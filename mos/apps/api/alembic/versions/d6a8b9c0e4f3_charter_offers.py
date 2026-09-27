"""Charter offers tracking (long-tail / D2).

Revision ID: d6a8b9c0e4f3
Revises: c5f7e8d9b3a2
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d6a8b9c0e4f3"
down_revision = "c5f7e8d9b3a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charter_offers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("counterparty_id", sa.Uuid(), sa.ForeignKey("counterparties.id"), nullable=True),
        sa.Column("vessel_id", sa.Uuid(), sa.ForeignKey("vessels.id"), nullable=True),
        sa.Column("charterer_name", sa.Text(), nullable=True),
        sa.Column("cargo", sa.Text(), nullable=True),
        sa.Column("laycan_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("laycan_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate", sa.Numeric(14, 4), nullable=True),
        sa.Column("demurrage_rate", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="offer"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("charter_id", sa.Uuid(), sa.ForeignKey("charters.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("charter_offers")
