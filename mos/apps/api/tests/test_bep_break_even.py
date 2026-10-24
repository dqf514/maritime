"""Break-even point (BEP) semantics.

Regression cover for the "silent zero" defect found by the simulation harness:
``/estimates/{id}/bep`` used to answer ``bep_freight_rate = null`` for an
estimate that had no cost inputs at all, without telling the caller *why* —
the UI could only render a bare "N/A".  The endpoint now reports
``has_cost_base`` so the client can explain the gap.
"""

from __future__ import annotations

import uuid


def _login(client, email: str = "charterer@demo.marios") -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Demo1234!", "tenant_code": "demo"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_estimate(client, headers, title: str, inputs: dict) -> str:
    created = client.post(
        "/api/v1/estimates",
        headers=headers,
        json={"title": title, "mode": "voyage", "inputs": inputs},
    )
    assert created.status_code in (200, 201), created.text
    eid = created.json()["id"]
    calc = client.post(f"/api/v1/estimates/{eid}/calculate", headers=headers)
    assert calc.status_code == 200, calc.text
    return eid


def test_bep_computed_when_cost_inputs_exist(client):
    h = _login(client)
    eid = _make_estimate(
        client,
        h,
        "BEP with cost base",
        {
            "cargo_qty": 50000,
            "freight_rate": 30,
            "sea_days": 10,
            "port_days": 2,
            "bunker_sea_tpd": 25,
            "bunker_price": 400,
            "port_costs": 120000,
        },
    )

    r = client.get(f"/api/v1/estimates/{eid}/bep", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["has_cost_base"] is True
    assert body["base_cost"] > 0
    assert body["bep_freight_rate"] is not None
    assert body["bep_freight_rate"] > 0
    assert body["bep_cargo_qty"] is not None
    assert body["bep_cargo_qty"] > 0
    # 运价 30 > 盈亏平衡运价 → 这票是赚的
    assert body["bep_freight_rate"] < body["current_freight_rate"]
    # BEP 口径自洽：运费率 × 货量 ≈ 成本
    assert abs(body["bep_freight_rate"] * body["current_cargo_qty"] - body["base_cost"]) < 1.0


def test_bep_reports_missing_cost_base_instead_of_silent_zero(client):
    h = _login(client)
    eid = _make_estimate(
        client,
        h,
        "BEP without cost inputs",
        {"cargo_qty": 50000, "freight_rate": 30, "sea_days": 10, "port_days": 2},
    )

    r = client.get(f"/api/v1/estimates/{eid}/bep", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["has_cost_base"] is False
    assert body["base_cost"] == 0
    assert body["bep_freight_rate"] is None
    assert body["bep_cargo_qty"] is None


def test_bep_unknown_estimate_is_404(client):
    h = _login(client)
    r = client.get(f"/api/v1/estimates/{uuid.uuid4()}/bep", headers=h)
    assert r.status_code == 404, r.text


def test_bep_is_tenant_scoped(client):
    """另一个租户不能读取本租户估价的盈亏平衡点。"""
    h = _login(client)
    eid = _make_estimate(
        client,
        h,
        "BEP tenant scope",
        {"cargo_qty": 50000, "freight_rate": 30, "sea_days": 10, "port_days": 2},
    )

    other = client.post(
        "/api/v1/auth/login",
        json={"email": "ops@marios.platform", "password": "Demo1234!", "tenant_code": "sys"},
    )
    if other.status_code != 200:
        # 平台账号不可用时跳过（不同部署的演示账号可能不同）
        return
    oh = {"Authorization": f"Bearer {other.json()['access_token']}"}
    r = client.get(f"/api/v1/estimates/{eid}/bep", headers=oh)
    assert r.status_code == 404, r.text
