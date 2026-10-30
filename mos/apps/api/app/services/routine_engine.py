"""例行任务引擎 —— 触发 → 处理 → 草稿。

一段例行任务的完整链路：

    候选邮件/计划 → 触发规则匹配 → 技能处理（skill_runtime）
                  → 待确认草稿（DraftRecord）→ 通知负责角色

三条硬约束（写在代码里，不是写在文档里）：

1. **零自动落库** —— 这里只产出草稿，落库必须走 :func:`confirm_draft`（人工确认）。
2. **幂等** —— 草稿键 = ``<task.code>:<dedupe_key_template 渲染>``，
   ``(tenant_id, dedupe_key)`` 唯一 → 同一封邮件被拉两次只有一份草稿。
3. **失败显性** —— 处理失败落 ``status="failed"`` 且 ``error`` 写明原因，
   同时通知负责角色；**绝不静默吞掉**（「AI 恒答万能话术」的教训）。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.models_routine import DraftRecord, RoutineTask, SkillTemplate, TriggerRule
from app.models_wave1 import EmailMessage
from app.services.skill_runtime import run_skill

log = logging.getLogger("marios.routine_engine")

#: 入站候选邮件的默认回看窗口（天）—— 定时扫描只看最近的邮件
DEFAULT_SCAN_WINDOW_DAYS = 7

#: 单次扫描最多处理多少封邮件（防跑飞）
MAX_MESSAGES_PER_SCAN = 50

#: 草稿状态
STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"
STATUS_APPLIED = "applied"
STATUS_SUPERSEDED = "superseded"
STATUS_FAILED = "failed"


# ── 技能模板解析 ──────────────────────────────────────────────────────────

def resolve_skill(db: Session, tenant_id: UUID, code: str) -> SkillTemplate | None:
    """租户技能优先，其次平台模板（``tenant_id IS NULL``）。"""
    row = db.scalar(
        select(SkillTemplate).where(
            SkillTemplate.tenant_id == tenant_id, SkillTemplate.code == code
        )
    )
    if row is not None:
        return row
    return db.scalar(
        select(SkillTemplate).where(
            SkillTemplate.tenant_id.is_(None), SkillTemplate.code == code
        )
    )


# ── 触发规则匹配 ──────────────────────────────────────────────────────────

def _domain_of(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].strip().lower()


#: 「不限」通配符（folder / direction 字段用）
ANY = "*"


def rule_has_condition(rule: TriggerRule) -> bool:
    """规则是否至少有一个**实质性**条件。

    ``folder`` / ``direction`` 只是收窄条件（默认 inbox / inbound），
    **不算**实质性条件 —— 否则「空规则」（= 整个收件箱全匹配）就无法表达，
    端点也就没法拦它。通配 ``"*"`` 表示不限。
    """
    if [str(e).strip() for e in (rule.sender_emails or []) if str(e).strip()]:
        return True
    if [str(d).strip() for d in (rule.sender_domains or []) if str(d).strip()]:
        return True
    if (rule.subject_regex or "").strip():
        return True
    if [str(m).strip() for m in (rule.body_markers or []) if str(m).strip()]:
        return True
    return False


def rule_matches(rule: TriggerRule, message: EmailMessage) -> bool:
    """一条规则是否命中这封邮件 —— 规则内各条件之间是 AND。"""
    # 空规则 = 全匹配 —— 不允许（端点已拦，这里再兜一层）
    if not rule_has_condition(rule):
        return False

    sender_emails = [str(e).strip().lower() for e in (rule.sender_emails or []) if str(e).strip()]
    if sender_emails:
        frm = (message.from_email or "").strip().lower()
        if not any(frm == e or frm.endswith("@" + e) or e in frm for e in sender_emails):
            return False

    sender_domains = [str(d).strip().lower().lstrip("@") for d in (rule.sender_domains or []) if str(d).strip()]
    if sender_domains:
        domain = _domain_of(message.from_email)
        if not any(domain == d or domain.endswith("." + d) for d in sender_domains):
            return False

    if (rule.subject_regex or "").strip():
        try:
            if not re.search(rule.subject_regex, message.subject or "", re.I):
                return False
        except re.error:
            log.warning("routine_engine: invalid subject_regex %r on rule %s", rule.subject_regex, rule.id)
            return False

    markers = [str(m).strip().lower() for m in (rule.body_markers or []) if str(m).strip()]
    if markers:
        body = (message.body_text or "").lower()
        if not any(m in body for m in markers):
            return False

    folder = str(rule.folder or "").strip().lower()
    if folder and folder != ANY:
        if (message.folder or "inbox").lower() != folder:
            return False

    direction = str(rule.direction or "").strip().lower()
    if direction and direction != ANY:
        if (message.direction or "inbound").lower() != direction:
            return False

    return True


def task_rules(db: Session, tenant_id: UUID, task: RoutineTask) -> list[TriggerRule]:
    return list(
        db.scalars(
            select(TriggerRule).where(
                TriggerRule.tenant_id == tenant_id,
                TriggerRule.routine_task_id == task.id,
                TriggerRule.enabled.is_(True),
                TriggerRule.deleted_at.is_(None),
            )
        ).all()
    )


def match_task(db: Session, tenant_id: UUID, task: RoutineTask, message: EmailMessage) -> bool:
    rules = task_rules(db, tenant_id, task)
    return any(rule_matches(rule, message) for rule in rules)


# ── 幂等键 ────────────────────────────────────────────────────────────────

def build_dedupe_key(task: RoutineTask, *, message_id: str | None = None, period: str | None = None) -> str:
    """草稿幂等键 —— 一律带任务码前缀（不同任务处理同一封邮件不互相顶掉）。"""
    template = task.dedupe_key_template or "message:{message_id}"
    try:
        rendered = template.format(message_id=message_id or "", period=period or "", task_code=task.code)
    except (KeyError, IndexError):
        rendered = f"message:{message_id or period or ''}"
    return f"{task.code}:{rendered}"


def draft_exists(db: Session, tenant_id: UUID, dedupe_key: str) -> DraftRecord | None:
    return db.scalar(
        select(DraftRecord).where(
            DraftRecord.tenant_id == tenant_id, DraftRecord.dedupe_key == dedupe_key
        )
    )


# ── 候选扫描 ──────────────────────────────────────────────────────────────

def candidate_messages(
    db: Session,
    tenant_id: UUID,
    task: RoutineTask,
    *,
    window_days: int = DEFAULT_SCAN_WINDOW_DAYS,
    limit: int = MAX_MESSAGES_PER_SCAN,
) -> list[EmailMessage]:
    """入站候选邮件 —— 最近窗口内的 inbound 邮件（尚未处理过的会被幂等挡掉）。"""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    stmt = (
        select(EmailMessage)
        .where(
            EmailMessage.tenant_id == tenant_id,
            EmailMessage.direction == "inbound",
        )
        .order_by(EmailMessage.sent_at.desc().nullslast(), EmailMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(db.scalars(stmt).all())
    out: list[EmailMessage] = []
    for row in rows:
        sent_at = row.sent_at
        if sent_at is not None:
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            if sent_at < since:
                continue
        out.append(row)
    return out


# ── 草稿生成 ──────────────────────────────────────────────────────────────

def _notify_owner(db: Session, tenant_id: UUID, task: RoutineTask, draft: DraftRecord, *, failed: bool = False) -> None:
    """通知负责角色 —— 草稿待确认（或处理失败）都要有人知道。"""
    from app.services.notifications import notify_roles_once

    try:
        notify_roles_once(
            db,
            tenant_id,
            (task.owner_role,),
            title=("Routine task failed" if failed else "Routine task draft ready"),
            body=f"{task.name}: {(draft.error or 'draft')}",
            href=f"/routine?draft={draft.id}",
            level="warn" if failed else "info",
        )
    except Exception:  # noqa: BLE001 — 通知失败不该拖垮草稿生成
        log.warning("routine_engine: owner notification failed for draft %s", draft.id, exc_info=True)


def _audit(db: Session, tenant_id: UUID, action: str, draft: DraftRecord, detail: dict[str, Any] | None = None) -> None:
    from app.services.audit import audit

    try:
        audit(
            db,
            action=action,
            tenant_id=tenant_id,
            actor_user_id=draft.created_by,
            entity_type="draft_record",
            entity_id=draft.id,
            detail=detail or {},
        )
    except Exception:  # noqa: BLE001 — 审计不吞业务结果，但也不该让流程炸掉
        log.warning("routine_engine: audit %s failed for draft %s", action, draft.id, exc_info=True)


def process_message(
    db: Session,
    *,
    tenant_id: UUID,
    task: RoutineTask,
    message: EmailMessage,
    user_id: UUID | None = None,
) -> DraftRecord | None:
    """一封邮件 → 一份待确认草稿（不匹配规则 / 已处理过则返回 None）。"""
    if not task.enabled or task.trigger_type != "inbound_email":
        return None
    if not match_task(db, tenant_id, task, message):
        return None

    dedupe_key = build_dedupe_key(task, message_id=message.message_id)
    if draft_exists(db, tenant_id, dedupe_key) is not None:
        return None  # 幂等：已处理过

    skill = resolve_skill(db, tenant_id, task.skill_code)
    if skill is None:
        log.warning("routine_engine: skill %s not found for task %s", task.skill_code, task.code)
        draft = DraftRecord(
            tenant_id=tenant_id,
            routine_task_id=task.id,
            source_kind="email",
            source_email_id=message.id,
            dedupe_key=dedupe_key,
            target_entity=task.output_target,
            payload={},
            evidence=[],
            field_diff={},
            status=STATUS_FAILED,
            error=f"skill_not_found:{task.skill_code}",
            created_by=user_id,
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)
        _notify_owner(db, tenant_id, task, draft, failed=True)
        _audit(db, tenant_id, "routine.draft.failed", draft, {"error": draft.error})
        return draft

    provider = None
    try:
        from app.services.llm_client import resolve_provider_config

        provider = resolve_provider_config(db, tenant_id, skill_code=task.skill_code)
    except Exception:  # noqa: BLE001 — 没有 provider 就走规则腿（草稿会标 rule_fallback）
        provider = None

    result = run_skill(
        skill=skill,
        subject=message.subject or "",
        body=message.body_text or "",
        db=db,
        tenant_id=tenant_id,
        provider=provider,
        context={"message_id": message.message_id, "from_email": message.from_email},
    )

    failed = bool(result.error) or not result.payload
    error = result.error
    if not error and not result.payload:
        error = "no_fields_extracted"
    if not error and result.errors:
        # 校验没过：草稿仍生成（人能补），但要明示缺什么
        error = None

    draft = DraftRecord(
        tenant_id=tenant_id,
        routine_task_id=task.id,
        source_kind="email",
        source_email_id=message.id,
        dedupe_key=dedupe_key,
        target_entity=task.output_target,
        payload=result.payload,
        evidence=result.evidence,
        field_diff={**result.field_diff, "warnings": result.warnings},
        confidence=result.confidence,
        status=STATUS_FAILED if failed else STATUS_PENDING,
        error=error,
        created_by=user_id,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    _notify_owner(db, tenant_id, task, draft, failed=failed)
    _audit(
        db,
        tenant_id,
        "routine.draft.failed" if failed else "routine.draft.created",
        draft,
        {
            "task": task.code,
            "source": "email",
            "message_id": message.message_id,
            "fields": sorted(result.payload.keys()),
            "extracted_by": result.source,
            "error": error,
        },
    )
    return draft


def run_task(
    db: Session,
    *,
    tenant_id: UUID,
    task: RoutineTask,
    user_id: UUID | None = None,
    window_days: int = DEFAULT_SCAN_WINDOW_DAYS,
    limit: int = MAX_MESSAGES_PER_SCAN,
) -> list[DraftRecord]:
    """手动/定时跑一条例行任务 —— 返回本次产生的草稿。"""
    drafts: list[DraftRecord] = []
    if task.trigger_type == "inbound_email":
        for message in candidate_messages(db, tenant_id, task, window_days=window_days, limit=limit):
            draft = process_message(db, tenant_id=tenant_id, task=task, message=message, user_id=user_id)
            if draft is not None:
                drafts.append(draft)
    elif task.trigger_type == "schedule":
        draft = run_scheduled_task(db, tenant_id=tenant_id, task=task, user_id=user_id)
        if draft is not None:
            drafts.append(draft)
    return drafts


def run_scheduled_task(
    db: Session,
    *,
    tenant_id: UUID,
    task: RoutineTask,
    user_id: UUID | None = None,
    period: str | None = None,
) -> DraftRecord | None:
    """计划腿 —— 生成一份「系统数据」草稿（期一仅骨架，数据腿留期二）。"""
    period = period or datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    dedupe_key = build_dedupe_key(task, period=period)
    if draft_exists(db, tenant_id, dedupe_key) is not None:
        return None
    draft = DraftRecord(
        tenant_id=tenant_id,
        routine_task_id=task.id,
        source_kind="schedule",
        dedupe_key=dedupe_key,
        target_entity=task.output_target,
        payload={},
        evidence=[],
        field_diff={},
        status=STATUS_FAILED,
        error="scheduled_task_not_implemented",
        created_by=user_id,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    _notify_owner(db, tenant_id, task, draft, failed=True)
    return draft


# ── 人工确认后的写回腿 ──────────────────────────────────────────────────────

#: 写回目标 → 处理器名（见 :func:`_writeback`）
TARGETS = ("noon_report", "laytime_calc", "estimate")


def merge_confirmed(
    draft_payload: dict[str, Any] | None,
    override: dict[str, Any] | None = None,
    confirmed: set[str] | None = None,
) -> dict[str, Any]:
    """合并草稿字段 + 人工修正，并套用**字段子集**语义。

    ``confirmed`` 为 None = 全量确认；给了集合则集合外的字段一律视为不存在
    （不落库、不参与计算）—— 「人只认了部分字段」的核心语义。
    """
    merged: dict[str, Any] = dict(draft_payload or {})
    for key, value in (override or {}).items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    if confirmed is None:
        return merged
    return {k: v for k, v in merged.items() if k in confirmed}


def _writeback(
    db: Session,
    *,
    tenant_id: UUID,
    task: RoutineTask,
    draft: DraftRecord,
    fields: dict[str, Any],
    user_id: UUID | None,
) -> dict[str, Any]:
    """把确认后的字段真正写进业务表 —— 返回 ``{created, warnings, error, target_id}``。"""
    from app.models_domain import Voyage
    from app.models_wave1 import EmailMessage
    from app.services.email_writeback import (
        create_estimate_charter_from_recap,
        create_laytime_calc,
        match_counterparty_name,
        match_voyage,
        parse_dt,
        resolve_vessel,
    )

    target = task.output_target or ""
    msg = db.get(EmailMessage, draft.source_email_id) if draft.source_email_id else None
    subject = msg.subject if msg is not None else None

    if target == "noon_report":
        from app.services.noon_service import create_noon_report

        voyage = None
        voyage_id = fields.get("voyage_id")
        if voyage_id:
            voyage = db.get(Voyage, voyage_id) if isinstance(voyage_id, UUID) else None
            if voyage is not None and voyage.tenant_id != tenant_id:
                voyage = None
        if voyage is None:
            vessel = resolve_vessel(db, tenant_id, fields, subject)
            voyage = match_voyage(db, tenant_id, vessel, hint=fields.get("voyage_no") or subject)
        if voyage is None:
            return {"created": [], "warnings": [], "error": "VOYAGE_REQUIRED", "target_id": None}
        report_at = parse_dt(fields.get("report_at"))
        if report_at is None:
            return {"created": [], "warnings": [], "error": "REPORT_AT_REQUIRED", "target_id": None}
        if report_at.tzinfo is None:
            report_at = report_at.replace(tzinfo=timezone.utc)
        noon_fields = {
            "lat", "lon", "speed", "rob_fo", "rob_do", "eta_next", "remarks",
            "wind_bf", "sea_state", "current_kn",
        }
        eta_next = parse_dt(fields.get("eta_next"))
        if eta_next is not None and eta_next.tzinfo is None:
            eta_next = eta_next.replace(tzinfo=timezone.utc)
        try:
            res = create_noon_report(
                db,
                tenant_id=tenant_id,
                voyage_id=voyage.id,
                report_at=report_at,
                lat=fields.get("lat"),
                lon=fields.get("lon"),
                speed=fields.get("speed"),
                rob_fo=fields.get("rob_fo"),
                rob_do=fields.get("rob_do"),
                eta_next=eta_next,
                remarks=fields.get("remarks"),
                wind_bf=fields.get("wind_bf"),
                sea_state=fields.get("sea_state"),
                current_kn=fields.get("current_kn"),
                user_id=user_id,
                fields=set(fields.keys()) & noon_fields,
                commit=False,
            )
        except HTTPException as exc:
            db.rollback()
            return {"created": [], "warnings": [], "error": f"WRITE_BACK_FAILED:{exc.status_code}", "target_id": None}
        return {
            "created": [
                {
                    "entity": "noon_report",
                    "id": str(res["id"]),
                    "action": "created",
                    "voyage": res.get("voyage_no"),
                    "href": f"/operations/voyages/{res['voyage_id']}",
                }
            ],
            "warnings": [],
            "error": None,
            "target_id": str(res["id"]),
        }

    if msg is None:
        # 没有原邮件就无法复用邮件写回 creators —— 显性失败，不猜
        return {"created": [], "warnings": [], "error": "SOURCE_EMAIL_MISSING", "target_id": None}

    vessel = resolve_vessel(db, tenant_id, fields, subject)
    confirmed = set(fields.keys())

    if target == "laytime_calc":
        created, warnings, hints = create_laytime_calc(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            msg=msg,
            fields=fields,
            vessel=vessel,
            confirmed=confirmed,
        )
        target_id = created[0]["id"] if created else None
        return {
            "created": created,
            "warnings": warnings + hints,
            "error": None if created else "NOTHING_WRITTEN",
            "target_id": target_id,
        }

    if target == "estimate":
        cp_id, cp_name = match_counterparty_name(db, tenant_id, fields.get("charterers"))
        created, warnings, hints = create_estimate_charter_from_recap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            msg=msg,
            fields=fields,
            vessel=vessel,
            cp_id=cp_id,
            cp_name=cp_name,
            confirmed=confirmed,
        )
        target_id = created[0]["id"] if created else None
        return {
            "created": created,
            "warnings": warnings + hints,
            "error": None if created else "NOTHING_WRITTEN",
            "target_id": target_id,
        }

    return {"created": [], "warnings": [], "error": f"UNSUPPORTED_TARGET:{target}", "target_id": None}


def apply_draft(
    db: Session,
    *,
    tenant_id: UUID,
    draft: DraftRecord,
    payload: dict[str, Any] | None = None,
    confirmed: set[str] | None = None,
    comment: str | None = None,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    """人工确认 → 落库。

    返回 ``{"ok", "created", "warnings", "error", "target_id", "fields"}``；
    ``ok=False`` 时 ``error`` 写明原因（调用方据此回 409/422）。
    """
    task = db.get(RoutineTask, draft.routine_task_id)
    if task is None or task.tenant_id != tenant_id:
        return {"ok": False, "created": [], "warnings": [], "error": "TASK_NOT_FOUND", "target_id": None, "fields": {}}

    fields = merge_confirmed(draft.payload, payload, confirmed)

    # 服务端复验 —— 客户端传什么都不算，必须重新过一遍校验规则
    skill = resolve_skill(db, tenant_id, task.skill_code)
    if skill is not None:
        from app.services.skill_runtime import validate_payload

        schema = dict(skill.output_schema or {})
        errors = validate_payload(fields, dict(skill.validator_rules or {}), list(schema.get("required") or []))
        if errors:
            return {
                "ok": False,
                "created": [],
                "warnings": [],
                "error": "VALIDATION_FAILED",
                "errors": errors,
                "target_id": None,
                "fields": fields,
            }

    result = _writeback(
        db,
        tenant_id=tenant_id,
        task=task,
        draft=draft,
        fields=fields,
        user_id=user_id,
    )
    if result.get("error"):
        db.rollback()
        return {
            "ok": False,
            "created": result.get("created") or [],
            "warnings": result.get("warnings") or [],
            "error": result["error"],
            "target_id": None,
            "fields": fields,
        }

    before = dict(draft.payload or {})
    draft.payload = fields
    draft.target_id = _as_uuid(result.get("target_id"))
    draft.status = STATUS_APPLIED
    draft.decided_by = user_id
    draft.decided_at = datetime.now(timezone.utc)
    draft.decided_comment = comment
    draft.field_diff = {**(draft.field_diff or {}), "applied_diff": _diff(before, fields)}
    db.commit()

    _audit(
        db,
        tenant_id,
        "routine.draft.applied",
        draft,
        {
            "task": task.code,
            "target_entity": task.output_target,
            "target_id": result.get("target_id"),
            "created": result.get("created") or [],
            "fields": sorted(fields.keys()),
        },
    )
    return {
        "ok": True,
        "created": result.get("created") or [],
        "warnings": result.get("warnings") or [],
        "error": None,
        "target_id": result.get("target_id"),
        "fields": fields,
    }


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """落库前后字段差异（人工改了什么）——审计用。"""
    changed = {}
    for key in set(before) | set(after):
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changed[key] = {"before": old, "after": new}
    return changed


def _as_uuid(value: Any) -> UUID | None:
    """把 creator 返回的 id（字符串或 UUID）统一成 UUID —— 列是 Uuid 类型。"""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
