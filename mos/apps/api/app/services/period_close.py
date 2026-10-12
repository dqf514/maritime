"""Period-close guard + MACR (月度计提) integrity.

期间关账：``AccountingPeriod`` (``gl_accounting_periods``) 是既有机制 —— 行缺失
视为 open（默认永不关账，行为与旧版一致）；``status="closed"`` 之后，任何
GL 过账（新建/过账/冲销/删除）都不得落入该期间 → 409 ``PERIOD_CLOSED``。

MACR 完整性：月度计提记录（``VoyageAccrual`` / ``journal_type="accrual"`` 的
``PeriodJournal``）一旦过账或被引用即不可删除 —— 只能冲销或重建。删除请求
→ 409 ``MACR_LOCKED``。冲销（reverse）与重建（rebuild）路径保持可用。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import VoyageAccrual
from app.models_gl import AccountingPeriod, PeriodJournal
from app.services.financial_statements import norm_period

# 过账后/被引用 → 只可冲销或重建，禁止删除。
MACR_LOCKED_STATUSES = frozenset({"posted", "reversed"})


def period_closed_error(period: str) -> HTTPException:
    return HTTPException(
        409,
        detail={
            "code": "PERIOD_CLOSED",
            "message": f"Period {period} is closed; reopen it before posting",
            "period": period,
        },
    )


def macr_locked_error(message: str = "accrual is posted; reverse or rebuild instead") -> HTTPException:
    return HTTPException(409, detail={"code": "MACR_LOCKED", "message": message})


def is_period_closed(db: Session, tenant_id: UUID, period: str) -> bool:
    """True only when an AccountingPeriod row explicitly marks the period closed."""
    p = norm_period(period)
    row = db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.tenant_id == tenant_id,
            AccountingPeriod.period == p,
        )
    )
    return bool(row is not None and row.status == "closed")


def assert_period_open(db: Session, tenant_id: UUID, period: str) -> str:
    """Raise 409 PERIOD_CLOSED when the accounting period is closed. Returns normalised period."""
    p = norm_period(period)
    if is_period_closed(db, tenant_id, p):
        raise period_closed_error(p)
    return p


def get_accounting_period(db: Session, tenant_id: UUID, period: str) -> AccountingPeriod | None:
    p = norm_period(period)
    return db.scalar(
        select(AccountingPeriod).where(
            AccountingPeriod.tenant_id == tenant_id,
            AccountingPeriod.period == p,
        )
    )


# —— MACR 引用检测：其他分录 reference 中出现本记录 id ————————————


def _entries_reference(entries: Any, needle: str) -> bool:
    for entry in entries or []:
        ref = str(entry.get("reference") or "")
        if needle and needle in ref:
            return True
    return False


def journal_is_referenced(db: Session, journal: PeriodJournal) -> bool:
    """True when another PeriodJournal entry points at this journal id."""
    needle = str(journal.id)
    others = db.scalars(
        select(PeriodJournal).where(
            PeriodJournal.tenant_id == journal.tenant_id,
            PeriodJournal.id != journal.id,
        )
    ).all()
    return any(_entries_reference(o.entries, needle) for o in others)


def accrual_is_referenced(db: Session, accrual: VoyageAccrual) -> bool:
    """True when a GL journal entry points at this accrual id."""
    needle = str(accrual.id)
    journals = db.scalars(
        select(PeriodJournal).where(PeriodJournal.tenant_id == accrual.tenant_id)
    ).all()
    return any(_entries_reference(j.entries, needle) for j in journals)


def assert_macr_deletable(row: Any, *, referenced: bool = False) -> None:
    """Monthly-accrual integrity: posted/reversed/referenced rows are rebuild-only.

    Delete attempts raise 409 MACR_LOCKED — reverse or rebuild instead.
    """
    status = str(getattr(row, "status", "") or "")
    if status in MACR_LOCKED_STATUSES or referenced:
        raise macr_locked_error()


# —— 冲销 / 重建（MACR 只可冲销重建，不可删除）——————————————————


def reverse_voyage_accrual(db: Session, row: VoyageAccrual) -> VoyageAccrual:
    """Non-destructive reverse: posted → reversed (P&L ignores ``status="reversed"``)."""
    from app.services.state_machine import ACCRUAL_TRANSITIONS, transition

    transition("accrual", row.status or "draft", "reversed", ACCRUAL_TRANSITIONS)
    row.status = "reversed"
    db.flush()
    return row


def rebuild_voyage_accrual(
    db: Session,
    row: VoyageAccrual,
    *,
    overrides: dict[str, Any] | None = None,
) -> VoyageAccrual:
    """Reverse the original (when posted) and create a replacement draft accrual.

    The original is kept as an audit trail (status reversed / left as-is for
    drafts) — never hard-deleted. Returns the new draft row.
    """
    if (row.status or "draft") == "posted":
        reverse_voyage_accrual(db, row)
    elif (row.status or "draft") == "reversed":
        pass  # already reversed — rebuild still allowed
    data = {
        "voyage_id": row.voyage_id,
        "period_ym": row.period_ym,
        "line_type": row.line_type,
        "amount": row.amount,
        "currency": row.currency,
        "notes": row.notes,
    }
    if overrides:
        data.update({k: v for k, v in overrides.items() if v is not None})
    replacement = VoyageAccrual(
        tenant_id=row.tenant_id,
        voyage_id=data["voyage_id"],
        period_ym=data["period_ym"],
        line_type=data["line_type"],
        amount=data["amount"],
        currency=data["currency"],
        notes=data["notes"],
        status="draft",
    )
    db.add(replacement)
    db.flush()
    return replacement
