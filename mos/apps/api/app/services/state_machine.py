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
    # red-flush (红冲) refund of the received amount; the invariant is enforced
    # in services/finance_workflow.assert_void_allowed (INV-VOID-CREDIT).
    # void alone does not return money to the counterparty.
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

# 加油需求采购链：draft→approved→tendering→ordered→fulfilled（draft 亦可直接招标）。
BUNKER_REQUIREMENT_TRANSITIONS = {
    "draft": {"approved", "tendering", "ordered", "cancelled"},
    "approved": {"tendering", "ordered", "cancelled"},
    "tendering": {"ordered", "cancelled"},
    "ordered": {"fulfilled", "cancelled"},
    "fulfilled": set(),
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

# 货盘生命周期 (Phase 3 Cargo): open→booked→nominated→fixed→completed;
# cancelled 只在早期状态 (open/booked/nominated) 允许, fixed 之后只能走向 completed。
CARGO_TRANSITIONS = {
    "open": {"booked", "cancelled"},
    "booked": {"nominated", "cancelled"},
    "nominated": {"fixed", "cancelled"},
    "fixed": {"completed"},
    "completed": set(),
    "cancelled": set(),
}

CHARTER_AMENDMENT_TRANSITIONS = {
    "proposed": {"approved", "rejected"},
    "approved": set(),
    "rejected": set(),
}

# Phase 6 COA — CoaContract lifecycle: draft → active → completed;
# cancel allowed from any early state. Lifting allocation is only meaningful
# while the contract is active (enforced in services/coa.py).
COA_CONTRACT_TRANSITIONS = {
    "draft": {"active", "cancelled"},
    "active": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

# Phase 7 Trading — Trade lifecycle: draft → confirmed → settled | cancelled;
# cancel is only legal before settlement.
TRADE_TRANSITIONS = {
    "draft": {"confirmed", "cancelled"},
    "confirmed": {"settled", "cancelled"},
    "settled": set(),
    "cancelled": set(),
}

# Phase 5 TC depth — TimeCharterContract lifecycle (draft → active → completed;
# cancel allowed from any early state).
TIME_CHARTER_TRANSITIONS = {
    "draft": {"active", "cancelled"},
    "active": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

# HireStatement lifecycle: draft → sent → approved → paid → void.
HIRE_STATEMENT_TRANSITIONS = {
    "draft": {"sent", "void"},
    "sent": {"approved", "void"},
    "approved": {"paid", "void"},
    "paid": {"void"},
    "void": set(),
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
