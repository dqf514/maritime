"""row-level scope owner columns (created_by)

Revision ID: c1d2e3f4a5b6
Revises: d1f2a3b4c5d6
Create Date: 2026-10-24 18:40:00.000000

行级数据权限（``RoleDataScope``）以前只在 3/13 个模块真正落地 ——
管理员把某角色设成「只看自己建的」，但对应模型根本没有归属列，
``apply_data_scope`` 于是**静默放行**（返回全租户数据），这个开关等于摆设。

本 revision 给可被行级收窄的模型补上 ``created_by`` 归属列，
并把 ``apply_data_scope`` 改成 **fail closed**（无归属列 → 返回空集）。

注意：
- ``ports`` / ``port_distances`` 是**全局参考表**（没有 tenant_id），
  不加归属列 —— 行级归属对它们没有意义；
- 全部为可空列 → 存量行 ``created_by IS NULL``（历史数据无归属人），
  「只看自己建的」用户看不到历史行，这是保守且预期的行为；
- revision 幂等：ORM 没声明 / 库里已有 → 跳过。
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = "d1f2a3b4c5d6"
branch_labels = None
depends_on = None

#: 需要补 ``created_by`` 的表（可空的 UUID 外键 → users.id）
TABLES = [
    "laytime_calcs",
    "claims",
    "bunker_orders",
    "payments",
    "payment_batches",
    "charters",
    "vessels",
    "counterparties",
    "cargo_names",
    "ship_certificates",
]


def _has_table(name: str) -> bool:
    from sqlalchemy import inspect

    return name in inspect(op.get_bind()).get_table_names()


def _has_column(table: str, column: str) -> bool:
    from sqlalchemy import inspect

    insp = inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for table in TABLES:
        if not _has_table(table):
            continue
        if _has_column(table, "created_by"):
            continue
        op.add_column(table, sa.Column("created_by", sa.Uuid(), nullable=True))


def downgrade() -> None:
    for table in reversed(TABLES):
        if not _has_table(table):
            continue
        if not _has_column(table, "created_by"):
            continue
        op.drop_column(table, "created_by")
