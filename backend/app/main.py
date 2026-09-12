from datetime import datetime, timezone

from fastapi import FastAPI

app = FastAPI(title="PulseWatch API", version="0.1.0")


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Report that the API process is ready to accept requests."""
    return {
        "status": "ok",
        "service": "pulsewatch-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
