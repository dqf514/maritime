"""审计链防篡改（P1-19 残留项）。

覆盖：
- 每一行审计都带 prev_hash / row_hash，且同租户串成链；
- ``verify_chain`` 能抓到"内容被改"（确证篡改）与"中间行被删"（链断裂）；
- detail 里带 UUID/Decimal 时审计**不会整个丢掉**（老 bug：JSON 列序列化失败
  → 异常被吞 → 行直接没了）；
- HTTP 中间件写的行同样进链；
- 租户管理员可以通过接口自检，非管理员 403。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import sessionmaker

from app.models_audit import AuditLog
from app.services.audit import audit, append_audit_row, verify_chain

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _write(db, tenant_id, action, **kw):
    audit(
        db,
        tenant_id=tenant_id,
        action=action,
        entity_type="test",
        detail={"n": action},
        **kw,
    )


def _rows(db, tenant_id):
    return list(
        db.scalars(
            select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.created_at, AuditLog.id)
        ).all()
    )


# —— 链的基本形状 ——
def test_rows_carry_hash_chain(db_session):
    tid = uuid.uuid4()
    _write(db_session, tid, "a.one")
    _write(db_session, tid, "a.two")
    _write(db_session, tid, "a.three")
    db_session.commit()

    rows = _rows(db_session, tid)
    assert len(rows) == 3
    assert all(r.row_hash for r in rows), "每行都必须有 row_hash"
    # 链首 prev_hash 为空串；后续每行的 prev_hash = 上一行的 row_hash
    assert rows[0].prev_hash == ""
    assert rows[1].prev_hash == rows[0].row_hash
    assert rows[2].prev_hash == rows[1].row_hash
    # 链是按租户串的 —— 另一个租户不能接上这条链
    other = uuid.uuid4()
    _write(db_session, other, "b.one")
    db_session.commit()
    other_rows = _rows(db_session, other)
    assert other_rows[0].prev_hash == ""


def test_verify_chain_clean(db_session):
    tid = uuid.uuid4()
    for i in range(4):
        _write(db_session, tid, f"ok.{i}")
    db_session.commit()

    res = verify_chain(db_session, tid)
    assert res["ok"] is True
    assert res["checked"] == 4
    assert res["tampered"] == []
    assert res["broken_links"] == []


# —— 篡改被抓 ——
def test_tampered_row_is_detected(db_session):
    tid = uuid.uuid4()
    for i in range(3):
        _write(db_session, tid, f"t.{i}")
    db_session.commit()

    victim = _rows(db_session, tid)[1]
    db_session.execute(
        update(AuditLog).where(AuditLog.id == victim.id).values(action="t.tampered")
    )
    db_session.commit()

    res = verify_chain(db_session, tid)
    assert res["ok"] is False
    assert len(res["tampered"]) == 1
    assert res["tampered"][0]["id"] == str(victim.id)
    assert res["tampered"][0]["reason"] == "row_hash_mismatch"


def test_tampered_detail_is_detected(db_session):
    """改明细同样要被抓 —— 只改 action 是不够的。"""
    tid = uuid.uuid4()
    _write(db_session, tid, "d.one")
    db_session.commit()
    victim = _rows(db_session, tid)[0]
    db_session.execute(
        update(AuditLog).where(AuditLog.id == victim.id).values(detail={"n": "forged"})
    )
    db_session.commit()

    res = verify_chain(db_session, tid)
    assert res["ok"] is False
    assert res["tampered"]


def test_deleted_middle_row_breaks_link(db_session):
    tid = uuid.uuid4()
    for i in range(3):
        _write(db_session, tid, f"x.{i}")
    db_session.commit()

    victim = _rows(db_session, tid)[1]
    db_session.execute(delete(AuditLog).where(AuditLog.id == victim.id))
    db_session.commit()

    res = verify_chain(db_session, tid)
    # 删行不会让任何一行的内容哈希失配（删掉的是整行），但链会不连续
    assert res["ok"] is True
    assert len(res["broken_links"]) == 1
    remaining = _rows(db_session, tid)
    assert len(remaining) == 2
    assert res["broken_links"][0]["id"] == str(remaining[1].id)


def test_rewriting_prev_hash_is_detected(db_session):
    """把 prev_hash 改掉以"接上"另一行 —— 本行的哈希会当场失效。"""
    tid = uuid.uuid4()
    for i in range(2):
        _write(db_session, tid, f"p.{i}")
    db_session.commit()
    rows = _rows(db_session, tid)
    db_session.execute(
        update(AuditLog).where(AuditLog.id == rows[1].id).values(prev_hash="deadbeef")
    )
    db_session.commit()

    res = verify_chain(db_session, tid)
    assert res["ok"] is False
    assert res["tampered"]


# —— 老数据不打断链 ——
def test_legacy_rows_without_hash_are_skipped(db_session):
    tid = uuid.uuid4()
    legacy = AuditLog(
        tenant_id=tid,
        action="legacy.row",
        entity_type="test",
        detail={},
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(legacy)
    db_session.commit()

    _write(db_session, tid, "after.legacy")
    db_session.commit()

    res = verify_chain(db_session, tid)
    assert res["ok"] is True
    assert res["checked"] == 1  # 老行没有哈希，不参与校验
    assert res["broken_links"] == []


# —— detail 规范化 ——
def test_detail_with_uuid_is_not_lost(db_session):
    """老 bug：detail 里带 UUID → JSON 列序列化失败 → 审计行整个丢掉。"""
    tid = uuid.uuid4()
    audit(
        db_session,
        tenant_id=tid,
        action="uuid.detail",
        entity_type="test",
        detail={"user_id": uuid.uuid4(), "amount": Decimal("12.34"), "ok": True},
    )
    db_session.commit()

    rows = _rows(db_session, tid)
    assert len(rows) == 1, "审计行不能因为 detail 里有 UUID 就丢掉"
    assert isinstance(rows[0].detail["user_id"], str)
    assert rows[0].detail["amount"] == "12.34"
    assert verify_chain(db_session, tid)["ok"] is True


def test_canonical_detail_is_stable(db_session):
    """同一份 detail 的两种写法要算出同一个哈希（键序无关）。"""
    tid = uuid.uuid4()
    append_audit_row(
        db_session, tenant_id=tid, action="c.one", detail={"a": 1, "b": 2}
    )
    db_session.flush()
    append_audit_row(
        db_session, tenant_id=tid, action="c.two", detail={"b": 2, "a": 1}
    )
    db_session.commit()
    rows = _rows(db_session, tid)
    assert rows[0].row_hash != rows[1].row_hash  # action 不同 → 哈希不同
    assert verify_chain(db_session, tid)["ok"] is True


# —— HTTP 中间件 ——
def test_middleware_rows_are_chained(client, db_session, auth_headers):
    """带 JWT 的写操作 → 中间件补一行审计，且这行也进链。"""
    r = client.post(
        f"{API}/tasks",
        headers=auth_headers,
        json={"title": "audit-chain probe", "priority": "normal"},
    )
    assert r.status_code == 200, r.text

    rows = db_session.scalars(
        select(AuditLog).where(AuditLog.detail["source"].as_string() == "http_middleware")
    ).all()
    assert rows, "中间件应该为写操作落一行审计"
    assert all(x.row_hash for x in rows), "中间件写的行也必须进链"

    # 同一个请求的显式审计行（task.create）也要有哈希
    explicit = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "task.create")
    ).all()
    assert explicit and all(x.row_hash for x in explicit)


# —— 管理端自检接口 ——
def test_verify_endpoint_admin(client, auth_headers):
    r = client.get(f"{API}/admin/security/audit-logs/verify", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ok" in body and "tampered" in body and "broken_links" in body
    assert body["ok"] is True, body


def test_verify_endpoint_forbidden_for_non_admin(client):
    from tests.isolation_helpers import login

    headers = login(client, "charterer@demo.marios")
    r = client.get(f"{API}/admin/security/audit-logs/verify", headers=headers)
    assert r.status_code == 403
