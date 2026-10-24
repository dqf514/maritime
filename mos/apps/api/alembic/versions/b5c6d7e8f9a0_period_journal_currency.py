"""period_journals —— 币种 + 业务来源（幂等过账）。

与 ORM 侧 ``app/models_gl.py::PeriodJournal`` 严格一致：

    currency    / String(3) / 非空 / server_default "USD"
    source_type / String(32) / 可空
    source_id   / Uuid()      / 可空
    UniqueConstraint("tenant_id", "journal_type", "source_type", "source_id")

用途：
- ``currency`` —— 日记账记本位币，跨币种期间不能直接相加；
- ``source_type`` + ``source_id`` —— 业务来源单据（invoice/accrual/voyage…），
  配合唯一约束实现「同一单据只过账一次」的幂等。
  NULL 不参与唯一性（SQLite / PG 都视 NULL 互不相等），历史行与手工日记账不受影响。

迁移约定（详见 ``alembic/README.md``「迁移约定」一节）：
本仓库 schema 的真源是 ``Base.metadata``（应用启动即 ``create_all``），迁移链
只负责把**存量库**收敛到模型定义。因此本 revision：

- 模型尚未声明该列/该约束 → 跳过（ORM 变更未落地时不制造 schema 漂移，
  ``alembic check`` 保持无 diff）；
- 数据库里已有等价列/约束 → 跳过（空库自举建出来的库就是这种）；
- 其余 → 按 ORM 定义补齐。

revision id: b5c6d7e8f9a0
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b5c6d7e8f9a0"
down_revision = "b2f4d6e8a1c3"
branch_labels = None
depends_on = None

TABLE_NAME = "period_journals"

# (列名, 列构造) —— 与 ORM 逐字段对齐
COLUMN_SPECS = (
    ("currency", lambda: sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD")),
    ("source_type", lambda: sa.Column("source_type", sa.String(length=32), nullable=True)),
    ("source_id", lambda: sa.Column("source_id", sa.Uuid(), nullable=True)),
)

# 过账幂等约束（ORM 侧目前未命名，这里用显式名；若 ORM 侧命名则以 ORM 为准）
UNIQUE_NAME = "uq_period_journals_source"
UNIQUE_COLUMNS = ["tenant_id", "journal_type", "source_type", "source_id"]


def _model_table():
    from app.db import Base
    import app.models_gl  # noqa: F401  (确保模型已注册到 Base.metadata)

    return Base.metadata.tables.get(TABLE_NAME)


def _model_columns() -> set[str]:
    table = _model_table()
    return set(table.columns.keys()) if table is not None else set()


def _model_unique() -> tuple[str | None, list[str]] | None:
    """ORM 声明的唯一约束 → (约束名, 列名列表)；没有则 None。"""
    table = _model_table()
    if table is None:
        return None
    for constraint in table.constraints:
        if not isinstance(constraint, sa.UniqueConstraint):
            continue
        cols = [c.name for c in constraint.columns]
        if cols:
            return constraint.name, cols
    return None


def _db_columns(bind) -> set[str]:
    inspector = sa.inspect(bind)
    if TABLE_NAME not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(TABLE_NAME)}


def _db_uniques(bind) -> list[tuple[str | None, list[str]]]:
    inspector = sa.inspect(bind)
    if TABLE_NAME not in inspector.get_table_names():
        return []
    return [
        (uc.get("name"), list(uc.get("column_names") or []))
        for uc in inspector.get_unique_constraints(TABLE_NAME)
    ]


def upgrade() -> None:
    bind = op.get_bind()
    model_cols = _model_columns()
    db_cols = _db_columns(bind)

    for name, factory in COLUMN_SPECS:
        if name not in model_cols:
            # ORM 还没这列 → 不动 schema（保持 alembic check 无 diff）
            continue
        if name in db_cols:
            continue
        op.add_column(TABLE_NAME, factory())
        db_cols.add(name)

    # 幂等过账唯一约束
    target = _model_unique()
    if target is None:
        return
    name, cols = target
    name = name or UNIQUE_NAME
    existing = _db_uniques(bind)
    if any(sorted(c) == sorted(cols) for _, c in existing):
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.create_unique_constraint(name, cols)
    else:
        op.create_unique_constraint(name, TABLE_NAME, cols)


def downgrade() -> None:
    bind = op.get_bind()
    existing = _db_uniques(bind)
    target = _model_unique()
    if target is not None:
        name, cols = target
        name = name or UNIQUE_NAME
        match = next(
            (
                db_name
                for db_name, db_cols in existing
                if sorted(db_cols) == sorted(cols) and db_name
            ),
            None,
        )
        if match is not None:
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table(TABLE_NAME) as batch_op:
                    batch_op.drop_constraint(match, type_="unique")
            else:
                op.drop_constraint(match, TABLE_NAME, type_="unique")

    db_cols = _db_columns(bind)
    for name, _factory in reversed(COLUMN_SPECS):
        if name in db_cols:
            with op.batch_alter_table(TABLE_NAME) as batch_op:
                batch_op.drop_column(name)
