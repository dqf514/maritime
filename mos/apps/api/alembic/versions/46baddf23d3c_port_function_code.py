"""PortCall.function_code — canonical port function code (L/D/P/I/W).

Revision ID: 46baddf23d3c
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "46baddf23d3c"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("port_calls", sa.Column("function_code", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("port_calls", "function_code")
