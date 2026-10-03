"""Merge heads: rate_tables + report_designer + time_charter

Revision ID: a1b2c3d4e5f6
Revises: 9d8e7f6a5b4c, f9c3d4e6a1b8
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = ("9d8e7f6a5b4c", "f9c3d4e6a1b8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge revision — no schema changes, just joins two branches."""
    pass


def downgrade() -> None:
    """No-op — cannot unmerge."""
    pass
