"""分配策略解析器 —— 把"该谁做"这件事从代码里抽出来，形成可配置的策略。

背景
----
仓库里原来的分派规则藏在 ``services/domain_events.ensure_task``：
``assign_role`` 直接取 ``role_recipients(...)[0]`` —— **该角色第一个 active
用户**。这在角色下有多人时完全是任意的（依赖 DB 返回顺序），任务可能永远
压在同一个人头上。

本模块给出五种策略，并统一按**负载最低优先**挑选具体的人：

===================  ==================================================
策略                  解析
===================  ==================================================
``user``             直接指定的人
``role``             持该角色的 active 用户（负载均衡）
``role_in_unit``     某部门内持该角色的 active 用户（负载均衡）
``manager``          触发人的直接上级（``users.manager_user_id``）
``self``             触发人自己
===================  ==================================================

负载 = 该人名下**未完成**的任务数（``todo`` / ``in_progress`` / ``overdue``）。
平手按 ``(full_name, email)`` 序，保证结果**确定性**（不再依赖 DB 顺序）。

``manager`` 策略依赖人的汇报线 —— ``users.manager_user_id``（Batch B 新增）。
OrgUnit 的 ``manager_user_id`` 只能表达"部门经理"，无法表达"甲汇报给乙"
（同部门内上级下属就是这种），所以人的汇报线单独用一列存。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Role, User, UserRole
from app.models_task import Task

# 策略取值 —— 与 TaskRule / 收尾清单 / 新建任务入参共用同一套字符串
STRATEGIES = ("user", "role", "role_in_unit", "manager", "self")

# 计入"负载"的任务状态：未完成即算占用
_OPEN_TASK_STATUSES = ("todo", "in_progress")


@dataclass(frozen=True)
class Assignment:
    """一次分配解析的结果。"""

    strategy: str
    assignee_user_id: UUID | None
    # 解析依据（审计 / 前端展示用）：如 {"role": "charterer"} / {"unit": "ops"}
    reason: dict


def _open_task_load(db: Session, tenant_id: UUID) -> dict[UUID, int]:
    """每个用户当前未完成的任务数。"""
    rows = db.execute(
        select(Task.assignee_user_id, func.count(Task.id))
        .where(
            Task.tenant_id == tenant_id,
            Task.status.in_(_OPEN_TASK_STATUSES),
            Task.assignee_user_id.is_not(None),
        )
        .group_by(Task.assignee_user_id)
    ).all()
    return {uid: int(cnt) for uid, cnt in rows}


def _pick_least_loaded(users: list[User], load: dict[UUID, int]) -> User | None:
    """负载最低优先；平手按 (full_name, email) 序 —— 结果确定。"""
    if not users:
        return None
    return min(users, key=lambda u: (load.get(u.id, 0), (u.full_name or "").lower(), u.email.lower()))


def _users_with_role(db: Session, tenant_id: UUID, role_code: str) -> list[User]:
    role_ids = select(Role.id).where(Role.tenant_id == tenant_id, Role.code == role_code)
    user_ids = select(UserRole.user_id).where(UserRole.role_id.in_(role_ids))
    return list(
        db.scalars(
            select(User).where(
                User.id.in_(user_ids),
                User.tenant_id == tenant_id,
                User.status == "active",
            )
        ).all()
    )


def _users_with_permission(db: Session, tenant_id: UUID, permission: str) -> list[User]:
    """按**权限**找人 —— 角色码没人时的兜底。

    动作目录写的是角色码（``claims``），但租户不一定建了这个角色
    （演示租户就没有 —— 权限是挂在 ``demurrage`` 角色上的）。
    找不到角色时退一步：谁有这块权限就归谁。
    任务有人认领，比"角色码对得上"更重要。
    """
    roles = db.scalars(select(Role).where(Role.tenant_id == tenant_id)).all()
    wanted = [r.id for r in roles if (r.permissions or {}).get(permission) is True]
    if not wanted:
        return []
    user_ids = select(UserRole.user_id).where(UserRole.role_id.in_(wanted))
    return list(
        db.scalars(
            select(User).where(
                User.id.in_(user_ids),
                User.tenant_id == tenant_id,
                User.status == "active",
            )
        ).all()
    )


def _users_in_unit(db: Session, tenant_id: UUID, unit_id: UUID) -> list[User]:
    """某部门（org unit）内的 active 用户 —— 走主成员关系。"""
    from app.models_saas import UserOrgMembership

    user_ids = select(UserOrgMembership.user_id).where(UserOrgMembership.org_unit_id == unit_id)
    return list(
        db.scalars(
            select(User).where(
                User.id.in_(user_ids),
                User.tenant_id == tenant_id,
                User.status == "active",
            )
        ).all()
    )


def resolve_assignment(
    db: Session,
    tenant_id: UUID,
    *,
    strategy: str = "role",
    role_code: str | None = None,
    user_id: UUID | None = None,
    unit_id: UUID | None = None,
    actor_user_id: UUID | None = None,
) -> Assignment:
    """按策略解析出具体承接人。

    策略无法解析出人选（角色下无人 / 上级未设置）时返回 ``assignee_user_id=None``
    —— 任务照建，管理层视角仍可见（与 ``ensure_task`` 原行为一致）。
    """
    strategy = strategy or "role"
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown assignment strategy: {strategy}")

    if strategy == "user":
        if user_id is None:
            return Assignment(strategy, None, {"strategy": strategy})
        target = db.get(User, user_id)
        if target is None or target.tenant_id != tenant_id or target.status != "active":
            return Assignment(strategy, None, {"strategy": strategy, "requested_user_id": str(user_id)})
        return Assignment(strategy, target.id, {"strategy": strategy, "user_id": str(target.id)})

    if strategy == "self":
        if actor_user_id is None:
            return Assignment(strategy, None, {"strategy": strategy})
        return Assignment(strategy, actor_user_id, {"strategy": strategy, "user_id": str(actor_user_id)})

    if strategy == "manager":
        if actor_user_id is None:
            return Assignment(strategy, None, {"strategy": strategy})
        actor = db.get(User, actor_user_id)
        if actor is None or actor.tenant_id != tenant_id:
            return Assignment(strategy, None, {"strategy": strategy})
        mgr_id = actor.manager_user_id
        if mgr_id is None:
            return Assignment(strategy, None, {"strategy": strategy, "no_manager": True})
        mgr = db.get(User, mgr_id)
        if mgr is None or mgr.tenant_id != tenant_id or mgr.status != "active":
            return Assignment(strategy, None, {"strategy": strategy, "no_manager": True})
        return Assignment(strategy, mgr.id, {"strategy": strategy, "user_id": str(mgr.id)})

    if strategy == "role_in_unit":
        if unit_id is None or not role_code:
            return Assignment(strategy, None, {"strategy": strategy})
        unit_users = {u.id for u in _users_in_unit(db, tenant_id, unit_id)}
        candidates = [u for u in _users_with_role(db, tenant_id, role_code) if u.id in unit_users]
        load = _open_task_load(db, tenant_id)
        picked = _pick_least_loaded(candidates, load)
        return Assignment(
            strategy,
            picked.id if picked else None,
            {"strategy": strategy, "role": role_code, "org_unit_id": str(unit_id), "candidates": len(candidates)},
        )

    # role
    if not role_code:
        return Assignment(strategy, None, {"strategy": strategy})
    candidates = _users_with_role(db, tenant_id, role_code)
    resolved_by = "role"
    if not candidates:
        # 这个角色码下没人（租户没建这个角色）→ 找有同等权限的人接手
        candidates = _users_with_permission(db, tenant_id, role_code)
        resolved_by = "permission"
    load = _open_task_load(db, tenant_id)
    picked = _pick_least_loaded(candidates, load)
    return Assignment(
        strategy,
        picked.id if picked else None,
        {"strategy": strategy, "role": role_code, "resolved_by": resolved_by, "candidates": len(candidates)},
    )


# ── 汇报线（人的上下级关系） ────────────────────────────────────────────────


def reports_to(db: Session, tenant_id: UUID, user_id: UUID) -> UUID | None:
    """某人的直接上级。"""
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        return None
    return user.manager_user_id


def is_ancestor(db: Session, tenant_id: UUID, ancestor_id: UUID, user_id: UUID) -> bool:
    """``ancestor_id`` 是否是 ``user_id`` 的（间接）上级。

    沿 ``manager_user_id`` 链上溯，深度上限 20 层（防脏数据成环）。
    """
    seen: set[UUID] = set()
    current = user_id
    for _ in range(20):
        if current in seen:
            return False
        seen.add(current)
        nxt = reports_to(db, tenant_id, current)
        if nxt is None:
            return False
        if nxt == ancestor_id:
            return True
        current = nxt
    return False


def subordinate_ids(db: Session, tenant_id: UUID, manager_id: UUID) -> list[UUID]:
    """某人的所有（间接）下属 user id。"""
    out: list[UUID] = []
    children: dict[UUID, list[UUID]] = {}
    for uid, mgr in db.execute(
        select(User.id, User.manager_user_id).where(
            User.tenant_id == tenant_id, User.manager_user_id.is_not(None)
        )
    ).all():
        children.setdefault(mgr, []).append(uid)
    stack = list(children.get(manager_id, []))
    seen: set[UUID] = {manager_id}
    while stack:
        uid = stack.pop()
        if uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
        stack.extend(children.get(uid, []))
    return out


def validate_manager(db: Session, tenant_id: UUID, user_id: UUID, manager_user_id: UUID | None) -> None:
    """校验汇报线设置：不能自己汇报给自己、不能成环、跨租户非法。"""
    from fastapi import HTTPException

    if manager_user_id is None:
        return
    if manager_user_id == user_id:
        raise HTTPException(
            400,
            detail={"code": "INVALID_MANAGER", "message": "A user cannot report to themselves"},
        )
    manager = db.get(User, manager_user_id)
    if manager is None or manager.tenant_id != tenant_id or manager.status == "deleted":
        raise HTTPException(
            400,
            detail={"code": "INVALID_MANAGER", "message": "Manager is not an active tenant user"},
        )
    # 成环检测：新上级链上若已能回到本人 → 环
    seen: set[UUID] = set()
    current: UUID | None = manager_user_id
    while current is not None:
        if current == user_id:
            raise HTTPException(
                400,
                detail={"code": "INVALID_MANAGER", "message": "Reporting line would create a cycle"},
            )
        if current in seen:
            break
        seen.add(current)
        node = db.get(User, current)
        current = node.manager_user_id if node else None


def visible_to_user(db: Session, tenant_id: UUID, user_id: UUID) -> list[UUID]:
    """任务中心"我能看到的人"——  自己 + 下属。"""
    return [user_id, *subordinate_ids(db, tenant_id, user_id)]
