from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Machine

DEGRADED_AFTER_SECONDS = 30
OFFLINE_AFTER_SECONDS = 60


def refresh_machine_statuses(session: Session, reference_time: datetime | None = None) -> list[Alert]:
    """Persist liveness state and create one incident per lost machine."""
    current_time = reference_time or datetime.now(timezone.utc)
    created_alerts: list[Alert] = []
    for machine in session.scalars(select(Machine)).all():
        if machine.last_heartbeat_at is None:
            continue
        heartbeat = machine.last_heartbeat_at.replace(tzinfo=timezone.utc) if machine.last_heartbeat_at.tzinfo is None else machine.last_heartbeat_at
        age_seconds = (current_time - heartbeat).total_seconds()
        status = "online" if age_seconds < DEGRADED_AFTER_SECONDS else "degraded" if age_seconds < OFFLINE_AFTER_SECONDS else "offline"
        machine.status = status
        if status == "offline":
            active_alert = session.scalar(select(Alert).where(Alert.machine_id == machine.id, Alert.kind == "heartbeat", Alert.state == "active"))
            if active_alert is None:
                alert = Alert(machine_id=machine.id, kind="heartbeat", severity="critical", message=f"{machine.name} has not sent a heartbeat for {int(age_seconds)} seconds")
                session.add(alert)
                created_alerts.append(alert)
    return created_alerts
