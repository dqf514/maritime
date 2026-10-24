"""审批额度工作流 — approval amount limit enforcement (IMOS Financial Control).

Limits are amount bands (Amt From → Amt To) per role/group + entity_type +
currency. An approval whose amount falls outside every active band belonging to
the approver is rejected with 409 ``APPROVAL_LIMIT``.

Permissive default (documented): if the approver has **no** active limit rows
for the given entity_type + currency, the approval is allowed. This keeps
tenants that have not configured limits working exactly as before.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_finance_ext import ApprovalLimit


def _approver_role_codes(approver) -> list[str]:
    """Extract role/group codes from an AuthContext, role string, or list of roles."""
    if approver is None:
        return []
    roles = getattr(approver, "roles", None)
    if roles is not None and not isinstance(approver, str):
        return [str(r) for r in roles]
    if isinstance(approver, str):
        return [approver]
    if isinstance(approver, (list, tuple, set)):
        return [str(r) for r in approver]
    return []


def matching_limits(
    db: Session,
    tenant_id: UUID,
    approver,
    entity_type: str,
    currency: str = "USD",
) -> list[ApprovalLimit]:
    """Active limit rows for the approver's roles + entity_type + currency."""
    rows = all_limits(db, tenant_id, approver, entity_type)
    ccy = (currency or "USD").upper()
    return [r for r in rows if (r.currency or "USD").upper() == ccy]


def all_limits(
    db: Session,
    tenant_id: UUID,
    approver,
    entity_type: str,
) -> list[ApprovalLimit]:
    """Active limit rows for the approver's roles + entity_type（**不限币种**）。"""
    role_codes = _approver_role_codes(approver)
    if not role_codes:
        return []
    rows = db.scalars(
        select(ApprovalLimit).where(
            ApprovalLimit.tenant_id == tenant_id,
            ApprovalLimit.entity_type == entity_type,
            ApprovalLimit.active.is_(True),
            ApprovalLimit.role_code.in_(role_codes),
        )
    ).all()
    return list(rows)


def _base_currency(db: Session, tenant_id: UUID) -> str:
    from app.models_wave1 import Company

    comp = db.scalar(select(Company).where(Company.tenant_id == tenant_id).limit(1))
    return (comp.base_currency if comp and comp.base_currency else "USD")


def _rate_date(
    db: Session,
    tenant_id: UUID,
    invoice_type: str | None,
    context_date: date | None,
) -> date | None:
    """折算用的取价日 —— 按租户配置的 FxDateRule 规则（P1-B9）。

    ``context_date`` 是被审批单据的日期（发票日）。规则选哪个 basis，就用
    哪个日期；上下文里没有对应日期时退回单据日期 —— **绝不**退回「绝对最新
    汇率」（那样同一张单据换个时间批一次结论就变了）。
    """
    if context_date is None:
        return None
    from app.services.fx_date_rules import resolve_rate_date

    return resolve_rate_date(
        db,
        tenant_id,
        invoice_type,
        {
            "invoice": context_date,
            "invoice_date": context_date,
            "posted": context_date,
            "posted_date": context_date,
            "gmt_date": context_date,
        },
        fallback=context_date,
    )


def _convert(
    db: Session,
    tenant_id: UUID,
    amount: Decimal,
    from_ccy: str,
    to_ccy: str,
    *,
    context_date: date | None = None,
    invoice_type: str | None = None,
) -> Decimal | None:
    """金额跨币种折算（经本位币中转）。没有汇率时返回 None。"""
    from app.services.fx_date_rules import resolve_fx_rate

    base = _base_currency(db, tenant_id)
    src = (from_ccy or "USD").upper()
    dst = (to_ccy or "USD").upper()
    if src == dst:
        return amount
    rate_date = _rate_date(db, tenant_id, invoice_type, context_date)
    rate_src = (
        Decimal("1")
        if src == base.upper()
        else resolve_fx_rate(db, tenant_id, src, base, invoice_type=invoice_type, context_date=rate_date)
    )
    rate_dst = (
        Decimal("1")
        if dst == base.upper()
        else resolve_fx_rate(db, tenant_id, dst, base, invoice_type=invoice_type, context_date=rate_date)
    )
    if not rate_src or not rate_dst:
        return None
    return amount * rate_src / rate_dst


def assert_within_limit(
    db: Session,
    tenant_id: UUID,
    approver,
    entity_type: str,
    amount,
    currency: str = "USD",
    *,
    context_date: date | None = None,
    invoice_type: str | None = None,
) -> None:
    """Raise 409 ``APPROVAL_LIMIT`` when ``amount`` is outside the approver's bands.

    ``approver`` may be an ``AuthContext`` (uses ``.roles``), a single role code,
    or a list of role codes. A band covers ``amount`` when
    ``amount_from <= amount <= amount_to`` (inclusive). The approver passes when
    **any** active band of any of their roles covers the amount.

    Permissive default: no active rows for (roles, entity_type) at all → allow.

    P1-B7：**币种不能当成绕过额度的后门**。额度行按币种配置，但审批金额
    可能用别的币种 —— 旧实现只查同币种的额度行，查不到就「宽松放行」，
    于是把一张 EUR 发票改成 EUR 就能绕过 USD 额度。现在查不到同币种额度行
    时，会把金额折算到其它币种的额度行里再比一次。

    ``context_date`` = 被审批单据的日期（发票日），``invoice_type`` = 单据类型。
    两者用于按租户配置的 FxDateRule 规则选折算汇率的**取价日**（P1-B9）；
    不传时折算退回「绝对最新汇率」（旧行为，仅供兼容旧调用点）。
    """
    rows = matching_limits(db, tenant_id, approver, entity_type, currency)
    amt = Decimal(str(amount))

    if rows:
        for row in rows:
            lo = Decimal(str(row.amount_from))
            hi = Decimal(str(row.amount_to))
            if lo <= amt <= hi:
                return
        bands = [
            {
                "role_code": r.role_code,
                "currency": (r.currency or "USD").upper(),
                "amount_from": float(r.amount_from),
                "amount_to": float(r.amount_to),
            }
            for r in rows
        ]
        raise HTTPException(
            status_code=409,
            detail={
                "code": "APPROVAL_LIMIT",
                "message": (
                    f"Approval amount {amt} {currency} is outside the approver's "
                    f"limit for {entity_type}"
                ),
                "entity_type": entity_type,
                "amount": float(amt),
                "currency": currency,
                "limits": bands,
            },
        )

    # 该币种没有额度行 —— 看看有没有别的币种的额度行（有就必须折算后比较）
    every = all_limits(db, tenant_id, approver, entity_type)
    if not every:
        return  # permissive default — 该审批人没有任何额度配置
    other_ccys = sorted({(r.currency or "USD").upper() for r in every})
    for ccy in other_ccys:
        conv = _convert(
            db,
            tenant_id,
            amt,
            currency,
            ccy,
            context_date=context_date,
            invoice_type=invoice_type,
        )
        if conv is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "APPROVAL_LIMIT_FX",
                    "message": (
                        f"Cannot compare approval amount {amt} {currency} against the "
                        f"{ccy} limit: no FX rate available. Configure an FX rate or a "
                        f"{currency} limit row."
                    ),
                    "entity_type": entity_type,
                    "amount": float(amt),
                    "currency": currency,
                    "limit_currency": ccy,
                },
            )
        for row in every:
            if (row.currency or "USD").upper() != ccy:
                continue
            lo = Decimal(str(row.amount_from))
            hi = Decimal(str(row.amount_to))
            if lo <= conv <= hi:
                return
    bands = [
        {
            "role_code": r.role_code,
            "currency": (r.currency or "USD").upper(),
            "amount_from": float(r.amount_from),
            "amount_to": float(r.amount_to),
        }
        for r in every
    ]
    raise HTTPException(
        status_code=409,
        detail={
            "code": "APPROVAL_LIMIT",
            "message": (
                f"Approval amount {amt} {currency} is outside the approver's "
                f"limit for {entity_type}"
            ),
            "entity_type": entity_type,
            "amount": float(amt),
            "currency": currency,
            "limits": bands,
        },
    )
