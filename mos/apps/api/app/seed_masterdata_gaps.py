"""走查补种 (masterdata gaps) — 港口距离 / 货物品名 / 港口与船舶字段回填。

距离是全局参照（无 tenant_id），货品/回填只针对 demo 租户。
全部幂等：按自然键存在性闸门，仅补空字段，不覆盖已有人工编辑。
由 main.py lifespan 在 seed_full_demo_flow 之后调用。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session


# ── 1. 港口距离（全局）—— 覆盖 6 个 demo 港口两两 + 好望角/运河变体 ──
# (from, to, route_type, canal_transit, distance_nm, transit_days, notes)
_DISTANCES: list[tuple[str, str, str, str | None, str, str, str]] = [
    ("SGSIN", "NLRTM", "canal", "suez", "8280.0", "24.6", "via Suez"),
    ("NLRTM", "SGSIN", "canal", "suez", "8280.0", "24.6", "via Suez"),
    ("SGSIN", "NLRTM", "cape", None, "11800.0", "35.1", "via Cape of Good Hope"),
    ("NLRTM", "SGSIN", "cape", None, "11800.0", "35.1", "via Cape of Good Hope"),
    ("SGSIN", "CNTXG", "standard", None, "2210.0", "6.6", "South China Sea / Taiwan Strait"),
    ("CNTXG", "SGSIN", "standard", None, "2210.0", "6.6", "South China Sea / Taiwan Strait"),
    ("SGSIN", "JPYOK", "standard", None, "2880.0", "8.6", "via Bashi Channel"),
    ("JPYOK", "SGSIN", "standard", None, "2880.0", "8.6", "via Bashi Channel"),
    ("SGSIN", "AUBNE", "standard", None, "3750.0", "11.2", "via Lombok / Java Sea"),
    ("AUBNE", "SGSIN", "standard", None, "3750.0", "11.2", "via Lombok / Java Sea"),
    ("SGSIN", "BRSSZ", "canal", "suez", "8450.0", "25.1", "via Suez / Cape"),
    ("BRSSZ", "SGSIN", "canal", "suez", "8450.0", "25.1", "via Suez / Cape"),
    ("NLRTM", "CNTXG", "canal", "suez", "10600.0", "31.5", "via Suez / Malacca"),
    ("CNTXG", "NLRTM", "canal", "suez", "10600.0", "31.5", "via Suez / Malacca"),
    ("NLRTM", "JPYOK", "canal", "suez", "11100.0", "33.0", "via Suez"),
    ("JPYOK", "NLRTM", "canal", "suez", "11100.0", "33.0", "via Suez"),
    ("NLRTM", "AUBNE", "canal", "suez", "10800.0", "32.1", "via Suez / Lombok"),
    ("AUBNE", "NLRTM", "canal", "suez", "10800.0", "32.1", "via Suez / Lombok"),
    ("NLRTM", "BRSSZ", "standard", None, "5300.0", "15.8", "North Atlantic"),
    ("BRSSZ", "NLRTM", "standard", None, "5300.0", "15.8", "North Atlantic"),
    ("CNTXG", "JPYOK", "standard", None, "1150.0", "3.4", "East China Sea"),
    ("JPYOK", "CNTXG", "standard", None, "1150.0", "3.4", "East China Sea"),
    ("CNTXG", "AUBNE", "standard", None, "4500.0", "13.4", "via Philippine Sea"),
    ("AUBNE", "CNTXG", "standard", None, "4500.0", "13.4", "via Philippine Sea"),
    ("CNTXG", "BRSSZ", "canal", "panama", "11000.0", "32.7", "via Panama"),
    ("BRSSZ", "CNTXG", "canal", "panama", "11000.0", "32.7", "via Panama"),
    ("JPYOK", "AUBNE", "standard", None, "4200.0", "12.5", "North Pacific / Coral Sea"),
    ("AUBNE", "JPYOK", "standard", None, "4200.0", "12.5", "North Pacific / Coral Sea"),
    ("JPYOK", "BRSSZ", "canal", "panama", "9500.0", "28.3", "via Panama"),
    ("BRSSZ", "JPYOK", "canal", "panama", "9500.0", "28.3", "via Panama"),
    ("AUBNE", "BRSSZ", "cape", None, "8800.0", "26.2", "Southern Ocean / Cape Horn"),
    ("BRSSZ", "AUBNE", "cape", None, "8800.0", "26.2", "Southern Ocean / Cape Horn"),
]

# ── 2. 货组（demo 租户）──
_CARGO_GROUPS: list[tuple[str, str]] = [
    ("Dry Bulk", "Bulk solid cargoes — ore, coal, grain, cement"),
    ("Liquid Bulk", "Crude, products, chemical parcelling"),
    ("Gas", "LNG / LPG and other liquefied gases"),
    ("General Cargo", "Break-bulk, project, steel, bagged"),
    ("Containers", "Containerised liner cargoes"),
]

# (short, full, group, class, imo_name, ibc, imsbc, un, imdg, dangerous, stow_m3, stow_ft3, api, product, unit, basis, desc)
_CARGO_NAMES: list[tuple] = [
    ("IRON ORE", "Iron Ore Fines", "Dry Bulk", "ore", "Iron ore fines", None, "Iron ore fines (A)",
     None, None, False, "0.4200", "15.0000", None, "IOF", "MT", "grain",
     "IMSBC Group A — moisture content risk"),
    ("STEAM COAL", "Steam Coal (Thermal)", "Dry Bulk", "coal", "Coal", None, "Coal (A)",
     None, None, False, "0.5600", "20.0000", None, "SCL", "MT", "grain",
     "Thermal coal, GCV basis"),
    ("GRAIN", "Wheat / Feed Grains", "Dry Bulk", "grain", "Grain", None, "Grain (A)",
     None, None, False, "1.3000", "46.0000", None, "WHT", "MT", "grain",
     "Bulk grain — fumigation may apply"),
    ("BAUXITE", "Bauxite", "Dry Bulk", "ore", "Bauxite", None, "Bauxite (A)",
     None, None, False, "0.7200", "25.5000", None, "ALB", "MT", "grain",
     "Aluminium ore"),
    ("CEMENT", "Portland Cement", "Dry Bulk", "cement", "Cement", None, "Cement (A)",
     None, None, False, "0.8900", "31.5000", None, "CEM", "MT", "grain",
     "Bagged or bulk cement"),
    ("UREA", "Urea (Prilled)", "Dry Bulk", "fertilizer", "Urea", None, "Urea (A)",
     None, None, False, "1.1900", "42.0000", None, "URA", "MT", "grain",
     "Prilled urea fertiliser"),
    ("ALUMINA", "Alumina", "Dry Bulk", "ore", "Alumina", None, "Alumina (A)",
     None, None, False, "0.9500", "33.5000", None, "ALO", "MT", "grain",
     "Refined aluminium oxide"),
    ("CRUDE", "Crude Oil", "Liquid Bulk", "crude", "Crude oil", "A", None,
     None, None, False, "1.0500", "37.0000", "32.0000", "CRD", "MT", "unspecified",
     "Dirty cargo — tank cleaning required"),
    ("MGO", "Marine Gas Oil", "Liquid Bulk", "product", "Marine gas oil", "B", None,
     None, None, False, "1.2500", "44.0000", "42.0000", "MGO", "MT", "unspecified",
     "Distillate fuel, ISO 8217 DMA"),
    ("VLSFO", "Very Low Sulphur Fuel Oil", "Liquid Bulk", "product", "Fuel oil", "B", None,
     None, None, False, "1.1000", "39.0000", "25.0000", "VLS", "MT", "unspecified",
     "0.50% sulphur residual fuel"),
    ("METHANOL", "Methanol", "Liquid Bulk", "chemical", "Methanol", "T", None,
     "UN1230", "6.1", True, "1.2500", "44.0000", None, "MEO", "MT", "unspecified",
     "Toxic / flammable — IBC Ch.17"),
    ("CONTAINERIZED", "Containerised Cargo", "Containers", "container", "Containerised cargo",
     None, None, None, None, False, None, None, None, "TEU", "TEU", "unspecified",
     "Liner cargo measured in TEU"),
]

# ── 3. 港口字段回填（仅填 NULL）──
# unlocode -> (port_type, region, loadline, std_gmt, dst_gmt, fuel_zone)
_PORT_FIELDS: dict[str, tuple] = {
    "SGSIN": ("seaport", "ASIA", "TROPICAL", "8.00", "8.00", "Global"),
    "NLRTM": ("seaport", "EURO", "WINTER", "1.00", "2.00", "North Sea ECA"),
    "CNTXG": ("seaport", "ASIA", "SUMMER", "8.00", "8.00", "China Bohai Rim ECA"),
    "AUBNE": ("seaport", "ASIA", "SUMMER", "10.00", "10.00", "Global"),
    "JPYOK": ("seaport", "ASIA", "SUMMER", "9.00", "9.00", "Global"),
    "BRSSZ": ("seaport", "TRANSATL", "TROPICAL", "-3.00", "-2.00", "Global"),
}

# ── 4. 船舶字段回填（仅填 NULL）──
# imo -> (vessel_code, speed_laden, speed_ballast, tpc, class, trade_area, ownership, daily_cost)
_VESSEL_FIELDS: dict[str, tuple] = {
    "9000001": ("DEMWAV", "13.50", "14.00", "52.00", "ABS", "ASIA", "own", "8500.00"),
    "9000002": ("PACSTA", "14.00", "14.50", "68.00", "DNV", "GLOBAL", "own", "11200.00"),
    "9000003": ("ATLPRL", "13.20", "13.80", "92.00", "LR", "TRANSATL", "tc", "15800.00"),
    "9000004": ("INDMON", "13.80", "14.30", "56.00", "NK", "ASIA", "own", "9600.00"),
}


def seed_masterdata_gaps(db: Session) -> None:
    """走查补种：距离 / 货品 / 港口与船舶空字段回填。幂等。"""
    from app.models import Tenant
    from app.models_cargo import CargoGroup, CargoName
    from app.models_reference import PortDistance
    from app.models_wave1 import Port, Vessel

    # ── 1. 港口距离（全局参照，无 tenant）──
    for frm, to, route, canal, dist, days, notes in _DISTANCES:
        exists = db.scalar(
            select(PortDistance).where(
                PortDistance.from_port_unlocode == frm,
                PortDistance.to_port_unlocode == to,
                PortDistance.route_type == route,
            ).limit(1)
        )
        if exists:
            continue
        db.add(
            PortDistance(
                from_port_unlocode=frm,
                to_port_unlocode=to,
                route_type=route,
                canal_transit=canal,
                distance_nm=Decimal(dist),
                transit_days=Decimal(days),
                notes=notes,
                source="seed",
            )
        )
    db.flush()

    tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
    if not tenant:
        db.commit()
        return

    # ── 2. 货组 + 货物品名 ──
    groups: dict[str, object] = {}
    for name, desc in _CARGO_GROUPS:
        g = db.scalar(
            select(CargoGroup).where(
                CargoGroup.tenant_id == tenant.id,
                CargoGroup.name == name,
                CargoGroup.deleted_at.is_(None),
            )
        )
        if not g:
            g = CargoGroup(tenant_id=tenant.id, name=name, description=desc)
            db.add(g)
            db.flush()
        groups[name] = g

    for row in _CARGO_NAMES:
        (short, full, grp, cls, imo_name, ibc, imsbc, un, imdg, danger,
         stow_m3, stow_ft3, api, product, unit, basis, desc) = row
        exists = db.scalar(
            select(CargoName).where(
                CargoName.tenant_id == tenant.id,
                CargoName.short_name == short,
                CargoName.deleted_at.is_(None),
            )
        )
        if exists:
            continue
        g = groups.get(grp)
        db.add(
            CargoName(
                tenant_id=tenant.id,
                short_name=short,
                full_name=full,
                cargo_group_id=getattr(g, "id", None),
                cargo_class=cls,
                imo_name=imo_name,
                ibc_code=ibc,
                imsbc_code=imsbc,
                un_number=un,
                imdg_class=imdg,
                dangerous=danger,
                stow_factor_m3_mt=Decimal(stow_m3) if stow_m3 else None,
                stow_factor_ft3_mt=Decimal(stow_ft3) if stow_ft3 else None,
                api_gravity=Decimal(api) if api else None,
                product_code=product,
                default_cp_unit=unit,
                capacity_basis=basis,
                inactive=False,
                description=desc,
            )
        )
    db.flush()

    # ── 3. 港口空字段回填（不覆盖已有值）──
    for unlocode, (ptype, region, loadline, std_gmt, dst_gmt, fuel) in _PORT_FIELDS.items():
        p = db.scalar(select(Port).where(Port.unlocode == unlocode))
        if not p:
            continue
        if p.port_type is None:
            p.port_type = ptype
        if p.region_code is None:
            p.region_code = region
        if p.loadline_zone is None:
            p.loadline_zone = loadline
        if p.std_gmt_offset is None:
            p.std_gmt_offset = Decimal(std_gmt)
        if p.dst_gmt_offset is None:
            p.dst_gmt_offset = Decimal(dst_gmt)
        if p.fuel_zone_default is None:
            p.fuel_zone_default = fuel

    # ── 4. 船舶空字段回填（不覆盖已有值）──
    for imo, (code, sl, sb, tpc, cls, area, own, cost) in _VESSEL_FIELDS.items():
        v = db.scalar(
            select(Vessel).where(Vessel.tenant_id == tenant.id, Vessel.imo == imo)
        )
        if not v:
            continue
        if v.vessel_code is None:
            v.vessel_code = code
        if v.speed_laden is None:
            v.speed_laden = Decimal(sl)
        if v.speed_ballast is None:
            v.speed_ballast = Decimal(sb)
        if v.tpc is None:
            v.tpc = Decimal(tpc)
        if v.class_society is None:
            v.class_society = cls
        if v.trade_area is None:
            v.trade_area = area
        if v.ownership is None:
            v.ownership = own
        if v.daily_cost is None:
            v.daily_cost = Decimal(cost)

    db.commit()
