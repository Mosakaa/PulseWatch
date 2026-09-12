"""create initial PulseWatch schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "machines",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("agent_token_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_machines_owner_id", "machines", ["owner_id"])
    op.create_table(
        "telemetry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(length=36), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_percent", sa.Float(), nullable=False),
        sa.Column("disk_percent", sa.Float(), nullable=False),
        sa.Column("network_bytes_sent", sa.Integer(), nullable=False),
        sa.Column("network_bytes_received", sa.Integer(), nullable=False),
        sa.Column("uptime_seconds", sa.Integer(), nullable=False),
        sa.Column("services", sa.JSON(), nullable=False),
    )
    op.create_index("ix_telemetry_machine_id", "telemetry", ["machine_id"])
    op.create_index("ix_telemetry_collected_at", "telemetry", ["collected_at"])
    op.create_table(
        "service_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(length=36), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("service_name", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_service_checks_machine_id", "service_checks", ["machine_id"])
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(length=36), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("metric", sa.String(length=50), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_alert_rules_machine_id", "alert_rules", ["machine_id"])
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(length=36), sa.ForeignKey("machines.id"), nullable=False),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("alert_rules.id"), nullable=True),
        sa.Column("service_check_id", sa.Integer(), sa.ForeignKey("service_checks.id"), nullable=True),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_machine_id", "alerts", ["machine_id"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_alerts_created_at", table_name="alerts")
    op.drop_index("ix_alerts_machine_id", table_name="alerts")
    op.drop_table("alerts")
    op.drop_index("ix_alert_rules_machine_id", table_name="alert_rules")
    op.drop_table("alert_rules")
    op.drop_index("ix_service_checks_machine_id", table_name="service_checks")
    op.drop_table("service_checks")
    op.drop_index("ix_telemetry_collected_at", table_name="telemetry")
    op.drop_index("ix_telemetry_machine_id", table_name="telemetry")
    op.drop_table("telemetry")
    op.drop_index("ix_machines_owner_id", table_name="machines")
    op.drop_table("machines")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
