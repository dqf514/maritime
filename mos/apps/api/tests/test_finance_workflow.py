"""红冲工作流不变量（Phase 1）：INV-VOID-CREDIT。

- 未收款 → 可直接作废
- 已收款未红冲 → 409 CREDIT_NOTE_REQUIRED
- 已收款部分红冲 → 409
- 已收款全额红冲 → 可作废
"""

from __future__ import annotations


def _issue_and_pay(client, h, amount=1000, pay=1000):
    inv = client.post("/api/v1/invoices", headers=h, json={"amount": amount, "currency": "USD"}).json()
    iid = inv["id"]
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=issued", headers=h).status_code == 200
    if pay:
        r = client.post(f"/api/v1/invoices/{iid}/payments?amount={pay}", headers=h)
        assert r.status_code == 200, r.text
    return iid


def test_void_unpaid_invoice_ok(client, auth_headers):
    h = auth_headers
    inv = client.post("/api/v1/invoices", headers=h, json={"amount": 500}).json()
    assert client.post(f"/api/v1/invoices/{inv['id']}/transition?target=void", headers=h).status_code == 200


def test_void_paid_requires_full_credit(client, auth_headers):
    h = auth_headers
    iid = _issue_and_pay(client, h, amount=1000, pay=400)  # → partially_paid

    blocked = client.post(f"/api/v1/invoices/{iid}/transition?target=void", headers=h)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "CREDIT_NOTE_REQUIRED"

    # 部分红冲仍不可作废
    assert client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 200}).status_code == 200
    blocked2 = client.post(f"/api/v1/invoices/{iid}/transition?target=void", headers=h)
    assert blocked2.status_code == 409
    assert blocked2.json()["detail"]["credited_amount"] == 200.0

    # 全额红冲后可作废（INV-VOID-CREDIT 满足）
    assert client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 200}).status_code == 200
    ok = client.post(f"/api/v1/invoices/{iid}/transition?target=void", headers=h)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "void"


def test_void_fully_paid_blocked_by_state_machine(client, auth_headers):
    """paid → void 被状态机禁止：全额结清的发票须先冲正付款回到 partially_paid。"""
    h = auth_headers
    iid = _issue_and_pay(client, h, amount=1000, pay=1000)  # → paid
    assert client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 1000}).status_code == 200
    r = client.post(f"/api/v1/invoices/{iid}/transition?target=void", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INVALID_STATE"


def test_credit_note_cannot_exceed_balance(client, auth_headers):
    h = auth_headers
    iid = _issue_and_pay(client, h, amount=1000, pay=500)
    # 红冲上限 = 发票总额（含未收部分）；耗尽 1000 后再红冲 → 409
    assert client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 600}).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 400}).status_code == 200
    over = client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 1})
    assert over.status_code == 409
    assert over.json()["detail"]["code"] == "CREDIT_EXCEEDS_BALANCE"


def test_void_invoice_service_unit(db_engine):
    """服务层不变量直接锁定（不经 HTTP）。"""
    import uuid

    from fastapi import HTTPException
    from sqlalchemy.orm import sessionmaker

    from app.models import Tenant
    from app.models_domain import Invoice
    from app.models_finance_ext import CreditNote
    from app.services.finance_workflow import void_invoice

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as s:
        tid = s.query(Tenant.id).limit(1).scalar()
        inv = Invoice(tenant_id=tid, invoice_no=f"WF-{uuid.uuid4().hex[:6]}", amount=1000, paid_amount=800, status="issued")
        s.add(inv)
        s.commit()
        try:
            void_invoice(s, inv)
            raise AssertionError("expected 409")
        except HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail["code"] == "CREDIT_NOTE_REQUIRED"
        s.add(CreditNote(tenant_id=tid, invoice_id=inv.id, credit_note_no=f"CN-{uuid.uuid4().hex[:6]}", amount=800, status="issued"))
        s.commit()
        void_invoice(s, inv)
        assert inv.status == "void"
