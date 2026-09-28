"""数据闭环（对手方/联系人）：跨公司联系人检索、索赔联系人、供油方落库、
入站邮件匹配、全局搜索实体命中。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _mk_party_with_contact(client, h, company="Acme Tankers", name="Jane Doe", email="jane@acme.com"):
    party = client.post("/api/v1/masterdata/counterparties", headers=h, json={"name": company, "type": "charterer"}).json()
    contact = client.post(
        f"/api/v1/masterdata/counterparties/{party['id']}/contacts",
        headers=h,
        json={"name": name, "email": email, "title": "Ops"},
    ).json()
    return party, contact


def test_contacts_cross_search(client, auth_headers):
    h = auth_headers
    party, contact = _mk_party_with_contact(client, h)
    body = client.get("/api/v1/masterdata/counterparty-contacts?q=Jane", headers=h).json()
    hit = next(i for i in body["items"] if i["id"] == contact["id"])
    assert hit["counterparty_name"] == "Acme Tankers"
    # 按公司名也能搜到联系人
    body2 = client.get("/api/v1/masterdata/counterparty-contacts?q=Acme", headers=h).json()
    assert any(i["id"] == contact["id"] for i in body2["items"])
    # 按 email 搜索
    body3 = client.get("/api/v1/masterdata/counterparty-contacts?q=jane@acme.com", headers=h).json()
    assert any(i["id"] == contact["id"] for i in body3["items"])


def test_claim_links_contact(client, auth_headers):
    h = auth_headers
    party, contact = _mk_party_with_contact(client, h, company="Beta", name="Bob", email="bob@beta.com")
    claim = client.post(
        "/api/v1/claims",
        headers=h,
        json={"amount": 5000, "contact_id": contact["id"]},
    ).json()
    detail = client.get(f"/api/v1/claims/{claim['id']}", headers=h).json()
    assert detail["contact"]["name"] == "Bob"
    assert detail["contact"]["email"] == "bob@beta.com"
    rows = client.get("/api/v1/claims", headers=h).json()["items"]
    row = next(r for r in rows if r["id"] == claim["id"])
    assert row["contact_id"] == contact["id"]
    # 换联系人
    _, c2 = _mk_party_with_contact(client, h, company="Gamma", name="Carol", email="carol@gamma.com")
    client.patch(f"/api/v1/claims/{claim['id']}", headers=h, json={"contact_id": c2["id"]})
    assert client.get(f"/api/v1/claims/{claim['id']}", headers=h).json()["contact"]["name"] == "Carol"


def test_bunker_counterparty_persists(client, auth_headers):
    """闭环修复：BunkerIn.counterparty_id 此前只校验不落库。"""
    h = auth_headers
    party, _ = _mk_party_with_contact(client, h, company="Delta Bunkers")
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    order = client.post(
        "/api/v1/bunker-orders",
        headers=h,
        json={
            "vessel_id": vessels[0]["id"],
            "qty_ordered": 500,
            "unit_price": 450,
            "rob_before": 800,
            "supplier": "Delta Bunkers",
            "counterparty_id": party["id"],
        },
    ).json()
    rows = client.get("/api/v1/bunker-orders", headers=h).json()
    row = next(r for r in rows if r["id"] == order["id"])
    assert row["counterparty_id"] == party["id"]
    assert row["supplier"] == "Delta Bunkers"


def test_inbound_email_matches_sender_contact(client, auth_headers, db_session):
    h = auth_headers
    party, contact = _mk_party_with_contact(client, h, company="Echo Shipping", name="Eve", email="eve@echo.com")
    from datetime import datetime, timezone

    from app.models_wave1 import EmailMessage

    msg = EmailMessage(
        tenant_id=uuid.UUID(party["tenant_id"] if "tenant_id" in party else "00000000-0000-0000-0000-000000000000"),
        direction="inbound",
        message_id=f"m-{uuid.uuid4().hex[:8]}",
        from_email="Eve <eve@echo.com>",
        subject="Fixture Recap",
        body_text="Vessel: MV Test",
        sent_at=datetime.now(timezone.utc),
        parse_status="pending",
    )
    # 取 demo 租户（确定性）
    from sqlalchemy import select

    from app.models import Tenant

    tid = db_session.scalar(select(Tenant.id).where(Tenant.code == "demo"))
    msg.tenant_id = tid
    db_session.add(msg)
    db_session.commit()

    from app.services import email_intelligence as ei

    result = ei.process_inbound_email(db_session, tid, uuid.UUID(str(msg.id)))
    assert result["parse_result"]["matched"]["counterparty_name"] == "Echo Shipping"
    assert result["parse_result"]["matched"]["contact_name"] == "Eve"
    assert result["parse_result"]["matched"]["basis"] == "sender_email"


def test_omni_search_entity_hits(client, auth_headers):
    h = auth_headers
    _mk_party_with_contact(client, h, company="Foxtrot Corp", name="Frank", email="frank@foxtrot.com")
    hits = client.get("/api/v1/search?q=Foxtrot", headers=h).json()
    assert any("Foxtrot Corp" in (x.get("title") or "") for x in hits)
    hits2 = client.get("/api/v1/search?q=Frank", headers=h).json()
    assert any("Frank" in (x.get("title") or "") for x in hits2)
