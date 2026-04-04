from unittest.mock import MagicMock, patch

import pytest

from app import create_app
from app.models.url import URL


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


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


def test_shorten_missing_url(client):
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


def test_redirect_found(client):
    mock_url = MagicMock()
    mock_url.original_url = "https://example.com"

    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get", return_value=mock_url):
        response = client.get("/abc123")

    assert response.status_code == 200
    assert response.get_json()["original_url"] == "https://example.com"


def test_redirect_not_found(client):
    with patch("peewee.PostgresqlDatabase.connect"), \
         patch("peewee.PostgresqlDatabase.is_closed", return_value=True), \
         patch("app.routes.url.URL.get", side_effect=URL.DoesNotExist):
        response = client.get("/notfound")

    assert response.status_code == 404
    assert response.get_json()["error"] == "not found"
