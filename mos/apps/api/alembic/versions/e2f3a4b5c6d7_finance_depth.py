"""Finance depth (Phase 6) — rebilling, commission records, payment
terms/methods/bank accounts, advance payments/allocations, GL account
groups and accounting periods.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rebill_invoices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("rebill_no", sa.Text(), nullable=False),
        sa.Column("source_invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("source_expense_type", sa.String(32), nullable=False, server_default="other"),
        sa.Column("counterparty_id", sa.Uuid(), sa.ForeignKey("counterparties.id"), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("over_cap", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cap_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "rebill_no"),
    )

    op.create_table(
        "commission_types",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("commission_type", sa.String(32), nullable=False),
        sa.Column("base_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("rate_pct", sa.Numeric(8, 4), nullable=False),
        sa.Column("calculated_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("counterparty_id", sa.Uuid(), sa.ForeignKey("counterparties.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "payment_terms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("discount_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("discount_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name"),
    )

    op.create_table(
        "payment_methods",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code"),
    )

    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("bank_name", sa.Text(), nullable=False),
        sa.Column("account_name", sa.Text(), nullable=False),
        sa.Column("account_number", sa.Text(), nullable=False),
        sa.Column("swift_code", sa.String(16), nullable=True),
        sa.Column("iban", sa.String(34), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("counterparty_id", sa.Uuid(), sa.ForeignKey("counterparties.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "advance_payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("advance_no", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False, server_default="payment"),
        sa.Column("counterparty_id", sa.Uuid(), sa.ForeignKey("counterparties.id"), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("allocated_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False, server_default="unallocated"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "advance_no"),
    )

    op.create_table(
        "advance_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("advance_id", sa.Uuid(), sa.ForeignKey("advance_payments.id"), nullable=False, index=True),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id"), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "gl_account_groups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("group_code", sa.String(32), nullable=False),
        sa.Column("group_name", sa.Text(), nullable=False),
        sa.Column("account_type", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "group_code"),
    )

    op.create_table(
        "gl_accounting_periods",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "period"),
    )


def downgrade() -> None:
    op.drop_table("gl_accounting_periods")
    op.drop_table("gl_account_groups")
    op.drop_table("advance_allocations")
    op.drop_table("advance_payments")
    op.drop_table("bank_accounts")
    op.drop_table("payment_methods")
    op.drop_table("payment_terms")
    op.drop_table("commission_types")
    op.drop_table("rebill_invoices")
