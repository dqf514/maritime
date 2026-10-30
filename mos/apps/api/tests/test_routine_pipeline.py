"""例行任务中枢（期一）—— 触发 / 处理 / 幂等 / 降级 / 证据 / 字段子集 / 权限。

覆盖中枢的三条红线：

1. **无证据不落字段** —— 指不回原文的字段一律丢弃（并明示 warning）；
2. **幂等** —— 同一封邮件跑两遍只出一份草稿；
3. **失败显性 + 四眼** —— 技能跑挂落 ``failed`` 草稿并带原因；草稿创建人不能自己确认。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import Tenant, User
from app.models_routine import DraftRecord, RoutineTask, SkillTemplate, TriggerRule
from app.models_wave1 import EmailMessage
from app.security import hash_password
from app.services.routine_engine import (
    build_dedupe_key,
    candidate_messages,
    process_message,
    rule_matches,
    run_task,
)
from app.services.skill_runtime import run_skill


@pytest.fixture()
def open_db(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)


def _demo_tenant(db) -> Tenant:
    return db.scalar(select(Tenant).where(Tenant.code == "demo"))


def _login(client, email: str, tenant_code: str = "demo") -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Demo1234!", "tenant_code": tenant_code},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_task(db, tenant, *, code="t_noon", owner_role="operations", skill_code="noon_report",
               output_target="noon_report", module_code="operations") -> RoutineTask:
    task = RoutineTask(
        tenant_id=tenant.id,
        code=code,
        name="Noon report intake",
        direction="inbound",
        module_code=module_code,
        trigger_type="inbound_email",
        trigger_config={},
        skill_code=skill_code,
        output_target=output_target,
        owner_role=owner_role,
        sla_minutes=60,
        dedupe_key_template="message:{message_id}",
        enabled=True,
    )
    db.add(task)
    db.flush()
    return task


def _make_rule(db, tenant, task, **kw) -> TriggerRule:
    rule = TriggerRule(
        tenant_id=tenant.id,
        routine_task_id=task.id,
        sender_emails=kw.get("sender_emails", []),
        sender_domains=kw.get("sender_domains", []),
        subject_regex=kw.get("subject_regex"),
        body_markers=kw.get("body_markers", []),
        folder=kw.get("folder", "inbox"),
        direction=kw.get("direction", "inbound"),
        priority=100,
        enabled=True,
    )
    db.add(rule)
    db.flush()
    return rule


def _make_email(db, tenant, *, subject="Noon report — Ocean Star", body="", sender="master@oceanstar.com",
                 message_id=None, folder="inbox", direction="inbound", days_ago=0) -> EmailMessage:
    msg = EmailMessage(
        tenant_id=tenant.id,
        message_id=message_id or f"<m-{uuid.uuid4().hex[:10]}@oceanstar.com>",
        direction=direction,
        folder=folder,
        from_email=sender,
        subject=subject,
        body_text=body,
        sent_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        parse_status="pending",
        parse_result={},
    )
    db.add(msg)
    db.flush()
    return msg


NOON_BODY = (
    "NOON REPORT\n"
    "Vessel: Ocean Star\n"
    "Report at: 2026-10-30 06:00\n"
    "Lat: 12.5\n"
    "Lon: 118.2\n"
    "Speed: 12.5\n"
    "ROB FO: 320\n"
    "ROB DO: 180\n"
    "ETA next: 2026-11-02 08:00\n"
    "Sea state: slight\n"
)


def _dropped(warnings: list[str]) -> set[str]:
    """从 ``no_evidence:a,b`` 告警里取出被丢弃的字段名。"""
    out: set[str] = set()
    for w in warnings:
        if w.startswith("no_evidence:"):
            out.update(x for x in w.split(":", 1)[1].split(",") if x)
    return out


# ── 1. 触发规则匹配 ───────────────────────────────────────────────────────


def test_rule_matches_sender_domain_and_subject(open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant)
    rule = _make_rule(db, tenant, task, sender_domains=["oceanstar.com"], subject_regex="noon report")
    db.commit()

    hit = _make_email(db, tenant, subject="Noon report — Ocean Star")
    miss_subject = _make_email(db, tenant, subject="Bunker offer")
    miss_sender = _make_email(db, tenant, subject="Noon report", sender="ops@other.com")
    db.commit()

    assert rule_matches(rule, hit) is True
    assert rule_matches(rule, miss_subject) is False
    assert rule_matches(rule, miss_sender) is False


def test_empty_rule_never_matches(open_db):
    """空规则 = 全匹配，会把整个收件箱变成草稿 —— 必须不命中。"""
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant)
    rule = _make_rule(db, tenant, task, folder="*", direction="*")
    db.commit()
    msg = _make_email(db, tenant)
    db.commit()
    assert rule_matches(rule, msg) is False


def test_rule_conditions_are_and(open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant)
    rule = _make_rule(db, tenant, task, sender_domains=["oceanstar.com"], body_markers=["ROB FO"])
    db.commit()
    ok = _make_email(db, tenant, body=NOON_BODY)
    no_marker = _make_email(db, tenant, body="Lat: 1.0")
    db.commit()
    assert rule_matches(rule, ok) is True
    assert rule_matches(rule, no_marker) is False


# ── 2. 幂等 ───────────────────────────────────────────────────────────────


def test_same_message_produces_one_draft(open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant)
    _make_rule(db, tenant, task, subject_regex="noon report")
    msg = _make_email(db, tenant, body=NOON_BODY)
    db.commit()

    first = process_message(db, tenant_id=tenant.id, task=task, message=msg)
    assert first is not None
    second = process_message(db, tenant_id=tenant.id, task=task, message=msg)
    assert second is None  # 幂等：不再产生第二份

    rows = db.scalars(select(DraftRecord).where(DraftRecord.tenant_id == tenant.id)).all()
    assert len(rows) == 1
    assert rows[0].status == "pending"


def test_dedupe_key_is_scoped_by_task(open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    t1 = _make_task(db, tenant, code="t_a")
    t2 = _make_task(db, tenant, code="t_b")
    db.commit()
    k1 = build_dedupe_key(t1, message_id="<m1>")
    k2 = build_dedupe_key(t2, message_id="<m1>")
    assert k1 != k2
    assert k1.startswith("t_a:")


def test_candidate_scan_ignores_outbound_and_old_mail(open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant)
    _make_email(db, tenant, direction="outbound")
    _make_email(db, tenant, days_ago=30)
    recent = _make_email(db, tenant)
    db.commit()
    rows = candidate_messages(db, tenant.id, task, window_days=7)
    assert [m.id for m in rows] == [recent.id]


# ── 3. 证据：无出处不落字段 ───────────────────────────────────────────────


def test_field_without_evidence_is_dropped(open_db):
    """规则腿塞进来的字段如果原文没有出处 → 丢弃 + warning。"""
    db = open_db()
    tenant = _demo_tenant(db)
    skill = db.scalar(
        select(SkillTemplate).where(SkillTemplate.code == "noon_report", SkillTemplate.tenant_id.is_(None))
    )
    assert skill is not None
    result = run_skill(
        skill=skill,
        subject="Noon report",
        body=NOON_BODY,
        db=db,
        tenant_id=tenant.id,
        rule_fields={"speed": 99.9},  # 原文没有 99.9
    )
    assert "speed" not in result.payload
    assert "speed" in _dropped(result.warnings)
    assert "lat" in result.payload  # 有出处的字段保留
    # 正文里写着的数值字段必须拿到证据（320 与 320.0 视为同一个数）
    assert "rob_fo" in result.payload
    assert "rob_do" in result.payload


def test_rule_fallback_is_visible(open_db):
    """LLM 不可用时走规则腿 —— 降级必须明示（rule_fallback）。"""
    db = open_db()
    tenant = _demo_tenant(db)
    skill = db.scalar(
        select(SkillTemplate).where(SkillTemplate.code == "noon_report", SkillTemplate.tenant_id.is_(None))
    )
    result = run_skill(skill=skill, subject="Noon report", body=NOON_BODY, db=db, tenant_id=tenant.id)
    assert result.source == "rules"
    assert "rule_fallback" in result.warnings
    assert result.error is None


def test_missing_required_field_is_reported(open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    skill = db.scalar(
        select(SkillTemplate).where(SkillTemplate.code == "noon_report", SkillTemplate.tenant_id.is_(None))
    )
    result = run_skill(skill=skill, subject="hello", body="nothing useful here", db=db, tenant_id=tenant.id)
    assert any(e.startswith("missing_required:report_at") for e in result.errors)


# ── 4. 失败显性 ───────────────────────────────────────────────────────────


def test_missing_skill_yields_failed_draft(open_db):
    """技能模板找不到 → 落 failed 草稿并写明原因（不静默）。"""
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant, skill_code="nope_skill")
    _make_rule(db, tenant, task, subject_regex="noon")
    msg = _make_email(db, tenant, body=NOON_BODY)
    db.commit()

    draft = process_message(db, tenant_id=tenant.id, task=task, message=msg)
    assert draft is not None
    assert draft.status == "failed"
    assert "skill_not_found" in (draft.error or "")


def test_empty_extraction_yields_failed_draft(open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant)
    _make_rule(db, tenant, task, subject_regex="noon")
    msg = _make_email(db, tenant, body="nothing to extract")
    db.commit()
    draft = process_message(db, tenant_id=tenant.id, task=task, message=msg)
    assert draft is not None
    assert draft.status == "failed"
    assert draft.error


# ── 5. API：任务 / 触发规则 / 草稿 ────────────────────────────────────────


def test_task_crud_and_trigger_guard(client, auth_headers):
    r = client.post(
        "/api/v1/routine/tasks",
        headers=auth_headers,
        json={
            "code": "api_noon",
            "name": "Noon intake",
            "module_code": "operations",
            "skill_code": "noon_report",
            "output_target": "noon_report",
            "owner_role": "operations",
        },
    )
    assert r.status_code == 201, r.text
    task_id = r.json()["id"]

    # 空触发规则必须被拒（否则等于匹配整个收件箱）
    r = client.put(
        f"/api/v1/routine/tasks/{task_id}/triggers",
        headers=auth_headers,
        json={"rules": [{"subject_regex": None, "body_markers": [], "sender_emails": [], "sender_domains": []}]},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "EMPTY_TRIGGER_RULE"

    r = client.put(
        f"/api/v1/routine/tasks/{task_id}/triggers",
        headers=auth_headers,
        json={"rules": [{"subject_regex": "noon report", "body_markers": [], "sender_emails": [], "sender_domains": []}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1

    r = client.delete(f"/api/v1/routine/tasks/{task_id}", headers=auth_headers)
    assert r.status_code == 200, r.text


def test_task_code_conflict_and_unknown_skill(client, auth_headers):
    r = client.post(
        "/api/v1/routine/tasks",
        headers=auth_headers,
        json={
            "code": "dup_task",
            "name": "A",
            "module_code": "operations",
            "skill_code": "noon_report",
        },
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/api/v1/routine/tasks",
        headers=auth_headers,
        json={
            "code": "dup_task",
            "name": "B",
            "module_code": "operations",
            "skill_code": "noon_report",
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "TASK_CODE_TAKEN"

    r = client.post(
        "/api/v1/routine/tasks",
        headers=auth_headers,
        json={"code": "x", "name": "X", "module_code": "operations", "skill_code": "does_not_exist"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "SKILL_NOT_FOUND"


def test_skill_validation_can_only_be_tightened(client, auth_headers, open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    r = client.post(
        "/api/v1/routine/skills",
        headers=auth_headers,
        json={
            "code": "acme.noon_report",
            "name": "Acme noon",
            "output_schema": {"kind": "noon_report", "required": ["report_at"]},
            "validator_rules": {"ranges": {"lat": [-90, 90]}},
        },
    )
    assert r.status_code == 201, r.text

    # 放松校验（去掉 required）→ 拒绝
    r = client.patch(
        "/api/v1/routine/skills/acme.noon_report",
        headers=auth_headers,
        json={"output_schema": {"kind": "noon_report", "required": []}},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "SKILL_VALIDATION_LOOSENED"

    # 改抽取类型 → 拒绝
    r = client.patch(
        "/api/v1/routine/skills/acme.noon_report",
        headers=auth_headers,
        json={"output_schema": {"kind": "nor", "required": ["report_at"]}},
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "SKILL_KIND_IMMUTABLE"

    # 平台模板不可改
    r = client.patch(
        "/api/v1/routine/skills/noon_report",
        headers=auth_headers,
        json={"name": "hijack"},
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "PLATFORM_SKILL_IMMUTABLE"


def test_draft_list_is_role_scoped(client, auth_headers, open_db):
    """草稿是角色信箱 —— 非负责角色看不到。"""
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant, owner_role="operations")
    _make_rule(db, tenant, task, subject_regex="noon report")
    msg = _make_email(db, tenant, body=NOON_BODY)
    db.commit()
    process_message(db, tenant_id=tenant.id, task=task, message=msg)
    db.commit()

    ops = _login(client, "ops@demo.marios")
    r = client.get("/api/v1/routine/drafts", headers=ops)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1

    finance = _login(client, "finance@demo.marios")
    r = client.get("/api/v1/routine/drafts", headers=finance)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0

    draft_id = client.get("/api/v1/routine/drafts", headers=ops).json()["items"][0]["id"]
    r = client.get(f"/api/v1/routine/drafts/{draft_id}", headers=finance)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "ROLE_REQUIRED"


def test_draft_not_found_for_other_tenant(client, auth_headers, open_db):
    """跨租户访问 → 404（不泄露存在性）。"""
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant)
    _make_rule(db, tenant, task, subject_regex="noon report")
    msg = _make_email(db, tenant, body=NOON_BODY)
    db.commit()
    draft = process_message(db, tenant_id=tenant.id, task=task, message=msg)
    db.commit()

    other = Tenant(
        name="Other Co", code="other", status="active", default_locale="en", default_timezone="UTC"
    )
    db.add(other)
    db.flush()
    user = User(
        tenant_id=other.id,
        email="admin@other.marios",
        full_name="Other Admin",
        password_hash=hash_password("Demo1234!"),
        status="active",
        locale="en",
        timezone="UTC",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    from app.models import Role, UserRole

    role = Role(tenant_id=other.id, code="tenant_admin", name="Tenant Admin", permissions={})
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()

    other_headers = _login(client, "admin@other.marios", tenant_code="other")
    r = client.get(f"/api/v1/routine/drafts/{draft.id}", headers=other_headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "DRAFT_NOT_FOUND"


def test_self_approval_blocked_and_field_subset(client, auth_headers, open_db):
    """创建人不能自己确认；别人确认时字段子集生效。"""
    db = open_db()
    tenant = _demo_tenant(db)

    # 午报要挂在航次上 —— 先建一条航次（用 demo 已有的船）
    vessels = client.get("/api/v1/masterdata/vessels", headers=auth_headers).json()
    items = vessels.get("items", vessels) if isinstance(vessels, dict) else vessels
    vessel_id = items[0]["id"]
    vessel_name = items[0].get("name") or "MV DEMO WAVE"
    r = client.post(
        "/api/v1/voyages",
        headers=auth_headers,
        json={"voyage_no": "RW-001", "vessel_id": vessel_id},
    )
    assert r.status_code in (200, 201), r.text
    voyage_id = uuid.UUID(r.json()["id"])

    body = NOON_BODY.replace("Ocean Star", vessel_name)
    task = _make_task(db, tenant, owner_role="operations")
    _make_rule(db, tenant, task, subject_regex="noon report")
    msg = _make_email(db, tenant, body=body, subject=f"Noon report — {vessel_name}")
    db.commit()

    # 管理员手动跑任务 → 草稿 created_by = 管理员
    r = client.post(f"/api/v1/routine/tasks/{task.id}/run", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    draft_id = r.json()["drafts"][0]["id"]

    r = client.post(f"/api/v1/routine/drafts/{draft_id}/confirm", headers=auth_headers, json={})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "SELF_APPROVAL_BLOCKED"

    # 闸门要在列表/详情里就说清楚 —— 不让用户点了「采纳」才吃 409
    r = client.get("/api/v1/routine/drafts", headers=auth_headers)
    row = next(d for d in r.json()["items"] if d["id"] == draft_id)
    assert row["can_confirm"] is False
    assert "four-eyes" in (row["blocked_reason"] or "")
    r = client.get(f"/api/v1/routine/drafts/{draft_id}", headers=auth_headers)
    assert r.json()["can_confirm"] is False

    # ops（另一个角色）确认，只认 report_at + lat 两个字段
    ops = _login(client, "ops@demo.marios")
    r = client.get(f"/api/v1/routine/drafts/{draft_id}", headers=ops)
    assert r.json()["can_confirm"] is True
    r = client.post(
        f"/api/v1/routine/drafts/{draft_id}/confirm",
        headers=ops,
        json={"confirmed": ["report_at", "lat"], "comment": "checked against the email"},
    )
    assert r.status_code == 200, r.text
    body_out = r.json()
    assert body_out["draft"]["status"] == "applied"
    assert body_out["target_id"]

    from app.models_domain import NoonReport

    rows = db.scalars(
        select(NoonReport).where(
            NoonReport.tenant_id == tenant.id, NoonReport.voyage_id == voyage_id
        )
    ).all()
    assert len(rows) == 1
    noon = rows[0]
    assert noon.lat is not None
    assert noon.speed is None  # 未确认 → 不落库
    assert noon.rob_fo is None


def test_confirm_revalidates_missing_required(client, auth_headers, open_db):
    """服务端复验 —— 必填字段缺失 → 422，不落库。"""
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant, owner_role="operations")
    _make_rule(db, tenant, task, subject_regex="noon report")
    msg = _make_email(db, tenant, body=NOON_BODY)
    db.commit()
    draft = process_message(db, tenant_id=tenant.id, task=task, message=msg)
    db.commit()
    # 人为去掉必填字段
    draft.payload = {"lat": 12.5}
    db.commit()

    ops = _login(client, "ops@demo.marios")
    r = client.post(f"/api/v1/routine/drafts/{draft.id}/confirm", headers=ops, json={})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "VALIDATION_FAILED"


def test_reject_requires_reason(client, auth_headers, open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant, owner_role="operations")
    _make_rule(db, tenant, task, subject_regex="noon report")
    msg = _make_email(db, tenant, body=NOON_BODY)
    db.commit()
    draft = process_message(db, tenant_id=tenant.id, task=task, message=msg)
    db.commit()

    ops = _login(client, "ops@demo.marios")
    r = client.post(f"/api/v1/routine/drafts/{draft.id}/reject", headers=ops, json={"reason": ""})
    assert r.status_code == 422, r.text

    r = client.post(f"/api/v1/routine/drafts/{draft.id}/reject", headers=ops, json={"reason": "wrong vessel"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


def test_run_task_creates_drafts_for_matching_mail_only(client, auth_headers, open_db):
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant, owner_role="operations")
    _make_rule(db, tenant, task, subject_regex="noon report")
    _make_email(db, tenant, subject="Bunker offer", body="Bunker offer ...")
    _make_email(db, tenant, body=NOON_BODY)
    db.commit()

    drafts = run_task(db, tenant_id=tenant.id, task=task)
    assert len(drafts) == 1


# ── W10：草稿携带来源邮件（前端收件箱要显示发件人/主题/原文）──────────────


def test_draft_list_carries_source_email_brief(client, open_db):
    """列表里能直接看到来源邮件的发件人与主题（前端不必再发 N+1 请求）。"""
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant, owner_role="operations")
    _make_rule(db, tenant, task, subject_regex="noon report")
    msg = _make_email(
        db,
        tenant,
        subject="Noon report — Ocean Star",
        body=NOON_BODY,
        sender="master@oceanstar.com",
    )
    db.commit()
    process_message(db, tenant_id=tenant.id, task=task, message=msg)
    db.commit()

    ops = _login(client, "ops@demo.marios")
    r = client.get("/api/v1/routine/drafts", headers=ops)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "expected one draft"
    src = items[0]["source_email"]
    assert src is not None
    assert src["subject"] == "Noon report — Ocean Star"
    assert src["from_email"] == "master@oceanstar.com"
    assert src["id"] == str(msg.id)


def test_draft_detail_carries_source_excerpt(client, open_db):
    """详情带原文摘录 —— 人工核对证据时不必去邮件页翻。"""
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant, owner_role="operations")
    _make_rule(db, tenant, task, subject_regex="noon report")
    msg = _make_email(db, tenant, body=NOON_BODY)
    db.commit()
    draft = process_message(db, tenant_id=tenant.id, task=task, message=msg)
    db.commit()

    ops = _login(client, "ops@demo.marios")
    r = client.get(f"/api/v1/routine/drafts/{draft.id}", headers=ops)
    assert r.status_code == 200, r.text
    src = r.json()["source_email"]
    assert src is not None
    assert "NOON REPORT" in src["body_excerpt"]
    assert src["body_truncated"] is False


def test_draft_source_email_is_tenant_scoped(client, open_db):
    """别人的邮件不能借草稿接口读到（跨租户一律 404）。"""
    db = open_db()
    tenant = _demo_tenant(db)
    task = _make_task(db, tenant, owner_role="operations")
    _make_rule(db, tenant, task, subject_regex="noon report")
    msg = _make_email(db, tenant, body=NOON_BODY)
    db.commit()
    draft = process_message(db, tenant_id=tenant.id, task=task, message=msg)
    db.commit()

    other = Tenant(
        name="Other Co", code="other2", status="active", default_locale="en", default_timezone="UTC"
    )
    db.add(other)
    db.flush()
    user = User(
        tenant_id=other.id,
        email="admin@other2.marios",
        full_name="Other Admin",
        password_hash=hash_password("Demo1234!"),
        status="active",
        locale="en",
        timezone="UTC",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    from app.models import Role, UserRole

    role = Role(tenant_id=other.id, code="tenant_admin", name="Tenant Admin", permissions={})
    db.add(role)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()

    other_headers = _login(client, "admin@other2.marios", tenant_code="other2")
    r = client.get(f"/api/v1/routine/drafts/{draft.id}", headers=other_headers)
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "DRAFT_NOT_FOUND"


# ── W10：导航挂出 /routine（角色可见性 + 路径 ACL + 搜索一致）──────────────


def test_routine_nav_visible_and_searchable(client):
    """例行任务中枢在导航里挂出，角色可见性与路径 ACL 一致。"""
    ops_headers = _login(client, "ops@demo.marios")
    boot = client.get("/api/v1/shell/bootstrap", headers=ops_headers).json()
    hrefs = {
        i["href"] for sec in boot["navigation"] for i in sec["items"] if not i.get("locked")
    }
    assert "/routine" in hrefs
    assert "/routine" in boot.get("allowed_paths", [])

    hits = client.get("/api/v1/search", params={"q": "routine"}, headers=ops_headers).json()
    assert any((h.get("href") or "") == "/routine" for h in hits)


def test_routine_nav_locked_for_unrelated_role():
    """角色不在白名单 → 入口置灰（菜单锁定 = 路径拒绝，B1 一致性）。"""
    from app.services.shell_nav import build_navigation

    def item_for(roles: list[str]) -> dict:
        for sec in build_navigation(roles):
            for item in sec["items"]:
                if item["href"] == "/routine":
                    return item
        raise AssertionError(f"/routine missing from nav for roles={roles}")

    assert item_for(["operations"]).get("locked") is None
    assert item_for(["chartering"]).get("locked") is None
    assert item_for(["viewer"]).get("locked") is True
    assert item_for(["risk"]).get("locked") is True
    assert item_for(["tenant_admin"]).get("locked") is None


# ── W11 试点闭环：入站邮件 → 待确认草稿 → 人工确认 → 业务表 ────────────────


def _pilot_drafts(db, tenant) -> dict[str, DraftRecord]:
    """跑三条试点例行任务，返回 ``{任务 code: 草稿}``（demo 三封试点邮件 → 三份草稿）。"""
    from app.seed_routine import seed_routine_pilot_emails

    seed_routine_pilot_emails(db, tenant.id)
    db.commit()
    out: dict[str, DraftRecord] = {}
    tasks = db.scalars(
        select(RoutineTask).where(
            RoutineTask.tenant_id == tenant.id, RoutineTask.enabled.is_(True)
        )
    ).all()
    for task in tasks:
        for draft in run_task(db, tenant_id=tenant.id, task=task):
            out[task.code] = draft
    db.commit()
    return out


def _counts(db, tenant_id) -> dict[str, int]:
    from app.models_domain import Charter, Estimate, LaytimeCalc, NoonReport

    def n(model) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.tenant_id == tenant_id)) or 0

    return {
        "noon": n(NoonReport),
        "laytime": n(LaytimeCalc),
        "estimate": n(Estimate),
        "charter": n(Charter),
    }


def test_pilot_chain_email_to_business_rows(client, auth_headers, open_db):
    """试点闭环：一封入站邮件 → 待确认草稿 → 人工确认 → 业务表真的多了一行。

    三条腿各落一处 —— 午报 → noon_reports；SOF → laytime_calcs；
    recap → estimates + charters（租约草稿带 laycan 窗口）。
    """
    from app.models_domain import Charter, Estimate, LaytimeCalc, NoonReport, Voyage

    db = open_db()
    tenant = _demo_tenant(db)
    drafts = _pilot_drafts(db, tenant)
    assert set(drafts) == {
        "noon_report_intake",
        "laytime_statement_intake",
        "fixture_recap_intake",
    }
    for code, draft in drafts.items():
        assert draft.status == "pending", (code, draft.error)
        assert draft.payload, (code, "没有抽出任何字段")
        assert draft.evidence, (code, "字段没有证据")

    before = _counts(db, tenant.id)

    # 人工确认（租户管理员）—— 草稿由系统生成，四眼规则不拦
    for code, draft in drafts.items():
        r = client.post(
            f"/api/v1/routine/drafts/{draft.id}/confirm",
            headers=auth_headers,
            json={"payload": {}, "confirmed": None, "comment": "pilot confirm"},
        )
        assert r.status_code == 200, (code, r.text)
        assert r.json()["draft"]["status"] == "applied"

    db2 = open_db()
    after = _counts(db2, tenant.id)
    assert after == {k: before[k] + 1 for k in before}, (before, after)

    # ① 午报 → 落在进行中的航次上（VOY-2407 / MV PACIFIC STAR）
    voyage = db2.scalars(
        select(Voyage).where(Voyage.tenant_id == tenant.id, Voyage.voyage_no == "VOY-2407")
    ).one()
    noon = db2.scalars(
        select(NoonReport).where(
            NoonReport.tenant_id == tenant.id,
            NoonReport.voyage_id == voyage.id,
            NoonReport.lat == 51.9,
        )
    ).one()
    assert float(noon.lat) == 51.9
    assert float(noon.lon) == 4.4
    assert float(noon.speed) == 11.9
    assert float(noon.rob_fo) == 1520
    assert float(noon.rob_do) == 980
    assert noon.eta_next is not None

    # ② SOF → 装卸时间计算草稿，挂到 MV DEMO WAVE 的航次上
    laytime_voyage = db2.scalars(
        select(Voyage).where(Voyage.tenant_id == tenant.id, Voyage.voyage_no == "VOY-2408")
    ).one()
    calc = db2.scalars(
        select(LaytimeCalc).where(
            LaytimeCalc.tenant_id == tenant.id,
            LaytimeCalc.voyage_id == laytime_voyage.id,
        )
    ).one()
    assert len(calc.inputs["sof_events"]) == 4
    assert float(calc.inputs["allowed_days"]) == 3.5

    # ③ recap → 估算草稿 + 租约草稿（船名/对手方都匹配上了，laycan 窗口不丢）
    est = db2.scalars(
        select(Estimate).where(
            Estimate.tenant_id == tenant.id,
            Estimate.title.like("Recap draft:%"),
        )
    ).one()
    assert est.status == "draft"
    assert float(est.inputs["freight_rate"]) == 18.5
    assert est.inputs["cargo"] == "Coal"
    assert est.inputs["load_port"] == "SGSIN"
    assert est.inputs["discharge_port"] == "NLRTM"
    assert est.vessel_id is not None, "船名应匹配到 demo 船舶"
    assert est.counterparty_id is not None, "对手方应匹配到 demo 对手方"

    charter = db2.scalars(
        select(Charter).where(Charter.tenant_id == tenant.id, Charter.estimate_id == est.id)
    ).one()
    assert charter.status == "draft"
    assert charter.laycan_from is not None, "laycan 窗口不该被 split('-') 弄丢"
    assert charter.laycan_to is not None
    assert charter.laycan_to > charter.laycan_from
    assert float(charter.freight_rate) == 18.5
    assert float(charter.commission_pct) == 1.5


def test_evidence_labels_rule_fallback_fields_as_rules(open_db, monkeypatch):
    """逐字段标抽取腿 —— 规则兜底的字段不能挂「llm」标签。

    走查发现：LLM 腿返回结构合法但没抽到东西时，规则腿兜底的字段被整体标成
    llm，复核人会误以为这些值是模型抽的。
    """
    from app.services import llm_extract
    from app.services.skill_runtime import run_skill

    skill = SkillTemplate(
        tenant_id=None,
        code="noon_report",
        name="Noon",
        purpose="pilot",
        prompt_template="",
        output_schema={"kind": "noon_report", "required": ["report_at"], "fields": {}},
        validator_rules={},
        version=1,
        enabled=True,
    )
    # LLM 腿只贡献一个字段，其余走规则兜底
    monkeypatch.setattr(
        llm_extract,
        "extract_fields",
        lambda kind, subject, body, rule_fields=None, **kw: {
            "lat": 12.5,
            "_source": "llm",
            "_rule_diffs": [],
        },
    )
    body = NOON_BODY
    res = run_skill(skill=skill, subject="Noon report", body=body, db=None, tenant_id=None)
    by_field = {e["field"]: e["extracted_by"] for e in res.evidence}
    assert by_field["lat"] == "llm"
    assert by_field["report_at"] == "rules"
    assert by_field["rob_fo"] == "rules"
    # LLM 腿有贡献 → 整体不算降级，但每个字段的标签必须真实
    assert res.source == "llm"
    assert "rule_fallback" not in res.warnings


def test_evidence_marks_all_rules_when_llm_returns_nothing(open_db, monkeypatch):
    """LLM 腿完全没出东西 → 全部标 rules，并带 rule_fallback 告警。"""
    from app.services import llm_extract
    from app.services.skill_runtime import run_skill

    skill = SkillTemplate(
        tenant_id=None,
        code="noon_report",
        name="Noon",
        purpose="pilot",
        prompt_template="",
        output_schema={"kind": "noon_report", "required": ["report_at"], "fields": {}},
        validator_rules={},
        version=1,
        enabled=True,
    )
    monkeypatch.setattr(
        llm_extract,
        "extract_fields",
        lambda kind, subject, body, rule_fields=None, **kw: {
            "_source": "llm",
            "_rule_diffs": [],
        },
    )
    res = run_skill(skill=skill, subject="Noon report", body=NOON_BODY, db=None, tenant_id=None)
    assert res.source == "rules"
    assert "rule_fallback" in res.warnings
    assert all(e["extracted_by"] == "rules" for e in res.evidence)


def test_llm_empty_value_does_not_override_rule_result(open_db, monkeypatch):
    """LLM 腿返回空容器（[]/""）时不算「抽到值」—— 不能顶掉规则腿的结果。

    试点走查踩到：模型把「没找到」表达成 ``events: []``，把规则腿抽到的 4 条
    SOF 事件顶掉了 → 装卸时间草稿成了空壳（还看不出哪里错）。
    """
    from app.services import llm_extract
    from app.services.skill_runtime import run_skill

    skill = SkillTemplate(
        tenant_id=None,
        code="laytime_statement",
        name="SOF",
        purpose="pilot",
        prompt_template="",
        output_schema={"kind": "laytime_statement", "required": ["events"], "fields": {}},
        validator_rules={},
        version=1,
        enabled=True,
    )
    monkeypatch.setattr(
        llm_extract,
        "extract_fields",
        lambda kind, subject, body, rule_fields=None, **kw: {
            "events": [],
            "_source": "llm",
            "_rule_diffs": [],
        },
    )
    body = (
        "Statement of Facts - MV DEMO WAVE\n"
        "12-10 08:00 Vessel alongside berth 4\n"
        "12-10 12:00 Commencement of laytime\n"
        "12-12 10:30 Notice of readiness tendered\n"
        "12-14 16:00 Laytime terminated\n"
        "Total: 3.5 days\n"
    )
    res = run_skill(skill=skill, subject="Statement of Facts", body=body, db=None, tenant_id=None)
    assert len(res.payload.get("events") or []) == 4, res.payload
    assert res.payload["allowed_days"] == 3.5
    # LLM 一个有效字段都没贡献 → 整体按规则腿算，并明示降级
    assert res.source == "rules"
    assert "rule_fallback" in res.warnings
    assert res.errors == []


# ── 试点走查发现的两个缺陷（回归）────────────────────────────────────────

#: 数值字段的出处必须指向**真正写着这个数**的那一行
NOON_BODY_NUMERIC = (
    "NOON REPORT\n"
    "Vessel: MV PACIFIC STAR\n"
    "Voyage: VOY-2408\n"
    "Report at: 2026-10-30 04:00\n"
    "Lat: 51.9\n"
    "Lon: 4.4\n"
    "Speed: 11.9\n"
    "ROB FO: 1520\n"
    "ROB DO: 980\n"
    "Wind BF: 4\n"
    "Current: 0.6\n"
)


def test_evidence_line_must_be_the_line_that_holds_the_number(open_db):
    """出处行指错，等于「无证据不落库」被绕过。

    走查踩到：wind_bf=4 的出处指向 "Report at: ... 04:00"（子串命中 04），
    event_count=4 的出处指向 "Voyage: VOY-2408"（子串命中 2408）。
    数值字段必须按「独立出现的数字」匹配。
    """
    db = open_db()
    tenant = _demo_tenant(db)
    skill = db.scalar(
        select(SkillTemplate).where(SkillTemplate.code == "noon_report", SkillTemplate.tenant_id.is_(None))
    )
    assert skill is not None
    result = run_skill(
        skill=skill,
        subject="Noon report",
        body=NOON_BODY_NUMERIC,
        db=db,
        tenant_id=tenant.id,
    )
    quote = {e["field"]: e.get("quote") or "" for e in result.evidence}
    assert quote.get("wind_bf", "").startswith("Wind BF: 4"), quote
    assert "04:00" not in quote.get("wind_bf", "")
    assert quote.get("current_kn", "").startswith("Current: 0.6"), quote
    assert quote.get("lat", "").startswith("Lat: 51.9"), quote
    assert quote.get("lon", "").startswith("Lon: 4.4"), quote
    assert quote.get("rob_fo", "").startswith("ROB FO: 1520"), quote
    assert quote.get("rob_do", "").startswith("ROB DO: 980"), quote


def test_evidence_line_for_event_count_is_not_the_voyage_number(open_db):
    """事件条数的出处不能落在航次号上（"4" 是 "2408" 的子串）。"""
    db = open_db()
    tenant = _demo_tenant(db)
    skill = db.scalar(
        select(SkillTemplate).where(
            SkillTemplate.code == "laytime_statement", SkillTemplate.tenant_id.is_(None)
        )
    )
    assert skill is not None
    body = (
        "Statement of Facts - MV DEMO WAVE\n"
        "Voyage: VOY-2408\n"
        "12-10 08:00 Vessel alongside berth 4\n"
        "12-10 12:00 Commencement of laytime\n"
        "12-12 10:30 Notice of readiness tendered\n"
        "12-14 16:00 Laytime terminated\n"
        "Total: 3.5 days\n"
    )
    result = run_skill(skill=skill, subject="Statement of Facts", body=body, db=db, tenant_id=tenant.id)
    quote = {e["field"]: e.get("quote") or "" for e in result.evidence}
    assert quote.get("event_count", "").startswith("12-10 08:00"), quote
    assert "VOY-2408" not in quote.get("event_count", "")


def test_recap_rule_leg_does_not_swallow_the_next_sentence(open_db):
    """单行 recap：字段值不能把下一句一起吞掉。

    "Vessel MV X IMO 9123456. Laycan 12-18 Sep. Freight USD 18.5 PMT." 一行里
    挤了三件事 —— 按行捕获会让 vessel 变成整行、laycan 变成 "12-18 Sep. Freight ..."。
    """
    from app.services.email_intelligence import parse_fixture_recap

    parsed = parse_fixture_recap(
        "Vessel MV OCEAN STAR IMO 9123456. Laycan 12-18 Sep. Freight USD 18.5 PMT."
    )
    assert parsed["vessel"] == "MV OCEAN STAR IMO 9123456", parsed
    assert parsed["laycan"] == "12-18 Sep", parsed
    assert parsed["freight_rate"] == 18.5, parsed
