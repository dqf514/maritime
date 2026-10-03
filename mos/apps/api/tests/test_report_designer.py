"""Phase 8 — Report Designer: declarative datasets, joins, expressions, safety."""

from __future__ import annotations

import uuid

import pytest

from app.services.report_builder import (
    compile_expression,
    validate_spec,
)
from tests.isolation_helpers import create_tenant

API = "/api/v1"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _single_voyage_spec() -> dict:
    return {
        "datasets": [{"dataset": "voyages", "alias": "v"}],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "v", "field": "status", "label": "Status"},
        ],
        "order_by": [{"dataset": "v", "field": "voyage_no", "direction": "asc"}],
    }


def _join_spec(join_type: str = "inner") -> dict:
    return {
        "datasets": [
            {"dataset": "voyages", "alias": "v"},
            {"dataset": "bunker_orders", "alias": "b"},
        ],
        "joins": [
            {
                "left": "v",
                "right": "b",
                "join_type": join_type,
                "left_field": "id",
                "right_field": "voyage_id",
            }
        ],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "b", "field": "order_no", "label": "Order #"},
            {"dataset": "b", "field": "grade", "label": "Grade"},
        ],
    }


def _expression_spec() -> dict:
    return {
        "datasets": [{"dataset": "bunker_orders", "alias": "b"}],
        "fields": [
            {"dataset": "b", "field": "order_no", "label": "Order #"},
            {
                "dataset": "b",
                "field": "cost",
                "expression": "qty_ordered * unit_price",
                "label": "Cost",
                "format": "currency",
            },
        ],
    }


def _agg_spec() -> dict:
    return {
        "datasets": [{"dataset": "invoices", "alias": "i"}],
        "fields": [
            {"dataset": "i", "field": "invoice_type", "label": "Type"},
            {"dataset": "i", "field": "amount", "label": "Total", "agg": "sum", "format": "currency"},
            {"dataset": "i", "field": "amount", "label": "Avg", "agg": "avg", "format": "currency"},
            {"dataset": "i", "field": "id", "label": "Count", "agg": "count"},
        ],
        "group_by": [{"dataset": "i", "field": "invoice_type"}],
        "order_by": [{"dataset": "i", "field": "invoice_type", "direction": "asc"}],
    }


def _preview(client, headers, spec, params=None, limit=100):
    return client.post(
        f"{API}/reports/preview",
        headers=headers,
        json={"spec": spec, "params": params or {}, "limit": limit},
    )


# ---------------------------------------------------------------------------
# Dataset catalog
# ---------------------------------------------------------------------------


def test_dataset_listing_with_fields(client, auth_headers):
    r = client.get(f"{API}/reports/datasets", headers=auth_headers)
    assert r.status_code == 200, r.text
    datasets = r.json()
    by_entity = {d["entity"]: d for d in datasets}
    for entity in ("voyages", "invoices", "charters", "laytime", "claims", "bunker_orders"):
        assert entity in by_entity, f"missing dataset {entity}"
    voy = by_entity["voyages"]
    field_names = [f["name"] for f in voy["fields"]]
    assert "voyage_no" in field_names
    assert "tenant_id" in field_names
    for f in voy["fields"]:
        assert set(f) >= {"name", "type", "label", "table_alias"}
        assert f["type"] in {"string", "number", "date", "datetime", "bool", "json", "uuid"}


def test_dataset_detail(client, auth_headers):
    datasets = client.get(f"{API}/reports/datasets", headers=auth_headers).json()
    target = next(d for d in datasets if d["entity"] == "bunker_orders")
    r = client.get(f"{API}/reports/datasets/{target['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["entity"] == "bunker_orders"
    assert detail["base_table"] == "bunker_orders"
    names = [f["name"] for f in detail["fields"]]
    assert {"order_no", "qty_ordered", "unit_price"} <= set(names)

    missing = client.get(f"{API}/reports/datasets/{uuid.uuid4()}", headers=auth_headers)
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Declarative queries
# ---------------------------------------------------------------------------


def test_declarative_query_single_dataset(client, auth_headers):
    r = _preview(client, auth_headers, _single_voyage_spec())
    assert r.status_code == 200, r.text
    result = r.json()
    assert [c["key"] for c in result["columns"]] == ["Voyage #", "Status"]
    assert result["total_rows"] >= 3  # seeded demo voyages
    voyage_nos = [row["Voyage #"] for row in result["rows"]]
    assert "VOY-2407" in voyage_nos
    for row in result["rows"]:
        assert set(row) == {"Voyage #", "Status"}


def test_declarative_query_join_two_datasets(client, auth_headers):
    r = _preview(client, auth_headers, _join_spec("inner"))
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    # seeded demo: BNK-2407 is delivered onto VOY-2407
    pairs = {(row["Voyage #"], row["Order #"]) for row in rows}
    assert ("VOY-2407", "BNK-2407") in pairs

    # left join keeps voyages without bunker orders
    r = _preview(client, auth_headers, _join_spec("left"))
    assert r.status_code == 200, r.text
    left_rows = r.json()["rows"]
    assert len(left_rows) >= len(rows)
    assert "VOY-2408" in {row["Voyage #"] for row in left_rows}


def test_expression_evaluation(client, auth_headers):
    # create a bunker order with exact numbers
    vessels = client.get(f"{API}/masterdata/vessels", headers=auth_headers).json()
    voyages = client.get(f"{API}/voyages", headers=auth_headers).json()
    r = client.post(
        f"{API}/bunker-orders",
        headers=auth_headers,
        json={
            "vessel_id": vessels[0]["id"],
            "voyage_id": voyages[0]["id"],
            "grade": "VLSFO",
            "qty_ordered": 100,
            "unit_price": 50,
        },
    )
    assert r.status_code == 200, r.text
    order_no = r.json()["order_no"]

    r = _preview(client, auth_headers, _expression_spec())
    assert r.status_code == 200, r.text
    rows = {row["Order #"]: row for row in r.json()["rows"]}
    assert order_no in rows
    assert rows[order_no]["Cost"] == pytest.approx(5000.0)
    # seeded demo order: 800 * 545
    assert rows["BNK-2407"]["Cost"] == pytest.approx(800 * 545)


def test_aggregation_sum_avg_count(client, auth_headers):
    r = _preview(client, auth_headers, _agg_spec())
    assert r.status_code == 200, r.text
    rows = {row["Type"]: row for row in r.json()["rows"]}
    assert set(rows) == {"freight", "demurrage"}
    # seeded demo invoices: freight 1,850,000 + 2,100,000; demurrage 78,000
    assert rows["freight"]["Total"] == pytest.approx(3950000.0)
    assert rows["freight"]["Avg"] == pytest.approx(1975000.0)
    assert rows["freight"]["Count"] == 2
    assert rows["demurrage"]["Total"] == pytest.approx(78000.0)
    assert rows["demurrage"]["Count"] == 1


def test_group_by_requires_grouped_fields(client, auth_headers):
    spec = _agg_spec()
    spec["fields"].append({"dataset": "i", "field": "invoice_no", "label": "Invoice #"})
    r = _preview(client, auth_headers, spec)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_REPORT_SPEC"


def test_filter_and_runtime_param(client, auth_headers):
    spec = _single_voyage_spec()
    spec["filters"] = [
        {"dataset": "v", "field": "status", "op": "eq", "value": {"param": "st"}}
    ]
    r = _preview(client, auth_headers, spec, params={"st": "completed"})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    assert rows and all(row["Status"] == "completed" for row in rows)
    assert "VOY-2405" in {row["Voyage #"] for row in rows}


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_tenant_isolation(client, auth_headers):
    uniq = uuid.uuid4().hex[:6]
    tid_b, hb = create_tenant(
        client,
        code=f"rd{uniq}",
        name=f"RD {uniq}",
        admin_email=f"rd-{uniq}@example.com",
    )
    vessel = client.post(
        f"{API}/masterdata/vessels", headers=hb, json={"name": f"ISO Vessel {uniq}"}
    ).json()
    voy = client.post(
        f"{API}/voyages",
        headers=hb,
        json={"voyage_no": f"VOY-ISO-{uniq}", "vessel_id": vessel["id"]},
    )
    assert voy.status_code == 200, voy.text

    spec = _single_voyage_spec()
    r = _preview(client, auth_headers, spec)
    assert r.status_code == 200, r.text
    demo_rows = r.json()["rows"]
    demo_nos = {row["Voyage #"] for row in demo_rows}
    assert f"VOY-ISO-{uniq}" not in demo_nos
    assert "VOY-2407" in demo_nos

    r = _preview(client, hb, spec)
    assert r.status_code == 200, r.text
    b_nos = {row["Voyage #"] for row in r.json()["rows"]}
    assert f"VOY-ISO-{uniq}" in b_nos
    assert "VOY-2407" not in b_nos

    # cross-tenant report definition access is 404
    created = client.post(
        f"{API}/reports",
        headers=auth_headers,
        json={"report_name": f"RD demo {uniq}", "data_source": "spec", "query_spec": spec},
    )
    assert created.status_code == 200, created.text
    report_id = created.json()["id"]
    assert client.get(f"{API}/reports/{report_id}", headers=hb).status_code == 404
    assert client.get(f"{API}/reports/{report_id}/data", headers=hb).status_code == 404


# ---------------------------------------------------------------------------
# SQL injection safety
# ---------------------------------------------------------------------------


MALICIOUS_EXPRESSIONS = [
    "1; DROP TABLE voyages--",
    "amount); DELETE FROM invoices --",
    "(SELECT amount FROM invoices)",
    "qty * price /* comment */",
    "qty * price UNION SELECT password FROM users",
    "amount || 'x'",
    "coalesce((SELECT 1), 0)",
    "qty; ATTACH DATABASE 'x' AS y",
]


@pytest.mark.parametrize("expr", MALICIOUS_EXPRESSIONS)
def test_malicious_expression_rejected(expr):
    spec = {
        "datasets": [{"dataset": "bunker_orders", "alias": "b"}],
        "fields": [
            {"dataset": "b", "field": "cost", "expression": expr, "label": "Cost"},
        ],
    }
    errors = validate_spec(spec)
    assert errors, f"expression accepted: {expr!r}"


@pytest.mark.parametrize("expr", MALICIOUS_EXPRESSIONS)
def test_malicious_expression_blocked_via_api(client, auth_headers, expr):
    spec = {
        "datasets": [{"dataset": "bunker_orders", "alias": "b"}],
        "fields": [
            {"dataset": "b", "field": "cost", "expression": expr, "label": "Cost"},
        ],
    }
    r = _preview(client, auth_headers, spec)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "INVALID_REPORT_SPEC"

    r = client.post(
        f"{API}/reports",
        headers=auth_headers,
        json={"report_name": "Evil", "data_source": "spec", "query_spec": spec},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "INVALID_REPORT_SPEC"


def test_safe_expression_still_accepted():
    ok = [
        "qty_ordered * unit_price",
        "amount - paid_amount",
        "round(qty_ordered * unit_price, 2)",
        "coalesce(qty_delivered, qty_ordered)",
    ]
    cmap = {
        f"b.{n}": ("b", n)
        for n in ("qty_ordered", "unit_price", "qty_delivered", "amount", "paid_amount")
    }
    for expr in ok:
        assert compile_expression(expr, cmap)
    with pytest.raises(Exception):
        compile_expression("qty_ordered * (SELECT 1)", cmap)


def test_sql_injection_attempt_does_not_damage_data(client, auth_headers):
    r = _preview(client, auth_headers, _single_voyage_spec())
    assert r.status_code == 200, r.text
    assert r.json()["total_rows"] >= 3  # voyages table still exists


# ---------------------------------------------------------------------------
# Spec persistence / run / export
# ---------------------------------------------------------------------------


def test_create_run_update_export_spec_report(client, auth_headers):
    uniq = uuid.uuid4().hex[:6]
    spec = _single_voyage_spec()
    r = client.post(
        f"{API}/reports",
        headers=auth_headers,
        json={
            "report_name": f"Designer {uniq}",
            "data_source": "spec",
            "query_spec": spec,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["spec_version"] == "v2"
    report_id = r.json()["id"]

    r = client.get(f"{API}/reports/{report_id}/data", headers=auth_headers)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["total_rows"] >= 3
    assert [c["key"] for c in result["columns"]] == ["Voyage #", "Status"]

    # children mirrored for the designer
    detail = client.get(f"{API}/reports/{report_id}", headers=auth_headers).json()
    assert detail["query_spec"] == spec
    assert detail["spec_version"] == "v2"

    # update with a new spec
    new_spec = _agg_spec()
    r = client.put(
        f"{API}/reports/{report_id}",
        headers=auth_headers,
        json={"query_spec": new_spec},
    )
    assert r.status_code == 200, r.text
    r = client.get(f"{API}/reports/{report_id}/data", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "Type" in {c["key"] for c in r.json()["columns"]}

    # export
    r = client.get(f"{API}/reports/{report_id}/export?format=csv", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "text/csv" in r.headers["content-type"]
    assert r.headers["content-disposition"].startswith("attachment; filename=")
    body = r.content.decode("utf-8-sig")
    assert body.splitlines()[0].startswith("Voyage #,Status") or "Type" in body.splitlines()[0]


def test_report_field_and_join_children_persisted(client, auth_headers, db_engine):
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.models_report import ReportDataset, ReportField, ReportJoin

    uniq = uuid.uuid4().hex[:6]
    r = client.post(
        f"{API}/reports",
        headers=auth_headers,
        json={
            "report_name": f"Children {uniq}",
            "data_source": "spec",
            "query_spec": _join_spec("left"),
        },
    )
    assert r.status_code == 200, r.text
    report_id = r.json()["id"]

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        joins = db.scalars(
            select(ReportJoin).where(ReportJoin.report_definition_id == uuid.UUID(report_id))
        ).all()
        assert len(joins) == 1
        assert joins[0].join_type == "left"
        assert joins[0].left_field == "id"
        assert joins[0].right_field == "voyage_id"
        fields = db.scalars(
            select(ReportField).where(ReportField.report_definition_id == uuid.UUID(report_id))
        ).all()
        assert {f.label for f in fields} == {"Voyage #", "Order #", "Grade"}
        ds_ids = {f.dataset_id for f in fields} | {joins[0].left_dataset_id, joins[0].right_dataset_id}
        datasets = db.scalars(select(ReportDataset).where(ReportDataset.id.in_(ds_ids))).all()
        assert {d.entity for d in datasets} == {"voyages", "bunker_orders"}


# ---------------------------------------------------------------------------
# System reports (regression) + declarative adapters
# ---------------------------------------------------------------------------


def test_system_reports_still_work(client, auth_headers):
    from app.services.report_engine import SYSTEM_REPORTS

    r = client.get(f"{API}/reports/system/seed", headers=auth_headers)
    assert r.status_code == 200, r.text

    reports = client.get(f"{API}/reports", headers=auth_headers).json()
    system = {r_["report_type"]: r_ for r_ in reports if r_["is_system"]}
    assert len(system) == len(SYSTEM_REPORTS)
    for report_type, meta in system.items():
        r = client.post(f"{API}/reports/{meta['id']}/execute", headers=auth_headers, json={})
        assert r.status_code == 200, f"{report_type}: {r.text}"
        result = r.json()
        assert not result.get("error"), f"{report_type}: {result.get('error')}"
        assert result["columns"], f"{report_type}: no columns"
        assert "rows" in result
        for row in result["rows"][:3]:
            assert set(row) == {c["key"] for c in result["columns"]}, f"{report_type} row shape"


def test_system_report_declarative_adapters(client, auth_headers):
    from app.services.report_engine import SYSTEM_REPORT_SPECS

    for report_type in sorted(SYSTEM_REPORT_SPECS):
        r = client.get(f"{API}/reports/system/specs/{report_type}", headers=auth_headers)
        assert r.status_code == 200, r.text
        spec = r.json()["spec"]
        assert validate_spec(spec) == [], f"{report_type} adapter spec invalid"
        p = _preview(client, auth_headers, spec)
        assert p.status_code == 200, f"{report_type}: {p.text}"
        assert p.json()["columns"]

    missing = client.get(f"{API}/reports/system/specs/unicorns", headers=auth_headers)
    assert missing.status_code == 404
