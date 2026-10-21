"""port_calls / noon_reports / sof_events gain deleted_at (soft delete).

运营子实体此前只能新增不能删除；补齐 PATCH/DELETE 需要软删列，
沿用 recycle 约定一（deleted_at 时间戳列）。

Revision ID: c7e1f3a5b9d2
Revises: b2c4d6e8a0f1
Create Date: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7e1f3a5b9d2"
down_revision = "b2c4d6e8a0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("port_calls", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("noon_reports", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sof_events", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sof_events", "deleted_at")
    op.drop_column("noon_reports", "deleted_at")
    op.drop_column("port_calls", "deleted_at")
