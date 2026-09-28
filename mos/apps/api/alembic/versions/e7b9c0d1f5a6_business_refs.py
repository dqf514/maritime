"""Business reference links: claims.contact_id + bunker_orders.counterparty_id.

Revision ID: e7b9c0d1f5a6
Revises: d6a8b9c0e4f3
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e7b9c0d1f5a6"
down_revision = "d6a8b9c0e4f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 原生 ADD COLUMN 支持内联 REFERENCES（避免 batch 模式约束命名要求）
    op.add_column("claims", sa.Column("contact_id", sa.Uuid(), nullable=True))
    op.add_column("bunker_orders", sa.Column("counterparty_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("bunker_orders", "counterparty_id")
    op.drop_column("claims", "contact_id")
