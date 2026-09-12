"""Minimal telemetry collector for a host enrolled in PulseWatch."""

import os
import socket
import time
from datetime import datetime, timezone

import httpx
import psutil


def api_configuration() -> tuple[str, dict[str, str]]:
    return (
        os.getenv("PULSEWATCH_API_URL", "http://localhost:8000").rstrip("/"),
        {
            "X-Machine-ID": os.environ["PULSEWATCH_MACHINE_ID"],
            "X-Agent-Token": os.environ["PULSEWATCH_AGENT_TOKEN"],
        },
    )


def monitored_services() -> dict[str, str]:
    expected_services = [name.strip() for name in os.getenv("PULSEWATCH_SERVICES", "").split(",") if name.strip()]
    running_processes = {process.info["name"].lower() for process in psutil.process_iter(["name"]) if process.info["name"]}
    return {name: "running" if name.lower() in running_processes else "stopped" for name in expected_services}


def collect_snapshot() -> dict[str, object]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    network = psutil.net_io_counters()
    return {
        "hostname": socket.gethostname(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": memory.percent,
        "disk_percent": disk.percent,
        "network_bytes_sent": network.bytes_sent,
        "network_bytes_received": network.bytes_recv,
        "uptime_seconds": int(datetime.now().timestamp() - psutil.boot_time()),
        "services": monitored_services(),
    }


def submit_snapshot(snapshot: dict[str, object]) -> None:
    api_url, headers = api_configuration()
    response = httpx.post(f"{api_url}/agent/telemetry", json={key: value for key, value in snapshot.items() if key not in {"hostname", "collected_at"}}, headers=headers, timeout=10)
    response.raise_for_status()


def send_heartbeat() -> None:
    api_url, headers = api_configuration()
    response = httpx.post(f"{api_url}/agent/heartbeat", headers=headers, timeout=10)
    response.raise_for_status()


if __name__ == "__main__":
    interval_seconds = int(os.getenv("PULSEWATCH_INTERVAL_SECONDS", "30"))
    while True:
        try:
            send_heartbeat()
            snapshot = collect_snapshot()
            submit_snapshot(snapshot)
            print(f"Submitted telemetry for {snapshot['hostname']}")
        except httpx.HTTPError as error:
            print(f"PulseWatch submission failed: {error}")
        time.sleep(interval_seconds)
