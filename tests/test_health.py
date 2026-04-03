import pytest
from unittest.mock import patch

from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health_check(client):
    with patch("peewee.PostgresqlDatabase.connect"), patch("peewee.PostgresqlDatabase.is_closed", return_value=True):
        response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
