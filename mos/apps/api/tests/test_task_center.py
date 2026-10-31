"""任务中心 2.0 · 统一 API（D 批）。

覆盖：
  * 六个视角 Tab（我的 / 分配给我的 / 我分配的 / 团队 / 工作包 / OKR）
  * 服务端分页信封 + 筛选器
  * 任务详情（子任务 / 父任务 / 评论 / 动作状态 / 进度）
  * 评论 + @提及 → 被提及人收到通知
  * 工作包 / OKR 目标 / 关键结果 CRUD + 进度上卷
  * 跨租户隔离
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import create_tenant, login

API = "/api/v1"
OPS = "ops@demo.marios"
FIN = "finance@demo.marios"
MGMT = "mgmt@demo.marios"


def _create(client, h, **overrides):
    payload = {"title": "任务中心测试", **overrides}
    r = client.post(f"{API}/tasks", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _user_id(client, h, email: str) -> str:
    rows = client.get(f"{API}/tasks/assignees", headers=h).json()
    return next(u["id"] for u in rows if u["email"] == email)


# ── Tab 与分页 ───────────────────────────────────────────────────────────


def test_task_tabs(client, auth_headers):
    """六个视角 Tab 都能打开，且按"谁的任务"收窄。"""
    h = auth_headers
    ops_id = _user_id(client, h, OPS)

    mine = _create(client, h, title="我建的")
    assigned = _create(client, h, title="派给 ops 的", assignee_user_id=ops_id)

    ops_h = login(client, OPS)

    r = client.get(f"{API}/tasks", headers=ops_h, params={"tab": "assigned_to_me"})
    assert r.status_code == 200, r.text
    ids = [t["id"] for t in r.json()["items"]]
    assert assigned["id"] in ids
    assert mine["id"] not in ids

    r = client.get(f"{API}/tasks", headers=ops_h, params={"tab": "mine"})
    ids = [t["id"] for t in r.json()["items"]]
    assert assigned["id"] in ids

    r = client.get(f"{API}/tasks", headers=h, params={"tab": "assigned_by_me"})
    ids = [t["id"] for t in r.json()["items"]]
    assert assigned["id"] in ids

    # 团队视角：ops 是 mgmt 的下属 → mgmt 看得见 ops 的任务
    mgmt_h = login(client, MGMT)
    r = client.get(f"{API}/tasks", headers=mgmt_h, params={"tab": "team"})
    assert r.status_code == 200, r.text
    ids = [t["id"] for t in r.json()["items"]]
    assert assigned["id"] in ids


def test_task_list_pagination_envelope(client, auth_headers):
    h = auth_headers
    for i in range(5):
        _create(client, h, title=f"分页任务 {i}")
    r = client.get(f"{API}/tasks", headers=h, params={"tab": "mine", "limit": 2, "offset": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"items", "total", "limit", "offset"}
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert body["total"] >= 5
    assert len(body["items"]) <= 2


def test_task_list_filters(client, auth_headers):
    h = auth_headers
    ops_id = _user_id(client, h, OPS)
    _create(client, h, title="筛选目标", priority="urgent", assignee_user_id=ops_id)
    _create(client, h, title="筛选别的", priority="low")

    r = client.get(
        f"{API}/tasks", headers=h, params={"tab": "mine", "priority": "urgent", "assignee_user_id": ops_id}
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items and all(t["priority"] == "urgent" for t in items)

    r = client.get(f"{API}/tasks", headers=h, params={"tab": "mine", "q": "筛选目标"})
    items = r.json()["items"]
    assert any(t["title"] == "筛选目标" for t in items)


def test_task_tab_unknown_rejected(client, auth_headers):
    r = client.get(f"{API}/tasks", headers=auth_headers, params={"tab": "nope"})
    assert r.status_code == 400, r.text


# ── 详情 / 评论 / 提及 ───────────────────────────────────────────────────


def test_task_detail_includes_children_and_progress(client, auth_headers):
    h = auth_headers
    parent = _create(client, h, title="父任务")
    child = _create(client, h, title="子任务", parent_id=parent["id"], weight=2)
    assert child["parent_id"] == parent["id"]

    r = client.get(f"{API}/tasks/{parent['id']}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == parent["id"]
    assert any(c["id"] == child["id"] for c in body["children"])
    assert body["progress"] == 0.0
    assert body["comments"] == []


def test_subtask_completion_rolls_up_progress(client, auth_headers):
    """子任务全完成 → 父任务进度 100%。"""
    h = auth_headers
    parent = _create(client, h, title="进度父任务")
    child = _create(client, h, title="进度子任务", parent_id=parent["id"])
    client.post(f"{API}/tasks/{child['id']}/complete", headers=h)

    r = client.get(f"{API}/tasks/{parent['id']}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["progress"] == 100.0


def test_weighted_progress(client, auth_headers, db_engine):
    """加权进度：权重高的子任务占大头。"""
    h = auth_headers
    parent = _create(client, h, title="加权父任务")
    big = _create(client, h, title="重的子任务", parent_id=parent["id"], weight=3)
    small = _create(client, h, title="轻的子任务", parent_id=parent["id"], weight=1)
    client.post(f"{API}/tasks/{big['id']}/complete", headers=h)

    r = client.get(f"{API}/tasks/{parent['id']}", headers=h)
    assert r.status_code == 200, r.text
    # 3/(3+1) = 75%
    assert r.json()["progress"] == 75.0


def test_task_comment_and_mention_notifies(client, auth_headers):
    h = auth_headers
    ops_id = _user_id(client, h, OPS)
    task = _create(client, h, title="有评论的任务")

    r = client.post(
        f"{API}/tasks/{task['id']}/comments",
        headers=h,
        json={"body": "请看下这条", "mentions": [ops_id]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["body"] == "请看下这条"
    assert body["mentions"] == [ops_id]

    ops_h = login(client, OPS)
    notifs = client.get(f"{API}/notifications", headers=ops_h).json()
    assert any("你被提及" in (n["title"] or "") for n in notifs), "被提及人应收到通知"

    r = client.get(f"{API}/tasks/{task['id']}/comments", headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


def test_task_comment_empty_rejected(client, auth_headers):
    task = _create(client, auth_headers, title="空评论")
    r = client.post(f"{API}/tasks/{task['id']}/comments", headers=auth_headers, json={"body": "   "})
    assert r.status_code == 400, r.text


# ── 工作包 ───────────────────────────────────────────────────────────────


def test_work_package_crud_and_progress(client, auth_headers):
    h = auth_headers
    r = client.post(
        f"{API}/tasks/work-packages",
        headers=h,
        json={"code": "WP-001", "title": "某份合同的工作包"},
    )
    assert r.status_code == 200, r.text
    pkg = r.json()
    assert pkg["code"] == "WP-001"
    assert pkg["progress"] == 0.0

    # 重复 code → 409
    r = client.post(f"{API}/tasks/work-packages", headers=h, json={"code": "WP-001", "title": "重复"})
    assert r.status_code == 409, r.text

    task = _create(client, h, title="包里的任务", work_package_id=pkg["id"])
    client.post(f"{API}/tasks/{task['id']}/complete", headers=h)

    r = client.get(f"{API}/tasks/work-packages", headers=h)
    assert r.status_code == 200, r.text
    row = next(p for p in r.json() if p["id"] == pkg["id"])
    assert row["progress"] == 100.0

    r = client.patch(f"{API}/tasks/work-packages/{pkg['id']}", headers=h, json={"status": "closed"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed"


# ── OKR ──────────────────────────────────────────────────────────────────


def test_objective_and_key_results(client, auth_headers):
    h = auth_headers
    r = client.post(
        f"{API}/tasks/objectives",
        headers=h,
        json={"code": "O-2026", "title": "提升 TCE", "period": "2026Q4"},
    )
    assert r.status_code == 200, r.text
    obj = r.json()
    assert obj["code"] == "O-2026"
    assert obj["progress"] == 0.0

    r = client.post(
        f"{API}/tasks/objectives/{obj['id']}/key-results",
        headers=h,
        json={"title": "TCE 提升 5%", "metric": "tce", "target_value": 5, "current_value": 2.5, "weight": 1},
    )
    assert r.status_code == 200, r.text
    kr = r.json()
    assert kr["title"] == "TCE 提升 5%"

    r = client.get(f"{API}/tasks/objectives/{obj['id']}/key-results", headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    # 目标进度 = KR 进度上卷（current/target = 50%）
    r = client.get(f"{API}/tasks/objectives", headers=h)
    row = next(o for o in r.json() if o["id"] == obj["id"])
    assert row["progress"] == 50.0


def test_objective_duplicate_code(client, auth_headers):
    h = auth_headers
    client.post(f"{API}/tasks/objectives", headers=h, json={"code": "O-DUP", "title": "一个"})
    r = client.post(f"{API}/tasks/objectives", headers=h, json={"code": "O-DUP", "title": "两个"})
    assert r.status_code == 409, r.text


def test_okr_tab_lists_tasks_under_objective(client, auth_headers):
    h = auth_headers
    obj = client.post(f"{API}/tasks/objectives", headers=h, json={"code": "O-TAB", "title": "带任务的目标"}).json()
    task = _create(client, h, title="OKR 子任务", objective_id=obj["id"])
    r = client.get(f"{API}/tasks", headers=h, params={"tab": "okr"})
    assert r.status_code == 200, r.text
    assert any(t["id"] == task["id"] for t in r.json()["items"])


# ── 统计 / 人员 ──────────────────────────────────────────────────────────


def test_task_stats(client, auth_headers):
    h = auth_headers
    _create(client, h, title="统计任务", priority="high")
    r = client.get(f"{API}/tasks/stats", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["open"] >= 1
    assert "overdue" in body and "due_today" in body and "done" in body
    assert isinstance(body["load"], list)


def test_task_people_exposes_reporting_line(client, auth_headers):
    r = client.get(f"{API}/tasks/people", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    by_email = {u["email"]: u for u in rows}
    assert by_email["mgmt@demo.marios"]["manager_user_id"] == by_email["admin@demo.marios"]["id"]
    assert by_email["ops@demo.marios"]["is_report"] is True


# ── 跨租户隔离 ───────────────────────────────────────────────────────────


def test_task_center_cross_tenant(client, auth_headers):
    h = auth_headers
    task = _create(client, h, title="租户隔离任务")
    _, other = create_tenant(client, code="othcenter", name="Other Center Co", admin_email="other-center@example.com")

    assert client.get(f"{API}/tasks/{task['id']}", headers=other).status_code == 404
    assert client.get(f"{API}/tasks/{task['id']}/comments", headers=other).status_code == 404
    assert client.post(f"{API}/tasks/{task['id']}/comments", headers=other, json={"body": "x"}).status_code == 404
    r = client.get(f"{API}/tasks", headers=other, params={"tab": "mine"})
    assert r.status_code == 200
    assert all(t["id"] != task["id"] for t in r.json()["items"])
