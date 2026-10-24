"""汇率日期规则 — FX rate date basis per invoice type.

``rate_date_basis`` decides which date an FX rate is taken from:

- ``departure`` — vessel departure date of the voyage
- ``arrival``   — vessel arrival date of the voyage
- ``invoice``   — invoice date
- ``posted``    — posting / GMT date

Additive only in the *configuration* sense: when no active ``FxDateRule`` row
exists for an invoice type the default basis (``invoice``) applies. The rate
**date** itself is always honoured — see :func:`resolve_fx_rate` (P1-B9).

取价日的解析入口是 :func:`resolve_rate_date`（读规则 → :func:`pick_rate_date`
→ 具体日期）；调用方把它算出的日期作为 ``context_date`` 传给
:func:`resolve_fx_rate`。规则表为空时的默认口径：**单据日期（basis=invoice）**，
绝不退回「绝对最新汇率」。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_finance_ext import FxDateRule
from app.models_wave1 import ExchangeRate
from app.services.invoice_types import is_valid_invoice_type, normalize_invoice_type

RATE_DATE_BASES: tuple[str, ...] = ("departure", "arrival", "invoice", "posted")
DEFAULT_RATE_DATE_BASIS = "invoice"

# Context keys a caller may supply to pick_rate_date(), parallel to RATE_DATE_BASES.
_CONTEXT_KEYS = {
    "departure": ("departure", "departure_date", "sailing_date"),
    "arrival": ("arrival", "arrival_date"),
    "invoice": ("invoice", "invoice_date"),
    "posted": ("posted", "posted_date", "gmt_date"),
}


def validate_rate_date_basis(basis: str) -> str:
    """Return ``basis`` if valid; raise ``ValueError`` otherwise."""
    key = (basis or "").strip().lower()
    if key not in RATE_DATE_BASES:
        raise ValueError(f"rate_date_basis must be one of {list(RATE_DATE_BASES)}")
    return key


def _canonical_type(invoice_type: str) -> str:
    if is_valid_invoice_type(invoice_type):
        return normalize_invoice_type(invoice_type)
    return (invoice_type or "").strip().upper()


def _as_date(value) -> date | None:
    """Coerce a context value into a ``date``.

    ``datetime`` 取其日期部分（旧实现直接返回 datetime 对象，
    拿去跟 ``ExchangeRate.rate_date`` 比较会串类型）；字符串取 ISO 前 10 位；
    认不出来的值返回 ``None``（由调用方的 fallback 兜底，而不是抛 500）。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def get_rule(db: Session, tenant_id: UUID, invoice_type: str) -> FxDateRule | None:
    """Active rule row for the (canonical) invoice type, or ``None``."""
    return db.scalar(
        select(FxDateRule).where(
            FxDateRule.tenant_id == tenant_id,
            FxDateRule.invoice_type == _canonical_type(invoice_type),
            FxDateRule.active.is_(True),
        )
    )


def rule_applies(db: Session, tenant_id: UUID, invoice_type: str) -> bool:
    """True when an active rule row exists for this invoice type."""
    return get_rule(db, tenant_id, invoice_type) is not None


def effective_basis(db: Session, tenant_id: UUID, invoice_type: str) -> str:
    """Configured basis for the invoice type, else :data:`DEFAULT_RATE_DATE_BASIS`."""
    row = get_rule(db, tenant_id, invoice_type)
    return row.rate_date_basis if row else DEFAULT_RATE_DATE_BASIS


def pick_rate_date(basis: str, context: dict | None, *, fallback: date | None = None) -> date | None:
    """Map a basis onto a concrete date from a caller-supplied context dict.

    Accepts flexible keys (e.g. ``departure`` / ``departure_date``).

    P1-B9：**不静默退回「绝对最新汇率」**。旧实现拿不到日期时返回 ``None``，
    调用方于是把 ``context_date=None`` 传给 :func:`resolve_fx_rate` —— 后者
    只能取「绝对最新汇率」，同一张历史单据过几个月重算会得到另一个数。
    现在拿不到日期时返回显式的 ``fallback``（通常是**单据/交易日**），
    没有 fallback 才返回 ``None``（调用方必须自己决定取价日）。

    未知 basis（脏配置）按默认 basis（``invoice``）处理，保证行为确定。
    """
    key = (basis or "").strip().lower()
    if key not in RATE_DATE_BASES:
        key = DEFAULT_RATE_DATE_BASIS
    if not context:
        return fallback
    for name in _CONTEXT_KEYS[key]:
        if name not in context:
            continue
        picked = _as_date(context[name])
        if picked is not None:
            return picked
    return fallback


def resolve_rate_date(
    db: Session,
    tenant_id: UUID,
    invoice_type: str | None,
    context: dict | None,
    *,
    fallback: date | None = None,
) -> date | None:
    """取价日 —— 按租户配置的 ``FxDateRule`` 解析成具体日期。

    没有配置规则行时用默认 basis（``invoice``，见 :data:`DEFAULT_RATE_DATE_BASIS`）；
    规则选的 basis 在上下文里没有对应日期时退回 ``fallback``（通常是单据日期）。
    这是「汇率取数日规则」唯一的入口 —— 调用方拿它算出的日期传给
    :func:`resolve_fx_rate`，规则才真正生效（P1-B9）。
    """
    basis = effective_basis(db, tenant_id, invoice_type) if invoice_type else DEFAULT_RATE_DATE_BASIS
    return pick_rate_date(basis, context, fallback=fallback)


def upsert_rule(
    db: Session,
    tenant_id: UUID,
    invoice_type: str,
    rate_date_basis: str,
    active: bool = True,
) -> FxDateRule:
    """Create or update the tenant's rule for ``invoice_type`` (idempotent)."""
    basis = validate_rate_date_basis(rate_date_basis)
    if not is_valid_invoice_type(invoice_type):
        raise ValueError(f"Unknown invoice_type: {invoice_type!r}")
    code = normalize_invoice_type(invoice_type)
    row = db.scalar(
        select(FxDateRule).where(
            FxDateRule.tenant_id == tenant_id,
            FxDateRule.invoice_type == code,
        )
    )
    if row is None:
        row = FxDateRule(
            tenant_id=tenant_id,
            invoice_type=code,
            rate_date_basis=basis,
            active=active,
        )
        db.add(row)
    else:
        row.rate_date_basis = basis
        row.active = active
    return row


def resolve_fx_rate(
    db: Session,
    tenant_id: UUID,
    currency: str,
    base_ccy: str,
    *,
    invoice_type: str | None = None,
    context_date: date | None = None,
) -> Decimal | None:
    """FX rate converting 1 unit of ``currency`` into ``base_ccy``.

    P1-B9：**取价日必须生效，不管租户有没有配置 FxDateRule**。旧实现只在存在
    规则行时才用 ``context_date``，其余一律取「绝对最新汇率」—— 于是租户后来
    改了汇率，再算一遍历史发票就变成另一个数，报表不可复现。现在只要调用方
    给了 ``context_date``，就取「该日期当时有效的最新汇率」
    （``rate_date <= context_date``）；该日期之前一条汇率都没有时，才退回
    绝对最新汇率（此时没有更早的可用值，退回不会把旧值换掉）。

    ``invoice_type`` 仍用于查规则（规则决定调用方该传哪个日期），但不再决定
    取价日是否生效。

    调用方应先用 :func:`resolve_rate_date`（或 :func:`pick_rate_date`）算出
    取价日再传进来；``context_date=None`` 表示调用方**明确放弃**取价日规则
    （退化成「绝对最新汇率」），P1-B9 起所有生产调用点都不再这么用。
    """
    if currency == base_ccy:
        return Decimal("1")
    base_q = (
        ExchangeRate.base_currency == currency,
        ExchangeRate.quote_currency == base_ccy,
        (ExchangeRate.tenant_id == tenant_id) | (ExchangeRate.tenant_id.is_(None)),
    )
    q = select(ExchangeRate).where(*base_q)
    if context_date is not None:
        q = q.where(ExchangeRate.rate_date <= context_date)
    row = db.scalars(q.order_by(ExchangeRate.rate_date.desc()).limit(1)).first()
    if row is None and context_date is not None:
        # 该日期之前没有可用汇率 —— 退回绝对最新（只有这一档可用，不会覆盖旧值）
        q = select(ExchangeRate).where(*base_q)
        row = db.scalars(q.order_by(ExchangeRate.rate_date.desc()).limit(1)).first()
    return Decimal(str(row.rate)) if row else None
