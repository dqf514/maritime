"""例行任务中枢 API（期一）。

端点分组：

* **任务与技能**（``/routine/tasks``、``/routine/skills``）—— 租户管理员配置；
* **待确认草稿**（``/routine/drafts``）—— 角色信箱：任务的 ``owner_role`` 负责角色
  或租户管理员可见可确认。

三条不可协商的约束（写在这里，也写在服务层）：

1. **草稿不自动落库** —— 只有 ``POST /routine/drafts/{id}/confirm`` 才写业务表；
2. **四眼** —— 草稿的创建人不能自己确认（``SELF_APPROVAL_BLOCKED``）；
3. **失败显性** —— 技能跑挂的草稿是 ``status="failed"`` 且带 ``error``，不是消失。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Module
from app.models_routine import DraftRecord, RoutineTask, SkillTemplate, TriggerRule
from app.security import (
    AuthContext,
    get_current_auth,
    require_module_role,
    tenant_has_module,
)
from app.services.audit import audit

log = logging.getLogger("marios.routine")

router = APIRouter(prefix="/routine", tags=["Routine"])

#: 管理员角色 —— 看得到全部草稿
ADMIN_ROLES = {"tenant_admin", "platform_admin"}

#: 允许的触发方式（期一实现 inbound_email / schedule）
TRIGGER_TYPES = {"inbound_email", "schedule", "event"}

#: 允许的落库目标
OUTPUT_TARGETS = {"noon_report", "laytime_calc", "estimate"}


# ── 入参模型 ──────────────────────────────────────────────────────────────


class RoutineTaskIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    direction: str = "inbound"
    module_code: str = Field(min_length=1, max_length=64)
    trigger_type: str = "inbound_email"
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    skill_code: str = Field(min_length=1, max_length=64)
    output_target: str | None = None
    owner_role: str = "operations"
    sla_minutes: int = Field(default=120, ge=1, le=60 * 24 * 14)
    dedupe_key_template: str = "message:{message_id}"
    enabled: bool = True


class RoutineTaskPatch(BaseModel):
    name: str | None = None
    module_code: str | None = None
    trigger_type: str | None = None
    trigger_config: dict[str, Any] | None = None
    skill_code: str | None = None
    output_target: str | None = None
    owner_role: str | None = None
    sla_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 14)
    dedupe_key_template: str | None = None
    enabled: bool | None = None


class TriggerRuleIn(BaseModel):
    sender_emails: list[str] = Field(default_factory=list)
    sender_domains: list[str] = Field(default_factory=list)
    subject_regex: str | None = None
    body_markers: list[str] = Field(default_factory=list)
    folder: str = "inbox"  # "*" = 不限
    direction: str = "inbound"  # "*" = 不限
    priority: int = 100
    enabled: bool = True


class TriggerRulesIn(BaseModel):
    rules: list[TriggerRuleIn] = Field(default_factory=list)


class SkillIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    purpose: str | None = None
    prompt_template: str | None = None
    output_schema: dict[str, Any] = Field(default_factory=dict)
    validator_rules: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    deterministic_engine: str | None = None
    based_on: str | None = None
    enabled: bool = True


class SkillPatch(BaseModel):
    name: str | None = None
    purpose: str | None = None
    prompt_template: str | None = None
    output_schema: dict[str, Any] | None = None
    validator_rules: dict[str, Any] | None = None
    allowed_tools: list[str] | None = None
    deterministic_engine: str | None = None
    enabled: bool | None = None


class DraftConfirmIn(BaseModel):
    payload: dict[str, Any] | None = None
    confirmed: list[str] | None = None  # 字段子集；None = 全量确认
    comment: str | None = None


class DraftRejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


# ── 输出模型 ──────────────────────────────────────────────────────────────


def task_out(task: RoutineTask) -> dict:
    return {
        "id": str(task.id),
        "code": task.code,
        "name": task.name,
        "direction": task.direction,
        "module_code": task.module_code,
        "trigger_type": task.trigger_type,
        "trigger_config": task.trigger_config or {},
        "skill_code": task.skill_code,
        "output_target": task.output_target,
        "owner_role": task.owner_role,
        "sla_minutes": task.sla_minutes,
        "dedupe_key_template": task.dedupe_key_template,
        "enabled": bool(task.enabled),
        "created_by": str(task.created_by) if task.created_by else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "deleted_at": task.deleted_at.isoformat() if task.deleted_at else None,
    }


def trigger_out(rule: TriggerRule) -> dict:
    return {
        "id": str(rule.id),
        "routine_task_id": str(rule.routine_task_id),
        "sender_emails": rule.sender_emails or [],
        "sender_domains": rule.sender_domains or [],
        "subject_regex": rule.subject_regex,
        "body_markers": rule.body_markers or [],
        "folder": rule.folder,
        "direction": rule.direction,
        "priority": rule.priority,
        "enabled": bool(rule.enabled),
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


def skill_out(skill: SkillTemplate) -> dict:
    return {
        "id": str(skill.id),
        "code": skill.code,
        "scope": "platform" if skill.tenant_id is None else "tenant",
        "name": skill.name,
        "purpose": skill.purpose,
        "prompt_template": skill.prompt_template,
        "output_schema": skill.output_schema or {},
        "validator_rules": skill.validator_rules or {},
        "allowed_tools": skill.allowed_tools or [],
        "deterministic_engine": skill.deterministic_engine,
        "version": skill.version,
        "enabled": bool(skill.enabled),
        "based_on": skill.based_on,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }


def draft_out(
    draft: DraftRecord,
    task: RoutineTask | None = None,
    source: dict | None = None,
) -> dict:
    return {
        "id": str(draft.id),
        "routine_task_id": str(draft.routine_task_id),
        "task_code": task.code if task is not None else None,
        "task_name": task.name if task is not None else None,
        "owner_role": task.owner_role if task is not None else None,
        "source_kind": draft.source_kind,
        "source_email_id": str(draft.source_email_id) if draft.source_email_id else None,
        "dedupe_key": draft.dedupe_key,
        "target_entity": draft.target_entity,
        "target_id": str(draft.target_id) if draft.target_id else None,
        "payload": draft.payload or {},
        "field_diff": draft.field_diff or {},
        "evidence": draft.evidence or [],
        "confidence": float(draft.confidence) if draft.confidence is not None else None,
        "status": draft.status,
        "error": draft.error,
        "decided_by": str(draft.decided_by) if draft.decided_by else None,
        "decided_at": draft.decided_at.isoformat() if draft.decided_at else None,
        "decided_comment": draft.decided_comment,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        "source_email": source,
    }


#: 来源邮件正文摘录长度（够核对证据，不整封复制）
SOURCE_EXCERPT_CHARS = 1500


def _source_email_map(db: Session, tenant_id: UUID, email_ids: set[UUID]) -> dict[UUID, dict]:
    """批量取来源邮件的元信息（列表页用；避免 N+1）。"""
    if not email_ids:
        return {}
    from app.models_wave1 import EmailMessage

    rows = db.scalars(
        select(EmailMessage).where(
            EmailMessage.tenant_id == tenant_id,
            EmailMessage.id.in_(tuple(email_ids)),
        )
    ).all()
    return {row.id: row for row in rows}


def _source_brief(row: Any) -> dict:
    return {
        "id": str(row.id),
        "subject": row.subject,
        "from_email": row.from_email,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "folder": row.folder,
    }


def _source_excerpt(row: Any) -> dict:
    brief = _source_brief(row)
    body = row.body_text or ""
    brief["body_excerpt"] = body[:SOURCE_EXCERPT_CHARS]
    brief["body_truncated"] = len(body) > SOURCE_EXCERPT_CHARS
    return brief


# ── 内部助手 ──────────────────────────────────────────────────────────────


def _fail(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **extra})


def _get_task(db: Session, tenant_id: UUID, task_id: UUID) -> RoutineTask:
    task = db.get(RoutineTask, task_id)
    if task is None or task.tenant_id != tenant_id or task.deleted_at is not None:
        raise _fail(404, "TASK_NOT_FOUND", "Routine task not found")
    return task


def _get_draft(db: Session, tenant_id: UUID, draft_id: UUID) -> DraftRecord:
    draft = db.get(DraftRecord, draft_id)
    if draft is None or draft.tenant_id != tenant_id or draft.deleted_at is not None:
        raise _fail(404, "DRAFT_NOT_FOUND", "Draft not found")
    return draft


def _is_admin(auth: AuthContext) -> bool:
    return bool(ADMIN_ROLES & set(auth.roles))


def _assert_task_access(db: Session, auth: AuthContext, task: RoutineTask) -> None:
    """草稿可见性 —— 许可轴 + 角色轴（负责角色或管理员）。"""
    if not tenant_has_module(db, auth.tenant_id, task.module_code):
        raise _fail(403, "MODULE_NOT_LICENSED", f"Module '{task.module_code}' is not licensed")
    if _is_admin(auth):
        return
    if task.owner_role not in auth.roles:
        raise _fail(
            403,
            "ROLE_REQUIRED",
            "Only the task owner role or a tenant admin may act on this draft",
            roles=sorted({task.owner_role} | ADMIN_ROLES),
        )


def _assert_skill_exists(db: Session, tenant_id: UUID, code: str) -> SkillTemplate:
    skill = db.scalar(
        select(SkillTemplate).where(SkillTemplate.tenant_id == tenant_id, SkillTemplate.code == code)
    ) or db.scalar(
        select(SkillTemplate).where(SkillTemplate.tenant_id.is_(None), SkillTemplate.code == code)
    )
    if skill is None:
        raise _fail(422, "SKILL_NOT_FOUND", f"Skill template '{code}' not found")
    return skill


def _assert_module_exists(db: Session, module_code: str) -> None:
    """模块码必须存在 —— Module 是全局参考表（无 tenant_id）。"""
    exists = db.scalar(select(Module).where(Module.code == module_code))
    if exists is None:
        raise _fail(422, "MODULE_NOT_FOUND", f"Module '{module_code}' does not exist")


def _rule_has_condition(rule: TriggerRuleIn) -> bool:
    return bool(
        rule.sender_emails
        or rule.sender_domains
        or (rule.subject_regex or "").strip()
        or rule.body_markers
    )


def _ranges_narrowed(old: dict, new: dict) -> bool:
    """新范围只能更紧（区间收窄 / 新增键），不能放松。"""
    for key, bounds in (new or {}).items():
        if key not in (old or {}):
            continue
        old_bounds = old[key]
        try:
            o_low, o_high = old_bounds[0], old_bounds[1]
            n_low, n_high = bounds[0], bounds[1]
        except (TypeError, IndexError):
            return False
        if o_low is not None and (n_low is None or n_low < o_low):
            return False
        if o_high is not None and (n_high is None or n_high > o_high):
            return False
    return True


def _one_of_narrowed(old: dict, new: dict) -> bool:
    """枚举只能收窄。"""
    for key, allowed in (new or {}).items():
        if key not in (old or {}):
            continue
        old_set = {str(a).upper() for a in (old[key] or [])}
        new_set = {str(a).upper() for a in (allowed or [])}
        if not new_set.issubset(old_set):
            return False
    return True


# ── 任务 ──────────────────────────────────────────────────────────────────


@router.get("/tasks")
def list_tasks(
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
    include_disabled: bool = Query(default=True),
):
    """任务列表（租户内）。"""
    stmt = select(RoutineTask).where(RoutineTask.tenant_id == auth.tenant_id)
    if not include_disabled:
        stmt = stmt.where(RoutineTask.enabled.is_(True))
    rows = db.scalars(stmt.order_by(RoutineTask.code)).all()
    return {"items": [task_out(t) for t in rows], "total": len(rows)}


@router.post("/tasks", status_code=201)
def create_task(
    body: RoutineTaskIn,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    """新建例行任务。"""
    if body.trigger_type not in TRIGGER_TYPES:
        raise _fail(422, "INVALID_TRIGGER_TYPE", f"trigger_type must be one of {sorted(TRIGGER_TYPES)}")
    if body.output_target and body.output_target not in OUTPUT_TARGETS:
        raise _fail(422, "INVALID_OUTPUT_TARGET", f"output_target must be one of {sorted(OUTPUT_TARGETS)}")
    _assert_module_exists(db, body.module_code)
    _assert_skill_exists(db, auth.tenant_id, body.skill_code)
    exists = db.scalar(
        select(RoutineTask.id).where(RoutineTask.tenant_id == auth.tenant_id, RoutineTask.code == body.code)
    )
    if exists is not None:
        raise _fail(409, "TASK_CODE_TAKEN", f"Routine task code '{body.code}' already exists")
    task = RoutineTask(
        tenant_id=auth.tenant_id,
        code=body.code,
        name=body.name,
        direction=body.direction,
        module_code=body.module_code,
        trigger_type=body.trigger_type,
        trigger_config=body.trigger_config or {},
        skill_code=body.skill_code,
        output_target=body.output_target,
        owner_role=body.owner_role,
        sla_minutes=body.sla_minutes,
        dedupe_key_template=body.dedupe_key_template,
        enabled=body.enabled,
        created_by=auth.user_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    audit(
        db,
        action="routine.task.created",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="routine_task",
        entity_id=task.id,
        detail={"fields": ["code", "skill_code", "output_target", "module_code"]},
    )
    db.commit()
    return task_out(task)


@router.get("/tasks/{task_id}")
def get_task(
    task_id: UUID,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    return task_out(_get_task(db, auth.tenant_id, task_id))


@router.patch("/tasks/{task_id}")
def patch_task(
    task_id: UUID,
    body: RoutineTaskPatch,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    task = _get_task(db, auth.tenant_id, task_id)
    data = body.model_dump(exclude_none=True)
    if "module_code" in data:
        _assert_module_exists(db, data["module_code"])
    if "skill_code" in data:
        _assert_skill_exists(db, auth.tenant_id, data["skill_code"])
    if data.get("trigger_type") and data["trigger_type"] not in TRIGGER_TYPES:
        raise _fail(422, "INVALID_TRIGGER_TYPE", f"trigger_type must be one of {sorted(TRIGGER_TYPES)}")
    if data.get("output_target") and data["output_target"] not in OUTPUT_TARGETS:
        raise _fail(422, "INVALID_OUTPUT_TARGET", f"output_target must be one of {sorted(OUTPUT_TARGETS)}")
    before = task_out(task)
    for key, value in data.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    audit(
        db,
        action="routine.task.updated",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="routine_task",
        entity_id=task.id,
        detail={"before": before, "fields": sorted(data.keys())},
    )
    db.commit()
    return task_out(task)


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: UUID,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    """软删（``deleted_at``）—— 草稿留档，不物理删除。"""
    task = _get_task(db, auth.tenant_id, task_id)
    task.deleted_at = datetime.now(timezone.utc)
    task.enabled = False
    db.commit()
    audit(
        db,
        action="routine.task.deleted",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="routine_task",
        entity_id=task.id,
        detail={"fields": ["deleted_at"]},
    )
    db.commit()
    return {"ok": True, "id": str(task.id)}


@router.post("/tasks/{task_id}/run")
def run_task_now(
    task_id: UUID,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    """手动跑一次任务 —— 立即扫描候选邮件并生成草稿（幂等：已处理的不会重复）。"""
    from app.services.routine_engine import run_task

    task = _get_task(db, auth.tenant_id, task_id)
    drafts = run_task(db, tenant_id=auth.tenant_id, task=task, user_id=auth.user_id)
    return {
        "task": task_out(task),
        "drafts": [draft_out(d, task) for d in drafts],
        "created": len(drafts),
    }


@router.get("/tasks/{task_id}/triggers")
def list_triggers(
    task_id: UUID,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    task = _get_task(db, auth.tenant_id, task_id)
    rows = db.scalars(
        select(TriggerRule).where(
            TriggerRule.tenant_id == auth.tenant_id,
            TriggerRule.routine_task_id == task.id,
            TriggerRule.deleted_at.is_(None),
        ).order_by(TriggerRule.priority, TriggerRule.created_at)
    ).all()
    return {"items": [trigger_out(r) for r in rows], "total": len(rows)}


@router.put("/tasks/{task_id}/triggers")
def replace_triggers(
    task_id: UUID,
    body: TriggerRulesIn,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    """整组替换触发规则。空规则（一个条件都没有）一律拒绝。"""
    task = _get_task(db, auth.tenant_id, task_id)
    for rule in body.rules:
        if not _rule_has_condition(rule):
            raise _fail(
                422,
                "EMPTY_TRIGGER_RULE",
                "Each trigger rule needs at least one condition "
                "(sender / domain / subject / body marker) — an empty rule would match every mail",
            )
        if rule.subject_regex:
            import re as _re

            try:
                _re.compile(rule.subject_regex)
            except _re.error as exc:
                raise _fail(422, "INVALID_SUBJECT_REGEX", f"Invalid subject_regex: {exc}") from exc

    db.query(TriggerRule).filter(
        TriggerRule.tenant_id == auth.tenant_id, TriggerRule.routine_task_id == task.id
    ).delete(synchronize_session=False)
    db.flush()
    created: list[TriggerRule] = []
    for rule in body.rules:
        row = TriggerRule(
            tenant_id=auth.tenant_id,
            routine_task_id=task.id,
            sender_emails=rule.sender_emails or [],
            sender_domains=rule.sender_domains or [],
            subject_regex=rule.subject_regex,
            body_markers=rule.body_markers or [],
            folder=rule.folder,
            direction=rule.direction,
            priority=rule.priority,
            enabled=rule.enabled,
            created_by=auth.user_id,
        )
        db.add(row)
        created.append(row)
    db.commit()
    for row in created:
        db.refresh(row)
    audit(
        db,
        action="routine.task.triggers_replaced",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="routine_task",
        entity_id=task.id,
        detail={"fields": ["triggers"], "count": len(created)},
    )
    db.commit()
    return {"items": [trigger_out(r) for r in created], "total": len(created)}


# ── 技能模板 ──────────────────────────────────────────────────────────────


@router.get("/skills")
def list_skills(
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
    scope: str = Query(default="all", pattern="^(all|platform|tenant)$"),
):
    """技能模板列表（平台模板 + 租户自己的模板）。"""
    stmt = select(SkillTemplate)
    if scope == "platform":
        stmt = stmt.where(SkillTemplate.tenant_id.is_(None))
    elif scope == "tenant":
        stmt = stmt.where(SkillTemplate.tenant_id == auth.tenant_id)
    else:
        stmt = stmt.where(
            (SkillTemplate.tenant_id.is_(None)) | (SkillTemplate.tenant_id == auth.tenant_id)
        )
    rows = db.scalars(stmt.order_by(SkillTemplate.code)).all()
    return {"items": [skill_out(s) for s in rows], "total": len(rows)}


@router.post("/skills", status_code=201)
def create_skill(
    body: SkillIn,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    """新建**租户级**技能模板（平台模板不可改，只能基于它另建）。"""
    if not (body.output_schema or {}).get("kind"):
        raise _fail(422, "SKILL_KIND_REQUIRED", "output_schema.kind is required")
    exists = db.scalar(select(SkillTemplate.id).where(SkillTemplate.code == body.code))
    if exists is not None:
        raise _fail(409, "SKILL_CODE_TAKEN", f"Skill code '{body.code}' already exists")
    if body.based_on:
        _assert_skill_exists(db, auth.tenant_id, body.based_on)
    skill = SkillTemplate(
        tenant_id=auth.tenant_id,
        code=body.code,
        name=body.name,
        purpose=body.purpose,
        prompt_template=body.prompt_template,
        output_schema=body.output_schema or {},
        validator_rules=body.validator_rules or {},
        allowed_tools=body.allowed_tools or [],
        deterministic_engine=body.deterministic_engine,
        version=1,
        enabled=body.enabled,
        based_on=body.based_on,
        created_by=auth.user_id,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    audit(
        db,
        action="routine.skill.created",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="skill_template",
        entity_id=skill.id,
        detail={"fields": ["code", "output_schema", "validator_rules"]},
    )
    db.commit()
    return skill_out(skill)


def _get_skill(db: Session, tenant_id: UUID, code: str) -> SkillTemplate:
    skill = db.scalar(
        select(SkillTemplate).where(SkillTemplate.tenant_id == tenant_id, SkillTemplate.code == code)
    ) or db.scalar(
        select(SkillTemplate).where(SkillTemplate.tenant_id.is_(None), SkillTemplate.code == code)
    )
    if skill is None:
        raise _fail(404, "SKILL_NOT_FOUND", f"Skill template '{code}' not found")
    return skill


@router.get("/skills/{code}")
def get_skill(
    code: str,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    return skill_out(_get_skill(db, auth.tenant_id, code))


@router.patch("/skills/{code}")
def patch_skill(
    code: str,
    body: SkillPatch,
    auth: AuthContext = Depends(require_module_role("platform", "platform_admin")),
    db: Session = Depends(get_db),
):
    """改技能模板 —— **只能收紧校验，不能放松**；抽取类型（kind）不可改。

    放松校验 = 让后来的坏数据合法化，所以这里直接拒绝（422）。
    """
    skill = _get_skill(db, auth.tenant_id, code)
    if skill.tenant_id is None:
        raise _fail(
            403,
            "PLATFORM_SKILL_IMMUTABLE",
            "Platform skill templates are read-only — copy it into a tenant skill instead",
        )
    data = body.model_dump(exclude_none=True)

    if "output_schema" in data:
        old_schema = dict(skill.output_schema or {})
        new_schema = dict(data["output_schema"] or {})
        if new_schema.get("kind") != old_schema.get("kind"):
            raise _fail(
                422,
                "SKILL_KIND_IMMUTABLE",
                "output_schema.kind cannot change — it defines the extraction contract",
            )
        old_required = set(old_schema.get("required") or [])
        new_required = set(new_schema.get("required") or [])
        if not old_required.issubset(new_required):
            raise _fail(
                422,
                "SKILL_VALIDATION_LOOSENED",
                "required fields may only be added, never removed",
            )
        skill.output_schema = new_schema

    if "validator_rules" in data:
        old_rules = dict(skill.validator_rules or {})
        new_rules = dict(data["validator_rules"] or {})
        if not _ranges_narrowed(old_rules.get("ranges") or {}, new_rules.get("ranges") or {}):
            raise _fail(422, "SKILL_VALIDATION_LOOSENED", "numeric ranges may only be narrowed")
        if not _one_of_narrowed(old_rules.get("one_of") or {}, new_rules.get("one_of") or {}):
            raise _fail(422, "SKILL_VALIDATION_LOOSENED", "enum sets may only be narrowed")
        skill.validator_rules = new_rules

    for key in ("name", "purpose", "prompt_template", "allowed_tools", "deterministic_engine", "enabled"):
        if key in data:
            setattr(skill, key, data[key])
    db.commit()
    db.refresh(skill)
    audit(
        db,
        action="routine.skill.updated",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="skill_template",
        entity_id=skill.id,
        detail={"fields": sorted(data.keys())},
    )
    db.commit()
    return skill_out(skill)


# ── 草稿（角色信箱）────────────────────────────────────────────────────────


@router.get("/drafts")
def list_drafts(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
    status: str | None = Query(default=None),
    task_code: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """草稿列表 —— 只返回本人有权看到的（负责角色 + 管理员）。"""
    tasks = list(
        db.scalars(select(RoutineTask).where(RoutineTask.tenant_id == auth.tenant_id)).all()
    )
    by_id = {t.id: t for t in tasks}
    if _is_admin(auth):
        visible = tasks
    else:
        visible = [t for t in tasks if t.owner_role in auth.roles]
    visible_ids = [t.id for t in visible]
    if not visible_ids:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}

    stmt = select(DraftRecord).where(
        DraftRecord.tenant_id == auth.tenant_id,
        DraftRecord.deleted_at.is_(None),
        DraftRecord.routine_task_id.in_(visible_ids),
    )
    if status:
        stmt = stmt.where(DraftRecord.status == status)
    if task_code:
        target = next((t for t in visible if t.code == task_code), None)
        if target is None:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        stmt = stmt.where(DraftRecord.routine_task_id == target.id)
    total = len(db.scalars(stmt).all())
    rows = db.scalars(
        stmt.order_by(DraftRecord.created_at.desc()).limit(limit).offset(offset)
    ).all()
    sources = _source_email_map(
        db, auth.tenant_id, {d.source_email_id for d in rows if d.source_email_id}
    )
    return {
        "items": [
            draft_out(
                d,
                by_id.get(d.routine_task_id),
                _source_brief(sources[d.source_email_id]) if d.source_email_id in sources else None,
            )
            for d in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/drafts/{draft_id}")
def get_draft(
    draft_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    draft = _get_draft(db, auth.tenant_id, draft_id)
    task = db.get(RoutineTask, draft.routine_task_id)
    _assert_task_access(db, auth, task)
    source = None
    if draft.source_email_id:
        from app.models_wave1 import EmailMessage

        row = db.scalar(
            select(EmailMessage).where(
                EmailMessage.tenant_id == auth.tenant_id,
                EmailMessage.id == draft.source_email_id,
            )
        )
        if row is not None:
            source = _source_excerpt(row)
    return draft_out(draft, task, source)


@router.post("/drafts/{draft_id}/confirm")
def confirm_draft(
    draft_id: UUID,
    body: DraftConfirmIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """人工确认 → 真正落库。

    - ``payload`` —— 人工修正后的字段（覆盖草稿值）；
    - ``confirmed`` —— **字段子集**：只列出的字段才算确认，没列出的不落库；
    - 四眼：草稿创建人不能自己确认。
    """
    from app.services.routine_engine import apply_draft

    draft = _get_draft(db, auth.tenant_id, draft_id)
    task = db.get(RoutineTask, draft.routine_task_id)
    _assert_task_access(db, auth, task)

    if draft.status != "pending":
        raise _fail(
            409,
            "INVALID_STATE",
            f"Draft is '{draft.status}' — only pending drafts can be confirmed",
        )
    if draft.created_by is not None and draft.created_by == auth.user_id:
        raise _fail(
            409,
            "SELF_APPROVAL_BLOCKED",
            "The person who triggered this draft cannot confirm it — four-eyes rule",
        )

    confirmed = set(body.confirmed) if body.confirmed is not None else None
    result = apply_draft(
        db,
        tenant_id=auth.tenant_id,
        draft=draft,
        payload=body.payload,
        confirmed=confirmed,
        comment=body.comment,
        user_id=auth.user_id,
    )
    if not result["ok"]:
        code = result["error"] or "WRITE_BACK_FAILED"
        if code == "VALIDATION_FAILED":
            raise _fail(422, "VALIDATION_FAILED", "Draft payload failed validation", errors=result.get("errors"))
        if code in ("VOYAGE_REQUIRED", "REPORT_AT_REQUIRED", "SOURCE_EMAIL_MISSING"):
            raise _fail(422, code, "Draft is missing information required to write it back")
        raise _fail(409, code, "Draft could not be applied")
    db.refresh(draft)
    return {
        "draft": draft_out(draft, task),
        "created": result["created"],
        "warnings": result["warnings"],
        "target_id": result["target_id"],
    }


@router.post("/drafts/{draft_id}/reject")
def reject_draft(
    draft_id: UUID,
    body: DraftRejectIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """驳回草稿 —— 必须写明理由（理由进审计）。"""
    draft = _get_draft(db, auth.tenant_id, draft_id)
    task = db.get(RoutineTask, draft.routine_task_id)
    _assert_task_access(db, auth, task)
    if draft.status not in ("pending", "failed"):
        raise _fail(409, "INVALID_STATE", f"Draft is '{draft.status}' — only pending drafts can be rejected")
    draft.status = "rejected"
    draft.decided_by = auth.user_id
    draft.decided_at = datetime.now(timezone.utc)
    draft.decided_comment = body.reason
    db.commit()
    db.refresh(draft)
    audit(
        db,
        action="routine.draft.rejected",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="draft_record",
        entity_id=draft.id,
        detail={"fields": ["status"], "reason": body.reason},
    )
    db.commit()
    return draft_out(draft, task)


@router.post("/drafts/{draft_id}/reprocess")
def reprocess_draft(
    draft_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """重跑技能 —— 处理失败的草稿修好模板/规则后可以再试一次。"""
    from app.models_wave1 import EmailMessage
    from app.services.routine_engine import resolve_skill
    from app.services.skill_runtime import run_skill

    draft = _get_draft(db, auth.tenant_id, draft_id)
    task = db.get(RoutineTask, draft.routine_task_id)
    _assert_task_access(db, auth, task)
    if draft.status in ("applied", "rejected"):
        raise _fail(409, "INVALID_STATE", f"Draft is '{draft.status}' — it cannot be reprocessed")
    if not draft.source_email_id:
        raise _fail(422, "SOURCE_EMAIL_MISSING", "Only email-sourced drafts can be reprocessed")
    msg = db.get(EmailMessage, draft.source_email_id)
    if msg is None or msg.tenant_id != auth.tenant_id:
        raise _fail(404, "SOURCE_EMAIL_MISSING", "The source email no longer exists")
    skill = resolve_skill(db, auth.tenant_id, task.skill_code)
    if skill is None:
        raise _fail(422, "SKILL_NOT_FOUND", f"Skill template '{task.skill_code}' not found")

    provider = None
    try:
        from app.services.llm_client import resolve_provider_config

        provider = resolve_provider_config(db, auth.tenant_id, skill_code=task.skill_code)
    except Exception:  # noqa: BLE001 — 没 provider 就走规则腿
        provider = None

    result = run_skill(
        skill=skill,
        subject=msg.subject or "",
        body=msg.body_text or "",
        db=db,
        tenant_id=auth.tenant_id,
        provider=provider,
    )
    draft.payload = result.payload
    draft.evidence = result.evidence
    draft.confidence = result.confidence
    draft.field_diff = {**result.field_diff, "warnings": result.warnings}
    draft.status = "failed" if (result.error or not result.payload) else "pending"
    draft.error = result.error or (None if result.payload else "no_fields_extracted")
    db.commit()
    db.refresh(draft)
    audit(
        db,
        action="routine.draft.reprocessed",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="draft_record",
        entity_id=draft.id,
        detail={"fields": sorted(result.payload.keys()), "status": draft.status, "error": draft.error},
    )
    db.commit()
    return draft_out(draft, task)
