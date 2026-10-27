"""ai_messages 补 tokens_in / tokens_out（用量页 Tokens in/out 列）

Revision ID: b7c8d9e0f1a2
Revises: 9e35e5eceaee
Create Date: 2026-10-27 21:10:00.000000

用量页（AI 中枢 → 用量）有「输入 TOKEN / 输出 TOKEN」两列，但
``AIMessage`` 只存了合计 ``tokens_used`` —— 前端这两列永远是 0。
拆分列只对**新写入**的记录有值（LLM 响应里本来就有
prompt/completion 拆分，之前被丢掉了），历史行保持 NULL，不回填、
不猜。

迁移约定（alembic/README.md）：幂等 —— 列已存在则跳过。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "9e35e5eceaee"
branch_labels = None
depends_on = None

TABLE = "ai_messages"
COLUMNS = ("tokens_in", "tokens_out")


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    if TABLE not in insp.get_table_names():
        return  # 测试库由 create_all 建表 —— 无需迁移
    existing = {c["name"] for c in insp.get_columns(TABLE)}
    for name in COLUMNS:
        if name not in existing:
            op.add_column(TABLE, sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    insp = _inspector()
    if TABLE not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns(TABLE)}
    for name in COLUMNS:
        if name in existing:
            op.drop_column(TABLE, name)
