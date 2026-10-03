"""AI agent temperature override (MariAI overhaul).

Revision ID: d1e2f3a4b5c6
Revises: b8c4e2a1d7f9
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "b8c4e2a1d7f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_agent_definitions",
        sa.Column("temperature", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_agent_definitions", "temperature")
