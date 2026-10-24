"""C2-P2 航次批量操作 + C2-P3 航次行程模板。

- batch close happy path（in_progress → completed，合法转移）
- 混合合法/非法 → 部分成功（ok + failed 并存，200）
- 全部失败 → 409 带第一个错误
- 跨租户 id 记入 failed（NOT_FOUND），不泄露存在性
- batch close 角色门禁（viewer → 403 FORBIDDEN）
- voyage_ids > 200 → 422 BATCH_TOO_LARGE
- assign 写 meta.operator
- copy-itinerary 复制挂靠（seq/purpose/function_code/port/eta/etd）+ 租户隔离
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import Voyage
from tests.isolation_helpers import create_tenant

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _uniq() -> str:
    return uuid4().hex[:8]


def _rows(payload) -> list:
    """航次列表现在返回 U1 分页信封 {items,total,limit,offset}（P1-28）。

    旧断言直接对数组取下标 —— 这里统一拆信封，避免测试与实现两套形状。
    """
    if isinstance(payload, dict):
        return payload["items"]
    return payload


def _mk_voyage(client, h, suffix: str = "") -> dict:
    r = client.post(f"{API}/voyages", headers=h, json={"voyage_no": f"VB-{_uniq()}{suffix}"})
    assert r.status_code == 200, r.text
    return r.json()


def _move(client, h, voyage_id: str, target: str):
    r = client.post(f"{API}/voyages/{voyage_id}/transition", headers=h, json={"target": target})
    assert r.status_code == 200, r.text
    return r.json()


def _login(client, email: str, tenant_code: str = "demo", password: str = "Demo1234!") -> dict[str, str]:
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password, "tenant_code": tenant_code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── Feature 1: batch operations ──────────────────────────────────────────


def test_batch_close_happy_path(client, auth_headers):
    """两条 in_progress 航次批量 close → 全部 completed（部分成功允许的正例）。"""
    h = auth_headers
    v1 = _mk_voyage(client, h)
    v2 = _mk_voyage(client, h)
    _move(client, h, v1["id"], "in_progress")
    _move(client, h, v2["id"], "in_progress")

    r = client.post(
        f"{API}/voyages/batch",
        headers=h,
        json={"action": "close", "voyage_ids": [v1["id"], v2["id"]]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["ok"]) == sorted([v1["id"], v2["id"]])
    assert body["failed"] == []

    for vid in (v1["id"], v2["id"]):
        row = _rows(client.get(f"{API}/voyages", headers=h).json())
        hit = next(x for x in row if x["id"] == vid)
        assert hit["status"] == "completed"


def test_batch_mixed_legal_illegal_partial(client, auth_headers):
    """in_progress 可关、planned 不可直接 completed → 200 部分成功。"""
    h = auth_headers
    good = _mk_voyage(client, h)
    bad = _mk_voyage(client, h)  # stays planned
    _move(client, h, good["id"], "in_progress")

    r = client.post(
        f"{API}/voyages/batch",
        headers=h,
        json={"action": "close", "voyage_ids": [good["id"], bad["id"]]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] == [good["id"]]
    assert len(body["failed"]) == 1
    fail = body["failed"][0]
    assert fail["id"] == bad["id"]
    assert fail["code"] == "INVALID_STATE"

    listed = _rows(client.get(f"{API}/voyages", headers=h).json())
    assert next(x for x in listed if x["id"] == good["id"])["status"] == "completed"
    assert next(x for x in listed if x["id"] == bad["id"])["status"] == "planned"


def test_batch_all_failed_returns_409(client, auth_headers):
    """零成功 → 409 + 第一个错误 code。"""
    h = auth_headers
    v = _mk_voyage(client, h)  # planned，close 不合法
    r = client.post(f"{API}/voyages/batch", headers=h, json={"action": "close", "voyage_ids": [v["id"]]})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "INVALID_STATE"
    assert detail["failed"][0]["id"] == v["id"]


def test_batch_foreign_id_reported_not_leaked(client, auth_headers, db_session):
    """他租户航次 id 记入 failed NOT_FOUND，不整体 404、不泄露存在性。"""
    h = auth_headers
    mine = _mk_voyage(client, h)
    _move(client, h, mine["id"], "in_progress")

    _tid, h2 = create_tenant(client, code=f"vbx{_uniq()[:6]}", name="VBX", admin_email=f"vbx-{_uniq()}@example.com")
    foreign = _mk_voyage(client, h2)

    r = client.post(
        f"{API}/voyages/batch",
        headers=h,
        json={"action": "close", "voyage_ids": [mine["id"], foreign["id"]]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] == [mine["id"]]
    assert len(body["failed"]) == 1
    fail = body["failed"][0]
    assert fail["id"] == foreign["id"]
    assert fail["code"] == "NOT_FOUND"
    # 他租户航次状态不受影响（未被关闭）
    rows = _rows(client.get(f"{API}/voyages", headers=h2).json())
    assert next(x for x in rows if x["id"] == foreign["id"])["status"] == "planned"


def test_batch_close_role_forbidden(client, auth_headers):
    """viewer 角色不得 batch close → 403 FORBIDDEN。"""
    h = auth_headers
    email = f"vb-viewer-{_uniq()}@example.com"
    r = client.post(
        f"{API}/admin/users",
        headers=h,
        json={"email": email, "full_name": "VB Viewer", "password": "Demo1234!", "role_codes": ["viewer"]},
    )
    assert r.status_code == 200, r.text
    hv = _login(client, email)

    v = _mk_voyage(client, h)
    _move(client, h, v["id"], "in_progress")
    r2 = client.post(f"{API}/voyages/batch", headers=hv, json={"action": "close", "voyage_ids": [v["id"]]})
    assert r2.status_code == 403, r2.text
    assert r2.json()["detail"]["code"] == "FORBIDDEN"
    # 航次未被关闭
    listed = _rows(client.get(f"{API}/voyages", headers=h).json())
    assert next(x for x in listed if x["id"] == v["id"])["status"] == "in_progress"


def test_batch_too_large_422(client, auth_headers):
    ids = [str(uuid4()) for _ in range(201)]
    r = client.post(f"{API}/voyages/batch", headers=auth_headers, json={"action": "close", "voyage_ids": ids})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "BATCH_TOO_LARGE"


def test_batch_assign_persists_operator(client, auth_headers, db_session):
    h = auth_headers
    v = _mk_voyage(client, h)
    r = client.post(
        f"{API}/voyages/batch",
        headers=h,
        json={"action": "assign", "voyage_ids": [v["id"]], "operator": "Chief Ops"},
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    row = db_session.get(Voyage, UUID(v["id"]))
    assert (row.meta or {}).get("operator") == "Chief Ops"
    assert row.status == "planned"


def test_batch_reopen_moves_completed_back_to_in_progress(client, auth_headers, db_session):
    """reopen 走 completed → in_progress 边：状态回退、清 completed_at、保留 started_at；cancelled 仍终态。"""
    h = auth_headers
    v = _mk_voyage(client, h)
    _move(client, h, v["id"], "in_progress")
    _move(client, h, v["id"], "completed")
    db_session.expire_all()
    before = db_session.get(Voyage, UUID(v["id"]))
    started = before.started_at
    assert before.completed_at is not None

    r = client.post(f"{API}/voyages/batch", headers=h, json={"action": "reopen", "voyage_ids": [v["id"]]})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] == [v["id"]]
    assert not r.json()["failed"]
    db_session.expire_all()
    row = db_session.get(Voyage, UUID(v["id"]))
    assert row.status == "in_progress"
    assert row.completed_at is None
    assert row.started_at == started

    # cancelled 仍是终态：reopen → INVALID_STATE
    v2 = _mk_voyage(client, h)
    _move(client, h, v2["id"], "cancelled")
    r = client.post(f"{API}/voyages/batch", headers=h, json={"action": "reopen", "voyage_ids": [v2["id"]]})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "INVALID_STATE"


# ── Feature 2: copy-itinerary ────────────────────────────────────────────


def _mk_port_call(client, h, voyage_id: str, **kw) -> dict:
    payload = {"voyage_id": voyage_id, "seq": 1, "purpose": "load"}
    payload.update(kw)
    r = client.post(f"{API}/port-calls", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_copy_itinerary_copies_port_calls(client, auth_headers, db_session):
    """新航次 planned，挂靠 seq/purpose/function_code/port/eta/etd/agent 复制；实际执行时间不复制。"""
    h = auth_headers
    src = _mk_voyage(client, h, suffix="-SRC")
    eta = "2026-05-01T06:00:00+00:00"
    etd = "2026-05-01T18:00:00+00:00"
    _mk_port_call(client, h, src["id"], seq=1, purpose="load", eta=eta, etd=etd, agent="Agent A")
    _mk_port_call(client, h, src["id"], seq=2, purpose="discharge")

    r = client.post(f"{API}/voyages/{src['id']}/copy-itinerary", headers=h)
    assert r.status_code == 200, r.text
    new_v = r.json()
    assert new_v["id"] != src["id"]
    assert new_v["status"] == "planned"
    assert new_v["voyage_no"].startswith(src["voyage_no"])

    pcs = client.get(f"{API}/port-calls?voyage_id={new_v['id']}", headers=h).json()
    assert len(pcs) == 2
    by_seq = {p["seq"]: p for p in pcs}
    assert by_seq[1]["purpose"] == "load"
    # SQLite DateTime 列可能丢失 tzinfo — 比较前缀即可
    assert by_seq[1]["eta"].startswith("2026-05-01T06:00:00")
    assert by_seq[1]["etd"].startswith("2026-05-01T18:00:00")
    assert by_seq[1]["agent"] == "Agent A"
    assert by_seq[2]["purpose"] == "discharge"
    # 执行事实不复制
    assert by_seq[1]["ata"] is None
    assert by_seq[1]["atd"] is None
    assert by_seq[1]["nor_at"] is None

    db_session.expire_all()
    row = db_session.get(Voyage, UUID(new_v["id"]))
    assert row.meta.get("copied_from") == src["id"]


def test_copy_itinerary_tenant_isolation(client, auth_headers, db_session):
    """他租户航次 id → 404，不创建副本。"""
    h = auth_headers
    _tid, h2 = create_tenant(client, code=f"vbi{_uniq()[:6]}", name="VBI", admin_email=f"vbi-{_uniq()}@example.com")
    foreign = _mk_voyage(client, h2)
    _mk_port_call(client, h2, foreign["id"], seq=1, purpose="load")

    r = client.post(f"{API}/voyages/{foreign['id']}/copy-itinerary", headers=auth_headers)
    assert r.status_code == 404, r.text

    # 本租户没有产生副本
    rows = _rows(client.get(f"{API}/voyages", headers=auth_headers).json())
    assert not any(x["voyage_no"].startswith(foreign["voyage_no"]) for x in rows)


def test_copy_itinerary_as_template_flag(client, auth_headers, db_session):
    """as_template=true 仅在 meta 记录标记，不额外落库。"""
    h = auth_headers
    src = _mk_voyage(client, h, suffix="-TPL")
    _mk_port_call(client, h, src["id"], seq=1, purpose="load")

    r = client.post(f"{API}/voyages/{src['id']}/copy-itinerary?as_template=true", headers=h)
    assert r.status_code == 200, r.text
    new_v = r.json()
    db_session.expire_all()
    row = db_session.get(Voyage, UUID(new_v["id"]))
    assert row.meta.get("as_template") is True
    assert row.meta.get("copied_from") == src["id"]
