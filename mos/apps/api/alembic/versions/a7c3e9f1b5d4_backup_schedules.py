"""BackupSchedule table — 自动备份计划（每租户一行）。

Revision ID: a7c3e9f1b5d4
Revises: d4f6a8c1b2e3
Create Date: 2026-10-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7c3e9f1b5d4"
down_revision = "d4f6a8c1b2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("frequency", sa.Text(), nullable=False, server_default="daily"),
        sa.Column("hour_utc", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("weekday", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("keep_last", sa.Integer(), nullable=False, server_default=sa.text("14")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )
    op.create_index("ix_backup_schedules_tenant_id", "backup_schedules", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_backup_schedules_tenant_id", table_name="backup_schedules")
    op.drop_table("backup_schedules")
