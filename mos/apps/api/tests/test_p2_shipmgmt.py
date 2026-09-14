"""P2 ship-management fixes.

- Work-order spare consumption: registered per WO, stock deducted exactly once
  when the WO transitions to done; insufficient stock warns but never blocks.
- Crew certificates stored in meta.certificates with a cert-alerts endpoint
  (window filter + days_left ascending).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_ship import ShipSparePart


def _tenant_id(db_engine):
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        return db.scalar(select(Tenant).where(Tenant.code == "demo")).id


def _fleet_vessel_id(client, headers) -> str:
    fleet = client.get("/api/v1/ship/fleet", headers=headers)
    assert fleet.status_code == 200, fleet.text
    return fleet.json()["vessels"][0]["vessel_id"]


def _make_spare(db_engine, part_no: str, qty: str, min_qty: str = "0") -> str:
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        tenant_id = db.scalar(select(Tenant).where(Tenant.code == "demo")).id
        part = ShipSparePart(
            tenant_id=tenant_id,
            part_no=part_no,
            description=f"Test spare {part_no}",
            qty_on_hand=Decimal(qty),
            min_qty=Decimal(min_qty),
        )
        db.add(part)
        db.commit()
        return str(part.id)


def _qty_on_hand(db_engine, part_id: str) -> Decimal:
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        return Decimal(db.get(ShipSparePart, uuid.UUID(part_id)).qty_on_hand)


def _make_wo(client, headers, vessel_id: str, wo_no: str) -> str:
    r = client.post(
        "/api/v1/ship/work-orders",
        headers=headers,
        json={"vessel_id": vessel_id, "wo_no": wo_no, "title": f"WO {wo_no}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_wo_spare_register_and_deduct_on_done(client, auth_headers, db_engine):
    h = auth_headers
    vid = _fleet_vessel_id(client, h)
    part_id = _make_spare(db_engine, "P2-FILTER-01", qty="10", min_qty="2")
    wo_id = _make_wo(client, h, vid, "P2-WO-001")

    for qty in ("3", "2"):
        r = client.post(
            f"/api/v1/ship/work-orders/{wo_id}/spares",
            headers=h,
            json={"part_id": part_id, "qty": qty},
        )
        assert r.status_code == 200, r.text
        assert r.json()["warnings"] == []

    listed = client.get(f"/api/v1/ship/work-orders/{wo_id}/spares", headers=h)
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 2
    assert sorted(r["qty"] for r in rows) == [2.0, 3.0]
    assert rows[0]["part_no"] == "P2-FILTER-01"

    # Registration alone must not touch stock.
    assert _qty_on_hand(db_engine, part_id) == Decimal("10")

    done = client.patch(f"/api/v1/ship/work-orders/{wo_id}", headers=h, json={"status": "done"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    assert done.json()["warnings"] == []
    assert _qty_on_hand(db_engine, part_id) == Decimal("5")


def test_wo_done_insufficient_stock_warns_but_not_blocks(client, auth_headers, db_engine):
    h = auth_headers
    vid = _fleet_vessel_id(client, h)
    part_id = _make_spare(db_engine, "P2-SEAL-99", qty="2")
    wo_id = _make_wo(client, h, vid, "P2-WO-002")

    r = client.post(
        f"/api/v1/ship/work-orders/{wo_id}/spares",
        headers=h,
        json={"part_id": part_id, "qty": "5"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["warnings"], "registration should warn when qty exceeds stock"

    done = client.patch(f"/api/v1/ship/work-orders/{wo_id}", headers=h, json={"status": "done"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    warnings = done.json()["warnings"]
    assert len(warnings) == 1
    assert "P2-SEAL-99" in warnings[0]
    assert _qty_on_hand(db_engine, part_id) == Decimal("-3")


def test_wo_done_consumption_idempotent(client, auth_headers, db_engine):
    h = auth_headers
    vid = _fleet_vessel_id(client, h)
    part_id = _make_spare(db_engine, "P2-GASKET-07", qty="8")
    wo_id = _make_wo(client, h, vid, "P2-WO-003")

    r = client.post(
        f"/api/v1/ship/work-orders/{wo_id}/spares",
        headers=h,
        json={"part_id": part_id, "qty": "3"},
    )
    assert r.status_code == 200, r.text

    first = client.patch(f"/api/v1/ship/work-orders/{wo_id}", headers=h, json={"status": "done"})
    assert first.status_code == 200, first.text
    assert _qty_on_hand(db_engine, part_id) == Decimal("5")

    # Repeating the done transition must not deduct again.
    second = client.patch(f"/api/v1/ship/work-orders/{wo_id}", headers=h, json={"status": "done"})
    assert second.status_code == 200, second.text
    assert second.json()["warnings"] == []
    assert _qty_on_hand(db_engine, part_id) == Decimal("5")


def test_crew_certificates_and_cert_alerts(client, auth_headers, db_engine):
    h = auth_headers
    vid = _fleet_vessel_id(client, h)
    today = date.today()
    _ = db_engine

    # Baseline: seeded crew carry no certificates.
    base = client.get("/api/v1/ship/crew/cert-alerts", headers=h, params={"days": 3650})
    assert base.status_code == 200, base.text
    base_n = len(base.json())

    r = client.post(
        "/api/v1/ship/crew",
        headers=h,
        json={
            "vessel_id": vid,
            "full_name": "P2 Officer Near",
            "rank": "2nd Officer",
            "certificates": [
                {"code": "STCW-II/1", "expires_on": (today + timedelta(days=10)).isoformat()},
                {"code": "GMDSS", "expires_on": (today + timedelta(days=200)).isoformat()},
            ],
        },
    )
    assert r.status_code == 200, r.text
    crew_near = r.json()["id"]

    r = client.post(
        "/api/v1/ship/crew",
        headers=h,
        json={"vessel_id": vid, "full_name": "P2 Officer Far", "rank": "3rd Engineer"},
    )
    assert r.status_code == 200, r.text
    crew_far = r.json()["id"]

    # Update path: attach certificates via PATCH.
    r = client.patch(
        f"/api/v1/ship/crew/{crew_far}",
        headers=h,
        json={"certificates": [{"code": "STCW-III/1", "expires_on": (today + timedelta(days=45)).isoformat()}]},
    )
    assert r.status_code == 200, r.text

    alerts = client.get("/api/v1/ship/crew/cert-alerts", headers=h, params={"days": 60})
    assert alerts.status_code == 200, alerts.text
    mine = [a for a in alerts.json() if a["crew_id"] in (crew_near, crew_far)]
    assert len(mine) == 2, f"60-day window should exclude the 200-day GMDSS cert: {mine}"
    assert mine[0]["days_left"] <= mine[1]["days_left"], "alerts must sort by days_left ascending"
    assert mine[0]["crew_name"] == "P2 Officer Near"
    assert mine[0]["code"] == "STCW-II/1"
    assert mine[0]["days_left"] == 10
    assert mine[1]["code"] == "STCW-III/1"
    assert mine[1]["days_left"] == 45

    wide = client.get("/api/v1/ship/crew/cert-alerts", headers=h, params={"days": 3650})
    assert len(wide.json()) == base_n + 3
