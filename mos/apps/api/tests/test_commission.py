"""D4 佣金链：佣金计划 + 经纪佣金发票草稿。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import Charter


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _invoice_on_chartered_voyage(client, h, db_session, amount=100000, brokerage=1.25, address=2.5):
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    parties = parties["items"] if isinstance(parties, dict) else parties
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "voyage", "counterparty_id": parties[0]["id"]},
    ).json()
    charter = db_session.get(Charter, uuid.UUID(cp["id"]))
    charter.brokerage_pct = brokerage
    charter.address_comm_pct = address
    db_session.commit()

    voy = client.post("/api/v1/voyages", headers=h, json={"voyage_no": f"CM-{uuid.uuid4().hex[:6]}", "charter_id": cp["id"]}).json()
    inv = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"invoice_type": "freight", "amount": amount, "voyage_id": voy["id"], "counterparty_id": parties[0]["id"]},
    ).json()
    return inv


def test_commission_plan(client, auth_headers, db_session):
    h = auth_headers
    inv = _invoice_on_chartered_voyage(client, h, db_session, amount=100000)
    body = client.get(f"/api/v1/invoices/{inv['id']}/commission-plan", headers=h).json()
    assert body["brokerage_pct"] == 1.25
    assert body["brokerage_amount"] == 1250.0
    assert body["address_comm_pct"] == 2.5
    assert body["address_commission_amount"] == 2500.0


def test_create_brokerage_invoice(client, auth_headers, db_session):
    h = auth_headers
    inv = _invoice_on_chartered_voyage(client, h, db_session, amount=80000)
    created = client.post(f"/api/v1/invoices/{inv['id']}/commission-invoices", headers=h)
    assert created.status_code == 200, created.text
    assert created.json()["amount"] == 1000.0  # 1.25% × 80000
    detail = client.get(f"/api/v1/invoices/{created.json()['id']}", headers=h).json()
    assert detail["invoice_type"] == "broker_commission"
    assert detail["status"] == "draft"


def test_no_commission_rejected(client, auth_headers, db_session):
    h = auth_headers
    inv = _invoice_on_chartered_voyage(client, h, db_session, amount=1000, brokerage=0)
    r = client.post(f"/api/v1/invoices/{inv['id']}/commission-invoices", headers=h)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "NO_COMMISSION"
