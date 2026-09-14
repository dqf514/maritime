"""IMO CII (Carbon Intensity Indicator) calculation and A–E rating.

Attained CII = annual CO2 [grams] / (capacity [DWT] × distance travelled [nm]).

Constants and their sources:
- Reference lines (2019), CII_ref = a · Capacity^(-c): IMO MEPC.328(76).
- Annual reduction factors z applied to the reference to get the required CII:
  IMO MEPC.338(76) (2023: 5 %, 2024: 7 %, 2025: 9 %, 2026: 11 %; years beyond
  2026 reuse the 2026 factor until IMO publishes further values).
- Rating boundaries (exp(dd) vectors around the required CII): IMO MEPC.354(78)
  — superior/lower/upper/inferior boundaries per ship type.

Only bulk carrier / tanker / general cargo are parameterised; unknown ship
types fall back to the bulk carrier parameters.
"""

from __future__ import annotations

# MEPC.328(76): (a, c) per ship type, capacity in DWT.
_REFERENCE_PARAMS: dict[str, tuple[float, float]] = {
    "bulk_carrier": (4745.0, 0.622),
    "tanker": (5247.0, 0.610),
    "general_cargo": (588.0, 0.3885),
}

# MEPC.354(78): (superior, lower, upper, inferior) boundary vectors.
_RATING_VECTORS: dict[str, tuple[float, float, float, float]] = {
    "bulk_carrier": (0.86, 0.94, 1.06, 1.18),
    "tanker": (0.82, 0.93, 1.08, 1.28),
    "general_cargo": (0.83, 0.94, 1.06, 1.19),
}

# MEPC.338(76): reduction factor z vs the 2019 reference line.
_REDUCTION_FACTORS: dict[int, float] = {2023: 0.05, 2024: 0.07, 2025: 0.09, 2026: 0.11}

DEFAULT_SHIP_TYPE = "bulk_carrier"


def _params(ship_type: str | None) -> tuple[float, float]:
    return _REFERENCE_PARAMS.get(ship_type or "", _REFERENCE_PARAMS[DEFAULT_SHIP_TYPE])


def _vector(ship_type: str | None) -> tuple[float, float, float, float]:
    return _RATING_VECTORS.get(ship_type or "", _RATING_VECTORS[DEFAULT_SHIP_TYPE])


def reference_cii(dwt: float, ship_type: str | None = None) -> float:
    """2019 reference CII for the given capacity (MEPC.328(76))."""
    a, c = _params(ship_type)
    return a * float(dwt) ** (-c)


def required_cii(dwt: float, year: int, ship_type: str | None = None) -> float:
    """Required annual operational CII for the given year (MEPC.338(76))."""
    z = _REDUCTION_FACTORS.get(year)
    if z is None:
        z = 0.0 if year < 2023 else _REDUCTION_FACTORS[2026]
    return reference_cii(dwt, ship_type) * (1 - z)


def attained_cii(co2_mt: float, dwt: float, distance_nm: float) -> float:
    """Attained annual operational CII in gCO2 / (DWT · nm)."""
    if dwt <= 0 or distance_nm <= 0:
        raise ValueError("dwt and distance_nm must be > 0")
    return float(co2_mt) * 1_000_000 / (float(dwt) * float(distance_nm))


def rate_cii(
    co2_mt: float,
    dwt: float,
    distance_nm: float,
    year: int,
    ship_type: str | None = None,
) -> dict:
    """Full CII snapshot: attained vs required and the A–E rating."""
    attained = attained_cii(co2_mt, dwt, distance_nm)
    required = required_cii(dwt, year, ship_type)
    sup, low, up, inf = _vector(ship_type)
    if attained <= sup * required:
        rating = "A"
    elif attained <= low * required:
        rating = "B"
    elif attained <= up * required:
        rating = "C"
    elif attained <= inf * required:
        rating = "D"
    else:
        rating = "E"
    return {
        "attained_cii": round(attained, 4),
        "required_cii": round(required, 4),
        "rating": rating,
        "year": year,
        "ship_type": ship_type or DEFAULT_SHIP_TYPE,
    }
