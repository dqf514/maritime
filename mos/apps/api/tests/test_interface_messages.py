"""Interface Messages (IMOS Data Center 标配) — list/detail/retry/stats + auth gates.

运行:
    LICENSE_DEV_UNLOCK=all python -m pytest tests/test_interface_messages.py -q
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_interface import InterfaceMessage
from tests.isolation_helpers import create_tenant

API = "/api/v1/interface/messages"


def _session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    return TestingSession()


def _demo_tenant_id(db) -> UUID:
    return db.scalar(select(Tenant).where(Tenant.code == "demo")).id


def _make(db, tenant_id, **kw) -> str:
    row = InterfaceMessage(
        tenant_id=UUID(str(tenant_id)),
        direction=kw.get("direction", "inbound"),
        channel=kw.get("channel", "http"),
        interface_code=kw.get("interface_code", "VESLINK_NOON"),
        external_ref=kw.get("external_ref", "REF-001"),
        status=kw.get("status", "pending"),
        payload=kw.get("payload", {"vessel": "MV Demo", "eta": "2026-10-13"}),
        error_message=kw.get("error_message"),
        retry_count=kw.get("retry_count", 0),
    )
    db.add(row)
    db.commit()
    return str(row.id)


# ── list ────────────────────────────────────────────────────────────────


def test_list_tenant_scoped(client, auth_headers, db_engine):
    db = _session(db_engine)
    tid = _demo_tenant_id(db)
    mine = _make(db, tid, interface_code="VESLINK_NOON", status="success")
    _make(db, tid, interface_code="NOM_TEMPLATE", direction="outbound", status="failed")
    # other tenant row must never leak
    other_tid, _ = create_tenant(
        client, code="imsg-x1", name="IMSG Other", admin_email="imsg-x1@example.com"
    )
    foreign = _make(db, other_tid, interface_code="VESLINK_NOON", status="success")
    db.close()

    r = client.get(API, headers=auth_headers)
    assert r.status_code == 200, r.text
    ids = {row["id"] for row in r.json()}
    assert mine in ids
    assert foreign not in ids
    assert len(ids) == 2

    # filters
    only_failed = client.get(f"{API}?status=failed", headers=auth_headers).json()
    assert [row["interface_code"] for row in only_failed] == ["NOM_TEMPLATE"]
    only_out = client.get(f"{API}?direction=outbound", headers=auth_headers).json()
    assert len(only_out) == 1 and only_out[0]["direction"] == "outbound"
    only_code = client.get(f"{API}?interface_code=VESLINK_NOON", headers=auth_headers).json()
    assert len(only_code) == 1 and only_code[0]["id"] == mine
    # list omits payload body
    assert only_code[0]["payload"] is None

    # newest first + limit/offset
    for i in range(3):
        db = _session(db_engine)
        _make(db, tid, interface_code=f"LIM_{i}", external_ref=f"LIM-{i}")
        db.close()
    page = client.get(f"{API}?limit=2&offset=0", headers=auth_headers).json()
    assert len(page) == 2
    page2 = client.get(f"{API}?limit=2&offset=2", headers=auth_headers).json()
    assert len(page2) == 2
    assert {row["id"] for row in page}.isdisjoint({row["id"] for row in page2})


def test_detail_includes_full_payload(client, auth_headers, db_engine):
    db = _session(db_engine)
    mid = _make(
        db,
        _demo_tenant_id(db),
        payload={"msg": "UNB+UNOA:2", "seq": 7},
        error_message="boom",
    )
    db.close()

    r = client.get(f"{API}/{mid}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == mid
    assert body["payload"] == {"msg": "UNB+UNOA:2", "seq": 7}
    assert body["error_message"] == "boom"
    assert body["created_at"]

    missing = client.get(f"{API}/00000000-0000-0000-0000-000000000001", headers=auth_headers)
    assert missing.status_code == 404


def test_detail_cross_tenant_404(client, auth_headers, db_engine):
    db = _session(db_engine)
    other_tid, _ = create_tenant(
        client, code="imsg-x2", name="IMSG Other2", admin_email="imsg-x2@example.com"
    )
    foreign = _make(db, other_tid)
    db.close()
    r = client.get(f"{API}/{foreign}", headers=auth_headers)
    assert r.status_code == 404, r.text


# ── retry ───────────────────────────────────────────────────────────────


def test_retry_increments_and_processes_inbound_json(client, auth_headers, db_engine):
    db = _session(db_engine)
    mid = _make(
        db,
        _demo_tenant_id(db),
        status="failed",
        payload={"vessel": "MV Demo", "noon": True},
        error_message="upstream timeout",
        retry_count=0,
    )
    db.close()

    r = client.post(f"{API}/{mid}/retry", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["retry_count"] == 1
    assert body["last_retry_at"] is not None
    # stub processor: inbound parse-shaped JSON → success
    assert body["status"] == "success"
    assert body["error_message"] is None

    r2 = client.post(f"{API}/{mid}/retry", headers=auth_headers)
    assert r2.json()["retry_count"] == 2


def test_retry_outbound_fails_honestly(client, auth_headers, db_engine):
    db = _session(db_engine)
    mid = _make(db, _demo_tenant_id(db), direction="outbound", status="failed")
    db.close()

    body = client.post(f"{API}/{mid}/retry", headers=auth_headers).json()
    assert body["retry_count"] == 1
    assert body["status"] == "failed"
    assert body["error_message"] and "no external delivery" in body["error_message"]


def test_retry_non_json_payload_fails_honestly(client, auth_headers, db_engine):
    db = _session(db_engine)
    mid = _make(db, _demo_tenant_id(db), payload="UNB+UNOA:2:SENDER+RECIPIENT")
    db.close()

    body = client.post(f"{API}/{mid}/retry", headers=auth_headers).json()
    assert body["retry_count"] == 1
    assert body["status"] == "failed"
    assert body["error_message"] and "parse-shaped" in body["error_message"]


def test_retry_cross_tenant_404(client, auth_headers, db_engine):
    db = _session(db_engine)
    other_tid, _ = create_tenant(
        client, code="imsg-x3", name="IMSG Other3", admin_email="imsg-x3@example.com"
    )
    foreign = _make(db, other_tid)
    db.close()
    r = client.post(f"{API}/{foreign}/retry", headers=auth_headers)
    assert r.status_code == 404, r.text


# ── stats ───────────────────────────────────────────────────────────────


def test_stats_counts_by_status(client, auth_headers, db_engine):
    db = _session(db_engine)
    tid = _demo_tenant_id(db)
    _make(db, tid, status="pending")
    _make(db, tid, status="success")
    _make(db, tid, status="success")
    _make(db, tid, status="failed")
    other_tid, _ = create_tenant(
        client, code="imsg-x4", name="IMSG Other4", admin_email="imsg-x4@example.com"
    )
    _make(db, other_tid, status="success")  # must not count
    db.close()

    r = client.get(f"{API}/stats", headers=auth_headers)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["total"] == 4
    assert s["by_status"] == {"pending": 1, "success": 2, "failed": 1}
    assert s["last_24h"]["total"] == 4
    assert s["last_24h"]["success"] == 2


def test_stats_last_24h_window(client, auth_headers, db_engine):
    db = _session(db_engine)
    tid = _demo_tenant_id(db)
    old = InterfaceMessage(
        tenant_id=tid,
        direction="inbound",
        channel="file",
        interface_code="OLD_CODE",
        status="success",
        payload={},
    )
    db.add(old)
    db.flush()
    # backdate beyond 24h (SQLite/PG both accept a direct timestamp write)
    db.execute(
        InterfaceMessage.__table__.update()
        .where(InterfaceMessage.id == old.id)
        .values(created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    )
    db.commit()
    db.close()

    s = client.get(f"{API}/stats", headers=auth_headers).json()
    assert s["total"] == 1
    assert s["last_24h"]["total"] == 0


# ── auth gates ──────────────────────────────────────────────────────────


def test_requires_login(client):
    assert client.get(API).status_code == 401
    assert client.get(f"{API}/stats").status_code == 401
    assert client.post(f"{API}/00000000-0000-0000-0000-000000000001/retry").status_code == 401
    assert client.get(f"{API}/00000000-0000-0000-0000-000000000001").status_code == 401


def test_module_gate_403(client, auth_headers, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "license_dev_unlock", "none")
    blocked = client.get(API, headers=auth_headers)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"]["code"] == "MODULE_NOT_LICENSED"
    assert client.get(f"{API}/stats", headers=auth_headers).status_code == 403
    assert (
        client.post(f"{API}/00000000-0000-0000-0000-000000000001/retry", headers=auth_headers).status_code
        == 403
    )
