"""Bunker procurement chain + laytime depth (on-account / root causes / delays).

Revision ID: c8e4f1a2b7d9
Revises: d1e2f3a4b5c6
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8e4f1a2b7d9"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bunker_requirements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("requirement_no", sa.Text(), nullable=False),
        sa.Column("vessel_id", sa.Uuid(), sa.ForeignKey("vessels.id"), nullable=False),
        sa.Column("voyage_id", sa.Uuid(), sa.ForeignKey("voyages.id"), nullable=True),
        sa.Column("fuel_type", sa.String(32), nullable=False, server_default="VLSFO"),
        sa.Column("qty_required", sa.Numeric(12, 3), nullable=False),
        sa.Column("port_id", sa.Uuid(), sa.ForeignKey("ports.id"), nullable=True),
        sa.Column("window_from", sa.Date(), nullable=True),
        sa.Column("window_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "requirement_no"),
    )
    op.create_table(
        "bunker_options",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("requirement_id", sa.Uuid(), sa.ForeignKey("bunker_requirements.id"), nullable=False, index=True),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("counterparties.id"), nullable=False),
        sa.Column("port_id", sa.Uuid(), sa.ForeignKey("ports.id"), nullable=False),
        sa.Column("fuel_type", sa.String(32), nullable=False, server_default="VLSFO"),
        sa.Column("qty", sa.Numeric(12, 3), nullable=False),
        sa.Column("price_per_mt", sa.Numeric(12, 2), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="offered"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "bunker_cap_collar",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("charter_id", sa.Uuid(), sa.ForeignKey("charters.id"), nullable=True),
        sa.Column("fuel_type", sa.String(32), nullable=False),
        sa.Column("cap_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("collar_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("index_symbol", sa.String(32), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "fuel_consumption_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("vessel_id", sa.Uuid(), sa.ForeignKey("vessels.id"), nullable=False, index=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("fuel_type", sa.String(32), nullable=False, server_default="VLSFO"),
        sa.Column("consumption_per_day", sa.Numeric(12, 3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "demurrage_on_account",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("laytime_id", sa.Uuid(), sa.ForeignKey("laytime_calcs.id"), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("payment_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("applied_to_settlement", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "demurrage_root_causes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("laytime_id", sa.Uuid(), sa.ForeignKey("laytime_calcs.id"), nullable=False, index=True),
        sa.Column("cause", sa.String(32), nullable=False),
        sa.Column("delay_hours", sa.Numeric(12, 2), nullable=False),
        sa.Column("responsible_party", sa.String(16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "laytime_delays",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("laytime_id", sa.Uuid(), sa.ForeignKey("laytime_calcs.id"), nullable=False, index=True),
        sa.Column("delay_type", sa.String(32), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_hours", sa.Numeric(12, 2), nullable=True),
        sa.Column("excluded_from_laytime", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cost_impact", sa.Numeric(18, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("laytime_delays")
    op.drop_table("demurrage_root_causes")
    op.drop_table("demurrage_on_account")
    op.drop_table("fuel_consumption_categories")
    op.drop_table("bunker_cap_collar")
    op.drop_table("bunker_options")
    op.drop_table("bunker_requirements")
