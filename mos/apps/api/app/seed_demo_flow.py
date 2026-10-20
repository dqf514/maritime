"""Full commercial + ship-management demo flow seed (idempotent)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant


def _now() -> datetime:
    return datetime.now().astimezone()


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

    # Counterparties
    cp_defs = [
        ("Atlantic Brokers Ltd", "broker", "GB"),
        ("Nordic Grain Traders", "charterer", "NO"),
        ("Pacific Steel Mills", "charterer", "JP"),
        ("Rotterdam Agency BV", "agent", "NL"),
        ("Gulf Bunker Supply", "supplier", "SG"),
    ]
    cps: dict[str, Counterparty] = {}
    for name, ctype, country in cp_defs:
        c = db.scalar(select(Counterparty).where(Counterparty.tenant_id == tenant.id, Counterparty.name == name))
        if not c:
            c = Counterparty(tenant_id=tenant.id, name=name, type=ctype, country=country, sanctions_status="clear")
            db.add(c)
            db.flush()
        cps[name] = c

    v1, v2, v3, v4 = vessels["9000001"], vessels["9000002"], vessels["9000003"], vessels["9000004"]

    # Estimates — results 同时含展示键与 P&L 引擎键（total_revenue/voyage_cost/tce）
    est_data = [
        (
            "SEED SGSIN→NLRTM Capesize",
            v2,
            cps["Nordic Grain Traders"],
            "working",
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
            "submitted",
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
    )
    ch2 = Charter(
        tenant_id=tenant.id,
        charter_no="CP-2408",
        charter_type="voyage",
        status="submitted",
        vessel_id=v1.id,
        counterparty_id=cps["Pacific Steel Mills"].id,
        estimate_id=estimates[1].id,
        laycan_from=today + timedelta(days=5),
        laycan_to=today + timedelta(days=12),
        commission_pct=Decimal("1.25"),
        freight_terms={"freight_usd": 920000},
        clauses={"laytime_hours": 48, "demurrage_usd_day": 18000},
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


def _seed_demo_flow_extra(db: Session, tenant) -> None:
    """二次补种：付款批次 / GL / 应计 / COA / 期租 / 费率表 / 排期块 / MariLink / 排放。

    幂等：每组数据以自然键存在性为闸门；Estimate.results 的引擎键则无条件补齐。
    测试套件置 SEED_DEMO_EXTRA=0 跳过（tests/conftest.py）：这些补种数据与
    test_exposure / test_finance_depth / test_p1_finance / test_cargo_scheduling
    的固定键（2026-09 期间、科目 1000/4000、租约列表精确断言）冲突。
    """
    import os

    if os.environ.get("SEED_DEMO_EXTRA", "1") == "0":
        return
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
    from app.models_time_charter import TimeCharterContract
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
    if not db.scalar(select(CoaContract).where(CoaContract.tenant_id == tenant.id)):
        ch_coa = Charter(
            tenant_id=tenant.id, charter_no="CP-COA-2601", charter_type="coa", status="active",
            vessel_id=v1.id if v1 else None,
            counterparty_id=cps.get("Nordic Grain Traders").id if cps.get("Nordic Grain Traders") else None,
            laycan_from=today, laycan_to=today + timedelta(days=180),
            clauses={"description": "COA parent fixture (seed)"},
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
