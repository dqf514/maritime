"""UDF 数据字典 — label_en / label_zh / active columns.

udf_definitions gains bilingual labels and an active toggle (C4-P3).
field_label is kept for backward compatibility with /config/udf consumers.

Revision ID: f8a2c4d6e1b0
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f8a2c4d6e1b0"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("udf_definitions", sa.Column("label_en", sa.String(128), nullable=True))
    op.add_column("udf_definitions", sa.Column("label_zh", sa.String(128), nullable=True))
    op.add_column(
        "udf_definitions",
        sa.Column("active", sa.Boolean(), nullable=True, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("udf_definitions", "active")
    op.drop_column("udf_definitions", "label_zh")
    op.drop_column("udf_definitions", "label_en")
