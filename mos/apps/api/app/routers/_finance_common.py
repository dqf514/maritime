"""财务域共享 helper（路由拆分公共件）。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Invoice
from app.models_finance_ext import CreditNote


from app.models_wave1 import Company
from app.services.invoice_types import VALID_INVOICE_TYPES


def _alive(status: str | None) -> bool:
    return status != "deleted"


# New invoice input is restricted to the canonical registry (codes + legacy
# aliases); legacy free-text rows stay readable. See services/invoice_types.py.
DEFAULT_VAR_LIMIT = 100000.0

INVOICE_TYPES = set(VALID_INVOICE_TYPES)

DEFAULT_VAR_LIMIT = 100000.0

TIMEBAR_DAYS_AFTER_BL = 90


def _base_currency(db: Session, tenant_id: UUID) -> str:
    comp = db.scalar(select(Company).where(Company.tenant_id == tenant_id).limit(1))
    return (comp.base_currency if comp and comp.base_currency else "USD")


def _resolve_fx_rate(
    db: Session,
    tenant_id: UUID,
    currency: str,
    base_ccy: str,
    *,
    invoice_type: str | None = None,
    context_date: date | None = None,
) -> Decimal | None:
    """Latest tenant (or global) rate converting 1 unit of `currency` into `base_ccy`.

    Additive: when an active FxDateRule exists for ``invoice_type`` and a
    ``context_date`` is provided, the rate is taken as of that date. Without a
    rule row the historical default (absolute latest rate) is unchanged.
    """
    from app.services.fx_date_rules import resolve_fx_rate

    return resolve_fx_rate(
        db,
        tenant_id,
        currency,
        base_ccy,
        invoice_type=invoice_type,
        context_date=context_date,
    )


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


