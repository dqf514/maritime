"""审批额度工作流 — approval amount limit enforcement (IMOS Financial Control).

Limits are amount bands (Amt From → Amt To) per role/group + entity_type +
currency. An approval whose amount falls outside every active band belonging to
the approver is rejected with 409 ``APPROVAL_LIMIT``.

Permissive default (documented): if the approver has **no** active limit rows
for the given entity_type + currency, the approval is allowed. This keeps
tenants that have not configured limits working exactly as before.
"""

from __future__ import annotations

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
    role_codes = _approver_role_codes(approver)
    if not role_codes:
        return []
    ccy = (currency or "USD").upper()
    rows = db.scalars(
        select(ApprovalLimit).where(
            ApprovalLimit.tenant_id == tenant_id,
            ApprovalLimit.entity_type == entity_type,
            ApprovalLimit.active.is_(True),
            ApprovalLimit.role_code.in_(role_codes),
        )
    ).all()
    return [r for r in rows if (r.currency or "USD").upper() == ccy]


def assert_within_limit(
    db: Session,
    tenant_id: UUID,
    approver,
    entity_type: str,
    amount,
    currency: str = "USD",
) -> None:
    """Raise 409 ``APPROVAL_LIMIT`` when ``amount`` is outside the approver's bands.

    ``approver`` may be an ``AuthContext`` (uses ``.roles``), a single role code,
    or a list of role codes. A band covers ``amount`` when
    ``amount_from <= amount <= amount_to`` (inclusive). The approver passes when
    **any** active band of any of their roles covers the amount.

    Permissive default: no active rows for (roles, entity_type, currency) → allow.
    """
    rows = matching_limits(db, tenant_id, approver, entity_type, currency)
    if not rows:
        return  # permissive default — no limits configured for this approver

    amt = Decimal(str(amount))
    for row in rows:
        lo = Decimal(str(row.amount_from))
        hi = Decimal(str(row.amount_to))
        if lo <= amt <= hi:
            return

    bands = [
        {"role_code": r.role_code, "amount_from": float(r.amount_from), "amount_to": float(r.amount_to)}
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
