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

    # Marker: already seeded full flow
    if db.scalar(select(Estimate).where(Estimate.tenant_id == tenant.id, Estimate.title == "SEED SGSIN→NLRTM Capesize")):
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

    # Estimates
    est_data = [
        (
            "SEED SGSIN→NLRTM Capesize",
            v2,
            cps["Nordic Grain Traders"],
            "working",
            {"load_port": "SGSIN", "disch_port": "NLRTM", "cargo_mt": 75000, "freight_usd": 1850000},
            {"tce_usd_day": 16850, "voyage_days": 42, "pnl_usd": 420000},
        ),
        (
            "CNTXG→JPYOK coal",
            v1,
            cps["Pacific Steel Mills"],
            "draft",
            {"load_port": "CNTXG", "disch_port": "JPYOK", "cargo_mt": 52000, "freight_usd": 920000},
            {"tce_usd_day": 14200, "voyage_days": 18, "pnl_usd": 180000},
        ),
        (
            "BRSSZ→AUBNE grains TCT",
            v4,
            cps["Nordic Grain Traders"],
            "submitted",
            {"duration_days": 90, "hire_usd_day": 15500},
            {"tce_usd_day": 15100, "voyage_days": 90, "pnl_usd": 310000},
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
    for i, (sym, val) in enumerate([("BDI", 1680), ("BCI", 2450), ("VLSFO_SG", 545), ("HSFO_RTM", 480)]):
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
