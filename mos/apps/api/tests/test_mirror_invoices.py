"""Mirror invoice end-to-end: create / duplicate / chain / pull-sync / intercompany / isolation."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import create_tenant

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _demo_tenant_id(db_session) -> UUID:
    from app.models import Tenant

    return UUID(str(db_session.execute(select(Tenant.id).where(Tenant.code == "demo")).scalar()))


def _create_invoice(client, h, amount=1000.0, tax=0.0):
    r = client.post(
        f"{API}/invoices",
        headers=h,
        json={"invoice_type": "freight", "amount": amount, "tax_amount": tax, "currency": "USD"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_create_mirror_same_tenant(client, auth_headers):
    h = auth_headers
    inv = _create_invoice(client, h, amount=1500.0)
    r = client.post(f"{API}/invoices/{inv['id']}/mirror", headers=h, json={})
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["mirror_of_id"] == inv["id"]
    assert m["is_mirror"] is True
    assert m["status"] == "draft"
    assert m["invoice_no"] != inv["invoice_no"]
    assert m["amount"] == 1500.0
    assert m["currency"] == "USD"
    # source stays editable and is not a mirror
    src = client.get(f"{API}/invoices/{inv['id']}", headers=h).json()
    assert src["mirror_of_id"] is None


def test_duplicate_mirror_conflicts(client, auth_headers):
    h = auth_headers
    inv = _create_invoice(client, h)
    r1 = client.post(f"{API}/invoices/{inv['id']}/mirror", headers=h, json={})
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"{API}/invoices/{inv['id']}/mirror", headers=h, json={})
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "MIRROR_EXISTS"


def test_mirror_chain_returns_source_then_mirror(client, auth_headers):
    h = auth_headers
    inv = _create_invoice(client, h, amount=800.0)
    created = client.post(f"{API}/invoices/{inv['id']}/mirror", headers=h, json={}).json()
    r = client.get(f"{API}/invoices/{inv['id']}/mirror-chain", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0]["id"] == inv["id"]
    assert items[0]["is_mirror"] is False
    assert items[1]["id"] == created["id"]
    assert items[1]["is_mirror"] is True
    assert items[1]["mirror_of_id"] == inv["id"]


def test_pull_sync_updates_draft_mirror(client, auth_headers, db_session):
    from app.models_domain import Invoice

    h = auth_headers
    inv = _create_invoice(client, h, amount=1000.0)
    created = client.post(f"{API}/invoices/{inv['id']}/mirror", headers=h, json={}).json()
    mirror_id = UUID(created["id"])

    # Bump the source directly via db (simulate source commercial change).
    src = db_session.get(Invoice, UUID(inv["id"]))
    src.amount = Decimal("2222.00")
    src.currency = "EUR"
    src.due_date = None
    db_session.commit()

    r = client.get(f"{API}/invoices/{inv['id']}/mirror-chain", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert Decimal(items[1]["amount"]) == Decimal("2222.00")
    assert items[1]["currency"] == "EUR"

    db_session.expire_all()
    mirror = db_session.get(Invoice, mirror_id)
    assert mirror.amount == Decimal("2222.00")
    assert mirror.currency == "EUR"
    assert mirror.mirror_synced_source_at is not None


def test_cross_tenant_requires_intercompany_flag(client, auth_headers, db_session, monkeypatch):
    h = auth_headers
    inv = _create_invoice(client, h, amount=500.0)
    other_tenant_id, _other_h = create_tenant(
        client, code="mirrorco", name="Mirror Co", admin_email="admin@mirrorco.example.com"
    )

    # Flag off (default) → rejected
    r = client.post(
        f"{API}/invoices/{inv['id']}/mirror",
        headers=h,
        json={"target_tenant_id": other_tenant_id},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "INTERCOMPANY_DISABLED"

    # Flag on (monkeypatch the helper) → allowed
    monkeypatch.setattr(
        "app.services.invoice_mirror.intercompany_enabled",
        lambda db, tenant_id, user_id=None: True,
    )
    r = client.post(
        f"{API}/invoices/{inv['id']}/mirror",
        headers=h,
        json={"target_tenant_id": other_tenant_id},
    )
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["tenant_id"] == other_tenant_id
    assert m["mirror_of_id"] == inv["id"]
    assert m["status"] == "draft"


def test_chain_tenant_isolation(client, auth_headers):
    h = auth_headers
    inv = _create_invoice(client, h, amount=300.0)
    created = client.post(f"{API}/invoices/{inv['id']}/mirror", headers=h, json={}).json()

    _other_tenant_id, other_h = create_tenant(
        client, code="outsider", name="Outsider", admin_email="admin@outsider.example.com"
    )

    # Foreign tenant cannot read the chain by source id or mirror id
    r = client.get(f"{API}/invoices/{inv['id']}/mirror-chain", headers=other_h)
    assert r.status_code == 404, r.text
    r = client.get(f"{API}/invoices/{created['id']}/mirror-chain", headers=other_h)
    assert r.status_code == 404, r.text

    # Owner still sees the full chain
    r = client.get(f"{API}/invoices/{inv['id']}/mirror-chain", headers=h)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2
