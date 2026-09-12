from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Alert, Machine
from app.services.machine_status import refresh_machine_statuses
from app.services.notifications import discord_payload


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


def test_user_can_acknowledge_an_active_alert() -> None:
    credentials = {"email": "operator@example.com", "password": "strong-password"}
    with TestClient(app) as client:
        access_token = client.post("/auth/register", json=credentials).json()["access_token"]
        authorization = {"Authorization": f"Bearer {access_token}"}
        enrollment = client.post("/machines", json={"name": "demo-node", "hostname": "demo-node.local"}, headers=authorization).json()
        client.post("/agent/telemetry", json={"cpu_percent": 95, "memory_percent": 50, "disk_percent": 20, "uptime_seconds": 100}, headers={"X-Machine-ID": enrollment["id"], "X-Agent-Token": enrollment["agent_token"]})
        alert_id = client.get("/alerts", headers=authorization).json()[0]["id"]
        acknowledged = client.post(f"/alerts/{alert_id}/acknowledge", headers=authorization)

    assert acknowledged.status_code == 200
    assert acknowledged.json()["state"] == "acknowledged"
    assert acknowledged.json()["acknowledged_at"]


def test_service_down_creates_and_resolves_an_alert() -> None:
    credentials = {"email": "operator@example.com", "password": "strong-password"}
    with TestClient(app) as client:
        access_token = client.post("/auth/register", json=credentials).json()["access_token"]
        authorization = {"Authorization": f"Bearer {access_token}"}
        enrollment = client.post("/machines", json={"name": "demo-node", "hostname": "demo-node.local"}, headers=authorization).json()
        client.post(f"/machines/{enrollment['id']}/services", json={"service_name": "nginx", "severity": "critical"}, headers=authorization)
        agent_headers = {"X-Machine-ID": enrollment["id"], "X-Agent-Token": enrollment["agent_token"]}
        client.post("/agent/telemetry", json={"cpu_percent": 10, "memory_percent": 20, "disk_percent": 30, "uptime_seconds": 100, "services": {"nginx": "stopped"}}, headers=agent_headers)
        active_alert = client.get("/alerts", headers=authorization).json()[0]
        client.post("/agent/telemetry", json={"cpu_percent": 10, "memory_percent": 20, "disk_percent": 30, "uptime_seconds": 101, "services": {"nginx": "running"}}, headers=agent_headers)
        resolved_alert = client.get("/alerts", headers=authorization).json()[0]

    assert active_alert["kind"] == "service"
    assert active_alert["state"] == "active"
    assert resolved_alert["state"] == "resolved"


def test_discord_payload_contains_alert_context() -> None:
    machine = Machine(id="machine-1", owner_id=1, name="api-prod-01", hostname="api-prod-01.local", agent_token_hash="hash")
    alert = Alert(id=7, machine_id="machine-1", kind="service", state="active", severity="critical", message="api-prod-01: service nginx is stopped")

    payload = discord_payload(alert, machine)

    assert payload["username"] == "PulseWatch"
    assert payload["embeds"][0]["fields"][0]["value"] == "api-prod-01"
