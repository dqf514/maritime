"""Report schedule last_status column (Run-now outcome tracking).

Revision ID: e5c7a9b1d3f2
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5c7a9b1d3f2"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "report_schedules",
        sa.Column("last_status", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("report_schedules", "last_status")
