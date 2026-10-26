"""Invoice optimistic-lock stamp (updated_at).

invoices.updated_at — nullable timestamp used by the optimistic-lock helper
(services/optimistic_lock.py) for concurrent-edit detection (409 STALE_WRITE).
Legacy rows stay NULL until their first UPDATE; assert_fresh is permissive on
NULL. 新库由 Base.metadata.create_all 建全列；既有库走本迁移补列。

Revision ID: e8f9a0b1c2d3
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e8f9a0b1c2d3"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot ADD COLUMN with a non-constant default (CURRENT_TIMESTAMP);
    # legacy rows deliberately stay NULL (assert_fresh is permissive on NULL).
    op.add_column(
        "invoices",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoices", "updated_at")
