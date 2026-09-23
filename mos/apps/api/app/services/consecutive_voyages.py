"""Consecutive voyage management for TC contracts.

Handles voyage sequencing, state inheritance, and TCO cost allocation
under time-charter contracts (TCI/TCO).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models_domain import Voyage
from app.models_time_charter import TimeCharterContract


def _f(val) -> float:
    """Coerce Decimal / None to float."""
    return float(val) if val is not None else 0.0


def get_contract_voyages(db: Session, contract_id: UUID) -> list[Voyage]:
    """Get all voyages under a TC contract, ordered by sequence."""
    return list(
        db.scalars(
            select(Voyage)
            .where(Voyage.tc_contract_id == contract_id)
            .order_by(Voyage.tc_seq)
        ).all()
    )


def get_next_voyage_seq(db: Session, contract_id: UUID) -> int:
    """Get the next sequence number for a voyage under a contract."""
    max_seq = db.scalar(
        select(func.max(Voyage.tc_seq)).where(Voyage.tc_contract_id == contract_id)
    )
    return (max_seq or 0) + 1


def get_previous_voyage(db: Session, contract_id: UUID, current_seq: int) -> Voyage | None:
    """Get the previous voyage in a consecutive sequence."""
    if current_seq <= 1:
        return None
    return db.scalar(
        select(Voyage).where(
            Voyage.tc_contract_id == contract_id,
            Voyage.tc_seq == current_seq - 1,
        )
    )


def inherit_voyage_state(db: Session, voyage: Voyage) -> dict:
    """Inherit vessel state from previous voyage in consecutive sequence.

    Returns dict with inherited values:
    - bunker_rob: Remaining bunker from previous voyage
    - vessel_position: Last known position
    - expected_start: Auto-calculated start date (previous voyage end + 1 day)
    """
    if not voyage.tc_contract_id or not voyage.tc_seq:
        return {}

    prev = get_previous_voyage(db, voyage.tc_contract_id, voyage.tc_seq)
    if not prev:
        return {}

    inherited = {}

    # Inherit bunker ROB (Remaining On Board)
    prev_results = prev.results or {}
    if "bunker_rob" in prev_results:
        inherited["bunker_rob"] = prev_results["bunker_rob"]

    # Inherit vessel position (last port)
    prev_schedule = prev.schedule or []
    if prev_schedule:
        last_port = prev_schedule[-1]
        inherited["vessel_position"] = last_port.get("port_unlocode")

    # Auto-calculate expected start date
    if prev.actual_end or prev.expected_end:
        end_date = prev.actual_end or prev.expected_end
        if isinstance(end_date, datetime):
            end_date = end_date.date()
        inherited["expected_start"] = end_date + timedelta(days=1)

    return inherited


def allocate_tco_costs(
    db: Session,
    contract_id: UUID,
    total_tco_cost: Decimal,
) -> dict:
    """Allocate TCO (Time Charter Operations) costs across voyages.

    Allocation is proportional to voyage duration (days).
    Stores allocation in voyage.results["tco_allocation"].

    Args:
        db: Database session
        contract_id: TC contract UUID
        total_tco_cost: Total TCO cost to allocate

    Returns:
        Dict mapping voyage_id to allocated amount
    """
    voyages = get_contract_voyages(db, contract_id)
    if not voyages:
        return {}

    # Calculate total voyage days
    voyage_days = []
    for v in voyages:
        if v.actual_start and v.actual_end:
            days = (v.actual_end - v.actual_start).days
        elif v.expected_start and v.expected_end:
            days = (v.expected_end - v.expected_start).days
        else:
            days = 14  # default 14 days if no dates
        voyage_days.append(max(days, 1))

    total_days = sum(voyage_days)
    if total_days == 0:
        return {}

    # Allocate proportionally
    allocations = {}
    for v, days in zip(voyages, voyage_days):
        share = (Decimal(days) / Decimal(total_days)) * total_tco_cost
        share_float = float(share.quantize(Decimal("0.01")))
        
        # Store in voyage results
        results = v.results or {}
        results["tco_allocation"] = {
            "amount": share_float,
            "currency": "USD",
            "contract_id": str(contract_id),
            "days": days,
            "total_days": total_days,
        }
        v.results = results
        allocations[str(v.id)] = share_float

    db.commit()
    return allocations


def create_consecutive_voyage(
    db: Session,
    tenant_id: UUID,
    contract_id: UUID,
    vessel_id: UUID,
    title: str | None = None,
) -> Voyage:
    """Create a new voyage in a consecutive sequence.

    Automatically:
    - Assigns next sequence number
    - Inherits vessel state from previous voyage
    - Links to TC contract

    Args:
        db: Database session
        tenant_id: Tenant UUID
        contract_id: TC contract UUID
        vessel_id: Vessel UUID
        title: Optional voyage title

    Returns:
        New Voyage with inherited state
    """
    contract = db.get(TimeCharterContract, contract_id)
    if not contract or contract.tenant_id != tenant_id:
        raise ValueError("Contract not found")

    # Get next sequence number
    seq = get_next_voyage_seq(db, contract_id)

    # Generate voyage number
    from app.services.doc_numbers import next_doc_number
    voyage_no = next_doc_number(db, tenant_id, Voyage, Voyage.voyage_no, "V")

    voyage = Voyage(
        tenant_id=tenant_id,
        voyage_no=voyage_no,
        vessel_id=vessel_id,
        tc_contract_id=contract_id,
        tc_seq=seq,
        title=title or f"TC Voyage #{seq}",
        status="planned",
    )
    db.add(voyage)
    db.flush()

    # Inherit state from previous voyage
    inherited = inherit_voyage_state(db, voyage)
    if inherited:
        voyage.results = {**(voyage.results or {}), **inherited}
        if "expected_start" in inherited:
            voyage.expected_start = inherited["expected_start"]

    db.commit()
    db.refresh(voyage)
    return voyage


def contract_voyages_summary(db: Session, contract_id: UUID) -> dict:
    """Get summary of consecutive voyages under a TC contract.

    Returns:
        {
            "contract_id": str,
            "voyage_count": int,
            "voyages": [
                {
                    "voyage_id": str,
                    "voyage_no": str,
                    "tc_seq": int,
                    "status": str,
                    "expected_start": date,
                    "expected_end": date,
                    "actual_start": date,
                    "actual_end": date,
                    "bunker_rob": float,
                },
                ...
            ],
            "total_days": int,
            "completed_count": int,
        }
    """
    voyages = get_contract_voyages(db, contract_id)

    voyage_list = []
    total_days = 0
    completed = 0

    for v in voyages:
        days = 0
        if v.actual_start and v.actual_end:
            days = (v.actual_end - v.actual_start).days
            completed += 1
        elif v.expected_start and v.expected_end:
            days = (v.expected_end - v.expected_start).days

        total_days += days
        results = v.results or {}

        voyage_list.append({
            "voyage_id": str(v.id),
            "voyage_no": v.voyage_no,
            "tc_seq": v.tc_seq,
            "status": v.status,
            "expected_start": v.expected_start,
            "expected_end": v.expected_end,
            "actual_start": v.actual_start,
            "actual_end": v.actual_end,
            "bunker_rob": results.get("bunker_rob"),
            "days": days,
        })

    return {
        "contract_id": str(contract_id),
        "voyage_count": len(voyages),
        "voyages": voyage_list,
        "total_days": total_days,
        "completed_count": completed,
    }
