"""User view-state — tab 未读上标 (unread badges) + mark-seen."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.models_domain import Voyage
from app.models_voyage_ext import VoyageInstruction, VoyageNote
from app.models_wave1 import Company, Vessel
from tests.isolation_helpers import create_tenant

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db):
    return db.scalar(select(Company).limit(1)).tenant_id


def _build_voyage(db, tid):
    vessel = Vessel(tenant_id=tid, name=f"UVS Vessel {uuid4().hex[:6]}", imo=f"9{uuid4().int % 10**6:06d}", flag="SG")
    db.add(vessel)
    db.commit()
    voyage = Voyage(
        tenant_id=tid,
        voyage_no=f"UVS-{uuid4().hex[:6]}",
        status="in_progress",
        vessel_id=vessel.id,
        started_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add(voyage)
    db.commit()
    return voyage


def _other_user(db, tid, me_email="admin@demo.marios"):
    row = db.scalar(select(User).where(User.tenant_id == tid, User.email != me_email, User.status == "active").limit(1))
    assert row is not None, "demo seed should provide a second user"
    return row


def test_unread_excludes_own_and_respects_last_seen(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage = _build_voyage(db_session, tid)
    base = f"{API}/me/unread"

    # 自己创建的备注：count=1 但不算未读
    r = client.post(f"{API}/voyages/{voyage.id}/notes", json={"content": "self note"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.get(base, headers=auth_headers, params={"entity_type": "voyage", "entity_id": str(voyage.id)})
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == {"count": 1, "unread": 0}

    # 他人创建（直接改写 author 模拟同事）→ 未读 1
    rows = client.get(f"{API}/voyages/{voyage.id}/notes", headers=auth_headers).json()
    note = db_session.get(VoyageNote, UUID(rows[0]["id"]))
    note.created_by = _other_user(db_session, tid).id
    db_session.commit()
    r = client.get(base, headers=auth_headers, params={"entity_type": "voyage", "entity_id": str(voyage.id)})
    assert r.json()["notes"] == {"count": 1, "unread": 1}

    # 打开 tab → 已读
    r = client.post(f"{API}/me/viewed", headers=auth_headers, json={
        "entity_type": "voyage", "entity_id": str(voyage.id), "tab": "notes",
    })
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.get(base, headers=auth_headers, params={"entity_type": "voyage", "entity_id": str(voyage.id)})
    assert r.json()["notes"] == {"count": 1, "unread": 0}

    # viewed 可重复打点（upsert，不报错）
    r = client.post(f"{API}/me/viewed", headers=auth_headers, json={
        "entity_type": "voyage", "entity_id": str(voyage.id), "tab": "notes",
    })
    assert r.status_code == 200


def test_tabs_tracked_independently(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage = _build_voyage(db_session, tid)
    colleague = _other_user(db_session, tid).id

    # notes + instructions 各一条（他人创建）
    client.post(f"{API}/voyages/{voyage.id}/notes", json={"content": "n1"}, headers=auth_headers)
    client.post(f"{API}/voyages/{voyage.id}/instructions", json={"content": "i1"}, headers=auth_headers)
    for model in (VoyageNote, VoyageInstruction):
        for n in db_session.scalars(select(model)).all():
            if n.voyage_id == voyage.id:
                n.created_by = colleague
    db_session.commit()

    r = client.get(f"{API}/me/unread", headers=auth_headers,
                   params={"entity_type": "voyage", "entity_id": str(voyage.id)})
    assert r.json()["notes"]["unread"] == 1
    assert r.json()["instructions"]["unread"] == 1

    # 只标记 notes → instructions 仍 unread
    client.post(f"{API}/me/viewed", headers=auth_headers,
                json={"entity_type": "voyage", "entity_id": str(voyage.id), "tab": "notes"})
    r = client.get(f"{API}/me/unread", headers=auth_headers,
                   params={"entity_type": "voyage", "entity_id": str(voyage.id)})
    assert r.json()["notes"]["unread"] == 0
    assert r.json()["instructions"]["unread"] == 1


def test_unread_tenant_isolation_and_unknown(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage = _build_voyage(db_session, tid)
    _, hb = create_tenant(client, code="ntuvs", name="NT UVS", admin_email="admin@ntuvs.example.com")

    # 跨租户：404
    r = client.get(f"{API}/me/unread", headers=hb,
                   params={"entity_type": "voyage", "entity_id": str(voyage.id)})
    assert r.status_code == 404
    # 不存在的航次：404
    r = client.get(f"{API}/me/unread", headers=auth_headers,
                   params={"entity_type": "voyage", "entity_id": str(uuid4())})
    assert r.status_code == 404
    # 未注册的实体类型 → 空注册表（向前兼容）
    r = client.get(f"{API}/me/unread", headers=auth_headers,
                   params={"entity_type": "invoice", "entity_id": str(uuid4())})
    assert r.status_code == 200 and r.json() == {}
