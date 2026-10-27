"""Робота з локальною базою даних SQLite: схема, валідація та CRUD.

Запуск `python database.py` створює (ініціалізує) порожню базу даних.

Таблиця characters:
    id            INTEGER PRIMARY KEY AUTOINCREMENT  - локальний первинний ключ
    external_id   INTEGER NOT NULL UNIQUE            - id персонажа у Rick and Morty API
    name          TEXT NOT NULL (не порожнє)
    status        TEXT NOT NULL, CHECK IN (Alive, Dead, unknown)
    species       TEXT NOT NULL
    type          TEXT
    gender        TEXT NOT NULL, CHECK IN (Female, Male, Genderless, unknown)
    origin        TEXT, location TEXT, image TEXT
    episode_count INTEGER >= 0
    note          TEXT  - власна нотатка користувача
    saved_at      TEXT  - дата збереження
"""
import os
import sqlite3
from contextlib import closing

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "characters.db")

STATUSES = ("Alive", "Dead", "unknown")
GENDERS = ("Female", "Male", "Genderless", "unknown")
SORT_FIELDS = ("id", "name", "status", "species", "saved_at", "episode_count")
TEXT_FIELDS = ("name", "species", "type", "origin", "location", "note")

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id   INTEGER NOT NULL UNIQUE CHECK (external_id > 0),
    name          TEXT NOT NULL CHECK (length(trim(name)) > 0),
    status        TEXT NOT NULL CHECK (status IN ('Alive', 'Dead', 'unknown')),
    species       TEXT NOT NULL CHECK (length(trim(species)) > 0),
    type          TEXT NOT NULL DEFAULT '',
    gender        TEXT NOT NULL DEFAULT 'unknown'
                  CHECK (gender IN ('Female', 'Male', 'Genderless', 'unknown')),
    origin        TEXT NOT NULL DEFAULT 'unknown',
    location      TEXT NOT NULL DEFAULT 'unknown',
    image         TEXT NOT NULL DEFAULT '',
    episode_count INTEGER NOT NULL DEFAULT 0 CHECK (episode_count >= 0),
    note          TEXT NOT NULL DEFAULT '',
    saved_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name);
"""


class ValidationError(ValueError):
    """Некоректні дані персонажа. Атрибут errors містить список повідомлень."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors))


class DuplicateError(Exception):
    """Персонаж з таким external_id уже збережений."""


def set_db_path(path):
    global DB_PATH
    DB_PATH = path


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with closing(get_connection()) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


# ---------------------------------------------------------------- валідація
def validate_character(data, partial=False):
    """Перевіряє і нормалізує дані. partial=True - для часткового оновлення (PATCH)."""
    if not isinstance(data, dict):
        raise ValidationError(["Тіло запиту має бути JSON-об'єктом."])
    errors, clean = [], {}

    if "external_id" in data:
        try:
            ext = int(data["external_id"])
            if ext < 1 or isinstance(data["external_id"], bool):
                raise ValueError
            clean["external_id"] = ext
        except (TypeError, ValueError):
            errors.append("external_id має бути додатним цілим числом.")
    elif not partial:
        errors.append("Поле external_id обов'язкове.")

    for field in TEXT_FIELDS:
        if field in data:
            value = data[field]
            if value is None:
                value = ""
            if not isinstance(value, str):
                errors.append(f"Поле {field} має бути рядком.")
                continue
            value = value.strip()
            if len(value) > (1000 if field == "note" else 200):
                errors.append(f"Поле {field} задовге.")
                continue
            clean[field] = value
    for field in ("name", "species"):
        if field in clean and not clean[field]:
            errors.append(f"Поле {field} не може бути порожнім.")
        elif field not in data and not partial:
            errors.append(f"Поле {field} обов'язкове.")

    for field, allowed in (("status", STATUSES), ("gender", GENDERS)):
        if field in data:
            match = {a.lower(): a for a in allowed}.get(str(data[field]).strip().lower())
            if match:
                clean[field] = match
            else:
                errors.append(f"Поле {field}: допустимі значення {', '.join(allowed)}.")
        elif field == "status" and not partial:
            errors.append("Поле status обов'язкове.")

    if "image" in data:
        image = (data["image"] or "").strip() if isinstance(data["image"], (str, type(None))) else None
        if image is None or (image and not image.startswith(("http://", "https://"))):
            errors.append("Поле image має бути URL (http/https) або порожнім.")
        else:
            clean["image"] = image

    if "episode_count" in data:
        try:
            count = int(data["episode_count"])
            if count < 0:
                raise ValueError
            clean["episode_count"] = count
        except (TypeError, ValueError):
            errors.append("episode_count має бути невід'ємним цілим числом.")

    if errors:
        raise ValidationError(errors)
    return clean


# --------------------------------------------------------------------- CRUD
def add_character(data):
    """CREATE. Повертає збережений запис (dict). Кидає ValidationError / DuplicateError."""
    clean = validate_character(data)
    columns = ", ".join(clean)
    placeholders = ", ".join("?" for _ in clean)
    with closing(get_connection()) as conn:
        try:
            cur = conn.execute(
                f"INSERT INTO characters ({columns}) VALUES ({placeholders})", list(clean.values())
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            if "external_id" in str(exc):
                raise DuplicateError("Цей персонаж уже збережений.") from exc
            raise ValidationError([f"Порушення обмежень цілісності: {exc}"]) from exc
        return get_character(cur.lastrowid)


def get_character(char_id):
    """READ (один запис). Повертає dict або None."""
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM characters WHERE id = ?", (char_id,)).fetchone()
    return dict(row) if row else None


def _escape_like(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_characters(q="", status="", species="", gender="", sort="id", order="asc",
                    limit=None, offset=0):
    """READ (список) з локальним пошуком, фільтрацією та сортуванням."""
    where, params = [], []
    if q and q.strip():
        like = f"%{_escape_like(q.strip())}%"
        where.append("(name LIKE ? ESCAPE '\\' OR origin LIKE ? ESCAPE '\\' "
                     "OR location LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\')")
        params += [like] * 4
    for column, value in (("status", status), ("species", species), ("gender", gender)):
        if value and value.strip():
            where.append(f"{column} = ? COLLATE NOCASE")
            params.append(value.strip())
    if sort not in SORT_FIELDS:
        raise ValidationError([f"Некоректне поле сортування. Допустимо: {', '.join(SORT_FIELDS)}."])
    if order not in ("asc", "desc"):
        raise ValidationError(["Некоректний порядок сортування. Допустимо: asc, desc."])

    sql = "SELECT * FROM characters"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {sort} {order.upper()}, id ASC"  # sort/order - з білого списку
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params += [int(limit), int(offset)]
    with closing(get_connection()) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def update_character(char_id, data, partial=True):
    """UPDATE. Повертає оновлений запис або None, якщо запису немає."""
    if get_character(char_id) is None:
        return None
    clean = validate_character(data, partial=partial)
    clean.pop("external_id", None)  # зовнішній ідентифікатор незмінний
    if clean:
        assignments = ", ".join(f"{k} = ?" for k in clean)
        with closing(get_connection()) as conn:
            try:
                conn.execute(f"UPDATE characters SET {assignments} WHERE id = ?",
                             list(clean.values()) + [char_id])
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValidationError([f"Порушення обмежень цілісності: {exc}"]) from exc
    return get_character(char_id)


def delete_character(char_id):
    """DELETE. Повертає True, якщо запис видалено."""
    with closing(get_connection()) as conn:
        cur = conn.execute("DELETE FROM characters WHERE id = ?", (char_id,))
        conn.commit()
        return cur.rowcount > 0


def saved_external_ids():
    """Множина external_id, які вже збережені (щоб позначати їх у результатах пошуку)."""
    with closing(get_connection()) as conn:
        return {r[0] for r in conn.execute("SELECT external_id FROM characters")}


def distinct_species():
    with closing(get_connection()) as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT species FROM characters ORDER BY species")]


if __name__ == "__main__":
    init_db()
    print(f"База даних ініціалізована: {DB_PATH}")
