"""Clause library table (Phase 1 / D1).

Revision ID: b4e6d7c8a2f1
Revises: a3d5f8c2e1b9
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b4e6d7c8a2f1"
down_revision = "a3d5f8c2e1b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clause_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=True, index=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("cp_form", sa.Text(), nullable=True, index=True),
        sa.Column("category", sa.Text(), nullable=False, server_default="general"),
        sa.Column("title_en", sa.Text(), nullable=False),
        sa.Column("title_zh", sa.Text(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("clause_templates")
