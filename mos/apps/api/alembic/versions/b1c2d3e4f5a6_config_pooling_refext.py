"""Pooling depth + lightering/barge + master-data extensions.

pool_fees / pool_distributions — 池管理费与按期分摊明细
lightering_ops / barge_ops — 过驳/驳运作业
holiday_calendars / working_day_patterns / term_lists / standard_paragraphs — 主数据扩展

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Pooling depth ──
    op.create_table(
        "pool_fees",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("pool_id", sa.Uuid(), sa.ForeignKey("pools.id"), nullable=False),
        sa.Column("fee_type", sa.String(16), nullable=False),
        sa.Column("fee_basis", sa.String(8), nullable=False, server_default="pct"),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=True, server_default="USD"),
        sa.Column("active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pool_fees_tenant_id", "pool_fees", ["tenant_id"])
    op.create_index("ix_pool_fees_pool_id", "pool_fees", ["pool_id"])

    op.create_table(
        "pool_distributions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("period_id", sa.Uuid(), sa.ForeignKey("pool_periods.id"), nullable=False),
        sa.Column("vessel_id", sa.Uuid(), sa.ForeignKey("vessels.id"), nullable=False),
        sa.Column("points", sa.Numeric(10, 4), nullable=True, server_default="0"),
        sa.Column("gross_share", sa.Numeric(18, 2), nullable=True, server_default="0"),
        sa.Column("fee_deduction", sa.Numeric(18, 2), nullable=True, server_default="0"),
        sa.Column("net_share", sa.Numeric(18, 2), nullable=True, server_default="0"),
        sa.Column("paid_status", sa.String(16), nullable=True, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pool_distributions_tenant_id", "pool_distributions", ["tenant_id"])
    op.create_index("ix_pool_distributions_period_id", "pool_distributions", ["period_id"])
    op.create_index("ix_pool_distributions_vessel_id", "pool_distributions", ["vessel_id"])

    # ── Lightering & Barging ──
    op.create_table(
        "lightering_ops",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("op_no", sa.String(32), nullable=False),
        sa.Column("lightering_type", sa.String(32), nullable=False),
        sa.Column("vessel_id", sa.Uuid(), sa.ForeignKey("vessels.id"), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("qty_lightered", sa.Numeric(14, 3), nullable=True),
        sa.Column("status", sa.String(16), nullable=True, server_default="planned"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_lightering_ops_tenant_id", "lightering_ops", ["tenant_id"])
    op.create_index("ix_lightering_ops_vessel_id", "lightering_ops", ["vessel_id"])

    op.create_table(
        "barge_ops",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("op_no", sa.String(32), nullable=False),
        sa.Column("barge_name", sa.Text(), nullable=False),
        sa.Column("barge_type", sa.String(32), nullable=True),
        sa.Column("operation_type", sa.String(16), nullable=False),
        sa.Column("vessel_id", sa.Uuid(), sa.ForeignKey("vessels.id"), nullable=True),
        sa.Column("port_id", sa.Uuid(), sa.ForeignKey("ports.id"), nullable=True),
        sa.Column("qty", sa.Numeric(14, 3), nullable=True),
        sa.Column("status", sa.String(16), nullable=True, server_default="planned"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_barge_ops_tenant_id", "barge_ops", ["tenant_id"])
    op.create_index("ix_barge_ops_vessel_id", "barge_ops", ["vessel_id"])

    # ── Master data extensions ──
    op.create_table(
        "holiday_calendars",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("holidays", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_holiday_calendars_tenant_id", "holiday_calendars", ["tenant_id"])

    op.create_table(
        "working_day_patterns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("monday", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("tuesday", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("wednesday", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("thursday", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("friday", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("saturday", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("sunday", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("is_default", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_working_day_patterns_tenant_id", "working_day_patterns", ["tenant_id"])

    op.create_table(
        "term_lists",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label_en", sa.Text(), nullable=False),
        sa.Column("label_zh", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_term_lists_tenant_id", "term_lists", ["tenant_id"])

    op.create_table(
        "standard_paragraphs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_standard_paragraphs_tenant_id", "standard_paragraphs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_standard_paragraphs_tenant_id", table_name="standard_paragraphs")
    op.drop_table("standard_paragraphs")
    op.drop_index("ix_term_lists_tenant_id", table_name="term_lists")
    op.drop_table("term_lists")
    op.drop_index("ix_working_day_patterns_tenant_id", table_name="working_day_patterns")
    op.drop_table("working_day_patterns")
    op.drop_index("ix_holiday_calendars_tenant_id", table_name="holiday_calendars")
    op.drop_table("holiday_calendars")
    op.drop_index("ix_barge_ops_vessel_id", table_name="barge_ops")
    op.drop_index("ix_barge_ops_tenant_id", table_name="barge_ops")
    op.drop_table("barge_ops")
    op.drop_index("ix_lightering_ops_vessel_id", table_name="lightering_ops")
    op.drop_index("ix_lightering_ops_tenant_id", table_name="lightering_ops")
    op.drop_table("lightering_ops")
    op.drop_index("ix_pool_distributions_vessel_id", table_name="pool_distributions")
    op.drop_index("ix_pool_distributions_period_id", table_name="pool_distributions")
    op.drop_index("ix_pool_distributions_tenant_id", table_name="pool_distributions")
    op.drop_table("pool_distributions")
    op.drop_index("ix_pool_fees_pool_id", table_name="pool_fees")
    op.drop_index("ix_pool_fees_tenant_id", table_name="pool_fees")
    op.drop_table("pool_fees")
