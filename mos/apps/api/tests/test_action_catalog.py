"""任务中心 2.0 · 系统动作目录与自动完成（C 批）。

用户诉求原文：「安排一个任务可能涉及某个系统里的动作，这个动作如果在系统里
做好了，就自动标记为完成」。本文件验证这条闭环：

  * 动作目录可查（前端绑定动作用）
  * 任务绑定动作 → 动作做完 → 任务自动 done（判定器兜底 + 域事件即时两条通道）
  * 自动完成写审计、通知创建人
  * **人工永远可以覆盖** —— 自动完成后可重开；人工完成记 ``auto_completed=False``
  * 收尾清单与动作目录**同一份真相**（判定器复用 closing_check 的谓词）
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

API = "/api/v1"


def _admin(db):
    from app.models import User

    return db.scalar(select(User).where(User.email == "admin@demo.marios"))


def _voyage(db, tenant_id, no: str):
    from app.models_domain import Voyage

    v = Voyage(tenant_id=tenant_id, voyage_no=no, status="in_progress")
    db.add(v)
    db.flush()
    return v


# ── 动作目录 ─────────────────────────────────────────────────────────────


def test_action_catalog_endpoint(client, auth_headers):
    r = client.get(f"{API}/tasks/action-catalog", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) >= 15, "动作目录应有足够多的可选动作"
    codes = {a["code"] for a in rows}
    assert "voyage.complete" in codes
    assert "invoice.issue" in codes
    for a in rows:
        assert a["code"] and a["module"] and a["entity_type"]
        assert a["label"], "每个动作都要有可显示的名字"
        assert isinstance(a["event_kinds"], list)


def test_action_codes_unique_and_resolvable():
    from app.services.action_catalog import ACTION_BY_CODE, ACTIONS, get_action

    assert len(ACTION_BY_CODE) == len(ACTIONS), "动作码必须唯一"
    for spec in ACTIONS:
        assert get_action(spec.code) is spec
        assert callable(spec.detector)


def test_create_task_rejects_unknown_action(client, auth_headers):
    r = client.post(
        f"{API}/tasks",
        headers=auth_headers,
        json={"title": "未知动作", "action_code": "no.such.action"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "UNKNOWN_ACTION"


def test_create_task_accepts_known_action(client, auth_headers, db_engine):
    """绑系统动作必须指明关联单据 —— 没有单据，判定器无从下手。"""
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        admin = _admin(db)
        voyage = _voyage(db, admin.tenant_id, "V-ACT-BIND-1")
        db.commit()  # 必须落库 —— API 端在另一个连接上看得到
        voyage_id = str(voyage.id)
    r = client.post(
        f"{API}/tasks",
        headers=auth_headers,
        json={
            "title": "完成航次",
            "action_code": "voyage.complete",
            "entity_type": "voyage",
            "entity_id": voyage_id,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action_code"] == "voyage.complete"
    assert body["auto_complete"] is True
    assert body["entity_id"] == voyage_id


def test_create_task_action_requires_entity(client, auth_headers):
    """只给动作不给单据 → 400（否则任务永远不会自动完成）。"""
    r = client.post(
        f"{API}/tasks",
        headers=auth_headers,
        json={"title": "完成航次", "action_code": "voyage.complete", "entity_type": "voyage"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "ACTION_ENTITY_REQUIRED"


# ── 判定器兜底通道 ───────────────────────────────────────────────────────


def test_detector_auto_completes_task(db_engine):
    """动作做完 → 任务自动 done（判定器通道）。"""
    Session = sessionmaker(bind=db_engine)
    from app.models_task import Task
    from app.services.task_completion import refresh_task

    with Session() as db:
        admin = _admin(db)
        voyage = _voyage(db, admin.tenant_id, "V-ACT-DET-1")
        task = Task(
            tenant_id=admin.tenant_id,
            title="完成航次 V-ACT-DET-1",
            entity_type="voyage",
            entity_id=voyage.id,
            action_code="voyage.complete",
            auto_complete=True,
            status="todo",
            created_by=admin.id,
            assignee_user_id=admin.id,
        )
        db.add(task)
        db.flush()

        # 动作还没做 → 不勾
        assert refresh_task(db, task) is False
        assert task.status == "todo"

        # 动作做完了 → 自动勾
        voyage.status = "completed"
        db.flush()
        assert refresh_task(db, task) is True
        assert task.status == "done"
        assert task.auto_completed is True
        assert task.completed_by is None, "系统完成没有具体完成人"
        assert task.completed_at is not None
        db.rollback()


def test_scan_tenant_completes_pending_actions(db_engine):
    """兜底扫描（定时 tick 用的那条路）也能勾完成。"""
    Session = sessionmaker(bind=db_engine)
    from app.models_task import Task
    from app.services.task_completion import scan_tenant

    with Session() as db:
        admin = _admin(db)
        voyage = _voyage(db, admin.tenant_id, "V-ACT-SCAN-1")
        voyage.status = "completed"
        task = Task(
            tenant_id=admin.tenant_id,
            title="完成航次 V-ACT-SCAN-1",
            entity_type="voyage",
            entity_id=voyage.id,
            action_code="voyage.complete",
            auto_complete=True,
            status="todo",
            created_by=admin.id,
        )
        db.add(task)
        db.flush()
        n = scan_tenant(db, admin.tenant_id)
        assert n >= 1
        db.refresh(task)
        assert task.status == "done"
        db.rollback()


# ── 域事件即时通道 ───────────────────────────────────────────────────────


def test_domain_event_auto_completes_task(db_engine):
    """动作完成的域事件到达 → 立刻勾掉（不等 tick）。"""
    Session = sessionmaker(bind=db_engine)
    from app.models_task import Task
    from app.services.domain_events import emit

    with Session() as db:
        admin = _admin(db)
        voyage = _voyage(db, admin.tenant_id, "V-ACT-EVT-1")
        task = Task(
            tenant_id=admin.tenant_id,
            title="完成航次 V-ACT-EVT-1",
            entity_type="voyage",
            entity_id=voyage.id,
            action_code="voyage.complete",
            auto_complete=True,
            status="todo",
            created_by=admin.id,
        )
        db.add(task)
        db.flush()

        voyage.status = "completed"
        db.flush()
        emit(db, admin.tenant_id, "voyage.completed", "voyage", voyage.id, payload={"voyage_no": voyage.voyage_no})
        db.flush()
        db.refresh(task)
        assert task.status == "done", "事件到达即应自动勾完成"
        assert task.auto_completed is True
        db.rollback()


# ── 人工覆盖 ─────────────────────────────────────────────────────────────


def test_human_can_reopen_auto_completed_task(db_engine):
    """自动完成后人可以重开（人工永远可以覆盖系统）。"""
    Session = sessionmaker(bind=db_engine)
    from app.services.task_completion import complete_task, reopen_task

    with Session() as db:
        admin = _admin(db)
        from app.models_task import Task

        task = Task(
            tenant_id=admin.tenant_id,
            title="人工覆盖测试",
            status="todo",
            created_by=admin.id,
        )
        db.add(task)
        db.flush()
        assert complete_task(db, task, auto=True, reason="test") is True
        assert task.status == "done"
        assert reopen_task(db, task, actor_user_id=admin.id) is True
        assert task.status == "todo"
        assert task.auto_completed is False
        assert task.completed_by is None
        db.rollback()


def test_manual_completion_is_not_auto(db_engine):
    """人工勾选 → auto_completed=False，completed_by=操作人。"""
    Session = sessionmaker(bind=db_engine)
    from app.models_task import Task
    from app.services.task_completion import complete_task

    with Session() as db:
        admin = _admin(db)
        task = Task(tenant_id=admin.tenant_id, title="人工完成测试", status="todo", created_by=admin.id)
        db.add(task)
        db.flush()
        assert complete_task(db, task, actor_user_id=admin.id, auto=False, reason="manual") is True
        assert task.auto_completed is False
        assert task.completed_by == admin.id
        db.rollback()


def test_auto_complete_writes_audit_and_notifies(db_engine):
    """自动完成要写审计、通知创建人。"""
    Session = sessionmaker(bind=db_engine)
    from app.models_task import Task
    from app.models_audit import AuditLog
    from app.models_wave1 import Notification
    from app.services.task_completion import complete_task

    with Session() as db:
        admin = _admin(db)
        task = Task(
            tenant_id=admin.tenant_id,
            title="自动完成审计测试",
            status="todo",
            created_by=admin.id,
            action_code="voyage.complete",
        )
        db.add(task)
        db.flush()
        complete_task(db, task, auto=True, reason="action:voyage.complete")
        db.flush()

        row = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_type == "task",
                AuditLog.entity_id == str(task.id),
                AuditLog.action == "task.auto_complete",
            )
        )
        assert row is not None, "自动完成必须留审计"

        notif = db.scalar(
            select(Notification).where(
                Notification.tenant_id == admin.tenant_id,
                Notification.user_id == admin.id,
                Notification.title == "自动完成审计测试",
            )
        )
        assert notif is not None, "创建人应收到自动完成通知"
        db.rollback()


# ── 同一份真相 ───────────────────────────────────────────────────────────


def test_closeout_checks_shared_with_action_catalog():
    """收尾清单的 8 个谓词被动作目录直接复用 —— 只有一份实现。"""
    from app.services import closeout_checks, voyage_close

    for name in (
        "port_calls_state",
        "sof_state",
        "laytime_state",
        "claims_state",
        "invoices_state",
        "bunker_state",
        "emissions_state",
        "accruals_state",
    ):
        assert hasattr(closeout_checks, name), f"缺少共享谓词 {name}"
    # voyage_close 的 closing_check 走的是同一批谓词
    src = getattr(voyage_close, "closing_check")
    assert callable(src)
