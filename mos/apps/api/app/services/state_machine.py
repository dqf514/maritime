"""Shared finite-state helpers. Illegal transitions → 409 INVALID_STATE."""

from __future__ import annotations

from fastapi import HTTPException


class InvalidState(HTTPException):
    def __init__(self, entity: str, current: str, target: str):
        super().__init__(
            status_code=409,
            detail={
                "code": "INVALID_STATE",
                "message": f"{entity}: cannot transition {current} → {target}",
                "current": current,
                "target": target,
            },
        )


def transition(entity: str, current: str, target: str, allowed: dict[str, set[str]]) -> str:
    nxt = allowed.get(current, set())
    if target not in nxt:
        raise InvalidState(entity, current, target)
    return target


CHARTER_TRANSITIONS = {
    "draft": {"pending_approval", "cancelled"},
    "pending_approval": {"active", "draft", "cancelled"},
    "active": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

VOYAGE_TRANSITIONS = {
    "planned": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

INVOICE_TRANSITIONS = {
    "draft": {"pending_approval", "void"},
    "pending_approval": {"issued", "draft", "void"},
    "issued": {"partially_paid", "paid", "void"},
    # partially_paid → void is only legitimate together with a credit note /
    # red-flush (红冲) refund of the received amount; the credit-note workflow
    # lives in the finance router layer, which must implement it alongside
    # this transition (void alone does not return money to the counterparty).
    # partially_paid → issued / paid → partially_paid are only exercised by the
    # payment-void reversal in the finance router (POST /payments/{id}/void),
    # which rewrites paid_amount before transitioning.
    "partially_paid": {"paid", "void", "issued"},
    "paid": {"partially_paid"},
    "void": set(),
}

CLAIM_TRANSITIONS = {
    "open": {"negotiating", "settled", "withdrawn"},
    "negotiating": {"settled", "withdrawn", "open"},
    "settled": set(),
    "withdrawn": set(),
}

LAYTIME_TRANSITIONS = {
    "draft": {"calculated", "cancelled"},
    "calculated": {"finalized", "draft"},
    "finalized": set(),
    "cancelled": set(),
}

BUNKER_TRANSITIONS = {
    "planned": {"inquiry", "cancelled"},
    "inquiry": {"ordered", "cancelled"},
    "ordered": {"delivered", "cancelled"},
    "delivered": {"closed"},
    "closed": set(),
    "cancelled": set(),
}

OFFHIRE_TRANSITIONS = {
    "open": {"closed"},
    "closed": set(),
}

COA_LIFTING_TRANSITIONS = {
    "planned": {"nominated", "withdrawn"},
    "nominated": {"fixed", "withdrawn"},
    "fixed": {"completed", "withdrawn"},
    "completed": set(),
    "withdrawn": set(),
}

CHARTER_AMENDMENT_TRANSITIONS = {
    "proposed": {"approved", "rejected"},
    "approved": set(),
    "rejected": set(),
}

PDA_TRANSITIONS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"approved", "draft"},
    "approved": {"fda"},
    "fda": {"closed"},
    "closed": set(),
    "cancelled": set(),
}

POOL_PERIOD_TRANSITIONS = {
    "open": {"calculating", "cancelled"},
    "calculating": {"settled", "open"},
    "settled": set(),
    "cancelled": set(),
}

# DDS §5.4 also mandates email.parse / license / connector state machines.
# Statuses below mirror the values already used by the routers:
# email_notify.py (pending/review/parsed), admin_platform.py + saas.py
# (inactive/active/expired/suspended), connectors.py (draft/active/error/deleted).
EMAIL_PARSE_TRANSITIONS = {
    "pending": {"review", "parsed", "failed"},
    "review": {"parsed", "failed", "pending"},
    "parsed": {"archived"},
    "failed": {"pending"},
    "archived": set(),
}

LICENSE_TRANSITIONS = {
    "inactive": {"active"},
    "active": {"inactive", "suspended", "expired"},
    "suspended": {"active", "expired"},
    "expired": {"active"},  # renewal reactivates an expired license
}

CONNECTOR_TRANSITIONS = {
    "draft": {"active", "deleted"},
    "active": {"error", "deleted"},
    "error": {"active", "deleted"},
    "deleted": set(),
}
