"""D21 银行核销：配对建议 + 确认入账。"""

from __future__ import annotations


def _issued(client, h, amount=1000):
    inv = client.post("/api/v1/invoices", headers=h, json={"amount": amount, "currency": "USD"}).json()
    client.post(f"/api/v1/invoices/{inv['id']}/transition?target=pending_approval", headers=h)
    client.post(f"/api/v1/invoices/{inv['id']}/transition?target=issued", headers=h)
    return inv


def test_preview_scores_and_unmatched(client, auth_headers):
    h = auth_headers
    inv = _issued(client, h, amount=1000)
    inv2 = _issued(client, h, amount=2000)

    body = client.post(
        "/api/v1/reconciliation/preview" if False else "/api/v1/finance/reconciliation/preview",
        headers=h,
        json={
            "lines": [
                {"amount": 1000, "reference": f"TT {inv['invoice_no']}"},
                {"amount": 2000, "reference": "unrelated"},
                {"amount": 999, "reference": "no match"},
            ]
        },
    )
    assert body.status_code == 200, body.text
    res = body.json()
    by_idx = {s["line_index"]: s for s in res["suggestions"]}
    assert by_idx[0]["invoice_id"] == inv["id"]
    assert by_idx[0]["score"] == 1.0  # 含发票号
    assert by_idx[0]["reason"] == "amount+invoice_no"
    assert by_idx[1]["invoice_id"] == inv2["id"]
    assert by_idx[1]["score"] == 0.6  # 仅金额
    assert res["unmatched"] == [2]


def test_apply_records_payments_transactionally(client, auth_headers):
    h = auth_headers
    inv = _issued(client, h, amount=1500)

    ok = client.post(
        "/api/v1/finance/reconciliation/apply",
        headers=h,
        json={"matches": [{"invoice_id": inv["id"], "amount": 1500, "reference": "BANK-1"}]},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["applied"][0]["status"] == "paid"

    detail = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert detail["paid_amount"] == 1500.0

    # 无效发票 → 整体失败，不落任何一笔
    inv2 = _issued(client, h, amount=100)
    inv3 = _issued(client, h, amount=100)
    bad = client.post(
        "/api/v1/finance/reconciliation/apply",
        headers=h,
        json={
            "matches": [
                {"invoice_id": inv2["id"], "amount": 100},
                {"invoice_id": "00000000-0000-0000-0000-000000000099", "amount": 5},
            ]
        },
    )
    assert bad.status_code == 404
    d2 = client.get(f"/api/v1/invoices/{inv2['id']}", headers=h).json()
    assert d2["paid_amount"] == 0.0  # 未落账（事务回滚）
    assert inv3["id"]  # 占位避免未使用告警


def test_partial_reconcile_moves_to_partially_paid(client, auth_headers):
    h = auth_headers
    inv = _issued(client, h, amount=1000)
    r = client.post(
        "/api/v1/finance/reconciliation/apply",
        headers=h,
        json={"matches": [{"invoice_id": inv["id"], "amount": 400, "reference": "PART"}]},
    )
    assert r.status_code == 200
    assert r.json()["applied"][0]["status"] == "partially_paid"
