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

All errors — including unhandled exceptions and database failures — go through the global `@app.errorhandler(500)` handler and return JSON, never an HTML stack trace.

---

## Failure Manual

Documents exactly what happens when things break in production.

### 1. Database connection lost mid-deployment
**What happens:** `before_request` calls `db.connect()`, which raises `peewee.OperationalError`.  
**App response:** Global 500 handler catches it → `{"error": "internal server error"}` with status 500.  
**Recovery:** Docker's `restart: always` restarts the container. Once the DB is reachable, subsequent requests succeed.

### 2. Database connection lost during a request
**What happens:** A DB query (e.g. `URL.create(...)`) raises `OperationalError` after the connection dropped mid-flight.  
**App response:** Flask catches the unhandled exception → 500 JSON response. The failed write is not committed (Peewee has no implicit transaction here — partial state is avoided because the DB rejected it).  
**Recovery:** Client retries; next request opens a fresh connection (`reuse_if_open=True`).

### 3. Short-code collision (duplicate `short_code`)
**What happens:** Two concurrent requests generate the same 6-character code. The second `URL.create()` raises `peewee.IntegrityError`.  
**App response:** Route retries up to 5 times with a new random code. If all 5 collide (probability ~1 in 10^28 for a non-full table), returns 500 `{"error": "could not generate unique short code"}`.  
**Recovery:** Client retries the `POST /shorten` request.

### 4. Request to unknown route or wrong HTTP method
**What happens:** Flask cannot match the route.  
**App response:** Global 404/405 handler returns JSON — never an HTML "Not Found" page.

### 5. Container crash (Chaos Mode)
**What happens:** The `web` process exits unexpectedly (OOM kill, segfault, `kill -9`).  
**App response:** Docker's `restart: always` policy detects the exit and restarts the container automatically, typically within 1–2 seconds.  
**To demonstrate:**
```bash
docker compose up -d
docker kill $(docker compose ps -q web)   # simulate crash
docker compose ps                          # web restarts automatically
curl http://localhost:5000/health          # {"status": "ok"}
```

### 6. Bad input from client
**What happens:** Client sends malformed JSON, missing fields, wrong types, or invalid URLs.  
**App response:** Validated at the route level before any DB operation. Returns 400 with a specific error message. The DB is never touched.

### 7. PostgreSQL container restarts (data persistence)
**What happens:** The `db` container restarts.  
**App response:** The `web` container retries connections on the next request. Data persists because the `postgres_data` Docker volume survives container restarts.

---

## Chaos Mode (Docker)

```bash
# Start the app and database
docker compose up -d

# Seed the database
docker compose exec web uv run python seed/seed.py

# Verify the app is running
curl http://localhost:5000/health

# Simulate a crash — Docker will restart the container automatically
docker kill $(docker compose ps -q web)

# Watch it come back
watch docker compose ps

# App is alive again
curl http://localhost:5000/health
```

`restart: always` in `docker-compose.yml` is what ensures automatic recovery. The `db` service also has `restart: always` so both tiers self-heal.

## Tips

- Use `model_to_dict` from `playhouse.shortcuts` to convert model instances to dictionaries for JSON responses.
- Wrap bulk inserts in `db.atomic()` for transactional safety and performance.
- The template uses `teardown_appcontext` for connection cleanup, so connections are closed even when requests fail.
- Check `.env.example` for all available configuration options.
