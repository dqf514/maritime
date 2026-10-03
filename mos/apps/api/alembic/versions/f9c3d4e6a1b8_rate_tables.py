"""Rate tables + rows + pricing templates (Phase 4).

Revision ID: f9c3d4e6a1b8
Revises: e7b9c0d1f5a6
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f9c3d4e6a1b8"
down_revision = "e7b9c0d1f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_tables",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, index=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "rate_table_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("rate_table_id", sa.Uuid(), sa.ForeignKey("rate_tables.id"), nullable=False, index=True),
        sa.Column("dims", sa.JSON(), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit", sa.String(16), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "pricing_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rate_table_refs", sa.JSON(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pricing_templates")
    op.drop_table("rate_table_rows")
    op.drop_table("rate_tables")
