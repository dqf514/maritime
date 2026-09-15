"""DQ auto rule engine: scan creates issues, dedupes, auto-resolves, tenant-scoped."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_domain import Invoice, Voyage
from app.models_wave1 import Company, Vessel
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


def _scan(client, h):
    r = client.post("/api/v1/dq/scan", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _issues(client, h, status="open"):
    r = client.get(f"/api/v1/dq/issues?status={status}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_scan_creates_and_dedupes(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    vessel = Vessel(tenant_id=tid, name=f"DQ Vessel {_uniq()}", status="active")
    db_session.add(vessel)
    db_session.commit()

    first = _scan(client, auth_headers)
    assert first["new"] >= 3  # imo + flag + speed
    open_issues = [i for i in _issues(client, auth_headers) if i["entity_id"] == str(vessel.id)]
    assert {i["rule_code"] for i in open_issues} == {
        "vessel_missing_imo",
        "vessel_missing_flag",
        "vessel_missing_speed",
    }

    second = _scan(client, auth_headers)
    assert second["new"] == 0
    assert second["open_total"] == first["open_total"]


def test_scan_auto_resolves_fixed_issues(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    vessel = Vessel(tenant_id=tid, name=f"DQ Fix {_uniq()}", status="active")
    db_session.add(vessel)
    db_session.commit()
    _scan(client, auth_headers)

    vessel.imo = f"7{uuid4().int % 10**6:06d}"
    vessel.flag = "MT"
    vessel.speed_knots = Decimal("14.5")
    db_session.commit()

    result = _scan(client, auth_headers)
    assert result["resolved"] >= 3
    open_for_vessel = [i for i in _issues(client, auth_headers, "open") if i["entity_id"] == str(vessel.id)]
    assert open_for_vessel == []
    resolved_for_vessel = [i for i in _issues(client, auth_headers, "resolved") if i["entity_id"] == str(vessel.id)]
    assert len(resolved_for_vessel) == 3


def test_invoice_missing_due_date_rule(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    inv = Invoice(
        tenant_id=tid,
        invoice_no=f"INV-DQ-{_uniq()}",
        status="issued",
        amount=Decimal("100"),
        due_date=None,
    )
    db_session.add(inv)
    db_session.commit()
    _scan(client, auth_headers)
    hits = [
        i
        for i in _issues(client, auth_headers)
        if i["rule_code"] == "invoice_missing_due_date" and i["entity_id"] == str(inv.id)
    ]
    assert len(hits) == 1

    inv.due_date = date.today() + timedelta(days=30)
    db_session.commit()
    _scan(client, auth_headers)
    hits = [
        i
        for i in _issues(client, auth_headers, "resolved")
        if i["rule_code"] == "invoice_missing_due_date" and i["entity_id"] == str(inv.id)
    ]
    assert len(hits) == 1


def test_voyage_no_vessel_rule(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage = Voyage(tenant_id=tid, voyage_no=f"DQ-{_uniq()}", status="in_progress", vessel_id=None)
    db_session.add(voyage)
    db_session.commit()
    _scan(client, auth_headers)
    hits = [i for i in _issues(client, auth_headers) if i["rule_code"] == "voyage_no_vessel"]
    assert any(i["entity_id"] == str(voyage.id) for i in hits)


def test_scan_tenant_isolation(client, auth_headers, db_session):
    _, hb = create_tenant(client, code="dqiso", name="DQ Iso", admin_email="admin@dqiso.example.com")
    # demo tenant has a broken vessel; tenant B scan must not see or resolve it
    tid_a = _tenant_id(db_session)
    vessel_a = Vessel(tenant_id=tid_a, name=f"DQ IsoA {_uniq()}", status="active")
    db_session.add(vessel_a)
    db_session.commit()
    _scan(client, auth_headers)

    result_b = _scan(client, hb)
    assert result_b["resolved"] == 0
    issues_b = _issues(client, hb)
    # tenant B may report global-port findings, but never tenant A's entities
    assert not any(i["entity_id"] == str(vessel_a.id) for i in issues_b)
    assert not any(i["entity_type"] == "vessel" for i in issues_b)


def test_scan_requires_admin_role(client, auth_headers):
    uniq = _uniq()
    r = client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": f"dq-viewer-{uniq}@example.com",
            "full_name": "DQ Viewer",
            "password": "Demo1234!",
            "role_codes": ["viewer"],
        },
    )
    assert r.status_code == 200, r.text
    login = client.post(
        "/api/v1/auth/login",
        json={"email": f"dq-viewer-{uniq}@example.com", "password": "Demo1234!", "tenant_code": "demo"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.post("/api/v1/dq/scan", headers=h).status_code == 403


def test_dq_issues_feed_exception_scan(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    db_session.add(Vessel(tenant_id=tid, name=f"DQ Feed {_uniq()}", status="active"))
    db_session.commit()
    _scan(client, auth_headers)
    r = client.get("/api/v1/exceptions/scan", headers=auth_headers)
    assert r.status_code == 200, r.text
    dq_items = [i for i in r.json()["items"] if i["kind"] == "dq_issue"]
    assert dq_items, "expected aggregated dq_issue item"
    assert dq_items[0]["severity"] == "warning"
    assert dq_items[0]["href"] == "/analytics"
