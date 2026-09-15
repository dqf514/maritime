"""New-user onboarding checklist — role-aware, data-detected progress."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.models_domain import (
    Charter,
    Claim,
    DqIssue,
    Estimate,
    Invoice,
    LaytimeCalc,
    NoonReport,
    Payment,
    PortCall,
    Voyage,
)
from app.models_onboarding import OnboardingState
from app.models_ship import ShipCertificate, ShipTechnicalProfile
from app.models_task import Task
from app.models_wave1 import Attachment, Company, Counterparty, Notification, Vessel
from app.security import AuthContext, get_current_auth

router = APIRouter(tags=["Onboarding"])

MAX_ITEMS = 8


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _exists(db: Session, model, *conds) -> bool:
    return db.scalar(select(model.id).where(*conds).limit(1)) is not None


def _count_users(db: Session, auth: AuthContext) -> int:
    return db.scalar(
        select(func.count(User.id)).where(User.tenant_id == auth.tenant_id, User.status == "active")
    ) or 0


Check = Callable[[Session, AuthContext], bool]

CHECKS: dict[str, Check] = {
    "view_home": lambda db, auth: True,
    "has_notification": lambda db, auth: _exists(
        db, Notification, Notification.tenant_id == auth.tenant_id, Notification.user_id == auth.user_id
    ),
    "has_tasks": lambda db, auth: _exists(
        db,
        Task,
        Task.tenant_id == auth.tenant_id,
        or_(Task.assignee_user_id == auth.user_id, Task.created_by == auth.user_id),
    ),
    "company_profile_done": lambda db, auth: _exists(
        db, Company, Company.tenant_id == auth.tenant_id, Company.base_currency.is_not(None)
    ),
    "has_users": lambda db, auth: _count_users(db, auth) >= 2,
    "has_vessels": lambda db, auth: _exists(
        db, Vessel, Vessel.tenant_id == auth.tenant_id, Vessel.deleted_at.is_(None)
    ),
    "has_counterparties": lambda db, auth: _exists(
        db, Counterparty, Counterparty.tenant_id == auth.tenant_id, Counterparty.deleted_at.is_(None)
    ),
    "dq_scan_run": lambda db, auth: _exists(db, DqIssue, DqIssue.tenant_id == auth.tenant_id),
    "has_voyage": lambda db, auth: _exists(db, Voyage, Voyage.tenant_id == auth.tenant_id),
    "has_port_call": lambda db, auth: _exists(db, PortCall, PortCall.tenant_id == auth.tenant_id),
    "has_noon_report": lambda db, auth: _exists(db, NoonReport, NoonReport.tenant_id == auth.tenant_id),
    "has_laytime": lambda db, auth: _exists(db, LaytimeCalc, LaytimeCalc.tenant_id == auth.tenant_id),
    "has_claim": lambda db, auth: _exists(db, Claim, Claim.tenant_id == auth.tenant_id),
    "has_estimate": lambda db, auth: _exists(db, Estimate, Estimate.tenant_id == auth.tenant_id),
    "has_charter": lambda db, auth: _exists(db, Charter, Charter.tenant_id == auth.tenant_id),
    "has_invoice": lambda db, auth: _exists(db, Invoice, Invoice.tenant_id == auth.tenant_id),
    "has_payment": lambda db, auth: _exists(db, Payment, Payment.tenant_id == auth.tenant_id),
    "has_ship_profile": lambda db, auth: _exists(db, ShipTechnicalProfile, ShipTechnicalProfile.tenant_id == auth.tenant_id),
    "has_cert": lambda db, auth: _exists(db, ShipCertificate, ShipCertificate.tenant_id == auth.tenant_id),
    "has_cert_file": lambda db, auth: _exists(
        db, Attachment, Attachment.tenant_id == auth.tenant_id, Attachment.entity_type == "ship_certificate"
    ),
}

ITEM_DEFS: dict[str, dict] = {
    "view_home": {
        "label": {"en": "Open your workbench", "zh": "打开工作台"},
        "hint": {"en": "Your daily landing page with tasks, alerts and KPIs.", "zh": "每日落地页：任务、提醒与关键指标。"},
        "href": "/home",
    },
    "has_notification": {
        "label": {"en": "Check the notification bell", "zh": "查看通知铃铛"},
        "hint": {"en": "Notifications arrive when tasks are assigned or alerts fire.", "zh": "任务指派或告警触发时会收到通知。"},
        "href": "/home",
    },
    "has_tasks": {
        "label": {"en": "Create or receive a task", "zh": "创建或收到一条任务"},
        "hint": {"en": "Tasks track everything you must not forget.", "zh": "用任务跟踪所有怕漏掉的事。"},
        "href": "/tasks",
    },
    "company_profile_done": {
        "label": {"en": "Complete the company profile", "zh": "完善公司资料"},
        "hint": {"en": "Name and base currency drive invoicing and reports.", "zh": "公司名称与本位币驱动开票与报表。"},
        "href": "/admin/company",
    },
    "has_users": {
        "label": {"en": "Invite a second user", "zh": "邀请第二位用户"},
        "hint": {"en": "Invite colleagues and assign desk roles.", "zh": "邀请同事并分配岗位角色。"},
        "href": "/admin/organization",
    },
    "has_vessels": {
        "label": {"en": "Register your first vessel", "zh": "登记第一艘船"},
        "hint": {"en": "Vessel masterdata powers estimates and voyages.", "zh": "船舶主数据支撑估算与航次。"},
        "href": "/masterdata/vessels",
    },
    "has_counterparties": {
        "label": {"en": "Add your first counterparty", "zh": "添加第一个对手方"},
        "hint": {"en": "Charterers, owners, brokers — needed for fixtures and invoices.", "zh": "租家、船东、经纪人——成交与开票都需要。"},
        "href": "/masterdata/counterparties",
    },
    "dq_scan_run": {
        "label": {"en": "Run a data-quality scan", "zh": "跑一次数据质量扫描"},
        "hint": {"en": "The scan flags missing or inconsistent data early.", "zh": "扫描能及早发现缺失或不一致的数据。"},
        "href": "/exceptions",
    },
    "has_voyage": {
        "label": {"en": "Activate your first voyage", "zh": "激活第一个航次"},
        "hint": {"en": "Voyages start from an approved charter.", "zh": "航次从已批准的租约激活。"},
        "href": "/operations/voyages",
    },
    "has_port_call": {
        "label": {"en": "Add a port call", "zh": "添加一个挂靠港"},
        "hint": {"en": "Maintain ETA/ETD for every call on the voyage.", "zh": "为航次的每个挂靠港维护 ETA/ETD。"},
        "href": "/operations/voyages",
    },
    "has_noon_report": {
        "label": {"en": "Enter a noon report", "zh": "录入一份午报"},
        "hint": {"en": "Daily noon reports track speed and consumption.", "zh": "每日午报跟踪航速与油耗。"},
        "href": "/operations/voyages",
    },
    "has_laytime": {
        "label": {"en": "Start a laytime calculation", "zh": "创建一份滞期计算"},
        "hint": {"en": "Laytime turns SOF events into demurrage/despatch.", "zh": "滞期计算把 SOF 事件变成滞期/速遣。"},
        "href": "/operations/voyages",
    },
    "has_claim": {
        "label": {"en": "Register a claim", "zh": "登记一条索赔"},
        "hint": {"en": "Demurrage and other claims stay tracked to settlement.", "zh": "滞期等索赔全程跟踪到结案。"},
        "href": "/finance",
    },
    "has_estimate": {
        "label": {"en": "Run your first estimate", "zh": "完成第一次估算"},
        "hint": {"en": "Estimate TCE before committing to a cargo.", "zh": "揽货前先算 TCE。"},
        "href": "/estimates",
    },
    "has_charter": {
        "label": {"en": "Fix your first charter", "zh": "成交第一份租约"},
        "hint": {"en": "Convert a winning estimate into a charter.", "zh": "把胜出的估算转为租约。"},
        "href": "/charters",
    },
    "has_invoice": {
        "label": {"en": "Issue your first invoice", "zh": "开具第一张发票"},
        "hint": {"en": "Freight and demurrage invoices start the cash cycle.", "zh": "运费与滞期费发票开启现金循环。"},
        "href": "/finance",
    },
    "has_payment": {
        "label": {"en": "Register a payment", "zh": "登记一笔收款"},
        "hint": {"en": "Match payments against open invoices.", "zh": "收款要核销到未结发票。"},
        "href": "/finance",
    },
    "has_ship_profile": {
        "label": {"en": "Fill a technical profile", "zh": "完善船舶技术资料"},
        "hint": {"en": "Class society, drydock and survey dates per vessel.", "zh": "每船维护船级社、坞修与检验日期。"},
        "href": "/ship",
    },
    "has_cert": {
        "label": {"en": "Register a certificate", "zh": "登记一份证书"},
        "hint": {"en": "Statutory certificates with expiry dates.", "zh": "登记带到期日的法定证书。"},
        "href": "/ship",
    },
    "has_cert_file": {
        "label": {"en": "Upload a certificate file", "zh": "上传证书文件"},
        "hint": {"en": "Keep the latest scan attached to the certificate.", "zh": "把最新扫描件挂到证书上。"},
        "href": "/ship",
    },
}

ROLE_ITEMS: list[tuple[set[str], list[str]]] = [
    ({"tenant_admin", "management"}, ["company_profile_done", "has_users", "has_vessels", "has_counterparties", "dq_scan_run"]),
    ({"operations"}, ["has_voyage", "has_port_call", "has_noon_report", "has_laytime"]),
    ({"chartering"}, ["has_estimate", "has_charter"]),
    ({"finance"}, ["has_invoice", "has_payment"]),
    ({"demurrage"}, ["has_laytime", "has_claim"]),
    ({"technical"}, ["has_ship_profile", "has_cert", "has_cert_file"]),
    ({"viewer"}, ["has_tasks"]),
]

BASE_ITEMS = ["view_home", "has_notification"]


def _checklist_keys(roles: list[str]) -> list[str]:
    keys = list(BASE_ITEMS)
    role_set = set(roles)
    matched = False
    for group_roles, items in ROLE_ITEMS:
        if role_set & group_roles:
            matched = True
            for key in items:
                if key not in keys:
                    keys.append(key)
    if not matched and "has_tasks" not in keys:
        keys.append("has_tasks")
    return keys[:MAX_ITEMS]


@router.get("/onboarding")
def get_onboarding(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    keys = _checklist_keys(auth.roles)
    items = []
    done_count = 0
    for key in keys:
        done = bool(CHECKS[key](db, auth))
        done_count += 1 if done else 0
        items.append({"key": key, "done": done, **ITEM_DEFS[key]})
    state = db.get(OnboardingState, auth.user_id)
    dismissed = bool(state and state.dismissed_at)
    return {
        "items": items,
        "progress": {"done": done_count, "total": len(items)},
        "dismissed": dismissed,
    }


@router.post("/onboarding/dismiss")
def dismiss_onboarding(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    state = db.get(OnboardingState, auth.user_id)
    if state is None:
        state = OnboardingState(user_id=auth.user_id, tenant_id=auth.tenant_id)
        db.add(state)
    state.dismissed_at = _now()
    db.commit()
    return {"dismissed": True}


@router.post("/onboarding/reset")
def reset_onboarding(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    state = db.get(OnboardingState, auth.user_id)
    if state is not None:
        state.dismissed_at = None
        db.commit()
    return {"dismissed": False}
