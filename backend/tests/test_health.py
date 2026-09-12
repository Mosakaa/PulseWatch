from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Machine
from app.services.machine_status import refresh_machine_statuses


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


def test_authenticated_user_can_enroll_a_machine() -> None:
    credentials = {"email": "operator@example.com", "password": "strong-password"}
    with TestClient(app) as client:
        token = client.post("/auth/register", json=credentials).json()["access_token"]
        response = client.post("/machines", json={"name": "demo-node", "hostname": "demo-node.local"}, headers={"Authorization": f"Bearer {token}"})
        machines = client.get("/machines", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 201
    assert response.json()["agent_token"]
    assert machines.json()[0]["hostname"] == "demo-node.local"


def test_agent_can_submit_telemetry_for_an_enrolled_machine() -> None:
    credentials = {"email": "operator@example.com", "password": "strong-password"}
    with TestClient(app) as client:
        access_token = client.post("/auth/register", json=credentials).json()["access_token"]
        enrollment = client.post("/machines", json={"name": "demo-node", "hostname": "demo-node.local"}, headers={"Authorization": f"Bearer {access_token}"}).json()
        response = client.post("/agent/telemetry", json={"cpu_percent": 42, "memory_percent": 58, "disk_percent": 20, "network_bytes_sent": 10, "network_bytes_received": 11, "uptime_seconds": 100}, headers={"X-Machine-ID": enrollment["id"], "X-Agent-Token": enrollment["agent_token"]})
        history = client.get(f"/machines/{enrollment['id']}/telemetry", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 202
    assert history.json()[0]["cpu_percent"] == 42


def test_threshold_alert_is_created_and_resolved() -> None:
    credentials = {"email": "operator@example.com", "password": "strong-password"}
    headers: dict[str, str]
    with TestClient(app) as client:
        access_token = client.post("/auth/register", json=credentials).json()["access_token"]
        enrollment = client.post("/machines", json={"name": "demo-node", "hostname": "demo-node.local"}, headers={"Authorization": f"Bearer {access_token}"}).json()
        headers = {"X-Machine-ID": enrollment["id"], "X-Agent-Token": enrollment["agent_token"]}
        client.post("/agent/telemetry", json={"cpu_percent": 95, "memory_percent": 50, "disk_percent": 20, "uptime_seconds": 100}, headers=headers)
        active_alert = client.get("/alerts", headers={"Authorization": f"Bearer {access_token}"}).json()[0]
        client.post("/agent/telemetry", json={"cpu_percent": 30, "memory_percent": 50, "disk_percent": 20, "uptime_seconds": 101}, headers=headers)
        resolved_alert = client.get("/alerts", headers={"Authorization": f"Bearer {access_token}"}).json()[0]

    assert active_alert["state"] == "active"
    assert active_alert["kind"] == "threshold"
    assert resolved_alert["state"] == "resolved"


def test_machine_becomes_offline_when_heartbeat_expires() -> None:
    credentials = {"email": "operator@example.com", "password": "strong-password"}
    with TestClient(app) as client:
        access_token = client.post("/auth/register", json=credentials).json()["access_token"]
        enrollment = client.post("/machines", json={"name": "demo-node", "hostname": "demo-node.local"}, headers={"Authorization": f"Bearer {access_token}"}).json()
        client.post("/agent/heartbeat", headers={"X-Machine-ID": enrollment["id"], "X-Agent-Token": enrollment["agent_token"]})
        with SessionLocal() as session:
            machine = session.get(Machine, enrollment["id"])
            machine.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=61)
            refresh_machine_statuses(session)
            session.commit()
        machines = client.get("/machines", headers={"Authorization": f"Bearer {access_token}"}).json()
        alerts = client.get("/alerts", headers={"Authorization": f"Bearer {access_token}"}).json()

    assert machines[0]["status"] == "offline"
    assert alerts[0]["kind"] == "heartbeat"


def test_dashboard_receives_telemetry_events_over_websocket() -> None:
    credentials = {"email": "operator@example.com", "password": "strong-password"}
    with TestClient(app) as client:
        access_token = client.post("/auth/register", json=credentials).json()["access_token"]
        enrollment = client.post("/machines", json={"name": "demo-node", "hostname": "demo-node.local"}, headers={"Authorization": f"Bearer {access_token}"}).json()
        with client.websocket_connect(f"/ws/events?token={access_token}") as websocket:
            client.post("/agent/telemetry", json={"cpu_percent": 42, "memory_percent": 50, "disk_percent": 20, "uptime_seconds": 100}, headers={"X-Machine-ID": enrollment["id"], "X-Agent-Token": enrollment["agent_token"]})
            event = websocket.receive_json()

    assert event == {"type": "telemetry.received", "machine_id": enrollment["id"]}
