"""Request H canaries — 操作日志 / 创建人修改人 / 行级数据权限 / 上传设置 / 平台资源."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_domain import Invoice, Voyage
from app.models_saas import RoleDataScope
from app.models_wave1 import Vessel
from app.services.data_scope import apply_data_scope, effective_scope
from app.services.upload_policy import (
    DEFAULT_UPLOAD_POLICY,
    assert_upload_allowed,
    get_upload_policy,
    save_upload_policy,
)
from tests.isolation_helpers import login, platform_login

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


# ── H3 upload policy ──

def test_upload_policy_defaults_and_assert(db_session):
    # 未配置 → 保守默认
    pol = get_upload_policy(db_session, "image")
    assert pol["max_bytes"] == DEFAULT_UPLOAD_POLICY["image"]["max_bytes"]
    assert ".png" in pol["exts"]
    # assert：超限 / 非法扩展抛 400
    with pytest.raises(HTTPException) as e:
        assert_upload_allowed(pol, pol["max_bytes"] + 1, "logo.png")
    assert e.value.detail["code"] == "FILE_TOO_LARGE"
    with pytest.raises(HTTPException) as e:
        assert_upload_allowed(pol, 10, "logo.exe")
    assert e.value.detail["code"] == "UNSUPPORTED_TYPE"
    # 合法
    assert assert_upload_allowed(pol, 100, "logo.PNG") == ".png"


def test_upload_settings_roundtrip_platform_admin(client):
    ph = platform_login(client)
    r = client.get(f"{API}/platform/upload-settings", headers=ph)
    assert r.status_code == 200, r.text
    kinds = r.json()["kinds"]
    assert set(kinds) >= {"document", "image", "data"}

    # 收紧 image 上限
    r = client.put(f"{API}/platform/upload-settings", headers=ph, json={
        "kinds": {"image": {"max_bytes": 1234, "exts": [".png", ".jpg"]}},
    })
    assert r.status_code == 200, r.text
    assert r.json()["kinds"]["image"]["max_bytes"] == 1234
    r = client.get(f"{API}/platform/upload-settings", headers=ph)
    assert r.json()["kinds"]["image"]["max_bytes"] == 1234
    assert r.json()["kinds"]["image"]["exts"] == [".jpg", ".png"]


# ── H4 platform resources + per-tenant usage ──

def test_platform_health_resources_and_tenants(client):
    ph = platform_login(client)
    r = client.get(f"{API}/platform/health", headers=ph)
    assert r.status_code == 200, r.text
    body = r.json()
    res = body["resources"]
    assert res["db_up"] is True
    assert res["disk_pct"] >= 0
    assert "db_size_bytes" in res
    assert isinstance(body["tenants_usage"], list)
    assert any(t["code"] == "demo" for t in body["tenants_usage"])


# ── H1 activity feed (supervisor sees all, click-through href) ──

def test_activity_feed_includes_audited_action_with_href(client, auth_headers, db_session):
    # 建航次（create 不写审计）→ PATCH 触发 voyage.update 审计
    vessel = db_session.scalar(select(Vessel).limit(1))
    r = client.post(f"{API}/voyages", headers=auth_headers, json={
        "voyage_no": f"ACT-{uuid4().hex[:6]}", "vessel_id": str(vessel.id) if vessel else None,
    })
    assert r.status_code == 200, r.text
    vid = r.json()["id"]
    r = client.patch(f"{API}/voyages/{vid}", headers=auth_headers, json={"cargo": "coal"})
    assert r.status_code == 200, r.text

    r = client.get(f"{API}/activity/feed", headers=auth_headers, params={"limit": 100})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["supervisor"] is True  # demo admin = tenant_admin
    hit = next((i for i in body["items"] if i["action"] == "voyage.update" and i["entity_id"] == vid), None)
    assert hit is not None, body["items"][:5]
    assert hit["href"] == f"/operations/voyages/{vid}/workspace"


# ── H2a attribution (durable columns on invoice) ──

def test_invoice_attribution_from_durable_columns(client, auth_headers, db_session):
    from tests.isolation_helpers import _post

    inv = _post(client, "/invoices", auth_headers, json={"amount": 4200})
    r = client.get(f"{API}/meta/attribution", headers=auth_headers,
                   params={"entity_type": "invoice", "entity_id": inv["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created_by"] is not None
    assert body["created_at"] is not None


# ── H2b row-level data scope (own vs all, most-permissive wins) ──

def _make_ops_user(client, h):
    email = f"ops-{uuid4().hex[:6]}@example.com"
    client.post(f"{API}/admin/users", headers=h, json={
        "email": email, "full_name": "Ops Tester", "password": "Demo1234!", "role_codes": ["operations"],
    })
    return login(client, email, tenant_code="demo", password="Demo1234!")


def test_data_scope_own_narrows_voyage_list(client, auth_headers, db_session):
    # admin 建一个航次（created_by = admin）
    r = client.post(f"{API}/voyages", headers=auth_headers, json={"voyage_no": f"DS-{uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    admin_voyage = r.json()["id"]

    # 默认 all：ops 能看到 admin 的航次
    oh = _make_ops_user(client, auth_headers)
    r = client.get(f"{API}/voyages", headers=oh)
    assert r.status_code == 200, r.text
    assert admin_voyage in [v["id"] for v in r.json()]

    # admin 把 operations 角色收窄到 own
    r = client.put(f"{API}/admin/data-scopes", headers=auth_headers, json={
        "role_code": "operations", "module": "operations", "scope": "own",
    })
    assert r.status_code == 200, r.text

    # ops 现在只看得到自己创建的（看不到 admin 的）
    r = client.get(f"{API}/voyages", headers=oh)
    assert r.status_code == 200, r.text
    ids = [v["id"] for v in r.json()]
    assert admin_voyage not in ids

    # ops 自己建一个 → 只看得到它
    r = client.post(f"{API}/voyages", headers=oh, json={"voyage_no": f"OPS-{uuid4().hex[:6]}"})
    assert r.status_code == 200, r.text
    own = r.json()["id"]
    r = client.get(f"{API}/voyages", headers=oh)
    ids = [v["id"] for v in r.json()]
    assert own in ids and admin_voyage not in ids

    # admin（supervisor）不受影响：仍看得到全部
    r = client.get(f"{API}/voyages", headers=auth_headers)
    ids = [v["id"] for v in r.json()]
    assert admin_voyage in ids and own in ids


def test_effective_scope_most_permissive_wins(db_session):
    from app.models import User

    admin = db_session.scalar(select(User).where(User.email == "admin@demo.marios"))
    tid = admin.tenant_id
    # 非主管、无规则 → all
    assert effective_scope(db_session, tid, ["operations"], "operations") == "all"
    # own 规则 → own
    db_session.add(RoleDataScope(tenant_id=tid, role_code="operations", module="operations", scope="own"))
    db_session.commit()
    assert effective_scope(db_session, tid, ["operations"], "operations") == "own"
    # 主管永远 all（即便同时有 own 规则）
    assert effective_scope(db_session, tid, ["operations", "management"], "operations") == "all"
    # 多角色 most-permissive：另一角色授 all → all
    db_session.add(RoleDataScope(tenant_id=tid, role_code="chartering", module="operations", scope="all"))
    db_session.commit()
    assert effective_scope(db_session, tid, ["operations", "chartering"], "operations") == "all"
