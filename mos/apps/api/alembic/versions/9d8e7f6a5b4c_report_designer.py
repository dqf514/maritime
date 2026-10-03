"""Phase 8 report designer — datasets/joins/fields + declarative query_spec.

Revision ID: 9d8e7f6a5b4c
Revises: f1c2d3e4a5b6
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9d8e7f6a5b4c"
down_revision = "f1c2d3e4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_datasets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("entity", sa.String(64), nullable=False, unique=True),
        sa.Column("base_table", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "report_joins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "report_definition_id",
            sa.Uuid(),
            sa.ForeignKey("report_definitions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("left_dataset_id", sa.Uuid(), sa.ForeignKey("report_datasets.id"), nullable=False),
        sa.Column("right_dataset_id", sa.Uuid(), sa.ForeignKey("report_datasets.id"), nullable=False),
        sa.Column("join_type", sa.String(16), nullable=False, server_default="left"),
        sa.Column("left_field", sa.String(128), nullable=False),
        sa.Column("right_field", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "report_fields",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "report_definition_id",
            sa.Uuid(),
            sa.ForeignKey("report_definitions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("dataset_id", sa.Uuid(), sa.ForeignKey("report_datasets.id"), nullable=False),
        sa.Column("field_name", sa.String(128), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("expression", sa.Text(), nullable=True),
        sa.Column("agg", sa.String(16), nullable=True),
        sa.Column("format", sa.String(16), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.add_column("report_definitions", sa.Column("query_spec", sa.JSON(), nullable=True))
    op.add_column("report_definitions", sa.Column("spec_version", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("report_definitions", "spec_version")
    op.drop_column("report_definitions", "query_spec")
    op.drop_table("report_fields")
    op.drop_table("report_joins")
    op.drop_table("report_datasets")
