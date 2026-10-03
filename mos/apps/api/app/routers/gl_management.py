"""GL 管理路由 — 科目表/科目组/会计期间/日记账 + 三大报表 + 试算平衡。

底层引擎：``services.gl_engine``（业务规则→分录、过账、导出）与
``services.financial_statements``（试算平衡/资产负债表/利润表/现金流量表）。
``hire_engine.allocate_period_journal`` 在此暴露为
``POST /gl/journals/allocate-tc-hire``（TC 期间租金计提分录，幂等）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_gl import AccountGroup, AccountingPeriod, ChartOfAccount, PeriodJournal
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module
from app.services import financial_statements as fs
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter()

ACCOUNT_TYPES = ("revenue", "expense", "asset", "liability", "equity")
JOURNAL_TYPES = ("voyage", "accrual", "non_voyage", "ic")


def _f(val: Any) -> float:
    return float(val or 0)


def _account_out(row: ChartOfAccount) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "account_code": row.account_code,
        "account_name": row.account_name,
        "account_type": row.account_type,
        "parent_code": row.parent_code,
        "currency": row.currency,
        "is_active": bool(row.is_active),
    }


def _journal_out(row: PeriodJournal) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "period": row.period,
        "journal_type": row.journal_type,
        "description": row.description,
        "entries": row.entries or [],
        "total_debit": _f(row.total_debit),
        "total_credit": _f(row.total_credit),
        "status": row.status,
        "posted_at": row.posted_at.isoformat() if row.posted_at else None,
        "posted_by": str(row.posted_by) if row.posted_by else None,
    }


# —— 科目表 ————————————————————————————————————————————————


class AccountIn(BaseModel):
    account_code: str
    account_name: str
    account_type: str
    parent_code: str | None = None
    currency: str = "USD"
    is_active: bool = True


class AccountPatch(BaseModel):
    account_name: str | None = None
    account_type: str | None = None
    parent_code: str | None = None
    currency: str | None = None
    is_active: bool | None = None


@router.get("/gl/accounts")
def list_accounts(
    account_type: str | None = Query(None),
    is_active: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, ChartOfAccount, auth.tenant_id).order_by(ChartOfAccount.account_code.asc())
    if account_type:
        stmt = stmt.where(ChartOfAccount.account_type == account_type)
    if is_active is not None:
        stmt = stmt.where(ChartOfAccount.is_active == is_active)
    rows, total = paginate(db, stmt, limit, offset)
    return envelope([_account_out(r) for r in rows], total, limit, offset)


@router.post("/gl/accounts")
def create_account(
    body: AccountIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    if body.account_type not in ACCOUNT_TYPES:
        raise HTTPException(422, detail={"code": "BAD_ACCOUNT_TYPE", "message": f"expected one of {ACCOUNT_TYPES}"})
    dup = db.scalars(
        scoped_query(db, ChartOfAccount, auth.tenant_id).where(
            ChartOfAccount.account_code == body.account_code
        )
    ).first()
    if dup:
        raise HTTPException(409, detail={"code": "DUPLICATE_CODE", "message": body.account_code})
    row = ChartOfAccount(
        tenant_id=auth.tenant_id,
        account_code=body.account_code,
        account_name=body.account_name,
        account_type=body.account_type,
        parent_code=body.parent_code,
        currency=body.currency,
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _account_out(row)


@router.patch("/gl/accounts/{account_id}")
def patch_account(
    account_id: UUID,
    body: AccountPatch,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, ChartOfAccount, account_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "ACCOUNT_NOT_FOUND", "message": str(account_id)})
    if body.account_type is not None and body.account_type not in ACCOUNT_TYPES:
        raise HTTPException(422, detail={"code": "BAD_ACCOUNT_TYPE", "message": f"expected one of {ACCOUNT_TYPES}"})
    for field in ("account_name", "account_type", "parent_code", "currency", "is_active"):
        val = getattr(body, field)
        if val is not None:
            setattr(row, field, val)
    db.commit()
    db.refresh(row)
    return _account_out(row)


@router.delete("/gl/accounts/{account_id}")
def delete_account(
    account_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, ChartOfAccount, account_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "ACCOUNT_NOT_FOUND", "message": str(account_id)})
    db.delete(row)
    db.commit()
    return {"ok": True}


# —— 科目组 ————————————————————————————————————————————————


class AccountGroupIn(BaseModel):
    group_code: str
    group_name: str
    account_type: str


@router.get("/gl/account-groups")
def list_account_groups(
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        scoped_query(db, AccountGroup, auth.tenant_id).order_by(AccountGroup.group_code.asc())
    ).all()
    return [
        {
            "id": str(r.id),
            "group_code": r.group_code,
            "group_name": r.group_name,
            "account_type": r.account_type,
            "is_active": bool(r.is_active),
        }
        for r in rows
    ]


@router.post("/gl/account-groups")
def create_account_group(
    body: AccountGroupIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    if body.account_type not in ACCOUNT_TYPES:
        raise HTTPException(422, detail={"code": "BAD_ACCOUNT_TYPE", "message": f"expected one of {ACCOUNT_TYPES}"})
    row = AccountGroup(
        tenant_id=auth.tenant_id,
        group_code=body.group_code,
        group_name=body.group_name,
        account_type=body.account_type,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": str(row.id),
        "group_code": row.group_code,
        "group_name": row.group_name,
        "account_type": row.account_type,
        "is_active": bool(row.is_active),
    }


# —— 会计期间 ————————————————————————————————————————————————


class PeriodIn(BaseModel):
    period: str
    status: str = "open"


@router.get("/gl/periods")
def list_periods(
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        scoped_query(db, AccountingPeriod, auth.tenant_id).order_by(AccountingPeriod.period.desc())
    ).all()
    return [
        {
            "id": str(r.id),
            "period": r.period,
            "status": r.status,
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        }
        for r in rows
    ]


@router.post("/gl/periods")
def create_period(
    body: PeriodIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    try:
        period = fs.norm_period(body.period)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "BAD_PERIOD", "message": str(exc)})
    if body.status not in ("open", "closed"):
        raise HTTPException(422, detail={"code": "BAD_STATUS", "message": "expected open|closed"})
    dup = db.scalars(
        scoped_query(db, AccountingPeriod, auth.tenant_id).where(AccountingPeriod.period == period)
    ).first()
    if dup:
        raise HTTPException(409, detail={"code": "DUPLICATE_PERIOD", "message": period})
    row = AccountingPeriod(
        tenant_id=auth.tenant_id,
        period=period,
        status=body.status,
        closed_at=datetime.now(timezone.utc) if body.status == "closed" else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "period": row.period, "status": row.status}


# —— 日记账 ————————————————————————————————————————————————


class JournalLine(BaseModel):
    account_code: str | None = None
    account: str | None = None
    debit: float = 0
    credit: float = 0
    reference: str | None = None
    description: str | None = None


class JournalIn(BaseModel):
    period: str
    journal_type: str = "non_voyage"
    description: str | None = None
    entries: list[JournalLine] = Field(..., min_length=2)


def _normalize_entries(lines: list[JournalLine]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in lines:
        code = line.account_code or line.account
        if not code:
            raise HTTPException(422, detail={"code": "BAD_ENTRY", "message": "account_code required per line"})
        entries.append(
            {
                "account_code": code,
                "debit": str(Decimal(str(line.debit or 0))),
                "credit": str(Decimal(str(line.credit or 0))),
                "reference": line.reference or "",
                "description": line.description or "",
            }
        )
    total_debit = sum(Decimal(e["debit"]) for e in entries)
    total_credit = sum(Decimal(e["credit"]) for e in entries)
    if total_debit != total_credit:
        raise HTTPException(
            422,
            detail={
                "code": "UNBALANCED_JOURNAL",
                "message": f"debit {total_debit} != credit {total_credit}",
            },
        )
    if total_debit == 0:
        raise HTTPException(422, detail={"code": "EMPTY_JOURNAL", "message": "journal has no value"})
    return entries


@router.post("/gl/journals/allocate-tc-hire")
def allocate_tc_hire(
    tc_contract_id: UUID,
    period_start: date,
    period_end: date,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """TC 期间租金计提 → PeriodJournal（幂等：同合约同期间返回已有分录）。"""
    from app.models_time_charter import TimeCharterContract
    from app.services.hire_engine import allocate_period_journal

    contract = scoped_get(db, TimeCharterContract, tc_contract_id, auth.tenant_id)
    if contract is None:
        raise HTTPException(404, detail={"code": "TC_NOT_FOUND", "message": str(tc_contract_id)})
    journal = allocate_period_journal(db, tc_contract_id, period_start, period_end)
    db.commit()
    db.refresh(journal)
    return _journal_out(journal)


@router.post("/gl/journals")
def create_journal(
    body: JournalIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    try:
        period = fs.norm_period(body.period)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "BAD_PERIOD", "message": str(exc)})
    if body.journal_type not in JOURNAL_TYPES:
        raise HTTPException(422, detail={"code": "BAD_JOURNAL_TYPE", "message": f"expected one of {JOURNAL_TYPES}"})
    entries = _normalize_entries(body.entries)
    row = PeriodJournal(
        tenant_id=auth.tenant_id,
        period=period,
        journal_type=body.journal_type,
        description=body.description,
        entries=entries,
        total_debit=sum(Decimal(e["debit"]) for e in entries),
        total_credit=sum(Decimal(e["credit"]) for e in entries),
        status="draft",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _journal_out(row)


@router.get("/gl/journals")
def list_journals(
    period: str | None = Query(None),
    status: str | None = Query(None),
    journal_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, PeriodJournal, auth.tenant_id).order_by(
        PeriodJournal.period.desc(), PeriodJournal.created_at.desc()
    )
    if period:
        stmt = stmt.where(PeriodJournal.period == fs.norm_period(period))
    if status:
        stmt = stmt.where(PeriodJournal.status == status)
    if journal_type:
        stmt = stmt.where(PeriodJournal.journal_type == journal_type)
    rows, total = paginate(db, stmt, limit, offset)
    return envelope([_journal_out(r) for r in rows], total, limit, offset)


@router.get("/gl/journals/{journal_id}")
def get_journal(
    journal_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, PeriodJournal, journal_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "JOURNAL_NOT_FOUND", "message": str(journal_id)})
    return _journal_out(row)


@router.post("/gl/journals/{journal_id}/post")
def post_journal(
    journal_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, PeriodJournal, journal_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "JOURNAL_NOT_FOUND", "message": str(journal_id)})
    if row.status != "draft":
        raise HTTPException(
            409,
            detail={"code": "INVALID_STATE", "message": f"Journal is {row.status}, only draft can be posted"},
        )
    total_debit = sum(Decimal(str(e.get("debit", 0) or 0)) for e in row.entries or [])
    total_credit = sum(Decimal(str(e.get("credit", 0) or 0)) for e in row.entries or [])
    if total_debit != total_credit:
        raise HTTPException(
            422,
            detail={"code": "UNBALANCED_JOURNAL", "message": f"debit {total_debit} != credit {total_credit}"},
        )
    row.status = "posted"
    row.posted_at = datetime.now(timezone.utc)
    row.posted_by = auth.user_id
    db.commit()
    db.refresh(row)
    return _journal_out(row)


@router.api_route("/gl/journals/{journal_id}/reverse", methods=["GET", "POST"])
def reverse_journal(
    journal_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """冲销已过账分录：生成借贷对调的红字分录并过账，原分录置 reversed。"""
    row = scoped_get(db, PeriodJournal, journal_id, auth.tenant_id)
    if row is None:
        raise HTTPException(404, detail={"code": "JOURNAL_NOT_FOUND", "message": str(journal_id)})
    if row.status != "posted":
        raise HTTPException(
            409,
            detail={"code": "INVALID_STATE", "message": f"Journal is {row.status}, only posted can be reversed"},
        )
    reversed_entries = [
        {
            "account_code": e.get("account_code") or e.get("account"),
            "debit": str(Decimal(str(e.get("credit", 0) or 0))),
            "credit": str(Decimal(str(e.get("debit", 0) or 0))),
            "reference": f"reversal of {row.id}",
            "description": e.get("description", ""),
        }
        for e in row.entries or []
    ]
    reversal = PeriodJournal(
        tenant_id=auth.tenant_id,
        period=row.period,
        journal_type=row.journal_type,
        description=f"Reversal of journal {row.id}",
        entries=reversed_entries,
        total_debit=row.total_credit,
        total_credit=row.total_debit,
        status="posted",
        posted_at=datetime.now(timezone.utc),
        posted_by=auth.user_id,
    )
    db.add(reversal)
    row.status = "reversed"
    db.commit()
    db.refresh(reversal)
    return {"original": _journal_out(row), "reversal": _journal_out(reversal)}


# —— 报表 ————————————————————————————————————————————————


def _period_window(period: str | None, period_from: str | None, period_to: str | None) -> tuple[str, str]:
    if period_from and period_to:
        return fs.norm_period(period_from), fs.norm_period(period_to)
    if period:
        p = fs.norm_period(period)
        return p, p
    today = date.today().strftime("%Y-%m")
    return today, today


@router.get("/gl/trial-balance")
def gl_trial_balance(
    period: str | None = Query(None),
    period_from: str | None = Query(None),
    period_to: str | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    p_from, p_to = _period_window(period, period_from, period_to)
    return fs.trial_balance(db, auth.tenant_id, period_from=p_from, period_to=p_to)


@router.get("/gl/balance-sheet")
def gl_balance_sheet(
    period: str | None = Query(None),
    as_of: date | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    if as_of is None:
        if period:
            _, last = fs.period_to_date_range(fs.norm_period(period))
            as_of = last
        else:
            as_of = date.today()
    return fs.generate_balance_sheet(db, auth.tenant_id, as_of)


@router.get("/gl/income-statement")
def gl_income_statement(
    period: str | None = Query(None),
    period_from: str | None = Query(None),
    period_to: str | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    p_from, p_to = _period_window(period, period_from, period_to)
    return fs.generate_income_statement(db, auth.tenant_id, p_from, p_to)


@router.get("/gl/cashflow")
def gl_cashflow(
    period: str | None = Query(None),
    period_from: str | None = Query(None),
    period_to: str | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    p_from, p_to = _period_window(period, period_from, period_to)
    return fs.generate_cashflow(db, auth.tenant_id, p_from, p_to)
