"""Unified sanctions assertion for finance-domain write paths.

Every call records a SanctionsScreening audit row. A blocked counterparty
aborts the business write with 409 SANCTIONS_BLOCKED (same code as the
commercial-side charter check), but the audit row is committed first so the
screening trail survives the aborted request.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models_finance_ext import SanctionsScreening
from app.models_wave1 import Counterparty


def assert_not_sanctioned(
    db: Session,
    tenant_id: UUID,
    counterparty_id: UUID | None,
    *,
    provider: str = "internal-list-v1",
) -> None:
    """Raise 409 SANCTIONS_BLOCKED when the counterparty is not clear.

    Existence / tenant checks are the caller's responsibility; unknown or
    cross-tenant counterparties are ignored here.
    """
    if counterparty_id is None:
        return
    party = db.get(Counterparty, counterparty_id)
    if not party or party.tenant_id != tenant_id:
        return
    result = "clear" if (party.sanctions_status or "clear") == "clear" else "blocked"
    db.add(
        SanctionsScreening(
            tenant_id=tenant_id,
            counterparty_id=counterparty_id,
            provider=provider,
            result=result,
        )
    )
    if result == "blocked":
        db.commit()  # persist the audit trail before aborting
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SANCTIONS_BLOCKED",
                "message": f"Counterparty {party.name} is on the sanctions list",
                "counterparty_id": str(counterparty_id),
            },
        )
