"""Advanced pricing engine — Worldscale, differential freight, rate scales."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_reference import PortDistance, WorldscaleRate

_D = Decimal
_ZERO = _D("0")
_CENT = _D("0.01")


def _f(val) -> _D:
    if val is None:
        return _ZERO
    return _D(str(val))


class WorldscaleCalculator:
    """Worldscale freight = cargo_qty × flat_rate × (ws_pct / 100)."""

    @staticmethod
    def calculate(
        cargo_qty_mt: Decimal,
        ws_flat: Decimal,
        ws_pct: Decimal,
    ) -> Decimal:
        return (_f(cargo_qty_mt) * _f(ws_flat) * _f(ws_pct) / _D("100")).quantize(
            _CENT, ROUND_HALF_UP
        )

    @staticmethod
    def lookup(
        db: Session,
        from_port: str,
        to_port: str,
        year: int,
    ) -> WorldscaleRate | None:
        row = db.scalars(
            select(WorldscaleRate).where(
                WorldscaleRate.from_port_unlocode == from_port,
                WorldscaleRate.to_port_unlocode == to_port,
                WorldscaleRate.year == year,
            )
        ).first()
        return row


class DifferentialFreightCalculator:
    """Differential freight = (actual_rate − base_rate) × cargo_qty."""

    @staticmethod
    def calculate(
        base_rate: Decimal,
        actual_rate: Decimal,
        cargo_qty_mt: Decimal,
    ) -> Decimal:
        return ((_f(actual_rate) - _f(base_rate)) * _f(cargo_qty_mt)).quantize(
            _CENT, ROUND_HALF_UP
        )


class FreightRateScale:
    """Tiered freight rates by cargo quantity.

    rate_tiers: [(min_qty, max_qty, rate), ...]
    max_qty=None means unlimited.
    """

    @staticmethod
    def calculate(
        cargo_qty_mt: Decimal,
        rate_tiers: list[tuple[Decimal | None, Decimal | None, Decimal]],
    ) -> Decimal:
        qty = _f(cargo_qty_mt)
        for min_q, max_q, rate in rate_tiers:
            lo = _f(min_q) if min_q is not None else _ZERO
            hi = _f(max_q) if max_q is not None else None
            if qty >= lo and (hi is None or qty <= hi):
                return (qty * _f(rate)).quantize(_CENT, ROUND_HALF_UP)
        return _ZERO


class DeadfreightCalculator:
    """Deadfreight = (nominal_qty − loaded_qty) × freight_rate."""

    @staticmethod
    def calculate(
        nominal_qty: Decimal,
        loaded_qty: Decimal,
        freight_rate: Decimal,
    ) -> Decimal:
        shortfall = _f(nominal_qty) - _f(loaded_qty)
        if shortfall <= _ZERO:
            return _ZERO
        return (shortfall * _f(freight_rate)).quantize(_CENT, ROUND_HALF_UP)


class AdvancedPricingEngine:
    """Unified pricing facade — dispatches to the appropriate calculator."""

    @staticmethod
    def price_voyage(
        db: Session,
        freight_basis: str,
        cargo_qty_mt: Decimal,
        freight_rate: Decimal | None = None,
        ws_pct: Decimal | None = None,
        from_port: str | None = None,
        to_port: str | None = None,
        year: int | None = None,
    ) -> dict:
        """Calculate freight revenue based on the fixture's pricing basis."""
        qty = _f(cargo_qty_mt)
        result: dict = {"cargo_qty": float(qty), "basis": freight_basis}

        if freight_basis == "worldscale" and from_port and to_port and year:
            ws = WorldscaleCalculator.lookup(db, from_port, to_port, year)
            if ws:
                flat = _f(ws.flat_rate)
                pct = _f(ws_pct) if ws_pct else _D("100")
                freight = WorldscaleCalculator.calculate(qty, flat, pct)
                result.update({
                    "ws_flat": float(flat),
                    "ws_pct": float(pct),
                    "freight": float(freight),
                })
            else:
                result["error"] = "No worldscale rate found for this port pair/year"
        elif freight_basis == "per_mt" and freight_rate is not None:
            freight = (qty * _f(freight_rate)).quantize(_CENT, ROUND_HALF_UP)
            result.update({"rate": float(_f(freight_rate)), "freight": float(freight)})
        elif freight_basis == "lumpsum" and freight_rate is not None:
            result.update({"freight": float(_f(freight_rate))})
        else:
            result["error"] = f"Unsupported basis: {freight_basis}"

        return result
