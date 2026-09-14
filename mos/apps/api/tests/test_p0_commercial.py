"""P0 commercial fixes: commission split, Charter CP terms, off-hire, TC hire summary."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

FIXTURES_TCE = Path(__file__).resolve().parents[3] / "fixtures" / "calc" / "tce"


# ---- estimate engine: commission split ----


def test_commission_split_backward_compatible():
    from app.services.estimate_engine import compute_estimate

    gold01 = json.loads((FIXTURES_TCE / "gold_01.json").read_text(encoding="utf-8"))
    out = compute_estimate(gold01["inputs"])
    # legacy commission_pct behaves as address commission; no brokerage
    assert out["tce"] == 9953.13
    assert out["address_commission"] == 23125.0
    assert out["commission"] == 23125.0
    assert out["brokerage"] == 0.0
    assert out["voyage_cost"] == 503750.0


def test_commission_split_address_and_brokerage():
    from app.services.estimate_engine import compute_estimate

    gold02 = json.loads((FIXTURES_TCE / "gold_02.json").read_text(encoding="utf-8"))
    out = compute_estimate(gold02["inputs"])
    for k, expected in gold02["expect"].items():
        assert abs(out[k] - expected) <= 0.02, f"{k}: expected {expected} got {out[k]}"
    # brokerage reduces TCE via voyage_cost, address commission via revenue
    assert out["net_freight"] == 901875.0


def test_address_comm_pct_overrides_legacy():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 10000,
            "freight_rate": 20,
            "address_comm_pct": 1.0,
            "commission_pct": 5.0,  # ignored when address_comm_pct present
            "sea_days": 10,
        }
    )
    assert out["address_commission"] == 2000.0
    assert out["commission"] == 2000.0


# ---- Charter new fields ----

CHARTER_TERMS = {
    "demurrage_rate": 18000.0,
    "despatch_rate": 9000.0,
    "laytime_terms": "shex",  # normalized to SHEX
    "cp_form": "gencon",  # normalized to GENCON
    "freight_rate": 18.5,
    "freight_basis": "per_mt",
    "cargo_qty": 50000.0,
    "load_rate_pd": 10000.0,
    "disch_rate_pd": 8000.0,
    "address_comm_pct": 1.25,
    "brokerage_pct": 1.25,
    "hire_per_day": 21000.0,
    "hire_cycle_days": 30,
    "delivery_at": "2026-02-01T00:00:00+00:00",
    "redelivery_at": "2026-03-03T00:00:00+00:00",
    "ets_responsibility": "charterer",
}


def test_charter_new_fields_create_update_roundtrip(client, auth_headers):
    h = auth_headers
    r = client.post("/api/v1/charters", headers=h, json={"charter_type": "tct", **CHARTER_TERMS})
    assert r.status_code == 200, r.text
    body = r.json()
    charter_id = body["id"]
    assert body["demurrage_rate"] == 18000.0
    assert body["laytime_terms"] == "SHEX"
    assert body["cp_form"] == "GENCON"
    assert body["freight_basis"] == "per_mt"
    assert body["cargo_qty"] == 50000.0
    assert body["address_comm_pct"] == 1.25
    assert body["brokerage_pct"] == 1.25
    assert body["hire_per_day"] == 21000.0
    assert body["hire_cycle_days"] == 30
    assert body["ets_responsibility"] == "charterer"

    u = client.patch(
        f"/api/v1/charters/{charter_id}",
        headers=h,
        json={"demurrage_rate": 20000.0, "laytime_terms": "sshex", "freight_basis": "lumpsum"},
    )
    assert u.status_code == 200, u.text
    ub = u.json()
    assert ub["demurrage_rate"] == 20000.0
    assert ub["laytime_terms"] == "SSHEX"
    assert ub["freight_basis"] == "lumpsum"
    # untouched fields preserved
    assert ub["brokerage_pct"] == 1.25


def test_charter_invalid_freight_basis_422(client, auth_headers):
    h = auth_headers
    r = client.post("/api/v1/charters", headers=h, json={"freight_basis": "bogus"})
    assert r.status_code == 422

    ok = client.post("/api/v1/charters", headers=h, json={})
    assert ok.status_code == 200
    u = client.patch(f"/api/v1/charters/{ok.json()['id']}", headers=h, json={"freight_basis": "PER_DAY"})
    assert u.status_code == 422


def test_estimate_to_charter_carries_terms(client, auth_headers):
    h = auth_headers
    est = client.post(
        "/api/v1/estimates",
        headers=h,
        json={
            "title": "P0 commission split",
            "inputs": {
                "cargo_qty": 50000,
                "freight_rate": 18.5,
                "address_comm_pct": 2.5,
                "brokerage_pct": 1.25,
                "sea_days": 30,
                "port_days": 10,
                "bunker_sea_tpd": 28,
                "bunker_port_tpd": 3.5,
                "bunker_price": 450,
                "port_costs": 80000,
                "canal_costs": 20000,
                "other_costs": 10000,
            },
        },
    )
    assert est.status_code == 200, est.text
    est_id = est.json()["id"]
    cp = client.post(f"/api/v1/estimates/{est_id}/to-charter", headers=h)
    assert cp.status_code == 200, cp.text
    body = cp.json()
    assert body["cargo_qty"] == 50000.0
    assert body["freight_rate"] == 18.5
    assert body["freight_basis"] == "per_mt"
    assert body["address_comm_pct"] == 2.5
    assert body["brokerage_pct"] == 1.25


# ---- Off-hire events & hire summary ----


def _make_voyage(client, h, charter_id=None):
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    r = client.post(
        "/api/v1/voyages",
        headers=h,
        json={"voyage_no": "V-P0-001", "vessel_id": vessels[0]["id"], "charter_id": charter_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_offhire_open_close_and_deduction(client, auth_headers):
    h = auth_headers
    voyage_id = _make_voyage(client, h)
    start = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)

    opened = client.post(
        f"/api/v1/voyages/{voyage_id}/off-hire",
        headers=h,
        json={"start_at": start.isoformat(), "reason": "engine failure", "deduct_hire": True},
    )
    assert opened.status_code == 200, opened.text
    ev = opened.json()
    assert ev["status"] == "open"
    assert ev["deducted_days"] is None

    closed = client.post(
        f"/api/v1/off-hire/{ev['id']}/close",
        headers=h,
        json={"end_at": (start + timedelta(hours=36)).isoformat()},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["deducted_days"] == 1.5

    # closing a closed event is an illegal transition
    again = client.post(
        f"/api/v1/off-hire/{ev['id']}/close",
        headers=h,
        json={"end_at": (start + timedelta(hours=48)).isoformat()},
    )
    assert again.status_code == 409

    listed = client.get(f"/api/v1/voyages/{voyage_id}/off-hire", headers=h)
    assert listed.status_code == 200
    assert [e["id"] for e in listed.json()] == [ev["id"]]


def test_offhire_close_before_start_422(client, auth_headers):
    h = auth_headers
    voyage_id = _make_voyage(client, h)
    start = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    ev = client.post(
        f"/api/v1/voyages/{voyage_id}/off-hire",
        headers=h,
        json={"start_at": start.isoformat()},
    ).json()
    bad = client.post(
        f"/api/v1/off-hire/{ev['id']}/close",
        headers=h,
        json={"end_at": (start - timedelta(hours=1)).isoformat()},
    )
    assert bad.status_code == 422


def test_hire_summary_with_offhire_deduction(client, auth_headers):
    h = auth_headers
    delivery = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    redelivery = delivery + timedelta(days=30)
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={
            "charter_type": "tc",
            "hire_per_day": 20000.0,
            "delivery_at": delivery.isoformat(),
            "redelivery_at": redelivery.isoformat(),
        },
    )
    assert cp.status_code == 200, cp.text
    charter_id = cp.json()["id"]

    s = client.get(f"/api/v1/charters/{charter_id}/hire-summary", headers=h)
    assert s.status_code == 200, s.text
    body = s.json()
    assert body["charter_id"] == charter_id
    assert body["hire_per_day"] == 20000.0
    assert body["gross_days"] == 30.0
    assert body["offhire_days"] == 0.0
    assert body["billable_days"] == 30.0
    assert body["amount_due"] == 600000.0
    assert body["currency"] == "USD"

    # 60h deductible off-hire on a voyage of this charter -> 2.5 days deducted
    voyage_id = _make_voyage(client, h, charter_id=charter_id)
    ev = client.post(
        f"/api/v1/voyages/{voyage_id}/off-hire",
        headers=h,
        json={"start_at": (delivery + timedelta(days=5)).isoformat(), "reason": "drydock"},
    ).json()
    client.post(
        f"/api/v1/off-hire/{ev['id']}/close",
        headers=h,
        json={"end_at": (delivery + timedelta(days=5, hours=60)).isoformat()},
    )

    s2 = client.get(f"/api/v1/charters/{charter_id}/hire-summary", headers=h).json()
    assert s2["offhire_days"] == 2.5
    assert s2["billable_days"] == 27.5
    assert s2["amount_due"] == 550000.0


def test_hire_summary_cycle_days_fallback(client, auth_headers):
    h = auth_headers
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "tct", "hire_per_day": 15000.0, "hire_cycle_days": 15},
    )
    assert cp.status_code == 200, cp.text
    s = client.get(f"/api/v1/charters/{cp.json()['id']}/hire-summary", headers=h)
    assert s.status_code == 200, s.text
    assert s.json()["gross_days"] == 15.0
    assert s.json()["amount_due"] == 225000.0


def test_hire_summary_missing_rate_422(client, auth_headers):
    h = auth_headers
    cp = client.post("/api/v1/charters", headers=h, json={"charter_type": "voyage"})
    assert cp.status_code == 200
    s = client.get(f"/api/v1/charters/{cp.json()['id']}/hire-summary", headers=h)
    assert s.status_code == 422
