"""P1 ship-management / dashboard fixes.

- Certificate three-band status (valid/expiring/expired) computed on write and
  lazily re-migrated on read.
- Role wall KPIs backed by real queries (laycan, port calls, cert alerts, ...);
  remaining demo values carry ``synthetic: true``.
- next_drydock profile updates keep an idempotent repair ScheduleBlock.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_domain import Charter, Voyage
from app.models_ship import ShipCertificate


def _demo_ids(db_engine):
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
        voyage = db.scalar(select(Voyage).where(Voyage.tenant_id == tenant.id))
        return tenant.id, (voyage.id if voyage else None)


def _fleet_vessel_id(client, headers) -> str:
    fleet = client.get("/api/v1/ship/fleet", headers=headers)
    assert fleet.status_code == 200, fleet.text
    return fleet.json()["vessels"][0]["vessel_id"]


def _kpi(snap: dict, label: str) -> dict:
    for k in snap["kpis"]:
        if k["label"] == label:
            return k
    raise AssertionError(f"KPI {label!r} missing in {snap['role']}")


def test_certificate_status_bands_on_create_and_read(client, auth_headers):
    h = auth_headers
    vid = _fleet_vessel_id(client, h)
    today = date.today()
    cases = [
        ("P1-EXP", today - timedelta(days=1), "expired"),
        ("P1-WARN", today + timedelta(days=29), "expiring"),
        ("P1-EDGE", today + timedelta(days=30), "valid"),
        ("P1-FAR", today + timedelta(days=200), "valid"),
    ]
    for code, expires, _ in cases:
        r = client.post(
            "/api/v1/ship/certificates",
            headers=h,
            json={"vessel_id": vid, "cert_code": code, "cert_name": code, "expires_on": expires.isoformat()},
        )
        assert r.status_code == 200, r.text
    detail = client.get(f"/api/v1/ship/vessels/{vid}", headers=h)
    assert detail.status_code == 200, detail.text
    by_code = {c["cert_code"]: c["status"] for c in detail.json()["certificates"]}
    for code, _, expected in cases:
        assert by_code[code] == expected, f"{code}: expected {expected}, got {by_code[code]}"


def test_certificate_lazy_refresh_migrates_stale_rows(client, auth_headers, db_engine):
    h = auth_headers
    vid = _fleet_vessel_id(client, h)
    r = client.post(
        "/api/v1/ship/certificates",
        headers=h,
        json={"vessel_id": vid, "cert_code": "P1-STALE", "cert_name": "Stale cert", "expires_on": date.today().isoformat()},
    )
    assert r.status_code == 200, r.text
    cert_id = r.json()["id"]
    # Simulate a row that drifted out of date while nobody was looking.
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        cert = db.get(ShipCertificate, uuid.UUID(cert_id))
        cert.expires_on = date.today() - timedelta(days=3)
        cert.status = "valid"
        db.commit()
    detail = client.get(f"/api/v1/ship/vessels/{vid}", headers=h).json()
    stale = next(c for c in detail["certificates"] if c["cert_code"] == "P1-STALE")
    assert stale["status"] == "expired"
    fleet = client.get("/api/v1/ship/fleet", headers=h).json()
    row = next(v for v in fleet["vessels"] if v["vessel_id"] == vid)
    assert row["expiring_certs"] >= 1


def test_kpi_laycan_portcalls_certs_real_counts(client, auth_headers, db_engine):
    h = auth_headers
    tenant_id, voyage_id = _demo_ids(db_engine)
    assert voyage_id is not None, "seed should provide a voyage for port-call KPI"
    today = date.today()

    base_chartering = client.get("/api/v1/dashboards/chartering/snapshot", headers=h).json()
    base_ops = client.get("/api/v1/dashboards/operations/snapshot", headers=h).json()
    base_tech = client.get("/api/v1/dashboards/technical/snapshot", headers=h).json()
    base_laycan = int(_kpi(base_chartering, "Laycan this week")["value"])
    base_calls = int(_kpi(base_ops, "Port calls today")["value"])
    base_certs = int(_kpi(base_tech, "Certs expiring")["value"])

    Session = sessionmaker(bind=db_engine)
    from app.models_domain import PortCall  # noqa: PLC0415

    with Session() as db:
        for i in range(2):
            db.add(
                Charter(
                    tenant_id=tenant_id,
                    charter_no=f"P1-LAY-{uuid.uuid4().hex[:8]}",
                    charter_type="voyage",
                    status="active",
                    laycan_from=today,
                    laycan_to=today + timedelta(days=2),
                )
            )
        db.add(PortCall(tenant_id=tenant_id, voyage_id=voyage_id, purpose="load", eta=datetime.now()))
        db.commit()

    vid = _fleet_vessel_id(client, h)
    r = client.post(
        "/api/v1/ship/certificates",
        headers=h,
        json={
            "vessel_id": vid,
            "cert_code": "P1-KPI",
            "cert_name": "KPI cert",
            "expires_on": (today + timedelta(days=10)).isoformat(),
        },
    )
    assert r.status_code == 200, r.text

    chartering = client.get("/api/v1/dashboards/chartering/snapshot", headers=h).json()
    ops = client.get("/api/v1/dashboards/operations/snapshot", headers=h).json()
    tech = client.get("/api/v1/dashboards/technical/snapshot", headers=h).json()
    assert int(_kpi(chartering, "Laycan this week")["value"]) == base_laycan + 2
    assert int(_kpi(ops, "Port calls today")["value"]) == base_calls + 1
    assert int(_kpi(tech, "Certs expiring")["value"]) == base_certs + 1
    assert _kpi(chartering, "Laycan this week")["synthetic"] is False
    assert _kpi(ops, "Port calls today")["synthetic"] is False
    assert _kpi(tech, "Certs expiring")["synthetic"] is False


def test_kpi_synthetic_flags_present(client, auth_headers):
    h = auth_headers
    snaps = {}
    for role in ("management", "chartering", "operations", "finance", "demurrage", "technical", "tenant_admin"):
        r = client.get(f"/api/v1/dashboards/{role}/snapshot", headers=h)
        assert r.status_code == 200, r.text
        snaps[role] = r.json()
        for k in snaps[role]["kpis"]:
            assert "synthetic" in k, f"{role}/{k['label']} lacks synthetic flag"
    # Known real KPIs
    assert _kpi(snaps["chartering"], "Laycan this week")["synthetic"] is False
    assert _kpi(snaps["operations"], "Port calls today")["synthetic"] is False
    assert _kpi(snaps["operations"], "Off-hire (open)")["synthetic"] is False
    assert _kpi(snaps["technical"], "Certs expiring")["synthetic"] is False
    assert _kpi(snaps["technical"], "Drydock in 90d")["synthetic"] is False
    assert _kpi(snaps["demurrage"], "SOF pending")["synthetic"] is False
    assert _kpi(snaps["tenant_admin"], "Connector health")["synthetic"] is False
    # Known synthetic KPIs
    assert _kpi(snaps["management"], "Fleet TCE (live)")["synthetic"] is True
    assert _kpi(snaps["chartering"], "Win rate")["synthetic"] is True
    assert _kpi(snaps["finance"], "DSO")["synthetic"] is True
    assert _kpi(snaps["demurrage"], "Avg days to settle")["synthetic"] is True
    assert _kpi(snaps["tenant_admin"], "AI token burn")["synthetic"] is True


def test_drydock_schedule_block_idempotent(client, auth_headers):
    h = auth_headers
    vid = _fleet_vessel_id(client, h)

    def repair_blocks():
        r = client.get("/api/v1/schedules", headers=h, params={"vessel_id": vid})
        assert r.status_code == 200, r.text
        return [s for s in r.json() if s["block_type"] == "repair"]

    dd1 = (date.today() + timedelta(days=60)).isoformat()
    r = client.put("/api/v1/ship/profiles", headers=h, json={"vessel_id": vid, "next_drydock": dd1})
    assert r.status_code == 200, r.text
    blocks = repair_blocks()
    assert len(blocks) == 1
    assert blocks[0]["start_at"].startswith(dd1)
    block_id = blocks[0]["id"]

    # Same date again — update in place, no duplicate.
    r = client.put("/api/v1/ship/profiles", headers=h, json={"vessel_id": vid, "next_drydock": dd1})
    assert r.status_code == 200, r.text
    blocks = repair_blocks()
    assert len(blocks) == 1
    assert blocks[0]["id"] == block_id

    # Changed date — same block, moved.
    dd2 = (date.today() + timedelta(days=120)).isoformat()
    r = client.put("/api/v1/ship/profiles", headers=h, json={"vessel_id": vid, "next_drydock": dd2})
    assert r.status_code == 200, r.text
    blocks = repair_blocks()
    assert len(blocks) == 1
    assert blocks[0]["id"] == block_id
    assert blocks[0]["start_at"].startswith(dd2)

    # Cleared date — auto block removed.
    r = client.put("/api/v1/ship/profiles", headers=h, json={"vessel_id": vid, "next_drydock": None})
    assert r.status_code == 200, r.text
    assert repair_blocks() == []
