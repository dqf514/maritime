"""Estimate input enrichment from vessel master / fuel zones / market quotes.

Track 1 (同事意见 #2)：船速与油耗在船舶档案里维护，Fuel zone / EU ETS 计算要用
它们；此前 estimate_engine 只认手动输入，档案数据是“断链”的。本模块在
compute_estimate 计算前把缺失字段从主数据补全：

- 航速/油耗：legs[].speed_kn ← vessel.sea_speed_75 | speed_knots | design_speed；
  bunker_sea_tpd ← vessel.consumption_sea；bunker_port_tpd ← vessel.port_working
  | consumption_port（仅填缺失值，显式输入永远优先）。
- EU ETS 份额：按航线挂靠港序列相邻对平均（与 compliance_report.infer_eu_share
  同一约定：EU↔EU=1，EU↔非=0.5，非↔非=0）。港口归属判定：Port.is_eu 标志，
  或港口坐标落在 zone_type ∈ {eu_ets, fueleu} 的燃油区多边形内。
- ets_price：取租户最新 MarketQuote（symbol ∈ EUA/ETS 系列）；无行情时回退
  carbon_calculator.EU_ETS_CO2_PRICE 常量。
- eca_days：挂靠港坐标全部/部分落在 ECA 多边形时，按在 ECA 内的港口占比 ×
  sea_days 估算（仅在 eca_days 缺失且 sea_days 已知时填充；简化端点法，
  精确航路点法留给 voyage 执行阶段）。

只有在调用方传入 db + tenant_id 且 inputs 含 vessel_id 时才生效——gold fixtures
与纯算术调用完全不受影响。返回值不修改原 inputs（浅拷贝 + legs 拷贝）。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import MarketQuote
from app.models_wave1 import Port, Vessel
from app.services.carbon_calculator import EU_ETS_CO2_PRICE
from app.services.tenant_guard import scoped_get

# MarketQuote symbols accepted as an EU ETS allowance price (most recent wins).
_EUA_SYMBOLS = ("EUA", "EU_ETS", "EUETS", "ETS_EUA")


def _empty(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _find_port(db: Session, ref: Any) -> Port | None:
    """Resolve a port reference (UN/LOCODE or name) to a Port row."""
    if _empty(ref):
        return None
    token = str(ref).strip()
    port = db.scalar(select(Port).where(Port.unlocode == token.upper()))
    if port is None:
        port = db.scalar(select(Port).where(Port.name.ilike(token)))
    return port


def _port_is_eu(db: Session, port: Port, zone_cache: dict[tuple[float, float], list[dict]]) -> bool:
    if port.is_eu:
        return True
    if port.latitude is not None and port.longitude is not None:
        key = (float(port.latitude), float(port.longitude))
        if key not in zone_cache:
            from app.services.fuel_zone_service import get_zones_at_position

            zone_cache[key] = get_zones_at_position(db, key[0], key[1])
        return any(z.get("zone_type") in ("eu_ets", "fueleu") for z in zone_cache[key])
    return False


def _port_in_eca(db: Session, port: Port, zone_cache: dict[tuple[float, float], list[dict]]) -> bool | None:
    """True/False when the port position resolves to zones; None when no coords."""
    if port.latitude is None or port.longitude is None:
        return None
    key = (float(port.latitude), float(port.longitude))
    if key not in zone_cache:
        from app.services.fuel_zone_service import get_zones_at_position

        zone_cache[key] = get_zones_at_position(db, key[0], key[1])
    return any(z.get("zone_type") == "eca" for z in zone_cache[key])


def _latest_ets_price(db: Session, tenant_id: Any) -> Decimal | None:
    """Most recent tenant MarketQuote carrying an EUA / EU-ETS price."""
    rows = (
        db.scalars(
            select(MarketQuote)
            .where(
                MarketQuote.tenant_id == tenant_id,
                MarketQuote.symbol.in_(_EUA_SYMBOLS),
            )
            .order_by(MarketQuote.quote_date.desc())
        ).all()
    )
    if not rows:
        return None
    return Decimal(str(rows[0].value))


def enrich_estimate_inputs(
    inputs: dict[str, Any], db: Session, tenant_id: Any
) -> tuple[dict[str, Any], dict[str, str]]:
    """Fill missing estimate inputs from vessel master / fuel zones / market.

    Returns ``(new_inputs, provenance)``; ``inputs`` is never mutated.
    Provenance maps result-visible field names to a human-readable source
    (surfaced in results["inputs_enriched"]). No-op (returns inputs as-is,
    empty provenance) when vessel_id is absent or the vessel row is missing.
    """
    vessel_id = inputs.get("vessel_id")
    if _empty(vessel_id):
        return inputs, {}
    # JSON inputs carry vessel_id as a string — coerce to UUID so the Uuid
    # column comparison works on Postgres too (SQLite is lenient).
    if isinstance(vessel_id, str):
        import uuid as _uuid

        try:
            vessel_id = _uuid.UUID(vessel_id)
        except ValueError:
            return inputs, {}
    vessel = scoped_get(db, Vessel, vessel_id, tenant_id)
    if vessel is None:
        return inputs, {}

    # Work on a copy — never mutate the caller's (possibly ORM-persisted) dict.
    new_inputs: dict[str, Any] = dict(inputs)
    legs_raw = new_inputs.get("legs")
    if legs_raw:
        new_inputs["legs"] = [dict(leg) for leg in legs_raw]
    prov: dict[str, str] = {}

    # ── 1. 航速 / 海上与港口油耗（船舶档案 → legs / 顶层缺省值）──
    sea_speed = vessel.sea_speed_75 or vessel.speed_knots or vessel.design_speed
    for i, leg in enumerate(new_inputs.get("legs") or []):
        if _empty(leg.get("speed_kn")) and sea_speed:
            leg["speed_kn"] = float(sea_speed)
            prov[f"legs[{i}].speed_kn"] = "vessel.sea_speed_75|speed_knots|design_speed"
        if _empty(leg.get("bunker_sea_tpd")) and vessel.consumption_sea:
            leg["bunker_sea_tpd"] = float(vessel.consumption_sea)
            prov[f"legs[{i}].bunker_sea_tpd"] = "vessel.consumption_sea"
        if _empty(leg.get("bunker_port_tpd")) and (vessel.port_working or vessel.consumption_port):
            leg["bunker_port_tpd"] = float(vessel.port_working or vessel.consumption_port)
            prov[f"legs[{i}].bunker_port_tpd"] = "vessel.port_working|consumption_port"
    if not new_inputs.get("legs"):
        if _empty(new_inputs.get("bunker_sea_tpd")) and vessel.consumption_sea:
            new_inputs["bunker_sea_tpd"] = float(vessel.consumption_sea)
            prov["bunker_sea_tpd"] = "vessel.consumption_sea"
        if _empty(new_inputs.get("bunker_port_tpd")) and (vessel.port_working or vessel.consumption_port):
            new_inputs["bunker_port_tpd"] = float(vessel.port_working or vessel.consumption_port)
            prov["bunker_port_tpd"] = "vessel.port_working|consumption_port"

    # ── 2. 挂靠港序列（legs 优先，退化到顶层 load/disch_port）──
    port_refs: list[Any] = []
    legs = new_inputs.get("legs") or []
    if legs:
        for leg in legs:
            port_refs.append(leg.get("from_port"))
        port_refs.append(legs[-1].get("to_port"))
    else:
        port_refs = [new_inputs.get("load_port"), new_inputs.get("disch_port")]
    ports: list[Port] = []
    for ref in port_refs:
        port = _find_port(db, ref)
        if port is not None and (not ports or ports[-1].id != port.id):
            ports.append(port)

    zone_cache: dict[tuple[float, float], list[dict]] = {}

    # ── 3. eu_ets_share（相邻挂靠对平均，端点法）──
    if _empty(new_inputs.get("eu_ets_share")) and len(ports) >= 2:
        eu_flags = [_port_is_eu(db, p, zone_cache) for p in ports]
        pairs = [1.0 if eu_flags[i] and eu_flags[i + 1] else 0.5 if eu_flags[i] or eu_flags[i + 1] else 0.0
                 for i in range(len(eu_flags) - 1)]
        share = sum(pairs) / len(pairs)
        if share > 0:
            new_inputs["eu_ets_share"] = share
            prov["eu_ets_share"] = "port sequence is_eu/fuel-zone pair average"

    # ── 4. ets_price（市场行情 → 常量回退）——仅在确定会产生 ETS 成本时填充 ──
    if _empty(new_inputs.get("ets_price")) and _d_pos(new_inputs.get("eu_ets_share")):
        price = _latest_ets_price(db, tenant_id)
        if price is not None:
            new_inputs["ets_price"] = float(price)
            prov["ets_price"] = "market.EUA quote"
        else:
            new_inputs["ets_price"] = float(EU_ETS_CO2_PRICE)
            prov["ets_price"] = "carbon_calculator.EU_ETS_CO2_PRICE fallback"

    # ── 5. eca_days（ECA 挂靠港占比 × sea_days，简化端点法）──
    if _empty(new_inputs.get("eca_days")) and ports:
        sea_days = _d_pos(new_inputs.get("sea_days"))
        if sea_days:
            eca_flags = [_port_in_eca(db, p, zone_cache) for p in ports]
            resolved = [f for f in eca_flags if f is not None]
            if resolved:
                frac = sum(1 for f in resolved if f) / len(resolved)
                if frac > 0:
                    new_inputs["eca_days"] = round(sea_days * frac, 2)
                    prov["eca_days"] = "fuel-zone ECA endpoint share × sea_days"

    return new_inputs, prov


def _d_pos(v: Any) -> float | None:
    """Positive float value or None (for gating enrichment decisions)."""
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None
