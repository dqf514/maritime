"""Full commercial + ship-management demo flow seed (idempotent)."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant
from app.services.timeutil import utcnow_naive


def _now() -> datetime:
    return utcnow_naive()



def _apply_missing(obj, values: dict) -> bool:
    """仅把当前为 **None** 的列补上给定值；返回是否发生修改。

    用于 demo 数据的自愈式补全：新建时全量写入，既有库缺哪列补哪列，
    既不覆盖用户已改的值，也不需要清库重建。
    """
    changed = False
    for key, val in values.items():
        if val is None:
            continue
        if getattr(obj, key, None) is None:
            setattr(obj, key, val)
            changed = True
    return changed


# ── 交易对手主数据 ────────────────────────────────────────────────────────────
# demo 主数据要「像真实公司」：联系方式 / 财务条件 / GL 科目挂钩齐全，
# 否则下游发票、往来、付款全是空值（实测 36 个字段里 30 个为空）。
CP_SPECS = [
    {
        "name": "Atlantic Brokers Ltd",
        "type": "broker",
        "country": "GB",
        "short_name": "ATLANTIC BRK",
        "email": "chartering@atlanticbrokers.co.uk",
        "phone": "+44 20 7946 0812",
        "address": "12 Leadenhall Street, London EC3V 1RP, United Kingdom",
        "tax_id": "GB 412 8837 21",
        "vat_no": "GB412883721",
        "company_no": "04128837",
        "swift_code": "ATLGB2L",
        "website": "https://atlanticbrokers.co.uk",
        "currency": "USD",
        "credit_term": 30,
        "credit_line": Decimal("500000.00"),
        "credit_rating": "BBB+",
        "address_types": ["broker", "address_agent"],
        "ap_account": "2000",
        "default_account": "2000",
        "main_contact": "R. Whitfield",
        "department": "Dry Cargo Chartering",
        "ref_no": "BRK-ATL-001",
        "cross_ref": "ATL-BRK",
        "reference_code": "ATL",
        "demurrage_tb_days": Decimal("30"),
        "notes": "Dry bulk broker；经纪佣金 1.25%，地址佣金 1.00%（港方）。",
    },
    {
        "name": "Nordic Grain Traders",
        "type": "charterer",
        "country": "NO",
        "short_name": "NORDIC GRAIN",
        "email": "chartering@nordicgrain.no",
        "phone": "+47 22 07 44 00",
        "address": "Bryggen 6, 0157 Oslo, Norway",
        "tax_id": "NO 987 654 321",
        "vat_no": "NO987654321",
        "company_no": "987654321",
        "swift_code": "NGRANO22",
        "website": "https://nordicgrain.no",
        "currency": "USD",
        "credit_term": 30,
        "credit_line": Decimal("3000000.00"),
        "credit_rating": "BBB",
        "address_types": ["charterer"],
        "ar_account": "1200",
        "default_account": "1200",
        "main_contact": "M. Sørensen",
        "department": "Grain Chartering",
        "ref_no": "CHT-NGT-001",
        "cross_ref": "NGT",
        "reference_code": "NGT",
        "demurrage_tb_days": Decimal("45"),
        "notes": "Grain charterer；账期 30 天，信用额度 USD 3,000,000。",
    },
    {
        "name": "Pacific Steel Mills",
        "type": "charterer",
        "country": "JP",
        "short_name": "PACIFIC STEEL",
        "email": "chartering@pacificsteel.co.jp",
        "phone": "+81 3 5400 2211",
        "address": "2-1 Kaigan, Minato-ku, Tokyo 105-0012, Japan",
        "tax_id": "JP 7010001000001",
        "vat_no": "JP7010001000001",
        "company_no": "0100-01-100001",
        "swift_code": "PSMCJPJT",
        "website": "https://pacificsteel.co.jp",
        "currency": "USD",
        "credit_term": 45,
        "credit_line": Decimal("2000000.00"),
        "credit_rating": "A-",
        "address_types": ["charterer"],
        "ar_account": "1200",
        "default_account": "1200",
        "main_contact": "K. Tanaka",
        "department": "Raw Materials",
        "ref_no": "CHT-PSM-001",
        "cross_ref": "PSM",
        "reference_code": "PSM",
        "demurrage_tb_days": Decimal("30"),
        "notes": "Coal offtaker；账期 45 天。",
    },
    {
        "name": "Rotterdam Agency BV",
        "type": "agent",
        "country": "NL",
        "short_name": "RTM AGENCY",
        "email": "agency@rotterdamagency.nl",
        "phone": "+31 10 411 2200",
        "address": "Wilhelminakade 909, 3072 AP Rotterdam, Netherlands",
        "tax_id": "NL 8123.45.678.B01",
        "vat_no": "NL812345678B01",
        "company_no": "34215567",
        "swift_code": "RAGBNL2R",
        "website": "https://rotterdamagency.nl",
        "currency": "EUR",
        "credit_term": 30,
        "credit_line": Decimal("750000.00"),
        "credit_rating": "BBB",
        "address_types": ["agent"],
        "ap_account": "2000",
        "default_account": "2000",
        "main_contact": "J. de Vries",
        "department": "Port Agency",
        "ref_no": "AGT-RTM-001",
        "cross_ref": "RTMAGT",
        "reference_code": "RTMA",
        "demurrage_tb_days": Decimal("21"),
        "notes": "Rotterdam 港口代理；代理费用 USD 15,000/船次。",
    },
    {
        "name": "Gulf Bunker Supply",
        "type": "supplier",
        "country": "SG",
        "short_name": "GULF BUNKER",
        "email": "supply@gulfbunker.sg",
        "phone": "+65 6222 8800",
        "address": "9 Battery Road, #18-01, Singapore 049910",
        "tax_id": "SG 200912345K",
        "vat_no": "SG200912345K",
        "company_no": "200912345K",
        "swift_code": "GBSPGSGS",
        "website": "https://gulfbunker.sg",
        "currency": "USD",
        "credit_term": 15,
        "credit_line": Decimal("1000000.00"),
        "credit_rating": "BB+",
        "address_types": ["supplier"],
        "ap_account": "2000",
        "default_account": "2000",
        "main_contact": "A. Rahman",
        "department": "Bunkering",
        "ref_no": "SUP-GBS-001",
        "cross_ref": "GBS",
        "reference_code": "GBS",
        "demurrage_tb_days": Decimal("15"),
        "notes": "新加坡燃油供应商；VLSFO/HSFO/LSGO，付款 15 天。",
    },
]



def _charter_term_sets(today, ports) -> dict:
    """CP 类型化条款列取值 —— 新建与「既有库回填」共用同一份真值。

    过去 demo 只写了 clauses / freight_terms 两个 JSON 字段，20+ 个类型化列全空，
    导致 CP 详情里的装卸率、滞期费、交/还船港与时间、ETS 责任方、fixture 号等
    界面读不到值。这里给出完整取值。
    """

    def _utc_day(offset: int):
        """平台存储约定为 naive UTC（见 app/services/timeutil.py）。"""
        return datetime.combine(today + timedelta(days=offset), datetime.min.time())

    sgsin = ports.get("SGSIN")
    nlrtm = ports.get("NLRTM")
    cntxg = ports.get("CNTXG")
    jpyok = ports.get("JPYOK")
    aubne = ports.get("AUBNE")

    ch1_terms = {
        "demurrage_rate": Decimal("22000.00"),
        "despatch_rate": Decimal("11000.00"),
        "laytime_terms": "SHINC",
        "cp_form": "GENCON",
        "freight_rate": Decimal("24.6667"),
        "freight_basis": "per_mt",
        "cargo_qty": Decimal("75000"),
        "bill_by": "weight",
        "tolerance_pct": Decimal("5.00"),
        "overage_pct": Decimal("10.00"),
        "load_rate_pd": Decimal("35000"),
        "disch_rate_pd": Decimal("25000"),
        "address_comm_pct": Decimal("1.00"),
        "brokerage_pct": Decimal("1.25"),
        "delivery_port_id": sgsin.id if sgsin else None,
        "redelivery_port_id": nlrtm.id if nlrtm else None,
        "delivery_at": _utc_day(-18),
        "redelivery_at": _utc_day(24),
        "commence_at": _utc_day(-18),
        "ets_responsibility": "charterer",
        "exposure_amount": Decimal("1850000.00"),
        "pricing_basis": "per_mt",
        "fixture_no": "20260001",
        "voyage_no": "VOY-2407",
        "opr_type": "VOY",
        "chtr_specialist": "Alex Charterer",
        "ops_coordinator": "Olivia Ops",
        "piracy_routing": "default",
        "company_code": "DEMO",
        "lob": "Dry Bulk",
        "trade_area": "Far East / North Europe",
        "properties": {"cargo": "Iron ore 75kt", "incoterm": "FIOS", "loading_rate": "35,000 mt/day"},
    }

    ch2_terms = {
        "demurrage_rate": Decimal("18000.00"),
        "despatch_rate": Decimal("9000.00"),
        "laytime_terms": "SHINC",
        "cp_form": "GENCON",
        "freight_rate": Decimal("17.6923"),
        "freight_basis": "per_mt",
        "cargo_qty": Decimal("52000"),
        "bill_by": "weight",
        "tolerance_pct": Decimal("5.00"),
        "overage_pct": Decimal("10.00"),
        "load_rate_pd": Decimal("30000"),
        "disch_rate_pd": Decimal("20000"),
        "address_comm_pct": Decimal("1.00"),
        "brokerage_pct": Decimal("1.25"),
        "delivery_port_id": cntxg.id if cntxg else None,
        "redelivery_port_id": jpyok.id if jpyok else None,
        "delivery_at": _utc_day(7),
        "redelivery_at": _utc_day(25),
        "ets_responsibility": "charterer",
        "exposure_amount": Decimal("920000.00"),
        "pricing_basis": "per_mt",
        "fixture_no": "20260002",
        "voyage_no": "VOY-2408",
        "opr_type": "VOY",
        "chtr_specialist": "Alex Charterer",
        "ops_coordinator": "Olivia Ops",
        "piracy_routing": "default",
        "company_code": "DEMO",
        "lob": "Dry Bulk",
        "trade_area": "Middle East / Far East",
        "properties": {"cargo": "Coal 52kt", "incoterm": "FOB", "loading_rate": "30,000 mt/day"},
    }

    coa_terms = {
        "fixture_no": "20260003",
        "opr_type": "COA",
        "cp_form": "GENCON",
        "laytime_terms": "SHINC",
        "bill_by": "weight",
        "tolerance_pct": Decimal("5.00"),
        "overage_pct": Decimal("10.00"),
        "address_comm_pct": Decimal("1.00"),
        "brokerage_pct": Decimal("1.25"),
        "ets_responsibility": "charterer",
        "trade_area": "Global",
        "chtr_specialist": "Alex Charterer",
        "ops_coordinator": "Olivia Ops",
        "company_code": "DEMO",
        "lob": "Dry Bulk",
        "piracy_routing": "default",
        "properties": {"cargo": "Coal / grains parcels 50kt ±5%", "period": "12 months"},
    }

    tc_terms = {
        "hire_cycle_days": 30,
        "fixture_no": "20260004",
        "opr_type": "TCOV",
        "pricing_basis": "per_day",
        "delivery_port_id": sgsin.id if sgsin else None,
        "redelivery_port_id": aubne.id if aubne else None,
        "delivery_at": _utc_day(10),
        "redelivery_at": _utc_day(100),
        "commence_at": _utc_day(10),
        "ets_responsibility": "owner",
        "trade_area": "Worldwide",
        "chtr_specialist": "Alex Charterer",
        "ops_coordinator": "Olivia Ops",
        "company_code": "DEMO",
        "lob": "Dry Bulk",
        "piracy_routing": "default",
        "properties": {"duration_days": 90, "payment_frequency": "monthly"},
    }

    return {
        "CP-2407": ch1_terms,
        "CP-2408": ch2_terms,
        "CP-COA-2601": coa_terms,
        "CP-TC-2602": tc_terms,
    }


def _backfill_demo_master_data(db: Session, tenant) -> None:
    """把 demo 主数据的空列补齐（幂等、仅补 None，不覆盖用户已改的值）。

    既有 demo 库是在「类型化条款列」之前建的，启动时补一次即可自愈；
    新库走 seed_full_demo_flow 的全量写入路径，无需回填。
    """
    from app.models_domain import Charter
    from app.models_wave1 import Counterparty, Port

    today = date.today()
    ports = {p.unlocode: p for p in db.scalars(select(Port)).all()}

    # 1) 交易对手：联系方式 / 财务条件 / GL 科目挂钩
    for spec in CP_SPECS:
        c = db.scalar(
            select(Counterparty).where(
                Counterparty.tenant_id == tenant.id, Counterparty.name == spec["name"]
            )
        )
        if c is not None and _apply_missing(c, spec):
            db.flush()

    # 2) 租约：类型化条款列
    for charter_no, terms in _charter_term_sets(today, ports).items():
        c = db.scalar(
            select(Charter).where(Charter.tenant_id == tenant.id, Charter.charter_no == charter_no)
        )
        if c is not None and _apply_missing(c, terms):
            db.flush()

def seed_full_demo_flow(db: Session) -> None:
    """Populate estimate→charter→voyage→finance→twin→ship_mgmt for demo tenant."""
    from app.models_domain import (
        BunkerOrder,
        Charter,
        Claim,
        Estimate,
        Invoice,
        LaytimeCalc,
        MarketQuote,
        NoonReport,
        Payment,
        PortCall,
        PortDisbursement,
        SofEvent,
        TwinAlert,
        Voyage,
    )
    from app.models_ship import (
        ShipCertificate,
        ShipCrewMember,
        ShipDefect,
        ShipSparePart,
        ShipTechnicalProfile,
        ShipWorkOrder,
    )
    from app.models_wave1 import ConnectorInstance, Counterparty, Port, Vessel

    tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
    if not tenant:
        return

    # Marker: already seeded full flow — 仍补种扩展数据（幂等）
    if db.scalar(select(Estimate).where(Estimate.tenant_id == tenant.id, Estimate.title == "SEED SGSIN→NLRTM Capesize")):
        _seed_demo_flow_extra(db, tenant)
        return

    now = _now()
    today = date.today()

    # Extra ports
    port_defs = [
        ("AUBNE", "Brisbane", "AU", "Australia/Brisbane", Decimal("-27.470500"), Decimal("153.026000")),
        ("JPYOK", "Yokohama", "JP", "Asia/Tokyo", Decimal("35.443700"), Decimal("139.638000")),
        ("BRSSZ", "Santos", "BR", "America/Sao_Paulo", Decimal("-23.960800"), Decimal("-46.333600")),
    ]
    for unlocode, name, country, tz, lat, lon in port_defs:
        if not db.scalar(select(Port).where(Port.unlocode == unlocode)):
            db.add(Port(unlocode=unlocode, name=name, country=country, timezone=tz, latitude=lat, longitude=lon))
    db.flush()

    ports = {p.unlocode: p for p in db.scalars(select(Port)).all()}

    # Fleet
    vessel_defs = [
        ("MV DEMO WAVE", "9000001", "SG", "Bulker", "58000", "13.5", "28", "3.5"),
        ("MV PACIFIC STAR", "9000002", "MH", "Bulker", "82000", "14.0", "32", "4.0"),
        ("MV ATLANTIC PEARL", "9000003", "LR", "Tanker", "115000", "13.2", "38", "5.0"),
        ("MV INDIAN MONSOON", "9000004", "HK", "Bulker", "64000", "13.8", "29", "3.8"),
    ]
    vessels: dict[str, Vessel] = {}
    for name, imo, flag, vtype, dwt, speed, sea, portc in vessel_defs:
        v = db.scalar(select(Vessel).where(Vessel.tenant_id == tenant.id, Vessel.imo == imo))
        if not v:
            v = Vessel(
                tenant_id=tenant.id,
                name=name,
                imo=imo,
                flag=flag,
                vessel_type=vtype,
                dwt=Decimal(dwt),
                speed_knots=Decimal(speed),
                consumption_sea=Decimal(sea),
                consumption_port=Decimal(portc),
                status="active",
                # IMOS 对齐业务分组：示例船队里放一条“船管”以展示分组维度
                fleet_group="ship_management" if imo == "9000004" else "mother_vessel",
            )
            db.add(v)
            db.flush()
        vessels[imo] = v

    # Counterparties —— 主数据要「像真实公司」：联系方式 / 财务条件 / GL 科目挂钩齐全，
    # 否则下游发票、往来、付款全是空值（实测 36 个字段里 30 个为空）。
    # 取值见模块级 CP_SPECS；既有库由 _backfill_demo_master_data 回填（仅补空值，幂等自愈）。
    cps: dict[str, Counterparty] = {}
    for spec in CP_SPECS:
        c = db.scalar(
            select(Counterparty).where(
                Counterparty.tenant_id == tenant.id, Counterparty.name == spec["name"]
            )
        )
        if not c:
            c = Counterparty(tenant_id=tenant.id, sanctions_status="clear", **spec)
            db.add(c)
            db.flush()
        else:
            _apply_missing(c, spec)
        cps[spec["name"]] = c

    v1, v2, v3, v4 = vessels["9000001"], vessels["9000002"], vessels["9000003"], vessels["9000004"]

    # Estimates — results 同时含展示键与 P&L 引擎键（total_revenue/voyage_cost/tce）
    # status 只能用估算页认得的词表：draft / calculated / confirmed / converted / cancelled。
    # 以前这里写的是 working / submitted —— 两个词全系统没人产生，前端既没有
    # 筛选项也没有翻译（列表页直接露出英文 "working"），TCE 分析页也因此是空的。
    est_data = [
        (
            "SEED SGSIN→NLRTM Capesize",
            v2,
            cps["Nordic Grain Traders"],
            "calculated",
            {"load_port": "SGSIN", "disch_port": "NLRTM", "cargo_mt": 75000, "freight_usd": 1850000},
            {"tce_usd_day": 16850, "voyage_days": 42, "pnl_usd": 420000, "total_revenue": 1850000, "voyage_cost": 1430000, "tce": 16850},
        ),
        (
            "CNTXG→JPYOK coal",
            v1,
            cps["Pacific Steel Mills"],
            "draft",
            {"load_port": "CNTXG", "disch_port": "JPYOK", "cargo_mt": 52000, "freight_usd": 920000},
            {"tce_usd_day": 14200, "voyage_days": 18, "pnl_usd": 180000, "total_revenue": 920000, "voyage_cost": 740000, "tce": 14200},
        ),
        (
            "BRSSZ→AUBNE grains TCT",
            v4,
            cps["Nordic Grain Traders"],
            "confirmed",
            {"duration_days": 90, "hire_usd_day": 15500},
            {"tce_usd_day": 15100, "voyage_days": 90, "pnl_usd": 310000, "total_revenue": 1395000, "voyage_cost": 1085000, "tce": 15100},
        ),
    ]
    estimates = []
    for title, vessel, cp, status, inputs, results in est_data:
        e = Estimate(
            tenant_id=tenant.id,
            title=title,
            mode="tct" if "TCT" in title else "voyage",
            vessel_id=vessel.id,
            counterparty_id=cp.id,
            status=status,
            inputs=inputs,
            results=results,
        )
        db.add(e)
        estimates.append(e)
    db.flush()

    # Charters
    # 类型化条款列（IMOS 字段级对齐）——过去只写了 clauses / freight_terms 两个 JSON，
    # 装卸率、滞期费、交/还船港与时间、ETS 责任方、fixture 号等 20+ 列全空，
    # 租约详情页读不到值。新建与既有库回填共用 _charter_term_sets 一份真值。
    _terms = _charter_term_sets(today, ports)
    ch1_terms = _terms["CP-2407"]
    ch2_terms = _terms["CP-2408"]
    ch1 = Charter(
        tenant_id=tenant.id,
        charter_no="CP-2407",
        charter_type="voyage",
        status="active",
        vessel_id=v2.id,
        counterparty_id=cps["Nordic Grain Traders"].id,
        estimate_id=estimates[0].id,
        laycan_from=today - timedelta(days=20),
        laycan_to=today - timedelta(days=10),
        commission_pct=Decimal("1.25"),
        freight_terms={"freight_usd": 1850000, "basis": "FIOS"},
        clauses={"laytime_hours": 72, "demurrage_usd_day": 22000},
        **ch1_terms,
    )
    ch2 = Charter(
        tenant_id=tenant.id,
        charter_no="CP-2408",
        charter_type="voyage",
        # 必须是状态机认得的词：draft → pending_approval → active → completed。
        # 以前写 "submitted" —— 全系统没人产生这个值，于是这份租约在演示里
        # 永远批不了（任何流转都 409 INVALID_STATE），是条死胡同。
        status="pending_approval",
        vessel_id=v1.id,
        counterparty_id=cps["Pacific Steel Mills"].id,
        estimate_id=estimates[1].id,
        laycan_from=today + timedelta(days=5),
        laycan_to=today + timedelta(days=12),
        commission_pct=Decimal("1.25"),
        freight_terms={"freight_usd": 920000},
        clauses={"laytime_hours": 48, "demurrage_usd_day": 18000},
        **ch2_terms,
    )
    db.add_all([ch1, ch2])
    db.flush()

    # Voyages
    voy1 = Voyage(
        tenant_id=tenant.id,
        voyage_no="VOY-2407",
        status="in_progress",
        vessel_id=v2.id,
        charter_id=ch1.id,
        cargo="Iron ore 75kt",
        cp_date=today - timedelta(days=18),
        started_at=now - timedelta(days=12),
        meta={"tce_budget": 16000},
    )
    voy2 = Voyage(
        tenant_id=tenant.id,
        voyage_no="VOY-2408",
        status="planned",
        vessel_id=v1.id,
        charter_id=ch2.id,
        cargo="Coal 52kt",
        cp_date=today,
        meta={},
    )
    voy3 = Voyage(
        tenant_id=tenant.id,
        voyage_no="VOY-2405",
        status="completed",
        vessel_id=v3.id,
        cargo="Crude 100kt",
        cp_date=today - timedelta(days=60),
        started_at=now - timedelta(days=55),
        completed_at=now - timedelta(days=20),
        meta={"tce_actual": 19200},
    )
    db.add_all([voy1, voy2, voy3])
    db.flush()

    # Port calls + SOF
    pc_load = PortCall(
        tenant_id=tenant.id,
        voyage_id=voy1.id,
        port_id=ports.get("SGSIN").id if ports.get("SGSIN") else None,
        seq=1,
        purpose="load",
        eta=now - timedelta(days=11),
        ata=now - timedelta(days=11),
        atd=now - timedelta(days=9),
        agent="Pacific Agency SG",
        timezone="Asia/Singapore",
    )
    pc_disch = PortCall(
        tenant_id=tenant.id,
        voyage_id=voy1.id,
        port_id=ports.get("NLRTM").id if ports.get("NLRTM") else None,
        seq=2,
        purpose="discharge",
        eta=now + timedelta(days=8),
        agent="Rotterdam Agency BV",
        timezone="Europe/Amsterdam",
    )
    db.add_all([pc_load, pc_disch])
    db.flush()
    db.add_all(
        [
            SofEvent(tenant_id=tenant.id, port_call_id=pc_load.id, event_code="NOR", event_at=now - timedelta(days=11, hours=2)),
            SofEvent(tenant_id=tenant.id, port_call_id=pc_load.id, event_code="COMMENCED", event_at=now - timedelta(days=11)),
            SofEvent(tenant_id=tenant.id, port_call_id=pc_load.id, event_code="COMPLETED", event_at=now - timedelta(days=9, hours=6)),
        ]
    )

    # Noon reports (positions for twin/dashboards)
    track = [
        (1.29, 103.85, 0, 820, 45),
        (5.2, 98.1, 12.8, 790, 42),
        (12.4, 80.2, 13.1, 760, 40),
        (18.9, 65.4, 12.6, 735, 38),
        (25.1, 55.0, 13.0, 710, 36),
        (33.5, 32.1, 12.4, 680, 34),
        (40.2, 18.5, 12.9, 655, 32),
        (48.1, 8.2, 11.8, 630, 30),
    ]
    for i, (lat, lon, spd, fo, do) in enumerate(track):
        db.add(
            NoonReport(
                tenant_id=tenant.id,
                voyage_id=voy1.id,
                report_at=now - timedelta(days=8 - i),
                lat=Decimal(str(lat)),
                lon=Decimal(str(lon)),
                speed=Decimal(str(spd)),
                rob_fo=Decimal(str(fo)),
                rob_do=Decimal(str(do)),
                eta_next=now + timedelta(days=8 - i),
                remarks="Seed noon",
                eta_deviation_hours=Decimal("2.5") if i == 7 else Decimal("0"),
            )
        )
    db.add(
        NoonReport(
            tenant_id=tenant.id,
            voyage_id=voy3.id,
            report_at=now - timedelta(days=22),
            lat=Decimal("51.900000"),
            lon=Decimal("4.100000"),
            speed=Decimal("0"),
            rob_fo=Decimal("540"),
            rob_do=Decimal("28"),
        )
    )

    # Laytime / claim / PDA / bunker
    lt = LaytimeCalc(
        tenant_id=tenant.id,
        voyage_id=voy1.id,
        port_call_id=pc_load.id,
        status="finalized",
        inputs={"allowed_hours": 72, "demurrage_rate": 22000},
        results={"used_hours": 86, "demurrage_usd": 12833, "despatch_usd": 0},
        finalized_at=now - timedelta(days=8),
    )
    db.add(lt)
    db.flush()
    db.add(
        Claim(
            tenant_id=tenant.id,
            claim_no="CLM-2407-DEM",
            claim_type="demurrage",
            status="open",
            voyage_id=voy1.id,
            laytime_id=lt.id,
            amount=Decimal("12833.00"),
            currency="USD",
            time_bar=today + timedelta(days=40),
            notes="Load port demurrage — Singapore",
        )
    )
    db.add(
        Claim(
            tenant_id=tenant.id,
            claim_no="CLM-2405-DEM",
            claim_type="demurrage",
            status="settled",
            voyage_id=voy3.id,
            amount=Decimal("86000.00"),
            settlement_amount=Decimal("78000.00"),
            currency="USD",
            time_bar=today - timedelta(days=5),
        )
    )
    db.add(
        PortDisbursement(
            tenant_id=tenant.id,
            voyage_id=voy1.id,
            port_call_id=pc_load.id,
            status="fda",
            pda_amount=Decimal("42000"),
            fda_amount=Decimal("44850"),
            currency="USD",
            lines={"port_dues": 18000, "pilot": 6500, "agency": 4200, "other": 16150},
            variance=Decimal("2850"),
        )
    )
    db.add(
        BunkerOrder(
            tenant_id=tenant.id,
            order_no="BNK-2407",
            status="delivered",
            vessel_id=v2.id,
            voyage_id=voy1.id,
            grade="VLSFO",
            qty_ordered=Decimal("800"),
            qty_delivered=Decimal("795"),
            unit_price=Decimal("545"),
            rob_before=Decimal("420"),
            rob_after=Decimal("1215"),
            consumption=Decimal("0"),
        )
    )

    # Finance
    inv1 = Invoice(
        tenant_id=tenant.id,
        invoice_no="INV-2407-FRT",
        invoice_type="freight",
        status="issued",
        counterparty_id=cps["Nordic Grain Traders"].id,
        voyage_id=voy1.id,
        amount=Decimal("1850000"),
        tax_amount=Decimal("0"),
        paid_amount=Decimal("925000"),
        issued_at=now - timedelta(days=10),
        due_date=today + timedelta(days=5),
        gl_posted=True,
    )
    inv2 = Invoice(
        tenant_id=tenant.id,
        invoice_no="INV-2405-FRT",
        invoice_type="freight",
        status="paid",
        counterparty_id=cps["Pacific Steel Mills"].id,
        voyage_id=voy3.id,
        amount=Decimal("2100000"),
        paid_amount=Decimal("2100000"),
        issued_at=now - timedelta(days=35),
        due_date=today - timedelta(days=5),
        gl_posted=True,
    )
    inv3 = Invoice(
        tenant_id=tenant.id,
        invoice_no="INV-2398-DEM",
        invoice_type="demurrage",
        status="overdue",
        counterparty_id=cps["Nordic Grain Traders"].id,
        voyage_id=voy3.id,
        amount=Decimal("78000"),
        paid_amount=Decimal("0"),
        issued_at=now - timedelta(days=70),
        due_date=today - timedelta(days=40),
        gl_posted=False,
    )
    db.add_all([inv1, inv2, inv3])
    db.flush()
    db.add(
        Payment(
            tenant_id=tenant.id,
            invoice_id=inv1.id,
            amount=Decimal("925000"),
            currency="USD",
            paid_at=now - timedelta(days=3),
            reference="WIRE-SG-7781",
        )
    )
    db.add(
        Payment(
            tenant_id=tenant.id,
            invoice_id=inv2.id,
            amount=Decimal("2100000"),
            currency="USD",
            paid_at=now - timedelta(days=12),
            reference="WIRE-JP-4410",
        )
    )

    # Twin alerts + market
    db.add_all(
        [
            TwinAlert(
                tenant_id=tenant.id,
                level="warn",
                title="ETA slip +6h on VOY-2407 — weather routing",
                body="North Atlantic gale delay",
                href="/twin",
                vessel_id=v2.id,
                voyage_id=voy1.id,
            ),
            TwinAlert(
                tenant_id=tenant.id,
                level="info",
                title="NOR window approaching NLRTM",
                href="/operations/voyages",
                vessel_id=v2.id,
                voyage_id=voy1.id,
            ),
            TwinAlert(
                tenant_id=tenant.id,
                level="critical",
                title="Certificate Class Annual Survey due 18d — MV INDIAN MONSOON",
                href="/ship",
                vessel_id=v4.id,
            ),
        ]
    )
    _seed_market_history(db, tenant)

    # —— Ship management ——
    tech_defs = [
        (v1, "in_house", "BV", 2012, "CSSC", "MAN", "6S50ME", today + timedelta(days=220), "Lee Super"),
        (v2, "hybrid", "DNV", 2016, "Hyundai", "MAN", "6G70ME", today + timedelta(days=90), "Chen Tech"),
        (v3, "external_pms", "LR", 2014, "Samsung", "Wärtsilä", "7RT-flex", today + timedelta(days=400), "Ross Fleet"),
        (v4, "in_house", "ABS", 2018, "Imabari", "MAN", "6S60ME", today + timedelta(days=18), "Lee Super"),
    ]
    for vessel, mode, society, year, yard, maker, etype, dd, super_name in tech_defs:
        if not db.scalar(select(ShipTechnicalProfile).where(ShipTechnicalProfile.vessel_id == vessel.id)):
            db.add(
                ShipTechnicalProfile(
                    tenant_id=tenant.id,
                    vessel_id=vessel.id,
                    management_mode=mode,
                    class_society=society,
                    built_year=year,
                    yard=yard,
                    engine_maker=maker,
                    engine_type=etype,
                    next_drydock=dd,
                    next_special_survey=dd + timedelta(days=30),
                    technical_status="in_service" if vessel is not v4 else "repair",
                    superintendent=super_name,
                    external_pms_id=f"PMS-{vessel.imo}",
                    external_system="pms.mock" if mode != "in_house" else None,
                )
            )

    cert_rows = [
        (v1, "SMC", "Safety Management Certificate", today - timedelta(days=400), today + timedelta(days=320), "valid"),
        (v1, "ISSC", "ISPS Certificate", today - timedelta(days=200), today + timedelta(days=160), "valid"),
        (v2, "CLASS", "Class Certificate", today - timedelta(days=100), today + timedelta(days=45), "expiring"),
        (v2, "IOPP", "IOPP Certificate", today - timedelta(days=500), today + timedelta(days=200), "valid"),
        (v3, "SMC", "Safety Management Certificate", today - timedelta(days=50), today + timedelta(days=300), "valid"),
        (v4, "CLASS", "Annual Survey", today - timedelta(days=340), today + timedelta(days=18), "expiring"),
        (v4, "DOC", "Document of Compliance", today - timedelta(days=700), today - timedelta(days=5), "expired"),
    ]
    for vessel, code, name, issued, expires, status in cert_rows:
        db.add(
            ShipCertificate(
                tenant_id=tenant.id,
                vessel_id=vessel.id,
                cert_code=code,
                cert_name=name,
                issued_on=issued,
                expires_on=expires,
                status=status,
                issuing_body="Class / Flag",
            )
        )

    wo_rows = [
        (v1, "WO-1001", "ME cylinder oil feed check", "pms", "medium", "open", today + timedelta(days=7)),
        (v1, "WO-1002", "Lifeboat davit load test", "safety", "high", "in_progress", today + timedelta(days=3)),
        (v2, "WO-2001", "Ballast pump #2 seal replace", "defect", "high", "open", today + timedelta(days=5)),
        (v2, "WO-2002", "Quarterly bridge PMS pack", "pms", "low", "done", today - timedelta(days=2)),
        (v3, "WO-3001", "IGS scrubber inspection", "pms", "medium", "open", today + timedelta(days=14)),
        (v4, "WO-4001", "Class annual survey prep", "survey", "critical", "in_progress", today + timedelta(days=10)),
        (v4, "WO-4002", "Aux boiler refractory repair", "defect", "critical", "open", today + timedelta(days=4)),
    ]
    for vessel, wo_no, title, cat, pri, status, due in wo_rows:
        db.add(
            ShipWorkOrder(
                tenant_id=tenant.id,
                vessel_id=vessel.id,
                wo_no=wo_no,
                title=title,
                category=cat,
                priority=pri,
                status=status,
                due_on=due,
                estimated_cost=Decimal("12000") if pri == "critical" else Decimal("3500"),
                assignee="Superintendent",
                source="voyageos",
            )
        )

    db.add_all(
        [
            ShipDefect(
                tenant_id=tenant.id,
                vessel_id=v2.id,
                defect_no="DEF-21",
                title="Ballast pump seal leak",
                severity="major",
                status="open",
                found_on=today - timedelta(days=4),
                due_on=today + timedelta(days=5),
            ),
            ShipDefect(
                tenant_id=tenant.id,
                vessel_id=v4.id,
                defect_no="DEF-44",
                title="Aux boiler refractory cracked",
                severity="critical",
                status="open",
                found_on=today - timedelta(days=2),
                due_on=today + timedelta(days=4),
            ),
        ]
    )

    crew_rows = [
        (v2, "Capt. James Ong", "Master", "SG"),
        (v2, "C/E Hiro Tanaka", "Chief Engineer", "JP"),
        (v2, "2/O Maria Silva", "2nd Officer", "PH"),
        (v1, "Capt. Wei Lim", "Master", "CN"),
        (v4, "Capt. Ravi Patel", "Master", "IN"),
        (v4, "C/E Tom Hughes", "Chief Engineer", "GB"),
    ]
    for vessel, name, rank, nat in crew_rows:
        db.add(
            ShipCrewMember(
                tenant_id=tenant.id,
                vessel_id=vessel.id,
                full_name=name,
                rank=rank,
                nationality=nat,
                contract_end=today + timedelta(days=90),
                status="onboard",
            )
        )

    db.add_all(
        [
            ShipSparePart(
                tenant_id=tenant.id,
                vessel_id=v2.id,
                part_no="BP-SEAL-02",
                description="Ballast pump mechanical seal",
                qty_on_hand=Decimal("1"),
                min_qty=Decimal("2"),
                location="ER store",
            ),
            ShipSparePart(
                tenant_id=tenant.id,
                vessel_id=v4.id,
                part_no="AB-REF-KIT",
                description="Aux boiler refractory kit",
                qty_on_hand=Decimal("0"),
                min_qty=Decimal("1"),
                location="Shore warehouse",
            ),
        ]
    )

    # External PMS connector
    if not db.scalar(
        select(ConnectorInstance).where(
            ConnectorInstance.tenant_id == tenant.id, ConnectorInstance.connector_type == "pms.mock"
        )
    ):
        db.add(
            ConnectorInstance(
                tenant_id=tenant.id,
                connector_type="pms.mock",
                instance_name="MariOS Mock PMS",
                status="active",
                endpoint="https://pms.mock.marios.local",
                config={"mode": "demo_pull"},
                last_health={"ok": True, "message": "seeded"},
            )
        )

    db.commit()
    _seed_demo_flow_extra(db, tenant)


def _seed_market_history(db: Session, tenant) -> None:
    """行情单点 + 60 天指数历史（行情页瓦片 + 走势图）。主流程与二次补种共用，幂等。

    注意：测试夹具 session 是 autoflush=False，单点行情必须先 flush，
    否则 60 天序列的幂等 SELECT 看不到 pending 行，BDI@today / BCI@yesterday
    会重复插入 → UNIQUE(tenant,symbol,quote_date) 冲突。
    """
    from app.models_domain import MarketQuote

    today = date.today()
    for i, (sym, val) in enumerate([("BDI", 1680), ("BCI", 2450), ("VLSFO_SG", 545), ("HSFO_RTM", 480), ("EUA", 73.5)]):
        qdate = today - timedelta(days=i)
        exists = db.scalar(
            select(MarketQuote).where(
                MarketQuote.tenant_id == tenant.id,
                MarketQuote.symbol == sym,
                MarketQuote.quote_date == qdate,
            )
        )
        if not exists:
            db.add(
                MarketQuote(
                    tenant_id=tenant.id,
                    symbol=sym,
                    quote_date=qdate,
                    value=Decimal(str(val)),
                    source="seed",
                )
            )
    db.flush()
    # 30 天走势图需要历史序列 —— demo 库常只落单点。幂等补 ~60 天 BDI/BCI/BPI
    # （行情页指数瓦片 + history 曲线读取的序列；锚点贴近近期真实区间，0 日=锚点值）。
    for day_offset in range(60):
        qdate = today - timedelta(days=day_offset)
        for sym, base in (("BDI", 1680.0), ("BCI", 2450.0), ("BPI", 1520.0)):
            exists = db.scalar(
                select(MarketQuote).where(
                    MarketQuote.tenant_id == tenant.id,
                    MarketQuote.symbol == sym,
                    MarketQuote.quote_date == qdate,
                )
            )
            if exists:
                continue
            # 确定性正弦叠加（9 日短波 + 23 日长波，合计约 ±6%）—— 非随机，图表可复现
            wave = math.sin(day_offset / 9.0) * 0.05 + math.sin(day_offset / 23.0) * 0.03
            db.add(
                MarketQuote(
                    tenant_id=tenant.id,
                    symbol=sym,
                    quote_date=qdate,
                    value=Decimal(str(round(base * (1.0 + wave), 2))),
                    source="seed",
                )
            )


def _seed_demo_pool(db: Session, tenant) -> None:
    """船池（Pooling）示例数据 —— 演示租户的「船池」页不能是空页。

    幂等：船池以「名称」为自然键，成员以「池 + 船」为自然键，结算期以「池 + 标签」为自然键。
    分配口径与 routers/pooling.py 的 calculate-fees 一致：按点数分毛收益，再扣管理费 2% + 行政费 1%。
    """
    from app.models_domain import Pool, PoolPeriod, PoolVessel
    from app.models_pooling import PoolDistribution
    from app.models_wave1 import Vessel

    pool_name = "Asia-Europe Spot Pool"
    pool = db.scalar(select(Pool).where(Pool.tenant_id == tenant.id, Pool.name == pool_name))
    if pool is None:
        pool = Pool(tenant_id=tenant.id, name=pool_name, currency="USD", status="active")
        db.add(pool)
        db.flush()

    # (IMO, 份额点数)
    member_specs = [("9000001", "1.0000"), ("9000002", "1.5000"), ("9000004", "0.7500")]
    joined = date.today() - timedelta(days=45)
    members: list[tuple] = []
    for imo, pts in member_specs:
        v = db.scalar(select(Vessel).where(Vessel.tenant_id == tenant.id, Vessel.imo == imo))
        if v is None:
            continue
        row = db.scalar(
            select(PoolVessel).where(
                PoolVessel.pool_id == pool.id,
                PoolVessel.vessel_id == v.id,
                PoolVessel.left_on.is_(None),
            )
        )
        if row is None:
            row = PoolVessel(pool_id=pool.id, vessel_id=v.id, points=Decimal(pts), joined_on=joined)
            db.add(row)
        members.append((v, Decimal(pts)))
    db.flush()

    if not members:
        return

    quarter = (date.today().month - 1) // 3 + 1
    label = f"{date.today().year}-Q{quarter}"
    period = db.scalar(select(PoolPeriod).where(PoolPeriod.pool_id == pool.id, PoolPeriod.label == label))
    if period is not None:
        return

    total_result = Decimal("1250000.00")
    total_points = sum((p for _v, p in members), Decimal("0"))
    dist_map: dict[str, float] = {}
    mgmt_total = 0.0
    admin_total = 0.0
    period = PoolPeriod(pool_id=pool.id, label=label, status="settled", total_pool_result=total_result)
    db.add(period)
    db.flush()

    for v, pts in members:
        gross = round(float(total_result) * float(pts) / float(total_points), 2)
        mgmt = round(gross * 0.02, 2)
        admin = round(gross * 0.01, 2)
        deduction = round(mgmt + admin, 2)
        net = round(gross - deduction, 2)
        mgmt_total += mgmt
        admin_total += admin
        dist_map[str(v.id)] = gross
        db.add(
            PoolDistribution(
                tenant_id=tenant.id,
                period_id=period.id,
                vessel_id=v.id,
                points=pts,
                gross_share=Decimal(str(gross)),
                fee_deduction=Decimal(str(deduction)),
                net_share=Decimal(str(net)),
                paid_status="paid",
            )
        )

    period.distribution = {
        **dist_map,
        "_fees": {
            "management": round(mgmt_total, 2),
            "admin": round(admin_total, 2),
            "total": round(mgmt_total + admin_total, 2),
        },
    }
    db.flush()


def _seed_demo_flow_extra(db: Session, tenant) -> None:
    """二次补种：付款批次 / GL / 应计 / COA / 期租 / 费率表 / 排期块 / MariLink / 排放。

    幂等：每组数据以自然键存在性为闸门；Estimate.results 的引擎键则无条件补齐。
    测试套件置 SEED_DEMO_EXTRA=0 跳过（tests/conftest.py）：这些补种数据与
    test_exposure / test_finance_depth / test_p1_finance / test_cargo_scheduling
    的固定键（2026-09 期间、科目 1000/4000、租约列表精确断言）冲突。
    """
    import os

    # 行情历史：老 demo 库（主流程当年尚未包含 60 天序列）每次启动幂等补齐
    _seed_market_history(db, tenant)

    if os.environ.get("SEED_DEMO_EXTRA", "1") == "0":
        return

    # ── 0. demo 主数据自愈：交易对手联系方式/财务条件、租约类型化条款列 ──
    # 既有 demo 库是在这些列之前建的，启动时补一次即可补齐；仅补 None，幂等。
    _backfill_demo_master_data(db, tenant)

    # ── 0b. 船池示例数据：Pooling 是导航里的模块，演示租户不能是空页 ──
    _seed_demo_pool(db, tenant)

    from app.models_coa import CoaContract, CoaItinerary
    from app.models_domain import (
        Charter,
        EmissionRecord,
        Estimate,
        Payment,
        PaymentBatch,
        ScheduleBlock,
        Voyage,
        VoyageAccrual,
    )
    from app.models_gl import (
        AccountingPeriod,
        BusinessRule,
        ChartOfAccount,
        PeriodJournal,
    )
    from app.models_rates import RateTable, RateTableRow
    from app.models_shipshore import ShipForm, ShipReport, ShipTerminal
    from app.models_time_charter import HireStatement, TimeCharterContract
    from app.models_wave1 import Counterparty, Port, Vessel

    now = _now()
    today = date.today()
    period_ym = now.strftime("%Y-%m")

    vessels = {v.imo: v for v in db.scalars(select(Vessel).where(Vessel.tenant_id == tenant.id)).all()}
    ports = {p.unlocode: p for p in db.scalars(select(Port)).all()}
    cps = {c.name: c for c in db.scalars(select(Counterparty).where(Counterparty.tenant_id == tenant.id)).all()}
    voyages = {v.voyage_no: v for v in db.scalars(select(Voyage).where(Voyage.tenant_id == tenant.id)).all()}
    if not vessels:
        return
    v1, v2, v3, v4 = vessels.get("9000001"), vessels.get("9000002"), vessels.get("9000003"), vessels.get("9000004")
    voy1, voy3 = voyages.get("VOY-2407"), voyages.get("VOY-2405")

    # ── 1. P&L 引擎键补齐（存量行 results 缺 total_revenue/voyage_cost/tce → Estimate 列全 0）──
    engine_keys = {
        "SEED SGSIN→NLRTM Capesize": {"total_revenue": 1850000, "voyage_cost": 1430000, "tce": 16850},
        "CNTXG→JPYOK coal": {"total_revenue": 920000, "voyage_cost": 740000, "tce": 14200},
        "BRSSZ→AUBNE grains TCT": {"total_revenue": 1395000, "voyage_cost": 1085000, "tce": 15100},
    }
    for title, extra in engine_keys.items():
        est = db.scalar(select(Estimate).where(Estimate.tenant_id == tenant.id, Estimate.title == title))
        if est is not None:
            res = dict(est.results or {})
            if any(res.get(k) is None for k in extra):
                res.update(extra)
                est.results = res
    db.flush()

    # ── 2. 付款批次（demo 空表：batch + 关联一笔已存在的付款）──
    if not db.scalar(select(PaymentBatch).where(PaymentBatch.tenant_id == tenant.id)):
        p_jp = db.scalar(select(Payment).where(
            Payment.tenant_id == tenant.id, Payment.reference == "WIRE-JP-4410"
        ))
        batch = PaymentBatch(
            tenant_id=tenant.id,
            batch_number="PB-2026-0001",
            batch_date=today - timedelta(days=11),
            status="completed",
            total_amount=Decimal("2100000"),
            currency="USD",
            payment_count=1 if p_jp else 0,
            bank_charge_mode="sender",
            approved_at=now - timedelta(days=11),
            meta={"source": "seed"},
        )
        db.add(batch)
        db.flush()
        if p_jp:
            p_jp.batch_id = batch.id

    # ── 3. GL：科目表 + 规则 + 期间 + 已过账日记账 ──
    if not db.scalar(select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant.id)):
        coa_rows = [
            ("1000", "Cash & banks", "asset", None),
            ("1200", "Accounts receivable", "asset", None),
            ("2000", "Accounts payable", "liability", None),
            ("4000", "Freight revenue", "revenue", None),
            ("4010", "Demurrage revenue", "revenue", None),
            ("4100", "Time charter hire revenue", "revenue", None),
            ("5000", "Bunker cost", "expense", None),
            ("5100", "Port & disbursement cost", "expense", None),
            ("5200", "Commission", "expense", None),
            ("5900", "Other voyage cost", "expense", None),
        ]
        for code, name, atype, parent in coa_rows:
            db.add(ChartOfAccount(tenant_id=tenant.id, account_code=code, account_name=name, account_type=atype, parent_code=parent))
        db.flush()
        rules = [
            ("Freight → revenue", "invoice", "freight", "1200", "4000"),
            ("Bunker → expense", "bunker", "bunker", "5000", "2000"),
            ("Port cost → expense", "voyage", "port", "5100", "2000"),
            ("Commission → expense", "voyage", "commission", "5200", "2000"),
        ]
        for name, etype, cat, debit, credit in rules:
            db.add(BusinessRule(tenant_id=tenant.id, rule_name=name, entity_type=etype, expense_category=cat, debit_account=debit, credit_account=credit))
    for p in (period_ym, (now - timedelta(days=40)).strftime("%Y-%m")):
        if not db.scalar(select(AccountingPeriod).where(AccountingPeriod.tenant_id == tenant.id, AccountingPeriod.period == p)):
            db.add(AccountingPeriod(tenant_id=tenant.id, period=p, status="closed" if p != period_ym else "open",
                                    closed_at=now - timedelta(days=1) if p != period_ym else None))
    if not db.scalar(select(PeriodJournal).where(PeriodJournal.tenant_id == tenant.id)):
        entries = [
            {"account": "1200", "debit": 1850000, "credit": 0, "reference": "INV-2407-FRT", "description": "Freight billed"},
            {"account": "4000", "debit": 0, "credit": 1850000, "reference": "INV-2407-FRT", "description": "Freight revenue"},
            {"account": "5000", "debit": 433275, "credit": 0, "reference": "BNK-2407", "description": "VLSFO 795mt @ 545"},
            {"account": "2000", "debit": 0, "credit": 433275, "reference": "BNK-2407", "description": "Bunker payable"},
            {"account": "5100", "debit": 44850, "credit": 0, "reference": "FDA-2407", "description": "Load port disbursement"},
            {"account": "2000", "debit": 0, "credit": 44850, "reference": "FDA-2407", "description": "Port payable"},
        ]
        db.add(PeriodJournal(
            tenant_id=tenant.id, period=period_ym, journal_type="voyage",
            description="VOY-2407 accrual & billing (seed)", entries=entries,
            total_debit=Decimal("2328125"), total_credit=Decimal("2328125"),
            status="posted", posted_at=now,
        ))

    # ── 4. 航次应计（status=posted → P&L Posted 列）──
    if voy1 and not db.scalar(select(VoyageAccrual).where(VoyageAccrual.tenant_id == tenant.id, VoyageAccrual.voyage_id == voy1.id)):
        for line, amt, notes in (
            ("freight", Decimal("1850000"), "INV-2407-FRT"),
            ("bunker", Decimal("433275"), "BNK-2407 795mt@545"),
            ("port", Decimal("44850"), "FDA load port"),
            ("commission", Decimal("23125"), "1.25% address commission"),
        ):
            db.add(VoyageAccrual(tenant_id=tenant.id, voyage_id=voy1.id, period_ym=period_ym,
                                 line_type=line, amount=amt, status="posted", notes=notes))
    if voy3 and not db.scalar(select(VoyageAccrual).where(VoyageAccrual.tenant_id == tenant.id, VoyageAccrual.voyage_id == voy3.id)):
        for line, amt, notes in (
            ("freight", Decimal("2100000"), "INV-2405-FRT"),
            ("port", Decimal("38000"), "disch port estimate"),
        ):
            db.add(VoyageAccrual(tenant_id=tenant.id, voyage_id=voy3.id, period_ym=(now - timedelta(days=30)).strftime("%Y-%m"),
                                 line_type=line, amount=amt, status="posted", notes=notes))

    # ── 5. COA 合同（Charter parent + CoaContract + itineraries）──
    _terms = _charter_term_sets(today, ports)
    if not db.scalar(select(CoaContract).where(CoaContract.tenant_id == tenant.id)):
        ch_coa = Charter(
            tenant_id=tenant.id, charter_no="CP-COA-2601", charter_type="coa", status="active",
            vessel_id=v1.id if v1 else None,
            counterparty_id=cps.get("Nordic Grain Traders").id if cps.get("Nordic Grain Traders") else None,
            laycan_from=today, laycan_to=today + timedelta(days=180),
            clauses={"description": "COA parent fixture (seed)"},
            **_terms["CP-COA-2601"],
        )
        db.add(ch_coa)
        db.flush()
        coa = CoaContract(
            tenant_id=tenant.id, coa_no="COA-2026-0001", charter_id=ch_coa.id,
            total_qty=Decimal("300000"), qty_unit="mt",
            period_from=today, period_to=today + timedelta(days=360),
            rate_basis="per_mt", rate=Decimal("11.50"), currency="USD",
            cargo_spec="Coal / grains parcels 50kt ±5%", bill_by="weight",
            tolerance_pct=Decimal("5"), overage_pct=Decimal("10"), status="active",
        )
        db.add(coa)
        db.flush()
        txg = ports.get("CNTXG"); jpyok = ports.get("JPYOK"); brssz = ports.get("BRSSZ"); aubne = ports.get("AUBNE")
        legs = [
            (1, txg.id if txg else None, jpyok.id if jpyok else None, Decimal("100000"), Decimal("50000")),
            (2, txg.id if txg else None, jpyok.id if jpyok else None, Decimal("100000"), Decimal("0")),
            (3, brssz.id if brssz else None, aubne.id if aubne else None, Decimal("100000"), Decimal("0")),
        ]
        for seq, lp, dp, qty, alloc in legs:
            db.add(CoaItinerary(tenant_id=tenant.id, coa_contract_id=coa.id, seq=seq,
                                load_port_id=lp, disch_port_id=dp, qty=qty, allocated_qty=alloc,
                                notes="seed lifting leg"))

    # ── 6. 期租合同（Charter tc parent + TimeCharterContract）──
    if not db.scalar(select(TimeCharterContract).where(TimeCharterContract.tenant_id == tenant.id)):
        ng = cps.get("Nordic Grain Traders")
        ch_tc = Charter(
            tenant_id=tenant.id, charter_no="CP-TC-2602", charter_type="tct", status="active",
            vessel_id=v4.id if v4 else None,
            counterparty_id=ng.id if ng else None,
            hire_per_day=Decimal("15500"), commission_pct=Decimal("1.25"),
            laycan_from=today + timedelta(days=5), laycan_to=today + timedelta(days=15),
            clauses={"duration_days": 90},
            **_terms["CP-TC-2602"],
        )
        db.add(ch_tc)
        db.flush()
        db.add(TimeCharterContract(
            tenant_id=tenant.id, charter_id=ch_tc.id, contract_type="tci",
            vessel_id=v4.id, counterparty_id=ng.id,
            delivery_port="Singapore", delivery_date=today + timedelta(days=10),
            redelivery_port="Brisbane", redelivery_date=today + timedelta(days=100),
            hire_rate=Decimal("15500"), hire_currency="USD", payment_frequency="monthly",
            cancel_date=today + timedelta(days=3), status="active",
        ))
        db.flush()

    # 期租租金单（hire statements）——demo 里此前为 0 行，期租台账与
    # GET /hire-statements 都看不到东西。按月生成整个合同期（幂等：已有则跳过）。
    if not db.scalar(select(HireStatement).where(HireStatement.tenant_id == tenant.id)):
        from app.services.hire_engine import generate_all_statements

        tc_contract = db.scalar(
            select(TimeCharterContract).where(
                TimeCharterContract.tenant_id == tenant.id,
                TimeCharterContract.contract_type == "tci",
            )
        )
        if tc_contract is not None:
            generate_all_statements(db, tc_contract)

    # ── 7. 费率表 ──
    if not db.scalar(select(RateTable).where(RateTable.tenant_id == tenant.id)):
        rt = RateTable(
            tenant_id=tenant.id, name="SEED Freight Matrix", kind="freight_matrix",
            currency="USD", valid_from=today - timedelta(days=90), valid_to=today + timedelta(days=270),
            description="Capesize coal/grain FIOS matrix (seed)", is_active=True,
        )
        db.add(rt)
        db.flush()
        matrix = [
            ({"load_port": "SGSIN", "disch_port": "NLRTM", "cargo_type": "iron_ore"}, Decimal("24.67"), 10),
            ({"load_port": "CNTXG", "disch_port": "JPYOK", "cargo_type": "coal"}, Decimal("11.80"), 10),
            ({"load_port": "BRSSZ", "disch_port": "AUBNE", "cargo_type": "grains"}, Decimal("18.40"), 10),
            ({"cargo_type": "coal"}, Decimal("12.50"), 1),  # fallback row
        ]
        for dims, value, prio in matrix:
            db.add(RateTableRow(tenant_id=tenant.id, rate_table_id=rt.id, dims=dims, value=value, unit="per_mt", priority=prio))
        sur = RateTable(
            tenant_id=tenant.id, name="SEED Bunker Surcharges", kind="bunker_surcharge",
            currency="USD", valid_from=today - timedelta(days=90), valid_to=today + timedelta(days=270),
            description="VLSFO/LSGO differentials (seed)", is_active=True,
        )
        db.add(sur)
        db.flush()
        for dims, value, prio in (
            ({"grade": "VLSFO", "port": "SGSIN"}, Decimal("545.00"), 10),
            ({"grade": "HSFO", "port": "NLRTM"}, Decimal("480.00"), 10),
            ({"grade": "LSGO", "port": "SGSIN"}, Decimal("690.00"), 5),
        ):
            db.add(RateTableRow(tenant_id=tenant.id, rate_table_id=sur.id, dims=dims, value=value, unit="lumpsum", priority=prio))

    # ── 8. 排期块（航次/修理/停租 → 调度甘特图）──
    if not db.scalar(select(ScheduleBlock).where(ScheduleBlock.tenant_id == tenant.id)):
        blocks = []
        if voy1 and v2:
            blocks.append(ScheduleBlock(
                tenant_id=tenant.id, vessel_id=v2.id, block_type="voyage",
                title="VOY-2407 SGSIN→NLRTM", start_at=now - timedelta(days=12), end_at=now + timedelta(days=12),
                voyage_id=voy1.id, hard_conflict=False,
            ))
        voy2 = voyages.get("VOY-2408")
        if voy2 and v1:
            blocks.append(ScheduleBlock(
                tenant_id=tenant.id, vessel_id=v1.id, block_type="voyage",
                title="VOY-2408 CNTXG→JPYOK", start_at=today + timedelta(days=6), end_at=today + timedelta(days=24),
                voyage_id=voy2.id, hard_conflict=False,
            ))
        if v3:
            blocks.append(ScheduleBlock(
                tenant_id=tenant.id, vessel_id=v3.id, block_type="offhire",
                title="ATLANTIC PEARL off-hire survey", start_at=today - timedelta(days=40), end_at=today - timedelta(days=37),
                hard_conflict=False,
            ))
        if v4:
            blocks.append(ScheduleBlock(
                tenant_id=tenant.id, vessel_id=v4.id, block_type="repair",
                title="INDIAN MONSOON drydock window", start_at=today + timedelta(days=20), end_at=today + timedelta(days=35),
                hard_conflict=False,
            ))
        db.add_all(blocks)

    # ── 9. MariLink（终端 + 表单模板 + 报文实例）──
    if v2 and not db.scalar(select(ShipTerminal).where(ShipTerminal.tenant_id == tenant.id)):
        term = ShipTerminal(
            tenant_id=tenant.id, vessel_id=v2.id, terminal_key="SEED-TERM-9000002",
            device_info={"ua": "MariOS-PWA", "os": "seed"}, sw_version="1.0.0",
            last_sync_at=now - timedelta(hours=6), last_position={"lat": 25.1, "lon": 55.0, "speed": 13.0},
            status="active",
        )
        db.add(term)
        db.flush()
        f_noon = ShipForm(
            tenant_id=tenant.id, form_type="noon_report", form_name="Daily noon report",
            schema_json={"type": "object", "required": ["speed", "rob_fo"]},
            fields_json=[
                {"key": "speed", "label": "Speed (kn)", "type": "number"},
                {"key": "rob_fo", "label": "ROB FO (mt)", "type": "number"},
                {"key": "remarks", "label": "Remarks", "type": "text"},
            ],
            auto_import=True, target_model="noon_report", is_active=True, sort_order=1,
        )
        f_arr = ShipForm(
            tenant_id=tenant.id, form_type="arrival_notice", form_name="Arrival notice",
            schema_json={"type": "object", "required": ["eta"]},
            fields_json=[{"key": "eta", "label": "ETA", "type": "datetime"}, {"key": "pilot", "label": "Pilot boarded", "type": "boolean"}],
            auto_import=False, is_active=True, sort_order=2,
        )
        db.add_all([f_noon, f_arr])
        db.flush()
        db.add_all([
            ShipReport(
                tenant_id=tenant.id, terminal_id=term.id, form_id=f_noon.id,
                voyage_id=voy1.id if voy1 else None, form_type="noon_report",
                report_ref="NR-SEED-001", submitted_at=now - timedelta(days=1),
                submitted_by="Capt. James Ong / Master",
                data_json={"speed": 12.8, "rob_fo": 612, "remarks": "Fair weather, on schedule"},
                position={"lat": 25.1, "lon": 55.0}, status="submitted",
            ),
            ShipReport(
                tenant_id=tenant.id, terminal_id=term.id, form_id=f_noon.id,
                voyage_id=voy1.id if voy1 else None, form_type="noon_report",
                report_ref="NR-SEED-000", submitted_at=now - timedelta(days=2),
                submitted_by="Capt. James Ong / Master",
                data_json={"speed": 13.1, "rob_fo": 640, "remarks": "Slight head sea"},
                position={"lat": 22.4, "lon": 58.9}, status="approved",
                reviewed_at=now - timedelta(days=2), imported_model="noon_report",
            ),
            ShipReport(
                tenant_id=tenant.id, terminal_id=term.id, form_id=f_arr.id,
                voyage_id=voy1.id if voy1 else None, form_type="arrival_notice",
                report_ref="AN-SEED-001", submitted_at=now - timedelta(hours=8),
                submitted_by="Rotterdam Agency BV / Agent",
                data_json={"eta": (now + timedelta(days=8)).isoformat(), "pilot": False},
                status="review",
            ),
        ])

    # ── 10. 排放记录（emissions 页 demo 空表）──
    if not db.scalar(select(EmissionRecord).where(EmissionRecord.tenant_id == tenant.id)):
        rows = []
        if voy1 and v2:
            rows.append(EmissionRecord(tenant_id=tenant.id, voyage_id=voy1.id, vessel_id=v2.id,
                                       fo_mt=Decimal("630.000"), do_mt=Decimal("30.000"), co2_mt=Decimal("2058.690"),
                                       cii_rating="C", period=period_ym))
        if voy3 and v3:
            rows.append(EmissionRecord(tenant_id=tenant.id, voyage_id=voy3.id, vessel_id=v3.id,
                                       fo_mt=Decimal("540.000"), do_mt=Decimal("28.000"), co2_mt=Decimal("1771.168"),
                                       cii_rating="B", period=(now - timedelta(days=30)).strftime("%Y-%m")))
        if v1:
            rows.append(EmissionRecord(tenant_id=tenant.id, vessel_id=v1.id,
                                       fo_mt=Decimal("410.000"), do_mt=Decimal("18.000"), co2_mt=Decimal("1334.108"),
                                       cii_rating="A", period=period_ym))
        db.add_all(rows)

    db.commit()


def stamp_demo_attribution(db: Session, tenant) -> None:
    """给演示数据补「创建人 / 修改人」—— 归属条才有内容可显示。

    种子数据是脚本写的：既没有 created_by / updated_by 持久列，审计账本里也没有
    「创建」记录，于是详情页顶部的归属条（RecordAttribution）永远显示「—」。
    这里统一按演示租户管理员补齐：

    * 有持久列的表（voyages / invoices / estimates）—— 直接回填空列；
    * 只有审计账本的主数据（counterparties / vessels / ports / companies）
      —— 补一条 ``<entity>.create`` 账本记录，归属条从账本还原。

    幂等：只补空值；账本已有记录的主数据不再重复写。
    审计时间取记录自身的 created_at（而不是写库时刻），
    这样补录的条目不会挤占工作台「最近活动」的首屏。
    """
    from sqlalchemy import update

    from app.models_audit import AuditLog
    from app.models_domain import Estimate, Invoice, Voyage
    from app.models import User
    from app.models_wave1 import Company, Counterparty, Port, Vessel

    admin = db.scalar(
        select(User).where(User.tenant_id == tenant.id, User.email == "admin@demo.marios")
    ) or db.scalars(
        select(User).where(User.tenant_id == tenant.id).order_by(User.created_at.asc())
    ).first()
    if admin is None:
        return

    # 1) 有持久归属列的表：回填空列（不覆盖已有值）
    for model in (Voyage, Invoice, Estimate):
        db.execute(
            update(model)
            .where(model.tenant_id == tenant.id, model.created_by.is_(None))
            .values(created_by=admin.id)
        )
    for model in (Voyage, Invoice):
        db.execute(
            update(model)
            .where(model.tenant_id == tenant.id, model.updated_by.is_(None))
            .values(updated_by=admin.id)
        )

    # 2) 只有审计账本的主数据：补一条创建记录
    for model, entity_type in (
        (Counterparty, "counterparty"),
        (Vessel, "vessel"),
        (Port, "port"),
        (Company, "company"),
    ):
        rows = db.scalars(select(model)).all()
        for row in rows:
            if getattr(row, "tenant_id", None) is not None and row.tenant_id != tenant.id:
                continue  # 其他租户 / 全局参考数据不写入本租户账本
            exists = db.scalar(
                select(AuditLog.id).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_type == entity_type,
                    AuditLog.entity_id == str(row.id),
                ).limit(1)
            )
            if exists:
                continue
            db.add(
                AuditLog(
                    tenant_id=tenant.id,
                    actor_user_id=admin.id,
                    action=f"{entity_type}.create",
                    entity_type=entity_type,
                    entity_id=str(row.id),
                    detail={"seeded": True},
                    created_at=getattr(row, "created_at", None) or utcnow_naive(),
                )
            )
    db.flush()
