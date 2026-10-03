"""Hire statement engine for time-charter contracts.

Calculates periodic hire statements with off-hire deductions,
bunker adjustments, and line-by-line breakdown. Phase 5 TC depth adds
bareboat statements, tiered profit share, billing schedules, sub-TC
rollups and GL period-journal allocation.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import OffHireEvent, Voyage
from app.models_gl import PeriodJournal
from app.models_time_charter import (
    HireBillingSchedule,
    HireStatement,
    ProfitShareRule,
    TimeCharterContract,
)
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


# ── Phase 5 TC depth ─────────────────────────────────────────────────────────


def _get_contract(db: Session, tc_contract_id: uuid.UUID) -> TimeCharterContract:
    contract = db.get(TimeCharterContract, tc_contract_id)
    if contract is None:
        raise ValueError(f"TC contract {tc_contract_id} not found")
    return contract


def calculate_profit_share(
    db: Session,
    tc_contract_id: uuid.UUID,
    period_tce: Decimal,
) -> dict:
    """Tiered profit share on the TCE excess above the contract threshold.

    Rules (``ProfitShareRule``) bound TCE bands; ``share_pct`` is the owner's
    share of the excess inside each band. With no rules the contract-level
    ``profit_share_pct`` applies to the whole excess. Deterministic Decimal math.
    """
    contract = _get_contract(db, tc_contract_id)
    tce = _f(period_tce)
    threshold = _f(contract.profit_share_threshold)
    excess_total = tce - threshold if tce > threshold else _ZERO

    rules = db.scalars(
        select(ProfitShareRule)
        .where(
            ProfitShareRule.tenant_id == contract.tenant_id,
            ProfitShareRule.tc_contract_id == tc_contract_id,
        )
        .order_by(ProfitShareRule.tier_from)
    ).all()

    tiers_applied: list[dict] = []
    owner_share = _ZERO
    basis = "tce"

    if excess_total > _ZERO:
        if rules:
            for rule in rules:
                tier_lo = _f(rule.tier_from)
                tier_hi = _f(rule.tier_to) if rule.tier_to is not None else None
                lo = max(tier_lo, threshold)
                hi = min(tier_hi, tce) if tier_hi is not None else tce
                if hi <= lo:
                    continue
                band_amount = hi - lo
                share = (band_amount * _f(rule.share_pct) / _D("100")).quantize(
                    _CENT, ROUND_HALF_UP
                )
                owner_share += share
                basis = rule.basis or basis
                tiers_applied.append(
                    {
                        "rule_id": str(rule.id),
                        "tier_from": float(tier_lo),
                        "tier_to": float(tier_hi) if tier_hi is not None else None,
                        "share_pct": float(_f(rule.share_pct)),
                        "basis": rule.basis,
                        "band_amount": float(band_amount),
                        "owner_share": float(share),
                    }
                )
        else:
            flat_pct = _f(contract.profit_share_pct)
            if flat_pct > _ZERO:
                owner_share = (excess_total * flat_pct / _D("100")).quantize(
                    _CENT, ROUND_HALF_UP
                )
                tiers_applied.append(
                    {
                        "rule_id": None,
                        "tier_from": float(threshold),
                        "tier_to": None,
                        "share_pct": float(flat_pct),
                        "basis": basis,
                        "band_amount": float(excess_total),
                        "owner_share": float(owner_share),
                    }
                )

    return {
        "tc_contract_id": str(contract.id),
        "period_tce": float(tce),
        "threshold": float(threshold),
        "excess": float(excess_total),
        "owner_share": float(owner_share),
        "charterer_share": float(excess_total - owner_share),
        "basis": basis,
        "tiers": tiers_applied,
    }


def generate_billing_schedule(
    db: Session,
    tc_contract_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> list[HireBillingSchedule]:
    """Auto-generate hire billing rows from the contract payment_frequency.

    Periods are fixed 30-day (monthly) or 15-day (semi_monthly) chunks, matching
    ``generate_all_statements``. Amounts are gross hire (hire_rate × days);
    periods that already have a schedule row are skipped (regenerate-safe).
    """
    contract = _get_contract(db, tc_contract_id)
    if end_date <= start_date:
        raise ValueError("end_date must be after start_date")

    freq_days = 15 if contract.payment_frequency == "semi_monthly" else 30
    hire_rate = _f(contract.hire_rate)

    existing = {
        row.period_start
        for row in db.scalars(
            select(HireBillingSchedule).where(
                HireBillingSchedule.tenant_id == contract.tenant_id,
                HireBillingSchedule.tc_contract_id == tc_contract_id,
            )
        ).all()
    }

    rows: list[HireBillingSchedule] = []
    cursor = start_date
    while cursor < end_date:
        period_end = min(cursor + timedelta(days=freq_days), end_date)
        if cursor not in existing:
            days = _D(str((period_end - cursor).days))
            row = HireBillingSchedule(
                tenant_id=contract.tenant_id,
                tc_contract_id=contract.id,
                period_start=cursor,
                period_end=period_end,
                due_date=period_end,
                amount=(days * hire_rate).quantize(_CENT, ROUND_HALF_UP),
                status="draft",
            )
            db.add(row)
            rows.append(row)
        cursor = period_end

    db.flush()
    return rows


def bareboat_hire_statement(
    db: Session,
    tc_contract_id: uuid.UUID,
    period: tuple[date, date],
) -> dict:
    """Bareboat (光船) hire statement for ``period`` = (period_start, period_end).

    Bareboat hire runs for the full calendar period — the charterer bears
    off-hire risk, so there is no off-hire deduction. Address commission and
    brokerage (contract-level percentages) are deducted from gross hire.
    """
    contract = _get_contract(db, tc_contract_id)
    period_start, period_end = period
    if period_end <= period_start:
        raise ValueError("period_end must be after period_start")

    hire_rate = _f(contract.hire_rate)
    contract_start = contract.delivery_date or period_start
    contract_end = contract.redelivery_date or period_end

    effective_days = _days_in_period(
        contract_start, contract_end, period_start, period_end
    )
    gross_hire = (effective_days * hire_rate).quantize(_CENT, ROUND_HALF_UP)

    address_comm = (gross_hire * _f(contract.address_comm_pct) / _D("100")).quantize(
        _CENT, ROUND_HALF_UP
    )
    brokerage = (gross_hire * _f(contract.brokerage_pct) / _D("100")).quantize(
        _CENT, ROUND_HALF_UP
    )
    net_hire = (gross_hire - address_comm - brokerage).quantize(_CENT, ROUND_HALF_UP)

    return {
        "tc_contract_id": str(contract.id),
        "contract_style": "bareboat",
        "period_start": period_start,
        "period_end": period_end,
        "hire_days": effective_days,
        "off_hire_days": _ZERO,
        "gross_hire": gross_hire,
        "address_commission": address_comm,
        "brokerage": brokerage,
        "net_hire": net_hire,
        "currency": contract.hire_currency,
        "breakdown": {
            "lines": [
                {
                    "label": "Bareboat Hire (full period, no off-hire relief)",
                    "days": str(effective_days),
                    "rate": str(hire_rate),
                    "amount": str(gross_hire),
                },
                {
                    "label": "Address Commission",
                    "amount": f"-{address_comm}",
                },
                {
                    "label": "Brokerage",
                    "amount": f"-{brokerage}",
                },
                {"label": "Net Hire", "amount": str(net_hire)},
            ]
        },
    }


def child_tc_rollup(db: Session, parent_contract_id: uuid.UUID) -> dict:
    """Aggregate sub-TC (child) results under a parent TC contract."""
    parent = _get_contract(db, parent_contract_id)
    children = db.scalars(
        select(TimeCharterContract)
        .where(
            TimeCharterContract.tenant_id == parent.tenant_id,
            TimeCharterContract.parent_contract_id == parent_contract_id,
        )
        .order_by(TimeCharterContract.created_at)
    ).all()

    total_gross = _ZERO
    total_off_hire = _ZERO
    total_net = _ZERO
    child_rows: list[dict] = []
    for child in children:
        statements = db.scalars(
            select(HireStatement).where(
                HireStatement.tenant_id == parent.tenant_id,
                HireStatement.contract_id == child.id,
                HireStatement.status != "void",
            )
        ).all()
        gross = sum((_f(s.gross_hire) for s in statements), _ZERO)
        off_hire = sum((_f(s.off_hire_deduction) for s in statements), _ZERO)
        net = sum((_f(s.net_hire) for s in statements), _ZERO)
        total_gross += gross
        total_off_hire += off_hire
        total_net += net
        child_rows.append(
            {
                "id": str(child.id),
                "contract_type": child.contract_type,
                "contract_style": child.contract_style,
                "status": child.status,
                "hire_rate": float(_f(child.hire_rate)),
                "statement_count": len(statements),
                "gross_hire": float(gross),
                "off_hire_deduction": float(off_hire),
                "net_hire": float(net),
                "currency": child.hire_currency,
            }
        )

    return {
        "parent_contract_id": str(parent.id),
        "child_count": len(children),
        "total_gross_hire": float(total_gross),
        "total_off_hire_deduction": float(total_off_hire),
        "total_net_hire": float(total_net),
        "currency": parent.hire_currency,
        "children": child_rows,
    }


def allocate_period_journal(
    db: Session,
    tc_contract_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> PeriodJournal:
    """Link hire for the period to a GL PeriodJournal (accrual entries).

    TCO → debit hire_receivable / credit hire_revenue;
    TCI → debit hire_expense / credit hire_payable.
    Idempotent: an existing journal referencing this contract+period is returned.
    """
    contract = _get_contract(db, tc_contract_id)
    if contract.contract_style == "bareboat":
        calc = bareboat_hire_statement(db, tc_contract_id, (period_start, period_end))
    else:
        calc = calculate_hire_statement(db, contract, period_start, period_end)

    amount = _f(calc["net_hire"])
    period = period_start.strftime("%Y-%m")
    reference = f"tc:{contract.id}:{period_start}:{period_end}"

    existing = db.scalars(
        select(PeriodJournal).where(
            PeriodJournal.tenant_id == contract.tenant_id,
            PeriodJournal.period == period,
        )
    ).all()
    for journal in existing:
        for entry in journal.entries or []:
            if entry.get("reference") == reference:
                return journal

    if contract.contract_type == "tco":
        debit_account, credit_account = "hire_receivable", "hire_revenue"
    else:
        debit_account, credit_account = "hire_expense", "hire_payable"

    entries = [
        {
            "account": debit_account,
            "debit": str(amount),
            "credit": "0",
            "reference": reference,
            "description": f"TC hire {contract.contract_type} {period_start}~{period_end}",
        },
        {
            "account": credit_account,
            "debit": "0",
            "credit": str(amount),
            "reference": reference,
            "description": f"TC hire {contract.contract_type} {period_start}~{period_end}",
        },
    ]

    from app.services.gl_engine import post_journal

    journal = post_journal(
        db,
        contract.tenant_id,
        period,
        "accrual",
        entries,
        description=f"TC hire allocation {contract.id}",
    )
    return journal
