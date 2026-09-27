"""Standard list pagination envelope (U1 列表协议).

List endpoints return ``{"items": [...], "total": n, "limit": l, "offset": o}``
instead of a bare array so clients can page through large collections and
render accurate page controls. New list endpoints must use :func:`paginate`
and :func:`envelope` (see docs/internal/system-upgrade-plan.md §3.9 U1).
Frontend counterpart: ``apps/web/lib/api.ts`` ``apiList``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


def paginate(db: Session, stmt: Select, limit: int, offset: int) -> tuple[list[Any], int]:
    """Run ``stmt`` with limit/offset; return ``(rows, total_before_paging)``.

    ``stmt`` must already carry tenant filters and a deterministic ``order_by``
    (offset paging is only stable with a total order).
    """
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(limit).offset(offset)).all()
    return list(rows), int(total)


def envelope(items: list[Any], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {"items": items, "total": total, "limit": limit, "offset": offset}
