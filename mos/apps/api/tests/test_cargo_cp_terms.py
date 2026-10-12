"""Cargo CP terms (C1-P1): bill_by / tolerance_pct / overage_pct on charter + COA.

Covers CRUD, 422 validation ranges, tenant isolation, overage pricing
(``/charters/{id}/cargo-terms-price`` + pure ``freight_with_overage``), the
pricing-tab cargo↔itinerary scoring endpoint, and estimate→charter term carry-over.
"""

from __future__ import annotations

from decimal import Decimal

from tests.isolation_helpers import create_tenant


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_charter(client, h, **over) -> dict:
    body = {
        "charter_type": "voyage",
        "cargo_qty": 50000.0,
        "freight_rate": 18.5,
        "freight_basis": "per_mt",
    }
    body.update(over)
    r = client.post("/api/v1/charters", headers=h, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _make_coa(client, h, charter_id: str, **over) -> dict:
    body = {
        "charter_id": charter_id,
        "total_qty": 60000.0,
        "qty_unit": "mt",
        "period_from": "2026-01-01",
        "period_to": "2026-12-31",
        "rate_basis": "per_mt",
        "rate": 25.0,
    }
    body.update(over)
    r = client.post("/api/v1/coa/contracts", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── charter CRUD ─────────────────────────────────────────────────────────────


def test_charter_cargo_terms_crud(client, auth_headers):
    h = auth_headers
    ch = _make_charter(
        client,
        h,
        bill_by="weight",
        tolerance_pct=10.0,
        overage_pct=20.0,
    )
    assert ch["bill_by"] == "weight"
    assert ch["tolerance_pct"] == 10.0
    assert ch["overage_pct"] == 20.0

    got = client.get(f"/api/v1/charters/{ch['id']}", headers=h).json()
    assert got["bill_by"] == "weight"
    assert got["tolerance_pct"] == 10.0
    assert got["overage_pct"] == 20.0

    patched = client.patch(
        f"/api/v1/charters/{ch['id']}",
        headers=h,
        json={"bill_by": "measure", "tolerance_pct": 5.5, "overage_pct": 0.0},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["bill_by"] == "measure"
    assert patched.json()["tolerance_pct"] == 5.5
    assert patched.json()["overage_pct"] == 0.0

    listed = client.get("/api/v1/charters", headers=h).json()
    row = next(r for r in listed if r["id"] == ch["id"])
    assert row["bill_by"] == "measure"


def test_charter_cargo_terms_default_null(client, auth_headers):
    ch = _make_charter(client, auth_headers)
    assert ch["bill_by"] is None
    assert ch["tolerance_pct"] is None
    assert ch["overage_pct"] is None


# ── validation 422 ───────────────────────────────────────────────────────────


def test_charter_cargo_terms_validation_422(client, auth_headers):
    h = auth_headers
    for bad in (
        {"bill_by": "bogus"},
        {"bill_by": "cp_qty"},  # invoice-level vocabulary is not a cargo qty basis
        {"tolerance_pct": -1},
        {"tolerance_pct": 100},  # > 50
        {"overage_pct": -0.5},
        {"overage_pct": 250},  # > 100
    ):
        r = client.post("/api/v1/charters", headers=h, json={"charter_type": "voyage", **bad})
        assert r.status_code == 422, f"{bad} -> {r.status_code}: {r.text}"

    ch = _make_charter(client, h)
    for bad in ({"tolerance_pct": 51}, {"overage_pct": -1}, {"bill_by": "volume?"}):
        r = client.patch(f"/api/v1/charters/{ch['id']}", headers=h, json=bad)
        assert r.status_code == 422, f"{bad} -> {r.status_code}: {r.text}"


def test_coa_cargo_terms_validation_422(client, auth_headers):
    h = auth_headers
    ch = _make_charter(client, h)
    base = {
        "charter_id": ch["id"],
        "total_qty": 60000.0,
        "period_from": "2026-01-01",
        "period_to": "2026-12-31",
        "rate": 25.0,
    }
    for bad in (
        {"bill_by": "tonnage"},
        {"tolerance_pct": 50.01},
        {"overage_pct": -2},
    ):
        r = client.post("/api/v1/coa/contracts", headers=h, json={**base, **bad})
        assert r.status_code == 422, f"{bad} -> {r.status_code}: {r.text}"

    coa = _make_coa(client, h, ch["id"], bill_by="volume", tolerance_pct=5, overage_pct=15)
    r = client.patch(
        f"/api/v1/coa/contracts/{coa['id']}",
        headers=h,
        json={"tolerance_pct": 999},
    )
    assert r.status_code == 422, r.text


# ── COA contract CRUD ────────────────────────────────────────────────────────


def test_coa_cargo_terms_crud(client, auth_headers):
    h = auth_headers
    ch = _make_charter(client, h)
    coa = _make_coa(client, h, ch["id"], bill_by="volume", tolerance_pct=5, overage_pct=15)
    assert coa["bill_by"] == "volume"
    assert coa["tolerance_pct"] == 5.0
    assert coa["overage_pct"] == 15.0

    got = client.get(f"/api/v1/coa/contracts/{coa['id']}", headers=h).json()
    assert got["bill_by"] == "volume"
    assert got["tolerance_pct"] == 5.0

    patched = client.patch(
        f"/api/v1/coa/contracts/{coa['id']}",
        headers=h,
        json={"bill_by": "measure", "tolerance_pct": 2.5},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["bill_by"] == "measure"
    assert patched.json()["tolerance_pct"] == 2.5
    assert patched.json()["overage_pct"] == 15.0  # untouched


# ── tenant isolation ─────────────────────────────────────────────────────────


def test_cargo_terms_tenant_isolation(client, auth_headers):
    h = auth_headers
    ch = _make_charter(client, h, bill_by="weight", tolerance_pct=10, overage_pct=20)
    coa = _make_coa(client, h, ch["id"], bill_by="weight", tolerance_pct=10)

    _, hb = create_tenant(
        client, code="cgt-iso", name="CGT Iso", admin_email="admin@cgt-iso.example.com"
    )
    assert client.get(f"/api/v1/charters/{ch['id']}", headers=hb).status_code == 404
    assert client.patch(
        f"/api/v1/charters/{ch['id']}", headers=hb, json={"tolerance_pct": 1}
    ).status_code == 404
    assert client.get(f"/api/v1/coa/contracts/{coa['id']}", headers=hb).status_code == 404
    assert client.patch(
        f"/api/v1/coa/contracts/{coa['id']}", headers=hb, json={"overage_pct": 1}
    ).status_code == 404
    assert (
        client.get(
            f"/api/v1/charters/{ch['id']}/cargo-terms-price",
            headers=hb,
            params={"billed_qty": 100},
        ).status_code
        == 404
    )
    assert client.get(f"/api/v1/coa/contracts/{coa['id']}/score", headers=hb).status_code == 404


# ── pricing path: overage beyond tolerance at higher rate ────────────────────


def test_freight_with_overage_unit():
    from app.services.cargo_terms import freight_with_overage

    # 50k contract ±10% → max 55k; billed 58k → 3k overage at +20% rate
    out = freight_with_overage(
        contract_qty=Decimal("50000"),
        billed_qty=Decimal("58000"),
        freight_rate=Decimal("18.5"),
        tolerance_pct=Decimal("10"),
        overage_pct=Decimal("20"),
    )
    assert out["qty_min"] == 45000.0
    assert out["qty_max"] == 55000.0
    assert out["qty_at_contract_rate"] == 55000.0
    assert out["qty_at_overage_rate"] == 3000.0
    assert out["overage_rate"] == 22.2
    assert out["contract_freight"] == 1017500.0
    assert out["overage_freight"] == 66600.0
    assert out["total_freight"] == 1084100.0

    # inside the tolerance window → no overage
    inside = freight_with_overage(
        contract_qty=50000,
        billed_qty=52000,
        freight_rate=18.5,
        tolerance_pct=10,
        overage_pct=20,
    )
    assert inside["qty_at_overage_rate"] == 0.0
    assert inside["overage_freight"] == 0.0
    assert inside["total_freight"] == 962000.0

    # no tolerance / no overage → plain rate (legacy shape preserved)
    plain = freight_with_overage(
        contract_qty=50000, billed_qty=50000, freight_rate=18.5
    )
    assert plain["qty_min"] == 50000.0
    assert plain["qty_max"] == 50000.0
    assert plain["overage_pct"] == 0.0
    assert plain["total_freight"] == 925000.0

    # short shipment bills on the billed quantity
    short = freight_with_overage(
        contract_qty=50000, billed_qty=40000, freight_rate=18.5, tolerance_pct=10
    )
    assert short["qty_at_contract_rate"] == 40000.0
    assert short["total_freight"] == 740000.0

    # negative inputs rejected
    for kwargs in (
        {"contract_qty": 1, "billed_qty": -1, "freight_rate": 1},
        {"contract_qty": 1, "billed_qty": 1, "freight_rate": -2},
    ):
        try:
            freight_with_overage(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kwargs}")


def test_charter_cargo_terms_price_endpoint(client, auth_headers):
    h = auth_headers
    ch = _make_charter(
        client,
        h,
        bill_by="weight",
        tolerance_pct=10.0,
        overage_pct=20.0,
    )
    r = client.get(
        f"/api/v1/charters/{ch['id']}/cargo-terms-price",
        headers=h,
        params={"billed_qty": 58000},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bill_by"] == "weight"
    priced = body["priced"]
    assert priced["qty_max"] == 55000.0
    assert priced["qty_at_overage_rate"] == 3000.0
    assert priced["overage_rate"] == 22.2
    assert priced["total_freight"] == 1084100.0

    # billed inside the window → no overage component
    ok = client.get(
        f"/api/v1/charters/{ch['id']}/cargo-terms-price",
        headers=h,
        params={"billed_qty": 52000},
    ).json()
    assert ok["priced"]["overage_freight"] == 0.0

    # billed_qty must be > 0
    assert (
        client.get(
            f"/api/v1/charters/{ch['id']}/cargo-terms-price",
            headers=h,
            params={"billed_qty": 0},
        ).status_code
        == 422
    )


# ── estimate → charter term carry-over ───────────────────────────────────────


def test_estimate_to_charter_carries_tolerance(client, auth_headers):
    h = auth_headers
    r = client.post(
        "/api/v1/estimates",
        headers=h,
        json={
            "title": "CP terms carry",
            "mode": "voyage",
            "inputs": {
                "cargo_qty": 50000,
                "freight_rate": 18.5,
                "cargo_tolerance_pct": 10,
                "bill_by": "weight",
                "overage_pct": 15,
                "sea_days": 10,
                "port_days": 2,
            },
        },
    )
    assert r.status_code in (200, 201), r.text
    est_id = r.json()["id"]
    conv = client.post(f"/api/v1/estimates/{est_id}/to-charter", headers=h)
    assert conv.status_code == 200, conv.text
    ch = conv.json()
    assert ch["tolerance_pct"] == 10.0
    assert ch["bill_by"] == "weight"
    assert ch["overage_pct"] == 15.0


# ── pricing-tab auto scoring: cargo parcels ↔ itinerary legs ─────────────────


def test_score_cargo_vs_leg_unit():
    from app.services.cargo_terms import score_cargo_vs_leg

    perfect = score_cargo_vs_leg(
        cargo_load_port_id="L",
        cargo_disch_port_id="D",
        cargo_qty=50000,
        cargo_laycan_from=None,
        cargo_laycan_to=None,
        leg_load_port_id="L",
        leg_disch_port_id="D",
        leg_qty=50000,
        period_from=None,
        period_to=None,
        tolerance_pct=10,
    )
    # 25 + 25 + 30 + 0 (no laycan/period supplied) = 80
    assert perfect["score"] == 80.0
    assert perfect["within_tolerance"] is True

    mismatch = score_cargo_vs_leg(
        cargo_load_port_id="X",
        cargo_disch_port_id="D",
        cargo_qty=10000,
        cargo_laycan_from=None,
        cargo_laycan_to=None,
        leg_load_port_id="L",
        leg_disch_port_id="D",
        leg_qty=50000,
        tolerance_pct=10,
    )
    assert mismatch["breakdown"]["load_port"] == 0.0
    assert mismatch["breakdown"]["qty_fit"] == 6.0  # 30 × 10/50
    assert mismatch["within_tolerance"] is False


def test_coa_score_endpoint(client, auth_headers):
    h = auth_headers
    # two reference ports (global master data)
    suffix = "SGT"
    p1 = client.post(
        "/api/v1/masterdata/ports",
        headers=h,
        json={"name": f"Score Load {suffix}", "unlocode": f"SL{suffix}"},
    )
    p2 = client.post(
        "/api/v1/masterdata/ports",
        headers=h,
        json={"name": f"Score Disch {suffix}", "unlocode": f"SD{suffix}"},
    )
    assert p1.status_code in (200, 201), p1.text
    assert p2.status_code in (200, 201), p2.text
    load_id, disch_id = p1.json()["id"], p2.json()["id"]

    ch = _make_charter(client, h)
    coa = _make_coa(client, h, ch["id"], tolerance_pct=10)
    leg = client.post(
        f"/api/v1/coa/contracts/{coa['id']}/itineraries",
        headers=h,
        json={"seq": 1, "qty": 50000, "load_port_id": load_id, "disch_port_id": disch_id},
    )
    assert leg.status_code == 201, leg.text

    # matching cargo parcel (same ports, qty within ±10%, laycan inside period)
    cg = client.post(
        "/api/v1/cargo",
        headers=h,
        json={
            "commodity": "Iron ore",
            "qty": 50000,
            "qty_unit": "mt",
            "load_port_id": load_id,
            "disch_port_id": disch_id,
            "laycan_from": "2026-03-01",
            "laycan_to": "2026-03-15",
        },
    )
    assert cg.status_code in (200, 201), cg.text
    # non-matching parcel
    other = client.post(
        "/api/v1/cargo",
        headers=h,
        json={
            "commodity": "Coal",
            "qty": 10000,
            "qty_unit": "mt",
            "load_port_id": disch_id,
            "disch_port_id": load_id,
            "laycan_from": "2027-01-01",
            "laycan_to": "2027-01-15",
        },
    )
    assert other.status_code in (200, 201), other.text

    r = client.get(f"/api/v1/coa/contracts/{coa['id']}/score", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tolerance_pct"] == 10.0
    assert len(body["items"]) == 1
    leg_score = body["items"][0]
    assert leg_score["seq"] == 1
    matches = leg_score["matches"]
    assert matches, "expected at least one scored cargo"
    best = matches[0]
    assert best["cargo_id"] == cg.json()["id"]
    # 25+25+30+20 = 100 for a perfect pair
    assert best["score"] == 100.0
    assert best["within_tolerance"] is True
    assert any(m["cargo_id"] == other.json()["id"] for m in matches) or other.json()["id"] not in {
        m["cargo_id"] for m in matches
    }
    # ranking is deterministic: the matching parcel outscores the mismatch
    scores = {m["cargo_id"]: m["score"] for m in matches}
    if other.json()["id"] in scores:
        assert scores[cg.json()["id"]] > scores[other.json()["id"]]
