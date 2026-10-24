"""Audit trail tamper-evidence: prev_hash / row_hash on audit_logs.

audit_logs.prev_hash —— 同租户上一条审计行的 row_hash（链首为空串）
audit_logs.row_hash  —— sha256(prev_hash + 本行内容)，改任何一格都对不上

老行（迁移前写的）两列都是 NULL —— 校验时跳过，不打断链。

Revision ID: d1f2a3b4c5d6
Revises: c6d7e8f9a0b1
Create Date: 2026-10-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d1f2a3b4c5d6"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("prev_hash", sa.Text(), nullable=True))
    op.add_column("audit_logs", sa.Column("row_hash", sa.Text(), nullable=True))
    op.create_index("ix_audit_logs_row_hash", "audit_logs", ["row_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_row_hash", table_name="audit_logs")
    op.drop_column("audit_logs", "row_hash")
    op.drop_column("audit_logs", "prev_hash")
