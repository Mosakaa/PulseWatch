"""Exercise a complete PulseWatch resilience scenario against a running API."""

import argparse
import os
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
from telemetry_buffer import TelemetryBuffer, flush_buffer


@dataclass
class SimulatedMachine:
    id: str
    name: str
    agent_token: str


def api_request(client: httpx.Client, method: str, path: str, **kwargs) -> dict | list:
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


def authenticate(client: httpx.Client, email: str, password: str) -> str:
    credentials = {"email": email, "password": password}
    response = client.post("/auth/login", json=credentials)
    if response.status_code == 401:
        response = client.post("/auth/register", json=credentials)
    response.raise_for_status()
    return response.json()["access_token"]


def enroll_machine(client: httpx.Client, token: str, name: str) -> SimulatedMachine:
    enrollment = api_request(
        client,
        "POST",
        "/machines",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "hostname": f"{name}.pulsewatch.demo"},
    )
    return SimulatedMachine(enrollment["id"], name, enrollment["agent_token"])


def configure_cpu_rule(client: httpx.Client, token: str, machine_id: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    rules = api_request(client, "GET", f"/machines/{machine_id}/rules", headers=headers)
    cpu_rule = next(rule for rule in rules if rule["metric"] == "cpu_percent")
    api_request(
        client,
        "PUT",
        f"/alert-rules/{cpu_rule['id']}",
        headers=headers,
        json={"threshold": 90, "duration_seconds": 0, "severity": "critical", "enabled": True},
    )


def telemetry_payload(*, cpu_percent: float, services: dict[str, str] | None = None) -> dict[str, object]:
    return {
        "cpu_percent": cpu_percent,
        "memory_percent": 42,
        "disk_percent": 35,
        "network_bytes_sent": 1024,
        "network_bytes_received": 2048,
        "uptime_seconds": 86400,
        "services": services or {},
    }


def send_telemetry(client: httpx.Client, machine: SimulatedMachine, payload: dict[str, object]) -> None:
    api_request(
        client,
        "POST",
        "/agent/telemetry",
        headers={"X-Machine-ID": machine.id, "X-Agent-Token": machine.agent_token},
        json=payload,
    )


def send_heartbeat(client: httpx.Client, machine: SimulatedMachine) -> None:
    api_request(
        client,
        "POST",
        "/agent/heartbeat",
        headers={"X-Machine-ID": machine.id, "X-Agent-Token": machine.agent_token},
    )


def alerts_for_machine(client: httpx.Client, token: str, machine_id: str) -> list[dict]:
    alerts = api_request(client, "GET", "/alerts", headers={"Authorization": f"Bearer {token}"})
    return [alert for alert in alerts if alert["machine_id"] == machine_id]


def print_alerts(client: httpx.Client, token: str, machine: SimulatedMachine) -> list[dict]:
    alerts = alerts_for_machine(client, token, machine.id)
    for alert in alerts:
        print(f"  {alert['state'].upper():12} {alert['kind']:10} {alert['message']}")
    return alerts


def acknowledge_active_alert(client: httpx.Client, token: str, machine: SimulatedMachine, kind: str) -> None:
    alert = next(
        alert
        for alert in alerts_for_machine(client, token, machine.id)
        if alert["kind"] == kind and alert["state"] == "active"
    )
    api_request(
        client,
        "POST",
        f"/alerts/{alert['id']}/acknowledge",
        headers={"Authorization": f"Bearer {token}"},
    )
    print(f"Acknowledged {kind} incident for {machine.name}.")


def demonstrate_buffer_recovery(client: httpx.Client, machine: SimulatedMachine) -> None:
    with tempfile.TemporaryDirectory(prefix="pulsewatch-demo-") as directory:
        buffer = TelemetryBuffer(Path(directory) / "telemetry.db", max_rows=10)
        buffer.enqueue(telemetry_payload(cpu_percent=31, services={"nginx": "running"}))
        buffer.enqueue(telemetry_payload(cpu_percent=34, services={"nginx": "running"}))
        print("Simulating a disconnected agent with 2 buffered telemetry samples...")

        def unavailable(_: dict[str, object]) -> None:
            raise httpx.ConnectError("simulated network outage")

        if flush_buffer(buffer, unavailable) != 0:
            raise RuntimeError("Telemetry unexpectedly submitted while the simulated network was unavailable")
        submitted = flush_buffer(buffer, lambda payload: send_telemetry(client, machine, payload))
        if submitted != 2:
            raise RuntimeError(f"Expected 2 buffered samples to replay, got {submitted}")
        print(f"Connectivity restored; replayed {submitted} queued samples for {machine.name}.")
        buffer.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("PULSEWATCH_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--email", default=os.getenv("PULSEWATCH_DEMO_EMAIL", f"demo-{uuid.uuid4().hex[:8]}@pulsewatch.local"))
    parser.add_argument("--password", default=os.getenv("PULSEWATCH_DEMO_PASSWORD", "pulsewatch-demo-password"))
    parser.add_argument("--heartbeat-wait-seconds", type=int, default=65, help="Seconds to wait before checking the intentional heartbeat outage.")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=10) as client:
        token = authenticate(client, args.email, args.password)
        machines = [
            enroll_machine(client, token, name)
            for name in ("api-demo-01", "worker-demo-01", "cache-demo-01")
        ]
        primary = machines[0]
        print(f"Enrolled {len(machines)} simulated machines: {', '.join(machine.name for machine in machines)}")

        for machine in machines:
            configure_cpu_rule(client, token, machine.id)
            send_heartbeat(client, machine)
            send_telemetry(client, machine, telemetry_payload(cpu_percent=25, services={"nginx": "running"}))
        print("All simulated machines are online.")

        print(f"Triggering CPU threshold on {primary.name}...")
        send_telemetry(client, primary, telemetry_payload(cpu_percent=95, services={"nginx": "running"}))
        print_alerts(client, token, primary)
        acknowledge_active_alert(client, token, primary, "threshold")
        send_telemetry(client, primary, telemetry_payload(cpu_percent=25, services={"nginx": "running"}))
        print("CPU recovered and the acknowledged incident resolved.")

        api_request(client, "POST", f"/machines/{primary.id}/services", headers={"Authorization": f"Bearer {token}"}, json={"service_name": "nginx", "severity": "critical"})
        print(f"Simulating nginx stopped on {primary.name}...")
        send_telemetry(client, primary, telemetry_payload(cpu_percent=25, services={"nginx": "stopped"}))
        print_alerts(client, token, primary)
        send_telemetry(client, primary, telemetry_payload(cpu_percent=25, services={"nginx": "running"}))
        print("nginx recovered and the service incident resolved.")

        demonstrate_buffer_recovery(client, machines[1])

        offline_machine = machines[2]
        print(f"Stopping heartbeats for {offline_machine.name}; waiting {args.heartbeat_wait_seconds} seconds...")
        time.sleep(max(0, args.heartbeat_wait_seconds))
        api_request(client, "GET", "/machines", headers={"Authorization": f"Bearer {token}"})
        print_alerts(client, token, offline_machine)
        heartbeat_alert = next(
            (alert for alert in alerts_for_machine(client, token, offline_machine.id) if alert["kind"] == "heartbeat" and alert["state"] == "active"),
            None,
        )
        if args.heartbeat_wait_seconds >= 60 and heartbeat_alert is None:
            raise RuntimeError("Expected an active heartbeat incident after the intentional outage")
        send_heartbeat(client, offline_machine)
        if heartbeat_alert is not None:
            resolved_alert = next(
                alert
                for alert in alerts_for_machine(client, token, offline_machine.id)
                if alert["id"] == heartbeat_alert["id"]
            )
            if resolved_alert["state"] != "resolved":
                raise RuntimeError("Heartbeat incident did not resolve after agent recovery")
        print("Heartbeat restored and the offline incident resolved.")
        print("Resilience demo complete. Inspect the dashboard and Discord channel for the full alert history.")


if __name__ == "__main__":
    main()
