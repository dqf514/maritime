"""Role-aware workbench aggregation — one call for the ERP home page."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.models_domain import Charter, Claim, Estimate, Invoice, LaytimeCalc, PortCall, PortDisbursement, Voyage
from app.models_ship import ShipCertificate, ShipCrewMember, ShipDefect, ShipWorkOrder
from app.models_task import Task
from app.models_wave1 import Notification, Port, Vessel
from app.routers.saas import workflow_inbox
from app.routers.ship_mgmt import _refresh_certificate_status
from app.routers.tasks import task_out
from app.security import AuthContext, get_current_auth
from app.services.notifications import notify_once, role_recipients

log = logging.getLogger("marios.home")

router = APIRouter(tags=["Home"])

ALERT_NOTIFY_ROLES = ("technical", "management", "tenant_admin")

# ── Activity feed (operation log) — role-scoped, click-through ──
# Supervisors (management/tenant_admin/platform_admin) see every module's log.
# Everyone sees their own actions + others' actions for modules their roles cover.

_SUPERVISOR_ROLES = frozenset({"management", "tenant_admin", "platform_admin"})

_ALL_MODULES = frozenset(
    {"operations", "finance", "chartering", "commercial", "bunker", "masterdata", "ship", "tasks", "platform", "analytics"}
)

# entity_type -> module (for permission scoping + nav grouping)
_ENTITY_MODULE: dict[str, str] = {
    "voyage": "operations", "port_call": "operations", "sof_event": "operations",
    "noon_report": "operations", "off_hire_event": "operations", "port_disbursement": "operations",
    "invoice": "finance", "claim": "finance", "laytime": "finance", "laytime_statement": "finance",
    "pda": "finance", "journal": "finance", "accrual": "finance", "payment": "finance",
    "charter": "chartering", "tc_contract": "chartering", "time_charter": "chartering",
    "time_charter_contract": "chartering", "charter_offer": "chartering", "cargo": "chartering",
    "coa_contract": "chartering", "coa_lifting": "chartering", "master_contract": "chartering",
    "clause_template": "chartering",
    "estimate": "commercial", "rate_table": "commercial", "pricing_template": "commercial",
    "bunker_order": "bunker", "bunker_requirement": "bunker", "bunker_option": "bunker",
    "vessel": "masterdata", "port": "masterdata", "counterparty": "masterdata",
    "cargo_name": "masterdata", "cargo_group": "masterdata", "port_berth": "masterdata",
    "port_alias": "masterdata", "port_distance": "masterdata", "company": "masterdata", "trade": "masterdata",
    "user": "platform", "tenant": "platform", "connector": "platform", "org_unit": "platform",
    "email_account": "platform", "webhook_endpoint": "platform", "platform": "platform",
    "task": "tasks",
    "ship_certificate": "ship", "ship_work_order": "ship", "ship_terminal": "ship",
    "ship_report": "ship", "work_order": "ship",
    "dq_issue": "analytics",
}

# role -> modules whose logs the role may view
_ROLE_MODULES: dict[str, frozenset[str]] = {
    "management": _ALL_MODULES, "tenant_admin": _ALL_MODULES, "platform_admin": _ALL_MODULES,
    "operations": frozenset({"operations", "ship", "masterdata", "bunker", "tasks"}),
    "chartering": frozenset({"chartering", "commercial", "masterdata", "tasks"}),
    "finance": frozenset({"finance", "tasks"}),
    "demurrage": frozenset({"finance", "tasks"}),
    "technical": frozenset({"operations", "ship", "masterdata", "tasks"}),
    "bunker": frozenset({"bunker", "operations", "masterdata", "tasks"}),
    "pool_manager": frozenset({"finance", "tasks"}),
    "risk": frozenset({"operations", "finance", "tasks"}),
    "viewer": frozenset({"tasks"}),
    "agent": frozenset({"tasks"}),
}

# entity_type -> frontend route template (click-through直达)
_ENTITY_HREF: dict[str, str] = {
    "voyage": "/operations/voyages/{id}/workspace",
    "invoice": "/finance/invoices/{id}",
    "charter": "/charters/{id}",
    "time_charter": "/charters/tc/{id}",
    "time_charter_contract": "/charters/tc/{id}",
    "tc_contract": "/charters/tc/{id}",
    "coa_contract": "/charters/coa/{id}",
    "estimate": "/estimates",
    "claim": "/finance/claims",
    "laytime_statement": "/finance/laytimes/{id}",
    "bunker_order": "/bunker",
    "cargo": "/cargo",
    "vessel": "/masterdata/vessels",
    "counterparty": "/masterdata/counterparties",
    "port": "/masterdata/ports",
    "task": "/tasks",
    "user": "/admin/users",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# 工作台「最近活动」里要过滤掉的噪声动作（安全审计页仍保留全量）。
_FEED_NOISE_ACTIONS = {"auth.login_success"}


def _tasks_section(db: Session, auth: AuthContext) -> dict:
    rows = db.scalars(
        select(Task).where(
            Task.tenant_id == auth.tenant_id,
            or_(Task.assignee_user_id == auth.user_id, Task.created_by == auth.user_id),
            Task.status.notin_(["done", "cancelled"]),
        )
    ).all()
    now = _now()
    today = date.today()
    open_rows = [t for t in rows if t.status != "done"]

    def _sort_key(t: Task):
        return (t.due_at is None, _aware(t.due_at) or now, t.created_at or now)

    open_rows.sort(key=_sort_key)
    return {
        "open": len(open_rows),
        "overdue": sum(1 for t in open_rows if _aware(t.due_at) and _aware(t.due_at) < now),
        "due_today": sum(1 for t in open_rows if _aware(t.due_at) and _aware(t.due_at).date() == today),
        "items": [task_out(db, t) for t in open_rows[:5]],
    }


def _notifications_section(db: Session, auth: AuthContext) -> dict:
    mine = or_(Notification.user_id == auth.user_id, Notification.user_id.is_(None))
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.tenant_id == auth.tenant_id, mine, Notification.read_at.is_(None))
    ) or 0
    rows = db.scalars(
        select(Notification)
        .where(Notification.tenant_id == auth.tenant_id, mine)
        .order_by(Notification.created_at.desc())
        .limit(5)
    ).all()
    return {
        "unread": unread,
        "items": [
            {
                "id": str(n.id),
                "title": n.title,
                "body": n.body,
                "level": n.level,
                "href": n.href,
                "read_at": n.read_at.isoformat() if n.read_at else None,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in rows
        ],
    }


def _approvals_section(db: Session, auth: AuthContext) -> dict:
    items = workflow_inbox(auth=auth, db=db)
    return {"count": len(items), "items": items[:5]}


def _alert_recipients(db: Session, tenant_id: UUID) -> list[User]:
    return role_recipients(db, tenant_id, ALERT_NOTIFY_ROLES)


def _ship_alerts(db: Session, auth: AuthContext) -> list[dict]:
    _refresh_certificate_status(db, auth.tenant_id)
    vessels = {v.id: v.name for v in db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id)).all()}
    today = date.today()
    alerts: list[dict] = []
    certs = db.scalars(
        select(ShipCertificate).where(
            ShipCertificate.tenant_id == auth.tenant_id,
            ShipCertificate.status.in_(["expiring", "expired"]),
        )
    ).all()
    recipients = _alert_recipients(db, auth.tenant_id)
    for c in certs:
        vessel_name = vessels.get(c.vessel_id) or ""
        due_in = (c.expires_on - today).days if c.expires_on else None
        expired = c.status == "expired"
        kind = "ship_cert_expired" if expired else "ship_cert_expiring"
        title = f"{'Certificate expired' if expired else 'Certificate expiring'}: {c.cert_name} ({vessel_name})".strip()
        title_zh = f"{'证书已过期' if expired else '证书即将到期'}：{c.cert_name}（{vessel_name}）".strip()
        alerts.append(
            {
                "kind": kind,
                "title": title,
                "title_i18n": {"en": title, "zh": title_zh},
                "detail": f"{c.cert_code} · {c.expires_on.isoformat() if c.expires_on else '—'} · {c.issuing_body or ''}".strip(),
                "href": "/ship",
                "severity": "critical" if expired else "warning",
                "due_in_days": due_in,
            }
        )
        notify_once(
            db,
            auth.tenant_id,
            recipients,
            title=title,
            body=f"{c.cert_code} expires {c.expires_on.isoformat() if c.expires_on else '—'}",
            href="/ship",
            level="critical" if expired else "warning",
        )
    horizon = today + timedelta(days=60)
    crew = db.scalars(select(ShipCrewMember).where(ShipCrewMember.tenant_id == auth.tenant_id)).all()
    for member in crew:
        for cert in (member.meta or {}).get("certificates") or []:
            raw = cert.get("expires_on")
            if not raw:
                continue
            try:
                expires_on = date.fromisoformat(str(raw))
            except ValueError:
                continue
            if expires_on > horizon:
                continue
            due_in = (expires_on - today).days
            expired = due_in < 0
            title = f"Crew certificate {'expired' if expired else 'expiring'}: {cert.get('code') or '—'} — {member.full_name}"
            title_zh = f"船员证书{'已过期' if expired else '即将到期'}：{cert.get('code') or '—'} — {member.full_name}"
            alerts.append(
                {
                    "kind": "crew_cert_expiring",
                    "title": title,
                    "title_i18n": {"en": title, "zh": title_zh},
                    "detail": f"{member.rank} · expires {expires_on.isoformat()}",
                    "href": "/ship",
                    "severity": "critical" if expired else "warning",
                    "due_in_days": due_in,
                }
            )
            notify_once(
                db,
                auth.tenant_id,
                recipients,
                title=title,
                body=f"{member.full_name} · {cert.get('code') or '—'} expires {expires_on.isoformat()}",
                href="/ship",
                level="critical" if expired else "warning",
            )
    db.commit()
    alerts.sort(key=lambda a: (a["due_in_days"] is None, a["due_in_days"] if a["due_in_days"] is not None else 0))
    return alerts[:20]


def _schedule_section(db: Session, auth: AuthContext) -> list[dict]:
    now = _now()
    horizon = now + timedelta(days=7)
    calls = db.scalars(
        select(PortCall).where(
            PortCall.tenant_id == auth.tenant_id,
            PortCall.eta.isnot(None),
            PortCall.eta >= now.replace(tzinfo=None),
            PortCall.eta <= horizon.replace(tzinfo=None),
        )
    ).all()
    voyages = {v.id: v for v in db.scalars(select(Voyage).where(Voyage.tenant_id == auth.tenant_id)).all()}
    ports = {p.id: p.name for p in db.scalars(select(Port)).all()}
    vessels = {v.id: v.name for v in db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id)).all()}
    out = []
    for pc in calls:
        voy = voyages.get(pc.voyage_id)
        out.append(
            {
                "kind": "port_call",
                "title": ports.get(pc.port_id) or f"Port call #{pc.seq}",
                "subtitle": " · ".join(
                    p
                    for p in [
                        voy.voyage_no if voy else None,
                        vessels.get(voy.vessel_id) if voy and voy.vessel_id else None,
                        pc.purpose,
                    ]
                    if p
                ),
                "start": _aware(pc.eta).isoformat() if pc.eta else None,
                "href": "/operations/voyages",
            }
        )
    out.sort(key=lambda s: s["start"] or "")
    return out[:10]


def _kpi(key: str, en: str, zh: str, value, hint: str, href: str) -> dict:
    return {"key": key, "label": {"en": en, "zh": zh}, "value": str(value), "hint": hint, "href": href}


def _count(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def _kpis_for_role(db: Session, auth: AuthContext, role: str) -> list[dict]:
    tid = auth.tenant_id
    today = date.today()
    if role == "technical":
        return [
            _kpi(
                "certs_expiring_30d", "Certs expiring (30d)", "30天内到期证书",
                _count(db, select(ShipCertificate.id).where(ShipCertificate.tenant_id == tid, ShipCertificate.status == "expiring")),
                "Ship certificates", "/ship",
            ),
            _kpi(
                "open_work_orders", "Open work orders", "未完工单",
                _count(db, select(ShipWorkOrder.id).where(ShipWorkOrder.tenant_id == tid, ShipWorkOrder.status.in_(["open", "in_progress"]))),
                "PMS / defects", "/ship",
            ),
            _kpi(
                "open_defects", "Open defects", "未关闭缺陷",
                _count(db, select(ShipDefect.id).where(ShipDefect.tenant_id == tid, ShipDefect.status == "open")),
                "Fleet defects", "/ship",
            ),
        ]
    if role == "operations":
        now = _now().replace(tzinfo=None)
        return [
            _kpi(
                "active_voyages", "Active voyages", "在航航次",
                _count(db, select(Voyage.id).where(Voyage.tenant_id == tid, Voyage.status == "in_progress")),
                "In progress", "/operations/voyages",
            ),
            _kpi(
                "upcoming_port_calls_7d", "Port calls (7d)", "7日内靠港",
                _count(
                    db,
                    select(PortCall.id).where(
                        PortCall.tenant_id == tid,
                        PortCall.eta.isnot(None),
                        PortCall.eta >= now,
                        PortCall.eta <= now + timedelta(days=7),
                    ),
                ),
                "Next 7 days", "/operations/voyages",
            ),
        ]
    if role == "chartering":
        return [
            _kpi(
                "open_estimates", "Open estimates", "进行中估算",
                _count(db, select(Estimate.id).where(Estimate.tenant_id == tid, Estimate.status.in_(["draft", "calculated"]))),
                "Pipeline", "/estimates",
            ),
            _kpi(
                "open_fixtures", "Open fixtures", "进行中成交",
                _count(db, select(Charter.id).where(Charter.tenant_id == tid, Charter.status.in_(["draft", "pending_approval"]))),
                "Not yet active", "/charters",
            ),
        ]
    if role == "finance":
        return [
            _kpi(
                "overdue_invoices", "Overdue invoices", "逾期未付发票",
                _count(
                    db,
                    select(Invoice.id).where(
                        Invoice.tenant_id == tid,
                        Invoice.status.in_(["issued", "partially_paid"]),
                        Invoice.due_date.isnot(None),
                        Invoice.due_date < today,
                        Invoice.amount > Invoice.paid_amount,
                    ),
                ),
                "Past due date", "/finance",
            )
        ]
    return _fallback_kpis(db, auth)


def _fallback_kpis(db: Session, auth: AuthContext) -> list[dict]:
    tid = auth.tenant_id
    return [
        _kpi(
            "open_tasks", "Open tasks", "未完成任务",
            _count(db, select(Task.id).where(Task.tenant_id == tid, Task.status.notin_(["done", "cancelled"]))),
            "Tenant-wide", "/tasks",
        ),
        _kpi(
            "certs_expiring_30d", "Certs expiring (30d)", "30天内到期证书",
            _count(db, select(ShipCertificate.id).where(ShipCertificate.tenant_id == tid, ShipCertificate.status == "expiring")),
            "Ship certificates", "/ship",
        ),
        _kpi(
            "unread_notifications", "Unread notifications", "未读通知",
            _count(
                db,
                select(Notification.id).where(
                    Notification.tenant_id == tid,
                    or_(Notification.user_id == auth.user_id, Notification.user_id.is_(None)),
                    Notification.read_at.is_(None),
                ),
            ),
            "For you", "/home",
        ),
    ]


_KPI_ROLE_ORDER = ["technical", "operations", "chartering", "finance", "tenant_admin", "management", "viewer"]


def _kpis_section(db: Session, auth: AuthContext) -> list[dict]:
    kpis: list[dict] = []
    seen: set[str] = set()
    for role in _KPI_ROLE_ORDER:
        if role not in auth.roles:
            continue
        try:
            items = _kpis_for_role(db, auth, role)
        except Exception:  # noqa: BLE001
            log.exception("home kpi group failed role=%s", role)
            db.rollback()
            continue
        for item in items:
            if item["key"] in seen:
                continue
            seen.add(item["key"])
            kpis.append(item)
    return kpis[:6]


def _queues_section(db: Session, auth: AuthContext) -> list[dict]:
    """U3 工作队列：例外驱动的待办单据，行内可直达单据详情（可深链）。"""
    tid = auth.tenant_id
    queues: list[dict] = []

    def days_to_timebar(tb: date | None) -> int | None:
        return (tb - date.today()).days if tb else None

    # 1) 临近时效的索赔（≤14 天，未结）——索赔流失的最大来源
    claims = db.scalars(
        select(Claim).where(
            Claim.tenant_id == tid,
            Claim.status.in_(["open", "negotiating"]),
            Claim.time_bar.is_not(None),
        )
    ).all()
    soon = sorted(
        (c for c in claims if (d := days_to_timebar(c.time_bar)) is not None and d <= 14),
        key=lambda c: c.time_bar,
    )
    if soon:
        queues.append(
            {
                "id": "claims_timebar",
                "label": {"en": "Claims nearing time bar", "zh": "临近时效的索赔"},
                "items": [
                    {
                        "id": str(c.id),
                        "title": c.claim_no,
                        "meta": f"{days_to_timebar(c.time_bar)}d · {c.status}",
                        "href": f"/finance/claims/{c.id}",
                        "urgency": "critical" if (days_to_timebar(c.time_bar) or 0) <= 7 else "warning",
                    }
                    for c in soon[:8]
                ],
            }
        )

    # 2) 待审批发票
    pending_inv = db.scalars(
        select(Invoice)
        .where(Invoice.tenant_id == tid, Invoice.status == "pending_approval")
        .order_by(Invoice.due_date.is_(None), Invoice.due_date)
        .limit(8)
    ).all()
    if pending_inv:
        queues.append(
            {
                "id": "invoices_approval",
                "label": {"en": "Invoices awaiting approval", "zh": "待审批发票"},
                "items": [
                    {"id": str(i.id), "title": i.invoice_no, "meta": i.invoice_type or "", "href": f"/finance/invoices/{i.id}", "urgency": "warning"}
                    for i in pending_inv
                ],
            }
        )

    # 3) 待处理 laytime（draft=待计算 / calculated=待定稿）
    lts = db.scalars(
        select(LaytimeCalc)
        .where(LaytimeCalc.tenant_id == tid, LaytimeCalc.status.in_(["draft", "calculated"]))
        .order_by(LaytimeCalc.id)
        .limit(8)
    ).all()
    if lts:
        queues.append(
            {
                "id": "laytime_pending",
                "label": {"en": "Laytime to process", "zh": "待处理 Laytime"},
                "items": [
                    {
                        "id": str(l.id),
                        "title": str(l.id)[:8],
                        "meta": l.status,
                        "href": "/finance?tab=laytime",
                        "urgency": "info",
                    }
                    for l in lts
                ],
            }
        )

    # 4) 待定稿 PDA/FDA（draft/submitted）
    pdas = db.scalars(
        select(PortDisbursement)
        .where(PortDisbursement.tenant_id == tid, PortDisbursement.status.in_(["draft", "submitted"]))
        .order_by(PortDisbursement.id)
        .limit(8)
    ).all()
    if pdas:
        queues.append(
            {
                "id": "pda_pending",
                "label": {"en": "PDA/FDA to settle", "zh": "待定稿 PDA/FDA"},
                "items": [
                    {
                        "id": str(p.id),
                        "title": str(p.id)[:8],
                        "meta": f"{p.status} · {p.pda_amount or 0}",
                        "href": "/finance?tab=pda",
                        "urgency": "info",
                    }
                    for p in pdas
                ],
            }
        )
    return queues


@router.get("/activity/feed")
def activity_feed(
    limit: int = 30,
    module: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Role-scoped operation log for the workbench. Newest first, click-through.

    - supervisors (management / tenant_admin / platform_admin): every module's log;
    - everyone else: their own actions + others' actions for modules their roles cover.
    Each item carries a frontend ``href`` so a click jumps straight to the record.
    """
    from app.models_audit import AuditLog

    roles = set(auth.roles)
    supervisor = bool(roles & _SUPERVISOR_ROLES)
    my_modules: set[str] = set()
    for r in roles:
        my_modules |= _ROLE_MODULES.get(r, frozenset())

    window = min(max(limit, 1) * 4, 200)
    rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.tenant_id == auth.tenant_id,
            # 登录事件不进工作台操作日志 —— 否则首屏被「谁登录了」刷屏，
            # 主管想看的是各模块的业务操作。安全审计另有专页（/admin/security/audit-logs）。
            AuditLog.action.notin_(tuple(_FEED_NOISE_ACTIONS)),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(window)
    ).all()

    actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()}
        if actor_ids
        else {}
    )

    out: list[dict] = []
    for r in rows:
        ent_mod = _ENTITY_MODULE.get(r.entity_type or "")
        if module and ent_mod != module:
            continue
        visible = (
            supervisor
            or (r.actor_user_id is not None and r.actor_user_id == auth.user_id)
            or (ent_mod in my_modules if ent_mod else False)
        )
        if not visible:
            continue
        actor = users.get(r.actor_user_id)
        href = None
        if r.entity_type in _ENTITY_HREF and r.entity_id:
            href = _ENTITY_HREF[r.entity_type].format(id=r.entity_id)
        out.append(
            {
                "id": str(r.id),
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "module": ent_mod,
                "actor": (actor.full_name or actor.email) if actor else None,
                "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
                "detail": r.detail or {},
                "href": href,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
        if len(out) >= limit:
            break
    return {"items": out, "count": len(out), "supervisor": supervisor}


@router.get("/home/summary")
def home_summary(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    summary: dict = {"tasks": {}, "notifications": {}, "approvals": {}, "alerts": [], "schedule": [], "kpis": [], "exceptions": {"critical": 0, "warning": 0}, "queues": []}
    try:
        summary["tasks"] = _tasks_section(db, auth)
    except Exception:  # noqa: BLE001
        log.exception("home summary tasks section failed")
        db.rollback()
        summary["tasks"] = {"open": 0, "overdue": 0, "due_today": 0, "items": []}
    try:
        summary["notifications"] = _notifications_section(db, auth)
    except Exception:  # noqa: BLE001
        log.exception("home summary notifications section failed")
        db.rollback()
        summary["notifications"] = {"unread": 0, "items": []}
    try:
        summary["approvals"] = _approvals_section(db, auth)
    except Exception:  # noqa: BLE001
        log.exception("home summary approvals section failed")
        db.rollback()
        summary["approvals"] = {"count": 0, "items": []}
    try:
        summary["alerts"] = _ship_alerts(db, auth)
    except Exception:  # noqa: BLE001
        log.exception("home summary alerts section failed")
        db.rollback()
        summary["alerts"] = []
    try:
        summary["schedule"] = _schedule_section(db, auth)
    except Exception:  # noqa: BLE001
        log.exception("home summary schedule section failed")
        db.rollback()
        summary["schedule"] = []
    try:
        summary["queues"] = _queues_section(db, auth)
    except Exception:  # noqa: BLE001
        log.exception("home summary queues section failed")
        db.rollback()
        summary["queues"] = []
    summary["kpis"] = _kpis_section(db, auth)
    try:
        from app.services.exceptions import scan_exceptions

        scan = scan_exceptions(db, auth.tenant_id, notify=False)
        summary["exceptions"] = {"critical": scan["summary"]["critical"], "warning": scan["summary"]["warning"]}
    except Exception:  # noqa: BLE001
        log.exception("home summary exceptions section failed")
        db.rollback()
    return summary
