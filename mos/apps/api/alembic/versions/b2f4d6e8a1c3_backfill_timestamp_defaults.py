"""时间戳列：补 DEFAULT + 回填存量 NULL。

背景
----
a7e1c3f5b2d4 / e8f9a0b1c2d3 / f3a1c0de9b72 用 ``ALTER TABLE ADD COLUMN`` 给既有表补
``created_at`` / ``updated_at``。列是建出来了，但在**既有 SQLite 库**上落地后
**没有带上 DEFAULT**（DDL 里只有 ``"updated_at" DATETIME``），于是：

* 每次 INSERT 写入 NULL → 列表页 "Last Modified" 永远是 "—"；
* 乐观锁（``services/optimistic_lock.py::assert_fresh``）对 updated_at 为 NULL
  的行一律放行 → 并发覆盖检测在这些表上完全失效。

新建库（``Base.metadata.create_all``）不受影响：模型里带 ``server_default``，
DDL 会渲染 ``DEFAULT CURRENT_TIMESTAMP``。

本迁移（幂等，只补差）
----------------------
1. 回填存量 NULL：``updated_at ← COALESCE(created_at, CURRENT_TIMESTAMP)``；
   ``created_at`` 整列皆 NULL 时取 CURRENT_TIMESTAMP。
2. 给缺 DEFAULT 的列补上 ``DEFAULT CURRENT_TIMESTAMP``
   （SQLite 走 ``batch_alter_table`` 重建表；Postgres 直接 ALTER）。
3. 列本身不存在的库（从未跑过旧迁移）跳过 —— 由 create_all 建全列。

新写入路径另有 ORM 侧兜底：``models_domain.py`` / ``models_gl.py`` 中这几列
同时声明了 ``default=func.now()``，即使 DB 没有 DEFAULT 也会写入时间戳。

Revision ID: b2f4d6e8a1c3
Revises: f3a1c0de9b72
Create Date: 2026-10-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2f4d6e8a1c3"
down_revision = "f3a1c0de9b72"
branch_labels = None
depends_on = None

# (表, 列) — 这些列由旧迁移补建，在 SQLite 上丢了 DEFAULT
_TARGETS = (
    ("voyages", "updated_at"),
    ("claims", "created_at"),
    ("claims", "updated_at"),
    ("payments", "updated_at"),
    ("payment_batches", "updated_at"),
    ("chart_of_accounts", "updated_at"),
    ("period_journals", "updated_at"),
    ("invoices", "created_at"),
    ("invoices", "updated_at"),
)


def _columns(table: str) -> dict[str, dict]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return {}
    return {c["name"]: c for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    for table, col in _TARGETS:
        cols = _columns(table)
        if col not in cols:
            continue  # 该库从未有过这列 —— 由 create_all 建全列

        # 1) 回填存量 NULL（updated_at 优先继承 created_at —— 该表可能没有 created_at）
        if col == "updated_at" and "created_at" in cols:
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {col} = COALESCE(created_at, CURRENT_TIMESTAMP) "
                    f"WHERE {col} IS NULL"
                )
            )
        else:
            op.execute(
                sa.text(f"UPDATE {table} SET {col} = CURRENT_TIMESTAMP WHERE {col} IS NULL")
            )

        # 2) 补 DB 级 DEFAULT（缺失才动，避免无谓的表重建）
        if cols[col].get("server_default") is not None:
            continue
        if is_sqlite:
            # SQLite 不能 ALTER 列默认值 —— batch 模式重建表（FK 检查默认关闭，安全）
            with op.batch_alter_table(table) as batch:
                batch.alter_column(
                    col,
                    existing_type=sa.DateTime(timezone=True),
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                )
        else:
            op.alter_column(
                table,
                col,
                existing_type=sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )


def downgrade() -> None:
    # 不回滚：回填过的 created_at/updated_at 有真实业务含义，抹掉等于丢审计信息。
    # DEFAULT 本身保留（对旧行为而言只是更严谨）。
    pass
