"""TC contract index-linked hire components (指数联动定价).

Adds ``hire_components`` (JSON) to ``time_charter_contracts`` — the same
component spec as ``Estimate.inputs["unpriced_components"]`` (see
``services/unpriced_components.py``). Null/empty keeps hire statements
byte-identical to the legacy path.

Revision ID: a9f4e2c7b1d3
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a9f4e2c7b1d3"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "time_charter_contracts",
        sa.Column("hire_components", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("time_charter_contracts", "hire_components")
