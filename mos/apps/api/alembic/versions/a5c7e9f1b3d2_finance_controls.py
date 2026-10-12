"""Finance controls P1: approval amount limits + FX rate date rules.

approval_limits — per-role/group approval amount bands (Amt From → Amt To)
fx_date_rules   — FX rate date basis per invoice type (departure|arrival|invoice|posted)

Revision ID: a5c7e9f1b3d2
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a5c7e9f1b3d2"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_limits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("role_code", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True, server_default="USD"),
        sa.Column("amount_from", sa.Numeric(18, 2), nullable=False),
        sa.Column("amount_to", sa.Numeric(18, 2), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_approval_limits_tenant_id", "approval_limits", ["tenant_id"])
    op.create_index("ix_approval_limits_role", "approval_limits", ["role_code"])

    op.create_table(
        "fx_date_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("invoice_type", sa.String(32), nullable=False),
        sa.Column("rate_date_basis", sa.String(16), nullable=False, server_default="invoice"),
        sa.Column("active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "invoice_type", name="uq_fx_date_rules_tenant_type"),
    )
    op.create_index("ix_fx_date_rules_tenant_id", "fx_date_rules", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_fx_date_rules_tenant_id", table_name="fx_date_rules")
    op.drop_table("fx_date_rules")
    op.drop_index("ix_approval_limits_role", table_name="approval_limits")
    op.drop_index("ix_approval_limits_tenant_id", table_name="approval_limits")
    op.drop_table("approval_limits")
