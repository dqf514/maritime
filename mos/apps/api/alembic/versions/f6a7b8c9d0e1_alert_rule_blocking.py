"""Alert rule blocking flag (Tasks & Alerts 可阻断保存).

config_alert_rules.blocking — true = 命中高优先级规则时阻断保存 (ALERT_BLOCKED)。
新库由 Base.metadata.create_all 建全列；既有库走本迁移补列。

Revision ID: f6a7b8c9d0e1
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "config_alert_rules",
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("config_alert_rules", "blocking")
