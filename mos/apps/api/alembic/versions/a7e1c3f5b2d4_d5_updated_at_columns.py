"""D5 审计列：为缺少 updated_at 的核心表补列（+claims.created_at）。

voyages / claims / payments / payment_batches / chart_of_accounts /
period_journals — 列表页 Last Modified 列与 onupdate 时间戳的数据源。
存量行在迁移时取 DEFAULT CURRENT_TIMESTAMP，之后由 ORM onupdate 推进；
claims 同时补 created_at（原表没有任何时间戳列）。

Revision ID: a7e1c3f5b2d4
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7e1c3f5b2d4"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None

_TABLES = ("voyages", "claims", "payments", "payment_batches", "chart_of_accounts", "period_journals")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        )
    op.add_column(
        "claims",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_column("claims", "created_at")
    for table in reversed(_TABLES):
        op.drop_column(table, "updated_at")
