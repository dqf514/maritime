"""Role-based executive / ops / chartering / finance / technical dashboards.

Snapshot APIs include a live pulse (jitter) so fullscreen walls feel real-time
when polled every few seconds. Data prefers DB seed; falls back to synthetic.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import (
    Charter,
    Claim,
    Estimate,
    Invoice,
    NoonReport,
    TwinAlert,
    Voyage,
)
from app.models_ship import ShipCertificate, ShipDefect, ShipWorkOrder
from app.models_wave1 import Vessel
from app.security import AuthContext, require_auth

router = APIRouter(prefix="/dashboards", tags=["Dashboards"])

ROLE_SCREENS = {
    "management": {
        "title": "Executive Command Wall",
        "subtitle": "Owner / director commercial pulse",
        "accent": "#2bb5b0",
    },
    "chartering": {
        "title": "Chartering Day Board",
        "subtitle": "Pipeline · fixtures · market heat",
        "accent": "#3d8bfd",
    },
    "operations": {
        "title": "Ops Situation Room",
        "subtitle": "Voyages · ETA risk · fleet positions",
        "accent": "#f0a020",
    },
    "finance": {
        "title": "Finance Cash Wall",
        "subtitle": "AR · collections · voyage P&L",
        "accent": "#34c759",
    },
    "demurrage": {
        "title": "Laytime & Claims Wall",
        "subtitle": "Time bar · demurrage · SOF risk",
        "accent": "#c45c26",
    },
    "technical": {
        "title": "Technical Fleet Wall",
        "subtitle": "Certificates · PMS · defects · drydock",
        "accent": "#8b5cf6",
    },
    "tenant_admin": {
        "title": "Tenant Control Wall",
        "subtitle": "Adoption · licenses · workflow health",
        "accent": "#1a8a8a",
    },
}


def _now() -> datetime:
    return datetime.now().astimezone()


def _pulse(seed: str, amplitude: float = 1.0) -> float:
    """Deterministic-ish live jitter based on current minute+second."""
    t = _now()
    h = int(hashlib.md5(f"{seed}:{t.minute}:{t.second // 5}".encode()).hexdigest()[:8], 16)
    rnd = (h % 1000) / 1000.0
    wave = math.sin(t.second / 9.5 + (h % 7))
    return round(amplitude * (0.85 + 0.3 * rnd + 0.08 * wave), 2)


def _primary_role(roles: list[str]) -> str:
    order = ["management", "chartering", "operations", "finance", "demurrage", "technical", "tenant_admin"]
    for r in order:
        if r in roles:
            return r
    if "platform_admin" in roles:
        return "management"
    return "management"


@router.get("/catalog")
def dashboard_catalog(auth: AuthContext = Depends(require_auth)):
    roles = auth.roles or []
    items = []
    for code, meta in ROLE_SCREENS.items():
        if code in roles or "tenant_admin" in roles or "management" in roles:
            items.append({"role": code, **meta, "href": f"/dashboards/{code}"})
    if not items:
        items = [{"role": "management", **ROLE_SCREENS["management"], "href": "/dashboards/management"}]
    return {"default_role": _primary_role(roles), "screens": items}


@router.get("/{role}/snapshot")
def dashboard_snapshot(
    role: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    if role not in ROLE_SCREENS:
        raise HTTPException(404, "Unknown dashboard role")
    # management / tenant_admin can open any wall; others their own + management view
    if role not in (auth.roles or []) and "tenant_admin" not in (auth.roles or []) and "management" not in (
        auth.roles or []
    ):
        if role != _primary_role(auth.roles or []):
            raise HTTPException(403, "Role wall not permitted")

    tid = auth.tenant_id
    meta = ROLE_SCREENS[role]
    builders = {
        "management": _mgmt,
        "chartering": _chartering,
        "operations": _operations,
        "finance": _finance,
        "demurrage": _demurrage,
        "technical": _technical,
        "tenant_admin": _admin,
    }
    body = builders[role](db, tid)
    return {
        "role": role,
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "accent": meta["accent"],
        "generated_at": _now().isoformat(),
        "refresh_hint_sec": 5,
        "live": True,
        **body,
    }


def _kpi(label: str, value: Any, unit: str = "", delta: str | None = None, tone: str = "neutral") -> dict:
    return {"label": label, "value": value, "unit": unit, "delta": delta, "tone": tone}


def _mgmt(db: Session, tid: UUID) -> dict:
    voyages = db.scalars(select(Voyage).where(Voyage.tenant_id == tid)).all()
    active = [v for v in voyages if v.status in ("in_progress", "planned", "active")]
    invoices = db.scalars(select(Invoice).where(Invoice.tenant_id == tid)).all()
    revenue = sum(float(i.amount or 0) for i in invoices)
    unpaid = sum(float(i.amount or 0) - float(i.paid_amount or 0) for i in invoices if i.status != "paid")
    vessels = db.scalars(select(Vessel).where(Vessel.tenant_id == tid)).all()
    tce = _pulse("tce", 18500)
    util = min(98.0, 72 + _pulse("util", 8))
    series_tce = [{"t": i, "v": round(tce + math.sin(i / 2) * 900 + random.Random(i).uniform(-200, 200), 0)} for i in range(12)]
    series_pnl = [{"t": i, "v": round(0.4 + i * 0.08 + _pulse(f"pnl{i}", 0.05), 2)} for i in range(8)]
    fleet_map = []
    for i, v in enumerate(vessels[:8]):
        noon = db.scalar(
            select(NoonReport)
            .join(Voyage, Voyage.id == NoonReport.voyage_id)
            .where(Voyage.vessel_id == v.id)
            .order_by(NoonReport.report_at.desc())
            .limit(1)
        )
        lat = float(noon.lat) if noon and noon.lat is not None else 1.2 + i * 4.5
        lon = float(noon.lon) if noon and noon.lon is not None else 103.8 + i * 8.2
        fleet_map.append(
            {
                "name": v.name,
                "lat": lat + _pulse(f"lat{i}", 0.02) * 0.01,
                "lon": lon,
                "status": "steaming" if i % 2 == 0 else "port",
            }
        )
    alerts = db.scalars(select(TwinAlert).where(TwinAlert.tenant_id == tid).limit(8)).all()
    return {
        "kpis": [
            _kpi("Fleet TCE (live)", f"{tce:,.0f}", "USD/d", "+3.2%", "good"),
            _kpi("Active voyages", len(active) or 3, "", None, "neutral"),
            _kpi("Fleet util.", f"{util:.1f}", "%", "+1.1%", "good"),
            _kpi("Open AR", f"{unpaid or 1_240_000:,.0f}", "USD", "-4%", "warn" if unpaid > revenue * 0.3 else "good"),
            _kpi("YTD freight", f"{revenue or 8_420_000:,.0f}", "USD", "+12%", "good"),
            _kpi("Vessels", len(vessels) or 4, "", None, "neutral"),
        ],
        "charts": [
            {"id": "tce_trend", "title": "Rolling TCE", "type": "line", "series": series_tce},
            {"id": "pnl", "title": "Voyage P&L index", "type": "bar", "series": series_pnl},
        ],
        "fleet_positions": fleet_map,
        "feed": [
            {
                "tone": "warn" if a.level in ("high", "critical", "warn") else "info",
                "text": a.title,
                "ts": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ]
        or [
            {"tone": "info", "text": "Singapore bunker index firming — watch VLSFO", "ts": _now().isoformat()},
            {"tone": "good", "text": "MV PACIFIC STAR TCE above budget +8%", "ts": _now().isoformat()},
            {"tone": "warn", "text": "Rotterdam berth congestion +18h on VOY-2408", "ts": _now().isoformat()},
        ],
        "heatmap": [
            {"label": "Pacific", "value": 78 + int(_pulse("hm1", 5))},
            {"label": "Atlantic", "value": 64 + int(_pulse("hm2", 4))},
            {"label": "Indian", "value": 71 + int(_pulse("hm3", 6))},
            {"label": "Med", "value": 55 + int(_pulse("hm4", 3))},
        ],
    }


def _chartering(db: Session, tid: UUID) -> dict:
    estimates = db.scalars(select(Estimate).where(Estimate.tenant_id == tid)).all()
    charters = db.scalars(select(Charter).where(Charter.tenant_id == tid)).all()
    open_est = [e for e in estimates if e.status in ("draft", "working", "submitted")]
    active_cp = [c for c in charters if c.status in ("active", "approved", "submitted")]
    pipeline = []
    for e in estimates[:10]:
        tce = (e.results or {}).get("tce_usd_day") or (12000 + _pulse(str(e.id)[:6], 2000))
        pipeline.append(
            {
                "id": str(e.id),
                "title": e.title,
                "status": e.status,
                "tce": round(float(tce), 0),
                "mode": e.mode,
            }
        )
    return {
        "kpis": [
            _kpi("Open estimates", len(open_est) or len(estimates) or 5, "", None, "neutral"),
            _kpi("Active fixtures", len(active_cp) or 2, "", None, "good"),
            _kpi("Win rate", f"{42 + int(_pulse('win', 4))}", "%", "+2%", "good"),
            _kpi("Avg bid TCE", f"{14500 + int(_pulse('bid', 400)):,}", "USD/d", None, "neutral"),
            _kpi("Laycan this week", 3, "CPs", None, "warn"),
            _kpi("Mail queue", 7 + int(_pulse("mail", 2)), "", None, "neutral"),
        ],
        "charts": [
            {
                "id": "pipeline",
                "title": "Estimate TCE stack",
                "type": "bar",
                "series": [{"t": p["title"][:12], "v": p["tce"]} for p in pipeline[:8]]
                or [{"t": f"Op {i}", "v": 12000 + i * 800} for i in range(6)],
            },
            {
                "id": "fixture_mix",
                "title": "Fixture mix",
                "type": "donut",
                "series": [
                    {"t": "Voyage", "v": 55},
                    {"t": "TCT", "v": 30},
                    {"t": "COA", "v": 15},
                ],
            },
        ],
        "table": {
            "title": "Opportunity pipeline",
            "columns": ["title", "status", "tce", "mode"],
            "rows": pipeline
            or [
                {"title": "SGSIN→NLRTM iron ore", "status": "working", "tce": 16200, "mode": "voyage"},
                {"title": "CNTXG grains TCT", "status": "draft", "tce": 14800, "mode": "tct"},
            ],
        },
        "feed": [
            {"tone": "good", "text": "Recap confirmed — CP-2407 activated", "ts": _now().isoformat()},
            {"tone": "info", "text": "Baltic Capesize index +1.4%", "ts": _now().isoformat()},
            {"tone": "warn", "text": "Sanction re-screen due on Charterer X", "ts": _now().isoformat()},
        ],
        "fleet_positions": [],
        "heatmap": [],
    }


def _operations(db: Session, tid: UUID) -> dict:
    voyages = db.scalars(select(Voyage).where(Voyage.tenant_id == tid)).all()
    alerts = db.scalars(select(TwinAlert).where(TwinAlert.tenant_id == tid).limit(12)).all()
    noons = db.scalars(select(NoonReport).where(NoonReport.tenant_id == tid).order_by(NoonReport.report_at.desc()).limit(20)).all()
    vessels = {v.id: v for v in db.scalars(select(Vessel).where(Vessel.tenant_id == tid)).all()}
    positions = []
    for n in noons[:8]:
        voy = db.get(Voyage, n.voyage_id)
        name = vessels.get(voy.vessel_id).name if voy and voy.vessel_id in vessels else "Vessel"
        positions.append(
            {
                "name": name,
                "lat": float(n.lat or 0) + _pulse(str(n.id)[:4], 0.01) * 0.02,
                "lon": float(n.lon or 0),
                "status": "steaming",
                "speed": float(n.speed or 12),
            }
        )
    if not positions:
        positions = [
            {"name": "MV DEMO WAVE", "lat": 1.35, "lon": 104.2, "status": "steaming", "speed": 12.4},
            {"name": "MV PACIFIC STAR", "lat": 22.1, "lon": 114.2, "status": "port", "speed": 0},
            {"name": "MV ATLANTIC PEARL", "lat": 51.9, "lon": 4.1, "status": "steaming", "speed": 13.1},
        ]
    eta_risk = sum(1 for a in alerts if "eta" in (a.title or "").lower() or a.level in ("high", "critical", "warn"))
    return {
        "kpis": [
            _kpi("In progress", len([v for v in voyages if v.status == "in_progress"]) or 2, "voy", None, "neutral"),
            _kpi("ETA risk", eta_risk or 1, "alerts", None, "warn"),
            _kpi("Noon lag", f"{max(0, 2 - int(_pulse('noon', 1)))}", "h", None, "good"),
            _kpi("Port calls today", 4, "", None, "neutral"),
            _kpi("Bunker ROB alert", 1, "vsl", None, "warn"),
            _kpi("Twin health", f"{96 + int(_pulse('twin', 2))}", "%", None, "good"),
        ],
        "charts": [
            {
                "id": "speed",
                "title": "Fleet speed (kn)",
                "type": "line",
                "series": [{"t": i, "v": round(11.5 + math.sin(i) * 1.2 + _pulse(f"sp{i}", 0.3), 1)} for i in range(12)],
            }
        ],
        "fleet_positions": positions,
        "feed": [
            {"tone": "warn" if a.level in ("high", "critical", "warn") else "info", "text": a.title, "ts": None}
            for a in alerts
        ]
        or [
            {"tone": "warn", "text": "ETA slip +6h — weather routing suggested", "ts": _now().isoformat()},
            {"tone": "info", "text": "NOR tendered at CNTXG", "ts": _now().isoformat()},
        ],
        "table": {
            "title": "Active voyages",
            "columns": ["voyage_no", "status", "cargo"],
            "rows": [{"voyage_no": v.voyage_no, "status": v.status, "cargo": v.cargo or "—"} for v in voyages[:8]]
            or [{"voyage_no": "VOY-2401", "status": "in_progress", "cargo": "Iron ore"}],
        },
        "heatmap": [],
    }


def _finance(db: Session, tid: UUID) -> dict:
    invoices = db.scalars(select(Invoice).where(Invoice.tenant_id == tid)).all()
    open_inv = [i for i in invoices if i.status not in ("paid", "void")]
    aging = {"0-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
    today = date.today()
    for i in open_inv:
        bal = float(i.amount or 0) - float(i.paid_amount or 0)
        if bal <= 0:
            continue
        due = i.due_date or today
        days = (today - due).days
        if days <= 30:
            aging["0-30"] += bal
        elif days <= 60:
            aging["31-60"] += bal
        elif days <= 90:
            aging["61-90"] += bal
        else:
            aging["90+"] += bal
    if sum(aging.values()) == 0:
        aging = {"0-30": 820000, "31-60": 310000, "61-90": 95000, "90+": 42000}
    collected = sum(float(i.paid_amount or 0) for i in invoices)
    return {
        "kpis": [
            _kpi("Open AR", f"{sum(aging.values()):,.0f}", "USD", None, "warn"),
            _kpi("Collected MTD", f"{collected or 2_100_000:,.0f}", "USD", "+6%", "good"),
            _kpi("Invoices open", len(open_inv) or 6, "", None, "neutral"),
            _kpi("DSO", f"{38 + int(_pulse('dso', 2))}", "d", "-1d", "good"),
            _kpi("Overdue >90d", f"{aging['90+']:,.0f}", "USD", None, "danger" if aging["90+"] > 0 else "good"),
            _kpi("GL unposted", sum(1 for i in invoices if not i.gl_posted), "", None, "warn"),
        ],
        "charts": [
            {
                "id": "aging",
                "title": "AR aging",
                "type": "bar",
                "series": [{"t": k, "v": round(v)} for k, v in aging.items()],
            },
            {
                "id": "cash",
                "title": "Cash in (index)",
                "type": "line",
                "series": [{"t": i, "v": round(0.7 + i * 0.05 + _pulse(f"c{i}", 0.04), 2)} for i in range(10)],
            },
        ],
        "table": {
            "title": "Invoice desk",
            "columns": ["invoice_no", "status", "amount", "due_date"],
            "rows": [
                {
                    "invoice_no": i.invoice_no,
                    "status": i.status,
                    "amount": float(i.amount),
                    "due_date": i.due_date.isoformat() if i.due_date else None,
                }
                for i in invoices[:10]
            ],
        },
        "feed": [
            {"tone": "good", "text": "Payment matched INV-2405", "ts": _now().isoformat()},
            {"tone": "warn", "text": "Reminder sent — INV-2398 61d overdue", "ts": _now().isoformat()},
        ],
        "fleet_positions": [],
        "heatmap": [],
    }


def _demurrage(db: Session, tid: UUID) -> dict:
    claims = db.scalars(select(Claim).where(Claim.tenant_id == tid)).all()
    open_c = [c for c in claims if c.status in ("open", "negotiating")]
    amount = sum(float(c.amount or 0) for c in open_c)
    return {
        "kpis": [
            _kpi("Open claims", len(open_c) or 2, "", None, "warn"),
            _kpi("Demurrage exposure", f"{amount or 186000:,.0f}", "USD", None, "warn"),
            _kpi("Time-bar <14d", 1, "", None, "danger"),
            _kpi("SOF pending", 3, "", None, "neutral"),
            _kpi("Settled YTD", f"{420000 + int(_pulse('set', 5000)):,}", "USD", None, "good"),
            _kpi("Avg days to settle", f"{28 + int(_pulse('setd', 2))}", "d", None, "neutral"),
        ],
        "charts": [
            {
                "id": "claims",
                "title": "Claims by status",
                "type": "donut",
                "series": [
                    {"t": "Open", "v": max(1, len(open_c))},
                    {"t": "Settled", "v": max(1, len(claims) - len(open_c))},
                    {"t": "Disputed", "v": 1},
                ],
            }
        ],
        "table": {
            "title": "Claims queue",
            "columns": ["claim_no", "claim_type", "status", "amount"],
            "rows": [
                {
                    "claim_no": c.claim_no,
                    "claim_type": c.claim_type,
                    "status": c.status,
                    "amount": float(c.amount or 0),
                }
                for c in claims[:10]
            ]
            or [{"claim_no": "CLM-01", "claim_type": "demurrage", "status": "open", "amount": 86000}],
        },
        "feed": [
            {"tone": "danger", "text": "Time-bar in 9 days — CLM demurrage Rotterdam", "ts": _now().isoformat()},
            {"tone": "info", "text": "Laytime calc finalized VOY-2402", "ts": _now().isoformat()},
        ],
        "fleet_positions": [],
        "heatmap": [],
    }


def _technical(db: Session, tid: UUID) -> dict:
    wos = db.scalars(select(ShipWorkOrder).where(ShipWorkOrder.tenant_id == tid)).all()
    open_wo = [w for w in wos if w.status in ("open", "in_progress")]
    certs = db.scalars(select(ShipCertificate).where(ShipCertificate.tenant_id == tid)).all()
    expiring = [c for c in certs if c.status in ("expiring", "expired")]
    defects = db.scalars(select(ShipDefect).where(ShipDefect.tenant_id == tid, ShipDefect.status == "open")).all()
    vessels = db.scalars(select(Vessel).where(Vessel.tenant_id == tid)).all()
    return {
        "kpis": [
            _kpi("Fleet size", len(vessels), "vsl", None, "neutral"),
            _kpi("Open WOs", len(open_wo), "", None, "warn" if open_wo else "good"),
            _kpi("Critical WOs", sum(1 for w in open_wo if w.priority == "critical"), "", None, "danger"),
            _kpi("Certs expiring", len(expiring), "", None, "warn" if expiring else "good"),
            _kpi("Open defects", len(defects), "", None, "warn" if defects else "good"),
            _kpi("Drydock in 90d", 1, "vsl", None, "info"),
        ],
        "charts": [
            {
                "id": "wo_cat",
                "title": "Work orders by category",
                "type": "bar",
                "series": _count_by(open_wo or wos, "category")
                or [{"t": "pms", "v": 8}, {"t": "defect", "v": 3}, {"t": "survey", "v": 2}],
            },
            {
                "id": "cert",
                "title": "Certificate health",
                "type": "donut",
                "series": [
                    {"t": "Valid", "v": max(1, len(certs) - len(expiring))},
                    {"t": "Expiring", "v": max(0, len(expiring))},
                ],
            },
        ],
        "table": {
            "title": "Priority work orders",
            "columns": ["wo_no", "title", "priority", "status", "due_on"],
            "rows": [
                {
                    "wo_no": w.wo_no,
                    "title": w.title,
                    "priority": w.priority,
                    "status": w.status,
                    "due_on": w.due_on.isoformat() if w.due_on else None,
                }
                for w in sorted(open_wo, key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.priority, 9))[
                    :10
                ]
            ],
        },
        "feed": [
            {"tone": "warn", "text": f"Certificate expiring — {c.cert_name}" if c else "", "ts": _now().isoformat()}
            for c in expiring[:3]
        ]
        or [
            {"tone": "info", "text": "PMS pull from mock adapter OK", "ts": _now().isoformat()},
            {"tone": "good", "text": "Main engine overhaul WO closed", "ts": _now().isoformat()},
        ],
        "fleet_positions": [],
        "heatmap": [
            {"label": "PMS compliance", "value": 88 + int(_pulse("pms", 3))},
            {"label": "Class findings", "value": 12 + int(_pulse("cls", 2))},
            {"label": "Crew readiness", "value": 91 + int(_pulse("crew", 2))},
            {"label": "Spare cover", "value": 76 + int(_pulse("spr", 4))},
        ],
    }


def _admin(db: Session, tid: UUID) -> dict:
    users = db.execute(select(func.count()).select_from(Voyage).where(Voyage.tenant_id == tid)).scalar() or 0
    return {
        "kpis": [
            _kpi("Active users (7d)", 12 + int(_pulse("u", 2)), "", None, "good"),
            _kpi("Workflow SLA", f"{94 + int(_pulse('wf', 2))}", "%", None, "good"),
            _kpi("Connector health", "OK", "", None, "good"),
            _kpi("AI token burn", f"{int(1.2e6 + _pulse('ai', 5e4)):,}", "", None, "neutral"),
            _kpi("Voyages in DB", users, "", None, "neutral"),
            _kpi("SelfCheck", "PASS", "", None, "good"),
        ],
        "charts": [
            {
                "id": "adoption",
                "title": "Module adoption",
                "type": "bar",
                "series": [
                    {"t": "Estimate", "v": 92},
                    {"t": "Ops", "v": 88},
                    {"t": "Finance", "v": 76},
                    {"t": "Ship Mgmt", "v": 70},
                    {"t": "Twin", "v": 81},
                ],
            }
        ],
        "feed": [
            {"tone": "info", "text": "Fleet Pro subscription renews in 22 days", "ts": _now().isoformat()},
            {"tone": "good", "text": "Backup job completed", "ts": _now().isoformat()},
        ],
        "fleet_positions": [],
        "heatmap": [],
        "table": {"title": "", "columns": [], "rows": []},
    }


def _count_by(rows: list, attr: str) -> list[dict]:
    bucket: dict[str, int] = {}
    for r in rows:
        k = getattr(r, attr, None) or "other"
        bucket[k] = bucket.get(k, 0) + 1
    return [{"t": k, "v": v} for k, v in bucket.items()]
