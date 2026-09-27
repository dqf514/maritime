"""船队敞口（Phase 2 / D23）：未来 30/60/90 天已锁定租金敞口 + 敏感度。

口径：
- 敞口 = 生效 TC 租约（time/tct, active）的 hire_per_day × 窗口内剩余天数
  （截断到 redelivery_at，无还船期则满窗口）；
- 敏感度 = 窗口天数 × ±sensitivity_per_day（默认 $1000/天）；
- 已锁定 vs 市场：给 market_hire_rate 时输出对市场差额（正=锁定贵）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Charter

WINDOWS = (30, 60, 90)


def _as_date(v) -> date | None:
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else v


def fleet_exposure(
    db: Session,
    tenant_id,
    *,
    horizon_days: int = 90,
    market_hire_rate: float | None = None,
    sensitivity_per_day: float = 1000.0,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or datetime.now(timezone.utc).date()
    charters = db.scalars(
        select(Charter).where(
            Charter.tenant_id == tenant_id,
            Charter.status == "active",
            Charter.charter_type.in_(["time", "tct"]),
            Charter.hire_per_day.is_not(None),
        )
    ).all()

    windows: dict[str, dict[str, Any]] = {}
    for w in WINDOWS:
        if w > horizon_days:
            continue
        locked = Decimal("0")
        days_covered = Decimal("0")
        for c in charters:
            end = _as_date(c.redelivery_at) or (today.toordinal() + w)
            end_ord = end.toordinal() if isinstance(end, date) else int(end)
            remaining_days = max(0, min(today.toordinal() + w, end_ord) - today.toordinal())
            if remaining_days <= 0:
                continue
            locked += Decimal(str(c.hire_per_day)) * remaining_days
            days_covered += remaining_days
        sens = Decimal(str(sensitivity_per_day))
        entry: dict[str, Any] = {
            "locked_hire": float(locked),
            "charter_days": float(days_covered),
            "sensitivity_up": float(locked + days_covered * sens),
            "sensitivity_down": float(max(Decimal("0"), locked - days_covered * sens)),
        }
        if market_hire_rate is not None:
            entry["market_hire"] = float(Decimal(str(market_hire_rate)) * days_covered)
            entry["vs_market"] = float(locked - Decimal(str(market_hire_rate)) * days_covered)
        windows[str(w)] = entry

    return {
        "as_of": today.isoformat(),
        "charters": [{"id": str(c.id), "charter_no": c.charter_no, "hire_per_day": float(c.hire_per_day)} for c in charters],
        "windows": windows,
        "sensitivity_per_day": sensitivity_per_day,
    }
