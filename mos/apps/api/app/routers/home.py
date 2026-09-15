"""Role-aware workbench aggregation — one call for the ERP home page."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User, UserRole
from app.models_domain import Charter, Estimate, Invoice, PortCall, Voyage
from app.models_ship import ShipCertificate, ShipCrewMember, ShipDefect, ShipWorkOrder
from app.models_task import Task
from app.models_wave1 import Notification, Port, Vessel
from app.routers.saas import workflow_inbox
from app.routers.ship_mgmt import _refresh_certificate_status
from app.routers.tasks import task_out
from app.security import AuthContext, get_current_auth

log = logging.getLogger("voyageos.home")

router = APIRouter(tags=["Home"])

ALERT_NOTIFY_ROLES = ("technical", "management", "tenant_admin")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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
    role_ids = select(Role.id).where(Role.tenant_id == tenant_id, Role.code.in_(ALERT_NOTIFY_ROLES))
    user_ids = select(UserRole.user_id).where(UserRole.role_id.in_(role_ids))
    return db.scalars(
        select(User).where(User.id.in_(user_ids), User.tenant_id == tenant_id, User.status == "active")
    ).all()


def _notify_once(db: Session, tenant_id: UUID, recipients: list[User], *, title: str, body: str, href: str, level: str) -> None:
    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    targets: list[UUID | None] = [u.id for u in recipients] or [None]
    for uid in targets:
        q = select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.href == href,
            Notification.title == title,
            Notification.created_at >= today_start,
        )
        q = q.where(Notification.user_id == uid) if uid else q.where(Notification.user_id.is_(None))
        if db.scalar(q):
            continue
        db.add(Notification(tenant_id=tenant_id, user_id=uid, title=title, body=body, level=level, href=href))


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
        alerts.append(
            {
                "kind": kind,
                "title": title,
                "detail": f"{c.cert_code} · {c.expires_on.isoformat() if c.expires_on else '—'} · {c.issuing_body or ''}".strip(),
                "href": "/ship",
                "severity": "critical" if expired else "warning",
                "due_in_days": due_in,
            }
        )
        _notify_once(
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
            alerts.append(
                {
                    "kind": "crew_cert_expiring",
                    "title": title,
                    "detail": f"{member.rank} · expires {expires_on.isoformat()}",
                    "href": "/ship",
                    "severity": "critical" if expired else "warning",
                    "due_in_days": due_in,
                }
            )
            _notify_once(
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


@router.get("/home/summary")
def home_summary(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    summary: dict = {"tasks": {}, "notifications": {}, "approvals": {}, "alerts": [], "schedule": [], "kpis": []}
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
    summary["kpis"] = _kpis_section(db, auth)
    return summary
