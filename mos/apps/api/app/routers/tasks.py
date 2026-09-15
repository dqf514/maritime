"""Tenant-wide task system — available to every signed-in user, no module gate."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.models_task import Task
from app.models_wave1 import Notification
from app.security import AuthContext, get_current_auth
from app.services.audit import audit

router = APIRouter(tags=["Tasks"])

TASK_STATUSES = {"todo", "in_progress", "done", "cancelled"}
TASK_PRIORITIES = {"low", "normal", "high", "urgent"}
MANAGE_ROLES = {"tenant_admin", "management"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskIn(BaseModel):
    title: str
    description: str | None = None
    priority: str = "normal"
    due_at: datetime | None = None
    assignee_user_id: UUID | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None


class TaskPatchIn(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    due_at: datetime | None = None
    assignee_user_id: UUID | None = None
    status: str | None = None


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
    }


def _task_or_404(db: Session, tenant_id: UUID, task_id: UUID) -> Task:
    row = db.get(Task, task_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(404, "Task not found")
    return row


def _assert_can_edit(auth: AuthContext, task: Task) -> None:
    if "tenant_admin" in auth.roles:
        return
    if auth.user_id in (task.assignee_user_id, task.created_by):
        return
    raise HTTPException(403, detail={"code": "FORBIDDEN", "message": "Not allowed to edit this task"})


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
    status: str | None = None,
    assignee_user_id: UUID | None = None,
):
    if not MANAGE_ROLES.intersection(auth.roles):
        raise HTTPException(403, detail={"code": "ROLE_REQUIRED", "roles": sorted(MANAGE_ROLES)})
    q = select(Task).where(Task.tenant_id == auth.tenant_id)
    if status:
        q = q.where(Task.status == status)
    if assignee_user_id:
        q = q.where(Task.assignee_user_id == assignee_user_id)
    q = q.order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.created_at.desc())
    return [task_out(db, t) for t in db.scalars(q).all()]


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
    row = Task(tenant_id=auth.tenant_id, created_by=auth.user_id, **body.model_dump())
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
                href="/tasks",
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


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: UUID,
    body: TaskPatchIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    task = _task_or_404(db, auth.tenant_id, task_id)
    _assert_can_edit(auth, task)
    data = body.model_dump(exclude_unset=True)
    if "priority" in data and data["priority"] not in TASK_PRIORITIES:
        raise HTTPException(400, detail={"code": "INVALID_PRIORITY", "allowed": sorted(TASK_PRIORITIES)})
    if "status" in data and data["status"] not in TASK_STATUSES:
        raise HTTPException(400, detail={"code": "INVALID_STATUS", "allowed": sorted(TASK_STATUSES)})
    if data.get("assignee_user_id"):
        _active_tenant_user(db, auth.tenant_id, data["assignee_user_id"])
    for k, v in data.items():
        setattr(task, k, v)
    if data.get("status") == "done":
        task.completed_at = task.completed_at or _now()
    elif "status" in data:
        task.completed_at = None
    task.updated_at = _now()
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


@router.post("/tasks/{task_id}/complete")
def complete_task(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    task = _task_or_404(db, auth.tenant_id, task_id)
    _assert_can_edit(auth, task)
    task.status = "done"
    task.completed_at = _now()
    task.updated_at = _now()
    audit(db, action="task.complete", tenant_id=auth.tenant_id, actor_user_id=auth.user_id, entity_type="task", entity_id=task.id)
    db.commit()
    return task_out(db, task)


@router.post("/tasks/{task_id}/reopen")
def reopen_task(
    task_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    task = _task_or_404(db, auth.tenant_id, task_id)
    _assert_can_edit(auth, task)
    task.status = "todo"
    task.completed_at = None
    task.updated_at = _now()
    audit(db, action="task.reopen", tenant_id=auth.tenant_id, actor_user_id=auth.user_id, entity_type="task", entity_id=task.id)
    db.commit()
    return task_out(db, task)
