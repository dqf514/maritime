"""任务进度 —— 实时算，不落库。

派生值（百分比）一律**实时计算**，表里只存权重与目标值：
一旦把进度写进列，就必然出现"缓存与真相不一致"，而任务中心要的是
"上级看到的进度 = 下属任务的真实加权完成比例"。

口径（单一实现，别处不要另写一份）：

* **Task** —— 自己 ``done`` → 100%；有子任务 → 子任务按 ``weight`` 加权；
  两者都无 → 0%（``in_progress`` 不折算成 50%，那会让人误解）
* **WorkPackage** —— 其下**根任务**（``parent_id IS NULL``）按 ``weight`` 加权
* **Objective** —— 其 KeyResult 按 ``weight`` 加权；KR 进度 = 关联任务的加权
  完成比例，没有关联任务时用 ``current_value / target_value``

所有百分比用 ``Decimal`` + ``ROUND_HALF_UP``（仓库铁律）。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_task import Task
from app.models_task_center import KeyResult, Objective, WorkPackage

_PCT = Decimal("100")
_ONE = Decimal("1")


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole <= 0:
        return Decimal("0")
    return (part / whole * _PCT).quantize(_PCT, rounding=ROUND_HALF_UP)


def _weighted(finished_weight: Decimal, total_weight: Decimal) -> Decimal:
    """加权完成百分比。"""
    if total_weight <= 0:
        return Decimal("0")
    return _pct(finished_weight, total_weight)


def task_progress(db: Session, task: Task) -> Decimal:
    """单个任务的完成百分比（0–100）。"""
    if task.status == "done":
        return _PCT
    children = db.scalars(select(Task).where(Task.tenant_id == task.tenant_id, Task.parent_id == task.id)).all()
    if not children:
        return Decimal("0")
    total = Decimal("0")
    done = Decimal("0")
    for child in children:
        w = Decimal(str(child.weight or 1))
        total += w
        if child.status == "done":
            done += w
        else:
            # 未完成的子任务也按其自身进度折算（子任务可再分）
            done += w * task_progress(db, child) / _PCT
    return _weighted(done, total)


def work_package_progress(db: Session, package: WorkPackage) -> Decimal:
    """工作包进度 = 其下根任务按 weight 加权。"""
    rows = db.scalars(
        select(Task).where(
            Task.tenant_id == package.tenant_id,
            Task.work_package_id == package.id,
            Task.parent_id.is_(None),
            Task.status != "deleted",
        )
    ).all()
    if not rows:
        return Decimal("0")
    total = Decimal("0")
    done = Decimal("0")
    for row in rows:
        w = Decimal(str(row.weight or 1))
        total += w
        done += w * task_progress(db, row) / _PCT
    return _weighted(done, total)


def key_result_progress(db: Session, kr: KeyResult) -> Decimal:
    """关键结果进度：优先用关联任务的加权完成比例，否则用 current/target。"""
    rows = db.scalars(
        select(Task).where(
            Task.tenant_id == kr.tenant_id,
            Task.objective_id == kr.objective_id,
            Task.status != "deleted",
        )
    ).all()
    # 关联任务通过 objective 归到 KR：没有直接挂 KR 的任务表，
    # 这里用「objective 下所有未完成任务的加权完成比例」作为 KR 进度。
    if rows:
        total = Decimal("0")
        done = Decimal("0")
        for row in rows:
            w = Decimal(str(row.weight or 1))
            total += w
            done += w * task_progress(db, row) / _PCT
        task_pct = _weighted(done, total)
        # 量化口径也给了 current/target 时，取两者较高（任务已完成是真的）
        target = Decimal(str(kr.target_value or 0))
        current = Decimal(str(kr.current_value or 0))
        if target > 0:
            value_pct = _pct(current, target)
            return max(task_pct, value_pct)
        return task_pct
    target = Decimal(str(kr.target_value or 0))
    current = Decimal(str(kr.current_value or 0))
    if target <= 0:
        return Decimal("0")
    return _pct(current, target)


def objective_progress(db: Session, objective: Objective) -> Decimal:
    """目标进度 = 其 KeyResult 按 weight 加权。"""
    krs = db.scalars(
        select(KeyResult).where(KeyResult.tenant_id == objective.tenant_id, KeyResult.objective_id == objective.id)
    ).all()
    if not krs:
        # 没有 KR 时退化为：目标下任务的加权完成比例
        rows = db.scalars(
            select(Task).where(
                Task.tenant_id == objective.tenant_id,
                Task.objective_id == objective.id,
                Task.status != "deleted",
            )
        ).all()
        if not rows:
            return Decimal("0")
        total = Decimal("0")
        done = Decimal("0")
        for row in rows:
            w = Decimal(str(row.weight or 1))
            total += w
            done += w * task_progress(db, row) / _PCT
        return _weighted(done, total)
    total = Decimal("0")
    done = Decimal("0")
    for kr in krs:
        w = Decimal(str(kr.weight or 1))
        total += w
        done += w * key_result_progress(db, kr) / _PCT
    return _weighted(done, total)


def objective_tree(db: Session, objective: Objective) -> dict:
    """目标树节点：目标 + 其 KR + 其任务（前端 OKR 树用）。"""
    krs = db.scalars(
        select(KeyResult).where(KeyResult.tenant_id == objective.tenant_id, KeyResult.objective_id == objective.id)
    ).all()
    tasks = db.scalars(
        select(Task).where(
            Task.tenant_id == objective.tenant_id,
            Task.objective_id == objective.id,
            Task.status != "deleted",
        )
    ).all()
    return {
        "id": str(objective.id),
        "code": objective.code,
        "title": objective.title,
        "period": objective.period,
        "status": objective.status,
        "weight": float(objective.weight or 1),
        "progress": float(objective_progress(db, objective)),
        "key_results": [
            {
                "id": str(kr.id),
                "title": kr.title,
                "metric": kr.metric,
                "unit": kr.unit,
                "target_value": float(kr.target_value or 0),
                "current_value": float(kr.current_value or 0),
                "weight": float(kr.weight or 1),
                "status": kr.status,
                "progress": float(key_result_progress(db, kr)),
            }
            for kr in krs
        ],
        "tasks": [
            {
                "id": str(t.id),
                "title": t.title,
                "status": t.status,
                "weight": float(t.weight or 1),
                "progress": float(task_progress(db, t)),
            }
            for t in tasks
        ],
    }


def work_package_detail(db: Session, package: WorkPackage) -> dict:
    """工作包详情：根任务 + 子任务 + 进度。"""
    rows = db.scalars(
        select(Task)
        .where(
            Task.tenant_id == package.tenant_id,
            Task.work_package_id == package.id,
            Task.status != "deleted",
        )
        .order_by(Task.parent_id.is_not(None), Task.created_at)
    ).all()
    roots = [r for r in rows if r.parent_id is None]
    children_by_parent: dict[UUID, list[Task]] = {}
    for row in rows:
        if row.parent_id:
            children_by_parent.setdefault(row.parent_id, []).append(row)

    def _node(task: Task) -> dict:
        return {
            "id": str(task.id),
            "title": task.title,
            "status": task.status,
            "priority": task.priority,
            "weight": float(task.weight or 1),
            "progress": float(task_progress(db, task)),
            "due_at": task.due_at.isoformat() if task.due_at else None,
            "assignee_user_id": str(task.assignee_user_id) if task.assignee_user_id else None,
            "children": [_node(c) for c in children_by_parent.get(task.id, [])],
        }

    return {
        "id": str(package.id),
        "code": package.code,
        "title": package.title,
        "description": package.description,
        "entity_type": package.entity_type,
        "entity_id": str(package.entity_id) if package.entity_id else None,
        "owner_user_id": str(package.owner_user_id) if package.owner_user_id else None,
        "period": package.period,
        "status": package.status,
        "progress": float(work_package_progress(db, package)),
        "tasks": [_node(r) for r in roots],
    }
