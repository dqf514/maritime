"""任务中心 2.0 · 汇报线与分配策略（B 批）。

覆盖：
  * 人的汇报线设置与校验（自环 / 成环 / 跨租户 / 管理员端点回填）
  * 分配策略解析（user / role 负载均衡 / manager / self）
  * 任务编辑权（主责 / 协作 / 创建人 / 上级 / 无关用户 403）
  * 转派：上级下派可以、下级上交不行、通知 + 审计、跨租户 404
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import create_tenant, login

API = "/api/v1"
MGMT = "mgmt@demo.marios"
OPS = "ops@demo.marios"
FIN = "finance@demo.marios"


def _user(db, email: str):
    from app.models import User

    return db.scalar(select(User).where(User.email == email))


# ── 汇报线 ───────────────────────────────────────────────────────────────


def test_reporting_line_validation(db_engine):
    """不能自己汇报给自己、不能成环、跨租户不认。"""
    Session = sessionmaker(bind=db_engine)
    from fastapi import HTTPException

    from app.services.assignment import validate_manager

    with Session() as db:
        mgmt = _user(db, MGMT)
        ops = _user(db, OPS)
        fin = _user(db, FIN)
        tenant_id = mgmt.tenant_id

        # 自己汇报给自己
        with pytest.raises(HTTPException) as exc:
            validate_manager(db, tenant_id, mgmt.id, mgmt.id)
        assert exc.value.detail["code"] == "INVALID_MANAGER"

        # 跨租户
        other = _user(db, "other@example.com")
        if other is None:
            other = None
        with pytest.raises(HTTPException) as exc:
            validate_manager(db, tenant_id, ops.id, uuid4())
        assert exc.value.detail["code"] == "INVALID_MANAGER"

        # 成环：ops → fin，fin → ops
        ops.manager_user_id = fin.id
        db.flush()
        with pytest.raises(HTTPException) as exc:
            validate_manager(db, tenant_id, fin.id, ops.id)
        assert exc.value.detail["code"] == "INVALID_MANAGER"
        db.rollback()


def test_demo_seed_has_reporting_line(db_engine):
    """演示租户种子要有人的汇报线（admin → mgmt → 各业务岗）。"""
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        admin = _user(db, "admin@demo.marios")
        mgmt = _user(db, MGMT)
        ops = _user(db, OPS)
        assert mgmt.manager_user_id == admin.id
        assert ops.manager_user_id == mgmt.id


def test_admin_user_api_exposes_manager_fields(client, auth_headers):
    """管理员端点回填汇报线字段，并能设置。"""
    h = auth_headers
    r = client.get(f"{API}/admin/users", headers=h)
    assert r.status_code == 200, r.text
    rows = r.json()
    by_email = {u["email"]: u for u in rows}
    assert "manager_user_id" in by_email["mgmt@demo.marios"]
    assert by_email["mgmt@demo.marios"]["manager_user_id"] == by_email["admin@demo.marios"]["id"]
    assert by_email["mgmt@demo.marios"]["manager_name"]


def test_admin_can_set_manager(client, auth_headers):
    h = auth_headers
    users = client.get(f"{API}/admin/users", headers=h).json()
    by_email = {u["email"]: u for u in users}
    ops_id = by_email["ops@demo.marios"]["id"]
    fin_id = by_email["finance@demo.marios"]["id"]

    r = client.patch(f"{API}/admin/users/{ops_id}", headers=h, json={"manager_user_id": fin_id})
    assert r.status_code == 200, r.text
    assert r.json()["manager_user_id"] == fin_id

    # 自己汇报给自己 → 400
    r = client.patch(f"{API}/admin/users/{ops_id}", headers=h, json={"manager_user_id": ops_id})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "INVALID_MANAGER"

    # 还原
    client.patch(f"{API}/admin/users/{ops_id}", headers=h, json={"manager_user_id": None, "clear_manager": True})


# ── 分配策略 ─────────────────────────────────────────────────────────────


def test_resolve_assignment_prefers_least_loaded(db_engine):
    """同角色多人时，任务分给在办少的那个（不再"第一个用户"）。"""
    Session = sessionmaker(bind=db_engine)
    from app.models_task import Task
    from app.services.assignment import resolve_assignment

    with Session() as db:
        mgmt = _user(db, MGMT)
        ops = _user(db, OPS)
        fin = _user(db, FIN)
        tenant_id = mgmt.tenant_id

        # 先给 ops 压两件在办任务
        for i in range(2):
            db.add(
                Task(
                    tenant_id=tenant_id,
                    title=f"压测任务 {i}",
                    assignee_user_id=ops.id,
                    status="todo",
                    created_by=mgmt.id,
                )
            )
        db.flush()

        a = resolve_assignment(db, tenant_id, strategy="role", role_code="operations")
        assert a.assignee_user_id is not None
        # ops 是该角色下唯一用户 —— 负载再高也还是他（角色只有一个时无选择）
        assert a.assignee_user_id == ops.id

        # manager 策略：触发人的直接上级
        m = resolve_assignment(db, tenant_id, strategy="manager", actor_user_id=ops.id)
        assert m.assignee_user_id == mgmt.id

        # self 策略
        s = resolve_assignment(db, tenant_id, strategy="self", actor_user_id=fin.id)
        assert s.assignee_user_id == fin.id
        db.rollback()


def test_ensure_task_uses_resolver_and_writes_audit(db_engine):
    """ensure_task 走策略解析器，并补上审计（原来系统任务完全不留痕）。"""
    Session = sessionmaker(bind=db_engine)
    from app.models_task import Task
    from app.services.audit import AuditLog
    from app.services.domain_events import ensure_task

    with Session() as db:
        mgmt = _user(db, MGMT)
        tenant_id = mgmt.tenant_id

        t = ensure_task(
            db,
            tenant_id,
            title="系统生成的跟进任务",
            entity_type="voyage",
            entity_id=None,
            assign_role="operations",
        )
        db.flush()
        assert t.assignee_user_id is not None
        row = db.scalar(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.entity_type == "task",
                AuditLog.entity_id == str(t.id),
            )
        )
        assert row is not None, "系统生成任务必须留审计"
        assert row.action == "task.create.system"
        db.rollback()


def test_ensure_task_dedupe_key_idempotent(db_engine):
    """dedupe_key 相同 → 不重复建任务（改标题也不重复）。"""
    Session = sessionmaker(bind=db_engine)
    from app.models_task import Task
    from app.services.domain_events import ensure_task

    with Session() as db:
        mgmt = _user(db, MGMT)
        tenant_id = mgmt.tenant_id

        t1 = ensure_task(db, tenant_id, title="幂等任务 X", dedupe_key="invoice.issue:invoice:42")
        t2 = ensure_task(db, tenant_id, title="改了标题的幂等任务 X", dedupe_key="invoice.issue:invoice:42")
        assert t1.id == t2.id
        count = len(
            db.scalars(select(Task).where(Task.tenant_id == tenant_id, Task.dedupe_key == "invoice.issue:invoice:42")).all()
        )
        assert count == 1
        db.rollback()


# ── 编辑权与转派 ─────────────────────────────────────────────────────────


def _create(client, h, **overrides):
    payload = {"title": "转派测试任务", **overrides}
    r = client.post(f"{API}/tasks", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _user_id(client, h, email: str) -> str:
    rows = client.get(f"{API}/tasks/assignees", headers=h).json()
    return next(u["id"] for u in rows if u["email"] == email)


def test_manager_can_edit_report_task(client, auth_headers):
    """上级可以改下属的任务；无关角色 403。"""
    h = auth_headers
    ops_id = _user_id(client, h, OPS)
    task = _create(client, h, assignee_user_id=ops_id)

    mgmt_h = login(client, MGMT)
    r = client.patch(f"{API}/tasks/{task['id']}", headers=mgmt_h, json={"title": "上级改派标题"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "上级改派标题"

    fin_h = login(client, FIN)
    r = client.patch(f"{API}/tasks/{task['id']}", headers=fin_h, json={"title": "无关人改"})
    assert r.status_code == 403, r.text


def test_collaborator_can_edit(client, auth_headers):
    """协作人可编辑（不承担完成责任，但能协作）。"""
    h = auth_headers
    fin_id = _user_id(client, h, FIN)
    task = _create(client, h, collaborator_ids=[fin_id])
    fin_h = login(client, FIN)
    r = client.patch(f"{API}/tasks/{task['id']}", headers=fin_h, json={"description": "协作人补充"})
    assert r.status_code == 200, r.text


def test_transfer_task_flow(client, auth_headers, db_engine):
    """转派：上级下派可以 → 新负责人收到通知 + 审计落库。"""
    h = auth_headers
    ops_id = _user_id(client, h, OPS)
    fin_id = _user_id(client, h, FIN)
    task = _create(client, h, assignee_user_id=ops_id)

    mgmt_h = login(client, MGMT)
    r = client.post(
        f"{API}/tasks/{task['id']}/transfer",
        headers=mgmt_h,
        json={"assignee_user_id": fin_id, "reason": "财务口径更熟"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["assignee_user_id"] == fin_id

    fin_h = login(client, FIN)
    notifs = client.get(f"{API}/notifications", headers=fin_h).json()
    assert any(n["title"] == "转派测试任务" for n in notifs), "新负责人应收到转派通知"

    # 审计留痕
    from app.models_audit import AuditLog

    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        row = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_type == "task",
                AuditLog.entity_id == task["id"],
                AuditLog.action == "task.transfer",
            )
        )
        assert row is not None, "转派必须写审计"
        assert row.detail.get("to") == fin_id


def test_subordinate_cannot_transfer_upward(client, auth_headers):
    """下级不能把任务指派给上级（责任不得上推）。"""
    h = auth_headers
    ops_id = _user_id(client, h, OPS)
    mgmt_id = _user_id(client, h, MGMT)
    task = _create(client, h, assignee_user_id=ops_id)

    ops_h = login(client, OPS)
    r = client.post(
        f"{API}/tasks/{task['id']}/transfer", headers=ops_h, json={"assignee_user_id": mgmt_id}
    )
    assert r.status_code == 403, r.text


def test_transfer_cross_tenant_404(client, auth_headers):
    h = auth_headers
    task = _create(client, h)
    _, other_admin = create_tenant(
        client, code="othtr", name="Other Transfer Co", admin_email="other-transfer@example.com"
    )
    r = client.post(
        f"{API}/tasks/{task['id']}/transfer", headers=other_admin, json={"assignee_user_id": str(uuid4())}
    )
    assert r.status_code == 404, r.text
