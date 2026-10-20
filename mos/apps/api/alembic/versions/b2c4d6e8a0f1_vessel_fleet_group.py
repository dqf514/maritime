"""vessel fleet_group — IMOS-style business grouping (Mother Vessel / Ship
Management / Tugs & Barges / FLF).

Track 2 (master data IMOS alignment): vessels are grouped by commercial
nature, not by management desk. Backfilled to 'mother_vessel' for existing
rows (the overwhelmingly common case) so list views stay stable.

Revision ID: b2c4d6e8a0f1
Revises: a7c3e9f1b5d4
Create Date: 2026-10-20
"""

from alembic import op
import sqlalchemy as sa


revision = "b2c4d6e8a0f1"
down_revision = "a7c3e9f1b5d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vessels",
        sa.Column("fleet_group", sa.Text(), nullable=False, server_default="mother_vessel"),
    )


def downgrade() -> None:
    op.drop_column("vessels", "fleet_group")
