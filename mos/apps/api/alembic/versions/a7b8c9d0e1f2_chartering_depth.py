"""Chartering depth — master contracts, cargo broker rules, claim subtypes/actions,
estimate templates, laytime types + booking reference.

Revision ID: a7b8c9d0e1f2
Revises: f4a6b8c0d2e1
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f4a6b8c0d2e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "master_contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("contract_no", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("counterparty_id", sa.Uuid(), sa.ForeignKey("counterparties.id"), nullable=False),
        sa.Column("contract_type", sa.String(32), nullable=False, server_default="voyage_coa"),
        sa.Column("total_qty", sa.Numeric(18, 3), nullable=True),
        sa.Column("period_from", sa.Date(), nullable=True),
        sa.Column("period_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("clauses", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "contract_no"),
    )
    op.create_table(
        "cargo_broker_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("charter_id", sa.Uuid(), sa.ForeignKey("charters.id"), nullable=False),
        sa.Column("broker_party_id", sa.Uuid(), sa.ForeignKey("counterparties.id"), nullable=False),
        sa.Column("commission_type", sa.String(16), nullable=False),
        sa.Column("commission_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("applies_to", sa.String(16), nullable=False, server_default="all"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "estimate_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("template_name", sa.Text(), nullable=False),
        sa.Column("vessel_id", sa.Uuid(), sa.ForeignKey("vessels.id"), nullable=True),
        sa.Column("cargo_type", sa.String(32), nullable=True),
        sa.Column("route_name", sa.String(128), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "laytime_types",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("label_en", sa.Text(), nullable=False),
        sa.Column("label_zh", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "claim_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("claim_id", sa.Uuid(), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("action_type", sa.String(16), nullable=False),
        sa.Column("action_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_claim_actions_claim_id", "claim_actions", ["claim_id"])

    # Charter：合同方向 / 主合同挂靠 / 成交类型 + 租约页签字段
    op.add_column("charters", sa.Column("charter_direction", sa.String(8), nullable=False, server_default="out"))
    op.add_column("charters", sa.Column("master_contract_id", sa.Uuid(), sa.ForeignKey("master_contracts.id"), nullable=True))
    op.add_column("charters", sa.Column("fixture_type", sa.String(16), nullable=False, server_default="voyage_fixture"))
    op.add_column("charters", sa.Column("exposure_amount", sa.Numeric(18, 2), nullable=True))
    op.add_column("charters", sa.Column("pricing_basis", sa.String(32), nullable=True))
    op.add_column("charters", sa.Column("rebill_settings", sa.JSON(), nullable=True))
    op.add_column("charters", sa.Column("planning_periods", sa.JSON(), nullable=True))
    op.add_column("charters", sa.Column("rev_exp", sa.JSON(), nullable=True))
    op.add_column("charters", sa.Column("properties", sa.JSON(), nullable=True))

    op.add_column("laytime_calcs", sa.Column("booking_reference", sa.String(64), nullable=True))
    op.add_column("claims", sa.Column("subtype", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "subtype")
    op.drop_column("laytime_calcs", "booking_reference")
    for col in (
        "properties",
        "rev_exp",
        "planning_periods",
        "rebill_settings",
        "pricing_basis",
        "exposure_amount",
        "fixture_type",
        "master_contract_id",
        "charter_direction",
    ):
        op.drop_column("charters", col)
    op.drop_index("ix_claim_actions_claim_id", table_name="claim_actions")
    op.drop_table("claim_actions")
    op.drop_table("laytime_types")
    op.drop_table("estimate_templates")
    op.drop_table("cargo_broker_rules")
    op.drop_table("master_contracts")
