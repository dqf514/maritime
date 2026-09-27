"""航速油耗保证索赔引擎（Phase 1 / D5）。

行业口径：
- 仅在**好天气时段**评估（默认风力 ≤ good_weather_max_wind_bf 且海况 ≤ moderate）；
- 航速保证带 "about" 容差（默认 0.5 节）：实测 + 容差 < 保证航速即失速；
- 失速损失时间 = shortfall / 保证航速 × 24h，折算天数计索赔；
- 油耗超保证（容差默认 5%）按超耗量计索赔；
- 金额 = 失速天数 × claim_rate_per_day + 超耗 × fuel_price_per_mt。

引擎为纯函数（Decimal），API 层负责从 NoonReport 派生 day 行。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

TWOPLACES = Decimal("0.01")

_GOOD_SEA_STATES = {"smooth", "slight", "moderate", ""}


def _d(v: Any, default: str = "0") -> Decimal:
    if v is None or v == "":
        return Decimal(default)
    return Decimal(str(v))


def compute_performance(inputs: dict[str, Any]) -> dict[str, Any]:
    warranty_speed = _d(inputs.get("warranty_speed_kn"))
    if warranty_speed <= 0:
        raise ValueError("warranty_speed_kn must be > 0")
    about_kn = _d(inputs.get("about_kn"), "0.5")
    warranty_cons = _d(inputs.get("warranty_consumption_mt_day"))
    cons_tol_pct = _d(inputs.get("consumption_tolerance_pct"), "0.05")
    max_wind_bf = _d(inputs.get("good_weather_max_wind_bf"), "4")
    claim_rate = _d(inputs.get("claim_rate_per_day"))
    fuel_price = _d(inputs.get("fuel_price_per_mt"))

    rows_out: list[dict[str, Any]] = []
    lost_hours = Decimal("0")
    excess_mt = Decimal("0")
    good_days = 0
    assessed_days = 0

    for day in inputs.get("days") or []:
        wind = day.get("wind_bf")
        sea = str(day.get("sea_state") or "").lower()
        good_weather = (wind is None or _d(wind) <= max_wind_bf) and sea in _GOOD_SEA_STATES
        hours = _d(day.get("hours_underway"), "24")
        row: dict[str, Any] = {
            "date": day.get("date"),
            "speed_kn": float(_d(day.get("speed_kn")).quantize(TWOPLACES)),
            "cons_mt_day": float(_d(day.get("cons_mt_day")).quantize(TWOPLACES)),
            "wind_bf": float(_d(wind)) if wind is not None else None,
            "sea_state": day.get("sea_state"),
            "good_weather": good_weather,
        }
        if not good_weather:
            row["note"] = "excluded (not good weather)"
            rows_out.append(row)
            continue
        good_days += 1
        assessed_days += 1

        speed = _d(day.get("speed_kn"))
        if speed > 0 and speed + about_kn < warranty_speed:
            shortfall_kn = warranty_speed - about_kn - speed
            day_lost_h = (shortfall_kn / warranty_speed * hours).quantize(TWOPLACES)
            lost_hours += day_lost_h
            row["speed_shortfall_kn"] = float(shortfall_kn.quantize(TWOPLACES))
            row["lost_hours"] = float(day_lost_h)
        cons = _d(day.get("cons_mt_day"))
        if warranty_cons > 0 and cons > warranty_cons * (Decimal("1") + cons_tol_pct):
            excess = (cons - warranty_cons).quantize(TWOPLACES)
            excess_mt += excess
            row["cons_excess_mt"] = float(excess)
        rows_out.append(row)

    lost_days = (lost_hours / Decimal("24")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    amount = (lost_days * claim_rate + excess_mt * fuel_price).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    return {
        "days": rows_out,
        "total_days": len(rows_out),
        "good_weather_days": good_days,
        "lost_time_hours": float(lost_hours.quantize(TWOPLACES)),
        "lost_time_days": float(lost_days),
        "excess_consumption_mt": float(excess_mt.quantize(TWOPLACES)),
        "amount": float(amount),
        "currency": inputs.get("currency") or "USD",
    }
