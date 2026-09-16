"""Productivity platform — estimate update, WS freight, dynamic P&L."""

from __future__ import annotations


def test_estimate_desk_put_calculate_ws(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "charterer@demo.marios", "password": "Demo1234!", "tenant_code": "demo"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}

    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    assert vessels and parties

    created = client.post(
        "/api/v1/estimates",
        headers=h,
        json={
            "title": "WS productivity case",
            "vessel_id": vessels[0]["id"],
            "counterparty_id": parties[0]["id"],
            "inputs": {
                "cargo_qty": 50000,
                "ws_flat": 10,
                "ws_pct": 80,
                "commission_pct": 2.5,
                "sea_days": 20,
                "port_days": 5,
                "bunker_sea_tpd": 25,
                "bunker_price": 400,
                "port_costs": 50000,
            },
        },
    )
    assert created.status_code == 200, created.text
    eid = created.json()["id"]

    upd = client.put(
        f"/api/v1/estimates/{eid}",
        headers=h,
        json={"title": "WS productivity case v2", "inputs": {**created.json()["inputs"], "ws_pct": 85}},
    )
    assert upd.status_code == 200
    assert upd.json()["title"] == "WS productivity case v2"
    assert upd.json()["status"] in ("draft", "calculated")

    calc = client.post(f"/api/v1/estimates/{eid}/calculate", headers=h)
    assert calc.status_code == 200, calc.text
    body = calc.json()
    assert body["results"]["freight_basis"] == "worldscale"
    assert body["results"]["tce"] > 0
    assert body["results"]["gross_freight"] == 425000.0  # 50000*10*0.85

    sens = client.post(f"/api/v1/estimates/{eid}/sensitivity?field=ws_pct", headers=h)
    assert sens.status_code == 200
    assert len(sens.json()) == 5


def test_dynamic_voyage_pnl_shape(client):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "finance@demo.marios", "password": "Demo1234!", "tenant_code": "demo"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    pnl = client.get("/api/v1/analytics/reports/voyage-pnl", headers=h)
    assert pnl.status_code == 200, pnl.text
    rows = pnl.json()
    assert isinstance(rows, list)
    if rows:
        row = rows[0]
        for key in ("voyage_no", "estimated_revenue", "actual_revenue", "actual_pnl", "variance_pnl"):
            assert key in row
