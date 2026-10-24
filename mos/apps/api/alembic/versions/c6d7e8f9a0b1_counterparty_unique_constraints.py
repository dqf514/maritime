"""counterparties —— 补齐 ORM 声明的唯一约束 / 部分唯一索引。

背景：主数据写入没有服务端唯一约束，并发提交会落库两条同名对手方
（审计 P0-24）。

与 ORM 侧对齐：``app/models_wave1.py::Counterparty.__table_args__`` 目前声明的是
**部分唯一索引**（软删除的行不占用名字）::

    Index(
        "uq_counterparties_tenant_name", "tenant_id", "name", unique=True,
        sqlite_where=text("deleted_at IS NULL"),
        postgresql_where=text("deleted_at IS NULL"),
    )

迁移约定（详见 ``alembic/README.md``「迁移约定」一节）：
- 模型尚未声明 → 跳过（ORM 变更未落地时不制造 schema 漂移）；
- 数据库里已有等价索引/约束 → 跳过；
- 其余 → 按 ORM 的定义创建（列 + WHERE 条件都跟着 ORM 走，不硬编码）。

revision id: c6d7e8f9a0b1
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None

TABLE_NAME = "counterparties"


def _model_table():
    from app.db import Base
    import app.models_wave1  # noqa: F401  (确保模型已注册到 Base.metadata)

    return Base.metadata.tables.get(TABLE_NAME)


def _index_where(index) -> str | None:
    """部分索引的 WHERE 条件文本（按方言取，取不到则回退到通用 whereclause）。"""
    for dialect in ("sqlite", "postgresql"):
        try:
            clause = index.dialect_options[dialect].get("where")
        except Exception:  # pragma: no cover — 该方言没声明 where
            clause = None
        if clause is not None:
            return str(clause)
    whereclause = getattr(index, "whereclause", None)
    return str(whereclause) if whereclause is not None else None


def _model_unique_specs() -> list[dict]:
    """ORM 声明的唯一约束 / 唯一索引 → [{kind, name, columns, where}]。"""
    table = _model_table()
    if table is None:
        return []
    specs: list[dict] = []
    for constraint in table.constraints:
        if not isinstance(constraint, sa.UniqueConstraint):
            continue
        cols = [c.name for c in constraint.columns]
        if cols:
            specs.append(
                {
                    "kind": "constraint",
                    "name": (constraint.name or "uq_{}_{}".format(TABLE_NAME, "_".join(cols)))[:63],
                    "columns": cols,
                    "where": None,
                }
            )
    for index in table.indexes:
        if not index.unique:
            continue
        cols = [c.name for c in index.columns]
        if not cols:
            continue
        specs.append(
            {
                "kind": "index",
                "name": (index.name or "uq_{}_{}".format(TABLE_NAME, "_".join(cols)))[:63],
                "columns": cols,
                "where": _index_where(index),
            }
        )
    return specs


def _db_unique_specs(bind) -> list[dict]:
    """库里已有的唯一约束 / 唯一索引 → [{kind, name, columns, where}]。"""
    inspector = sa.inspect(bind)
    if TABLE_NAME not in inspector.get_table_names():
        return []
    out: list[dict] = []
    for uc in inspector.get_unique_constraints(TABLE_NAME):
        out.append(
            {
                "kind": "constraint",
                "name": uc.get("name"),
                "columns": list(uc.get("column_names") or []),
                "where": None,
            }
        )
    for ix in inspector.get_indexes(TABLE_NAME):
        if not ix.get("unique"):
            continue
        where = None
        for dialect in ("sqlite", "postgresql"):
            try:
                clause = ix.get("dialect_options", {}).get(dialect, {}).get("where")
            except Exception:  # pragma: no cover
                clause = None
            if clause is not None:
                where = str(clause)
                break
        out.append(
            {
                "kind": "index",
                "name": ix.get("name"),
                "columns": list(ix.get("column_names") or []),
                "where": where,
            }
        )
    return out


def _same_columns(a: list[str], b: list[str]) -> bool:
    return sorted(a) == sorted(b)


def _same_where(a: str | None, b: str | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    norm = lambda s: " ".join(s.replace("(", " ").replace(")", " ").split()).lower()  # noqa: E731
    return norm(a) == norm(b)


def _sort_key(value) -> str:
    """把 created_at 归一成可比较的字符串（SQLite 读出来是字符串，PG 是 datetime）。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _dedupe_soft_delete(bind, spec: dict) -> int:
    """建唯一索引**之前**先去重：同名同租户的行只留最早的一条，其余软删除。

    没有这一步，``alembic upgrade head`` 在有重复数据的存量库上**必然失败**
    （唯一索引建不出来）—— 而重复数据正是这条索引要治的病，迁移不能被
    自己的目标数据卡死（审计 P0-24）。

    为什么是**软删除**而不是硬删：重复行可能已经被发票 / 租约 / 索赔引用
    （外键指向它），硬删会直接炸；软删除既不丢数据，也不再占用唯一索引的
    名字（部分索引的条件是 ``deleted_at IS NULL``）。

    只处理**部分唯一索引**（带 WHERE 条件）：完整唯一约束没有「软删除就
    释放名字」这回事，重复行只能改名 —— 那属于改用户数据，这里不做，
    让迁移显式失败更好。
    """
    where = spec.get("where")
    if not where:
        return 0
    columns = spec["columns"]
    inspector = sa.inspect(bind)
    if TABLE_NAME not in inspector.get_table_names():
        return 0
    table_cols = {c["name"] for c in inspector.get_columns(TABLE_NAME)}
    if "deleted_at" not in table_cols or "id" not in table_cols:
        return 0
    if any(c not in table_cols for c in columns):
        return 0

    select_cols = ", ".join(["id", *columns])
    rows = bind.execute(
        sa.text(f"SELECT {select_cols}, created_at FROM {TABLE_NAME} WHERE {where}")
    ).mappings().all()
    if not rows:
        return 0

    groups: dict[tuple, list] = {}
    for row in rows:
        key = tuple(row[c] for c in columns)
        groups.setdefault(key, []).append(row)

    victims: list = []
    for group in groups.values():
        if len(group) < 2:
            continue
        # 保留最早创建的一条；created_at 为空的排最后（年龄未知），
        # 同龄再按 id 排序 → 结果确定、可复现。
        group.sort(
            key=lambda r: (
                0 if r.get("created_at") is not None else 1,
                _sort_key(r.get("created_at")),
                str(r.get("id")),
            )
        )
        victims.extend(r["id"] for r in group[1:])

    if not victims:
        return 0
    for victim_id in victims:
        bind.execute(
            sa.text(f"UPDATE {TABLE_NAME} SET deleted_at = CURRENT_TIMESTAMP WHERE id = :id"),
            {"id": victim_id},
        )
    return len(victims)


def upgrade() -> None:
    bind = op.get_bind()
    specs = _model_unique_specs()
    if not specs:
        return
    existing = _db_unique_specs(bind)
    for spec in specs:
        # 同名 → 已存在；同列 + 同 WHERE → 等价（名字不同也算）
        if any(e.get("name") == spec["name"] for e in existing):
            continue
        if any(
            _same_columns(e["columns"], spec["columns"]) and _same_where(e["where"], spec["where"])
            for e in existing
        ):
            continue
        # 建索引之前先去重 —— 存量库有重复数据时，索引建不出来。
        _dedupe_soft_delete(bind, spec)
        if spec["kind"] == "constraint":
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table(TABLE_NAME) as batch_op:
                    batch_op.create_unique_constraint(spec["name"], spec["columns"])
            else:
                op.create_unique_constraint(spec["name"], TABLE_NAME, spec["columns"])
        else:
            kwargs = {}
            if spec["where"]:
                kwargs[f"{bind.dialect.name}_where"] = sa.text(spec["where"])
            op.create_index(
                spec["name"],
                TABLE_NAME,
                spec["columns"],
                unique=True,
                **kwargs,
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _db_unique_specs(bind)
    for spec in _model_unique_specs():
        match = next(
            (
                e
                for e in existing
                if e.get("name") == spec["name"]
                or (
                    _same_columns(e["columns"], spec["columns"])
                    and _same_where(e["where"], spec["where"])
                )
            ),
            None,
        )
        if match is None or not match.get("name"):
            continue
        if match["kind"] == "constraint":
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table(TABLE_NAME) as batch_op:
                    batch_op.drop_constraint(match["name"], type_="unique")
            else:
                op.drop_constraint(match["name"], TABLE_NAME, type_="unique")
        else:
            op.drop_index(match["name"], TABLE_NAME)
