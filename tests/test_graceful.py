"""
Graceful failure tests — verify the app returns clean JSON for every error
condition rather than crashing or returning HTML stack traces.
Also covers the events and users routes.
"""
from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.models.event import Event
from app.models.user import User


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_unknown_route_returns_json_404(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.get("/this/route/does/not/exist")
    assert response.status_code == 404
    assert response.is_json
    assert response.get_json()["error"] == "not found"


def test_wrong_method_returns_json_405(client):
    # /health only accepts GET; before_request still fires so DB must be mocked
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/health")
    assert response.status_code == 405
    assert response.is_json
    assert response.get_json()["error"] == "method not allowed"


def test_db_failure_returns_json_500():
    """Simulate a DB crash — must return JSON 500, not an HTML traceback.
    Uses PROPAGATE_EXCEPTIONS=False so Flask routes the error through our handler
    (TESTING=True would otherwise re-raise it directly to the test).
    """
    from peewee import OperationalError

    app = create_app()
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = False

    with app.test_client() as c:
        with patch("peewee.PostgresqlDatabase.connect", side_effect=OperationalError("connection refused")):
            response = c.get("/health")

    assert response.status_code == 500
    assert response.is_json
    assert response.get_json()["error"] == "internal server error"


def test_list_users_returns_list(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.select") as mock_select:
        mock_select.return_value.order_by.return_value.dicts.return_value = [
            {"id": 1, "username": "alice", "email": "alice@example.com"}
        ]
        response = client.get("/users")

    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


def test_get_user_found(client):
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "alice"
    mock_user.email = "alice@example.com"
    mock_user.created_at = "2024-01-01"

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.get_by_id", return_value=mock_user):
        response = client.get("/users/1")

    assert response.status_code == 200
    data = response.get_json()
    assert data["username"] == "alice"
    assert data["email"] == "alice@example.com"


def test_get_user_not_found(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.get_by_id", side_effect=User.DoesNotExist):
        response = client.get("/users/999")

    assert response.status_code == 404
    assert response.get_json()["error"] == "user not found"


def test_get_user_urls_found(client):
    mock_user = MagicMock()
    mock_user.urls.dicts.return_value = [
        {"id": 1, "short_code": "abc123", "original_url": "https://example.com"}
    ]

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.get_by_id", return_value=mock_user):
        response = client.get("/users/1/urls")

    assert response.status_code == 200
    assert isinstance(response.get_json(), list)


def test_get_user_urls_user_not_found(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.get_by_id", side_effect=User.DoesNotExist):
        response = client.get("/users/999/urls")

    assert response.status_code == 404


def test_create_user(client):
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "alice"
    mock_user.email = "alice@example.com"
    mock_user.created_at = "2024-01-01"

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.create", return_value=mock_user):
        response = client.post("/users", json={"username": "alice", "email": "alice@example.com"})

    assert response.status_code == 201
    assert response.get_json()["username"] == "alice"

def test_create_user_missing_fields(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/users", json={"username": "alice"})
    assert response.status_code == 400

def test_update_user(client):
    mock_user = MagicMock()
    mock_user.id = 1
    mock_user.username = "updated"
    mock_user.email = "alice@example.com"
    mock_user.created_at = "2024-01-01"

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.get_by_id", return_value=mock_user), \
         patch("app.routes.users.User.update") as mock_update:
        mock_update.return_value.where.return_value.execute.return_value = 1
        response = client.put("/users/1", json={"username": "updated"})

    assert response.status_code == 200

def test_update_user_not_found(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.get_by_id", side_effect=User.DoesNotExist):
        response = client.put("/users/999", json={"username": "x"})
    assert response.status_code == 404

def test_delete_user(client):
    mock_user = MagicMock()
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.get_by_id", return_value=mock_user):
        response = client.delete("/users/1")
    assert response.status_code == 200
    assert response.get_json()["message"] == "deleted"

def test_delete_user_not_found(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.users.User.get_by_id", side_effect=User.DoesNotExist):
        response = client.delete("/users/999")
    assert response.status_code == 404

def test_list_events_returns_list(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.events.Event.select") as mock_select:
        mock_select.return_value.dicts.return_value = []
        response = client.get("/events/")

    assert response.status_code == 200
    assert isinstance(response.get_json(), list)

def test_get_event_found(client):
    mock_event = MagicMock()
    mock_event.id = 1
    mock_event.url_id = 1
    mock_event.user_id = None
    mock_event.event_type = "created"
    mock_event.timestamp = "2024-01-01"
    mock_event.details = "{}"

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.events.Event.get_by_id", return_value=mock_event):
        response = client.get("/events/1")

    assert response.status_code == 200
    assert response.get_json()["event_type"] == "created"

def test_get_event_not_found(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.events.Event.get_by_id", side_effect=Event.DoesNotExist):
        response = client.get("/events/999")

    assert response.status_code == 404
    assert response.get_json()["error"] == "not found"


def test_shorten_with_ftp_url_returns_400(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/shorten", json={"url": "ftp://files.example.com"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid url"

def test_shorten_with_numeric_url_returns_400(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.post("/shorten", json={"url": 12345})

    assert response.status_code == 400

def test_patch_url_no_valid_fields(client):
    mock_url = MagicMock()
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get_by_id", return_value=mock_url):
        response = client.patch("/urls/1", json={"unknown_field": "value"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "no valid fields to update"
