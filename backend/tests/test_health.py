import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_health_check_returns_service_status() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "pulsewatch-api"
    assert response.json()["database"] == "connected"


def test_user_can_register_and_log_in() -> None:
    credentials = {"email": "operator@example.com", "password": "strong-password"}
    with TestClient(app) as client:
        registration = client.post("/auth/register", json=credentials)
        login = client.post("/auth/login", json=credentials)

    assert registration.status_code == 201
    assert registration.json()["token_type"] == "bearer"
    assert login.status_code == 200
    assert login.json()["access_token"]
