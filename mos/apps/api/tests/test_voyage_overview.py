"""Voyage 360 overview aggregation + voyage_id filters on claims/invoices/laytimes."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_domain import (
    Charter,
    Claim,
    Estimate,
    Invoice,
    LaytimeCalc,
    NoonReport,
    OffHireEvent,
    PortCall,
    Voyage,
)
from app.models_wave1 import Company, Counterparty, Vessel
from tests.isolation_helpers import create_tenant


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db):
    return db.scalar(select(Company).limit(1)).tenant_id


def _uniq():
    return uuid4().hex[:8]


def _build_voyage(db, tid):
    vessel = Vessel(tenant_id=tid, name=f"OV Vessel {_uniq()}", imo=f"8{uuid4().int % 10**6:06d}", flag="SG")
    party = Counterparty(tenant_id=tid, name=f"OV CP {_uniq()}", country="SG")
    est = Estimate(
        tenant_id=tid,
        title=f"OV EST {_uniq()}",
        status="converted",
        results={
            "total_revenue": 120000.0,
            "voyage_cost": 40000.0,
            "tce": 12345.67,
            "bunker_cost": 30000.0,
            "commission": 1500.0,
            "emissions_cost": 2000.0,
            "currency": "USD",
        },
    )
    db.add_all([vessel, party, est])
    db.commit()
    charter = Charter(
        tenant_id=tid,
        charter_no=f"CP-OV-{_uniq()}",
        charter_type="voyage",
        status="active",
        vessel_id=vessel.id,
        counterparty_id=party.id,
        estimate_id=est.id,
    )
    db.add(charter)
    db.commit()
    voyage = Voyage(
        tenant_id=tid,
        voyage_no=f"OV-{_uniq()}",
        status="in_progress",
        vessel_id=vessel.id,
        charter_id=charter.id,
        cp_date=date.today() - timedelta(days=10),
        started_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.add(voyage)
    db.commit()
    db.add(
        PortCall(
            tenant_id=tid,
            voyage_id=voyage.id,
            seq=1,
            purpose="load",
            eta=datetime.now(timezone.utc) + timedelta(days=2),
        )
    )
    db.add(NoonReport(tenant_id=tid, voyage_id=voyage.id, report_at=datetime.now(timezone.utc)))
    db.add(
        LaytimeCalc(
            tenant_id=tid,
            voyage_id=voyage.id,
            status="finalized",
            results={"result_type": "demurrage", "amount": 4000.0, "currency": "USD"},
        )
    )
    db.add(
        Claim(
            tenant_id=tid,
            claim_no=f"CLM-OV-{_uniq()}",
            status="open",
            voyage_id=voyage.id,
            amount=Decimal("4000"),
            time_bar=date.today() + timedelta(days=120),
        )
    )
    db.add(
        Invoice(
            tenant_id=tid,
            invoice_no=f"INV-OV-{_uniq()}",
            invoice_type="freight",
            status="issued",
            voyage_id=voyage.id,
            counterparty_id=party.id,
            amount=Decimal("5000"),
            due_date=date.today() + timedelta(days=30),
        )
    )
    db.add(
        OffHireEvent(
            tenant_id=tid,
            voyage_id=voyage.id,
            start_at=datetime.now(timezone.utc) - timedelta(days=1),
            reason="Main engine",
            deduct_hire=True,
        )
    )
    db.commit()
    return voyage, charter, est


def test_overview_structure(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage, charter, est = _build_voyage(db_session, tid)
    r = client.get(f"/api/v1/voyages/{voyage.id}/overview", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()

    v = data["voyage"]
    assert v["id"] == str(voyage.id)
    assert v["voyage_no"] == voyage.voyage_no
    assert v["status"] == "in_progress"
    assert v["vessel_name"].startswith("OV Vessel")
    assert v["cp_date"] == (date.today() - timedelta(days=10)).isoformat()
    assert v["started_at"] is not None

    ch = data["charter"]
    assert ch["charter_no"] == charter.charter_no
    assert ch["charter_type"] == "voyage"
    assert ch["counterparty_name"].startswith("OV CP")
    assert ch["estimate_id"] == str(est.id)

    assert data["estimate"]["status"] == "converted"
    assert data["estimate"]["results_summary"] == {"total_revenue": 120000.0, "voyage_cost": 40000.0, "tce": 12345.67}

    assert len(data["port_calls"]) == 1
    assert data["port_calls"][0]["purpose"] == "load"
    assert data["noon_reports_count"] == 1
    assert data["laytime"][0]["result_type"] == "demurrage"
    assert data["laytime"][0]["amount"] == 4000.0
    assert data["claims"][0]["amount"] == 4000.0
    assert data["invoices"][0]["invoice_type"] == "freight"
    assert data["off_hire"][0]["deduct_hire"] is True


def test_overview_lifecycle(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage, _, _ = _build_voyage(db_session, tid)
    data = client.get(f"/api/v1/voyages/{voyage.id}/overview", headers=auth_headers).json()
    steps = {s["key"]: s for s in data["lifecycle"]}
    assert list(steps) == ["estimate", "charter", "execution", "laytime", "invoicing", "settlement", "closed"]
    assert steps["estimate"]["state"] == "done"
    assert steps["charter"]["state"] == "done"
    assert steps["execution"]["state"] == "current"
    assert steps["laytime"]["state"] == "done"
    assert steps["invoicing"]["state"] == "current"
    assert steps["settlement"]["state"] == "current"  # open claim outstanding
    assert steps["closed"]["state"] == "todo"
    for step in steps.values():
        assert step["label"]["en"] and step["label"]["zh"]
        assert step["href"] and step["detail"]


def test_overview_pnl_lines(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage, _, _ = _build_voyage(db_session, tid)
    data = client.get(f"/api/v1/voyages/{voyage.id}/overview", headers=auth_headers).json()
    pnl = data["pnl"]
    assert pnl["currency"] == "USD"
    assert pnl["estimated_pnl"] == 80000.0
    assert pnl["actual_pnl"] == 5000.0
    assert pnl["variance_pnl"] == 5000.0 - 80000.0
    lines = {l["key"]: l for l in pnl["lines"]}
    assert set(lines) == {"revenue", "hire", "demurrage", "port_costs", "canal", "bunker", "commission", "emissions", "other"}
    assert lines["revenue"]["estimated"] == 120000.0
    assert lines["revenue"]["actual"] == 5000.0
    assert lines["revenue"]["variance"] == 5000.0 - 120000.0
    assert lines["bunker"]["estimated"] == 30000.0
    assert lines["emissions"]["estimated"] == 2000.0
    assert lines["hire"]["estimated"] is None  # no estimate-side hire mapping
    assert lines["canal"]["estimated"] is None


def test_overview_cross_tenant_404(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage, _, _ = _build_voyage(db_session, tid)
    _, hb = create_tenant(client, code="oviso", name="OV Iso", admin_email="admin@oviso.example.com")
    r = client.get(f"/api/v1/voyages/{voyage.id}/overview", headers=hb)
    assert r.status_code == 404
    r = client.get(f"/api/v1/voyages/{uuid4()}/overview", headers=auth_headers)
    assert r.status_code == 404


def test_voyage_id_filters(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage, _, _ = _build_voyage(db_session, tid)
    other = Voyage(tenant_id=tid, voyage_no=f"OV-OTHER-{_uniq()}", status="planned")
    db_session.add(other)
    db_session.commit()
    db_session.add(
        Claim(tenant_id=tid, claim_no=f"CLM-OTHER-{_uniq()}", status="open", voyage_id=other.id, amount=Decimal("1"))
    )
    db_session.add(
        Invoice(tenant_id=tid, invoice_no=f"INV-OTHER-{_uniq()}", voyage_id=other.id, amount=Decimal("1"))
    )
    db_session.add(LaytimeCalc(tenant_id=tid, voyage_id=other.id, status="draft"))
    db_session.commit()

    vid = str(voyage.id)
    claims = client.get(f"/api/v1/claims?voyage_id={vid}", headers=auth_headers).json()
    assert {c["voyage_id"] for c in claims} == {vid}
    invoices = client.get(f"/api/v1/invoices?voyage_id={vid}", headers=auth_headers).json()
    assert {i["voyage_id"] for i in invoices} == {vid}
    laytimes = client.get(f"/api/v1/laytimes?voyage_id={vid}", headers=auth_headers).json()
    assert {lt["voyage_id"] for lt in laytimes} == {vid}
    # unfiltered lists stay backward compatible (contain both voyages' rows)
    all_laytimes = client.get("/api/v1/laytimes", headers=auth_headers).json()
    assert {lt["voyage_id"] for lt in all_laytimes} >= {vid, str(other.id)}
