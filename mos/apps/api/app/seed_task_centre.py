"""任务中心 2.0 的演示数据：工作包 + OKR 目标树 + 任务挂接。

为什么要有：任务中心的六个 Tab 里，「工作包」和「OKR」是**组织视角** ——
没有工作包就看不到"一份合同拆成多少子任务"，没有目标就看不到"进度如何上卷"。
演示租户原本只有零散的任务（业务事件自动生成的那些），这两层结构是空的，
Tab 打开只能看到空白 —— 演示时讲不清"任务中心是个整体"这件事。

结构（演示租户）::

    OKR 目标 O-DEMO-2026Q4「提升航次执行与收尾准时率」
      ├── KR 航次收尾任务按期完成率（90%，现 62%）
      └── KR 关键动作自动化覆盖率（80%，现 35%）
              │
              ├── 工作包 WP-VOYAGE-CLOSEOUT（航次 V-xxxxx 收尾）
              │     └── 根任务「航次收尾统筹」→ 3 个子任务（2 已完成）
              └── 工作包 WP-CHARTER-EXEC（合同 CP-xxxxx 执行）
                    └── 根任务「合同执行统筹」→ 2 个子任务（待办）

幂等：工作包/目标按 ``code`` 判存，根任务按 ``dedupe_key`` 判存，
重复启动不重复建；任务挂接只补 NULL 的挂接字段，不覆盖已有归属。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session


def _ensure_work_package(
    db: Session,
    tenant_id: UUID,
    *,
    code: str,
    title: str,
    description: str,
    entity_type: str | None,
    entity_id: UUID | None,
    owner_user_id: UUID | None,
    created_by: UUID | None,
    period: str,
):
    from app.models_task_center import WorkPackage

    pkg = db.scalar(select(WorkPackage).where(WorkPackage.tenant_id == tenant_id, WorkPackage.code == code))
    if pkg is not None:
        return pkg
    pkg = WorkPackage(
        tenant_id=tenant_id,
        code=code,
        title=title,
        description=description,
        entity_type=entity_type,
        entity_id=entity_id,
        owner_user_id=owner_user_id,
        period=period,
        status="open",
        created_by=created_by,
    )
    db.add(pkg)
    db.flush()
    return pkg


def _ensure_objective(
    db: Session,
    tenant_id: UUID,
    *,
    code: str,
    title: str,
    description: str,
    owner_user_id: UUID | None,
    created_by: UUID | None,
    period: str,
    weight: str = "1",
):
    from app.models_task_center import Objective

    obj = db.scalar(select(Objective).where(Objective.tenant_id == tenant_id, Objective.code == code))
    if obj is not None:
        return obj
    obj = Objective(
        tenant_id=tenant_id,
        code=code,
        title=title,
        description=description,
        owner_user_id=owner_user_id,
        period=period,
        weight=Decimal(weight),
        status="active",
        created_by=created_by,
    )
    db.add(obj)
    db.flush()
    return obj


def _ensure_key_result(
    db: Session,
    tenant_id: UUID,
    *,
    objective_id: UUID,
    title: str,
    metric: str,
    unit: str,
    target_value: str,
    current_value: str,
    weight: str = "1",
):
    from app.models_task_center import KeyResult

    kr = db.scalar(
        select(KeyResult).where(
            KeyResult.tenant_id == tenant_id,
            KeyResult.objective_id == objective_id,
            KeyResult.title == title,
        )
    )
    if kr is not None:
        return kr
    kr = KeyResult(
        tenant_id=tenant_id,
        objective_id=objective_id,
        title=title,
        metric=metric,
        unit=unit,
        target_value=Decimal(target_value),
        current_value=Decimal(current_value),
        weight=Decimal(weight),
        status="active",
    )
    db.add(kr)
    db.flush()
    return kr


def _ensure_root_task(
    db: Session,
    tenant_id: UUID,
    *,
    dedupe_key: str,
    title: str,
    assignee_user_id: UUID | None,
    created_by: UUID | None,
    work_package_id: UUID,
    objective_id: UUID | None,
    weight: str,
    due_days: int = 7,
):
    from datetime import datetime, timedelta, timezone

    from app.models_task import Task

    task = db.scalar(select(Task).where(Task.tenant_id == tenant_id, Task.dedupe_key == dedupe_key))
    if task is not None:
        return task
    task = Task(
        tenant_id=tenant_id,
        title=title,
        status="todo",
        priority="high",
        due_at=datetime.now(timezone.utc) + timedelta(days=due_days),
        assignee_user_id=assignee_user_id,
        created_by=created_by,
        source="manual",
        dedupe_key=dedupe_key,
        work_package_id=work_package_id,
        objective_id=objective_id,
        weight=Decimal(weight),
    )
    db.add(task)
    db.flush()
    return task


def _attach(db: Session, tenant_id: UUID, tasks, *, work_package_id: UUID, root_id: UUID) -> int:
    """把一批任务挂到工作包 + 根任务下（只补空的，不覆盖已有归属）。"""
    attached = 0
    for task in tasks:
        changed = False
        if task.work_package_id is None:
            task.work_package_id = work_package_id
            changed = True
        if task.parent_id is None:
            task.parent_id = root_id
            changed = True
        if changed:
            attached += 1
    return attached


# 汇报线由 app.seed.seed_reporting_lines 统一维护（演示租户基础数据的一部分），
# 任务中心只负责工作包 / OKR 两层结构。


def seed_task_centre_demo(db: Session, tenant_id: UUID) -> None:
    """给演示租户补上任务中心的工作包 / OKR 两层结构。"""
    from app.models import User
    from app.models_domain import Charter, Voyage
    from app.models_task import Task

    users = {u.email: u for u in db.scalars(select(User).where(User.tenant_id == tenant_id)).all()}
    admin = users.get("admin@demo.marios")
    ops = users.get("ops@demo.marios")
    mgmt = users.get("mgmt@demo.marios")
    if not (admin and ops and mgmt):
        return

    period = "2026Q4"

    # ── 汇报线（派单 / 转派 / "我的人"视图的依据）────────────────────
    from app.seed import seed_reporting_lines

    seed_reporting_lines(db, tenant_id)

    # ── 目标：一个季度目标 + 两个可量化 KR ────────────────────────────
    objective = _ensure_objective(
        db,
        tenant_id,
        code="O-DEMO-2026Q4",
        title="Improve voyage execution and closing punctuality",
        description="Turn the voyage closing checklist into owned tasks and measure punctuality by task progress.",
        owner_user_id=mgmt.id,
        created_by=admin.id,
        period=period,
    )
    _ensure_key_result(
        db,
        tenant_id,
        objective_id=objective.id,
        title="Voyage closing tasks completed on time",
        metric="percent",
        unit="%",
        target_value="90",
        current_value="62",
        weight="1.5",
    )
    _ensure_key_result(
        db,
        tenant_id,
        objective_id=objective.id,
        title="Key action automation coverage",
        metric="percent",
        unit="%",
        target_value="80",
        current_value="35",
    )

    # ── 工作包 1：航次收尾（已完成的航次，能看到真实的加权进度）──────
    voyages = db.scalars(select(Voyage).where(Voyage.tenant_id == tenant_id).order_by(Voyage.voyage_no)).all()
    done_voyage = next((v for v in voyages if v.status == "completed"), None)
    if done_voyage is not None:
        pkg_voyage = _ensure_work_package(
            db,
            tenant_id,
            code="WP-VOYAGE-CLOSEOUT",
            title=f"Voyage closing work package · {done_voyage.voyage_no}",
            description="Port calls, SOF loading/discharging facts and the laytime calculation for this voyage.",
            entity_type="voyage",
            entity_id=done_voyage.id,
            owner_user_id=ops.id,
            created_by=admin.id,
            period=period,
        )
        root_voyage = _ensure_root_task(
            db,
            tenant_id,
            dedupe_key=f"demo:tc:root:voyage:{done_voyage.voyage_no}",
            title=f"Voyage closing coordination · {done_voyage.voyage_no}",
            assignee_user_id=ops.id,
            created_by=admin.id,
            work_package_id=pkg_voyage.id,
            objective_id=objective.id,
            weight="3",
        )
        # 收尾缺项 → 真实任务（与航次完成时生成的**同源**：同一份收尾清单判定，
        # 同一套动作码绑定）。演示数据因此能演示"动作做完 → 任务自动勾完成"。
        from app.services.automation import create_closeout_tasks
        from app.services.ui_text import user_locale

        create_closeout_tasks(
            db,
            tenant_id,
            done_voyage,
            locale=user_locale(db, admin.id),
            created_by=admin.id,
            notify=False,  # 演示数据不打扰通知中心
        )
        voyage_tasks = db.scalars(
            select(Task).where(
                Task.tenant_id == tenant_id,
                Task.entity_type == "voyage",
                Task.entity_id == done_voyage.id,
            )
        ).all()
        _attach(db, tenant_id, voyage_tasks, work_package_id=pkg_voyage.id, root_id=root_voyage.id)

    # ── 工作包 2：合同执行（用户举的例子：一份合同拆成好多子任务）────
    charters = db.scalars(select(Charter).where(Charter.tenant_id == tenant_id).order_by(Charter.charter_no)).all()
    charter_task_ids = {
        t.entity_id
        for t in db.scalars(
            select(Task).where(Task.tenant_id == tenant_id, Task.entity_type == "charter")
        ).all()
        if t.entity_id
    }
    charter = next((c for c in charters if c.id in charter_task_ids), None) or next(
        (c for c in charters if c.status == "active"), None
    )
    if charter is not None:
        pkg_charter = _ensure_work_package(
            db,
            tenant_id,
            code="WP-CHARTER-EXEC",
            title=f"Charter execution work package · {charter.charter_no}",
            description="Charter execution, COA lifting approval and commercial term confirmation.",
            entity_type="charter",
            entity_id=charter.id,
            owner_user_id=ops.id,
            created_by=admin.id,
            period=period,
        )
        root_charter = _ensure_root_task(
            db,
            tenant_id,
            dedupe_key=f"demo:tc:root:charter:{charter.charter_no}",
            title=f"Charter execution coordination · {charter.charter_no}",
            assignee_user_id=mgmt.id,
            created_by=admin.id,
            work_package_id=pkg_charter.id,
            objective_id=objective.id,
            weight="6",
        )
        # 一份合同拆成多个子任务，各自给主责人 —— 权重决定工作包/目标进度上卷。
        from app.services.domain_events import ensure_task

        charterer = users.get("charterer@demo.marios")
        finance = users.get("finance@demo.marios")
        children = (
            ("Confirm charter commercial terms and loading/discharging clauses", "2", charterer.id if charterer else ops.id),
            ("Approve COA quantity and laycan", "3", ops.id),
            ("Review first-voyage costs and credit limit", "1", finance.id if finance else ops.id),
        )
        for idx, (title, weight, assignee) in enumerate(children, start=1):
            child = ensure_task(
                db,
                tenant_id,
                title=f"{title} · {charter.charter_no}",
                description=f"Charter execution sub-task of {charter.charter_no} (work package breakdown).",
                entity_type="charter",
                entity_id=charter.id,
                priority="normal",
                due_days=5 + idx,
                assign_user_id=assignee,
                created_by=admin.id,
                weight=Decimal(weight),
                dedupe_key=f"demo:tc:charter:{charter.charter_no}:{idx}",
            )
            if child.parent_id is None:
                child.parent_id = root_charter.id
            if child.work_package_id is None:
                child.work_package_id = pkg_charter.id
        charter_tasks = db.scalars(
            select(Task).where(
                Task.tenant_id == tenant_id,
                Task.entity_type == "charter",
                Task.entity_id == charter.id,
            )
        ).all()
        _attach(db, tenant_id, charter_tasks, work_package_id=pkg_charter.id, root_id=root_charter.id)
