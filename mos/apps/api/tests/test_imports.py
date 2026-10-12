"""CSV import wizard — /imports/preview + /imports/commit.

覆盖：端口 happy path、非法行拒绝、公式注入拒绝、行数上限、tenant_id 落库、401。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.models_wave1 import Counterparty, Vessel

PORTS_CSV = (
    "name,unlocode,country,timezone\n"
    "Import Port Alpha,IMPA1,CN,Asia/Shanghai\n"
    "Import Port Beta,IMPA2,CN,UTC\n"
)

PORTS_MISSING_NAME = (
    "name,unlocode\n"
    ",IMPA9\n"
    "Import Port Gamma,IMPA3\n"
)

PORTS_FORMULA = (
    "name,unlocode\n"
    "=cmd|'/c calc'!A0,IMPA4\n"
    "Import Port Delta,IMPA5\n"
)


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def test_preview_and_commit_ports(client, auth_headers):
    r = client.post(
        "/api/v1/imports/preview",
        headers=auth_headers,
        json={"entity": "ports", "format": "csv", "content": PORTS_CSV},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity"] == "ports"
    assert body["summary"]["total"] == 2
    assert body["summary"]["valid"] == 2
    assert body["summary"]["invalid"] == 0
    assert body["rows"][0]["row_no"] == 1
    assert body["rows"][0]["data"]["name"] == "Import Port Alpha"
    assert body["rows"][0]["valid"] is True

    valid_rows = [row["data"] for row in body["rows"] if row["valid"]]
    r2 = client.post(
        "/api/v1/imports/commit",
        headers=auth_headers,
        json={"entity": "ports", "rows": valid_rows},
    )
    assert r2.status_code == 200, r2.text
    commit = r2.json()
    assert commit["created"] == 2
    assert commit["failed"] == []
    assert len(commit["created_ids"]) == 2

    listed = client.get("/api/v1/masterdata/ports", headers=auth_headers).json()
    names = {p["name"] for p in listed}
    assert "Import Port Alpha" in names
    assert "Import Port Beta" in names


def test_invalid_row_rejected(client, auth_headers):
    r = client.post(
        "/api/v1/imports/preview",
        headers=auth_headers,
        json={"entity": "ports", "format": "csv", "content": PORTS_MISSING_NAME},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["total"] == 2
    assert body["summary"]["valid"] == 1
    assert body["summary"]["invalid"] == 1

    bad = body["rows"][0]
    assert bad["valid"] is False
    assert bad["errors"], "missing name should produce errors"
    assert any("name" in e for e in bad["errors"])

    good = body["rows"][1]
    assert good["valid"] is True

    # Committing only the valid row succeeds; the invalid one is not included
    r2 = client.post(
        "/api/v1/imports/commit",
        headers=auth_headers,
        json={"entity": "ports", "rows": [good["data"]]},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["created"] == 1


def test_formula_cell_rejected(client, auth_headers):
    r = client.post(
        "/api/v1/imports/preview",
        headers=auth_headers,
        json={"entity": "ports", "format": "csv", "content": PORTS_FORMULA},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["invalid"] >= 1
    formula_row = body["rows"][0]
    assert formula_row["valid"] is False
    assert "formula_not_allowed" in formula_row["errors"]

    # Even if a client bypasses preview, commit must refuse formula cells
    r2 = client.post(
        "/api/v1/imports/commit",
        headers=auth_headers,
        json={
            "entity": "ports",
            "rows": [{"name": "=1+1", "unlocode": "IMPA8"}],
        },
    )
    assert r2.status_code == 200, r2.text
    commit = r2.json()
    assert commit["created"] == 0
    assert commit["failed"][0]["errors"] == ["formula_not_allowed"]


def test_row_limit_rejected(client, auth_headers):
    header = "name,unlocode\n"
    body_rows = "".join(f"Port Limit {i},LIM{i:04d}\n" for i in range(501))
    r = client.post(
        "/api/v1/imports/preview",
        headers=auth_headers,
        json={"entity": "ports", "format": "csv", "content": header + body_rows},
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "ROW_LIMIT"
    assert detail["max_rows"] == 500


def test_tenant_id_set_on_created_rows(client, auth_headers, db_session):
    csv_text = (
        "name,imo,vessel_type,dwt\n"
        "Import Bulk Carrier,9990011,Bulk Carrier,50000\n"
        "Import Tanker,9990012,Tanker,100000\n"
    )
    r = client.post(
        "/api/v1/imports/preview",
        headers=auth_headers,
        json={"entity": "vessels", "format": "csv", "content": csv_text},
    )
    assert r.status_code == 200, r.text
    rows = [row["data"] for row in r.json()["rows"] if row["valid"]]
    assert len(rows) == 2

    r2 = client.post(
        "/api/v1/imports/commit",
        headers=auth_headers,
        json={"entity": "vessels", "rows": rows},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["created"] == 2

    admin = db_session.scalar(select(User).where(User.email == "admin@demo.marios"))
    assert admin is not None
    created = db_session.scalars(
        select(Vessel).where(Vessel.name.in_(["Import Bulk Carrier", "Import Tanker"]))
    ).all()
    assert len(created) == 2
    for v in created:
        assert v.tenant_id == admin.tenant_id, "import must set tenant_id server-side"

    # Counterparties are tenant-scoped too
    cp_csv = "name,type\nImport CP Ltd,owner\n"
    r3 = client.post(
        "/api/v1/imports/preview",
        headers=auth_headers,
        json={"entity": "counterparties", "format": "csv", "content": cp_csv},
    )
    assert r3.status_code == 200, r3.text
    cp_rows = [row["data"] for row in r3.json()["rows"] if row["valid"]]
    r4 = client.post(
        "/api/v1/imports/commit",
        headers=auth_headers,
        json={"entity": "counterparties", "rows": cp_rows},
    )
    assert r4.status_code == 200, r4.text
    assert r4.json()["created"] == 1
    cp = db_session.scalar(select(Counterparty).where(Counterparty.name == "Import CP Ltd"))
    assert cp is not None
    assert cp.tenant_id == admin.tenant_id


def test_requires_auth(client):
    r = client.post(
        "/api/v1/imports/preview",
        json={"entity": "ports", "format": "csv", "content": PORTS_CSV},
    )
    assert r.status_code == 401

    r2 = client.post(
        "/api/v1/imports/commit",
        json={"entity": "ports", "rows": [{"name": "X"}]},
    )
    assert r2.status_code == 401


def test_content_too_large(client, auth_headers):
    content = "name\n" + ("x" * (2 * 1024 * 1024 + 10))
    r = client.post(
        "/api/v1/imports/preview",
        headers=auth_headers,
        json={"entity": "ports", "format": "csv", "content": content},
    )
    assert r.status_code == 413, r.text
    assert r.json()["detail"]["code"] == "CONTENT_TOO_LARGE"
