"""Exception centre scan: signal detection, severity, tenant isolation, notifications."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models_domain import (
    Charter,
    Claim,
    Estimate,
    Invoice,
    LaytimeCalc,
    NoonReport,
    OffHireEvent,
    Voyage,
)
from app.models_ship import ShipCertificate
from app.models_wave1 import Company, Counterparty, Notification, Vessel
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


def _vessel(db, tid):
    v = Vessel(tenant_id=tid, name=f"EX Vessel {_uniq()}", imo=f"9{uuid4().int % 10**6:06d}", flag="PA")
    db.add(v)
    db.commit()
    return v


def _voyage(db, tid, **fields):
    v = Voyage(tenant_id=tid, voyage_no=f"EX-{_uniq()}", status="in_progress", **fields)
    db.add(v)
    db.commit()
    return v


def _make_all_signals(db, tid):
    vessel = _vessel(db, tid)
    est = Estimate(
        tenant_id=tid,
        title=f"EX EST {_uniq()}",
        status="calculated",
        results={"total_revenue": 100000.0, "voyage_cost": 0.0, "tce": 5000.0, "currency": "USD"},
    )
    db.add(est)
    db.commit()
    charter = Charter(tenant_id=tid, charter_no=f"CP-{_uniq()}", status="active", estimate_id=est.id)
    db.add(charter)
    db.commit()
    voyage = _voyage(db, tid, charter_id=charter.id, vessel_id=vessel.id)
    # pnl_deterioration (critical): estimate 100k, no actuals → variance -100k
    # eta_delay (critical): latest noon deviation 30h
    db.add(
        NoonReport(
            tenant_id=tid,
            voyage_id=voyage.id,
            report_at=datetime.now(timezone.utc),
            eta_deviation_hours=Decimal("30"),
        )
    )
    # demurrage_open (warning)
    db.add(
        LaytimeCalc(
            tenant_id=tid,
            voyage_id=voyage.id,
            status="calculated",
            results={"result_type": "demurrage", "amount": 5000.0, "currency": "USD"},
        )
    )
    # claim_timebar (critical): 10 days left
    db.add(
        Claim(
            tenant_id=tid,
            claim_no=f"CLM-{_uniq()}",
            status="open",
            voyage_id=voyage.id,
            amount=Decimal("8000"),
            time_bar=date.today() + timedelta(days=10),
        )
    )
    # invoice_overdue (critical): 40 days past due
    db.add(
        Invoice(
            tenant_id=tid,
            invoice_no=f"INV-EX-{_uniq()}",
            status="issued",
            voyage_id=voyage.id,
            amount=Decimal("1000"),
            due_date=date.today() - timedelta(days=40),
        )
    )
    # cert_expired (critical)
    db.add(
        ShipCertificate(
            tenant_id=tid,
            vessel_id=vessel.id,
            cert_code="IOPP",
            cert_name="IOPP Certificate",
            expires_on=date.today() - timedelta(days=1),
        )
    )
    # off_hire_open (warning)
    db.add(
        OffHireEvent(
            tenant_id=tid,
            voyage_id=voyage.id,
            start_at=datetime.now(timezone.utc) - timedelta(days=2),
            reason="Engine failure",
            deduct_hire=True,
        )
    )
    # tc_redelivery_due (warning)
    db.add(
        Charter(
            tenant_id=tid,
            charter_no=f"TC-{_uniq()}",
            charter_type="tct",
            status="active",
            redelivery_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
    )
    # sanctions_blocked (critical)
    party = Counterparty(tenant_id=tid, name=f"EX CP {_uniq()}", sanctions_status="blocked")
    db.add(party)
    db.commit()
    db.add(
        Charter(tenant_id=tid, charter_no=f"SB-{_uniq()}", status="active", counterparty_id=party.id)
    )
    db.commit()
    return voyage


def _scan(client, h):
    r = client.get("/api/v1/exceptions/scan", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_scan_detects_signals(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    _make_all_signals(db_session, tid)
    data = _scan(client, auth_headers)
    by_kind = {}
    for item in data["items"]:
        by_kind.setdefault(item["kind"], item)
        assert item["severity"] in ("critical", "warning")
        assert item["href"]
        assert item["detected_at"]
    expected = {
        "pnl_deterioration": "critical",
        "eta_delay": "critical",
        "demurrage_open": "warning",
        "claim_timebar": "critical",
        "invoice_overdue": "critical",
        "cert_expired": "critical",
        "off_hire_open": "warning",
        "tc_redelivery_due": "warning",
        "sanctions_blocked": "critical",
    }
    for kind, severity in expected.items():
        assert kind in by_kind, f"missing {kind}"
        assert by_kind[kind]["severity"] == severity, f"{kind}: {by_kind[kind]}"
    assert data["summary"]["total"] == len(data["items"])
    assert data["summary"]["critical"] + data["summary"]["warning"] == data["summary"]["total"]
    # critical items sort ahead of warnings
    severities = [i["severity"] for i in data["items"]]
    assert severities == sorted(severities, key=lambda s: s != "critical")


def test_scan_warning_thresholds(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage = _voyage(db_session, tid)
    # eta_delay warning band (6h ≤ dev < 24h)
    db_session.add(
        NoonReport(
            tenant_id=tid,
            voyage_id=voyage.id,
            report_at=datetime.now(timezone.utc),
            eta_deviation_hours=Decimal("8"),
        )
    )
    # invoice overdue ≤ 30 days → warning
    db_session.add(
        Invoice(
            tenant_id=tid,
            invoice_no=f"INV-EX-{_uniq()}",
            status="partially_paid",
            amount=Decimal("2000"),
            paid_amount=Decimal("500"),
            due_date=date.today() - timedelta(days=5),
        )
    )
    db_session.commit()
    data = _scan(client, auth_headers)
    eta = [i for i in data["items"] if i["kind"] == "eta_delay" and i["entity_id"] == str(voyage.id)]
    assert eta and eta[0]["severity"] == "warning"
    inv = [i for i in data["items"] if i["kind"] == "invoice_overdue" and i["value"].startswith("1,500")]
    assert inv and inv[0]["severity"] == "warning"


def test_scan_empty_tenant(client):
    _, h = create_tenant(client, code="exempty", name="EX Empty", admin_email="admin@exempty.example.com")
    data = _scan(client, h)
    assert data["summary"] == {"critical": 0, "warning": 0, "total": 0}
    assert data["items"] == []


def test_scan_tenant_isolation(client, auth_headers, db_session):
    _, hb = create_tenant(client, code="exiso", name="EX Iso", admin_email="admin@exiso.example.com")
    from app.models import Tenant

    tid_b = db_session.scalar(select(Tenant.id).where(Tenant.code == "exiso"))
    db_session.add(
        Invoice(
            tenant_id=tid_b,
            invoice_no=f"INV-EX-{_uniq()}",
            status="issued",
            amount=Decimal("9999"),
            due_date=date.today() - timedelta(days=60),
        )
    )
    db_session.commit()
    data_b = _scan(client, hb)
    assert any(i["kind"] == "invoice_overdue" for i in data_b["items"])
    data_a = _scan(client, auth_headers)
    foreign_ids = {i["entity_id"] for i in data_b["items"]} - {None}
    assert not any(i["entity_id"] in foreign_ids for i in data_a["items"])


def test_scan_critical_notifications_deduped(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    _make_all_signals(db_session, tid)
    _scan(client, auth_headers)
    count_after_first = db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.tenant_id == tid)
    ) or 0
    assert count_after_first > 0
    _scan(client, auth_headers)
    count_after_second = db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.tenant_id == tid)
    ) or 0
    assert count_after_second == count_after_first


def test_home_summary_includes_exceptions(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    _make_all_signals(db_session, tid)
    r = client.get("/api/v1/home/summary", headers=auth_headers)
    assert r.status_code == 200, r.text
    exc = r.json()["exceptions"]
    scan = _scan(client, auth_headers)
    assert exc["critical"] == scan["summary"]["critical"]
    assert exc["warning"] == scan["summary"]["warning"]


def test_scan_requires_login(client):
    assert client.get("/api/v1/exceptions/scan").status_code == 401
