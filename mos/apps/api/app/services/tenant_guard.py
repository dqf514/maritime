"""Tenant-scoped ORM access helpers — 逐点租户过滤的约定封装.

MariOS 的多租户隔离目前完全依赖各路由手写 ``tenant_id ==`` 过滤:
没有数据库行级安全 (RLS), 也没有全局查询作用域。本模块把两类最常见
的访问模式封装为统一约定, 供路由逐步采用, 降低手写过滤漏网的概率:

- :func:`scoped_get` — 按主键取单行, 同时校验租户归属与软删除状态;
- :func:`scoped_query` — 构造已带租户过滤 (及软删除过滤) 的 ``Select``。

重要边界: 这只是**约定封装**, 不是强制隔离层。未改用本模块的旧代码
不受其保护; 真正的数据库级隔离 (RLS / 每租户引擎, 见
``app.services.tenant_datastore``) 仍是后续架构工作。
"""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")

# 软删除在系统里有两种约定 (见 app.services.recycle.soft_delete):
# 有 deleted_at 列的模型打时间戳; 有 status 列的模型置为 "deleted"。
_DELETED_AT = "deleted_at"
_STATUS = "status"
_DELETED_STATUS = "deleted"


def _has_column(model: type, name: str) -> bool:
    return name in model.__table__.columns


def _is_soft_deleted(row: Any) -> bool:
    if getattr(row, _DELETED_AT, None) is not None:
        return True
    return getattr(row, _STATUS, None) == _DELETED_STATUS


def scoped_get(
    db: Session,
    model: type[ModelT],
    row_id: UUID,
    tenant_id: UUID,
    *,
    include_deleted: bool = False,
) -> ModelT | None:
    """按主键取一行; 不存在、属于其他租户或已软删除时一律返回 ``None``。

    不区分 "不存在" 与 "跨租户" 两种原因 —— 路由层据此返回统一的 404,
    避免向攻击者泄露资源的存在性 (IDOR 防护约定)。

    ``include_deleted=True`` 用于回收站等需要看到软删除行的场景, 此时
    仍校验租户归属。
    """
    row = db.get(model, row_id)
    if row is None:
        return None
    if getattr(row, "tenant_id", None) != tenant_id:
        return None
    if not include_deleted and _is_soft_deleted(row):
        return None
    return row


def scoped_query(
    db: Session,
    model: type[ModelT],
    tenant_id: UUID,
    *,
    include_deleted: bool = False,
) -> Select[tuple[ModelT]]:
    """构造已带租户过滤的 ``Select``, 供调用方继续链式追加条件后执行。

    用法::

        stmt = scoped_query(db, Invoice, auth.tenant_id).where(Invoice.status == "issued")
        rows = db.scalars(stmt.order_by(Invoice.invoice_no)).all()

    模型有 ``deleted_at`` 列时自动附加 ``deleted_at IS NULL``; 有
    ``status`` 列时自动附加 ``status != 'deleted'`` (与现有路由列表的
    手写约定一致)。``include_deleted=True`` 跳过软删除过滤。

    ``db`` 参数当前不参与构造, 保留它是为了与将来的每租户引擎路由
    (tenant datastore) 保持一致的调用签名。
    """
    _ = db
    stmt = select(model).where(model.tenant_id == tenant_id)
    if not include_deleted:
        if _has_column(model, _DELETED_AT):
            stmt = stmt.where(model.deleted_at.is_(None))
        if _has_column(model, _STATUS):
            stmt = stmt.where(model.status != _DELETED_STATUS)
    return stmt
