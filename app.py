"""Flask-застосунок: веб-інтерфейс (пошук, збережені персонажі, аналіз) і власний REST API."""
import os

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

import analytics
import api_client
import database
from api_client import ExternalAPIError, InvalidParametersError, NoResultsError
from database import DuplicateError, ValidationError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        DATABASE=os.path.join(BASE_DIR, "characters.db"),
    )
    app.json.ensure_ascii = False  # кирилиця у JSON-відповідях читабельна
    if config:
        app.config.update(config)
    database.set_db_path(app.config["DATABASE"])
    database.init_db()

    register_web_routes(app)
    register_api_routes(app)
    register_error_handlers(app)
    return app


def _is_api_request():
    return request.path.startswith("/api/") or request.path == "/api"


def _json_error(message, status, details=None):
    body = {"error": message}
    if details:
        body["details"] = details
    return jsonify(body), status


# ======================================================================
#  Веб-інтерфейс
# ======================================================================
def register_web_routes(app):
    @app.template_filter("status_class")
    def status_class(status):
        return {"Alive": "success", "Dead": "danger"}.get(status, "secondary")

    @app.route("/")
    def index():
        """Пошук персонажів у зовнішньому API."""
        fields = {k: request.args.get(k, "") for k in ("name", "status", "species", "gender")}
        context = {"fields": fields, "results": None, "saved_ids": database.saved_external_ids()}

        submitted = any(k in request.args for k in fields)
        if not submitted:
            return render_template("index.html", **context)

        try:
            data = api_client.search_characters(page=request.args.get("page", 1), **fields)
        except InvalidParametersError as exc:
            flash(str(exc), "warning")
            return render_template("index.html", **context), 400
        except NoResultsError:
            flash("За вашим запитом нічого не знайдено. Спробуйте змінити параметри.", "info")
            context["results"] = []
            return render_template("index.html", **context)
        except ExternalAPIError as exc:
            flash(str(exc), "danger")
            return render_template("index.html", **context), 503

        context.update(
            results=data["results"], count=data["count"], page=data["page"], pages=data["pages"],
            query_args={k: v for k, v in fields.items() if v.strip()},
        )
        return render_template("index.html", **context)

    @app.route("/save/<int:external_id>", methods=["POST"])
    def save(external_id):
        """Зберігає персонажа із зовнішнього API у локальну БД."""
        target = request.form.get("next") or url_for("index")
        if not target.startswith("/"):  # захист від open redirect
            target = url_for("index")
        try:
            character = api_client.get_character(external_id)
            database.add_character(character)
            flash(f"«{character['name']}» збережено до колекції.", "success")
        except NoResultsError:
            flash("Такого персонажа не існує у зовнішньому API.", "warning")
        except InvalidParametersError as exc:
            flash(str(exc), "warning")
        except ExternalAPIError as exc:
            flash(str(exc), "danger")
        except DuplicateError:
            flash("Цей персонаж уже є у вашій колекції.", "info")
        except ValidationError as exc:
            flash("Не вдалося зберегти: " + "; ".join(exc.errors), "danger")
        return redirect(target)

    @app.route("/saved")
    def saved():
        """Локальний список з пошуком, фільтрами та сортуванням."""
        filters = {k: request.args.get(k, "") for k in ("q", "status", "species", "gender")}
        sort, order = request.args.get("sort", "id"), request.args.get("order", "asc")
        try:
            characters = database.list_characters(sort=sort, order=order, **filters)
            status = 200
        except ValidationError as exc:
            flash("; ".join(exc.errors), "warning")
            characters, status = [], 400
        return render_template(
            "saved.html", characters=characters, filters=filters, sort=sort, order=order,
            species_list=database.distinct_species(), statuses=database.STATUSES,
            genders=database.GENDERS, sort_fields=database.SORT_FIELDS,
        ), status

    @app.route("/saved/<int:char_id>")
    def detail(char_id):
        character = database.get_character(char_id)
        if character is None:
            return render_template("error.html", code=404,
                                   message="Збереженого персонажа з таким ідентифікатором не існує."), 404
        return render_template("detail.html", c=character)

    @app.route("/saved/<int:char_id>/edit", methods=["GET", "POST"])
    def edit(char_id):
        character = database.get_character(char_id)
        if character is None:
            return render_template("error.html", code=404,
                                   message="Неможливо редагувати: запису не існує."), 404
        if request.method == "POST":
            form = {k: v for k, v in request.form.items() if k != "external_id"}
            try:
                database.update_character(char_id, form, partial=True)
            except ValidationError as exc:
                for message in exc.errors:
                    flash(message, "danger")
                return render_template("edit.html", c={**character, **form},
                                       statuses=database.STATUSES, genders=database.GENDERS), 400
            flash("Зміни збережено.", "success")
            return redirect(url_for("detail", char_id=char_id))
        return render_template("edit.html", c=character, statuses=database.STATUSES,
                               genders=database.GENDERS)

    @app.route("/saved/<int:char_id>/delete", methods=["POST"])
    def delete(char_id):
        if database.delete_character(char_id):
            flash("Персонажа видалено з колекції.", "success")
        else:
            flash("Такого запису не існує - можливо, його вже видалено.", "warning")
        return redirect(url_for("saved"))

    @app.route("/stats")
    def stats():
        characters = database.list_characters()
        return render_template("stats.html", summary=analytics.summary(characters),
                               charts=analytics.build_charts(characters))


# ======================================================================
#  REST API
# ======================================================================
def register_api_routes(app):
    @app.route("/api/characters", methods=["GET"])
    def api_list():
        """GET /api/characters?q=&status=&species=&gender=&sort=&order=&limit=&offset="""
        try:
            limit = int(request.args.get("limit", 50))
            offset = int(request.args.get("offset", 0))
            if limit < 1 or limit > 200 or offset < 0:
                raise ValueError
        except ValueError:
            return _json_error("limit має бути 1..200, offset - невід'ємне ціле число.", 400)
        try:
            items = database.list_characters(
                q=request.args.get("q", ""), status=request.args.get("status", ""),
                species=request.args.get("species", ""), gender=request.args.get("gender", ""),
                sort=request.args.get("sort", "id"), order=request.args.get("order", "asc"),
                limit=limit, offset=offset,
            )
        except ValidationError as exc:
            return _json_error("Некоректні параметри запиту.", 400, exc.errors)
        return jsonify({"count": len(items), "limit": limit, "offset": offset, "results": items})

    @app.route("/api/characters/<int:char_id>", methods=["GET"])
    def api_get(char_id):
        character = database.get_character(char_id)
        if character is None:
            return _json_error(f"Персонажа з id={char_id} не знайдено.", 404)
        return jsonify(character)

    @app.route("/api/characters", methods=["POST"])
    def api_create():
        """Створення запису. Якщо передано лише external_id - дані беруться із зовнішнього API."""
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _json_error("Очікується JSON-об'єкт (Content-Type: application/json).", 400)
        try:
            if set(data) == {"external_id"}:
                data = api_client.get_character(data["external_id"])
            character = database.add_character(data)
        except ValidationError as exc:
            return _json_error("Помилка валідації.", 400, exc.errors)
        except InvalidParametersError as exc:
            return _json_error(str(exc), 400)
        except NoResultsError:
            return _json_error("Персонажа з таким external_id не існує у зовнішньому API.", 404)
        except ExternalAPIError as exc:
            return _json_error(str(exc), 503)
        except DuplicateError as exc:
            return _json_error(str(exc), 409)
        response = jsonify(character)
        response.status_code = 201
        response.headers["Location"] = url_for("api_get", char_id=character["id"])
        return response

    @app.route("/api/characters/<int:char_id>", methods=["PUT", "PATCH"])
    def api_update(char_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _json_error("Очікується JSON-об'єкт (Content-Type: application/json).", 400)
        try:
            # PUT вимагає повного набору обов'язкових полів (крім незмінного external_id)
            if request.method == "PUT":
                database.validate_character({**data, "external_id": 1})
            character = database.update_character(char_id, data, partial=True)
        except ValidationError as exc:
            return _json_error("Помилка валідації.", 400, exc.errors)
        if character is None:
            return _json_error(f"Персонажа з id={char_id} не знайдено.", 404)
        return jsonify(character)

    @app.route("/api/characters/<int:char_id>", methods=["DELETE"])
    def api_delete(char_id):
        if not database.delete_character(char_id):
            return _json_error(f"Персонажа з id={char_id} не знайдено.", 404)
        return "", 204

    @app.route("/api/stats", methods=["GET"])
    def api_stats():
        return jsonify(analytics.summary(database.list_characters()))


# ======================================================================
#  Обробники помилок
# ======================================================================
def register_error_handlers(app):
    messages = {
        404: "Сторінку або ресурс не знайдено.",
        405: "Цей метод не підтримується для даної адреси.",
        500: "Внутрішня помилка сервера.",
    }

    def handler(error):
        code = getattr(error, "code", 500)
        if code not in messages:
            code = 500
        if _is_api_request():
            return _json_error(messages[code], code)
        return render_template("error.html", code=code, message=messages[code]), code

    for code in messages:
        app.register_error_handler(code, handler)


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")
