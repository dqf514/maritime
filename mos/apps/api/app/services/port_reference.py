"""Port reference data service.

Provides holiday checking, rate estimation, and restriction lookup.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.orm import Session

from app.models_reference import PortHoliday, PortRate, PortRestriction


# ── Holiday Management ──


def get_port_holidays(
    db: Session,
    port_unlocode: str | None = None,
    country: str | None = None,
    year: int | None = None,
) -> list[PortHoliday]:
    """Get port holidays with optional filters."""
    stmt = select(PortHoliday)
    if port_unlocode:
        stmt = stmt.where(PortHoliday.port_unlocode == port_unlocode)
    if country:
        stmt = stmt.where(PortHoliday.country == country)
    if year:
        stmt = stmt.where(PortHoliday.holiday_date.like(f"{year}%"))
    stmt = stmt.order_by(PortHoliday.holiday_date)
    return list(db.scalars(stmt).all())


def is_holiday(db: Session, port_unlocode: str, check_date: date) -> tuple[bool, str | None]:
    """Check if a date is a holiday at a port.

    Returns (is_holiday, holiday_name).
    """
    date_str = check_date.isoformat()
    holiday = db.scalars(
        select(PortHoliday).where(
            and_(
                PortHoliday.port_unlocode == port_unlocode,
                PortHoliday.holiday_date == date_str,
            )
        )
    ).first()
    if holiday:
        return True, holiday.holiday_name

    # Check recurring holidays (match month-day across years)
    month_day = date_str[5:]  # MM-DD
    recurring = db.scalars(
        select(PortHoliday).where(
            and_(
                PortHoliday.port_unlocode == port_unlocode,
                PortHoliday.recurring.is_(True),
                func.substr(PortHoliday.holiday_date, 6) == month_day,
            )
        )
    ).first()
    if recurring:
        return True, recurring.holiday_name

    return False, None


def count_working_days(
    db: Session, port_unlocode: str, start: date, end: date
) -> int:
    """Count working days between two dates (excluding weekends and holidays)."""
    working = 0
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            is_hol, _ = is_holiday(db, port_unlocode, current)
            if not is_hol:
                working += 1
        current = current.replace(day=current.day + 1) if current.day < 28 else _next_month(current)
    return working


def _next_month(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


def add_holiday(
    db: Session,
    port_unlocode: str,
    country: str,
    holiday_date: str,
    holiday_name: str,
    holiday_type: str = "public",
    recurring: bool = False,
) -> PortHoliday:
    """Add a port holiday."""
    holiday = PortHoliday(
        port_unlocode=port_unlocode,
        country=country,
        holiday_date=holiday_date,
        holiday_name=holiday_name,
        holiday_type=holiday_type,
        recurring=recurring,
    )
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday


# ── Rate Reference ──


def get_port_rates(
    db: Session,
    port_unlocode: str,
    rate_type: str | None = None,
    vessel_size_band: str = "medium",
) -> list[PortRate]:
    """Get port rate reference data."""
    stmt = select(PortRate).where(
        and_(
            PortRate.port_unlocode == port_unlocode,
            PortRate.vessel_size_band == vessel_size_band,
        )
    )
    if rate_type:
        stmt = stmt.where(PortRate.rate_type == rate_type)
    return list(db.scalars(stmt).all())


def estimate_port_costs(
    db: Session,
    port_unlocode: str,
    vessel_size_band: str = "medium",
    days: int = 1,
) -> dict:
    """Estimate total port costs for a call.

    Returns breakdown by rate type and total.
    """
    rates = get_port_rates(db, port_unlocode, vessel_size_band=vessel_size_band)
    breakdown = {}
    total = Decimal("0")

    for rate in rates:
        if rate.basis == "per_call":
            amount = rate.amount_usd
        elif rate.basis == "per_day":
            amount = rate.amount_usd * days
        else:
            amount = rate.amount_usd

        breakdown[rate.rate_type] = {
            "amount": float(amount),
            "basis": rate.basis,
            "currency": rate.currency,
        }
        total += amount

    return {"port_unlocode": port_unlocode, "breakdown": breakdown, "total_usd": float(total), "days": days}


def add_port_rate(
    db: Session,
    port_unlocode: str,
    rate_type: str,
    amount_usd: Decimal,
    vessel_size_band: str = "medium",
    currency: str = "USD",
    basis: str = "per_call",
    effective_from: str | None = None,
    source: str = "manual",
    notes: str | None = None,
) -> PortRate:
    """Add or update a port rate."""
    existing = db.scalars(
        select(PortRate).where(
            and_(
                PortRate.port_unlocode == port_unlocode,
                PortRate.rate_type == rate_type,
                PortRate.vessel_size_band == vessel_size_band,
            )
        )
    ).first()

    if existing:
        existing.amount_usd = amount_usd
        existing.currency = currency
        existing.basis = basis
        existing.effective_from = effective_from
        existing.source = source
        existing.notes = notes
        db.commit()
        db.refresh(existing)
        return existing

    rate = PortRate(
        port_unlocode=port_unlocode,
        rate_type=rate_type,
        vessel_size_band=vessel_size_band,
        amount_usd=amount_usd,
        currency=currency,
        basis=basis,
        effective_from=effective_from,
        source=source,
        notes=notes,
    )
    db.add(rate)
    db.commit()
    db.refresh(rate)
    return rate


# ── Restrictions ──


def get_port_restrictions(db: Session, port_unlocode: str) -> PortRestriction | None:
    """Get port restrictions."""
    return db.scalars(
        select(PortRestriction).where(PortRestriction.port_unlocode == port_unlocode)
    ).first()


def check_vessel_compatibility(
    db: Session, port_unlocode: str, draft_m: float, loa_m: float, dwt: float
) -> dict:
    """Check if a vessel can call at a port based on restrictions.

    Returns compatibility result with any violations.
    """
    restriction = get_port_restrictions(db, port_unlocode)
    if not restriction:
        return {"compatible": True, "violations": [], "port_unlocode": port_unlocode}

    violations = []
    if restriction.max_draft_m and draft_m > float(restriction.max_draft_m):
        violations.append(
            f"Draft {draft_m}m exceeds max {restriction.max_draft_m}m"
        )
    if restriction.max_loa_m and loa_m > float(restriction.max_loa_m):
        violations.append(
            f"LOA {loa_m}m exceeds max {restriction.max_loa_m}m"
        )
    if restriction.max_dwt and dwt > float(restriction.max_dwt):
        violations.append(
            f"DWT {dwt} exceeds max {restriction.max_dwt}"
        )

    return {
        "compatible": len(violations) == 0,
        "violations": violations,
        "port_unlocode": port_unlocode,
        "restrictions": {
            "max_draft_m": float(restriction.max_draft_m) if restriction.max_draft_m else None,
            "max_loa_m": float(restriction.max_loa_m) if restriction.max_loa_m else None,
            "max_dwt": float(restriction.max_dwt) if restriction.max_dwt else None,
            "berth_types": restriction.berth_types,
            "working_hours": restriction.working_hours,
            "night_work_allowed": restriction.night_work_allowed,
            "requires_pilot": restriction.requires_pilot,
        },
    }


def set_port_restrictions(
    db: Session,
    port_unlocode: str,
    max_draft_m: float | None = None,
    max_loa_m: float | None = None,
    max_beam_m: float | None = None,
    max_dwt: float | None = None,
    berth_types: list | None = None,
    cargo_types: list | None = None,
    working_hours: str | None = None,
    night_work_allowed: bool = True,
    sunday_work_allowed: bool = False,
    requires_pilot: bool = True,
    other_restrictions: str | None = None,
) -> PortRestriction:
    """Create or update port restrictions."""
    existing = get_port_restrictions(db, port_unlocode)
    if existing:
        if max_draft_m is not None:
            existing.max_draft_m = max_draft_m
        if max_loa_m is not None:
            existing.max_loa_m = max_loa_m
        if max_beam_m is not None:
            existing.max_beam_m = max_beam_m
        if max_dwt is not None:
            existing.max_dwt = max_dwt
        if berth_types is not None:
            existing.berth_types = berth_types
        if cargo_types is not None:
            existing.cargo_types = cargo_types
        if working_hours is not None:
            existing.working_hours = working_hours
        existing.night_work_allowed = night_work_allowed
        existing.sunday_work_allowed = sunday_work_allowed
        existing.requires_pilot = requires_pilot
        if other_restrictions is not None:
            existing.other_restrictions = other_restrictions
        db.commit()
        db.refresh(existing)
        return existing

    restriction = PortRestriction(
        port_unlocode=port_unlocode,
        max_draft_m=max_draft_m,
        max_loa_m=max_loa_m,
        max_beam_m=max_beam_m,
        max_dwt=max_dwt,
        berth_types=berth_types,
        cargo_types=cargo_types,
        working_hours=working_hours,
        night_work_allowed=night_work_allowed,
        sunday_work_allowed=sunday_work_allowed,
        requires_pilot=requires_pilot,
        other_restrictions=other_restrictions,
    )
    db.add(restriction)
    db.commit()
    db.refresh(restriction)
    return restriction
