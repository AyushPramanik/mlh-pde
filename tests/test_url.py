from unittest.mock import MagicMock, patch

import pytest
from peewee import IntegrityError

from app import create_app
from app.models.url import URL
from app.routes.url import is_valid_url


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ---------------------------------------------------------------------------
# is_valid_url unit tests (pure function, no DB)
# ---------------------------------------------------------------------------

def test_valid_url_http():
    assert is_valid_url("http://example.com") is True


def test_valid_url_https():
    assert is_valid_url("https://example.com/path?q=1") is True


def test_invalid_url_empty():
    assert is_valid_url("") is False


def test_invalid_url_no_scheme():
    assert is_valid_url("example.com") is False


def test_invalid_url_wrong_scheme():
    assert is_valid_url("ftp://example.com") is False


def test_invalid_url_not_string():
    assert is_valid_url(123) is False


def test_invalid_url_whitespace():
    assert is_valid_url("   ") is False


# ---------------------------------------------------------------------------
# POST /urls
# ---------------------------------------------------------------------------

def test_create_url(client):
    mock_url = MagicMock()
    mock_url.id = 1
    mock_url.user_id = None
    mock_url.short_code = "abc123"
    mock_url.original_url = "https://example.com"
    mock_url.title = "Test"
    mock_url.is_active = True
    mock_url.created_at = "2024-01-01"
    mock_url.updated_at = "2024-01-01"

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.create", return_value=mock_url), \
         patch("app.routes.url.Event.create"):
        response = client.post("/urls", json={"original_url": "https://example.com", "title": "Test"})

    assert response.status_code == 201
    data = response.get_json()
    assert "short_code" in data
    assert data["original_url"] == "https://example.com"


def test_create_url_missing_field(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/urls", json={})
    assert response.status_code == 400


def test_create_url_invalid_url(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/urls", json={"original_url": "not-a-url"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /shorten (legacy)
# ---------------------------------------------------------------------------

def test_shorten_creates_url(client):
    mock_url = MagicMock()
    mock_url.id = 1
    mock_url.original_url = "https://example.com"

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.create", return_value=mock_url), \
         patch("app.routes.url.Event.create"):
        response = client.post("/shorten", json={"url": "https://example.com"})

    assert response.status_code == 201
    data = response.get_json()
    assert data["original_url"] == "https://example.com"
    assert "short_code" in data


def test_shorten_missing_url_field(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/shorten", json={})
    assert response.status_code == 400
    assert response.get_json()["error"] == "url is required"


def test_shorten_no_body(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/shorten")
    assert response.status_code == 400
    assert response.get_json()["error"] == "url is required"


def test_shorten_empty_url(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/shorten", json={"url": ""})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid url"


def test_shorten_invalid_url_format(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/shorten", json={"url": "not-a-url"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid url"


def test_shorten_retries_on_collision(client):
    mock_url = MagicMock()
    mock_url.id = 1
    mock_url.original_url = "https://example.com"
    calls = [IntegrityError, mock_url]

    def side_effect(**kwargs):
        result = calls.pop(0)
        if result is IntegrityError:
            raise IntegrityError()
        return result

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.create", side_effect=side_effect), \
         patch("app.routes.url.Event.create"):
        response = client.post("/shorten", json={"url": "https://example.com"})

    assert response.status_code == 201


# ---------------------------------------------------------------------------
# GET /<short_code>  — 302 redirect
# ---------------------------------------------------------------------------

def test_redirect_found(client):
    mock_url = MagicMock()
    mock_url.original_url = "https://example.com"

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get", return_value=mock_url):
        response = client.get("/abc123")

    assert response.status_code == 302
    assert response.headers["Location"] == "https://example.com"


def test_redirect_not_found(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get", side_effect=URL.DoesNotExist):
        response = client.get("/notfound")
    assert response.status_code == 404
    assert response.get_json()["error"] == "not found"


def test_redirect_inactive_url_returns_404(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get", side_effect=URL.DoesNotExist):
        response = client.get("/inactive1")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /urls/<id>
# ---------------------------------------------------------------------------

def _mock_url_obj(id=1, short_code="abc123", original_url="https://example.com",
                  title="Test", is_active=True, user_id=None):
    m = MagicMock()
    m.id = id
    m.user_id = user_id
    m.short_code = short_code
    m.original_url = original_url
    m.title = title
    m.is_active = is_active
    m.created_at = "2024-01-01"
    m.updated_at = "2024-01-01"
    return m


def test_update_url(client):
    mock_url = _mock_url_obj()

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get_by_id", return_value=mock_url), \
         patch("app.routes.url.URL.update") as mock_update, \
         patch("app.routes.url.Event.create"):
        mock_update.return_value.where.return_value.execute.return_value = 1
        response = client.put("/urls/1", json={"title": "New Title"})

    assert response.status_code == 200


def test_update_url_via_patch(client):
    mock_url = _mock_url_obj()

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get_by_id", return_value=mock_url), \
         patch("app.routes.url.URL.update") as mock_update, \
         patch("app.routes.url.Event.create"):
        mock_update.return_value.where.return_value.execute.return_value = 1
        response = client.patch("/urls/1", json={"title": "New Title"})

    assert response.status_code == 200


def test_update_url_not_found(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get_by_id", side_effect=URL.DoesNotExist):
        response = client.put("/urls/999", json={"title": "x"})
    assert response.status_code == 404


def test_update_url_invalid_url(client):
    mock_url = MagicMock()
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get_by_id", return_value=mock_url):
        response = client.put("/urls/1", json={"original_url": "bad-url"})
    assert response.status_code == 400


def test_update_url_invalid_is_active(client):
    mock_url = MagicMock()
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get_by_id", return_value=mock_url):
        response = client.put("/urls/1", json={"is_active": "yes"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /urls/<id>
# ---------------------------------------------------------------------------

def test_delete_url(client):
    mock_url = MagicMock()
    mock_url.short_code = "abc123"

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get_by_id", return_value=mock_url), \
         patch("app.routes.url.URL.update") as mock_update, \
         patch("app.routes.url.Event.create"):
        mock_update.return_value.where.return_value.execute.return_value = 1
        response = client.delete("/urls/1")

    assert response.status_code == 200
    assert response.get_json()["message"] == "deleted"


def test_delete_url_not_found(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get_by_id", side_effect=URL.DoesNotExist):
        response = client.delete("/urls/999")
    assert response.status_code == 404
