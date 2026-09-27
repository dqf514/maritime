"""Hire surveys table (Phase 1 / D13 on-off-hire survey).

Revision ID: c5f7e8d9b3a2
Revises: b4e6d7c8a2f1
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c5f7e8d9b3a2"
down_revision = "b4e6d7c8a2f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hire_surveys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("charter_id", sa.Uuid(), sa.ForeignKey("charters.id"), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("surveyed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("port_id", sa.Uuid(), sa.ForeignKey("ports.id"), nullable=True),
        sa.Column("bunker_fo", sa.Numeric(12, 3), nullable=True),
        sa.Column("bunker_do", sa.Numeric(12, 3), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("hire_surveys")
