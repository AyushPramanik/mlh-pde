"""
Integration tests — hit the full request pipeline with a real (SQLite) database.
These tests verify that routes correctly read from and write to the DB,
as opposed to unit tests which mock all DB calls.
"""
import pytest
from peewee import SqliteDatabase

from app import create_app
from app.database import db
from app.models.event import Event
from app.models.url import URL
from app.models.user import User


@pytest.fixture
def integration_client(tmp_path):
    """
    Flask test client backed by a real SQLite database.

    Strategy: create_app() initialises the DatabaseProxy with PostgreSQL config
    (no connection is made yet — only on first request). We immediately
    re-initialise the proxy with a file-based SQLite DB so every subsequent
    request uses SQLite instead.  File-based (not :memory:) is required because
    Peewee's teardown hook closes the connection after each request; file-based
    SQLite survives close/reopen cycles.
    """
    app = create_app()
    app.config["TESTING"] = True

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    db.initialize(test_db)

    with test_db:
        test_db.create_tables([User, URL, Event])

    with app.test_client() as client:
        yield client


# ---------------------------------------------------------------------------
# POST /shorten → DB record created
# ---------------------------------------------------------------------------

def test_shorten_writes_url_to_db(integration_client, tmp_path):
    response = integration_client.post("/shorten", json={"url": "https://example.com"})
    assert response.status_code == 201

    short_code = response.get_json()["short_code"]

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        url = URL.get(URL.short_code == short_code)
        assert url.original_url == "https://example.com"
        assert url.is_active == True


def test_shorten_logs_created_event(integration_client, tmp_path):
    integration_client.post("/shorten", json={"url": "https://example.com"})

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        events = list(Event.select())
        assert len(events) == 1
        assert events[0].event_type == "created"


def test_shorten_with_title_stores_title(integration_client, tmp_path):
    integration_client.post("/shorten", json={
        "url": "https://example.com",
        "title": "My Link",
    })

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        url = URL.select().first()
        assert url.title == "My Link"


# ---------------------------------------------------------------------------
# GET /<short_code> → resolves from DB
# ---------------------------------------------------------------------------

def test_resolve_returns_original_url(integration_client):
    resp = integration_client.post("/shorten", json={"url": "https://example.com"})
    short_code = resp.get_json()["short_code"]

    resp = integration_client.get(f"/{short_code}")
    assert resp.status_code == 200
    assert resp.get_json()["original_url"] == "https://example.com"


def test_resolve_unknown_code_returns_404(integration_client):
    resp = integration_client.get("/doesnotexist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /urls/<id> → sets is_active=False, blocks resolution
# ---------------------------------------------------------------------------

def test_delete_deactivates_url(integration_client, tmp_path):
    resp = integration_client.post("/shorten", json={"url": "https://example.com"})
    short_code = resp.get_json()["short_code"]

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        url_id = URL.get(URL.short_code == short_code).id

    integration_client.delete(f"/urls/{url_id}")

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        url = URL.get_by_id(url_id)
        assert url.is_active == False


def test_deleted_url_not_resolvable(integration_client, tmp_path):
    resp = integration_client.post("/shorten", json={"url": "https://example.com"})
    short_code = resp.get_json()["short_code"]

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        url_id = URL.get(URL.short_code == short_code).id

    integration_client.delete(f"/urls/{url_id}")

    resp = integration_client.get(f"/{short_code}")
    assert resp.status_code == 404


def test_delete_logs_deleted_event(integration_client, tmp_path):
    resp = integration_client.post("/shorten", json={"url": "https://example.com"})
    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        url_id = URL.select().first().id

    integration_client.delete(f"/urls/{url_id}")

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        types = [e.event_type for e in Event.select()]
        assert "deleted" in types


# ---------------------------------------------------------------------------
# PATCH /urls/<id> → updates DB record
# ---------------------------------------------------------------------------

def test_update_title(integration_client, tmp_path):
    integration_client.post("/shorten", json={"url": "https://example.com"})

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        url_id = URL.select().first().id

    resp = integration_client.patch(f"/urls/{url_id}", json={"title": "Updated"})
    assert resp.status_code == 200

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        assert URL.get_by_id(url_id).title == "Updated"


def test_update_logs_updated_event(integration_client, tmp_path):
    integration_client.post("/shorten", json={"url": "https://example.com"})

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        url_id = URL.select().first().id

    integration_client.patch(f"/urls/{url_id}", json={"title": "Updated"})

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        types = [e.event_type for e in Event.select()]
        assert "updated" in types


# ---------------------------------------------------------------------------
# Full flow: create → resolve → update → delete
# ---------------------------------------------------------------------------

def test_full_lifecycle(integration_client, tmp_path):
    # Create
    resp = integration_client.post("/shorten", json={
        "url": "https://example.com",
        "title": "Original",
    })
    assert resp.status_code == 201
    short_code = resp.get_json()["short_code"]

    # Resolve
    resp = integration_client.get(f"/{short_code}")
    assert resp.status_code == 200

    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        url_id = URL.get(URL.short_code == short_code).id

    # Update
    resp = integration_client.patch(f"/urls/{url_id}", json={"title": "Updated"})
    assert resp.status_code == 200

    # Delete
    resp = integration_client.delete(f"/urls/{url_id}")
    assert resp.status_code == 200

    # Resolve after delete — must 404
    resp = integration_client.get(f"/{short_code}")
    assert resp.status_code == 404

    # Check all three event types exist
    test_db = SqliteDatabase(str(tmp_path / "test.db"))
    with test_db:
        types = {e.event_type for e in Event.select()}
        assert types == {"created", "updated", "deleted"}
