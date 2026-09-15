"""Minimal telemetry collector for a host enrolled in PulseWatch."""

import os
import socket
import sqlite3
import time
from datetime import datetime, timezone
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import psutil


class TelemetryBuffer:
    """A bounded, durable FIFO queue for telemetry collected while offline."""

    def __init__(self, path: str | Path, max_rows: int) -> None:
        self.connection = sqlite3.connect(path)
        self.max_rows = max(1, max_rows)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def enqueue(self, payload: dict[str, object]) -> None:
        self.connection.execute(
            "INSERT INTO telemetry_buffer (payload) VALUES (?)",
            (json.dumps(payload),),
        )
        overflow = self.pending_count() - self.max_rows
        if overflow > 0:
            self.connection.execute(
                "DELETE FROM telemetry_buffer WHERE id IN "
                "(SELECT id FROM telemetry_buffer ORDER BY id LIMIT ?)",
                (overflow,),
            )
        self.connection.commit()

    def oldest(self) -> tuple[int, dict[str, object]] | None:
        row = self.connection.execute(
            "SELECT id, payload FROM telemetry_buffer ORDER BY id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return row[0], json.loads(row[1])

    def remove(self, entry_id: int) -> None:
        self.connection.execute("DELETE FROM telemetry_buffer WHERE id = ?", (entry_id,))
        self.connection.commit()

    def pending_count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM telemetry_buffer").fetchone()[0]

    def close(self) -> None:
        self.connection.close()


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


def telemetry_payload(snapshot: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in snapshot.items() if key not in {"hostname", "collected_at"}}


def submit_telemetry(
    client: httpx.Client,
    api_url: str,
    headers: dict[str, str],
    payload: dict[str, object],
) -> None:
    response = client.post(f"{api_url}/agent/telemetry", json=payload, headers=headers)
    response.raise_for_status()


def send_heartbeat(client: httpx.Client, api_url: str, headers: dict[str, str]) -> None:
    response = client.post(f"{api_url}/agent/heartbeat", headers=headers)
    response.raise_for_status()


def flush_buffer(
    buffer: TelemetryBuffer,
    submit: Callable[[dict[str, object]], None],
) -> int:
    submitted = 0
    while entry := buffer.oldest():
        entry_id, payload = entry
        try:
            submit(payload)
        except httpx.HTTPError:
            break
        buffer.remove(entry_id)
        submitted += 1
    return submitted


def run() -> None:
    interval_seconds = max(1, int(os.getenv("PULSEWATCH_INTERVAL_SECONDS", "30")))
    buffer = TelemetryBuffer(
        os.getenv("PULSEWATCH_BUFFER_PATH", "pulsewatch-agent.db"),
        int(os.getenv("PULSEWATCH_BUFFER_MAX_ROWS", "10000")),
    )
    api_url, headers = api_configuration()

    try:
        with httpx.Client(timeout=10) as client:
            while True:
                snapshot = collect_snapshot()
                buffer.enqueue(telemetry_payload(snapshot))
                try:
                    send_heartbeat(client, api_url, headers)
                except httpx.HTTPError as error:
                    print(f"PulseWatch heartbeat failed: {error}")

                submitted = flush_buffer(
                    buffer,
                    lambda payload: submit_telemetry(client, api_url, headers, payload),
                )
                pending = buffer.pending_count()
                if pending:
                    print(f"PulseWatch has {pending} telemetry samples queued")
                elif submitted:
                    print(f"Submitted telemetry for {snapshot['hostname']}")
                time.sleep(interval_seconds)
    finally:
        buffer.close()


if __name__ == "__main__":
    run()
