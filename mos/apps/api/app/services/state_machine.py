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
    "partially_paid": {"paid", "void"},
    "paid": set(),
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
