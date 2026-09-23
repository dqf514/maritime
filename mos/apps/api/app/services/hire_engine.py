"""Hire statement engine for time-charter contracts.

Calculates periodic hire statements with off-hire deductions,
bunker adjustments, and line-by-line breakdown.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import OffHireEvent, Voyage
from app.models_time_charter import HireStatement, TimeCharterContract
from app.services.doc_numbering import next_doc_number

_D = Decimal
_ZERO = _D("0")
_CENT = _D("0.01")


def _f(val) -> _D:
    if val is None:
        return _ZERO
    return _D(str(val))


def _days_in_period(
    start: date, end: date, period_start: date, period_end: date
) -> _D:
    """Calculate billable days clipped to the statement period."""
    clip_start = max(start, period_start)
    clip_end = min(end, period_end)
    if clip_end <= clip_start:
        return _ZERO
    return _D(str((clip_end - clip_start).days))


def _off_hire_days_in_period(
    events: list[OffHireEvent],
    period_start: date,
    period_end: date,
) -> tuple[_D, _D]:
    """Return (total_off_hire_days, total_deduction) for events overlapping the period."""
    total_days = _ZERO
    total_deduction = _ZERO
    for ev in events:
        if not ev.deduct_hire:
            continue
        ev_start = ev.start_at.date() if ev.start_at else None
        ev_end = ev.end_at.date() if ev.end_at else period_end
        if ev_start is None:
            continue
        days = _days_in_period(ev_start, ev_end, period_start, period_end)
        total_days += days
        if ev.hire_deduction is not None:
            total_deduction += _f(ev.hire_deduction)
    return total_days, total_deduction


def calculate_hire_statement(
    db: Session,
    contract: TimeCharterContract,
    period_start: date,
    period_end: date,
) -> dict:
    """Calculate a hire statement for a billing period.

    Returns a dict with all computed fields ready for persistence.
    """
    hire_rate = _f(contract.hire_rate)

    total_period_days = _D(str((period_end - period_start).days))

    contract_start = contract.delivery_date or period_start
    contract_end = contract.redelivery_date or period_end

    effective_days = _days_in_period(
        contract_start, contract_end, period_start, period_end
    )

    tenant_id = contract.tenant_id
    contract_id = contract.id

    off_hire_q = select(OffHireEvent).where(
        OffHireEvent.tenant_id == tenant_id,
        OffHireEvent.charter_id == contract.charter_id,
        OffHireEvent.status.in_(["open", "closed"]),
    )
    off_hire_events = db.scalars(off_hire_q).all()

    oh_days, oh_explicit_deduction = _off_hire_days_in_period(
        off_hire_events, period_start, period_end
    )

    billable_days = effective_days - oh_days
    if billable_days < _ZERO:
        billable_days = _ZERO

    gross_hire = (billable_days * hire_rate).quantize(_CENT, ROUND_HALF_UP)

    time_deduction = (oh_days * hire_rate).quantize(_CENT, ROUND_HALF_UP)
    off_hire_deduction = time_deduction + oh_explicit_deduction

    net_hire = (gross_hire - off_hire_deduction).quantize(_CENT, ROUND_HALF_UP)

    breakdown_lines: list[dict] = []
    breakdown_lines.append({
        "label": "Gross Hire",
        "days": str(billable_days + oh_days),
        "rate": str(hire_rate),
        "amount": str(gross_hire + off_hire_deduction),
    })

    if oh_days > _ZERO:
        breakdown_lines.append({
            "label": "Off-hire Deduction (time)",
            "days": f"-{oh_days}",
            "rate": str(hire_rate),
            "amount": f"-{time_deduction}",
        })

    for ev in off_hire_events:
        if not ev.deduct_hire or ev.hire_deduction is None:
            continue
        breakdown_lines.append({
            "label": f"Off-hire: {ev.event_type or ev.reason or 'event'}",
            "amount": f"-{_f(ev.hire_deduction)}",
        })

    breakdown_lines.append({
        "label": "Net Hire",
        "amount": str(net_hire),
    })

    return {
        "period_start": period_start,
        "period_end": period_end,
        "hire_days": billable_days,
        "off_hire_days": oh_days,
        "gross_hire": (gross_hire + off_hire_deduction).quantize(_CENT, ROUND_HALF_UP),
        "off_hire_deduction": off_hire_deduction.quantize(_CENT, ROUND_HALF_UP),
        "bunker_adjustment": _ZERO,
        "other_adjustments": _ZERO,
        "net_hire": net_hire,
        "currency": contract.hire_currency,
        "breakdown": {"lines": breakdown_lines},
    }


def create_hire_statement(
    db: Session,
    contract: TimeCharterContract,
    period_start: date,
    period_end: date,
) -> HireStatement:
    """Calculate and persist a new HireStatement."""
    calc = calculate_hire_statement(db, contract, period_start, period_end)

    stmt_number = next_doc_number(
        db, contract.tenant_id, HireStatement, HireStatement.statement_number, "HS"
    )

    stmt = HireStatement(
        tenant_id=contract.tenant_id,
        contract_id=contract.id,
        statement_number=stmt_number,
        period_start=calc["period_start"],
        period_end=calc["period_end"],
        hire_days=calc["hire_days"],
        off_hire_days=calc["off_hire_days"],
        gross_hire=calc["gross_hire"],
        off_hire_deduction=calc["off_hire_deduction"],
        bunker_adjustment=calc["bunker_adjustment"],
        other_adjustments=calc["other_adjustments"],
        net_hire=calc["net_hire"],
        currency=calc["currency"],
        breakdown=calc["breakdown"],
    )
    db.add(stmt)
    db.flush()
    return stmt


def generate_all_statements(
    db: Session,
    contract: TimeCharterContract,
) -> list[HireStatement]:
    """Auto-generate monthly/semi-monthly statements for the full contract period."""
    if not contract.delivery_date or not contract.redelivery_date:
        return []

    freq_days = 30 if contract.payment_frequency == "monthly" else 15
    statements: list[HireStatement] = []

    cursor = contract.delivery_date
    while cursor < contract.redelivery_date:
        period_end = min(cursor + timedelta(days=freq_days), contract.redelivery_date)
        stmt = create_hire_statement(db, contract, cursor, period_end)
        statements.append(stmt)
        cursor = period_end

    return statements


def contract_summary(
    db: Session,
    contract: TimeCharterContract,
) -> dict:
    """Summary of a TC contract: linked voyages, total hire billed, outstanding."""
    voyages = db.scalars(
        select(Voyage).where(
            Voyage.tenant_id == contract.tenant_id,
            Voyage.tc_contract_id == contract.id,
        )
    ).all()

    statements = db.scalars(
        select(HireStatement).where(
            HireStatement.tenant_id == contract.tenant_id,
            HireStatement.contract_id == contract.id,
            HireStatement.status != "void",
        )
    ).all()

    total_billed = sum((_f(s.net_hire) for s in statements), _ZERO)
    total_paid = sum(
        (_f(s.net_hire) for s in statements if s.status == "paid"),
        _ZERO,
    )

    return {
        "contract_id": str(contract.id),
        "contract_type": contract.contract_type,
        "status": contract.status,
        "voyage_count": len(voyages),
        "voyages": [
            {"id": str(v.id), "voyage_no": v.voyage_no, "seq": v.tc_seq, "status": v.status}
            for v in sorted(voyages, key=lambda v: v.tc_seq or 0)
        ],
        "statement_count": len(statements),
        "total_billed": float(total_billed),
        "total_paid": float(total_paid),
        "outstanding": float(total_billed - total_paid),
        "currency": contract.hire_currency,
    }
