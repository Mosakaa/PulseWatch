"""Minimal telemetry collector for a host enrolled in PulseWatch."""

import os
import socket
from datetime import datetime, timezone

import psutil


def collect_snapshot() -> dict[str, object]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "hostname": socket.gethostname(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": memory.percent,
        "disk_percent": disk.percent,
        "uptime_seconds": int(datetime.now().timestamp() - psutil.boot_time()),
    }


if __name__ == "__main__":
    api_url = os.getenv("PULSEWATCH_API_URL", "http://localhost:8000")
    print(f"Collected snapshot for {collect_snapshot()['hostname']}; API target: {api_url}")
