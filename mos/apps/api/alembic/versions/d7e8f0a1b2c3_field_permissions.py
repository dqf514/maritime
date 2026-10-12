"""Field-level permissions (字段级权限).

field_permissions — per-tenant role×entity×field access mode (read|write|hidden)

Revision ID: d7e8f0a1b2c3
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d7e8f0a1b2c3"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "field_permissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False, server_default="read"),
        sa.Column("active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "entity", "field", "role", name="uq_field_perm_tenant_entity_field_role"),
    )
    op.create_index("ix_field_permissions_tenant_id", "field_permissions", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_field_permissions_tenant_id", table_name="field_permissions")
    op.drop_table("field_permissions")
