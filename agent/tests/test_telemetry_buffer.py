import httpx

from telemetry_buffer import TelemetryBuffer, flush_buffer


def test_buffer_retries_failed_telemetry_in_order(tmp_path):
    buffer = TelemetryBuffer(tmp_path / "telemetry.db", max_rows=10)
    buffer.enqueue({"sequence": 1})
    buffer.enqueue({"sequence": 2})
    attempts = 0
    received = []

    def submit(payload):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("network unavailable")
        received.append(payload["sequence"])

    assert flush_buffer(buffer, submit) == 0
    assert buffer.pending_count() == 2
    assert flush_buffer(buffer, submit) == 2
    assert received == [1, 2]
    assert buffer.pending_count() == 0
    buffer.close()


def test_buffer_discards_oldest_entries_when_full(tmp_path):
    buffer = TelemetryBuffer(tmp_path / "telemetry.db", max_rows=2)
    for sequence in range(1, 4):
        buffer.enqueue({"sequence": sequence})
    received = []

    assert flush_buffer(buffer, lambda payload: received.append(payload["sequence"])) == 2
    assert received == [2, 3]
    buffer.close()
