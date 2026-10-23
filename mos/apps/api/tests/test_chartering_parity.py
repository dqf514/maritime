"""P11 Chartering parity — TC Code auto-numbering, lay events / pricing ladder /
other-items grids, Fixture No. + header fields, fixture itinerary calculator,
cargo itinerary/options, open positions.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _items(payload):
    return payload["items"] if isinstance(payload, dict) else payload


def _make_charter(client, h, **overrides):
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    body = {
        "charter_type": "tct",
        "counterparty_id": parties[0]["id"],
        "hire_per_day": 12000,
    }
    body.update(overrides)
    r = client.post("/api/v1/charters", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _make_tc(client, h, **overrides):
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    vessels = _items(client.get("/api/v1/masterdata/vessels", headers=h).json())
    charter = _make_charter(client, h)
    body = {
        "charter_id": charter["id"],
        "contract_type": "tci",
        "contract_style": "time_charter",
        "vessel_id": vessels[0]["id"],
        "counterparty_id": parties[0]["id"],
        "hire_rate": 10000,
        "delivery_date": "2026-01-01",
        "redelivery_date": "2026-03-01",
    }
    body.update(overrides)
    r = client.post("/api/v1/tc/contracts", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── TC Code auto-numbering ───────────────────────────────────────────────────


def test_tc_code_autogen_tci_tco(client, auth_headers):
    h = auth_headers
    tc_in = _make_tc(client, h, contract_type="tci")
    assert tc_in["tc_code"], "tc_code must be auto-assigned"
    # VESSELNAME-I0001 format
    assert "-I" in tc_in["tc_code"]
    assert tc_in["tc_code"].endswith("0001") or tc_in["tc_code"].endswith("0002")

    tc_out = _make_tc(client, h, contract_type="tco")
    assert "-O" in tc_out["tc_code"]
    # In and Out sequences are independent
    assert tc_out["tc_code"].split("-")[0] == tc_in["tc_code"].split("-")[0]


def test_tc_code_explicit_override(client, auth_headers):
    h = auth_headers
    tc = _make_tc(client, h, tc_code="MYVES-I0099")
    assert tc["tc_code"] == "MYVES-I0099"


def test_tc_code_survives_reload(client, auth_headers):
    h = auth_headers
    tc = _make_tc(client, h)
    detail = client.get(f"/api/v1/tc/contracts/{tc['id']}", headers=h).json()
    assert detail["tc_code"] == tc["tc_code"]


# ── Lay events (Delivery/Redelivery table + Difference) ──────────────────────


def test_lay_events_crud_and_difference(client, auth_headers):
    h = auth_headers
    tc = _make_tc(client, h)

    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/lay-events",
        headers=h,
        json={
            "kind": "delivery",
            "port": "SINGAPORE",
            "est_gmt": "2026-01-01T00:00:00Z",
            "proj_act_gmt": "2026-01-01T06:00:00Z",
            "remarks": "NOR tendered",
        },
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["kind"] == "delivery"
    assert row["difference_hours"] == 6.0  # proj/act − est

    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/lay-events",
        headers=h,
        json={"kind": "redelivery", "port": "ROTTERDAM", "est_gmt": "2026-03-01T00:00:00Z"},
    )
    assert r.status_code == 201
    assert r.json()["difference_hours"] is None  # no proj/act yet

    rows = client.get(f"/api/v1/tc/contracts/{tc['id']}/lay-events", headers=h).json()
    assert len(rows) == 2

    # patch proj/act → difference recomputed
    r2 = client.patch(
        f"/api/v1/tc/contracts/{tc['id']}/lay-events/{rows[1]['id']}",
        headers=h,
        json={"proj_act_gmt": "2026-02-28T18:00:00Z"},
    )
    assert r2.status_code == 200
    assert r2.json()["difference_hours"] == -6.0  # 6 hours early redelivery

    r = client.delete(
        f"/api/v1/tc/contracts/{tc['id']}/lay-events/{row['id']}", headers=h
    )
    assert r.status_code == 200
    rows = client.get(f"/api/v1/tc/contracts/{tc['id']}/lay-events", headers=h).json()
    assert len(rows) == 1


# ── Pricing ladder ───────────────────────────────────────────────────────────


def test_pricing_ladder_crud(client, auth_headers):
    h = auth_headers
    tc = _make_tc(client, h)

    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/pricing-rows",
        headers=h,
        json={
            "hire_rate": 12000,
            "rate_type": "per_day",
            "from_gmt": "2026-01-01T00:00:00Z",
            "to_gmt": "2026-02-01T00:00:00Z",
            "duration_days": 31,
            "tcl_ins": 250,
            "comments": "first period",
        },
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["hire_rate"] == 12000
    assert row["rate_type"] == "per_day"
    assert row["tcl_ins"] == 250

    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/pricing-rows",
        headers=h,
        json={"hire_rate": 13500, "rate_type": "per_day", "locked": True},
    )
    assert r.status_code == 201
    assert r.json()["locked"] is True

    rows = client.get(f"/api/v1/tc/contracts/{tc['id']}/pricing-rows", headers=h).json()
    assert len(rows) == 2

    r = client.patch(
        f"/api/v1/tc/contracts/{tc['id']}/pricing-rows/{rows[0]['id']}",
        headers=h,
        json={"hire_rate": 12500},
    )
    assert r.status_code == 200
    assert r.json()["hire_rate"] == 12500

    r = client.delete(
        f"/api/v1/tc/contracts/{tc['id']}/pricing-rows/{rows[1]['id']}", headers=h
    )
    assert r.status_code == 200
    rows = client.get(f"/api/v1/tc/contracts/{tc['id']}/pricing-rows", headers=h).json()
    assert len(rows) == 1


# ── Other-items expense grid ─────────────────────────────────────────────────


def test_other_items_crud(client, auth_headers):
    h = auth_headers
    tc = _make_tc(client, h)

    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/other-items",
        headers=h,
        json={
            "code": "BALLA",
            "description": "Ballast adjustment",
            "rate_type": "lumpsum",
            "rate": 15000,
            "comm": True,
        },
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["code"] == "BALLA"
    assert row["rate"] == 15000
    assert row["comm"] is True

    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/other-items",
        headers=h,
        json={"code": "VICTU", "rate_type": "per_day", "rate": 850},
    )
    assert r.status_code == 201

    # invalid code rejected
    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/other-items",
        headers=h,
        json={"code": "NOPE", "rate": 1},
    )
    assert r.status_code == 422

    rows = client.get(f"/api/v1/tc/contracts/{tc['id']}/other-items", headers=h).json()
    assert {r["code"] for r in rows} == {"BALLA", "VICTU"}

    r = client.patch(
        f"/api/v1/tc/contracts/{tc['id']}/other-items/{rows[0]['id']}",
        headers=h,
        json={"rate": 16000},
    )
    assert r.status_code == 200
    assert r.json()["rate"] == 16000

    r = client.delete(
        f"/api/v1/tc/contracts/{tc['id']}/other-items/{rows[1]['id']}", headers=h
    )
    assert r.status_code == 200


# ── Broker rule IMOS columns ─────────────────────────────────────────────────


def test_broker_rule_p11_columns(client, auth_headers):
    h = auth_headers
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    tc = _make_tc(client, h)

    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/broker-rules",
        headers=h,
        json={
            "broker_party_id": parties[0]["id"],
            "commission_type": "brokerage",
            "commission_pct": 1.25,
            "applies_to": "all",
            "payment_method": "deduct_from_hire",
            "m_method": 1,
            "from_gmt": "2026-01-01T00:00:00Z",
            "to_gmt": "2026-03-01T00:00:00Z",
            "remarks": "IMOS grid columns",
        },
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["payment_method"] == "deduct_from_hire"
    assert row["m_method"] == 1
    assert row["remarks"] == "IMOS grid columns"

    r = client.patch(
        f"/api/v1/tc/contracts/{tc['id']}/broker-rules/{row['id']}",
        headers=h,
        json={"payment_method": "pay_directly", "m_method": 0},
    )
    assert r.status_code == 200
    assert r.json()["payment_method"] == "pay_directly"

    r = client.delete(
        f"/api/v1/tc/contracts/{tc['id']}/broker-rules/{row['id']}", headers=h
    )
    assert r.status_code == 200


# ── TC header P11 fields round-trip ──────────────────────────────────────────


def test_tc_header_p11_fields_roundtrip(client, auth_headers):
    h = auth_headers
    tc = _make_tc(
        client,
        h,
        beneficiary="Owner SA",
        company_code="MOS",
        trade_area="APAC",
        contract_form="NYPE 2015",
        duration_min_days=60,
        duration_max_days=90,
        duration_minus_days=15,
        duration_plus_days=15,
        billing_period="EVERY 15 DAYS",
        billing_schedule="IN ADVANCE",
        intercompany=True,
        ic_company="MOS HK",
        owner_comm_pct=1.5,
        remarks="header parity",
    )
    detail = client.get(f"/api/v1/tc/contracts/{tc['id']}", headers=h).json()
    assert detail["beneficiary"] == "Owner SA"
    assert detail["company_code"] == "MOS"
    assert detail["duration_min_days"] == 60
    assert detail["duration_plus_days"] == 15
    assert detail["billing_schedule"] == "IN ADVANCE"
    assert detail["intercompany"] is True
    assert detail["owner_comm_pct"] == 1.5

    r = client.patch(
        f"/api/v1/tc/contracts/{tc['id']}",
        headers=h,
        json={"beneficiary": "Owner Ltd", "remarks": "patched"},
    )
    assert r.status_code == 200
    assert r.json()["beneficiary"] == "Owner Ltd"
    assert r.json()["remarks"] == "patched"


# ── Fixture No. + charter header fields ──────────────────────────────────────


def test_fixture_no_autogen(client, auth_headers):
    h = auth_headers
    c1 = _make_charter(client, h)
    assert c1["fixture_no"], "fixture_no must be auto-assigned"
    year = datetime.now().year
    assert c1["fixture_no"].startswith(str(year))
    assert len(c1["fixture_no"]) == 8  # YYYYNNNN

    c2 = _make_charter(client, h)
    assert c2["fixture_no"] != c1["fixture_no"]
    assert int(c2["fixture_no"][4:]) == int(c1["fixture_no"][4:]) + 1


def test_fixture_header_p11_fields(client, auth_headers):
    h = auth_headers
    vessels = _items(client.get("/api/v1/masterdata/vessels", headers=h).json())
    c = _make_charter(
        client,
        h,
        voyage_no="V26001",
        opr_type="TCOV",
        performing_vessel_id=vessels[0]["id"],
        chtr_specialist="Alice",
        ops_coordinator="Bob",
        ballast_bonus=25000,
        ls_only=True,
        piracy_routing="avoid",
        dwf_pct=12.5,
        company_code="MOS",
        lob="BULK",
        trade_area="APAC",
    )
    assert c["fixture_no"]
    assert c["voyage_no"] == "V26001"
    assert c["opr_type"] == "TCOV"
    assert c["ls_only"] is True
    assert c["piracy_routing"] == "avoid"
    assert c["dwf_pct"] == 12.5
    assert c["lob"] == "BULK"

    r = client.patch(
        f"/api/v1/charters/{c['id']}",
        headers=h,
        json={"ops_coordinator": "Carol", "ls_only": False},
    )
    assert r.status_code == 200
    assert r.json()["ops_coordinator"] == "Carol"
    assert r.json()["ls_only"] is False


# ── Fixture itinerary calculator (rows + footer totals) ──────────────────────


def test_itinerary_rows_and_totals(client, auth_headers):
    h = auth_headers
    c = _make_charter(client, h)

    r = client.post(
        f"/api/v1/charters/{c['id']}/itinerary-rows",
        headers=h,
        json={
            "seq": 1,
            "port": "NEWCASTLE",
            "flag": "L",
            "cargo": "STEAM COAL",
            "ld_qty": 70000,
            "ld_rate": 15000,
            "terms": "12000 SHINC",
            "port_days": 5.5,
            "port_exp": 42000,
        },
    )
    assert r.status_code == 201, r.text

    r = client.post(
        f"/api/v1/charters/{c['id']}/itinerary-rows",
        headers=h,
        json={
            "seq": 2,
            "port": "HAI PHONG",
            "flag": "D",
            "miles": 3800,
            "speed": 12.5,
            "sea_days": 12.6667,
            "xsd": 0.5,
            "port_days": 4,
            "xpd": 8500,
            "port_exp": 31000,
            "liner_exp": 12000,
        },
    )
    assert r.status_code == 201

    payload = client.get(f"/api/v1/charters/{c['id']}/itinerary-rows", headers=h).json()
    assert len(payload["items"]) == 2
    totals = payload["totals"]
    assert totals["miles"] == 3800
    assert totals["sea_days"] == pytest.approx(12.6667)
    assert totals["port_days"] == 9.5
    assert totals["port_exp"] == 73000
    assert totals["xpd"] == 8500
    assert totals["liner_exp"] == 12000
    assert totals["rows"] == 2

    row_id = payload["items"][0]["id"]
    r = client.patch(
        f"/api/v1/charters/{c['id']}/itinerary-rows/{row_id}",
        headers=h,
        json={"port_days": 6},
    )
    assert r.status_code == 200
    assert r.json()["port_days"] == 6

    r = client.delete(f"/api/v1/charters/{c['id']}/itinerary-rows/{row_id}", headers=h)
    assert r.status_code == 200
    payload = client.get(f"/api/v1/charters/{c['id']}/itinerary-rows", headers=h).json()
    assert len(payload["items"]) == 1
    assert payload["totals"]["port_days"] == 4


# ── Cargo itinerary / options ────────────────────────────────────────────────


def _make_cargo(client, h, **overrides):
    body = {"commodity": "STEAM COAL", "qty": 70000, "qty_unit": "mt"}
    body.update(overrides)
    r = client.post("/api/v1/cargo", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_cargo_itinerary_crud(client, auth_headers):
    h = auth_headers
    cg = _make_cargo(client, h)

    r = client.post(
        f"/api/v1/cargo/{cg['id']}/itinerary",
        headers=h,
        json={
            "seq": 1,
            "flag": "L",
            "port_name": "NEWCASTLE",
            "berth": "CH4",
            "qty": 70000,
            "ld_rate": 15000,
            "terms": "12000 SHINC",
            "incoterms": "FOB",
            "port_exp": 42000,
            "draft": 12.8,
            "unit": "MT",
            "salinity": 1.025,
        },
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["flag"] == "L"
    assert row["salinity"] == 1.025
    assert row["berth"] == "CH4"

    rows = client.get(f"/api/v1/cargo/{cg['id']}/itinerary", headers=h).json()
    assert len(rows) == 1

    r = client.patch(
        f"/api/v1/cargo/{cg['id']}/itinerary/{rows[0]['id']}",
        headers=h,
        json={"berth": "CH5", "salinity": 1.02},
    )
    assert r.status_code == 200
    assert r.json()["berth"] == "CH5"

    r = client.delete(f"/api/v1/cargo/{cg['id']}/itinerary/{rows[0]['id']}", headers=h)
    assert r.status_code == 200


def test_cargo_options_crud(client, auth_headers):
    h = auth_headers
    cg = _make_cargo(client, h)

    r = client.post(
        f"/api/v1/cargo/{cg['id']}/options",
        headers=h,
        json={
            "kind": "load",
            "seq": 1,
            "port_area": "Newcastle (Port Waratah)",
            "ld_rate": 15000,
            "ru": "RWSD",
            "terms": "12000 SHINC",
            "tt_days": 2,
            "pexp": 12000,
            "draft": 12.8,
        },
    )
    assert r.status_code == 201, r.text

    r = client.post(
        f"/api/v1/cargo/{cg['id']}/options",
        headers=h,
        json={"kind": "disch", "seq": 1, "port_area": "Haiphong", "ld_rate": 8000},
    )
    assert r.status_code == 201

    all_rows = client.get(f"/api/v1/cargo/{cg['id']}/options", headers=h).json()
    assert len(all_rows) == 2
    load_rows = client.get(
        f"/api/v1/cargo/{cg['id']}/options", headers=h, params={"kind": "load"}
    ).json()
    assert len(load_rows) == 1
    assert load_rows[0]["port_area"].startswith("Newcastle")

    # invalid kind rejected
    r = client.post(
        f"/api/v1/cargo/{cg['id']}/options", headers=h, json={"kind": "bad", "seq": 1}
    )
    assert r.status_code == 422

    r = client.delete(
        f"/api/v1/cargo/{cg['id']}/options/{all_rows[0]['id']}", headers=h
    )
    assert r.status_code == 200


# ── Cargo P11 header/payment/laycan fields ───────────────────────────────────


def test_cargo_p11_fields_roundtrip(client, auth_headers):
    h = auth_headers
    cg = _make_cargo(
        client,
        h,
        cp_form="GENCON",
        option_pct=10,
        option_type="MOLOO",
        min_qty=65000,
        max_qty=75000,
        freight_type="F",
        currency="USD",
        cp_draft_m=12.8,
        coordinator="Dave",
        booking_no="BK-001",
        company_code="MOS",
        laycan_confirmed=True,
        remittance_bank="HSBC HK 1234",
        invoice_pct=30,
        balance_pct=70,
        payment_terms_code="NET30",
        payment_terms_desc="30 days from BL date",
    )
    detail = client.get(f"/api/v1/cargo/{cg['id']}", headers=h).json()
    assert detail["cp_form"] == "GENCON"
    assert detail["option_type"] == "MOLOO"
    assert detail["min_qty"] == 65000
    assert detail["max_qty"] == 75000
    assert detail["laycan_confirmed"] is True
    assert detail["payment_terms_code"] == "NET30"
    assert detail["invoice_pct"] == 30
    assert detail["remittance_bank"].startswith("HSBC")

    r = client.patch(
        f"/api/v1/cargo/{cg['id']}",
        headers=h,
        json={"payment_terms_code": "NET45", "laycan_confirmed": False},
    )
    assert r.status_code == 200
    assert r.json()["payment_terms_code"] == "NET45"
    assert r.json()["laycan_confirmed"] is False


# ── Open positions ───────────────────────────────────────────────────────────


def test_open_positions_includes_tc_and_voyage(client, auth_headers):
    h = auth_headers
    # active TC In → tc_open row keyed on redelivery date
    tc = _make_tc(client, h, contract_type="tci")
    r = client.post(f"/api/v1/tc/contracts/{tc['id']}/transition", headers=h, params={"target": "active"})
    assert r.status_code == 200, r.text

    # open voyage fixture → voyage_fix row keyed on laycan_to
    c = _make_charter(client, h, charter_type="voyage", laycan_from="2026-04-01", laycan_to="2026-04-10")

    payload = client.get("/api/v1/chartering/open-positions", headers=h).json()
    kinds = {r["kind"] for r in payload["items"]}
    assert "tc_open" in kinds
    assert "voyage_fix" in kinds

    tc_rows = [r for r in payload["items"] if r["kind"] == "tc_open"]
    assert any(r["id"] == tc["id"] for r in tc_rows)
    match = next(r for r in tc_rows if r["id"] == tc["id"])
    assert match["tc_code"] == tc["tc_code"]
    assert match["vessel_name"]
    assert match["open_date"]  # redelivery date

    voy_rows = [r for r in payload["items"] if r["kind"] == "voyage_fix"]
    assert any(r["id"] == c["id"] for r in voy_rows)
    vmatch = next(r for r in voy_rows if r["id"] == c["id"])
    assert vmatch["fixture_no"] == c["fixture_no"]
    assert vmatch["open_date"] == "2026-04-10"

    # date filter excludes the April fixture
    payload = client.get(
        "/api/v1/chartering/open-positions",
        headers=h,
        params={"date_from": "2026-05-01", "date_to": "2026-12-31"},
    ).json()
    assert all(r["id"] != c["id"] for r in payload["items"])
