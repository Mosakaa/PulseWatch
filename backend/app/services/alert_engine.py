from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, AlertRule, Machine, Telemetry


def evaluate_threshold_rules(session: Session, machine: Machine, telemetry: Telemetry) -> list[Alert]:
    """Open or resolve threshold alerts after a machine reports telemetry."""
    created_alerts: list[Alert] = []
    rules = session.scalars(select(AlertRule).where(AlertRule.machine_id == machine.id, AlertRule.enabled.is_(True))).all()
    for rule in rules:
        value = getattr(telemetry, rule.metric)
        active_alert = session.scalar(select(Alert).where(Alert.rule_id == rule.id, Alert.state.in_(("active", "acknowledged"))))
        if value >= rule.threshold and active_alert is None:
            alert = Alert(
                machine_id=machine.id,
                rule_id=rule.id,
                kind="threshold",
                severity=rule.severity,
                value=value,
                message=f"{machine.name}: {rule.metric} is {value:.1f}% (threshold {rule.threshold:.1f}%)",
            )
            session.add(alert)
            created_alerts.append(alert)
        elif value < rule.threshold and active_alert is not None:
            active_alert.state = "resolved"
            active_alert.resolved_at = datetime.now(timezone.utc)
    return created_alerts
