"""金额精度相关列的补齐（commission_basis 加宽 + 加油三表补 currency）

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-10-24 20:10:00.000000

本 revision 汇总了本轮「金额与数据正确性」整改里**唯一需要改 schema** 的
三处，全部是「列的宽度/存在性」问题，没有数据搬迁：

1. ``invoices.commission_basis`` → ``VARCHAR(128)``
   以前这一列是 ``VARCHAR(16)``，而佣金链往里写的是一句 60+ 字的自由文本
   （"brokerage on INV-000123 (charter …)"）→ PostgreSQL 直接
   ``StringDataRightTruncation`` → 500。现在该列只存**规范口径码**
   （``net`` / ``gross``），说明文字移到 ``Invoice.meta``；但历史行里仍可能
   留着 60 字的旧文本，加宽到 128 才能容下（也避免下次改口径码时被截断）。

2. ``bunker_options.currency`` / ``bunker_cap_collar.currency`` /
   ``bunker_inquiries.currency`` → ``VARCHAR(3) NOT NULL DEFAULT 'USD'``
   加油域以前**只有金额没有币种**，且多处写死 USD 计价 —— 同一张加油单里
   一半价格是 EUR、一半是 USD 时账算不平。现在三张表都带上币种，
   与 ``bunker_orders.currency`` / ``Invoice.currency`` 的既有约定一致。

迁移约定（详见 ``alembic/README.md``「迁移约定」一节）：
- ORM 没声明 → 跳过；库里已有等价列/列宽 → 跳过；否则按 ORM 的定义补齐。
- 全部 revision 幂等：重复执行不报错、不重复加列。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None

#: 需要补币种列的加油表：(表名, 列在 ORM 里的位置说明)
BUNKER_CURRENCY_TABLES = (
    "bunker_options",
    "bunker_cap_collar",
    "bunker_inquiries",
)

CURRENCY_LEN = 3
CURRENCY_DEFAULT = "USD"
BASIS_LEN = 128


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _column(table: str, column: str):
    if not _has_table(table):
        return None
    for col in _inspector().get_columns(table):
        if col["name"] == column:
            return col
    return None


def _orm_column(table: str, column: str):
    """ORM 里声明的列（没声明 → 返回 None，迁移据此跳过）。"""
    from app.db import Base
    import app.models_domain  # noqa: F401
    import app.models_finance_ext  # noqa: F401

    tbl = Base.metadata.tables.get(table)
    if tbl is None:
        return None
    return tbl.c.get(column)


def upgrade() -> None:
    # —— 1. invoices.commission_basis 加宽 ————————————————————————————
    orm_col = _orm_column("invoices", "commission_basis")
    db_col = _column("invoices", "commission_basis")
    if orm_col is not None and db_col is not None:
        current_len = getattr(db_col["type"], "length", None)
        target_len = getattr(orm_col.type, "length", None)
        if target_len and current_len and int(current_len) >= int(target_len):
            pass  # 已经是目标宽度（或更宽）→ 跳过
        else:
            with op.batch_alter_table("invoices") as batch_op:
                batch_op.alter_column(
                    "commission_basis",
                    existing_type=sa.String(current_len or 16),
                    type_=sa.String(target_len or BASIS_LEN),
                    existing_nullable=bool(db_col.get("nullable", True)),
                )

    # —— 2. 加油三表补 currency ——————————————————————————————————————
    for table in BUNKER_CURRENCY_TABLES:
        if _orm_column(table, "currency") is None:
            continue  # ORM 没声明 → 不制造 schema 漂移
        if _column(table, "currency") is not None:
            continue  # 库里已有 → 跳过
        if not _has_table(table):
            continue
        op.add_column(
            table,
            sa.Column(
                "currency",
                sa.String(CURRENCY_LEN),
                nullable=False,
                server_default=CURRENCY_DEFAULT,
            ),
        )


def downgrade() -> None:
    for table in reversed(BUNKER_CURRENCY_TABLES):
        if _column(table, "currency") is None:
            continue
        op.drop_column(table, "currency")

    db_col = _column("invoices", "commission_basis")
    if db_col is None:
        return
    # 收窄会截断历史自由文本（老行存的是 60+ 字的说明句）—— 与其静默毁数据，
    # 不如拒绝收窄：PG 上直接报错，SQLite 上会静默截断（更糟）。
    bind = op.get_bind()
    try:
        long_rows = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM invoices "
                "WHERE commission_basis IS NOT NULL AND LENGTH(commission_basis) > 16"
            )
        ).scalar()
    except Exception:  # noqa: BLE001 — 表结构异常时按「有长行」处理
        long_rows = 1
    if long_rows:
        import logging

        logging.getLogger("alembic.runtime.migration").warning(
            "d2e3f4a5b6c7 downgrade: invoices.commission_basis 仍有 %s 行超过 16 字符，"
            "跳过收窄（不截断数据）",
            long_rows,
        )
        return
    with op.batch_alter_table("invoices") as batch_op:
        batch_op.alter_column(
            "commission_basis",
            existing_type=sa.String(BASIS_LEN),
            type_=sa.String(16),
            existing_nullable=bool(db_col.get("nullable", True)),
        )
