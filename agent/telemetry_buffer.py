"""Durable telemetry queue shared by the monitoring agent and demo tooling."""

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import httpx


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
