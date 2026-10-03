"""Phase 4 rate tables: CRUD, specificity lookup, validity window, freight
matrix, pricing templates, tenant isolation, estimate-engine integration."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import create_tenant

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db):
    from app.models_wave1 import Company

    return db.scalar(select(Company).limit(1)).tenant_id


def _make_table(client, h, name="Test rates", kind="freight_matrix", **kw):
    r = client.post(f"{API}/rates/tables", headers=h, json={"name": name, "kind": kind, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _add_row(client, h, table_id, dims, value, **kw):
    r = client.post(
        f"{API}/rates/tables/{table_id}/rows",
        headers=h,
        json={"dims": dims, "value": value, **kw},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _resolve(client, h, table_id, dims, as_of=None):
    body = {"dims": dims}
    if as_of is not None:
        body["as_of"] = as_of
    r = client.post(f"{API}/rates/tables/{table_id}/resolve", headers=h, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# —— CRUD ——


def test_rate_table_crud(client, auth_headers):
    h = auth_headers
    t = _make_table(client, h, name="Freight 2026 Q1", kind="freight_matrix", currency="usd", description="demo matrix")
    assert t["kind"] == "freight_matrix"
    assert t["currency"] == "USD"

    # list (paginated envelope) + filter
    r = client.get(f"{API}/rates/tables?kind=freight_matrix", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"items", "total", "limit", "offset"}
    assert any(x["id"] == t["id"] for x in body["items"])

    # detail + row add/update/delete
    r = client.get(f"{API}/rates/tables/{t['id']}", headers=h)
    assert r.status_code == 200 and r.json()["row_count"] == 0

    row = _add_row(client, h, t["id"], {"load_port": "CNSHA", "disch_port": "SGSIN"}, 15.5, unit="per_mt", priority=1)
    assert row["value"] == 15.5
    r = client.get(f"{API}/rates/tables/{t['id']}", headers=h)
    assert r.json()["row_count"] == 1

    r = client.patch(
        f"{API}/rates/tables/{t['id']}/rows/{row['id']}",
        headers=h,
        json={"value": 16.25, "priority": 2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == 16.25 and r.json()["priority"] == 2

    # upsert: same dims updates in place
    again = _add_row(client, h, t["id"], {"load_port": "CNSHA", "disch_port": "SGSIN"}, 17.0)
    assert again["id"] == row["id"]
    r = client.get(f"{API}/rates/tables/{t['id']}", headers=h)
    assert r.json()["row_count"] == 1

    r = client.delete(f"{API}/rates/tables/{t['id']}/rows/{row['id']}", headers=h)
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.get(f"{API}/rates/tables/{t['id']}/rows", headers=h)
    assert r.json()["total"] == 0

    # table update + soft delete (recycle)
    r = client.patch(f"{API}/rates/tables/{t['id']}", headers=h, json={"name": "Freight 2026 Q1b", "is_active": False})
    assert r.status_code == 200 and r.json()["name"] == "Freight 2026 Q1b" and r.json()["is_active"] is False

    r = client.delete(f"{API}/rates/tables/{t['id']}", headers=h)
    assert r.status_code == 200 and r.json().get("recycled") is True
    assert client.get(f"{API}/rates/tables/{t['id']}", headers=h).status_code == 404
    body = client.get(f"{API}/rates/tables", headers=h).json()
    assert all(x["id"] != t["id"] for x in body["items"])


def test_rate_table_invalid_kind_rejected(client, auth_headers):
    r = client.post(f"{API}/rates/tables", headers=auth_headers, json={"name": "bad", "kind": "spot_charter"})
    assert r.status_code == 422


# —— lookup specificity ——


def test_rate_row_lookup_specificity(client, auth_headers):
    h = auth_headers
    t = _make_table(client, h, name="Specificity")
    _add_row(client, h, t["id"], {}, 10.0)  # catch-all
    _add_row(client, h, t["id"], {"cargo_type": "coal"}, 12.0)
    _add_row(client, h, t["id"], {"load_port": "CNSHA"}, 13.0)
    _add_row(client, h, t["id"], {"load_port": "CNSHA", "cargo_type": "coal"}, 15.0)

    # most matching dims wins
    assert _resolve(client, h, t["id"], {"load_port": "CNSHA", "cargo_type": "coal"})["value"] == 15.0
    # degrading specificity cascade
    assert _resolve(client, h, t["id"], {"load_port": "CNSHA", "cargo_type": "iron"})["value"] == 13.0
    assert _resolve(client, h, t["id"], {"load_port": "SGSIN", "cargo_type": "coal"})["value"] == 12.0
    assert _resolve(client, h, t["id"], {"load_port": "SGSIN", "cargo_type": "iron"})["value"] == 10.0
    assert _resolve(client, h, t["id"], {})["value"] == 10.0
    # no match at all (table has only specific rows) → matched False
    t2 = _make_table(client, h, name="No fallback")
    _add_row(client, h, t2["id"], {"load_port": "CNSHA"}, 9.0)
    out = _resolve(client, h, t2["id"], {"load_port": "SGSIN"})
    assert out["matched"] is False and out["value"] is None


def test_rate_row_priority_breaks_specificity_tie(client, auth_headers):
    h = auth_headers
    t = _make_table(client, h, name="Priority tie")
    _add_row(client, h, t["id"], {"load_port": "CNSHA"}, 13.0, priority=0)
    _add_row(client, h, t["id"], {"disch_port": "SGSIN"}, 14.0, priority=5)
    out = _resolve(client, h, t["id"], {"load_port": "CNSHA", "disch_port": "SGSIN"})
    assert out["value"] == 14.0  # same specificity (1), higher priority wins
    assert _resolve(client, h, t["id"], {"load_port": "CNSHA"})["value"] == 13.0


# —— validity window ——


def test_valid_from_to_date_filtering(client, auth_headers):
    h = auth_headers
    today = date.today()
    future = (today + timedelta(days=30)).isoformat()
    past = (today - timedelta(days=30)).isoformat()

    t_fut = _make_table(client, h, name="Future table", valid_from=future)
    _add_row(client, h, t_fut["id"], {"load_port": "CNSHA"}, 21.0)

    t_past = _make_table(client, h, name="Expired table", valid_from=past, valid_to=(today - timedelta(days=1)).isoformat())
    _add_row(client, h, t_past["id"], {"load_port": "CNSHA"}, 22.0)

    t_ok = _make_table(client, h, name="Current table", valid_from=past, valid_to=future)
    _add_row(client, h, t_ok["id"], {"load_port": "CNSHA"}, 23.0)

    dims = {"load_port": "CNSHA"}
    # not yet in effect / expired → no match today
    assert _resolve(client, h, t_fut["id"], dims)["matched"] is False
    assert _resolve(client, h, t_past["id"], dims)["matched"] is False
    assert _resolve(client, h, t_ok["id"], dims)["value"] == 23.0

    # as_of moves the window
    assert _resolve(client, h, t_fut["id"], dims, as_of=future)["value"] == 21.0
    assert _resolve(client, h, t_past["id"], dims, as_of=past)["value"] == 22.0
    assert _resolve(client, h, t_ok["id"], dims, as_of=future)["matched"] is True  # valid_to is that day inclusive


# —— freight matrix (service-level 2-D) ——


def test_freight_matrix_2d_lookup(db_session, client, auth_headers):
    from app.services.rates import freight_matrix_lookup

    h = auth_headers
    t = _make_table(client, h, name="Freight matrix 2D")
    _add_row(client, h, t["id"], {"load_port": "CNSHA", "disch_port": "SGSIN"}, 18.5, unit="per_mt")
    _add_row(client, h, t["id"], {"load_port": "CNSHA", "disch_port": "JPTYO"}, 12.0, unit="per_mt")
    _add_row(client, h, t["id"], {"load_port": "CNSHA"}, 15.0, unit="per_mt")  # load-port fallback

    tid = _tenant_id(db_session)
    table_id = t["id"]
    assert freight_matrix_lookup(db_session, tid, table_id, "CNSHA", "SGSIN") == 18.5
    assert freight_matrix_lookup(db_session, tid, table_id, "CNSHA", "JPTYO") == 12.0
    assert freight_matrix_lookup(db_session, tid, table_id, "CNSHA", "NLRTM") == 15.0  # fallback
    assert freight_matrix_lookup(db_session, tid, table_id, "SGSIN", "JPTYO") is None


# —— pricing templates ——


def test_pricing_template_resolution(client, auth_headers):
    h = auth_headers
    freight = _make_table(client, h, name="T freight", kind="freight_matrix")
    _add_row(client, h, freight["id"], {"load_port": "CNSHA", "disch_port": "SGSIN"}, 20.0, unit="per_mt")
    surcharge = _make_table(client, h, name="T surcharge", kind="surcharge")
    _add_row(client, h, surcharge["id"], {"route": "CNSHA-SGSIN"}, 1.5, unit="per_mt")
    demurrage = _make_table(client, h, name="T demurrage", kind="demurrage_rate")
    _add_row(client, h, demurrage["id"], {}, 15000.0, unit="per_day")

    r = client.post(
        f"{API}/rates/templates",
        headers=h,
        json={
            "name": "Coal East",
            "rate_table_refs": {"freight": freight["id"], "surcharge": surcharge["id"], "demurrage": demurrage["id"]},
            "rules": {"min_freight_usd": 100000},
        },
    )
    assert r.status_code == 200, r.text
    tpl = r.json()
    assert set(tpl["rate_table_refs"]) == {"freight", "surcharge", "demurrage"}

    r = client.post(
        f"{API}/rates/templates/{tpl['id']}/resolve",
        headers=h,
        json={
            "load_port": "CNSHA",
            "disch_port": "SGSIN",
            "route": "CNSHA-SGSIN",
            "cargo_qty": 50000,
            "demurrage_days": 2,
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["rates"]["freight"]["rate"] == 20.0
    assert out["rates"]["surcharge"]["rate"] == 1.5
    assert out["rates"]["demurrage"]["rate"] == 15000.0
    assert out["amounts"]["freight"] == 1000000.0  # 20 × 50000
    assert out["amounts"]["surcharge"] == 75000.0  # 1.5 × 50000
    assert out["amounts"]["demurrage"] == 30000.0  # 15000 × 2
    assert out["rules"] == {"min_freight_usd": 100000}

    # template with unknown/foreign table ref rejected at create time
    r = client.post(
        f"{API}/rates/templates",
        headers=h,
        json={"name": "Bad ref", "rate_table_refs": {"freight": "00000000-0000-0000-0000-00000000dead"}},
    )
    assert r.status_code == 404


# —— validation ——


def test_validate_rate_table_reports_gaps_and_conflicts(client, auth_headers):
    h = auth_headers
    t = _make_table(client, h, name="Messy")
    _add_row(client, h, t["id"], {"load_port": "CNSHA"}, 10.0)
    _add_row(client, h, t["id"], {"load_port": "CNSHA"}, 11.0)  # upsert overwrites same dims — no dup
    _add_row(client, h, t["id"], {"disch_port": "SGSIN"}, 12.0, priority=1)
    r = client.get(f"{API}/rates/tables/{t['id']}/validate", headers=h)
    assert r.status_code == 200, r.text
    issues = r.json()["issues"]
    # two specific rows, no catch-all → gap reported; no duplicate signatures
    assert any("catch-all" in i for i in issues)
    assert not any("duplicate rows" in i for i in issues)

    clean = _make_table(client, h, name="Clean")
    _add_row(client, h, clean["id"], {}, 5.0)
    _add_row(client, h, clean["id"], {"load_port": "CNSHA", "disch_port": "SGSIN"}, 9.0)
    issues = client.get(f"{API}/rates/tables/{clean['id']}/validate", headers=h).json()["issues"]
    assert issues == []


# —— tenant isolation ——


def test_tenant_isolation(client, auth_headers):
    h = auth_headers
    t = _make_table(client, h, name="Demo-only rates")
    row = _add_row(client, h, t["id"], {"load_port": "CNSHA"}, 11.0)

    _, other_h = create_tenant(client, code="othrates", name="Other Rates Co", admin_email="other-rates@example.com")

    assert client.get(f"{API}/rates/tables/{t['id']}", headers=other_h).status_code == 404
    assert client.patch(f"{API}/rates/tables/{t['id']}", headers=other_h, json={"name": "x"}).status_code == 404
    assert client.post(f"{API}/rates/tables/{t['id']}/rows", headers=other_h, json={"dims": {}, "value": 1.0}).status_code == 404
    assert client.patch(f"{API}/rates/tables/{t['id']}/rows/{row['id']}", headers=other_h, json={"value": 1.0}).status_code == 404
    assert client.delete(f"{API}/rates/tables/{t['id']}/rows/{row['id']}", headers=other_h).status_code == 404
    assert client.delete(f"{API}/rates/tables/{t['id']}", headers=other_h).status_code == 404
    r = client.post(f"{API}/rates/tables/{t['id']}/resolve", headers=other_h, json={"dims": {"load_port": "CNSHA"}})
    assert r.status_code == 404

    listed = client.get(f"{API}/rates/tables", headers=other_h).json()
    assert all(x["id"] != t["id"] for x in listed["items"])


# —— estimate engine integration ——


def test_estimate_engine_rate_table_drives_freight(db_session, client, auth_headers):
    from app.services.estimate_engine import compute_estimate

    h = auth_headers
    t = _make_table(client, h, name="Est freight", kind="freight_matrix")
    _add_row(client, h, t["id"], {"load_port": "CNSHA", "disch_port": "SGSIN"}, 20.0, unit="per_mt")

    out = compute_estimate(
        {
            "cargo_qty": 50000,
            "load_port": "CNSHA",
            "disch_port": "SGSIN",
            "freight_rate_table_id": t["id"],
            "sea_days": 10,
            "port_days": 5,
        },
        db=db_session,
        tenant_id=_tenant_id(db_session),
    )
    assert out["gross_freight"] == 1000000.0
    assert out["freight_basis"] == "rate"
    assert out["rate_table_rates"]["freight_rate"] == 20.0

    # backward compatibility: direct rate wins when provided
    out2 = compute_estimate(
        {
            "cargo_qty": 50000,
            "freight_rate": 25.0,
            "load_port": "CNSHA",
            "disch_port": "SGSIN",
            "freight_rate_table_id": t["id"],
            "sea_days": 10,
        },
        db=db_session,
        tenant_id=_tenant_id(db_session),
    )
    assert out2["gross_freight"] == 1250000.0
    # direct rate won → table contributed nothing → no provenance block
    assert "rate_table_rates" not in out2

    # without table ids nothing changes (gold path untouched)
    out3 = compute_estimate({"cargo_qty": 50000, "freight_rate": 25.0, "sea_days": 10})
    assert out3["gross_freight"] == 1250000.0
    assert "rate_table_rates" not in out3


def test_estimate_engine_demurrage_and_surcharge(db_session, client, auth_headers):
    from app.services.estimate_engine import compute_estimate

    h = auth_headers
    dem = _make_table(client, h, name="Est demurrage", kind="demurrage_rate")
    _add_row(client, h, dem["id"], {}, 15000.0, unit="per_day")
    sur = _make_table(client, h, name="Est surcharge", kind="surcharge")
    _add_row(client, h, sur["id"], {"cargo_type": "coal"}, 1.5, unit="per_mt")

    out = compute_estimate(
        {
            "cargo_qty": 50000,
            "cargo_type": "coal",
            "demurrage_rate_table_id": dem["id"],
            "demurrage_days": 2,
            "surcharge_rate_table_id": sur["id"],
            "sea_days": 10,
        },
        db=db_session,
        tenant_id=_tenant_id(db_session),
    )
    assert out["rate_table_rates"]["demurrage_income"] == 30000.0
    assert out["rate_table_rates"]["surcharge_income"] == 75000.0
    # revenue = net_freight (0) + demurrage + other + surcharge
    assert out["total_revenue"] == 105000.0

    # direct demurrage_income wins (backward compat)
    out2 = compute_estimate(
        {
            "cargo_qty": 50000,
            "demurrage_income": 999.0,
            "demurrage_rate_table_id": dem["id"],
            "demurrage_days": 2,
            "sea_days": 10,
        },
        db=db_session,
        tenant_id=_tenant_id(db_session),
    )
    assert "rate_table_rates" not in out2  # direct demurrage_income won
    assert out2["total_revenue"] == 999.0


def test_estimate_calculate_endpoint_uses_rate_table(client, auth_headers):
    h = auth_headers
    t = _make_table(client, h, name="API freight", kind="freight_matrix")
    _add_row(client, h, t["id"], {"load_port": "CNSHA", "disch_port": "SGSIN"}, 18.0, unit="per_mt")

    r = client.post(
        f"{API}/estimates",
        headers=h,
        json={
            "title": "Rate table estimate",
            "mode": "voyage",
            "inputs": {
                "cargo_qty": 10000,
                "load_port": "CNSHA",
                "disch_port": "SGSIN",
                "freight_rate_table_id": t["id"],
                "sea_days": 5,
                "port_days": 2,
            },
        },
    )
    assert r.status_code == 200, r.text
    est_id = r.json()["id"]

    r = client.post(f"{API}/estimates/{est_id}/calculate", headers=h)
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert results["gross_freight"] == 180000.0
    assert results["rate_table_rates"]["freight_rate"] == 18.0
