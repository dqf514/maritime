"""Voyage workspace notes / instructions / activity endpoints (Notes·Instructions·Activity 标签)."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_domain import PortCall, SofEvent, Voyage
from app.models_wave1 import Company, Vessel
from tests.isolation_helpers import create_tenant


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db):
    return db.scalar(select(Company).limit(1)).tenant_id


def _uniq():
    return uuid4().hex[:8]


def _build_voyage(db, tid):
    vessel = Vessel(tenant_id=tid, name=f"NT Vessel {_uniq()}", imo=f"9{uuid4().int % 10**6:06d}", flag="SG")
    db.add(vessel)
    db.commit()
    voyage = Voyage(
        tenant_id=tid,
        voyage_no=f"NT-{_uniq()}",
        status="in_progress",
        vessel_id=vessel.id,
        started_at=datetime.now(timezone.utc) - timedelta(days=3),
    )
    db.add(voyage)
    db.commit()
    pc = PortCall(
        tenant_id=tid,
        voyage_id=voyage.id,
        seq=1,
        purpose="load",
        ata=datetime.now(timezone.utc) - timedelta(days=1),
        atd=datetime.now(timezone.utc),
    )
    db.add(pc)
    db.commit()
    db.add(
        SofEvent(
            tenant_id=tid,
            port_call_id=pc.id,
            event_code="COMMENCED",
            event_at=datetime.now(timezone.utc) - timedelta(hours=6),
        )
    )
    db.commit()
    return voyage


def test_notes_crud(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage = _build_voyage(db_session, tid)
    base = f"/api/v1/voyages/{voyage.id}/notes"

    # create — 前端同时发 content 与 body，二者等价
    r = client.post(base, json={"content": "等泊超时，预计让运费", "body": "等泊超时，预计让运费",
                                "note_date": date.today().isoformat()}, headers=auth_headers)
    assert r.status_code == 200, r.text
    note = r.json()
    assert note["content"] == "等泊超时，预计让运费"
    assert note["body"] == note["content"]  # body 是 content 的镜像别名
    assert note["note"] == note["content"]
    assert note["note_date"] == date.today().isoformat()
    assert note["author_name"]  # 当前登录用户

    # list
    r = client.get(base, headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["id"] == note["id"]

    # patch — 只发 body 也要生效（前端 PATCH 同一 payload）
    r = client.patch(f"{base}/{note['id']}", json={"body": "改：与船东共担"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "改：与船东共担"

    # 空内容 → 422
    r = client.post(base, json={"content": "   "}, headers=auth_headers)
    assert r.status_code == 422

    # delete（软删）→ 列表为空
    r = client.delete(f"{base}/{note['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    r = client.get(base, headers=auth_headers)
    assert r.json() == []


def test_instructions_crud_and_kind(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage = _build_voyage(db_session, tid)
    base = f"/api/v1/voyages/{voyage.id}/instructions"

    r = client.post(base, json={"content": "OBO 运行，卸货港先新加坡", "kind": "owner"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    row = r.json()
    assert row["kind"] == "owner"
    assert row["ack"] is False

    r = client.get(base, headers=auth_headers)
    assert r.status_code == 200 and len(r.json()) == 1

    # ack 确认
    r = client.patch(f"{base}/{row['id']}", json={"ack": True}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["ack"] is True

    # notes 与 instructions 互不串台
    assert client.get(f"/api/v1/voyages/{voyage.id}/notes", headers=auth_headers).json() == []


def test_activity_derived(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage = _build_voyage(db_session, tid)
    # 加一条备注，活动流应包含 port/sof/note 三类
    client.post(f"/api/v1/voyages/{voyage.id}/notes", json={"content": "备航完成"}, headers=auth_headers)

    r = client.get(f"/api/v1/voyages/{voyage.id}/activity", headers=auth_headers)
    assert r.status_code == 200, r.text
    items = r.json()
    kinds = {i["kind"] for i in items}
    assert {"port", "sof", "note"} <= kinds
    # 按时间倒序
    times = [i["at"] for i in items if i.get("at")]
    assert times == sorted(times, reverse=True)
    sof = next(i for i in items if i["kind"] == "sof")
    assert sof["title"] == "COMMENCED"


def test_notes_cross_tenant_404(client, auth_headers, db_session):
    tid = _tenant_id(db_session)
    voyage = _build_voyage(db_session, tid)
    _, hb = create_tenant(client, code="ntiso", name="NT Iso", admin_email="admin@ntiso.example.com")
    # 别租户看不到
    assert client.get(f"/api/v1/voyages/{voyage.id}/notes", headers=hb).status_code == 404
    assert client.post(f"/api/v1/voyages/{voyage.id}/notes", json={"content": "x"}, headers=hb).status_code == 404
    # 不存在的航次
    assert client.get(f"/api/v1/voyages/{uuid4()}/notes", headers=auth_headers).status_code == 404
    # 跨租户不能改/删别人的数据
    mine = client.post(f"/api/v1/voyages/{voyage.id}/notes", json={"content": "本租户备注"}, headers=auth_headers).json()
    r = client.patch(
        f"/api/v1/voyages/{voyage.id}/notes/{mine['id']}", json={"content": "hacked"}, headers=hb
    )
    assert r.status_code == 404
    assert client.delete(f"/api/v1/voyages/{voyage.id}/notes/{mine['id']}", headers=hb).status_code == 404
