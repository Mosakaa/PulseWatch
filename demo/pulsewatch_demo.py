"""Create repeatable PulseWatch incidents against a local or deployed API."""

import argparse
import os
import uuid

import httpx


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


def send_telemetry(client: httpx.Client, machine_id: str, agent_token: str, *, cpu_percent: float, services: dict[str, str] | None = None) -> None:
    api_request(
        client,
        "POST",
        "/agent/telemetry",
        headers={"X-Machine-ID": machine_id, "X-Agent-Token": agent_token},
        json={
            "cpu_percent": cpu_percent,
            "memory_percent": 42,
            "disk_percent": 35,
            "network_bytes_sent": 1024,
            "network_bytes_received": 2048,
            "uptime_seconds": 86400,
            "services": services or {},
        },
    )


def print_alerts(client: httpx.Client, token: str) -> None:
    alerts = api_request(client, "GET", "/alerts", headers={"Authorization": f"Bearer {token}"})
    for alert in alerts[:5]:
        print(f"{alert['state'].upper():12} {alert['kind']:10} {alert['message']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("PULSEWATCH_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--scenario", choices=("cpu", "service", "all"), default="all")
    parser.add_argument("--email", default=os.getenv("PULSEWATCH_DEMO_EMAIL", f"demo-{uuid.uuid4().hex[:8]}@pulsewatch.local"))
    parser.add_argument("--password", default=os.getenv("PULSEWATCH_DEMO_PASSWORD", "pulsewatch-demo-password"))
    args = parser.parse_args()

    with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=10) as client:
        token = authenticate(client, args.email, args.password)
        headers = {"Authorization": f"Bearer {token}"}
        enrollment = api_request(
            client,
            "POST",
            "/machines",
            headers=headers,
            json={"name": f"demo-node-{uuid.uuid4().hex[:6]}", "hostname": "pulsewatch-demo.local"},
        )
        machine_id, agent_token = enrollment["id"], enrollment["agent_token"]
        configure_cpu_rule(client, token, machine_id)
        send_telemetry(client, machine_id, agent_token, cpu_percent=25, services={"nginx": "running"})

        if args.scenario in ("cpu", "all"):
            print("Simulating CPU threshold breach...")
            send_telemetry(client, machine_id, agent_token, cpu_percent=95, services={"nginx": "running"})
            print_alerts(client, token)
            print("Simulating CPU recovery...")
            send_telemetry(client, machine_id, agent_token, cpu_percent=25, services={"nginx": "running"})

        if args.scenario in ("service", "all"):
            api_request(client, "POST", f"/machines/{machine_id}/services", headers=headers, json={"service_name": "nginx", "severity": "critical"})
            print("Simulating stopped nginx service...")
            send_telemetry(client, machine_id, agent_token, cpu_percent=25, services={"nginx": "stopped"})
            print_alerts(client, token)
            print("Simulating service recovery...")
            send_telemetry(client, machine_id, agent_token, cpu_percent=25, services={"nginx": "running"})

        print("Final alert history:")
        print_alerts(client, token)


if __name__ == "__main__":
    main()
