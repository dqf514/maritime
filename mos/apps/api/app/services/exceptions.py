"""Exception centre — cross-module red-flag scan (P&L, ETA, laytime, claims, AR, certs, TC, sanctions)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import (
    Charter,
    Claim,
    Invoice,
    LaytimeCalc,
    NoonReport,
    OffHireEvent,
    PortCall,
    Voyage,
)
from app.models_ship import ShipCertificate
from app.models_wave1 import Counterparty, Vessel
from app.services import dq as dq_service
from app.services.notifications import notify_roles_once
from app.services.pnl import voyage_pnl_rows

log = logging.getLogger("marios.exceptions")

MAX_ITEMS = 100

# Base roles always notified on critical items, plus a module-specific role.
_NOTIFY_ROLES: dict[str, tuple[str, ...]] = {
    "pnl_deterioration": ("tenant_admin", "management", "finance"),
    "eta_delay": ("tenant_admin", "management", "operations"),
    "demurrage_open": ("tenant_admin", "management", "finance"),
    "claim_timebar": ("tenant_admin", "management", "finance"),
    "invoice_overdue": ("tenant_admin", "management", "finance"),
    "cert_expired": ("tenant_admin", "management", "technical"),
    "cert_expiring": ("tenant_admin", "management", "technical"),
    "off_hire_open": ("tenant_admin", "management", "operations"),
    "tc_redelivery_due": ("tenant_admin", "management", "chartering"),
    "sanctions_blocked": ("tenant_admin", "management", "chartering"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _item(
    kind: str,
    severity: str,
    title: str,
    detail: str,
    value: str,
    entity_type: str,
    entity_id: str | None,
    href: str,
    amount: float = 0.0,
) -> dict:
    return {
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "value": value,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "href": href,
        "_amount": amount,
    }


def _money(amount: float, currency: str = "USD") -> str:
    return f"{amount:,.2f} {currency}"


def _pnl_deterioration(db: Session, tenant_id: UUID) -> list[dict]:
    out = []
    for row in voyage_pnl_rows(db, tenant_id):
        if row["voyage_id"] == "unassigned" or row["status"] != "in_progress":
            continue
        var = float(row["variance_pnl"] or 0)
        if var >= 0:
            continue
        est = float(row["estimated_pnl"] or 0)
        ratio = abs(var / est) if est else 0.0
        if abs(var) >= 50000 or ratio >= 0.20:
            severity = "critical"
        elif abs(var) >= 10000 or ratio >= 0.10:
            severity = "warning"
        else:
            continue
        out.append(
            _item(
                "pnl_deterioration",
                severity,
                f"P&L deterioration: {row['voyage_no']}",
                f"actual P&L {_money(row['actual_pnl'])} vs estimate {_money(row['estimated_pnl'])}",
                _money(var),
                "voyage",
                row["voyage_id"],
                f"/operations/voyages/{row['voyage_id']}",
                abs(var),
            )
        )
    return out


def _eta_delay(db: Session, tenant_id: UUID) -> list[dict]:
    out = []
    voyages = db.scalars(
        select(Voyage).where(Voyage.tenant_id == tenant_id, Voyage.status == "in_progress")
    ).all()
    by_id = {v.id: v for v in voyages}
    if not by_id:
        return out
    reports = db.scalars(
        select(NoonReport)
        .where(NoonReport.tenant_id == tenant_id, NoonReport.voyage_id.in_(by_id))
        .order_by(NoonReport.report_at.desc())
    ).all()
    latest: dict[UUID, NoonReport] = {}
    for r in reports:
        latest.setdefault(r.voyage_id, r)
    for vid, r in latest.items():
        dev = abs(float(r.eta_deviation_hours or 0))
        if dev >= 24:
            severity = "critical"
        elif dev >= 6:
            severity = "warning"
        else:
            continue
        v = by_id[vid]
        out.append(
            _item(
                "eta_delay",
                severity,
                f"ETA delay: {v.voyage_no}",
                f"noon report ETA deviation {dev:.1f}h",
                f"{dev:.1f} h",
                "voyage",
                str(vid),
                f"/operations/voyages/{vid}",
            )
        )
    calls = db.scalars(
        select(PortCall).where(
            PortCall.tenant_id == tenant_id,
            PortCall.voyage_id.in_(by_id),
            PortCall.eta.isnot(None),
            PortCall.ata.isnot(None),
        )
    ).all()
    for pc in calls:
        eta, ata = _aware(pc.eta), _aware(pc.ata)
        if not eta or not ata:
            continue
        delay_h = (ata - eta).total_seconds() / 3600.0
        if delay_h < 12:
            continue
        v = by_id.get(pc.voyage_id)
        out.append(
            _item(
                "eta_delay",
                "warning",
                f"Late arrival: {v.voyage_no if v else '—'} call #{pc.seq}",
                f"ATA {delay_h:.1f}h after ETA ({pc.purpose})",
                f"{delay_h:.1f} h",
                "voyage",
                str(pc.voyage_id),
                f"/operations/voyages/{pc.voyage_id}",
            )
        )
    return out


def _demurrage_open(db: Session, tenant_id: UUID) -> list[dict]:
    out = []
    rows = db.scalars(
        select(LaytimeCalc).where(LaytimeCalc.tenant_id == tenant_id, LaytimeCalc.status == "calculated")
    ).all()
    for r in rows:
        results = r.results or {}
        amount = float(results.get("amount") or 0)
        if results.get("result_type") != "demurrage" or amount <= 0:
            continue
        currency = results.get("currency") or "USD"
        out.append(
            _item(
                "demurrage_open",
                "warning",
                f"Demurrage not claimed: {_money(amount, currency)}",
                f"laytime {str(r.id)[:8]} calculated · demurrage",
                _money(amount, currency),
                "voyage",
                str(r.voyage_id) if r.voyage_id else None,
                f"/operations/voyages/{r.voyage_id}" if r.voyage_id else "/finance",
                amount,
            )
        )
    return out


def _claim_timebar(db: Session, tenant_id: UUID) -> list[dict]:
    out = []
    today = date.today()
    rows = db.scalars(
        select(Claim).where(Claim.tenant_id == tenant_id, Claim.status.in_(["open", "negotiating"]))
    ).all()
    for r in rows:
        if not r.time_bar:
            continue
        days = (r.time_bar - today).days
        if days < 30:
            severity = "critical"
        elif days < 90:
            severity = "warning"
        else:
            continue
        amount = float(r.amount or 0)
        out.append(
            _item(
                "claim_timebar",
                severity,
                f"Time bar approaching: {r.claim_no}",
                f"{days}d to time bar ({r.time_bar.isoformat()}) · {r.status}",
                f"{days} d",
                "claim",
                str(r.id),
                "/finance",
                amount,
            )
        )
    return out


def _invoice_overdue(db: Session, tenant_id: UUID) -> list[dict]:
    out = []
    today = date.today()
    rows = db.scalars(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.status.in_(["issued", "partially_paid"]),
            Invoice.due_date.isnot(None),
            Invoice.due_date < today,
        )
    ).all()
    for r in rows:
        open_amount = float(r.amount or 0) + float(r.tax_amount or 0) - float(r.paid_amount or 0)
        if open_amount <= 0:
            continue
        days = (today - r.due_date).days
        severity = "critical" if days > 30 else "warning"
        out.append(
            _item(
                "invoice_overdue",
                severity,
                f"Invoice overdue: {r.invoice_no}",
                f"{days}d past due · open {_money(open_amount, r.currency or 'USD')}",
                _money(open_amount, r.currency or "USD"),
                "invoice",
                str(r.id),
                "/finance",
                open_amount,
            )
        )
    return out


def _cert_flags(db: Session, tenant_id: UUID) -> list[dict]:
    from app.routers.ship_mgmt import _refresh_certificate_status

    _refresh_certificate_status(db, tenant_id)
    out = []
    vessels = {v.id: v.name for v in db.scalars(select(Vessel).where(Vessel.tenant_id == tenant_id)).all()}
    today = date.today()
    rows = db.scalars(
        select(ShipCertificate).where(
            ShipCertificate.tenant_id == tenant_id,
            ShipCertificate.status.in_(["expired", "expiring"]),
        )
    ).all()
    for c in rows:
        expired = c.status == "expired"
        due_in = (c.expires_on - today).days if c.expires_on else None
        out.append(
            _item(
                "cert_expired" if expired else "cert_expiring",
                "critical" if expired else "warning",
                f"Certificate {'expired' if expired else 'expiring'}: {c.cert_name}",
                f"{vessels.get(c.vessel_id) or ''} · {c.cert_code} · {c.expires_on.isoformat() if c.expires_on else '—'}".strip(" ·"),
                f"{due_in} d" if due_in is not None else "—",
                "certificate",
                str(c.id),
                "/ship",
            )
        )
    return out


def _off_hire_open(db: Session, tenant_id: UUID) -> list[dict]:
    out = []
    rows = db.scalars(
        select(OffHireEvent).where(
            OffHireEvent.tenant_id == tenant_id,
            OffHireEvent.status == "open",
            OffHireEvent.deduct_hire.is_(True),
        )
    ).all()
    for r in rows:
        start = _aware(r.start_at)
        days = ((_now() - start).total_seconds() / 86400.0) if start else 0.0
        out.append(
            _item(
                "off_hire_open",
                "warning",
                f"Off-hire open: {r.reason or '—'}",
                f"since {start.date().isoformat() if start else '—'} · {days:.1f}d · deducts hire",
                f"{days:.1f} d",
                "voyage",
                str(r.voyage_id),
                f"/operations/voyages/{r.voyage_id}",
            )
        )
    return out


def _tc_redelivery_due(db: Session, tenant_id: UUID) -> list[dict]:
    out = []
    horizon = _now() + timedelta(days=14)
    rows = db.scalars(
        select(Charter).where(
            Charter.tenant_id == tenant_id,
            Charter.status == "active",
            Charter.charter_type == "tct",
            Charter.redelivery_at.isnot(None),
        )
    ).all()
    for c in rows:
        redelivery = _aware(c.redelivery_at)
        if not redelivery or redelivery > horizon:
            continue
        days = (redelivery - _now()).days
        out.append(
            _item(
                "tc_redelivery_due",
                "warning",
                f"TC redelivery due: {c.charter_no}",
                f"redelivery {redelivery.date().isoformat()} · {days}d",
                f"{days} d",
                "charter",
                str(c.id),
                "/charters",
            )
        )
    return out


def _sanctions_blocked(db: Session, tenant_id: UUID) -> list[dict]:
    out = []
    rows = db.scalars(
        select(Charter).where(Charter.tenant_id == tenant_id, Charter.status == "active")
    ).all()
    parties = {
        p.id: p
        for p in db.scalars(select(Counterparty).where(Counterparty.tenant_id == tenant_id)).all()
    }
    for c in rows:
        party = parties.get(c.counterparty_id) if c.counterparty_id else None
        if not c.sanctions_blocked and not (party and party.sanctions_status == "blocked"):
            continue
        out.append(
            _item(
                "sanctions_blocked",
                "critical",
                f"Sanctions blocked: {c.charter_no}",
                f"{party.name if party else '—'} · sanctions_status={party.sanctions_status if party else '—'}",
                "blocked",
                "counterparty",
                str(party.id) if party else str(c.id),
                "/charters",
            )
        )
    return out


def _dq_issues(db: Session, tenant_id: UUID) -> list[dict]:
    count = dq_service.open_issue_count(db, tenant_id)
    if count <= 0:
        return []
    return [
        _item(
            "dq_issue",
            "warning",
            f"{count} data quality issue{'s' if count != 1 else ''}",
            "auto DQ scan findings awaiting fixes",
            str(count),
            "dq_issue",
            None,
            "/analytics",
            float(count),
        )
    ]


_SIGNALS = (
    _pnl_deterioration,
    _eta_delay,
    _demurrage_open,
    _claim_timebar,
    _invoice_overdue,
    _cert_flags,
    _off_hire_open,
    _tc_redelivery_due,
    _sanctions_blocked,
    _dq_issues,
)


def scan_exceptions(db: Session, tenant_id: UUID, *, notify: bool = True) -> dict:
    items: list[dict] = []
    for signal in _SIGNALS:
        try:
            items.extend(signal(db, tenant_id))
        except Exception:  # noqa: BLE001
            log.exception("exception scan signal failed: %s", signal.__name__)
            db.rollback()
    items.sort(key=lambda i: (i["severity"] != "critical", -i["_amount"]))
    items = items[:MAX_ITEMS]
    detected_at = _now().isoformat()
    if notify:
        try:
            for i in items:
                if i["severity"] != "critical":
                    continue
                notify_roles_once(
                    db,
                    tenant_id,
                    _NOTIFY_ROLES.get(i["kind"], ("tenant_admin", "management")),
                    title=i["title"],
                    body=i["detail"],
                    href=i["href"],
                    level="critical",
                )
            db.commit()
        except Exception:  # noqa: BLE001
            log.exception("exception scan notifications failed")
            db.rollback()
    critical = sum(1 for i in items if i["severity"] == "critical")
    warning = sum(1 for i in items if i["severity"] == "warning")
    for i in items:
        i.pop("_amount", None)
        i["detected_at"] = detected_at
    return {"summary": {"critical": critical, "warning": warning, "total": len(items)}, "items": items}
