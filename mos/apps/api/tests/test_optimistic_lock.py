"""D4/D8 乐观锁（optimistic lock）— concurrent-edit detection (409 STALE_WRITE).

Per entity (Invoice / Charter / Counterparty / Vessel):

- (a) no ``expected_updated_at`` → PATCH succeeds (back-compat)
- (b) ``expected_updated_at`` == current → PATCH succeeds
- (c) stale expected → 409 ``STALE_WRITE`` with ``current`` in detail
- (d) two-step: PATCH with expected from a fresh GET, then second PATCH with the
  same (now stale) expected → 409
- (e) tenant isolation unchanged (foreign PATCH → 404, not 409)
- first PATCH actually bumps ``updated_at`` (proves the stamp advances)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import sessionmaker

from app.models_domain import Charter, Invoice
from app.models_wave1 import Counterparty, Vessel
from app.services.optimistic_lock import assert_fresh
from tests.isolation_helpers import create_tenant

OLD_STAMP = datetime(2020, 1, 1, 0, 0, 0)


# ── helpers ──────────────────────────────────────────────────────────────────


def _age_updated_at(db_engine, model, entity_id: str) -> None:
    """Force row.updated_at to a known old value so the next PATCH is provably new."""
    from uuid import UUID

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        row = db.get(model, UUID(entity_id))
        assert row is not None, f"{model.__name__} {entity_id} not found"
        row.updated_at = OLD_STAMP
        db.commit()


def _iso(dt) -> str:
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


# ── unit: assert_fresh None / missing-data handling ──────────────────────────


def test_assert_fresh_permissive_on_missing_data():
    class NoStamp:
        pass

    class NullStamp:
        updated_at = None

    assert_fresh(NoStamp(), "2020-01-01T00:00:00")  # no attribute → skip
    assert_fresh(NullStamp(), "2020-01-01T00:00:00")  # NULL current → skip
    assert_fresh(NullStamp(), None)  # no expected → skip
    assert_fresh(NoStamp(), None)


# ── Invoice ──────────────────────────────────────────────────────────────────


def _make_invoice(client, h):
    r = client.post("/api/v1/invoices", headers=h, json={"amount": 100, "tax_amount": 0, "currency": "USD"})
    assert r.status_code == 200, r.text
    return r.json()


def _invoice_stamp(client, h, iid: str) -> str | None:
    return client.get(f"/api/v1/invoices/{iid}", headers=h).json()["updated_at"]


def test_invoice_optimistic_lock(client, auth_headers, db_engine):
    h = auth_headers
    inv = _make_invoice(client, h)
    iid = inv["id"]

    # (a) no expected → back-compat
    r = client.patch(f"/api/v1/invoices/{iid}", headers=h, json={"amount": 200})
    assert r.status_code == 200, r.text

    # age the stamp, then (b)/(d) two-step
    _age_updated_at(db_engine, Invoice, iid)
    u1 = _invoice_stamp(client, h, iid)
    assert u1 is not None, "GET must expose updated_at for the optimistic-lock token"

    ok = client.patch(f"/api/v1/invoices/{iid}", headers=h, json={"amount": 300, "expected_updated_at": u1})
    assert ok.status_code == 200, ok.text

    # first PATCH bumps updated_at (proves onupdate / stamp advances)
    u2 = _invoice_stamp(client, h, iid)
    assert u2 is not None and u2 != u1, f"updated_at must advance after PATCH: {u1} -> {u2}"

    # (d) second PATCH with the same (now stale) expected → 409
    stale = client.patch(f"/api/v1/invoices/{iid}", headers=h, json={"amount": 400, "expected_updated_at": u1})
    assert stale.status_code == 409, stale.text
    detail = stale.json()["detail"]
    assert detail["code"] == "STALE_WRITE"
    assert "current" in detail

    # (c) obviously-old expected → 409
    older = client.patch(
        f"/api/v1/invoices/{iid}",
        headers=h,
        json={"amount": 500, "expected_updated_at": "2000-01-01T00:00:00"},
    )
    assert older.status_code == 409
    assert older.json()["detail"]["code"] == "STALE_WRITE"

    # (b) expected == current → succeeds
    cur = _invoice_stamp(client, h, iid)
    eq = client.patch(f"/api/v1/invoices/{iid}", headers=h, json={"amount": 600, "expected_updated_at": cur})
    assert eq.status_code == 200, eq.text


def test_invoice_optimistic_lock_tenant_isolation(client, auth_headers):
    h = auth_headers
    inv = _make_invoice(client, h)
    _, hb = create_tenant(
        client,
        code="olockinv",
        name="Olock Inv",
        admin_email="admin@olockinv.example.com",
    )
    # foreign PATCH → 404 (not 409), even with a lock token
    r = client.patch(
        f"/api/v1/invoices/{inv['id']}",
        headers=hb,
        json={"amount": 1, "expected_updated_at": "2020-01-01T00:00:00"},
    )
    assert r.status_code == 404


# ── Charter ──────────────────────────────────────────────────────────────────


def _make_charter(client, h):
    r = client.post("/api/v1/charters", headers=h, json={"charter_type": "voyage"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _charter_stamp(client, h, cid: str) -> str | None:
    return client.get(f"/api/v1/charters/{cid}", headers=h).json()["updated_at"]


def test_charter_optimistic_lock(client, auth_headers, db_engine):
    h = auth_headers
    ch = _make_charter(client, h)
    cid = ch["id"]

    # (a) no expected → back-compat
    r = client.patch(f"/api/v1/charters/{cid}", headers=h, json={"commission_pct": 1.5})
    assert r.status_code == 200, r.text

    _age_updated_at(db_engine, Charter, cid)
    u1 = _charter_stamp(client, h, cid)
    assert u1 is not None

    ok = client.patch(
        f"/api/v1/charters/{cid}", headers=h, json={"commission_pct": 2.0, "expected_updated_at": u1}
    )
    assert ok.status_code == 200, ok.text

    u2 = _charter_stamp(client, h, cid)
    assert u2 is not None and u2 != u1, f"updated_at must advance after PATCH: {u1} -> {u2}"

    # (d) same stale expected → 409
    stale = client.patch(
        f"/api/v1/charters/{cid}", headers=h, json={"commission_pct": 3.0, "expected_updated_at": u1}
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "STALE_WRITE"
    assert "current" in stale.json()["detail"]

    # (c) obviously-old expected → 409
    older = client.patch(
        f"/api/v1/charters/{cid}",
        headers=h,
        json={"commission_pct": 4.0, "expected_updated_at": "2000-01-01T00:00:00"},
    )
    assert older.status_code == 409
    assert older.json()["detail"]["code"] == "STALE_WRITE"

    # (b) expected == current → succeeds
    cur = _charter_stamp(client, h, cid)
    eq = client.patch(
        f"/api/v1/charters/{cid}", headers=h, json={"commission_pct": 5.0, "expected_updated_at": cur}
    )
    assert eq.status_code == 200, eq.text


def test_charter_optimistic_lock_tenant_isolation(client, auth_headers):
    h = auth_headers
    ch = _make_charter(client, h)
    _, hb = create_tenant(
        client,
        code="olockch",
        name="Olock Ch",
        admin_email="admin@olockch.example.com",
    )
    r = client.patch(
        f"/api/v1/charters/{ch['id']}",
        headers=hb,
        json={"commission_pct": 99, "expected_updated_at": "2020-01-01T00:00:00"},
    )
    assert r.status_code == 404


# ── Counterparty ─────────────────────────────────────────────────────────────


def _make_counterparty(client, h, name="OL Chartering"):
    r = client.post("/api/v1/masterdata/counterparties", headers=h, json={"name": name, "type": "owner"})
    assert r.status_code == 200, r.text
    return r.json()


def _cp_stamp(client, h, pid: str) -> str | None:
    return client.get(f"/api/v1/masterdata/counterparties/{pid}", headers=h).json()["updated_at"]


def test_counterparty_optimistic_lock(client, auth_headers, db_engine):
    h = auth_headers
    cp = _make_counterparty(client, h)
    pid = cp["id"]

    # (a) no expected → back-compat
    r = client.patch(f"/api/v1/masterdata/counterparties/{pid}", headers=h, json={"name": "OL Renamed"})
    assert r.status_code == 200, r.text

    _age_updated_at(db_engine, Counterparty, pid)
    u1 = _cp_stamp(client, h, pid)
    assert u1 is not None

    ok = client.patch(
        f"/api/v1/masterdata/counterparties/{pid}",
        headers=h,
        json={"name": "OL A", "expected_updated_at": u1},
    )
    assert ok.status_code == 200, ok.text

    u2 = _cp_stamp(client, h, pid)
    assert u2 is not None and u2 != u1, f"updated_at must advance after PATCH: {u1} -> {u2}"

    # (d) same stale expected → 409
    stale = client.patch(
        f"/api/v1/masterdata/counterparties/{pid}",
        headers=h,
        json={"name": "OL B", "expected_updated_at": u1},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "STALE_WRITE"
    assert "current" in stale.json()["detail"]

    # (c) obviously-old expected → 409
    older = client.patch(
        f"/api/v1/masterdata/counterparties/{pid}",
        headers=h,
        json={"name": "OL C", "expected_updated_at": "2000-01-01T00:00:00"},
    )
    assert older.status_code == 409
    assert older.json()["detail"]["code"] == "STALE_WRITE"

    # (b) expected == current → succeeds
    cur = _cp_stamp(client, h, pid)
    eq = client.patch(
        f"/api/v1/masterdata/counterparties/{pid}",
        headers=h,
        json={"name": "OL D", "expected_updated_at": cur},
    )
    assert eq.status_code == 200, eq.text


def test_counterparty_optimistic_lock_tenant_isolation(client, auth_headers):
    h = auth_headers
    cp = _make_counterparty(client, h, name="OL Iso")
    _, hb = create_tenant(
        client,
        code="olockcp",
        name="Olock Cp",
        admin_email="admin@olockcp.example.com",
    )
    r = client.patch(
        f"/api/v1/masterdata/counterparties/{cp['id']}",
        headers=hb,
        json={"name": "HACKED", "expected_updated_at": "2020-01-01T00:00:00"},
    )
    assert r.status_code == 404


# ── Vessel ───────────────────────────────────────────────────────────────────


def _make_vessel(client, h, name="MV Optimist", imo="9111111"):
    r = client.post("/api/v1/masterdata/vessels", headers=h, json={"name": name, "imo": imo})
    assert r.status_code == 200, r.text
    return r.json()


def _vessel_stamp(client, h, vid: str) -> str | None:
    return client.get(f"/api/v1/masterdata/vessels/{vid}", headers=h).json()["updated_at"]


def test_vessel_optimistic_lock(client, auth_headers, db_engine):
    h = auth_headers
    vs = _make_vessel(client, h)
    vid = vs["id"]

    # (a) no expected → back-compat
    r = client.patch(f"/api/v1/masterdata/vessels/{vid}", headers=h, json={"name": "MV Optimist 2"})
    assert r.status_code == 200, r.text

    _age_updated_at(db_engine, Vessel, vid)
    u1 = _vessel_stamp(client, h, vid)
    assert u1 is not None

    ok = client.patch(
        f"/api/v1/masterdata/vessels/{vid}",
        headers=h,
        json={"name": "MV A", "expected_updated_at": u1},
    )
    assert ok.status_code == 200, ok.text

    u2 = _vessel_stamp(client, h, vid)
    assert u2 is not None and u2 != u1, f"updated_at must advance after PATCH: {u1} -> {u2}"

    # (d) same stale expected → 409
    stale = client.patch(
        f"/api/v1/masterdata/vessels/{vid}",
        headers=h,
        json={"name": "MV B", "expected_updated_at": u1},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "STALE_WRITE"
    assert "current" in stale.json()["detail"]

    # (c) obviously-old expected → 409
    older = client.patch(
        f"/api/v1/masterdata/vessels/{vid}",
        headers=h,
        json={"name": "MV C", "expected_updated_at": "2000-01-01T00:00:00"},
    )
    assert older.status_code == 409
    assert older.json()["detail"]["code"] == "STALE_WRITE"

    # (b) expected == current → succeeds
    cur = _vessel_stamp(client, h, vid)
    eq = client.patch(
        f"/api/v1/masterdata/vessels/{vid}",
        headers=h,
        json={"name": "MV D", "expected_updated_at": cur},
    )
    assert eq.status_code == 200, eq.text


def test_vessel_optimistic_lock_tenant_isolation(client, auth_headers):
    h = auth_headers
    vs = _make_vessel(client, h, name="MV Iso", imo="9222222")
    _, hb = create_tenant(
        client,
        code="olockvs",
        name="Olock Vs",
        admin_email="admin@olockvs.example.com",
    )
    r = client.patch(
        f"/api/v1/masterdata/vessels/{vs['id']}",
        headers=hb,
        json={"name": "HACKED", "expected_updated_at": "2020-01-01T00:00:00"},
    )
    assert r.status_code == 404
