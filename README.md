# Rick and Morty — каталог персонажів

Flask-вебзастосунок для ознайомлення з персонажами серіалу **Rick and Morty** (варіант 7).
Дані беруться з публічного [Rick and Morty API](https://rickandmortyapi.com/), а обрані персонажі
зберігаються у локальній SQLite-базі, з якою можна працювати (пошук, фільтри, редагування, видалення, аналіз)
та через власний **REST API**.

## Можливості

- **Пошук** у зовнішньому API за іменем, статусом, видом і статтю (з пагінацією).
- Картка персонажа: ім'я, статус, вид, стать, походження, поточна локація, зображення.
- **Колекція** (локальна БД): збереження, перегляд, **редагування**, **видалення**.
- **Локальний пошук**, фільтрація за статусом/видом/статтю та сортування.
- **Аналіз** колекції з графіками `matplotlib` (статуси, види, епізоди).
- **Власний REST API** (`/api/characters`) з повним CRUD та JSON-помилками.
- Обробка помилок: порожній запит, некоректні параметри, відсутність результатів,
  недоступність зовнішнього API, неіснуючі локальні ресурси.
- Інтерфейс на Bootstrap 5 (темна тема).

## Структура

```
app.py          # Flask: веб-маршрути, REST API, обробники помилок
api_client.py   # запити до Rick and Morty API та перетворення даних
database.py     # схема SQLite, валідація, CRUD (python database.py - ініціалізація БД)
analytics.py    # підрахунки та графіки matplotlib
templates/      # HTML-шаблони (Jinja2 + Bootstrap)
static/         # CSS
tests/          # автотести (pytest)
postman/        # колекція Postman для перевірки REST API
```

## Запуск

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Відкрийте http://127.0.0.1:5000. Базу `characters.db` буде створено автоматично.
Тести: `python -m pytest -q`.

## Схема БД (таблиця `characters`)

| Поле | Тип | Обмеження |
|------|-----|-----------|
| `id` | INTEGER | **PRIMARY KEY**, AUTOINCREMENT |
| `external_id` | INTEGER | **UNIQUE**, NOT NULL, > 0 — id у зовнішньому API (захист від дублікатів) |
| `name`, `species` | TEXT | NOT NULL, не порожні |
| `status` | TEXT | NOT NULL, `Alive` / `Dead` / `unknown` |
| `gender` | TEXT | `Female` / `Male` / `Genderless` / `unknown` |
| `type`, `origin`, `location`, `image`, `note` | TEXT | значення за замовчуванням |
| `episode_count` | INTEGER | ≥ 0 |
| `saved_at` | TEXT | дата збереження (за замовчуванням — поточна) |

## REST API

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/api/characters?q=&status=&species=&gender=&sort=&order=&limit=&offset=` | список з пошуком, фільтрами, сортуванням |
| GET | `/api/characters/<id>` | один персонаж |
| POST | `/api/characters` | `{"external_id": 1}` — імпорт із зовнішнього API, або повний JSON (`external_id`, `name`, `status`, `species`, …) |
| PUT / PATCH | `/api/characters/<id>` | повне / часткове оновлення |
| DELETE | `/api/characters/<id>` | видалення (204) |
| GET | `/api/stats` | зведена статистика |

Коди помилок: `400` (невалідні дані/параметри), `404` (немає ресурсу), `405`, `409` (дублікат),
`503` (зовнішній API недоступний). Тіло помилки: `{"error": "...", "details": [...]}`.

Готова колекція запитів для Postman: `postman/rickandmorty.postman_collection.json`
(File → Import; змінна `base_url` = `http://127.0.0.1:5000`).

## Джерело даних

[rickandmortyapi.com](https://rickandmortyapi.com/documentation) — ендпоїнти `/character` (пошук) та `/character/{id}`.
