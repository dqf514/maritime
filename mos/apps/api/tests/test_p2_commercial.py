"""P2 commercial/operations fixes: cargo tolerance & capacity warnings in the
estimate engine, noon-report weather fields, SOF pre-NOR sequencing exemptions,
COA liftings list endpoint."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

FIXTURES_TCE = Path(__file__).resolve().parents[3] / "fixtures" / "calc" / "tce"

T0 = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)

BASE_INPUTS = {
    "cargo_qty": 50000,
    "freight_rate": 18.5,
    "commission_pct": 2.5,
    "sea_days": 30,
    "port_days": 10,
    "bunker_sea_tpd": 28,
    "bunker_port_tpd": 3.5,
    "bunker_price": 450,
    "port_costs": 80000,
    "canal_costs": 20000,
    "other_costs": 10000,
    "currency": "USD",
}


def _gold(name: str) -> dict:
    return json.loads((FIXTURES_TCE / f"{name}.json").read_text(encoding="utf-8"))


# ---- estimate engine: tolerance / stowage / deadweight ----


def test_cargo_tolerance_min_max():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate({**BASE_INPUTS, "cargo_tolerance_pct": 10})
    assert out["cargo_qty_min"] == 45000.0
    assert out["cargo_qty_max"] == 55000.0
    # tolerance band must not change voyage economics
    assert out["tce"] == 9953.13


def test_no_tolerance_no_min_max_keys():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(BASE_INPUTS)
    assert "cargo_qty_min" not in out
    assert "cargo_qty_max" not in out
    assert "warnings" not in out


def test_stowage_overflow_warning_non_blocking():
    from app.services.estimate_engine import compute_estimate

    # 50000 mt × 1.5 m3/mt = 75000 m3 > 70000 m3 hold capacity
    out = compute_estimate({**BASE_INPUTS, "stowage_factor": 1.5, "hold_capacity_m3": 70000})
    assert out["tce"] == 9953.13  # warning does not block or alter the result
    assert len(out["warnings"]) == 1
    assert out["warnings"][0]["code"] == "STOWAGE_OVERFLOW"

    # exactly at capacity is fine
    ok = compute_estimate({**BASE_INPUTS, "stowage_factor": 1.4, "hold_capacity_m3": 70000})
    assert "warnings" not in ok

    # only one of the pair provided → no check, no warning
    partial = compute_estimate({**BASE_INPUTS, "stowage_factor": 1.5})
    assert "warnings" not in partial


def test_deadweight_exceeded_warning():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate({**BASE_INPUTS, "vessel_deadweight": 45000})
    assert len(out["warnings"]) == 1
    assert out["warnings"][0]["code"] == "DEADWEIGHT_EXCEEDED"

    ok = compute_estimate({**BASE_INPUTS, "vessel_deadweight": 60000})
    assert "warnings" not in ok


def test_gold_06_tolerance_and_stowage_warning():
    from app.services.estimate_engine import compute_estimate

    g = _gold("gold_06")
    out = compute_estimate(g["inputs"])
    for k, expected in g["expect"].items():
        assert abs(out[k] - expected) <= 0.02, f"{k}: expected {expected} got {out[k]}"
    assert [w["code"] for w in out["warnings"]] == g["expect_warnings"]


def test_gold_01_05_unchanged():
    from app.services.estimate_engine import compute_estimate

    expected_tce = {"gold_01": 9953.13, "gold_02": 9664.06, "gold_03": 4503.63, "gold_04": 21979.0, "gold_05": 16300.0}
    for name, tce in expected_tce.items():
        out = compute_estimate(_gold(name)["inputs"])
        assert out["tce"] == pytest.approx(tce, abs=0.02), name
        assert "warnings" not in out, name


# ---- noon report weather fields ----


def test_noon_report_weather_fields_roundtrip(client, auth_headers):
    h = auth_headers
    v = client.post("/api/v1/voyages", headers=h, json={"voyage_no": "P2-NOON-1"})
    assert v.status_code == 200, v.text
    r = client.post(
        "/api/v1/noon-reports",
        headers=h,
        json={
            "voyage_id": v.json()["id"],
            "report_at": T0.isoformat(),
            "lat": 1.25,
            "lon": 103.8,
            "speed": 12.5,
            "wind_bf": 6.5,
            "sea_state": "rough",
            "current_kn": -0.8,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wind_bf"] == 6.5
    assert body["sea_state"] == "rough"
    assert body["current_kn"] == -0.8

    # weather fields are optional — legacy payloads still work
    r2 = client.post(
        "/api/v1/noon-reports",
        headers=h,
        json={"voyage_id": v.json()["id"], "report_at": (T0 + timedelta(days=1)).isoformat()},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["wind_bf"] is None
    assert r2.json()["sea_state"] is None
    assert r2.json()["current_kn"] is None


# ---- SOF pre-NOR sequencing exemptions ----


def _mk_port_call(client, h, voyage_no="P2-SOF-1"):
    v = client.post("/api/v1/voyages", headers=h, json={"voyage_no": voyage_no})
    assert v.status_code == 200, v.text
    pc = client.post("/api/v1/port-calls", headers=h, json={"voyage_id": v.json()["id"], "seq": 1, "purpose": "load"})
    assert pc.status_code == 200, pc.text
    return pc.json()


def _sof(client, h, pc_id, code, at):
    return client.post(
        "/api/v1/sof-events",
        headers=h,
        json={"port_call_id": pc_id, "event_code": code, "event_at": at.isoformat()},
    )


def test_sof_pre_nor_exempt_events_allowed_before_nor(client, auth_headers):
    h = auth_headers
    pc = _mk_port_call(client, h)
    assert _sof(client, h, pc["id"], "NOR", T0).status_code == 200
    # EOSP / ANCHOR / POB / AWSP realistically precede NOR and are exempt
    for i, code in enumerate(("EOSP", "ANCHOR", "POB", "AWSP")):
        r = _sof(client, h, pc["id"], code, T0 - timedelta(hours=i + 1))
        assert r.status_code == 200, f"{code}: {r.text}"


def test_sof_non_exempt_event_before_nor_still_422(client, auth_headers):
    h = auth_headers
    pc = _mk_port_call(client, h, voyage_no="P2-SOF-2")
    assert _sof(client, h, pc["id"], "NOR", T0).status_code == 200
    r = _sof(client, h, pc["id"], "COMMENCED", T0 - timedelta(hours=1))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "SOF_SEQUENCE_VIOLATION"


def test_sof_nor_bound_by_non_exempt_events_only(client, auth_headers):
    h = auth_headers
    pc = _mk_port_call(client, h, voyage_no="P2-SOF-3")
    # exempt events recorded first do not constrain a later NOR
    assert _sof(client, h, pc["id"], "EOSP", T0 - timedelta(hours=3)).status_code == 200
    assert _sof(client, h, pc["id"], "ANCHOR", T0 - timedelta(hours=2)).status_code == 200
    assert _sof(client, h, pc["id"], "NOR", T0).status_code == 200
    # but a non-exempt event earlier than a late NOR still blocks it
    pc2 = _mk_port_call(client, h, voyage_no="P2-SOF-4")
    assert _sof(client, h, pc2["id"], "COMMENCED", T0).status_code == 200
    late_nor = _sof(client, h, pc2["id"], "NOR", T0 + timedelta(hours=1))
    assert late_nor.status_code == 422
    assert late_nor.json()["detail"]["code"] == "SOF_SEQUENCE_VIOLATION"


# ---- COA liftings list endpoint ----


def test_list_charter_liftings(client, auth_headers):
    h = auth_headers
    charter = client.post("/api/v1/charters", headers=h, json={"charter_type": "coa", "cargo_qty": 30000.0})
    assert charter.status_code == 200, charter.text
    cid = charter.json()["id"]

    # empty list before any lifting
    empty = client.get(f"/api/v1/charters/{cid}/liftings", headers=h)
    assert empty.status_code == 200, empty.text
    assert empty.json() == []

    for label, qty in (("2026-Q1", 30000), ("2026-Q2", 32000)):
        r = client.post(
            f"/api/v1/charters/{cid}/liftings",
            headers=h,
            params={"period_label": label, "planned_qty": qty},
        )
        assert r.status_code == 200, r.text

    listed = client.get(f"/api/v1/charters/{cid}/liftings", headers=h)
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert [r["period_label"] for r in rows] == ["2026-Q1", "2026-Q2"]
    assert [r["planned_qty"] for r in rows] == [30000.0, 32000.0]
    assert all(r["status"] == "planned" for r in rows)
    assert all(r["charter_id"] == cid for r in rows)

    missing = client.get("/api/v1/charters/00000000-0000-0000-0000-000000000000/liftings", headers=h)
    assert missing.status_code == 404
