"""财务域共享 helper（路由拆分公共件）。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Invoice
from app.models_finance_ext import CreditNote


from app.models_wave1 import Company, ExchangeRate

def _alive(status: str | None) -> bool:
    return status != "deleted"


# New invoice input is restricted to these types; legacy free-text rows stay readable.
DEFAULT_VAR_LIMIT = 100000.0

INVOICE_TYPES = {
    "freight", "hire", "demurrage", "despatch", "bunker",
    "port_disbursement", "port_da", "tc_hire", "broker_commission",
    "carbon_allowance", "eu_ets", "credit_note", "other",
}

DEFAULT_VAR_LIMIT = 100000.0

TIMEBAR_DAYS_AFTER_BL = 90


def _base_currency(db: Session, tenant_id: UUID) -> str:
    comp = db.scalar(select(Company).where(Company.tenant_id == tenant_id).limit(1))
    return (comp.base_currency if comp and comp.base_currency else "USD")


def _resolve_fx_rate(db: Session, tenant_id: UUID, currency: str, base_ccy: str) -> Decimal | None:
    """Latest tenant (or global) rate converting 1 unit of `currency` into `base_ccy`."""
    if currency == base_ccy:
        return Decimal("1")
    row = db.scalars(
        select(ExchangeRate)
        .where(
            ExchangeRate.base_currency == currency,
            ExchangeRate.quote_currency == base_ccy,
            (ExchangeRate.tenant_id == tenant_id) | (ExchangeRate.tenant_id.is_(None)),
        )
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    ).first()
    return Decimal(str(row.rate)) if row else None


def _days_to_timebar(time_bar: date | None) -> int | None:
    if not time_bar:
        return None
    return (time_bar - date.today()).days


def _credited_amount(db: Session, invoice_id: UUID) -> Decimal:
    # 语义实现已收拢到 services/finance_workflow（不变量测试在那边锁定）
    from app.services.finance_workflow import credited_amount

    return credited_amount(db, invoice_id)


def _as_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


