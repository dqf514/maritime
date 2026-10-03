"""三大财务报表 — balance sheet / income statement / cashflow.

口径：数据源为 ``PeriodJournal`` 中 ``status="posted"`` 的分录（草稿与已冲销
不入账），科目方向取自 ``ChartOfAccount.account_type``：

- 资产/费用类借方为正（balance = Σdebit − Σcredit）；
- 负债/权益/收入类贷方为正（balance = Σcredit − Σdebit）。

资产负债表恒等式 A = L + E 通过把**本期损益**（收入−费用）并入权益
（``current_period_earnings``）成立——分录本身借贷平衡，故恒等式必然成立。
现金流量表按日记账内与现金/银行科目对列的对方科目类别分桶：
经营（收入/费用/负债）· 投资（资产）· 筹资（权益）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_gl import ChartOfAccount, PeriodJournal

_ZERO = Decimal("0")
_DEBIT_NORMAL = {"asset", "expense"}
_CREDIT_NORMAL = {"liability", "equity", "revenue"}
_ACCOUNT_TYPES = _DEBIT_NORMAL | _CREDIT_NORMAL
_CASHY = ("cash", "bank")


def _f(val: Any) -> Decimal:
    try:
        return Decimal(str(val or 0))
    except Exception:
        return _ZERO


def _entry_account(entry: dict) -> str:
    # 旧链路（hire_engine.allocate_period_journal）写 "account"，gl_engine 写 "account_code"。
    return str(entry.get("account_code") or entry.get("account") or "")


def _entry_debit(entry: dict) -> Decimal:
    return _f(entry.get("debit"))


def _entry_credit(entry: dict) -> Decimal:
    return _f(entry.get("credit"))


def norm_period(period: str) -> str:
    """Validate ``YYYY-MM`` and normalise (zero-padded month)."""
    parts = str(period or "").strip().split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"Invalid period '{period}', expected YYYY-MM")
    month = int(parts[1])
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid period '{period}', month out of range")
    return f"{parts[0]}-{month:02d}"


def period_to_date_range(period: str) -> tuple[date, date]:
    """Inclusive (first_day, last_day) of a YYYY-MM period."""
    import calendar

    p = norm_period(period)
    year, month = int(p[:4]), int(p[5:])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _posted_journals(
    db: Session,
    tenant_id: UUID,
    period_from: str | None = None,
    period_to: str | None = None,
) -> list[PeriodJournal]:
    stmt = select(PeriodJournal).where(
        PeriodJournal.tenant_id == tenant_id,
        PeriodJournal.status == "posted",
    )
    if period_from:
        stmt = stmt.where(PeriodJournal.period >= norm_period(period_from))
    if period_to:
        stmt = stmt.where(PeriodJournal.period <= norm_period(period_to))
    stmt = stmt.order_by(PeriodJournal.period.asc(), PeriodJournal.created_at.asc())
    return list(db.scalars(stmt).all())


def account_balances(
    db: Session,
    tenant_id: UUID,
    period_from: str | None = None,
    period_to: str | None = None,
) -> list[dict[str, Any]]:
    """Per-account debit/credit totals with direction-normalised balance."""
    totals: dict[str, dict[str, Decimal]] = {}
    for journal in _posted_journals(db, tenant_id, period_from, period_to):
        for entry in journal.entries or []:
            code = _entry_account(entry)
            if not code:
                continue
            bucket = totals.setdefault(code, {"debit": _ZERO, "credit": _ZERO})
            bucket["debit"] += _entry_debit(entry)
            bucket["credit"] += _entry_credit(entry)

    if not totals:
        return []

    accounts = {
        a.account_code: a
        for a in db.scalars(
            select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id)
        ).all()
    }

    rows: list[dict[str, Any]] = []
    for code in sorted(totals):
        account = accounts.get(code)
        account_type = (account.account_type if account else "") or ""
        debit = totals[code]["debit"]
        credit = totals[code]["credit"]
        if account_type in _CREDIT_NORMAL:
            balance = credit - debit
        else:
            balance = debit - credit
        rows.append(
            {
                "account_code": code,
                "account_name": account.account_name if account else code,
                "account_type": account_type or None,
                "debit": float(debit),
                "credit": float(credit),
                "balance": float(balance),
            }
        )
    return rows


def trial_balance(
    db: Session,
    tenant_id: UUID,
    period_from: str | None = None,
    period_to: str | None = None,
) -> dict[str, Any]:
    """Trial balance — every account's period movement, totals must agree."""
    rows = account_balances(db, tenant_id, period_from, period_to)
    total_debit = round(sum(r["debit"] for r in rows), 2)
    total_credit = round(sum(r["credit"] for r in rows), 2)
    return {
        "period_from": norm_period(period_from) if period_from else None,
        "period_to": norm_period(period_to) if period_to else None,
        "rows": rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "balanced": abs(total_debit - total_credit) < 0.01,
    }


def generate_balance_sheet(db: Session, tenant_id: UUID, as_of_date: date) -> dict[str, Any]:
    """资产负债表：assets = liabilities + equity（权益含本期损益）。

    取数范围为所有 ``period <= as_of_date`` 的已过账分录（截至日口径）。
    """
    if isinstance(as_of_date, str):
        as_of_date = date.fromisoformat(as_of_date)
    period_to = as_of_date.strftime("%Y-%m")
    rows = account_balances(db, tenant_id, period_from=None, period_to=period_to)

    assets = [r for r in rows if r["account_type"] == "asset"]
    liabilities = [r for r in rows if r["account_type"] == "liability"]
    equity = [r for r in rows if r["account_type"] == "equity"]
    revenue = [r for r in rows if r["account_type"] == "revenue"]
    expenses = [r for r in rows if r["account_type"] == "expense"]

    net_income = round(sum(r["balance"] for r in revenue) - sum(r["balance"] for r in expenses), 2)
    earnings_row = {
        "account_code": "CURRENT_EARNINGS",
        "account_name": "Current period earnings",
        "account_type": "equity",
        "debit": 0.0,
        "credit": 0.0,
        "balance": net_income,
    }
    equity_rows = equity + [earnings_row]

    total_assets = round(sum(r["balance"] for r in assets), 2)
    total_liabilities = round(sum(r["balance"] for r in liabilities), 2)
    total_equity = round(sum(r["balance"] for r in equity_rows), 2)

    return {
        "as_of": as_of_date.isoformat(),
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity_rows,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "net_income": net_income,
        "balanced": abs(total_assets - (total_liabilities + total_equity)) < 0.01,
    }


def generate_income_statement(
    db: Session,
    tenant_id: UUID,
    period_from: str,
    period_to: str,
) -> dict[str, Any]:
    """利润表：revenue − expenses = net income。"""
    rows = account_balances(db, tenant_id, period_from=period_from, period_to=period_to)
    revenue = [r for r in rows if r["account_type"] == "revenue"]
    expenses = [r for r in rows if r["account_type"] == "expense"]
    total_revenue = round(sum(r["balance"] for r in revenue), 2)
    total_expenses = round(sum(r["balance"] for r in expenses), 2)
    return {
        "period_from": norm_period(period_from),
        "period_to": norm_period(period_to),
        "revenue": revenue,
        "expenses": expenses,
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net_income": round(total_revenue - total_expenses, 2),
    }


def _is_cash_account(account: ChartOfAccount | None, code: str) -> bool:
    if account is not None and account.account_type == "asset":
        name = (account.account_name or "").lower()
        if code.startswith("10") or any(k in name for k in _CASHY):
            return True
    return False


def _classify_bucket(account_types: Iterable[str]) -> str:
    types = {t for t in account_types if t}
    if "equity" in types:
        return "financing"
    if "asset" in types:
        return "investing"
    return "operating"


def generate_cashflow(
    db: Session,
    tenant_id: UUID,
    period_from: str,
    period_to: str,
) -> dict[str, Any]:
    """现金流量表（直接法）：按与现金科目对列的对方科目类别分桶。

    operating  = 收入/费用/负债引起的现金流
    investing  = 资产（非现金）引起的现金流
    financing  = 权益引起的现金流
    net_change_in_cash = operating + investing + financing = 现金科目余额变动
    """
    accounts = {
        a.account_code: a
        for a in db.scalars(
            select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id)
        ).all()
    }
    cash_codes = {code for code, a in accounts.items() if _is_cash_account(a, code)}

    buckets = {"operating": _ZERO, "investing": _ZERO, "financing": _ZERO}
    period_from_n, period_to_n = norm_period(period_from), norm_period(period_to)

    for journal in _posted_journals(db, tenant_id, period_from=period_from_n, period_to=period_to_n):
        cash_delta = _ZERO
        counterpart_types: list[str] = []
        for entry in journal.entries or []:
            code = _entry_account(entry)
            movement = _entry_debit(entry) - _entry_credit(entry)
            if code in cash_codes:
                cash_delta += movement
            else:
                account = accounts.get(code)
                counterpart_types.append(account.account_type if account else "")
        if cash_delta == 0:
            continue
        buckets[_classify_bucket(counterpart_types)] += cash_delta

    # 现金期初 = 期初日之前所有已过账分录的现金余额
    beginning_rows = account_balances(db, tenant_id, period_from=None, period_to=None)
    cash_ending_all = sum(
        (_f(r["balance"]) for r in beginning_rows if r["account_code"] in cash_codes), _ZERO
    )
    net_change = sum(buckets.values(), _ZERO)
    # beginning_rows covers all periods; subtract in-period movement for the opening figure
    cash_beginning = cash_ending_all - net_change

    return {
        "period_from": period_from_n,
        "period_to": period_to_n,
        "operating": float(round(buckets["operating"], 2)),
        "investing": float(round(buckets["investing"], 2)),
        "financing": float(round(buckets["financing"], 2)),
        "net_change_in_cash": float(round(net_change, 2)),
        "cash_beginning": float(round(cash_beginning, 2)),
        "cash_ending": float(round(cash_ending_all, 2)),
    }
