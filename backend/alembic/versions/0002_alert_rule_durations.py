"""add alert rule duration policies

Revision ID: 0002_alert_rule_durations
Revises: 0001_initial_schema
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_alert_rule_durations"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alert_rules", sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("alert_rules", "duration_seconds")
