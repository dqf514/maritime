"""Report schedule CRUD API — tenant-scoped create/list/update/delete/run-now.

Covers (plan item: ``report_schedules`` console):
- full CRUD under ``/api/v1/reports/schedules`` is tenant-scoped (no cross-tenant leak)
- ``POST /schedules/{id}/run`` executes the schedule once and records
  ``last_run_at`` / ``last_status`` / ``next_run_at``
- ``schedule_type`` and ``output_format`` are validated (422 ``INVALID_*``)
- ``report_id`` is validated against the caller's tenant on create
"""

from __future__ import annotations

import uuid as uuid_mod

API = "/api/v1"


def _seed_system_report(client, auth_headers) -> dict:
    r = client.get(f"{API}/reports/system/seed", headers=auth_headers)
    assert r.status_code == 200, r.text
    reports = client.get(f"{API}/reports", headers=auth_headers).json()
    meta = next(x for x in reports if x["is_system"])
    return meta


def _create_schedule(client, auth_headers, report_id: str, **overrides) -> dict:
    body = {
        "report_id": report_id,
        "schedule_type": "daily",
        "recipients": ["ops@demo.marios"],
        "output_format": "excel",
        "is_active": True,
    }
    body.update(overrides)
    r = client.post(f"{API}/reports/schedules", headers=auth_headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_schedule_crud_roundtrip(client, auth_headers):
    report = _seed_system_report(client, auth_headers)

    created = _create_schedule(client, auth_headers, report["id"])
    assert created["id"]
    assert created["report_id"] == report["id"]
    assert created["schedule_type"] == "daily"
    assert created["is_active"] is True
    assert created["report_name"] == report["report_name"]

    listed = client.get(f"{API}/reports/schedules/list", headers=auth_headers).json()
    ids = {s["id"] for s in listed}
    assert created["id"] in ids
    row = next(s for s in listed if s["id"] == created["id"])
    assert row["output_format"] == "excel"
    assert row["recipients"] == ["ops@demo.marios"]
    # run metadata is exposed for the console grid
    assert "last_status" in row
    assert "next_run_at" in row

    single = client.get(f"{API}/reports/schedules/{created['id']}", headers=auth_headers)
    assert single.status_code == 200
    assert single.json()["schedule_type"] == "daily"

    patched = client.patch(
        f"{API}/reports/schedules/{created['id']}",
        headers=auth_headers,
        json={"schedule_type": "weekly", "recipients": ["a@demo.marios", "b@demo.marios"]},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["schedule_type"] == "weekly"
    assert patched.json()["recipients"] == ["a@demo.marios", "b@demo.marios"]

    deleted = client.delete(f"{API}/reports/schedules/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    after = client.get(f"{API}/reports/schedules/list", headers=auth_headers).json()
    assert created["id"] not in {s["id"] for s in after}


def test_schedule_tenant_scoped(client, auth_headers):
    """A schedule must never be visible / mutable across tenants."""
    from tests.isolation_helpers import create_tenant

    report = _seed_system_report(client, auth_headers)
    created = _create_schedule(client, auth_headers, report["id"])
    sid = created["id"]

    # second tenant (globex) — own empty schedule list
    _, hb = create_tenant(client, code="globex", name="Globex Marine", admin_email="Admin@Globex.example.com")

    leaked = client.get(f"{API}/reports/schedules/list", headers=hb).json()
    assert all(s["id"] != sid for s in leaked)

    # tenant B cannot read, run, patch or delete tenant A's schedule
    assert client.get(f"{API}/reports/schedules/{sid}", headers=hb).status_code == 404
    assert client.post(f"{API}/reports/schedules/{sid}/run", headers=hb).status_code == 404
    assert (
        client.patch(f"{API}/reports/schedules/{sid}", headers=hb, json={"is_active": False}).status_code == 404
    )
    assert client.delete(f"{API}/reports/schedules/{sid}", headers=hb).status_code == 404

    # tenant A still owns it untouched
    still = client.get(f"{API}/reports/schedules/{sid}", headers=auth_headers)
    assert still.status_code == 200
    assert still.json()["is_active"] is True


def test_schedule_create_rejects_foreign_report(client, auth_headers):
    """report_id must resolve to a report in the caller's tenant (404)."""
    from tests.isolation_helpers import create_tenant

    _seed_system_report(client, auth_headers)
    _, hb = create_tenant(client, code="globex", name="Globex Marine", admin_email="Admin@Globex.example.com")
    # tenant B has no seeded system reports yet
    foreign_reports = client.get(f"{API}/reports", headers=hb).json()
    if not foreign_reports:
        client.get(f"{API}/reports/system/seed", headers=hb)
        foreign_reports = client.get(f"{API}/reports", headers=hb).json()
    foreign_id = foreign_reports[0]["id"]

    # A cannot schedule B's report
    r = client.post(
        f"{API}/reports/schedules",
        headers=auth_headers,
        json={"report_id": foreign_id, "schedule_type": "daily"},
    )
    assert r.status_code == 404

    # and a ghost uuid is rejected the same way
    ghost = client.post(
        f"{API}/reports/schedules",
        headers=auth_headers,
        json={"report_id": str(uuid_mod.uuid4()), "schedule_type": "daily"},
    )
    assert ghost.status_code == 404


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_schedule_type_validated(client, auth_headers):
    report = _seed_system_report(client, auth_headers)

    bad = client.post(
        f"{API}/reports/schedules",
        headers=auth_headers,
        json={"report_id": report["id"], "schedule_type": "hourly-ish"},
    )
    assert bad.status_code == 422, bad.text
    detail = bad.json()["detail"]
    assert detail["code"] == "INVALID_SCHEDULE_TYPE"
    assert "daily" in detail["allowed"]

    created = _create_schedule(client, auth_headers, report["id"])
    patched = client.patch(
        f"{API}/reports/schedules/{created['id']}",
        headers=auth_headers,
        json={"schedule_type": "nope"},
    )
    assert patched.status_code == 422
    assert patched.json()["detail"]["code"] == "INVALID_SCHEDULE_TYPE"


def test_output_format_validated(client, auth_headers):
    report = _seed_system_report(client, auth_headers)
    bad = client.post(
        f"{API}/reports/schedules",
        headers=auth_headers,
        json={"report_id": report["id"], "schedule_type": "daily", "output_format": "docx"},
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "INVALID_OUTPUT_FORMAT"


# ---------------------------------------------------------------------------
# Run now
# ---------------------------------------------------------------------------


def test_run_now_records_a_run(client, auth_headers):
    report = _seed_system_report(client, auth_headers)
    created = _create_schedule(client, auth_headers, report["id"], schedule_type="on_demand")

    # on_demand → no automatic next run
    assert created["next_run_at"] is None

    r = client.post(f"{API}/reports/schedules/{created['id']}/run", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["last_status"] == "success"
    assert body["last_run_at"] is not None

    # persisted on the row, not just the response
    listed = client.get(f"{API}/reports/schedules/list", headers=auth_headers).json()
    row = next(s for s in listed if s["id"] == created["id"])
    assert row["last_status"] == "success"
    assert row["last_run_at"] is not None


def test_run_now_advances_next_run_for_recurring(client, auth_headers):
    report = _seed_system_report(client, auth_headers)
    created = _create_schedule(client, auth_headers, report["id"], schedule_type="daily")

    r = client.post(f"{API}/reports/schedules/{created['id']}/run", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["last_status"] == "success"
    # daily → next_run_at advanced past the run
    assert body["next_run_at"] is not None
    assert body["next_run_at"] > body["last_run_at"]


def test_run_now_missing_report_marks_failed(client, auth_headers, db_engine):
    """A schedule whose report vanished records a failed run, not a 500."""
    from app.models_report import ReportSchedule
    from sqlalchemy.orm import sessionmaker

    report = _seed_system_report(client, auth_headers)
    created = _create_schedule(client, auth_headers, report["id"], schedule_type="on_demand")

    # point the schedule at a dangling report id (bypasses the API on purpose)
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        row = db.get(ReportSchedule, uuid_mod.UUID(created["id"]))
        assert row is not None
        row.report_id = uuid_mod.uuid4()
        db.commit()

    r = client.post(f"{API}/reports/schedules/{created['id']}/run", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["last_status"] == "failed"
    assert body["last_run_at"] is not None

    with TestingSession() as db:
        row = db.get(ReportSchedule, uuid_mod.UUID(created["id"]))
        assert row.last_status == "failed"
        assert row.last_run_at is not None

    # unknown schedule id → 404
    missing = client.post(f"{API}/reports/schedules/{uuid_mod.uuid4()}/run", headers=auth_headers)
    assert missing.status_code == 404
