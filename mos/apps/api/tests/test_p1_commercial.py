"""P1 commercial fixes: EU ETS cost, multi-grade bunkers, multi-leg estimates,
COA lifting lifecycle, charter amendments."""

import json
from pathlib import Path

import pytest

FIXTURES_TCE = Path(__file__).resolve().parents[3] / "fixtures" / "calc" / "tce"


def _gold(name: str) -> dict:
    return json.loads((FIXTURES_TCE / f"{name}.json").read_text(encoding="utf-8"))


# ---- estimate engine: EU ETS / multi-grade / multi-leg ----


def test_gold_03_eu_ets_cost():
    from app.services.estimate_engine import compute_estimate

    g = _gold("gold_03")
    out = compute_estimate(g["inputs"])
    for k, expected in g["expect"].items():
        assert abs(out[k] - expected) <= 0.02, f"{k}: expected {expected} got {out[k]}"
    # emissions cost is a voyage cost component
    assert out["voyage_cost"] == pytest.approx(503750.0 + out["emissions_cost"], abs=0.02)


def test_ets_default_share_zero_backward_compatible():
    from app.services.estimate_engine import compute_estimate

    for name, tce in (("gold_01", 9953.13), ("gold_02", 9664.06)):
        out = compute_estimate(_gold(name)["inputs"])
        assert out["tce"] == tce
        assert out["emissions_cost"] == 0.0
        # fuel/CO2 are still reported even when no ETS share is priced
        assert out["fuel_mt"] == 875.0
        assert out["co2_mt"] == 2724.75
    # explicit zero share keeps cost at zero even with a price set
    out = compute_estimate({**_gold("gold_01")["inputs"], "eu_ets_share": 0, "ets_price": 100})
    assert out["emissions_cost"] == 0.0
    assert out["tce"] == 9953.13


def test_gold_04_multi_grade_bunker_prices():
    from app.services.estimate_engine import compute_estimate

    g = _gold("gold_04")
    out = compute_estimate(g["inputs"])
    for k, expected in g["expect"].items():
        assert abs(out[k] - expected) <= 0.02, f"{k}: expected {expected} got {out[k]}"


def test_multi_grade_fallback_to_single_price():
    from app.services.estimate_engine import compute_estimate

    base = _gold("gold_01")["inputs"]
    # unknown grade in bunker_prices falls back to legacy bunker_price
    out = compute_estimate({**base, "bunker_prices": {"VLSFO": 450}, "bunker_grade": "HSFO"})
    assert out["tce"] == 9953.13
    # known grade reprices the sea leg only
    out2 = compute_estimate({**base, "bunker_prices": {"VLSFO": 500}, "bunker_grade": "VLSFO"})
    assert out2["bunker_cost"] == 28 * 30 * 500 + 3.5 * 10 * 450


def test_gold_05_multi_legs_derive_days():
    from app.services.estimate_engine import compute_estimate

    g = _gold("gold_05")
    out = compute_estimate(g["inputs"])
    for k, expected in g["expect"].items():
        assert abs(out[k] - expected) <= 0.02, f"{k}: expected {expected} got {out[k]}"


def test_legs_invalid_values_raise():
    from app.services.estimate_engine import compute_estimate

    base = {"freight_rate": 10, "cargo_qty": 1000}
    with pytest.raises(ValueError):
        compute_estimate({**base, "legs": [{"distance_nm": 0, "speed_kn": 12}]})
    with pytest.raises(ValueError):
        compute_estimate({**base, "legs": [{"distance_nm": -100, "speed_kn": 12}]})
    with pytest.raises(ValueError):
        compute_estimate({**base, "legs": [{"distance_nm": 100, "speed_kn": 0}]})


def test_legs_invalid_422_via_api(client, auth_headers):
    h = auth_headers
    est = client.post(
        "/api/v1/estimates",
        headers=h,
        json={
            "title": "bad legs",
            "inputs": {
                "freight_rate": 10,
                "legs": [{"distance_nm": 500, "speed_kn": 0}],
            },
        },
    )
    assert est.status_code == 200, est.text
    calc = client.post(f"/api/v1/estimates/{est.json()['id']}/calculate", headers=h)
    assert calc.status_code == 422
    assert calc.json()["detail"]["code"] == "INVALID_ESTIMATE_INPUT"


# ---- COA lifting lifecycle ----


def _make_charter(client, h, **terms):
    r = client.post("/api/v1/charters", headers=h, json=terms)
    assert r.status_code == 200, r.text
    return r.json()


def _make_voyage(client, h, voyage_no="V-P1-001"):
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    r = client.post(
        "/api/v1/voyages",
        headers=h,
        json={"voyage_no": voyage_no, "vessel_id": vessels[0]["id"]},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_lifting(client, h, charter_id):
    r = client.post(
        f"/api/v1/charters/{charter_id}/liftings",
        headers=h,
        params={"period_label": "2026-Q1", "planned_qty": 30000},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_lifting_full_lifecycle(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h, charter_type="coa", cargo_qty=30000.0)
    lift_id = _make_lifting(client, h, charter["id"])

    # illegal: cannot complete / fix from planned
    bad = client.post(f"/api/v1/coa-liftings/{lift_id}/complete", headers=h, json={})
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "INVALID_STATE"
    voyage_id = _make_voyage(client, h)
    bad_fix = client.post(f"/api/v1/coa-liftings/{lift_id}/fix", headers=h, json={"voyage_id": voyage_id})
    assert bad_fix.status_code == 409

    # bad laycan window
    bad_laycan = client.post(
        f"/api/v1/coa-liftings/{lift_id}/nominate",
        headers=h,
        json={"laycan_from": "2026-03-10T00:00:00Z", "laycan_to": "2026-03-01T00:00:00Z"},
    )
    assert bad_laycan.status_code == 422

    nom = client.post(
        f"/api/v1/coa-liftings/{lift_id}/nominate",
        headers=h,
        json={"laycan_from": "2026-03-01T00:00:00Z", "laycan_to": "2026-03-10T00:00:00Z"},
    )
    assert nom.status_code == 200, nom.text
    assert nom.json()["status"] == "nominated"
    assert nom.json()["laycan_from"].startswith("2026-03-01")

    # illegal: nominate again
    again = client.post(
        f"/api/v1/coa-liftings/{lift_id}/nominate",
        headers=h,
        json={"laycan_from": "2026-03-01T00:00:00Z", "laycan_to": "2026-03-10T00:00:00Z"},
    )
    assert again.status_code == 409

    # fix requires an existing voyage in the same tenant
    missing = client.post(
        f"/api/v1/coa-liftings/{lift_id}/fix",
        headers=h,
        json={"voyage_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert missing.status_code == 404

    fixed = client.post(f"/api/v1/coa-liftings/{lift_id}/fix", headers=h, json={"voyage_id": voyage_id})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["status"] == "fixed"
    assert fixed.json()["voyage_id"] == voyage_id

    done = client.post(f"/api/v1/coa-liftings/{lift_id}/complete", headers=h, json={"actual_qty": 29500})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    assert done.json()["actual_qty"] == 29500.0

    # terminal: nothing further allowed
    late = client.post(
        f"/api/v1/coa-liftings/{lift_id}/nominate",
        headers=h,
        json={"laycan_from": "2026-03-01T00:00:00Z", "laycan_to": "2026-03-10T00:00:00Z"},
    )
    assert late.status_code == 409


def test_lifting_withdrawn_allowed_until_fixed(client, auth_headers):
    from app.services.state_machine import COA_LIFTING_TRANSITIONS, transition

    assert transition("coa_lifting", "planned", "withdrawn", COA_LIFTING_TRANSITIONS) == "withdrawn"
    assert transition("coa_lifting", "nominated", "withdrawn", COA_LIFTING_TRANSITIONS) == "withdrawn"
    assert transition("coa_lifting", "fixed", "withdrawn", COA_LIFTING_TRANSITIONS) == "withdrawn"


# ---- Charter amendments ----


def _activate_charter(client, h, charter_id):
    r1 = client.post(f"/api/v1/charters/{charter_id}/transition", headers=h, json={"target": "pending_approval"})
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"/api/v1/charters/{charter_id}/transition", headers=h, json={"target": "active"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "active"


def test_amendment_flow_active_charter(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h, demurrage_rate=18000.0, freight_rate=18.5, cargo_qty=50000.0)
    cid = charter["id"]

    # draft charter: key terms still freely patchable
    ok = client.patch(f"/api/v1/charters/{cid}", headers=h, json={"demurrage_rate": 19000.0})
    assert ok.status_code == 200, ok.text
    assert ok.json()["demurrage_rate"] == 19000.0

    _activate_charter(client, h, cid)

    # active charter: direct PATCH of key terms is rejected
    blocked = client.patch(f"/api/v1/charters/{cid}", headers=h, json={"demurrage_rate": 22000.0})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "AMENDMENT_REQUIRED"
    blocked2 = client.patch(f"/api/v1/charters/{cid}", headers=h, json={"laycan_from": "2026-03-01"})
    assert blocked2.status_code == 409
    # non-key fields are still patchable
    ok2 = client.patch(f"/api/v1/charters/{cid}", headers=h, json={"despatch_rate": 9500.0})
    assert ok2.status_code == 200, ok2.text

    # invalid amendment fields -> 422
    bad = client.post(
        f"/api/v1/charters/{cid}/amendments",
        headers=h,
        json={"changes": {"vessel_id": "x"}, "reason": "bad"},
    )
    assert bad.status_code == 422

    # amendment #1: proposed -> approved applies the changes
    a1 = client.post(
        f"/api/v1/charters/{cid}/amendments",
        headers=h,
        json={"changes": {"demurrage_rate": 22000.0}, "reason": "market uplift"},
    )
    assert a1.status_code == 200, a1.text
    assert a1.json()["seq"] == 1
    assert a1.json()["status"] == "proposed"

    listed = client.get(f"/api/v1/charters/{cid}/amendments", headers=h)
    assert listed.status_code == 200
    assert [a["seq"] for a in listed.json()] == [1]

    ap = client.post(f"/api/v1/charter-amendments/{a1.json()['id']}/approve", headers=h)
    assert ap.status_code == 200, ap.text
    assert ap.json()["status"] == "approved"
    after = client.get("/api/v1/charters", headers=h).json()
    row = next(c for c in after if c["id"] == cid)
    assert row["demurrage_rate"] == 22000.0

    # approving twice is an illegal transition
    again = client.post(f"/api/v1/charter-amendments/{a1.json()['id']}/approve", headers=h)
    assert again.status_code == 409

    # amendment #2: seq increments; rejected amendments do not apply
    a2 = client.post(
        f"/api/v1/charters/{cid}/amendments",
        headers=h,
        json={"changes": {"freight_rate": 25.0}, "reason": "renegotiation"},
    )
    assert a2.status_code == 200, a2.text
    assert a2.json()["seq"] == 2
    rj = client.post(f"/api/v1/charter-amendments/{a2.json()['id']}/reject", headers=h)
    assert rj.status_code == 200, rj.text
    assert rj.json()["status"] == "rejected"
    row = next(c for c in client.get("/api/v1/charters", headers=h).json() if c["id"] == cid)
    assert row["freight_rate"] == 18.5

    listed = client.get(f"/api/v1/charters/{cid}/amendments", headers=h).json()
    assert [(a["seq"], a["status"]) for a in listed] == [(1, "approved"), (2, "rejected")]


def test_amendment_laycan_applied_as_date(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h)
    cid = charter["id"]
    _activate_charter(client, h, cid)
    a = client.post(
        f"/api/v1/charters/{cid}/amendments",
        headers=h,
        json={"changes": {"laycan_from": "2026-04-01", "laycan_to": "2026-04-10"}},
    )
    assert a.status_code == 200, a.text
    client.post(f"/api/v1/charter-amendments/{a.json()['id']}/approve", headers=h)
    row = next(c for c in client.get("/api/v1/charters", headers=h).json() if c["id"] == cid)
    assert row["laycan_from"] == "2026-04-01"
    assert row["laycan_to"] == "2026-04-10"
