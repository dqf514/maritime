"""Time Charter depth (Phase 5) — contract style/sub-TC/profit-share columns
plus profit_share_rules, broker_rules, hire_billing_schedules,
hire_payment_schedules tables.

Revision ID: f1c2d3e4a5b6
Revises: e7b9c0d1f5a6
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1c2d3e4a5b6"
down_revision = "e7b9c0d1f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "time_charter_contracts",
        sa.Column("contract_style", sa.String(16), nullable=False, server_default="time_charter"),
    )
    op.add_column(
        "time_charter_contracts",
        sa.Column("parent_contract_id", sa.Uuid(), sa.ForeignKey("time_charter_contracts.id"), nullable=True),
    )
    op.add_column(
        "time_charter_contracts",
        sa.Column("profit_share_pct", sa.Numeric(6, 2), nullable=True),
    )
    op.add_column(
        "time_charter_contracts",
        sa.Column("profit_share_threshold", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "time_charter_contracts",
        sa.Column("address_comm_pct", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "time_charter_contracts",
        sa.Column("brokerage_pct", sa.Numeric(5, 2), nullable=True),
    )

    op.create_table(
        "profit_share_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("tc_contract_id", sa.Uuid(), sa.ForeignKey("time_charter_contracts.id"), nullable=False, index=True),
        sa.Column("tier_from", sa.Numeric(18, 2), nullable=False),
        sa.Column("tier_to", sa.Numeric(18, 2), nullable=True),
        sa.Column("share_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("basis", sa.String(16), nullable=False, server_default="tce"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "broker_rules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("tc_contract_id", sa.Uuid(), sa.ForeignKey("time_charter_contracts.id"), nullable=False, index=True),
        sa.Column("broker_party_id", sa.Uuid(), sa.ForeignKey("counterparties.id"), nullable=False),
        sa.Column("commission_type", sa.String(16), nullable=False),
        sa.Column("commission_pct", sa.Numeric(6, 2), nullable=False),
        sa.Column("applies_to", sa.String(16), nullable=False, server_default="all"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "hire_billing_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("tc_contract_id", sa.Uuid(), sa.ForeignKey("time_charter_contracts.id"), nullable=False, index=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("hire_statement_id", sa.Uuid(), sa.ForeignKey("hire_statements.id"), nullable=True),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "hire_payment_schedules",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("tc_contract_id", sa.Uuid(), sa.ForeignKey("time_charter_contracts.id"), nullable=False, index=True),
        sa.Column("billing_schedule_id", sa.Uuid(), sa.ForeignKey("hire_billing_schedules.id"), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("hire_payment_schedules")
    op.drop_table("hire_billing_schedules")
    op.drop_table("broker_rules")
    op.drop_table("profit_share_rules")
    op.drop_column("time_charter_contracts", "brokerage_pct")
    op.drop_column("time_charter_contracts", "address_comm_pct")
    op.drop_column("time_charter_contracts", "profit_share_threshold")
    op.drop_column("time_charter_contracts", "profit_share_pct")
    op.drop_column("time_charter_contracts", "parent_contract_id")
    op.drop_column("time_charter_contracts", "contract_style")
