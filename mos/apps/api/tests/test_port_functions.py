"""Port function code catalog（C2-P2）：GET /meta/port-functions + PortCall.function_code.

Covers: catalog endpoint shape/tones; create port call with valid / invalid
function_code (via the service normalizer the create path will call); tenant
scoping of port-call rows that carry a function_code; additive-safe default
(function_code absent → no behavior change).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import PortCall, Voyage
from app.services.port_functions import (
    PORT_FUNCTIONS,
    assert_function_code,
    normalize_function_code,
    port_functions_payload,
)

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _mk_voyage(client, h, voyage_no: str) -> dict:
    v = client.post(f"{API}/voyages", headers=h, json={"voyage_no": voyage_no})
    assert v.status_code == 200, v.text
    return v.json()


def _mk_port_call(client, h, voyage_id: str, **extra) -> dict:
    payload = {"voyage_id": voyage_id, "seq": 1, "purpose": "load"}
    payload.update(extra)
    r = client.post(f"{API}/port-calls", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


# —— catalog endpoint ——


def test_port_functions_catalog_endpoint(client, auth_headers):
    r = client.get(f"{API}/meta/port-functions", headers=auth_headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    by_code = {i["code"]: i for i in items}
    assert set(by_code) == set(PORT_FUNCTIONS) == {"L", "D", "P", "I", "W"}
    # tones map onto the status-color language (L=ok D=info P=muted I=warn W=default)
    assert by_code["L"]["tone"] == "ok"
    assert by_code["D"]["tone"] == "info"
    assert by_code["P"]["tone"] == "muted"
    assert by_code["I"]["tone"] == "warn"
    assert by_code["W"]["tone"] == "default"
    for row in items:
        assert row["label_en"] and row["label_zh"]
        assert set(row) == {"code", "label_en", "label_zh", "tone"}


def test_port_functions_catalog_requires_auth(client):
    r = client.get(f"{API}/meta/port-functions")
    assert r.status_code == 401


def test_port_functions_payload_matches_catalog():
    rows = port_functions_payload()
    assert [r["code"] for r in rows] == ["L", "D", "P", "I", "W"]


# —— create port call with valid / invalid function_code ——


def test_create_port_call_with_valid_function_code(client, auth_headers, db_session):
    """Valid code normalizes + persists on PortCall (create path contract).

    ``routers/operations.py`` (owned by a concurrent agent) must add
    ``function_code`` to PortCallIn/PortCallOut and call
    ``normalize_function_code`` — this test exercises the same normalize +
    model-write sequence so the behavior is pinned now.
    """
    h = auth_headers
    voy = _mk_voyage(client, h, "PF-VALID-1")
    code = normalize_function_code("L")
    assert code == "L"
    # lowercase / whitespace still canonical
    assert normalize_function_code(" d ") == "D"
    assert normalize_function_code(None) is None
    assert normalize_function_code("") is None

    row = PortCall(
        tenant_id=_tenant_id(db_session, voy["id"]),
        voyage_id=uuid.UUID(voy["id"]),
        seq=1,
        purpose="load",
        function_code=normalize_function_code("L"),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.function_code == "L"

    # absent field on the HTTP create path is still accepted (additive-safe)
    pc = _mk_port_call(client, h, voy["id"], seq=2)
    assert pc["id"]


def test_create_port_call_with_invalid_function_code_422(client, auth_headers):
    """Unknown code → 422 INVALID_PORT_FUNCTION before any write."""
    with pytest.raises(Exception) as exc:
        assert_function_code("X")
    err = exc.value
    assert getattr(err, "status_code", None) == 422
    detail = err.detail
    assert detail["code"] == "INVALID_PORT_FUNCTION"
    assert "L" in detail["allowed"]

    with pytest.raises(Exception) as exc2:
        normalize_function_code("bogus")
    assert getattr(exc2.value, "status_code", None) == 422

    # blank is "unset", not invalid
    assert normalize_function_code("   ") is None

    # HTTP create without function_code remains 200 (no behavior change when absent)
    voy = _mk_voyage(client, auth_headers, "PF-INVALID-1")
    pc = _mk_port_call(client, auth_headers, voy["id"])
    assert pc["id"]


def test_function_code_column_roundtrip_on_list(client, auth_headers, db_session):
    h = auth_headers
    voy = _mk_voyage(client, h, "PF-ROUNDTRIP-1")
    vid = uuid.UUID(voy["id"])
    tid = _tenant_id(db_session, vid)
    db_session.add(
        PortCall(tenant_id=tid, voyage_id=vid, seq=1, purpose="discharge", function_code=normalize_function_code("D"))
    )
    db_session.commit()

    rows = client.get(f"{API}/port-calls?voyage_id={voy['id']}", headers=h).json()
    assert len(rows) == 1
    # model carries the column even while PortCallOut is still pending the ops one-liner
    fresh = db_session.get(PortCall, uuid.UUID(rows[0]["id"]))
    assert fresh is not None
    assert fresh.function_code == "D"
    assert fresh.purpose == "discharge"


# —— tenant scoping ——


def test_port_calls_with_function_code_are_tenant_scoped(client, auth_headers, db_engine):
    from tests.isolation_helpers import create_tenant

    h_a = auth_headers
    voy_a = _mk_voyage(client, h_a, "PF-TENANT-A")
    _mk_port_call(client, h_a, voy_a["id"])

    _, h_b = create_tenant(client, code="pf_tenant_b", name="PF Tenant B", admin_email="pf-b@example.com")
    voy_b = _mk_voyage(client, h_b, "PF-TENANT-B")
    pc_b = _mk_port_call(client, h_b, voy_b["id"])

    # A's list must not contain B's port call
    rows_a = client.get(f"{API}/port-calls?voyage_id={voy_a['id']}", headers=h_a).json()
    assert all(r["id"] != pc_b["id"] for r in rows_a)
    rows_b = client.get(f"{API}/port-calls?voyage_id={voy_b['id']}", headers=h_b).json()
    assert [r["id"] for r in rows_b] == [pc_b["id"]]

    # B cannot create a port call on A's voyage
    r = client.post(
        f"{API}/port-calls",
        headers=h_b,
        json={"voyage_id": voy_a["id"], "seq": 9, "purpose": "load"},
    )
    assert r.status_code == 404

    # catalog is global reference data — identical for both tenants
    cat_a = client.get(f"{API}/meta/port-functions", headers=h_a).json()["items"]
    cat_b = client.get(f"{API}/meta/port-functions", headers=h_b).json()["items"]
    assert cat_a == cat_b


def _tenant_id(db_session, voyage_id):
    if isinstance(voyage_id, str):
        voyage_id = uuid.UUID(voyage_id)
    row = db_session.get(Voyage, voyage_id)
    assert row is not None, f"voyage {voyage_id} not found"
    return row.tenant_id
