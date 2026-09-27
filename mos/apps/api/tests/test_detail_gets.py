"""U2 单据详情：单条 GET 端点（可深链视图）契约。"""

from __future__ import annotations

import uuid


def test_get_invoice_detail(client, auth_headers):
    created = client.post(
        "/api/v1/invoices",
        headers=auth_headers,
        json={"amount": 1234, "currency": "USD", "tax_amount": 10},
    ).json()
    body = client.get(f"/api/v1/invoices/{created['id']}", headers=auth_headers)
    assert body.status_code == 200
    data = body.json()
    assert data["id"] == created["id"]
    assert data["amount"] == 1234
    assert data["tax_amount"] == 10
    assert data["status"] == "draft"


def test_get_claim_detail(client, auth_headers):
    created = client.post("/api/v1/claims", headers=auth_headers, json={"amount": 5000}).json()
    body = client.get(f"/api/v1/claims/{created['id']}", headers=auth_headers)
    assert body.status_code == 200
    data = body.json()
    assert data["id"] == created["id"]
    assert data["amount"] == 5000
    assert "days_to_timebar" in data


def test_get_charter_detail(client, auth_headers):
    parties = client.get("/api/v1/masterdata/counterparties", headers=auth_headers).json()
    created = client.post(
        "/api/v1/charters",
        headers=auth_headers,
        json={"charter_type": "voyage", "counterparty_id": parties["items"][0]["id"] if isinstance(parties, dict) else parties[0]["id"]},
    )
    assert created.status_code == 200, created.text
    body = client.get(f"/api/v1/charters/{created.json()['id']}", headers=auth_headers)
    assert body.status_code == 200
    assert body.json()["id"] == created.json()["id"]


def test_detail_gets_404_on_unknown_id(client, auth_headers):
    missing = str(uuid.uuid4())
    for path in ("/api/v1/invoices", "/api/v1/claims", "/api/v1/charters"):
        assert client.get(f"{path}/{missing}", headers=auth_headers).status_code == 404
