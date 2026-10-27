"""Модуль для отримання та перетворення даних із Rick and Morty API.

Документація: https://rickandmortyapi.com/documentation
"""
import os

import requests

# URL можна перевизначити змінною середовища (наприклад, для перевірки недоступності API)
BASE_URL = os.environ.get("RICKMORTY_API_URL", "https://rickandmortyapi.com/api")
TIMEOUT = 10  # секунд

# Допустимі значення фільтрів зовнішнього API
API_STATUSES = ("alive", "dead", "unknown")
API_GENDERS = ("female", "male", "genderless", "unknown")


class ExternalAPIError(Exception):
    """Зовнішній API недоступний або повернув неочікувану відповідь."""


class NoResultsError(Exception):
    """За запитом нічого не знайдено."""


class InvalidParametersError(ValueError):
    """Користувач передав некоректні параметри пошуку."""


def _get(url, params=None):
    """Виконує GET-запит і перетворює збої мережі у ExternalAPIError."""
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
    except requests.exceptions.Timeout as exc:
        raise ExternalAPIError("Зовнішній API не відповів вчасно. Спробуйте пізніше.") from exc
    except requests.exceptions.RequestException as exc:
        raise ExternalAPIError("Не вдалося з'єднатися із зовнішнім API.") from exc

    if response.status_code == 404:
        raise NoResultsError("Нічого не знайдено.")
    if response.status_code != 200:
        raise ExternalAPIError(f"Зовнішній API повернув помилку (HTTP {response.status_code}).")
    try:
        return response.json()
    except ValueError as exc:
        raise ExternalAPIError("Зовнішній API повернув некоректну відповідь.") from exc


def normalize_character(raw):
    """Перетворює сирий JSON персонажа у плоский словник для нашої БД."""
    return {
        "external_id": raw["id"],
        "name": raw.get("name") or "",
        "status": raw.get("status") or "unknown",
        "species": raw.get("species") or "unknown",
        "type": raw.get("type") or "",
        "gender": raw.get("gender") or "unknown",
        "origin": (raw.get("origin") or {}).get("name") or "unknown",
        "location": (raw.get("location") or {}).get("name") or "unknown",
        "image": raw.get("image") or "",
        "episode_count": len(raw.get("episode") or []),
    }


def search_characters(name="", status="", species="", gender="", page=1):
    """Шукає персонажів. Повертає {'results': [...], 'count', 'pages', 'page'}."""
    name, status = (name or "").strip(), (status or "").strip().lower()
    species, gender = (species or "").strip(), (gender or "").strip().lower()

    if not any((name, status, species, gender)):
        raise InvalidParametersError("Введіть хоча б один параметр пошуку.")
    if status and status not in API_STATUSES:
        raise InvalidParametersError(f"Некоректний статус. Допустимо: {', '.join(API_STATUSES)}.")
    if gender and gender not in API_GENDERS:
        raise InvalidParametersError(f"Некоректна стать. Допустимо: {', '.join(API_GENDERS)}.")
    try:
        page = int(page)
        if page < 1:
            raise ValueError
    except (TypeError, ValueError):
        raise InvalidParametersError("Номер сторінки має бути додатним цілим числом.")

    params = {"page": page}
    for key, value in (("name", name), ("status", status), ("species", species), ("gender", gender)):
        if value:
            params[key] = value

    data = _get(f"{BASE_URL}/character", params)
    return {
        "results": [normalize_character(r) for r in data.get("results", [])],
        "count": data.get("info", {}).get("count", 0),
        "pages": data.get("info", {}).get("pages", 1),
        "page": page,
    }


def get_character(external_id):
    """Отримує одного персонажа за id із зовнішнього API."""
    try:
        external_id = int(external_id)
        if external_id < 1:
            raise ValueError
    except (TypeError, ValueError):
        raise InvalidParametersError("Ідентифікатор персонажа має бути додатним цілим числом.")
    return normalize_character(_get(f"{BASE_URL}/character/{external_id}"))
