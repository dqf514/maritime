"""Business-integrity regressions.

Covers: payment validation (negative / overpayment), locked invoice mutation,
cross-tenant reference (IDOR) rejection, workflow decision validation and
self-approval blocking, fail-closed feature matrix, and list pagination limits.
"""

import re
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker


def _login(client, email, tenant_code="demo", password="Demo1234!"):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "tenant_code": tenant_code},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_invoice(client, h, amount=1000, tax=0):
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    inv = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"counterparty_id": parties[0]["id"], "amount": amount, "tax_amount": tax, "currency": "USD"},
    )
    assert inv.status_code == 200, inv.text
    return inv.json()


def _issue_invoice(client, h, iid):
    # admin is tenant_admin: direct issue path bypasses the workflow gate
    r1 = client.post(f"/api/v1/invoices/{iid}/transition?target=pending_approval", headers=h)
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"/api/v1/invoices/{iid}/transition?target=issued", headers=h)
    assert r2.status_code == 200, r2.text


# —— Payments ——


def test_negative_and_zero_payment_rejected(client, auth_headers):
    h = auth_headers
    iid = _create_invoice(client, h, amount=1000)["id"]
    _issue_invoice(client, h, iid)
    neg = client.post(f"/api/v1/invoices/{iid}/payments?amount=-5", headers=h)
    assert neg.status_code == 422
    assert neg.json()["detail"]["code"] == "INVALID_AMOUNT"
    zero = client.post(f"/api/v1/invoices/{iid}/payments?amount=0", headers=h)
    assert zero.status_code == 422


def test_overpayment_rejected_and_status_recalc(client, auth_headers):
    h = auth_headers
    iid = _create_invoice(client, h, amount=1000)["id"]
    _issue_invoice(client, h, iid)
    over = client.post(f"/api/v1/invoices/{iid}/payments?amount=1000.01", headers=h)
    assert over.status_code == 409
    assert over.json()["detail"]["code"] == "OVERPAYMENT"
    p1 = client.post(f"/api/v1/invoices/{iid}/payments?amount=600", headers=h)
    assert p1.status_code == 200
    assert p1.json()["status"] == "partially_paid"
    over2 = client.post(f"/api/v1/invoices/{iid}/payments?amount=400.01", headers=h)
    assert over2.status_code == 409
    p2 = client.post(f"/api/v1/invoices/{iid}/payments?amount=400", headers=h)
    assert p2.status_code == 200
    assert p2.json()["status"] == "paid"


def test_issued_and_paid_invoice_amount_locked(client, auth_headers):
    h = auth_headers
    # issued (unpaid) invoice: financial fields locked
    iid = _create_invoice(client, h, amount=500)["id"]
    _issue_invoice(client, h, iid)
    r = client.patch(f"/api/v1/invoices/{iid}", headers=h, json={"amount": 450})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INVOICE_LOCKED"
    # paid invoice: still locked
    pay = client.post(f"/api/v1/invoices/{iid}/payments?amount=500", headers=h)
    assert pay.json()["status"] == "paid"
    r2 = client.patch(f"/api/v1/invoices/{iid}", headers=h, json={"amount": 400, "due_date": "2030-01-01"})
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "INVOICE_LOCKED"


def test_draft_invoice_amount_editable_but_not_below_paid(client, auth_headers):
    h = auth_headers
    iid = _create_invoice(client, h, amount=500)["id"]
    ok = client.patch(f"/api/v1/invoices/{iid}", headers=h, json={"amount": 600})
    assert ok.status_code == 200
    assert ok.json()["amount"] == 600
    neg = client.patch(f"/api/v1/invoices/{iid}", headers=h, json={"amount": -1})
    assert neg.status_code == 422


def test_invoice_numbers_sequential_per_tenant(client, auth_headers):
    h = auth_headers
    n1 = _create_invoice(client, h, amount=10)["invoice_no"]
    n2 = _create_invoice(client, h, amount=20)["invoice_no"]
    pat = r"^INV-\d{4}-\d{5}$"
    assert re.match(pat, n1) and re.match(pat, n2)
    assert n1 != n2
    assert int(n2.rsplit("-", 1)[1]) == int(n1.rsplit("-", 1)[1]) + 1


# —— Cross-tenant IDOR ——


def _create_second_tenant_counterparty(client):
    hp = _login(client, "ops@marios.platform", tenant_code="sys", password="Ops1234!")
    created = client.post(
        "/api/v1/platform/tenants",
        headers=hp,
        json={
            "name": "Globex Marine",
            "code": "globex",
            "profile_tier": "M",
            "admin_email": "Admin@Globex.example.com",
            "admin_password": "Demo1234!",
        },
    )
    assert created.status_code == 200, created.text
    # email normalization: stored login is lowercased
    hg = _login(client, "admin@globex.example.com", tenant_code="globex")
    cp = client.post(
        "/api/v1/masterdata/counterparties",
        headers=hg,
        json={"name": "Globex CP", "type": "charterer"},
    )
    assert cp.status_code == 200, cp.text
    return cp.json()["id"]


def test_cross_tenant_counterparty_reference_rejected(client, auth_headers):
    h = auth_headers
    foreign_cp = _create_second_tenant_counterparty(client)
    charter = client.post("/api/v1/charters", headers=h, json={"charter_type": "voyage", "counterparty_id": foreign_cp})
    assert charter.status_code == 404
    invoice = client.post("/api/v1/invoices", headers=h, json={"counterparty_id": foreign_cp, "amount": 100})
    assert invoice.status_code == 404
    msg = client.post(f"/api/v1/portal/messages?counterparty_id={foreign_cp}&subject=hi", headers=h)
    assert msg.status_code == 404
    # random UUIDs must not silently pass either
    ghost = client.post("/api/v1/charters", headers=h, json={"charter_type": "voyage", "counterparty_id": str(uuid4())})
    assert ghost.status_code == 404


# —— Workflow approvals ——


def _submit_invoice_workflow(client, h_fin, h_admin):
    """Finance submits an invoice for approval; returns (invoice_id, workflow_instance_id)."""
    grant = client.put(
        "/api/v1/admin/features",
        headers=h_admin,
        json={"role_code": "finance", "feature_code": "invoice.issue", "allowed": True},
    )
    assert grant.status_code == 200
    inv = _create_invoice(client, h_fin, amount=250)
    sub = client.post(f"/api/v1/invoices/{inv['id']}/transition?target=pending_approval", headers=h_fin)
    assert sub.status_code == 200, sub.text
    inbox = client.get("/api/v1/workflows/inbox", headers=h_admin).json()
    hit = next(i for i in inbox if i["entity_id"] == inv["id"])
    return inv["id"], hit["id"]


def test_workflow_invalid_decision_422(client, auth_headers, db_engine):
    h_admin = auth_headers
    h_fin = _login(client, "finance@demo.marios")
    _, instance_id = _submit_invoice_workflow(client, h_fin, h_admin)

    from app.models_saas import WorkflowInstance
    from app.services.saas_engine import advance_workflow

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        inst = db.get(WorkflowInstance, __import__("uuid").UUID(instance_id))
        assert inst is not None
        with pytest.raises(HTTPException) as exc:
            advance_workflow(
                db,
                instance_id=inst.id,
                tenant_id=inst.tenant_id,
                actor_roles=["tenant_admin"],
                actor_user_id=uuid4(),
                decision="maybe",
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "INVALID_DECISION"


def test_workflow_self_approval_blocked(client, auth_headers):
    h_admin = auth_headers
    h_fin = _login(client, "finance@demo.marios")
    _, instance_id = _submit_invoice_workflow(client, h_fin, h_admin)
    # finance may hold the workflow.approve feature, but still cannot approve own submission
    client.put(
        "/api/v1/admin/features",
        headers=h_admin,
        json={"role_code": "finance", "feature_code": "workflow.approve", "allowed": True},
    )
    r = client.post(f"/api/v1/workflows/{instance_id}/decide", headers=h_fin, json={"decision": "approve"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "SELF_APPROVAL_BLOCKED"
    # a different approver still works
    ok = client.post(f"/api/v1/workflows/{instance_id}/decide", headers=h_admin, json={"decision": "approve"})
    assert ok.status_code == 200


# —— Feature matrix fail-closed ——


def test_feature_matrix_fail_closed(client, auth_headers, db_engine):
    h_admin = auth_headers
    h_fin = _login(client, "finance@demo.marios")
    # no matrix row for finance/invoice.collect → denied (fail-closed)
    iid = _create_invoice(client, h_admin, amount=100)["id"]
    _issue_invoice(client, h_admin, iid)
    blocked = client.post(f"/api/v1/invoices/{iid}/payments?amount=10", headers=h_fin)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "FEATURE_DENIED"
    # explicit allow row → permitted
    grant = client.put(
        "/api/v1/admin/features",
        headers=h_admin,
        json={"role_code": "finance", "feature_code": "invoice.collect", "allowed": True},
    )
    assert grant.status_code == 200
    allowed = client.post(f"/api/v1/invoices/{iid}/payments?amount=10", headers=h_fin)
    assert allowed.status_code == 200, allowed.text

    # engine-level: empty roles and unknown features deny; admins always allowed
    from app.models import Tenant
    from app.services.saas_engine import feature_allowed

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        tid = db.scalar(select(Tenant.id).where(Tenant.code == "demo"))
        assert feature_allowed(db, tid, ["viewer"], "ai.invoke") is False
        assert feature_allowed(db, tid, [], "ai.invoke") is False
        assert feature_allowed(db, tid, ["tenant_admin"], "ai.invoke") is True


# —— Pagination ——


def test_list_pagination_limits(client, auth_headers):
    h = auth_headers
    for _ in range(3):
        _create_invoice(client, h, amount=10)
    page1 = client.get("/api/v1/invoices?limit=2", headers=h).json()
    assert len(page1) == 2
    page2 = client.get("/api/v1/invoices?limit=2&offset=2", headers=h).json()
    assert len(page2) >= 1
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})

    cps = client.get("/api/v1/masterdata/counterparties?limit=1", headers=h).json()
    assert len(cps) == 1
    charters = client.get("/api/v1/charters?limit=1", headers=h).json()
    assert len(charters) == 1
    users = client.get("/api/v1/admin/users?limit=1", headers=h).json()
    assert len(users) == 1
    # limit above the server cap is rejected
    too_much = client.get("/api/v1/invoices?limit=501", headers=h)
    assert too_much.status_code == 422
