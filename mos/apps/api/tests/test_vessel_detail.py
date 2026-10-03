"""Vessel detail APIs — 船舶明细：CRUD、max-lift、汇总、租户隔离。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import assert_blocked, create_tenant

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


@pytest.fixture()
def vessel_id(client, auth_headers):
    r = client.post(
        f"{API}/masterdata/vessels",
        headers=auth_headers,
        json={"name": "MV Vessel Detail", "imo": "9001234", "dwt": 50000},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ─────────────────────────────────────────────────────────────────────
# CRUD matrix — one row per new vessel-card resource
# ─────────────────────────────────────────────────────────────────────

CRUD_CASES = [
    (
        "contacts",
        {"contact_role": "captain", "name": "Cap. Test", "email": "capt@example.com", "phone": "+86 1000"},
        {"name": "Cap. Updated", "contact_role": "superintendent"},
        "name",
    ),
    (
        "routes",
        {
            "route_name": "CNSHA-ROTTEM",
            "from_area": "Far East",
            "to_area": "Continent",
            "typical_speed": 13.5,
            "distance_nm": 10500,
        },
        {"typical_speed": 14.0, "notes": "slow steam option"},
        "route_name",
    ),
    (
        "tugs",
        {"tug_name": "TUG ALPHA", "power_hp": 4000, "notes": "2 tugs required"},
        {"power_hp": 5000},
        "tug_name",
    ),
    (
        "tanks",
        {"tank_name": "NO.1 FOT", "tank_type": "fuel", "capacity_mt": 1200.5, "max_fill_pct": 95},
        {"capacity_mt": 1250, "tank_type": "ballast"},
        "tank_name",
    ),
    (
        "performance",
        {"cargo_type": "coal", "load_rate_mt_hr": 1500, "discharge_rate_mt_hr": 1200, "stowage_factor": 1.25},
        {"load_rate_mt_hr": 1600},
        "cargo_type",
    ),
    (
        "tce-targets",
        {"year_month": "2026-10", "target_tce_usd": 25000, "notes": "budget"},
        {"target_tce_usd": 26500},
        "year_month",
    ),
    (
        "vettings",
        {
            "vetting_type": "sire",
            "vetting_date": "2026-05-01",
            "result": "pass",
            "expiry_date": "2027-05-01",
            "inspector": "OCIMF Insp",
        },
        {"result": "conditional"},
        "vetting_type",
    ),
    (
        "loadline-zones",
        {"zone_name": "summer", "max_draft_m": 12.2, "valid_from": "2026-01-01"},
        {"max_draft_m": 12.35, "zone_name": "tropical"},
        "zone_name",
    ),
]


@pytest.mark.parametrize("path,create_body,patch_body,check_field", CRUD_CASES)
def test_child_resource_crud(client, auth_headers, vessel_id, path, create_body, patch_body, check_field):
    h = auth_headers
    base = f"{API}/vessels/{vessel_id}/{path}"

    # create
    r = client.post(base, headers=h, json=create_body)
    assert r.status_code == 200, r.text
    row = r.json()
    row_id = row["id"]
    assert row["vessel_id"] == vessel_id
    assert row[check_field] == create_body[check_field]

    # list
    r = client.get(base, headers=h)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(x["id"] == row_id for x in rows), rows

    # patch
    r = client.patch(f"{base}/{row_id}", headers=h, json=patch_body)
    assert r.status_code == 200, r.text
    upd = r.json()
    for k, v in patch_body.items():
        assert upd[k] == v, (k, upd[k], v)

    # delete
    r = client.delete(f"{base}/{row_id}", headers=h)
    assert r.status_code == 200, r.text
    r = client.get(base, headers=h)
    assert all(x["id"] != row_id for x in r.json())


def test_child_row_404_on_foreign_vessel(client, auth_headers, vessel_id):
    """A row id from another vessel must not be patchable through this vessel's path."""
    h = auth_headers
    other = client.post(f"{API}/masterdata/vessels", headers=h, json={"name": "MV Other"}).json()["id"]
    contact = client.post(
        f"{API}/vessels/{other}/contacts", headers=h, json={"name": "Cap. Foreign"}
    ).json()

    r = client.patch(f"{API}/vessels/{vessel_id}/contacts/{contact['id']}", headers=h, json={"name": "X"})
    assert r.status_code == 404, r.text
    r = client.delete(f"{API}/vessels/{vessel_id}/contacts/{contact['id']}", headers=h)
    assert r.status_code == 404, r.text


# ─────────────────────────────────────────────────────────────────────
# DWT / draft spec block
# ─────────────────────────────────────────────────────────────────────


def test_dwt_draft_get_patch(client, auth_headers, vessel_id):
    h = auth_headers
    url = f"{API}/vessels/{vessel_id}/dwt-draft"

    r = client.get(url, headers=h)
    assert r.status_code == 200, r.text
    spec = r.json()
    assert spec["vessel_id"] == vessel_id
    assert set(spec) == {"vessel_id", "dwt_draft", "vessel_type_detail", "consumption_detail", "capacity"}

    r = client.patch(
        url,
        headers=h,
        json={
            "summer_dwt": 52000,
            "tropical_dwt": 53500,
            "winter_dwt": 50500,
            "summer_draft": 12.2,
            "tropical_draft": 12.45,
            "winter_draft": 11.9,
            "lightship": 9800,
            "deadweight_scale": [
                {"draft_m": 8.0, "deadweight_mt": 30000},
                {"draft_m": 12.2, "deadweight_mt": 52000},
            ],
            "hull_type": "double hull",
            "build_year": 2015,
            "build_yard": "Shanghai Waigaoqiao",
            "flag_state": "HK",
            "ism_manager": "Demo Shipmanagement",
            "isps_manager": "Demo Shipmanagement",
            "sea_speed_25": 11.5,
            "sea_speed_75": 13.0,
            "sea_speed_100": 14.2,
            "port_working": 22.0,
            "port_idle": 8.5,
            "port_maneuvering": 12.0,
            "ifo_mdo_ratio": 0.95,
            "max_lift_qty": 50000,
            "stowage_factor": 1.2,
            "design_speed": 14.5,
            "tank_capacity_total": 1800,
        },
    )
    assert r.status_code == 200, r.text
    spec = r.json()
    assert spec["dwt_draft"]["summer_dwt"] == 52000
    assert spec["dwt_draft"]["deadweight_scale"][1]["deadweight_mt"] == 52000
    assert spec["vessel_type_detail"]["build_year"] == 2015
    assert spec["consumption_detail"]["port_idle"] == 8.5
    assert spec["capacity"]["stowage_factor"] == 1.2

    # partial patch touches only provided fields
    r = client.patch(url, headers=h, json={"summer_dwt": 52100})
    assert r.status_code == 200, r.text
    spec = r.json()
    assert spec["dwt_draft"]["summer_dwt"] == 52100
    assert spec["capacity"]["stowage_factor"] == 1.2  # untouched

    r = client.get(url, headers=h)
    assert r.json()["dwt_draft"]["summer_dwt"] == 52100


def test_dwt_draft_404_missing_vessel(client, auth_headers):
    r = client.get(f"{API}/vessels/{uuid4()}/dwt-draft", headers=auth_headers)
    assert r.status_code == 404, r.text


# ─────────────────────────────────────────────────────────────────────
# Max lift calculation
# ─────────────────────────────────────────────────────────────────────


def test_max_lift_draft_limited(client, auth_headers, vessel_id):
    h = auth_headers
    client.patch(
        f"{API}/vessels/{vessel_id}/dwt-draft",
        headers=h,
        json={
            "summer_dwt": 50000,
            "summer_draft": 12.0,
            "max_lift_qty": 45000,
            "stowage_factor": 1.2,
            "deadweight_scale": [
                {"draft_m": 8.0, "deadweight_mt": 30000},
                {"draft_m": 12.0, "deadweight_mt": 50000},
            ],
        },
    )
    r = client.get(
        f"{API}/vessels/{vessel_id}/max-lift",
        headers=h,
        params={"draft": 10.0, "bunkers_mt": 2000, "stores_mt": 100, "fresh_water_mt": 300, "hold_capacity_cbm": 48000},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_dwt_mt"] == 50000
    assert body["available_deadweight_mt"] == 47600  # 50000 − 2400
    # scale interpolation at 10m: 30000 + 20000×(2/4) = 40000 → minus consumables
    assert body["draft_limited_deadweight_mt"] == 37600
    assert body["hold_volume_limit_mt"] == 40000  # 48000 / 1.2
    assert body["gear_limit_mt"] == 45000
    assert body["max_lift_mt"] == 37600
    assert body["limiting_factor"] == "draft"
    assert body["cargo_volume_cbm"] == pytest.approx(37600 * 1.2)


def test_max_lift_hold_volume_limited(client, auth_headers, vessel_id):
    h = auth_headers
    client.patch(
        f"{API}/vessels/{vessel_id}/dwt-draft",
        headers=h,
        json={"summer_dwt": 50000, "summer_draft": 12.0, "max_lift_qty": 45000, "stowage_factor": 1.2},
    )
    r = client.get(
        f"{API}/vessels/{vessel_id}/max-lift",
        headers=h,
        params={"hold_capacity_cbm": 48000, "bunkers_mt": 2400},
    )
    body = r.json()
    assert body["draft_limited_deadweight_mt"] is None
    assert body["max_lift_mt"] == 40000  # hold volume binds before gear 45000 / DWT 47600
    assert body["limiting_factor"] == "hold_volume"


def test_max_lift_deadweight_limited_without_scale(client, auth_headers, vessel_id):
    h = auth_headers
    client.patch(
        f"{API}/vessels/{vessel_id}/dwt-draft",
        headers=h,
        json={"summer_dwt": 50000, "summer_draft": 12.0},
    )
    r = client.get(
        f"{API}/vessels/{vessel_id}/max-lift",
        headers=h,
        params={"draft": 6.0, "bunkers_mt": 2000, "stores_mt": 400},
    )
    body = r.json()
    # no scale → linear from summer draft: 50000 × 6/12 = 25000 − 2400
    assert body["draft_limited_deadweight_mt"] == 22600
    assert body["max_lift_mt"] == 22600
    assert body["limiting_factor"] == "draft"


def test_max_lift_uses_performance_stowage(client, auth_headers, vessel_id):
    h = auth_headers
    client.patch(
        f"{API}/vessels/{vessel_id}/dwt-draft",
        headers=h,
        json={"summer_dwt": 50000, "stowage_factor": 2.0},
    )
    client.post(
        f"{API}/vessels/{vessel_id}/performance",
        headers=h,
        json={"cargo_type": "coal", "stowage_factor": 1.25, "load_rate_mt_hr": 1500},
    )
    r = client.get(
        f"{API}/vessels/{vessel_id}/max-lift",
        headers=h,
        params={"cargo_type": "coal", "hold_capacity_cbm": 50000},
    )
    body = r.json()
    assert body["inputs"]["stowage_factor"] == 1.25  # cargo profile wins over vessel default
    assert body["max_lift_mt"] == 40000  # 50000 / 1.25


def test_max_lift_loadline_zone_clamp(client, auth_headers, vessel_id):
    h = auth_headers
    client.patch(
        f"{API}/vessels/{vessel_id}/dwt-draft",
        headers=h,
        json={
            "summer_dwt": 50000,
            "summer_draft": 12.0,
            "deadweight_scale": [{"draft_m": 12.0, "deadweight_mt": 50000}],
        },
    )
    client.post(
        f"{API}/vessels/{vessel_id}/loadline-zones",
        headers=h,
        json={"zone_name": "winter", "max_draft_m": 11.5},
    )
    r = client.get(
        f"{API}/vessels/{vessel_id}/max-lift",
        headers=h,
        params={"draft": 13.0, "bunkers_mt": 0},
    )
    body = r.json()
    assert body["inputs"]["draft_m"] == 11.5  # clamped to deepest zone
    assert body["warnings"], body
    assert body["draft_limited_deadweight_mt"] == 50000  # scale saturates at 12m end


def test_max_lift_requires_dwt(client, auth_headers):
    v = client.post(f"{API}/masterdata/vessels", headers=auth_headers, json={"name": "MV No DWT"}).json()
    r = client.get(f"{API}/vessels/{v['id']}/max-lift", headers=auth_headers)
    assert r.status_code == 422, r.text


# ─────────────────────────────────────────────────────────────────────
# Summary aggregation
# ─────────────────────────────────────────────────────────────────────


def test_summary_aggregates_all_tabs(client, auth_headers, vessel_id):
    h = auth_headers
    client.patch(f"{API}/vessels/{vessel_id}/dwt-draft", headers=h, json={"summer_dwt": 52000, "build_year": 2018})
    client.post(f"{API}/vessels/{vessel_id}/contacts", headers=h, json={"name": "Cap. A", "contact_role": "captain"})
    client.post(f"{API}/vessels/{vessel_id}/contacts", headers=h, json={"name": "Supt. B", "contact_role": "superintendent"})
    client.post(f"{API}/vessels/{vessel_id}/routes", headers=h, json={"route_name": "TPX"})
    client.post(f"{API}/vessels/{vessel_id}/tugs", headers=h, json={"tug_name": "TUG-1"})
    client.post(f"{API}/vessels/{vessel_id}/tanks", headers=h, json={"tank_name": "FOT-1"})
    client.post(f"{API}/vessels/{vessel_id}/performance", headers=h, json={"cargo_type": "coal"})
    client.post(f"{API}/vessels/{vessel_id}/tce-targets", headers=h, json={"year_month": "2026-11", "target_tce_usd": 20000})
    client.post(f"{API}/vessels/{vessel_id}/vettings", headers=h, json={"vetting_type": "psc", "result": "fail"})
    client.post(f"{API}/vessels/{vessel_id}/loadline-zones", headers=h, json={"zone_name": "winter"})

    r = client.get(f"{API}/vessels/{vessel_id}/summary", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["vessel"]["id"] == vessel_id
    assert body["vessel"]["name"] == "MV Vessel Detail"
    assert body["spec"]["dwt_draft"]["summer_dwt"] == 52000
    assert body["spec"]["vessel_type_detail"]["build_year"] == 2018
    assert body["counts"] == {
        "contacts": 2,
        "routes": 1,
        "tugs": 1,
        "tanks": 1,
        "performance": 1,
        "tce_targets": 1,
        "vettings": 1,
        "loadline_zones": 1,
    }
    assert len(body["contacts"]) == 2
    assert body["vettings"][0]["result"] == "fail"
    assert body["tce_targets"][0]["target_tce_usd"] == 20000
    assert body["tanks"][0]["tank_name"] == "FOT-1"


# ─────────────────────────────────────────────────────────────────────
# Tenant isolation
# ─────────────────────────────────────────────────────────────────────


def test_tenant_isolation(client, auth_headers):
    h_a = auth_headers
    _tid_b, h_b = create_tenant(client, code="viso", name="Vessel Iso", admin_email="viso.admin@example.com")

    # tenant B owns a vessel + child rows
    v_b = client.post(f"{API}/masterdata/vessels", headers=h_b, json={"name": "MV Tenant B"}).json()["id"]
    c_b = client.post(f"{API}/vessels/{v_b}/contacts", headers=h_b, json={"name": "Cap. B"}).json()
    client.patch(f"{API}/vessels/{v_b}/dwt-draft", headers=h_b, json={"summer_dwt": 30000})

    # tenant A owns its own vessel + row
    v_a = client.post(f"{API}/masterdata/vessels", headers=h_a, json={"name": "MV Tenant A"}).json()["id"]
    c_a = client.post(f"{API}/vessels/{v_a}/contacts", headers=h_a, json={"name": "Cap. A"}).json()

    # A cannot read or write B's vessel subtree
    assert_blocked(client.get(f"{API}/vessels/{v_b}/summary", headers=h_a), "summary foreign vessel")
    assert_blocked(client.get(f"{API}/vessels/{v_b}/dwt-draft", headers=h_a), "dwt-draft foreign vessel")
    assert_blocked(
        client.patch(f"{API}/vessels/{v_b}/dwt-draft", headers=h_a, json={"summer_dwt": 1}),
        "patch dwt-draft foreign vessel",
    )
    assert_blocked(client.get(f"{API}/vessels/{v_b}/contacts", headers=h_a), "list foreign contacts")
    assert_blocked(
        client.post(f"{API}/vessels/{v_b}/contacts", headers=h_a, json={"name": "X"}),
        "create contact on foreign vessel",
    )
    assert_blocked(
        client.patch(f"{API}/vessels/{v_b}/contacts/{c_b['id']}", headers=h_a, json={"name": "X"}),
        "patch foreign contact",
    )
    assert_blocked(client.delete(f"{API}/vessels/{v_b}/contacts/{c_b['id']}", headers=h_a), "delete foreign contact")
    assert_blocked(client.get(f"{API}/vessels/{v_b}/max-lift", headers=h_a), "max-lift foreign vessel")

    # A's list stays empty of B rows; B cannot reach A's row through A's vessel
    rows = client.get(f"{API}/vessels/{v_a}/contacts", headers=h_a).json()
    assert [x["id"] for x in rows] == [c_a["id"]]
    assert_blocked(
        client.patch(f"{API}/vessels/{v_a}/contacts/{c_b['id']}", headers=h_b, json={"name": "X"}),
        "cross vessel/tenant row",
    )
