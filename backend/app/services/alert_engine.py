from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, AlertRule, Machine, ServiceCheck, Telemetry


def evaluate_threshold_rules(session: Session, machine: Machine, telemetry: Telemetry) -> list[Alert]:
    """Promote sustained threshold breaches and resolve incidents on recovery."""
    alerts_to_notify: list[Alert] = []
    current_time = datetime.now(timezone.utc)
    rules = session.scalars(select(AlertRule).where(AlertRule.machine_id == machine.id, AlertRule.enabled.is_(True))).all()
    for rule in rules:
        value = getattr(telemetry, rule.metric)
        incident = session.scalar(select(Alert).where(Alert.rule_id == rule.id, Alert.state.in_(("pending", "active", "acknowledged"))))
        if value >= rule.threshold and incident is None:
            state = "active" if rule.duration_seconds == 0 else "pending"
            alert = Alert(
                machine_id=machine.id,
                rule_id=rule.id,
                kind="threshold",
                state=state,
                severity=rule.severity,
                value=value,
                message=f"{machine.name}: {rule.metric} is {value:.1f}% (threshold {rule.threshold:.1f}%)",
            )
            session.add(alert)
            if state == "active":
                alerts_to_notify.append(alert)
        elif value >= rule.threshold and incident.state == "pending":
            started_at = incident.created_at.replace(tzinfo=timezone.utc) if incident.created_at.tzinfo is None else incident.created_at
            if current_time - started_at >= timedelta(seconds=rule.duration_seconds):
                incident.state = "active"
                alerts_to_notify.append(incident)
        elif value < rule.threshold and incident is not None:
            incident.state = "resolved"
            incident.resolved_at = current_time
    return alerts_to_notify


def evaluate_service_checks(session: Session, machine: Machine, telemetry: Telemetry) -> list[Alert]:
    """Open an incident when an expected service is not reported as running."""
    created_alerts: list[Alert] = []
    checks = session.scalars(select(ServiceCheck).where(ServiceCheck.machine_id == machine.id, ServiceCheck.enabled.is_(True))).all()
    for check in checks:
        service_status = telemetry.services.get(check.service_name, "missing")
        incident = session.scalar(select(Alert).where(Alert.service_check_id == check.id, Alert.state.in_(("active", "acknowledged"))))
        if service_status != "running" and incident is None:
            alert = Alert(machine_id=machine.id, service_check_id=check.id, kind="service", severity=check.severity, message=f"{machine.name}: service {check.service_name} is {service_status}")
            session.add(alert)
            created_alerts.append(alert)
        elif service_status == "running" and incident is not None:
            incident.state = "resolved"
            incident.resolved_at = datetime.now(timezone.utc)
    return created_alerts
