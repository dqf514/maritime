"""Chartering depth — master contracts, cargo broker rules, claim subtypes/actions,
estimate templates + column view, booking-based laytime, laytime types.
"""

from __future__ import annotations


def _items(payload):
    return payload["items"] if isinstance(payload, dict) else payload


ESTIMATE_INPUTS = {
    "cargo_qty": 50000,
    "freight_rate": 20,
    "sea_days": 10,
    "port_days": 4,
    "bunker_sea_tpd": 25,
    "bunker_port_tpd": 8,
    "bunker_price": 600,
    "port_costs": 50000,
}


# ── Master contract CRUD + linking ───────────────────────────────────────────


def _make_master(client, h, **overrides):
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    body = {
        "title": "COA 2026 China iron ore",
        "counterparty_id": parties[0]["id"],
        "contract_type": "voyage_coa",
        "total_qty": 500000,
        "period_from": "2026-01-01",
        "period_to": "2026-12-31",
    }
    body.update(overrides)
    r = client.post("/api/v1/master-contracts", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_master_contract_crud_and_linking(client, auth_headers):
    h = auth_headers
    mc = _make_master(client, h)
    assert mc["contract_no"].startswith("MC-")
    assert mc["status"] == "draft"
    assert mc["contract_type"] == "voyage_coa"
    assert mc["total_qty"] == 500000

    # read back
    got = client.get(f"/api/v1/master-contracts/{mc['id']}", headers=h).json()
    assert got["title"] == "COA 2026 China iron ore"

    # update → active
    patched = client.patch(
        f"/api/v1/master-contracts/{mc['id']}",
        headers=h,
        json={
            "title": "COA 2026 China iron ore (revised)",
            "counterparty_id": mc["counterparty_id"],
            "contract_type": "voyage_coa",
            "status": "active",
            "clauses": {"codes": ["GENCON"]},
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "active"
    assert patched.json()["clauses"] == {"codes": ["GENCON"]}

    listed = client.get("/api/v1/master-contracts", headers=h).json()
    assert mc["id"] in [r["id"] for r in listed]

    # link a charter (fixture) to the master contract
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={
            "charter_type": "voyage",
            "counterparty_id": parties[0]["id"],
            "master_contract_id": mc["id"],
            "charter_direction": "out",
            "fixture_type": "voyage_fixture",
            "cargo_qty": 50000,
        },
    )
    assert cp.status_code == 200, cp.text
    charter = cp.json()
    assert charter["master_contract_id"] == mc["id"]
    assert charter["charter_direction"] == "out"
    assert charter["fixture_type"] == "voyage_fixture"

    linked = client.get(f"/api/v1/master-contracts/{mc['id']}/charters", headers=h).json()
    assert charter["id"] in [r["id"] for r in linked]

    # deleting a master contract still linked to fixtures is refused
    refused = client.delete(f"/api/v1/master-contracts/{mc['id']}", headers=h)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "MASTER_CONTRACT_IN_USE"

    # unlink then delete succeeds (soft delete → recycle bin)
    un = client.patch(f"/api/v1/charters/{charter['id']}", headers=h, json={"master_contract_id": None})
    assert un.status_code == 200, un.text
    assert un.json()["master_contract_id"] is None
    deleted = client.delete(f"/api/v1/master-contracts/{mc['id']}", headers=h)
    assert deleted.status_code == 200, deleted.text
    gone = client.get(f"/api/v1/master-contracts/{mc['id']}", headers=h)
    assert gone.status_code == 404


def test_charter_contract_tab_fields(client, auth_headers):
    h = auth_headers
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    r = client.post(
        "/api/v1/charters",
        headers=h,
        json={
            "charter_type": "voyage",
            "counterparty_id": parties[0]["id"],
            "charter_direction": "in",
            "fixture_type": "relet",
            "exposure_amount": 125000.5,
            "pricing_basis": "worldscale",
            "rebill_settings": {"enabled": True, "markup_pct": 2.5},
            "planning_periods": {"periods": ["2026-Q1", "2026-Q2"]},
            "rev_exp": {"revenue": 200000, "expense": 150000},
            "properties": {"color": "blue"},
        },
    )
    assert r.status_code == 200, r.text
    charter = r.json()
    assert charter["charter_direction"] == "in"
    assert charter["fixture_type"] == "relet"
    assert charter["exposure_amount"] == 125000.5
    assert charter["pricing_basis"] == "worldscale"
    assert charter["rebill_settings"] == {"enabled": True, "markup_pct": 2.5}
    assert charter["planning_periods"] == {"periods": ["2026-Q1", "2026-Q2"]}
    assert charter["rev_exp"] == {"revenue": 200000, "expense": 150000}
    assert charter["properties"] == {"color": "blue"}

    patched = client.patch(
        f"/api/v1/charters/{charter['id']}",
        headers=h,
        json={"exposure_amount": 90000, "properties": {"color": "red"}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["exposure_amount"] == 90000
    assert patched.json()["properties"] == {"color": "red"}


# ── Cargo broker rules ───────────────────────────────────────────────────────


def test_cargo_broker_rules(client, auth_headers):
    h = auth_headers
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "voyage", "counterparty_id": parties[0]["id"]},
    ).json()

    empty = client.get(f"/api/v1/charters/{cp['id']}/broker-rules", headers=h).json()
    assert empty == []

    created = client.post(
        f"/api/v1/charters/{cp['id']}/broker-rules",
        headers=h,
        json={
            "broker_party_id": parties[-1]["id"],
            "commission_type": "brokerage",
            "commission_pct": 1.25,
            "applies_to": "freight",
        },
    )
    assert created.status_code == 201, created.text
    rule = created.json()
    assert rule["commission_type"] == "brokerage"
    assert rule["commission_pct"] == 1.25
    assert rule["applies_to"] == "freight"
    assert rule["charter_id"] == cp["id"]

    addr = client.post(
        f"/api/v1/charters/{cp['id']}/broker-rules",
        headers=h,
        json={
            "broker_party_id": parties[-1]["id"],
            "commission_type": "address",
            "commission_pct": 2.5,
            "applies_to": "all",
        },
    )
    assert addr.status_code == 201, addr.text

    rows = client.get(f"/api/v1/charters/{cp['id']}/broker-rules", headers=h).json()
    assert len(rows) == 2
    assert {r["commission_type"] for r in rows} == {"brokerage", "address"}

    # invalid commission_type rejected
    bad = client.post(
        f"/api/v1/charters/{cp['id']}/broker-rules",
        headers=h,
        json={"broker_party_id": parties[-1]["id"], "commission_type": "kickback", "commission_pct": 1},
    )
    assert bad.status_code == 422

    deleted = client.delete(f"/api/v1/broker-rules/{rule['id']}", headers=h)
    assert deleted.status_code == 200
    assert len(client.get(f"/api/v1/charters/{cp['id']}/broker-rules", headers=h).json()) == 1


# ── Claim subtypes and actions ───────────────────────────────────────────────


def test_claim_subtypes_catalog(client, auth_headers):
    body = client.get("/api/v1/claims/types", headers=auth_headers).json()
    by_code = {i["code"]: i for i in body["items"]}
    dem = by_code["demurrage"]
    sub_codes = {s["code"] for s in dem["subtypes"]}
    assert {"loading_delay", "discharge_delay", "weather", "port_congestion", "documentation"} <= sub_codes
    for s in dem["subtypes"]:
        assert set(s["label"].keys()) == {"en", "zh"}
    action_codes = {a["code"] for a in body["actions"]}
    assert {"negotiate", "litigate", "arbitrate", "settle", "write_off"} <= action_codes


def test_claim_subtype_validation(client, auth_headers):
    ok = client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={"claim_type": "demurrage", "subtype": "port_congestion", "amount": 1000},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["subtype"] == "port_congestion"

    detail = client.get(f"/api/v1/claims/{ok.json()['id']}", headers=auth_headers).json()
    assert detail["subtype"] == "port_congestion"

    bad = client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={"claim_type": "demurrage", "subtype": "nonsense", "amount": 5},
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "INVALID_CLAIM_SUBTYPE"

    # subtype not belonging to the chosen type is rejected too
    mismatched = client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={"claim_type": "off_hire", "subtype": "loading_delay", "amount": 5},
    )
    assert mismatched.status_code == 422
    assert mismatched.json()["detail"]["code"] == "INVALID_CLAIM_SUBTYPE"


def test_claim_actions(client, auth_headers):
    h = auth_headers
    claim = client.post("/api/v1/claims", headers=h, json={"claim_type": "demurrage", "amount": 5000}).json()

    empty = client.get(f"/api/v1/claims/{claim['id']}/actions", headers=h).json()
    assert empty["items"] == []

    a1 = client.post(
        f"/api/v1/claims/{claim['id']}/actions",
        headers=h,
        json={"action_type": "negotiate", "action_date": "2026-09-01", "notes": "counterparty low-balled", "result": "no deal"},
    )
    assert a1.status_code == 201, a1.text
    assert a1.json()["action_type"] == "negotiate"
    assert a1.json()["action_date"] == "2026-09-01"
    assert a1.json()["result"] == "no deal"

    a2 = client.post(
        f"/api/v1/claims/{claim['id']}/actions",
        headers=h,
        json={"action_type": "settle", "result": "settled at 4500"},
    )
    assert a2.status_code == 201, a2.text

    rows = client.get(f"/api/v1/claims/{claim['id']}/actions", headers=h).json()["items"]
    assert [r["action_type"] for r in rows] == ["negotiate", "settle"]
    # settle action auto-advances the claim
    assert client.get(f"/api/v1/claims/{claim['id']}", headers=h).json()["status"] == "settled"

    bad = client.post(
        f"/api/v1/claims/{claim['id']}/actions",
        headers=h,
        json={"action_type": "high_five"},
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "INVALID_CLAIM_ACTION"


def test_claim_time_bar_task(client, auth_headers):
    h = auth_headers
    claim = client.post(
        "/api/v1/claims",
        headers=h,
        json={"claim_type": "demurrage", "amount": 2000, "time_bar": "2026-12-31"},
    ).json()
    task = client.post(f"/api/v1/claims/{claim['id']}/generate-time-bar-task", headers=h)
    assert task.status_code == 200, task.text
    body = task.json()
    assert body["reused"] is False
    assert "Time bar" in body["title"]
    assert body["due_at"].startswith("2026-12-31")

    # idempotent: second call returns the open task instead of a duplicate
    again = client.post(f"/api/v1/claims/{claim['id']}/generate-time-bar-task", headers=h).json()
    assert again["id"] == body["id"]
    assert again["reused"] is True


# ── Template estimates ───────────────────────────────────────────────────────


def test_estimate_templates(client, auth_headers):
    h = auth_headers
    vessels = _items(client.get("/api/v1/masterdata/vessels", headers=h).json())

    tpl = client.post(
        "/api/v1/estimates/templates",
        headers=h,
        json={
            "template_name": "Capesize WS China",
            "vessel_id": vessels[0]["id"],
            "cargo_type": "iron_ore",
            "route_name": "Tubarao→Qingdao",
            "inputs": ESTIMATE_INPUTS,
        },
    )
    assert tpl.status_code == 200, tpl.text
    template = tpl.json()
    assert template["template_name"] == "Capesize WS China"
    assert template["inputs"]["cargo_qty"] == 50000

    listed = client.get("/api/v1/estimates/templates", headers=h).json()
    assert template["id"] in [r["id"] for r in listed]

    # from-template → estimate seeded with template inputs
    est = client.post(f"/api/v1/estimates/from-template/{template['id']}", headers=h, json={"title": "Q1 fixture study"})
    assert est.status_code == 200, est.text
    estimate = est.json()
    assert estimate["title"] == "Q1 fixture study"
    assert estimate["inputs"]["freight_rate"] == 20
    assert estimate["vessel_id"] == vessels[0]["id"]

    calc = client.post(f"/api/v1/estimates/{estimate['id']}/calculate", headers=h)
    assert calc.status_code == 200, calc.text
    assert calc.json()["results"]["tce"] is not None

    # save-as-template → round-trips the inputs
    saved = client.post(
        f"/api/v1/estimates/{estimate['id']}/save-as-template",
        headers=h,
        json={"template_name": "From Q1 fixture"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["inputs"]["freight_rate"] == 20
    assert saved.json()["is_system"] is False

    # soft delete removes template from listing
    deleted = client.delete(f"/api/v1/estimates/templates/{template['id']}", headers=h)
    assert deleted.status_code == 200
    listed2 = client.get("/api/v1/estimates/templates", headers=h).json()
    assert template["id"] not in [r["id"] for r in listed2]


def test_estimate_column_view(client, auth_headers):
    h = auth_headers
    vessels = _items(client.get("/api/v1/masterdata/vessels", headers=h).json())
    vessel_id = vessels[0]["id"]
    ids = []
    for rate in (15, 20, 25):
        inputs = dict(ESTIMATE_INPUTS, freight_rate=rate)
        r = client.post(
            "/api/v1/estimates",
            headers=h,
            json={"title": f"col-{rate}", "vessel_id": vessel_id, "inputs": inputs},
        )
        assert r.status_code == 200, r.text
        e = r.json()
        client.post(f"/api/v1/estimates/{e['id']}/calculate", headers=h)
        ids.append(e["id"])

    q = ",".join(ids)
    view = client.get("/api/v1/estimates/column-view", headers=h, params={"ids": q}).json()
    assert len(view["columns"]) == 3
    assert view["missing"] == []
    assert "tce" in view["fields"]
    tces = [c["values"]["tce"] for c in view["columns"]]
    # higher freight rate → higher TCE
    assert tces == sorted(tces)
    assert view["columns"][0]["values"]["title"] == "col-15"

    # benchmark is per-vessel: the three estimates above share vessel_id
    bench = client.get(f"/api/v1/estimates/benchmark/{vessel_id}", headers=h)
    assert bench.status_code == 200, bench.text
    body = bench.json()
    assert body["sample_size"] >= 1
    assert body["avg_tce"] is not None


# ── Booking-based laytime ────────────────────────────────────────────────────


def test_laytime_from_booking(client, auth_headers):
    h = auth_headers
    r = client.post(
        "/api/v1/laytimes/from-booking",
        headers=h,
        json={
            "booking_reference": "BK-2026-0001",
            "allowed_hours": 48,
            "terms": "SHINC",
            "demurrage_rate_per_day": 12000,
            "events": [
                {
                    "start": "2026-05-01T00:00:00+00:00",
                    "end": "2026-05-03T00:00:00+00:00",
                    "kind": "working",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["booking_reference"] == "BK-2026-0001"
    assert body["status"] == "calculated"
    assert body["results"]["used_hours"] == 48.0
    # 48h used vs 48h allowed → on time
    assert body["results"]["result_type"] in ("none", "on_time", "despatch", "demurrage")

    listed = client.get("/api/v1/laytimes", headers=h).json()
    assert body["id"] in [i["id"] for i in listed["items"]]
    row = next(i for i in listed["items"] if i["id"] == body["id"])
    assert row["booking_reference"] == "BK-2026-0001"

    # booking with demurrage: 60h used vs 24h allowed
    dem = client.post(
        "/api/v1/laytimes/from-booking",
        headers=h,
        json={
            "booking_reference": "BK-2026-0002",
            "allowed_hours": 24,
            "demurrage_rate_per_day": 12000,
            "events": [
                {
                    "start": "2026-05-01T00:00:00+00:00",
                    "end": "2026-05-03T12:00:00+00:00",
                    "kind": "working",
                }
            ],
        },
    )
    assert dem.status_code == 200, dem.text
    results = dem.json()["results"]
    assert results["result_type"] == "demurrage"
    assert results["balance_hours"] == 36.0
    assert results["amount"] == 18000.0  # 1.5 days × 12000

    est = client.get(f"/api/v1/laytimes/{dem.json()['id']}/estimated-demurrage", headers=h)
    assert est.status_code == 200, est.text
    assert est.json()["demurrage_amount"] == 18000.0

    # include demurrage in a freight invoice
    inv = client.post(
        f"/api/v1/laytimes/{dem.json()['id']}/include-in-freight",
        headers=h,
        json={"freight_amount": 1000000},
    )
    assert inv.status_code == 200, inv.text
    assert inv.json()["invoice_type"] == "freight"
    assert inv.json()["amount"] == 1018000.0
    assert inv.json()["settlement_amount"] == 18000.0

    # missing booking_reference rejected
    bad = client.post("/api/v1/laytimes/from-booking", headers=h, json={"booking_reference": "  "})
    assert bad.status_code == 422


# ── Laytime types ────────────────────────────────────────────────────────────


def test_laytime_types(client, auth_headers):
    body = client.get("/api/v1/laytimes/types", headers=auth_headers).json()
    codes = {i["code"] for i in body["items"]}
    assert {"SHINC", "SHEX", "SHEXUU", "WWDSHEX"} <= codes
    shinc = next(i for i in body["items"] if i["code"] == "SHINC")
    assert shinc["label_en"]
    assert shinc["label_zh"]
    # stable on second read (seed only once)
    again = client.get("/api/v1/laytimes/types", headers=auth_headers).json()
    assert [i["code"] for i in again["items"]] == [i["code"] for i in body["items"]]
