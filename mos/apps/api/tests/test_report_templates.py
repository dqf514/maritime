"""Report templates — industry preset reports, Excel export, schedule runner.

Covers:
- every SYSTEM_REPORT preset executes against seeded demo data (no errors)
- every SYSTEM_REPORT_SPECS declarative adapter validates + previews
- Excel export produces a real .xlsx workbook (openpyxl-readable)
- builder preview accepts both ``spec`` and ``query_spec`` payload keys
- builder filters accept comma-separated string values for in/not_in
- report schedule runner executes due schedules and advances next_run_at
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

API = "/api/v1"


# ---------------------------------------------------------------------------
# Preset reports
# ---------------------------------------------------------------------------


def test_all_preset_reports_execute(client, auth_headers):
    from app.services.report_engine import PRESET_EXECUTORS, SYSTEM_REPORTS

    r = client.get(f"{API}/reports/system/seed", headers=auth_headers)
    assert r.status_code == 200, r.text

    # every registered preset has a report row and an executor
    query_keys = {s["query"] for s in SYSTEM_REPORTS}
    assert query_keys == set(PRESET_EXECUTORS.keys())
    assert len(SYSTEM_REPORTS) >= 24

    reports = client.get(f"{API}/reports", headers=auth_headers).json()
    system = {x["report_type"]: x for x in reports if x["is_system"]}
    assert set(system) == {s["report_type"] for s in SYSTEM_REPORTS}

    for report_type, meta in sorted(system.items()):
        r = client.post(f"{API}/reports/{meta['id']}/execute", headers=auth_headers, json={})
        assert r.status_code == 200, f"{report_type}: {r.text}"
        result = r.json()
        assert not result.get("error"), f"{report_type}: {result.get('error')}"
        assert result["columns"], f"{report_type}: no columns"
        keys = {c["key"] for c in result["columns"]}
        for row in result["rows"][:5]:
            assert set(row) == keys, f"{report_type} row shape {set(row)} != {keys}"


def test_new_maritime_presets_have_expected_columns(client, auth_headers):
    """Field expectations per the maritime report catalogue."""
    expected = {
        "sof_statement": {"vessel_name", "voyage_no", "port_name", "event_code", "event_at", "duration_hours", "remarks"},
        "laytime_statement": {"voyage_no", "port_name", "allowed_days", "used_days", "demurrage_rate", "despatch_rate", "demurrage_amount", "despatch_amount", "status"},
        "hire_statement": {"statement_no", "contract_no", "vessel_name", "period_start", "period_end", "hire_rate", "hire_days", "off_hire_days", "net_hire", "status"},
        "estimate_vs_actual": {"estimate_title", "voyage_no", "vessel_name", "est_revenue", "act_revenue", "est_cost", "act_cost", "revenue_variance", "cost_variance", "net_variance"},
        "fixture_recap": {"fixture_date", "charter_no", "vessel_name", "charterer", "cargo", "load_port", "disch_port", "freight_rate", "laycan_from", "laycan_to", "cp_form"},
        "trial_balance": {"account_code", "account_name", "account_type", "debit_total", "credit_total", "balance"},
        "commission_report": {"invoice_no", "broker", "commission_type", "rate_pct", "base_amount", "amount", "currency"},
        "statement_of_account": {"party_name", "invoice_no", "invoice_date", "invoice_type", "amount", "paid", "outstanding", "status"},
        "port_cost_breakdown": {"port_name", "voyage_no", "pda_amount", "fda_amount", "variance", "variance_pct", "status"},
        "credit_exposure": {"party_name", "open_invoices", "total_exposure", "credit_limit", "utilization_pct", "breach"},
        "cii_annual": {"vessel_name", "period", "distance_nm", "co2_mt", "aer", "required_cii", "cii_rating"},
        "mrv_voyage": {"voyage_no", "vessel_name", "fuel_type", "fo_mt", "do_mt", "co2_mt", "transport_work", "aer"},
        "eu_ets_cost": {"voyage_no", "vessel_name", "co2_mt", "eu_share_pct", "applicable_pct", "ets_price_eur", "allowance_cost_eur"},
        "noon_report_summary": {"vessel_name", "voyage_no", "report_at", "position", "speed", "consumption_mt", "rob_fo", "rob_do", "eta_deviation_hours"},
        "bunker_reconciliation": {"vessel_name", "order_no", "grade", "bdn_qty", "rob_before", "rob_after", "consumption", "computed_consumption", "variance"},
        "vessel_utilization": {"vessel_name", "voyage_days", "sea_days", "port_days", "utilization_pct"},
    }
    client.get(f"{API}/reports/system/seed", headers=auth_headers)
    reports = client.get(f"{API}/reports", headers=auth_headers).json()
    by_type = {x["report_type"]: x for x in reports if x["is_system"]}

    for report_type, cols in expected.items():
        assert report_type in by_type, f"missing preset {report_type}"
        r = client.post(f"{API}/reports/{by_type[report_type]['id']}/execute", headers=auth_headers, json={})
        assert r.status_code == 200, f"{report_type}: {r.text}"
        result = r.json()
        assert not result.get("error"), f"{report_type}: {result.get('error')}"
        keys = {c["key"] for c in result["columns"]}
        assert keys == cols, f"{report_type}: {keys} != {cols}"


def test_all_declarative_specs_validate(client, auth_headers):
    from app.services.report_builder import validate_spec
    from app.services.report_engine import SYSTEM_REPORT_SPECS

    assert len(SYSTEM_REPORT_SPECS) >= 24
    for report_type, factory in sorted(SYSTEM_REPORT_SPECS.items()):
        spec = factory() if callable(factory) else factory
        errors = validate_spec(spec)
        assert errors == [], f"{report_type}: {errors}"
        p = client.post(f"{API}/reports/preview", headers=auth_headers, json={"spec": spec, "limit": 5})
        assert p.status_code == 200, f"{report_type}: {p.text}"
        assert p.json()["columns"], f"{report_type}: no columns"


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------


def test_xlsx_export_is_valid_workbook(client, auth_headers):
    from openpyxl import load_workbook

    client.get(f"{API}/reports/system/seed", headers=auth_headers)
    reports = client.get(f"{API}/reports", headers=auth_headers).json()
    meta = next(x for x in reports if x["is_system"] and x["report_type"] == "voyage_pnl")

    r = client.get(f"{API}/reports/{meta['id']}/export?format=xlsx", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers.get("content-type", "")
    assert "xlsx" in r.headers.get("content-disposition", "")

    wb = load_workbook(io.BytesIO(r.content))
    ws = wb.active
    assert ws.freeze_panes == "A2"
    header = [c.value for c in ws[1]]
    assert header and all(h for h in header)
    assert header[0] == ws.cell(row=1, column=1).value
    # header styling applied
    assert ws.cell(row=1, column=1).font.bold
    # columns are sized
    assert ws.column_dimensions["A"].width >= 10


def test_csv_export_still_works(client, auth_headers):
    client.get(f"{API}/reports/system/seed", headers=auth_headers)
    reports = client.get(f"{API}/reports", headers=auth_headers).json()
    meta = next(x for x in reports if x["is_system"])
    r = client.get(f"{API}/reports/{meta['id']}/export?format=csv", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "csv" in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Builder: payload shape + filter value coercion
# ---------------------------------------------------------------------------


def _voyages_spec() -> dict:
    return {
        "datasets": [{"dataset": "voyages", "alias": "v"}],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "v", "field": "status", "label": "Status"},
        ],
        "filters": [],
    }


def test_preview_accepts_spec_and_query_spec_keys(client, auth_headers):
    spec = _voyages_spec()
    r1 = client.post(f"{API}/reports/preview", headers=auth_headers, json={"spec": spec, "limit": 10})
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"{API}/reports/preview", headers=auth_headers, json={"query_spec": spec, "limit": 10})
    assert r2.status_code == 200, r2.text
    assert r1.json()["columns"] == r2.json()["columns"]
    assert r1.json()["total_rows"] == r2.json()["total_rows"]

    # neither key → 422
    r3 = client.post(f"{API}/reports/preview", headers=auth_headers, json={"limit": 10})
    assert r3.status_code == 422, r3.text


def test_in_filter_accepts_comma_separated_string(client, auth_headers):
    """in / not_in string values are auto-converted to lists."""
    base = _voyages_spec()
    spec = {
        **base,
        "filters": [{"dataset": "v", "field": "status", "op": "in", "value": "active, completed, planned"}],
    }
    r = client.post(f"{API}/reports/preview", headers=auth_headers, json={"spec": spec, "limit": 50})
    assert r.status_code == 200, r.text

    # explicit list still works
    spec_list = {
        **base,
        "filters": [{"dataset": "v", "field": "status", "op": "in", "value": ["active", "completed"]}],
    }
    r2 = client.post(f"{API}/reports/preview", headers=auth_headers, json={"spec": spec_list, "limit": 50})
    assert r2.status_code == 200, r2.text

    # not_in with a string
    spec_not = {
        **base,
        "filters": [{"dataset": "v", "field": "status", "op": "not_in", "value": "deleted, cancelled"}],
    }
    r3 = client.post(f"{API}/reports/preview", headers=auth_headers, json={"spec": spec_not, "limit": 50})
    assert r3.status_code == 200, r3.text


def test_between_filter_accepts_comma_separated_string(client, auth_headers):
    spec = {
        **_voyages_spec(),
        "filters": [
            {
                "dataset": "v",
                "field": "created_at",
                "op": "between",
                "value": "2000-01-01, 2100-01-01",
            }
        ],
    }
    r = client.post(f"{API}/reports/preview", headers=auth_headers, json={"spec": spec, "limit": 50})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Schedule runner
# ---------------------------------------------------------------------------


def test_compute_next_run_variants():
    from app.models_report import ReportSchedule
    from app.services.report_scheduler import compute_next_run

    now = datetime(2026, 9, 29, 8, 0, 0, tzinfo=timezone.utc)

    def _sched(**kw):
        return ReportSchedule(
            tenant_id=None,
            report_id=None,
            schedule_type=kw.get("schedule_type", "daily"),
            cron_expression=kw.get("cron_expression"),
        )

    daily = compute_next_run(_sched(schedule_type="daily"), now)
    assert daily == now + timedelta(days=1)

    weekly = compute_next_run(_sched(schedule_type="weekly"), now)
    assert weekly == now + timedelta(days=7)

    monthly = compute_next_run(_sched(schedule_type="monthly"), now)
    assert monthly.month == 10 and monthly.day == 29

    on_demand = compute_next_run(_sched(schedule_type="on_demand"), now)
    assert on_demand is None

    cron = compute_next_run(_sched(schedule_type="on_demand", cron_expression="0 6 * * *"), now)
    assert cron == datetime(2026, 9, 30, 6, 0, 0, tzinfo=timezone.utc)


def test_run_due_schedules_executes_and_advances(client, auth_headers, db_engine):
    from app.models_report import ReportDefinition, ReportSchedule
    from app.services.report_scheduler import run_due_schedules
    from sqlalchemy.orm import sessionmaker

    client.get(f"{API}/reports/system/seed", headers=auth_headers)
    reports = client.get(f"{API}/reports", headers=auth_headers).json()
    meta = next(x for x in reports if x["is_system"])

    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with Session() as db:
        report = db.get(ReportDefinition, uuid.UUID(meta["id"]))
        assert report is not None

        due_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        sched = ReportSchedule(
            tenant_id=report.tenant_id,
            report_id=report.id,
            schedule_type="daily",
            recipients=["ops@demo.marios"],
            output_format="excel",
            is_active=True,
            next_run_at=due_at,
            last_run_at=None,
        )
        db.add(sched)
        db.commit()
        sched_id = sched.id

        now = datetime.now(timezone.utc)
        processed = run_due_schedules(db, now)
        assert processed == 1

        from app.models_identity import OutboundMailLog

        db.expire_all()
        mail = db.execute(
            select(OutboundMailLog).where(OutboundMailLog.purpose == "report_schedule")
        ).scalars().first()
        assert mail is not None, "schedule run should send an email"
        assert mail.to_email == "ops@demo.marios"
        atts = (mail.meta or {}).get("attachments") or []
        assert atts and atts[0].get("filename", "").endswith(".xlsx")

        sched = db.get(ReportSchedule, sched_id)
        assert sched.last_run_at is not None
        assert sched.next_run_at is not None
        assert sched.next_run_at > due_at

        # second run finds nothing due
        assert run_due_schedules(db, datetime.now(timezone.utc)) == 0


def test_install_scheduler_bootstraps_tick_once(client, auth_headers, db_engine):
    """install_scheduler enqueues a tick only while none is live (restart-safe)."""
    from app.models_jobs import Job
    from app.services.report_scheduler import TICK_KIND, install_scheduler, register_handlers
    from sqlalchemy.orm import sessionmaker

    register_handlers()
    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with Session() as db:
        install_scheduler(db)
        install_scheduler(db)  # second call must not duplicate the tick
        ticks = db.scalars(select(Job).where(Job.kind == TICK_KIND)).all()
        assert len(ticks) == 1
        assert ticks[0].status == "pending"

        # once the tick is done and the chain already re-enqueued, no extra tick
        ticks[0].status = "done"
        db.commit()
        install_scheduler(db)
        ticks = db.scalars(select(Job).where(Job.kind == TICK_KIND)).all()
        assert len(ticks) == 2  # the fresh bootstrap tick


def test_schedule_runner_isolates_failures(client, auth_headers, db_engine):
    """One broken schedule (missing report) must not block the others."""
    from app.models_report import ReportDefinition, ReportSchedule
    from app.services.report_scheduler import run_due_schedules
    from sqlalchemy.orm import sessionmaker

    client.get(f"{API}/reports/system/seed", headers=auth_headers)
    reports = client.get(f"{API}/reports", headers=auth_headers).json()
    meta = next(x for x in reports if x["is_system"])

    Session = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with Session() as db:
        report = db.get(ReportDefinition, uuid.UUID(meta["id"]))
        due_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)

        broken = ReportSchedule(
            tenant_id=report.tenant_id,
            report_id=uuid.uuid4(),  # dangling FK target
            schedule_type="daily",
            recipients=["x@demo.marios"],
            output_format="csv",
            is_active=True,
            next_run_at=due_at,
        )
        good = ReportSchedule(
            tenant_id=report.tenant_id,
            report_id=report.id,
            schedule_type="daily",
            recipients=["y@demo.marios"],
            output_format="csv",
            is_active=True,
            next_run_at=due_at,
        )
        db.add_all([broken, good])
        db.commit()

        processed = run_due_schedules(db, datetime.now(timezone.utc))
        assert processed == 1  # only the good one produced a result

        from app.models_identity import OutboundMailLog

        db.expire_all()
        mails = db.execute(
            select(OutboundMailLog).where(OutboundMailLog.purpose == "report_schedule")
        ).scalars().all()
        assert any(m.to_email == "y@demo.marios" for m in mails)
