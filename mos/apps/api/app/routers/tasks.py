"""Tenant-wide task system — available to every signed-in user, no module gate."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.models_task import Task
from app.models_task_center import TaskComment
from app.models_wave1 import Notification
from app.security import AuthContext, get_current_auth, require_roles
from app.services.audit import audit
from app.services.data_scope import apply_module_scope
from app.services.notifications import notify_once

router = APIRouter(tags=["Tasks"])

TASK_STATUSES = {"todo", "in_progress", "done", "cancelled"}
TASK_PRIORITIES = {"low", "normal", "high", "urgent"}
MANAGE_ROLES = {"tenant_admin", "management"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """把数据库里读出的时间归一到 aware UTC。

    ``tasks.due_at`` 是 ``DateTime(timezone=True)``，但 SQLite 里存的是
    naive 串（平台约定 naive = UTC），读回来就是 naive —— 直接和
    ``datetime.now(timezone.utc)`` 比会抛
    ``can't compare offset-naive and offset-aware datetimes``。
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class TaskIn(BaseModel):
    title: str
    description: str | None = None
    priority: str = "normal"
    due_at: datetime | None = None
    assignee_user_id: UUID | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    # —— 任务中心 2.0 ——
    parent_id: UUID | None = None
    action_code: str | None = None
    weight: float | None = None
    collaborator_ids: list[UUID] = Field(default_factory=list)
    work_package_id: UUID | None = None
    objective_id: UUID | None = None
    dedupe_key: str | None = None
    auto_complete: bool = True


class TaskPatchIn(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    due_at: datetime | None = None
    assignee_user_id: UUID | None = None
    status: str | None = None
    parent_id: UUID | None = None
    action_code: str | None = None
    weight: float | None = None
    collaborator_ids: list[UUID] | None = None
    work_package_id: UUID | None = None
    objective_id: UUID | None = None
    auto_complete: bool | None = None


def _user_brief(user: User | None) -> dict | None:
    if not user:
        return None
    return {"id": str(user.id), "email": user.email, "full_name": user.full_name}


def task_out(db: Session, row: Task) -> dict:
    return {
        "id": str(row.id),
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "priority": row.priority,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "assignee_user_id": str(row.assignee_user_id) if row.assignee_user_id else None,
        "assignee": _user_brief(db.get(User, row.assignee_user_id) if row.assignee_user_id else None),
        "created_by": str(row.created_by) if row.created_by else None,
        "creator": _user_brief(db.get(User, row.created_by) if row.created_by else None),
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id) if row.entity_id else None,
        "source": row.source,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        # —— 任务中心 2.0 ——
        "parent_id": str(row.parent_id) if row.parent_id else None,
        "action_code": row.action_code,
        "weight": float(row.weight) if row.weight is not None else None,
        "collaborator_ids": [str(x) for x in (row.collaborator_ids or [])],
        "auto_complete": bool(row.auto_complete),
        "auto_completed": bool(row.auto_completed),
        "completed_by": str(row.completed_by) if row.completed_by else None,
        "dedupe_key": row.dedupe_key,
        "work_package_id": str(row.work_package_id) if row.work_package_id else None,
        "objective_id": str(row.objective_id) if row.objective_id else None,
    }


def _entity_href(entity_type: str | None, entity_id: UUID | None) -> str:
    """任务关联系统实体时，通知直达对应页面；否则回任务箱。"""
    if entity_type and entity_id:
        if entity_type == "voyage":
            return f"/operations/voyages/{entity_id}/workspace"
        if entity_type in ("invoice",):
            return f"/finance/invoices/{entity_id}"
        if entity_type in ("charter", "time_charter"):
            return f"/charters/{entity_id}"
        if entity_type == "estimate":
            return f"/estimates"
    return "/tasks"


def _task_or_404(db: Session, tenant_id: UUID, task_id: UUID) -> Task:
    row = db.get(Task, task_id)
    if not row or row.tenant_id != tenant_id or row.status == "deleted":
        raise HTTPException(404, "Task not found")
    return row


def _assert_can_edit(db: Session, auth: AuthContext, task: Task) -> None:
    """编辑权 = 主责 / 协作人 / 创建人 / 该人的上级 / tenant_admin。

    上级由 ``users.manager_user_id`` 这条**人的汇报线**判定（不是部门经理）——
    部门经理管的是编制单元，管不到具体某条任务。
    """
    if "tenant_admin" in auth.roles:
        return
    if auth.user_id in (task.assignee_user_id, task.created_by):
        return
    if auth.user_id and str(auth.user_id) in {str(x) for x in (task.collaborator_ids or [])}:
        return
    if auth.user_id and _is_manager_of(db, auth.tenant_id, auth.user_id, task.assignee_user_id):
        return
    raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Not allowed to edit this task"})


def _is_manager_of(db: Session, tenant_id: UUID, manager_id: UUID | None, user_id: UUID | None) -> bool:
    if not manager_id or not user_id or manager_id == user_id:
        return False
    from app.services.assignment import is_ancestor

    return is_ancestor(db, tenant_id, manager_id, user_id)


def _active_tenant_user(db: Session, tenant_id: UUID, user_id: UUID) -> User:
    user = db.get(User, user_id)
    if not user or user.tenant_id != tenant_id or user.status != "active":
        raise HTTPException(400, detail={"code": "INVALID_ASSIGNEE", "message": "Assignee is not an active tenant user"})
    return user


@router.get("/tasks/my")
def my_tasks(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    status: str | None = None,
    include_done: bool = False,
):
    q = select(Task).where(
        Task.tenant_id == auth.tenant_id,
        Task.status != "deleted",
        or_(Task.assignee_user_id == auth.user_id, Task.created_by == auth.user_id),
    )
    if status:
        q = q.where(Task.status == status)
    elif not include_done:
        q = q.where(Task.status.notin_(["done", "cancelled"]))
    q = q.order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.created_at.desc())
    return [task_out(db, t) for t in db.scalars(q).all()]


@router.get("/tasks/assignees")
def task_assignees(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(User).where(User.tenant_id == auth.tenant_id, User.status == "active").order_by(User.email)
    ).all()
    return [{"id": str(u.id), "email": u.email, "full_name": u.full_name} for u in rows]


@router.get("/tasks")
def list_tasks(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    tab: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assignee_user_id: UUID | None = None,
    action_code: str | None = None,
    entity_type: str | None = None,
    work_package_id: UUID | None = None,
    objective_id: UUID | None = None,
    overdue: bool = False,
    q: str | None = None,
    include_done: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    """任务中心统一列表。

    * **不带 ``tab``** —— 全租户任务列表（管理视角）。沿用原契约：仅
      ``management`` / ``tenant_admin`` 可见，其余角色 403。
    * **带 ``tab``** —— 任务中心的六个视角，对所有登录用户开放；每个视角
      的可见范围由"谁的任务"决定（自己 / 派给我的 / 我派出的 / 我管的团队）。

    返回统一分页信封 ``{items, total, limit, offset}``。
    """
    if tab is None and not ({"management", "tenant_admin"} & set(auth.roles)):
        raise HTTPException(
            403,
            detail={"code": "FORBIDDEN", "message": "Full task list requires management or tenant_admin role"},
        )
    stmt = select(Task).where(Task.tenant_id == auth.tenant_id, Task.status != "deleted")
    if tab is not None:
        stmt = _apply_task_tab(stmt, db, auth, tab)
    else:
        # 行级数据权限：角色被收紧到 "own" 时，任务列表只看自己建的任务。
        stmt = apply_module_scope(db, stmt, Task, auth, "operations")
    if status:
        stmt = stmt.where(Task.status == status)
    elif not include_done:
        stmt = stmt.where(Task.status.notin_(["done", "cancelled"]))
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if assignee_user_id:
        stmt = stmt.where(Task.assignee_user_id == assignee_user_id)
    if action_code:
        stmt = stmt.where(Task.action_code == action_code)
    if entity_type:
        stmt = stmt.where(Task.entity_type == entity_type)
    if work_package_id:
        stmt = stmt.where(Task.work_package_id == work_package_id)
    if objective_id:
        stmt = stmt.where(Task.objective_id == objective_id)
    if overdue:
        stmt = stmt.where(
            Task.due_at.is_not(None),
            Task.due_at < _now(),
            Task.status.notin_(["done", "cancelled"]),
        )
    if q:
        stmt = stmt.where(
            or_(Task.title.ilike(f"%{q}%"), Task.description.ilike(f"%{q}%"))
        )
    stmt = stmt.order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.created_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.scalars(stmt.limit(max(1, min(limit, 200))).offset(max(0, offset))).all()
    # 惰性刷新：绑了系统动作且未完成的任务，在读路径上跑一次判定器。
    _lazy_refresh(db, rows)
    return {
        "items": [task_out(db, t) for t in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


def _apply_task_tab(stmt, db: Session, auth: AuthContext, tab: str):
    """按任务中心的视角收窄查询。

    ``mine``            我建 + 我主责
    ``assigned_to_me``  主责是我
    ``assigned_by_me``  我派出去的（我建的，或我作为上级派给下属的）
    ``team``            我管的团队（管理角色看全租户，否则只看自己 + 下属）
    ``work_package``    挂在工作包下的任务
    ``okr``             挂在 OKR 目标下的任务
    """
    from app.services.assignment import subordinate_ids

    me = auth.user_id
    if tab == "mine":
        return stmt.where(
            or_(Task.assignee_user_id == me, Task.created_by == me)
        )
    if tab == "assigned_to_me":
        return stmt.where(Task.assignee_user_id == me)
    if tab == "assigned_by_me":
        subs = subordinate_ids(db, auth.tenant_id, me) if me else []
        clauses = [Task.created_by == me]
        if subs:
            clauses.append(
                and_(
                    Task.assignee_user_id.in_(subs),
                    Task.assignee_user_id != me,
                    Task.created_by != me,
                )
            )
        return stmt.where(or_(*clauses))
    if tab == "team":
        if {"management", "tenant_admin"} & set(auth.roles):
            return stmt
        subs = subordinate_ids(db, auth.tenant_id, me) if me else []
        return stmt.where(
            Task.assignee_user_id.in_([me, *subs]) if (me or subs) else Task.id.is_(None)
        )
    if tab == "work_package":
        return stmt.where(Task.work_package_id.is_not(None))
    if tab == "okr":
        return stmt.where(Task.objective_id.is_not(None))
    raise HTTPException(400, detail={"code": "UNKNOWN_TAB", "message": f"Unknown task tab {tab}"})


def _lazy_refresh(db: Session, rows: list[Task]) -> None:
    """读路径上的判定器兜底：动作在别处做完了，这里顺手把任务勾上。"""
    if not rows:
        return
    try:
        from app.services.task_completion import refresh_tasks

        changed = refresh_tasks(db, rows[0].tenant_id if rows else None, rows)
        if changed:
            db.commit()
    except Exception:  # noqa: BLE001 —— 刷新失败不得让列表接口挂掉
        db.rollback()


# ── 任务中心：动作目录 / 人员 / 统计 ───────────────────────────────────


@router.get("/tasks/action-catalog")
def action_catalog(auth: AuthContext = Depends(get_current_auth)):
    """系统动作目录 —— 新建任务时绑定"做完就自动勾完成"的系统动作。"""
    from app.services.action_catalog import catalog_payload

    return catalog_payload()


@router.get("/tasks/people")
def task_people(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    """人员选择器：带汇报关系（谁是谁的上级）与所属部门，按组织树排。

    ``/tasks/assignees`` 保持老契约（只回 id/email/full_name），这里是
    任务中心用的**带汇报线 + 部门**的版本 —— 「团队」看板按部门分列，
    前端拿部门信息把任务按人归到列里。
    """
    from app.models_saas import OrgUnit, UserOrgMembership
    from app.services.assignment import subordinate_ids

    users = db.scalars(
        select(User).where(User.tenant_id == auth.tenant_id, User.status == "active").order_by(User.email)
    ).all()
    by_id = {u.id: u for u in users}
    subs = set(subordinate_ids(db, auth.tenant_id, auth.user_id)) if auth.user_id else set()

    # 部门（主部门优先）：人 → 部门 code/name
    unit_by_id = {
        u.id: u for u in db.scalars(select(OrgUnit).where(OrgUnit.tenant_id == auth.tenant_id)).all()
    }
    dept_of: dict[UUID, tuple[str, str]] = {}
    memberships = db.scalars(
        select(UserOrgMembership).where(UserOrgMembership.user_id.in_([u.id for u in users] or [uuid4()]))
    ).all()
    for m in memberships:
        unit = unit_by_id.get(m.org_unit_id)
        if unit is None:
            continue
        current = dept_of.get(m.user_id)
        if current is None or m.is_primary:
            dept_of[m.user_id] = (unit.code, unit.name)

    return [
        {
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "manager_user_id": str(u.manager_user_id) if u.manager_user_id else None,
            "manager_name": (
                by_id[u.manager_user_id].full_name
                if u.manager_user_id in by_id
                else None
            ),
            "is_report": u.id in subs,
            "org_unit_code": dept_of.get(u.id, ("", ""))[0],
            "org_unit_name": dept_of.get(u.id, ("", ""))[1],
        }
        for u in users
    ]


@router.get("/tasks/stats")
def task_stats(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    """任务中心统计：在办 / 逾期 / 今日到期 / 已完成 + 按人负载。"""
    today = _now().date()
    base = (Task.tenant_id == auth.tenant_id, Task.status != "deleted")
    open_rows = db.scalars(
        select(Task).where(*base, Task.status.in_(["todo", "in_progress"]))
    ).all()
    now = _now()
    overdue = [t for t in open_rows if t.due_at is not None and _as_utc(t.due_at) < now]
    due_today = [
        t for t in open_rows if t.due_at is not None and t.due_at.date() == today
    ]
    done = db.scalar(select(func.count()).select_from(Task).where(*base, Task.status == "done")) or 0
    load: dict[str, int] = {}
    for t in open_rows:
        if t.assignee_user_id:
            key = str(t.assignee_user_id)
            load[key] = load.get(key, 0) + 1
    people = {
        str(u.id): u.full_name or u.email
        for u in db.scalars(select(User).where(User.id.in_([UUID(k) for k in load]))).all()
    } if load else {}
    return {
        "open": len(open_rows),
        "overdue": len(overdue),
        "due_today": len(due_today),
        "done": int(done),
        "load": [
            {"user_id": uid, "name": people.get(uid, uid), "open": cnt}
            for uid, cnt in sorted(load.items(), key=lambda kv: -kv[1])
        ],
    }


# ── 工作包 ─────────────────────────────────────────────────────────────


class WorkPackageIn(BaseModel):
    code: str
    title: str
    description: str | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    owner_user_id: UUID | None = None
    period: str | None = None


class WorkPackagePatchIn(BaseModel):
    title: str | None = None
    description: str | None = None
    owner_user_id: UUID | None = None
    period: str | None = None
    status: str | None = None


def _work_package_out(db: Session, pkg) -> dict:
    from app.services.task_progress import work_package_progress

    return {
        "id": str(pkg.id),
        "code": pkg.code,
        "title": pkg.title,
        "description": pkg.description,
        "entity_type": pkg.entity_type,
        "entity_id": str(pkg.entity_id) if pkg.entity_id else None,
        "owner_user_id": str(pkg.owner_user_id) if pkg.owner_user_id else None,
        "period": pkg.period,
        "status": pkg.status,
        "progress": float(work_package_progress(db, pkg)),
        "created_at": pkg.created_at.isoformat() if pkg.created_at else None,
    }


@router.get("/tasks/work-packages")
def list_work_packages(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    status: str | None = None,
):
    from app.models_task_center import WorkPackage

    stmt = select(WorkPackage).where(WorkPackage.tenant_id == auth.tenant_id)
    if status:
        stmt = stmt.where(WorkPackage.status == status)
    rows = db.scalars(stmt.order_by(WorkPackage.created_at.desc())).all()
    return [_work_package_out(db, r) for r in rows]


@router.post("/tasks/work-packages")
def create_work_package(
    body: WorkPackageIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from app.models_task_center import WorkPackage

    code = body.code.strip()
    if not code:
        raise HTTPException(400, detail={"code": "INVALID_CODE", "message": "Code is required"})
    exists = db.scalar(
        select(WorkPackage).where(WorkPackage.tenant_id == auth.tenant_id, WorkPackage.code == code)
    )
    if exists:
        raise HTTPException(409, detail={"code": "DUPLICATE_CODE", "message": "Work package code already exists"})
    if body.owner_user_id:
        _active_tenant_user(db, auth.tenant_id, body.owner_user_id)
    pkg = WorkPackage(
        tenant_id=auth.tenant_id,
        code=code,
        title=body.title,
        description=body.description,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        owner_user_id=body.owner_user_id,
        period=body.period,
        status="open",
        created_by=auth.user_id,
    )
    db.add(pkg)
    db.flush()
    audit(
        db,
        action="task.work_package_create",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="work_package",
        entity_id=pkg.id,
        detail={"code": code, "title": body.title},
    )
    db.commit()
    db.refresh(pkg)
    return _work_package_out(db, pkg)


@router.patch("/tasks/work-packages/{package_id}")
def update_work_package(
    package_id: UUID,
    body: WorkPackagePatchIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from app.models_task_center import WorkPackage

    pkg = db.get(WorkPackage, package_id)
    if not pkg or pkg.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Work package not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("status") and data["status"] not in ("open", "closed"):
        raise HTTPException(400, detail={"code": "INVALID_STATUS", "allowed": ["open", "closed"]})
    if data.get("owner_user_id"):
        _active_tenant_user(db, auth.tenant_id, data["owner_user_id"])
    for k, v in data.items():
        setattr(pkg, k, v)
    pkg.updated_at = _now()
    audit(
        db,
        action="task.work_package_update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="work_package",
        entity_id=pkg.id,
        detail={"fields": sorted(data.keys())},
    )
    db.commit()
    db.refresh(pkg)
    return _work_package_out(db, pkg)


# ── OKR 目标与关键结果 ─────────────────────────────────────────────────


class ObjectiveIn(BaseModel):
    code: str
    title: str
    description: str | None = None
    parent_id: UUID | None = None
    owner_user_id: UUID | None = None
    period: str | None = None
    weight: float = 1
    status: str = "active"


class ObjectivePatchIn(BaseModel):
    title: str | None = None
    description: str | None = None
    owner_user_id: UUID | None = None
    period: str | None = None
    weight: float | None = None
    status: str | None = None


class KeyResultIn(BaseModel):
    title: str
    metric: str | None = None
    unit: str | None = None
    target_value: float = 0
    current_value: float = 0
    weight: float = 1
    status: str = "active"


def _objective_out(db: Session, obj) -> dict:
    from app.services.task_progress import objective_progress

    return {
        "id": str(obj.id),
        "code": obj.code,
        "title": obj.title,
        "description": obj.description,
        "parent_id": str(obj.parent_id) if obj.parent_id else None,
        "owner_user_id": str(obj.owner_user_id) if obj.owner_user_id else None,
        "period": obj.period,
        "weight": float(obj.weight or 1),
        "status": obj.status,
        "progress": float(objective_progress(db, obj)),
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
    }


@router.get("/tasks/objectives")
def list_objectives(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    status: str | None = None,
    period: str | None = None,
):
    from app.models_task_center import Objective

    stmt = select(Objective).where(Objective.tenant_id == auth.tenant_id)
    if status:
        stmt = stmt.where(Objective.status == status)
    if period:
        stmt = stmt.where(Objective.period == period)
    rows = db.scalars(stmt.order_by(Objective.created_at.desc())).all()
    return [_objective_out(db, r) for r in rows]


@router.post("/tasks/objectives")
def create_objective(
    body: ObjectiveIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from app.models_task_center import Objective

    code = body.code.strip()
    if not code:
        raise HTTPException(400, detail={"code": "INVALID_CODE", "message": "Code is required"})
    exists = db.scalar(
        select(Objective).where(Objective.tenant_id == auth.tenant_id, Objective.code == code)
    )
    if exists:
        raise HTTPException(409, detail={"code": "DUPLICATE_CODE", "message": "Objective code already exists"})
    if body.status not in ("draft", "active", "closed"):
        raise HTTPException(400, detail={"code": "INVALID_STATUS", "allowed": ["draft", "active", "closed"]})
    if body.owner_user_id:
        _active_tenant_user(db, auth.tenant_id, body.owner_user_id)
    if body.parent_id:
        parent = db.get(Objective, body.parent_id)
        if not parent or parent.tenant_id != auth.tenant_id:
            raise HTTPException(400, detail={"code": "INVALID_PARENT"})
    obj = Objective(
        tenant_id=auth.tenant_id,
        code=code,
        title=body.title,
        description=body.description,
        parent_id=body.parent_id,
        owner_user_id=body.owner_user_id,
        period=body.period,
        weight=Decimal(str(body.weight)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        status=body.status,
        created_by=auth.user_id,
    )
    db.add(obj)
    db.flush()
    audit(
        db,
        action="task.objective_create",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="objective",
        entity_id=obj.id,
        detail={"code": code, "title": body.title},
    )
    db.commit()
    db.refresh(obj)
    return _objective_out(db, obj)


@router.patch("/tasks/objectives/{objective_id}")
def update_objective(
    objective_id: UUID,
    body: ObjectivePatchIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from app.models_task_center import Objective

    obj = db.get(Objective, objective_id)
    if not obj or obj.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Objective not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("status") and data["status"] not in ("draft", "active", "closed"):
        raise HTTPException(400, detail={"code": "INVALID_STATUS", "allowed": ["draft", "active", "closed"]})
    if data.get("owner_user_id"):
        _active_tenant_user(db, auth.tenant_id, data["owner_user_id"])
    if data.get("weight") is not None:
        data["weight"] = Decimal(str(data["weight"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = _now()
    audit(
        db,
        action="task.objective_update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="objective",
        entity_id=obj.id,
        detail={"fields": sorted(data.keys())},
    )
    db.commit()
    db.refresh(obj)
    return _objective_out(db, obj)


def _key_result_out(db: Session, kr) -> dict:
    from app.services.task_progress import key_result_progress

    return {
        "id": str(kr.id),
        "objective_id": str(kr.objective_id),
        "title": kr.title,
        "metric": kr.metric,
        "unit": kr.unit,
        "target_value": float(kr.target_value or 0),
        "current_value": float(kr.current_value or 0),
        "weight": float(kr.weight or 1),
        "status": kr.status,
        "progress": float(key_result_progress(db, kr)),
    }


@router.get("/tasks/objectives/{objective_id}/key-results")
def list_key_results(
    objective_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from app.models_task_center import KeyResult, Objective

    obj = db.get(Objective, objective_id)
    if not obj or obj.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Objective not found")
    rows = db.scalars(
        select(KeyResult).where(
            KeyResult.tenant_id == auth.tenant_id, KeyResult.objective_id == objective_id
        )
    ).all()
    return [_key_result_out(db, r) for r in rows]


@router.post("/tasks/objectives/{objective_id}/key-results")
def create_key_result(
    objective_id: UUID,
    body: KeyResultIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from app.models_task_center import KeyResult, Objective

    obj = db.get(Objective, objective_id)
    if not obj or obj.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Objective not found")
    if body.status not in ("active", "closed"):
        raise HTTPException(400, detail={"code": "INVALID_STATUS", "allowed": ["active", "closed"]})
    kr = KeyResult(
        tenant_id=auth.tenant_id,
        objective_id=objective_id,
        title=body.title,
        metric=body.metric,
        unit=body.unit,
        target_value=Decimal(str(body.target_value)),
        current_value=Decimal(str(body.current_value)),
        weight=Decimal(str(body.weight)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        status=body.status,
    )
    db.add(kr)
    db.flush()
    audit(
        db,
        action="task.key_result_create",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="key_result",
        entity_id=kr.id,
        detail={"objective_id": str(objective_id), "title": body.title},
    )
    db.commit()
    db.refresh(kr)
    return _key_result_out(db, kr)


# ── 任务详情与评论 ─────────────────────────────────────────────────────


@router.get("/tasks/{task_id}")
def get_task(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """任务详情：任务 + 子任务 + 父任务 + 评论 + 动作状态 + 进度。"""
    from app.services.task_progress import task_progress

    task = _task_or_404(db, auth.tenant_id, task_id)
    _lazy_refresh(db, [task])
    children = db.scalars(
        select(Task).where(Task.tenant_id == auth.tenant_id, Task.parent_id == task.id)
    ).all()
    parent = db.get(Task, task.parent_id) if task.parent_id else None
    comments = db.scalars(
        select(TaskComment)
        .where(
            TaskComment.tenant_id == auth.tenant_id,
            TaskComment.task_id == task.id,
            TaskComment.deleted_at.is_(None),
        )
        .order_by(TaskComment.created_at)
    ).all()
    spec = None
    if task.action_code:
        from app.services.action_catalog import get_action

        found = get_action(task.action_code)
        spec = found.as_dict() if found else None
    return {
        **task_out(db, task),
        "progress": float(task_progress(db, task)),
        "parent": task_out(db, parent) if parent is not None and parent.tenant_id == auth.tenant_id else None,
        "children": [task_out(db, c) for c in children],
        "comments": [
            {
                "id": str(c.id),
                "body": c.body,
                "author_user_id": str(c.author_user_id) if c.author_user_id else None,
                "author": _user_brief(db.get(User, c.author_user_id) if c.author_user_id else None),
                "mentions": [str(m) for m in (c.mentions or [])],
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in comments
        ],
        "action": spec,
    }


class TaskCommentIn(BaseModel):
    body: str
    mentions: list[UUID] = Field(default_factory=list)


@router.get("/tasks/{task_id}/comments")
def list_comments(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    task = _task_or_404(db, auth.tenant_id, task_id)
    rows = db.scalars(
        select(TaskComment)
        .where(
            TaskComment.tenant_id == auth.tenant_id,
            TaskComment.task_id == task.id,
            TaskComment.deleted_at.is_(None),
        )
        .order_by(TaskComment.created_at)
    ).all()
    return [
        {
            "id": str(c.id),
            "body": c.body,
            "author_user_id": str(c.author_user_id) if c.author_user_id else None,
            "author": _user_brief(db.get(User, c.author_user_id) if c.author_user_id else None),
            "mentions": [str(m) for m in (c.mentions or [])],
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in rows
    ]


@router.post("/tasks/{task_id}/comments")
def add_comment(
    task_id: UUID,
    body: TaskCommentIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """评论 + @提及：被提及的人会收到通知。"""
    task = _task_or_404(db, auth.tenant_id, task_id)
    text = (body.body or "").strip()
    if not text:
        raise HTTPException(400, detail={"code": "EMPTY_COMMENT", "message": "Comment body is required"})
    mentions: list[str] = []
    for uid in body.mentions:
        _active_tenant_user(db, auth.tenant_id, uid)
        mentions.append(str(uid))
    comment = TaskComment(
        tenant_id=auth.tenant_id,
        task_id=task.id,
        author_user_id=auth.user_id,
        body=text,
        mentions=mentions,
    )
    db.add(comment)
    db.flush()
    audit(
        db,
        action="task.comment",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="task",
        entity_id=task.id,
        detail={"comment_id": str(comment.id), "mentions": mentions},
    )
    if mentions:
        mentioned = [db.get(User, UUID(m)) for m in mentions]
        notify_once(
            db,
            auth.tenant_id,
            [u for u in mentioned if u is not None],
            title=f"你被提及：{task.title}",
            body=text[:300],
            href=f"/tasks?task={task.id}",
            level="info",
        )
    db.commit()
    db.refresh(comment)
    return {
        "id": str(comment.id),
        "body": comment.body,
        "author_user_id": str(comment.author_user_id) if comment.author_user_id else None,
        "author": _user_brief(db.get(User, comment.author_user_id) if comment.author_user_id else None),
        "mentions": mentions,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }


@router.post("/tasks")
def create_task(
    body: TaskIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    if body.priority not in TASK_PRIORITIES:
        raise HTTPException(400, detail={"code": "INVALID_PRIORITY", "allowed": sorted(TASK_PRIORITIES)})
    if body.assignee_user_id:
        _active_tenant_user(db, auth.tenant_id, body.assignee_user_id)
    spec = None
    if body.action_code:
        from app.services.action_catalog import get_action

        spec = get_action(body.action_code)
        if spec is None:
            raise HTTPException(
                400, detail={"code": "UNKNOWN_ACTION", "message": f"Unknown action code {body.action_code}"}
            )
    if body.parent_id:
        parent = _task_or_404(db, auth.tenant_id, body.parent_id)
        if parent.parent_id is not None:
            raise HTTPException(
                400, detail={"code": "INVALID_PARENT", "message": "Task tree is limited to two levels"}
            )
    collaborators = _validate_collaborators(db, auth.tenant_id, body.collaborator_ids)
    data = body.model_dump()
    data["collaborator_ids"] = [str(x) for x in collaborators]
    data["weight"] = _validate_weight(body.weight)
    data["auto_complete"] = bool(body.auto_complete) and bool(body.action_code)
    row = Task(tenant_id=auth.tenant_id, created_by=auth.user_id, **data)
    db.add(row)
    db.flush()
    if row.assignee_user_id and row.assignee_user_id != auth.user_id:
        db.add(
            Notification(
                tenant_id=auth.tenant_id,
                user_id=row.assignee_user_id,
                title=row.title,
                body=(row.description or "")[:500] or None,
                level="info",
                href=_entity_href(row.entity_type, row.entity_id),
            )
        )
    audit(
        db,
        action="task.create",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="task",
        entity_id=row.id,
        detail={"title": row.title, "assignee_user_id": str(row.assignee_user_id) if row.assignee_user_id else None},
    )
    db.commit()
    db.refresh(row)
    return task_out(db, row)


def _validate_weight(weight: float | None) -> Decimal:
    """权重必须为正 —— 进度加权靠它，负数/零会让上卷结果失去意义。"""
    if weight is None:
        return Decimal("1")
    value = Decimal(str(weight)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value <= 0:
        raise HTTPException(400, detail={"code": "INVALID_WEIGHT", "message": "Weight must be positive"})
    return value


def _validate_collaborators(
    db: Session, tenant_id: UUID, ids: list[UUID] | None
) -> list[UUID]:
    """协作人必须是本租户在职用户，且不能与主责重复。"""
    if not ids:
        return []
    out: list[UUID] = []
    for cid in ids:
        if cid in out:
            continue
        _active_tenant_user(db, tenant_id, cid)
        out.append(cid)
    return out


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: UUID,
    body: TaskPatchIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    task = _task_or_404(db, auth.tenant_id, task_id)
    _assert_can_edit(db, auth, task)
    data = body.model_dump(exclude_unset=True)
    if "priority" in data and data["priority"] not in TASK_PRIORITIES:
        raise HTTPException(400, detail={"code": "INVALID_PRIORITY", "allowed": sorted(TASK_PRIORITIES)})
    if "status" in data and data["status"] not in TASK_STATUSES:
        raise HTTPException(400, detail={"code": "INVALID_STATUS", "allowed": sorted(TASK_STATUSES)})
    if "status" in data and data["status"] != task.status:
        # 状态流转走状态机 —— 非法跳转 409（与全站口径一致）
        from app.services.state_machine import TASK_TRANSITIONS, transition

        try:
            transition("task", task.status, data["status"], TASK_TRANSITIONS)
        except Exception as exc:  # noqa: BLE001 — InvalidState
            raise HTTPException(
                409,
                detail={
                    "code": "INVALID_STATE",
                    "message": f"Cannot move task from {task.status} to {data['status']}",
                    "allowed": sorted(TASK_TRANSITIONS.get(task.status, set())),
                },
            ) from exc
    if data.get("assignee_user_id"):
        _active_tenant_user(db, auth.tenant_id, data["assignee_user_id"])
    if "action_code" in data and data["action_code"]:
        from app.services.action_catalog import get_action

        if get_action(data["action_code"]) is None:
            raise HTTPException(
                400, detail={"code": "UNKNOWN_ACTION", "message": f"Unknown action code {data['action_code']}"}
            )
    if "collaborator_ids" in data and data["collaborator_ids"] is not None:
        data["collaborator_ids"] = [str(x) for x in _validate_collaborators(db, auth.tenant_id, data["collaborator_ids"])]
    if "weight" in data and data["weight"] is not None:
        data["weight"] = _validate_weight(data["weight"])
    if "parent_id" in data and data["parent_id"]:
        _task_or_404(db, auth.tenant_id, data["parent_id"])
    previous_assignee = task.assignee_user_id
    for k, v in data.items():
        setattr(task, k, v)
    if data.get("status") == "done":
        task.completed_at = task.completed_at or _now()
    elif "status" in data:
        task.completed_at = None
    task.updated_at = _now()
    # 改派要通知新负责人 —— 旧 PATCH 改 assignee 完全不通知，是个缺口。
    if "assignee_user_id" in data and data["assignee_user_id"] != previous_assignee:
        _notify_assignee(db, auth.tenant_id, task, data["assignee_user_id"])
    audit(
        db,
        action="task.update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="task",
        entity_id=task.id,
        detail={"fields": sorted(data.keys())},
    )
    db.commit()
    db.refresh(task)
    return task_out(db, task)


def _notify_assignee(
    db: Session,
    tenant_id: UUID,
    task: Task,
    assignee_user_id: UUID | None,
    *,
    level: str = "info",
) -> None:
    """通知（新的）负责人 —— 改派/转派都要让对方知情。"""
    if not assignee_user_id or assignee_user_id == task.created_by:
        return
    db.add(
        Notification(
            tenant_id=tenant_id,
            user_id=assignee_user_id,
            title=task.title,
            body=(task.description or "")[:500] or None,
            level=level,
            href=_entity_href(task.entity_type, task.entity_id),
        )
    )


class TaskTransferIn(BaseModel):
    """转派 —— 上级 / 创建人 / 管理员把任务交给别人。"""

    assignee_user_id: UUID
    reason: str | None = None


@router.post("/tasks/{task_id}/transfer")
def transfer_task(
    task_id: UUID,
    body: TaskTransferIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """转派任务：改主责人 + 通知新负责人 + 写审计。

    权责口径（"任务分明、权责分明"）：
      * **上级**可以下派 —— 上级是当前主责的上级即可；
      * **创建人**可以改派；
      * **当前主责**只能**向下**转派（交给自己的下属），不能把任务上交 ——
        下级不能指派给上级，避免责任被上推；
      * **tenant_admin** 随时可转派。
    """
    task = _task_or_404(db, auth.tenant_id, task_id)
    new_owner = _active_tenant_user(db, auth.tenant_id, body.assignee_user_id)
    if "tenant_admin" not in auth.roles:
        allowed = False
        if auth.user_id and auth.user_id == task.created_by:
            allowed = True
        elif auth.user_id and task.assignee_user_id and auth.user_id == task.assignee_user_id:
            # 当前主责：只允许向下转派
            allowed = _is_manager_of(db, auth.tenant_id, auth.user_id, new_owner.id)
        elif auth.user_id:
            allowed = _is_manager_of(db, auth.tenant_id, auth.user_id, task.assignee_user_id)
        if not allowed:
            raise HTTPException(
                403, detail={"code": "FORBIDDEN", "message": "Not allowed to transfer this task"}
            )
    old_owner = task.assignee_user_id
    task.assignee_user_id = new_owner.id
    task.updated_at = _now()
    _notify_assignee(db, auth.tenant_id, task, new_owner.id)
    audit(
        db,
        action="task.transfer",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="task",
        entity_id=task.id,
        detail={
            "from": str(old_owner) if old_owner else None,
            "to": str(new_owner.id),
            "reason": body.reason,
        },
    )
    db.commit()
    db.refresh(task)
    return task_out(db, task)


@router.post("/tasks/{task_id}/complete")
def complete_task(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from app.services.task_completion import complete_task as _complete

    task = _task_or_404(db, auth.tenant_id, task_id)
    _assert_can_edit(db, auth, task)
    if not _complete(db, task, actor_user_id=auth.user_id, auto=False, reason="manual"):
        raise HTTPException(
            409, detail={"code": "INVALID_STATE", "message": f"Cannot complete a {task.status} task"}
        )
    db.commit()
    db.refresh(task)
    return task_out(db, task)


@router.post("/tasks/{task_id}/reopen")
def reopen_task(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from app.services.task_completion import reopen_task as _reopen

    task = _task_or_404(db, auth.tenant_id, task_id)
    _assert_can_edit(db, auth, task)
    if not _reopen(db, task, actor_user_id=auth.user_id):
        raise HTTPException(
            409, detail={"code": "INVALID_STATE", "message": f"Cannot reopen a {task.status} task"}
        )
    db.commit()
    db.refresh(task)
    return task_out(db, task)


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Soft delete via status="deleted" (done/cancelled tasks may also be deleted)."""
    from app.services.recycle import soft_delete

    task = _task_or_404(db, auth.tenant_id, task_id)
    _assert_can_edit(db, auth, task)
    soft_delete(db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="task", row=task, title=task.title)
    task.updated_at = _now()
    audit(db, action="task.delete", tenant_id=auth.tenant_id, actor_user_id=auth.user_id, entity_type="task", entity_id=task.id)
    db.commit()
    return {"ok": True, "recycled": True}
