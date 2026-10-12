"""Cargo CP terms: bill_by / tolerance_pct / overage_pct on charter + COA contract.

Revision ID: bb025ca9b1c6
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "bb025ca9b1c6"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("charters", sa.Column("bill_by", sa.String(16), nullable=True))
    op.add_column("charters", sa.Column("tolerance_pct", sa.Numeric(5, 2), nullable=True))
    op.add_column("charters", sa.Column("overage_pct", sa.Numeric(5, 2), nullable=True))
    op.add_column("coa_contracts", sa.Column("bill_by", sa.String(16), nullable=True))
    op.add_column("coa_contracts", sa.Column("tolerance_pct", sa.Numeric(5, 2), nullable=True))
    op.add_column("coa_contracts", sa.Column("overage_pct", sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("coa_contracts", "overage_pct")
    op.drop_column("coa_contracts", "tolerance_pct")
    op.drop_column("coa_contracts", "bill_by")
    op.drop_column("charters", "overage_pct")
    op.drop_column("charters", "tolerance_pct")
    op.drop_column("charters", "bill_by")
