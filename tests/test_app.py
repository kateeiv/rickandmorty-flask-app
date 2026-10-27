"""Автотести: CRUD, REST API та помилкові сценарії (зовнішній API підміняється)."""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_service  # noqa: E402
import database  # noqa: E402
from app import create_app  # noqa: E402

RICK_RAW = {
    "id": 1, "name": "Rick Sanchez", "status": "Alive", "species": "Human", "type": "",
    "gender": "Male", "origin": {"name": "Earth (C-137)"}, "location": {"name": "Citadel of Ricks"},
    "image": "https://rickandmortyapi.com/api/character/avatar/1.jpeg", "episode": ["e1", "e2", "e3"],
}


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def client(tmp_path):
    app = create_app({"DATABASE": str(tmp_path / "test.db"), "TESTING": True})
    return app.test_client()


@pytest.fixture
def fake_api(monkeypatch):
    """Підміна requests.get: повертає Рика для /character/1 та пошуку, 404 для решти."""
    def fake_get(url, params=None, timeout=None):
        if url.endswith("/character/1"):
            return FakeResponse(200, RICK_RAW)
        if url.endswith("/character") and params.get("name", "").lower() == "rick":
            return FakeResponse(200, {"info": {"count": 1, "pages": 1}, "results": [RICK_RAW]})
        return FakeResponse(404, {"error": "There is nothing here"})
    monkeypatch.setattr(api_service.requests, "get", fake_get)


def raise_error(exc):
    def _get(*args, **kwargs):
        raise exc
    return _get


# ------------------------------------------------------------ веб-інтерфейс
def test_index_without_query_shows_form(client):
    assert client.get("/").status_code == 200


def test_empty_search_is_rejected(client, fake_api):
    r = client.get("/?name=&status=&species=&gender=")
    assert r.status_code == 400
    assert "хоча б один параметр" in r.get_data(as_text=True)


def test_invalid_status_rejected(client, fake_api):
    assert client.get("/?status=happy").status_code == 400


def test_invalid_page_rejected(client, fake_api):
    assert client.get("/?name=rick&page=abc").status_code == 400


def test_search_success(client, fake_api):
    r = client.get("/?name=rick")
    assert r.status_code == 200 and "Rick Sanchez" in r.get_data(as_text=True)


def test_search_no_results(client, fake_api):
    r = client.get("/?name=zzzzzz")
    assert r.status_code == 200 and "нічого не знайдено" in r.get_data(as_text=True)


def test_external_api_down(client, monkeypatch):
    monkeypatch.setattr(api_service.requests, "get", raise_error(requests.exceptions.ConnectionError()))
    r = client.get("/?name=rick")
    assert r.status_code == 503 and "Не вдалося" in r.get_data(as_text=True)


def test_external_api_timeout(client, monkeypatch):
    monkeypatch.setattr(api_service.requests, "get", raise_error(requests.exceptions.Timeout()))
    assert client.get("/?name=rick").status_code == 503


def test_save_view_edit_delete_flow(client, fake_api):
    r = client.post("/save/1", follow_redirects=True)
    assert "збережено" in r.get_data(as_text=True)
    assert "Rick Sanchez" in client.get("/saved").get_data(as_text=True)

    # повторне збереження - дублікат
    assert "уже є" in client.post("/save/1", follow_redirects=True).get_data(as_text=True)

    r = client.post("/saved/1/edit", data={"name": "Rick C-137", "status": "Dead"}, follow_redirects=True)
    assert "Rick C-137" in r.get_data(as_text=True)

    assert client.post("/saved/1/edit", data={"name": "  "}).status_code == 400
    assert client.post("/saved/1/edit", data={"status": "Zombie"}).status_code == 400

    client.post("/saved/1/delete")
    assert client.get("/saved/1").status_code == 404


def test_local_not_found_pages(client):
    assert client.get("/saved/999").status_code == 404
    assert client.get("/saved/999/edit").status_code == 404
    assert client.get("/nonexistent").status_code == 404
    assert "не існує" in client.post("/saved/999/delete", follow_redirects=True).get_data(as_text=True)


def test_saved_filters_and_bad_sort(client):
    database.add_character({"external_id": 1, "name": "Rick", "status": "Alive", "species": "Human"})
    database.add_character({"external_id": 2, "name": "Birdperson", "status": "Dead", "species": "Alien"})
    assert "Birdperson" not in client.get("/saved?status=Alive").get_data(as_text=True)
    assert "Birdperson" in client.get("/saved?q=bird").get_data(as_text=True)
    assert client.get("/saved?sort=DROP").status_code == 400


def test_stats_page(client):
    assert client.get("/stats").status_code == 200
    database.add_character({"external_id": 1, "name": "Rick", "status": "Alive", "species": "Human"})
    assert "data:image/png;base64" in client.get("/stats").get_data(as_text=True)


# ------------------------------------------------------------------ REST API
def test_api_crud(client):
    body = {"external_id": 5, "name": "Jerry", "status": "alive", "species": "Human"}
    r = client.post("/api/characters", json=body)
    assert r.status_code == 201 and r.json["status"] == "Alive"
    cid = r.json["id"]

    assert client.post("/api/characters", json=body).status_code == 409
    assert client.get(f"/api/characters/{cid}").json["name"] == "Jerry"
    assert client.get("/api/characters?q=jer").json["count"] == 1

    r = client.patch(f"/api/characters/{cid}", json={"note": "Loser"})
    assert r.status_code == 200 and r.json["note"] == "Loser"
    r = client.put(f"/api/characters/{cid}", json={"name": "Jerry S.", "status": "Alive", "species": "Human"})
    assert r.status_code == 200 and r.json["name"] == "Jerry S."

    assert client.delete(f"/api/characters/{cid}").status_code == 204
    assert client.delete(f"/api/characters/{cid}").status_code == 404


def test_api_import_by_external_id(client, fake_api):
    r = client.post("/api/characters", json={"external_id": 1})
    assert r.status_code == 201 and r.json["name"] == "Rick Sanchez"
    assert client.post("/api/characters", json={"external_id": 9999}).status_code == 404


def test_api_import_when_external_down(client, monkeypatch):
    monkeypatch.setattr(api_service.requests, "get", raise_error(requests.exceptions.ConnectionError()))
    assert client.post("/api/characters", json={"external_id": 1}).status_code == 503


def test_api_errors_are_json(client):
    assert client.get("/api/characters/999").status_code == 404
    assert client.get("/api/characters/999").json["error"]
    assert client.get("/api/unknown").status_code == 404
    assert client.get("/api/unknown").is_json
    assert client.put("/api/characters/999", json={"name": "x", "status": "Alive", "species": "y"}).status_code == 404
    assert client.open("/api/characters", method="DELETE").status_code == 405
    assert client.post("/api/characters", data="not json").status_code == 400
    assert client.post("/api/characters", json={"name": ""}).status_code == 400
    assert client.post("/api/characters", json={"external_id": 1, "name": "A", "status": "x",
                                                "species": "H"}).status_code == 400
    assert client.get("/api/characters?limit=abc").status_code == 400
    assert client.get("/api/characters?sort=bogus").status_code == 400


def test_api_stats(client):
    database.add_character({"external_id": 1, "name": "Rick", "status": "Alive", "species": "Human"})
    assert client.get("/api/stats").json["total"] == 1


def test_database_constraints(client):
    with pytest.raises(database.ValidationError):
        database.add_character({"external_id": 1, "name": "x", "status": "Alive", "species": "y",
                                "image": "javascript:alert(1)"})
    assert database.get_character(12345) is None
    assert database.update_character(12345, {"name": "x"}) is None


def test_local_search_treats_wildcards_literally(client):
    database.add_character({"external_id": 1, "name": "Rick", "status": "Alive", "species": "Human"})
    assert database.list_characters(q="%") == []
    assert database.list_characters(q="' OR 1=1 --") == []
    assert len(database.list_characters(q="ric")) == 1
    assert len(database.list_characters(limit=1, offset=0)) == 1
    assert database.list_characters(limit=1, offset=1) == []
