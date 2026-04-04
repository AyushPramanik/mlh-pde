# MLH PE Hackathon — Flask + Peewee + PostgreSQL Template

A minimal hackathon starter template. You get the scaffolding and database wiring — you build the models, routes, and CSV loading logic.

**Stack:** Flask · Peewee ORM · PostgreSQL · uv

## Prerequisites

- **uv** — a fast Python package manager that handles Python versions, virtual environments, and dependencies automatically.
  Install it with:
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # Windows (PowerShell)
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
  For other methods see the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/).
- PostgreSQL running locally (you can use Docker or a local instance)

## uv Basics

`uv` manages your Python version, virtual environment, and dependencies automatically — no manual `python -m venv` needed.

| Command | What it does |
|---------|--------------|
| `uv sync` | Install all dependencies (creates `.venv` automatically) |
| `uv run <script>` | Run a script using the project's virtual environment |
| `uv add <package>` | Add a new dependency |
| `uv remove <package>` | Remove a dependency |

## Quick Start

```bash
# 1. Clone the repo
git clone <repo-url> && cd mlh-pe-hackathon

# 2. Install dependencies
uv sync

# 3. Create the database
createdb hackathon_db

# 4. Configure environment
cp .env.example .env   # edit if your DB credentials differ

# 5. Run the server
uv run run.py

# 6. Verify
curl http://localhost:5000/health
# → {"status":"ok"}
```

## Project Structure

```
mlh-pe-hackathon/
├── app/
│   ├── __init__.py          # App factory (create_app)
│   ├── database.py          # DatabaseProxy, BaseModel, connection hooks
│   ├── models/
│   │   └── __init__.py      # Import your models here
│   └── routes/
│       └── __init__.py      # register_routes() — add blueprints here
├── .env.example             # DB connection template
├── .gitignore               # Python + uv gitignore
├── .python-version          # Pin Python version for uv
├── pyproject.toml           # Project metadata + dependencies
├── run.py                   # Entry point: uv run run.py
└── README.md
```

## Error Handling

### 404 Not Found
Returned when a requested resource does not exist or is inactive.

| Scenario | Status |
|---|---|
| `GET /<short_code>` — code not in DB | 404 |
| `GET /<short_code>` — URL exists but `is_active=False` | 404 |
| `GET /urls/<id>` — ID not in DB | 404 |
| `PATCH /urls/<id>` — ID not in DB | 404 |
| `DELETE /urls/<id>` — ID not in DB | 404 |
| `GET /users/<id>` — ID not in DB | 404 |
| `GET /events/<id>` — ID not in DB | 404 |

All 404 responses return JSON: `{"error": "not found"}`

### 400 Bad Request
Returned when input fails validation before any DB operation is attempted.

| Scenario | Status |
|---|---|
| `POST /shorten` — missing `url` field | 400 `{"error": "url is required"}` |
| `POST /shorten` — empty, non-string, or non-http/https URL | 400 `{"error": "invalid url"}` |
| `PATCH /urls/<id>` — `original_url` fails URL validation | 400 `{"error": "invalid url"}` |
| `PATCH /urls/<id>` — `is_active` is not a boolean | 400 `{"error": "is_active must be a boolean"}` |
| `PATCH /urls/<id>` — no recognised fields in body | 400 `{"error": "no valid fields to update"}` |

### 500 Internal Server Error
Returned only in the rare case that short-code generation exhausts all retries due to collisions (5 attempts, probability effectively zero in practice).

Response: `{"error": "could not generate unique short code"}`

All other unhandled exceptions surface as Flask's default 500 response.

## Tips

- Use `model_to_dict` from `playhouse.shortcuts` to convert model instances to dictionaries for JSON responses.
- Wrap bulk inserts in `db.atomic()` for transactional safety and performance.
- The template uses `teardown_appcontext` for connection cleanup, so connections are closed even when requests fail.
- Check `.env.example` for all available configuration options.
