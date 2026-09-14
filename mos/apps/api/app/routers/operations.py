"""Operations, PortCall, Twin L1–L2."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import Charter, NoonReport, PortCall, SofEvent, TwinAlert, Voyage
from app.models_wave1 import Port, Vessel
from app.security import AuthContext, require_module
from app.services.recycle import soft_delete
from app.services.tenant_guard import scoped_get
from app.services.state_machine import VOYAGE_TRANSITIONS, transition

router = APIRouter(tags=["Operations"])

# SOF（Statement of Facts）标准事件码表
SOF_EVENT_CODES: dict[str, str] = {
    "NOR": "Notice of Readiness 递交备妥通知书",
    "EOSP": "End of Sea Passage 海上航行结束（抵港）",
    "ANCHOR": "抛锚（抵锚地待泊）",
    "AWSP": "All Fast 缆绳全部带妥（靠妥）",
    "POB": "Pilot on Board 引航员登船",
    "DOCKED": "靠泊就位",
    "SHIFTED_BERTH": "移泊（更换泊位）",
    "COMMENCED": "开始装卸作业",
    "COMPLETED": "装卸作业完成",
    "HOSES_OFF": "拆除输油软管（货油作业收尾）",
    "BL_DATE": "提单签发日期",
    "SAILED": "开航离港",
}

# 现实时序上早于 NOR 的事件（抵港/抛锚/引航员登船/带缆均发生在递交通知书之前），
# 豁免"不得早于 NOR"的下界校验
SOF_PRE_NOR_EXEMPT: frozenset[str] = frozenset({"EOSP", "ANCHOR", "POB", "AWSP"})


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _alive(status: str | None) -> bool:
    return status != "deleted"


class VoyageIn(BaseModel):
    voyage_no: str
    vessel_id: UUID | None = None
    charter_id: UUID | None = None
    cargo: str | None = None


class VoyageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    voyage_no: str
    status: str
    vessel_id: UUID | None
    charter_id: UUID | None
    cargo: str | None


class PortCallIn(BaseModel):
    voyage_id: UUID
    port_id: UUID | None = None
    seq: int = 1
    purpose: str = "load"
    eta: datetime | None = None
    etd: datetime | None = None
    agent: str | None = None
    timezone: str = "UTC"


class PortCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    voyage_id: UUID
    port_id: UUID | None
    seq: int
    purpose: str
    eta: datetime | None
    etd: datetime | None
    ata: datetime | None
    atd: datetime | None
    nor_at: datetime | None
    eosp_at: datetime | None
    bl_date: datetime | None
    agent: str | None
    timezone: str


class NoonIn(BaseModel):
    voyage_id: UUID
    report_at: datetime
    lat: float | None = None
    lon: float | None = None
    speed: float | None = None
    rob_fo: float | None = None
    rob_do: float | None = None
    eta_next: datetime | None = None
    remarks: str | None = None
    wind_bf: float | None = None
    sea_state: str | None = None
    current_kn: float | None = None


class NoonOut(BaseModel):
    id: UUID
    eta_deviation_hours: float | None = None
    wind_bf: float | None = None
    sea_state: str | None = None
    current_kn: float | None = None


class SofIn(BaseModel):
    port_call_id: UUID
    event_code: str
    event_at: datetime
    local_tz: str = "UTC"
    remarks: str | None = None


@router.get("/voyages", response_model=list[VoyageOut])
def list_voyages(auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Voyage)
        .where(Voyage.tenant_id == auth.tenant_id, Voyage.status != "deleted")
        .order_by(Voyage.created_at.desc())
    ).all()
    return [VoyageOut.model_validate(r) for r in rows]


@router.post("/voyages", response_model=VoyageOut)
def create_voyage(body: VoyageIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    if body.vessel_id is not None and scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
        raise HTTPException(404, "Vessel not found")
    if body.charter_id is not None and scoped_get(db, Charter, body.charter_id, auth.tenant_id) is None:
        raise HTTPException(404, "Charter not found")
    row = Voyage(
        tenant_id=auth.tenant_id,
        voyage_no=body.voyage_no,
        vessel_id=body.vessel_id,
        charter_id=body.charter_id,
        cargo=body.cargo,
        status="planned",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return VoyageOut.model_validate(row)


class VoyageUpdate(BaseModel):
    voyage_no: str | None = None
    cargo: str | None = None
    vessel_id: UUID | None = None
    clear_vessel: bool = False


@router.patch("/voyages/{voyage_id}", response_model=VoyageOut)
def update_voyage(
    voyage_id: UUID,
    body: VoyageUpdate,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = db.get(Voyage, voyage_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Voyage not found")
    fields = body.model_fields_set
    if "voyage_no" in fields and body.voyage_no is not None:
        row.voyage_no = body.voyage_no
    if "cargo" in fields:
        row.cargo = body.cargo
    if body.clear_vessel or ("vessel_id" in fields and body.vessel_id is None):
        row.vessel_id = None
    elif body.vessel_id is not None:
        if scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
            raise HTTPException(404, "Vessel not found")
        row.vessel_id = body.vessel_id
    db.commit()
    db.refresh(row)
    return VoyageOut.model_validate(row)


@router.delete("/voyages/{voyage_id}")
def delete_voyage(voyage_id: UUID, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    row = db.get(Voyage, voyage_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Voyage not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="voyage",
        row=row,
        title=row.voyage_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


class VoyageTransition(BaseModel):
    target: str


@router.post("/voyages/{voyage_id}/transition", response_model=VoyageOut)
def voyage_transition(
    voyage_id: UUID,
    body: VoyageTransition,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = db.get(Voyage, voyage_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Voyage not found")
    row.status = transition("voyage", row.status, body.target, VOYAGE_TRANSITIONS)
    now = datetime.now(timezone.utc)
    if body.target == "in_progress":
        row.started_at = now
    if body.target == "completed":
        row.completed_at = now
    db.commit()
    db.refresh(row)
    return VoyageOut.model_validate(row)


@router.post("/port-calls", response_model=PortCallOut)
def create_port_call(body: PortCallIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    v = db.get(Voyage, body.voyage_id)
    if not v or v.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    row = PortCall(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return PortCallOut.model_validate(row)


@router.get("/port-calls", response_model=list[PortCallOut])
def list_port_calls(
    voyage_id: UUID | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    stmt = select(PortCall).where(PortCall.tenant_id == auth.tenant_id)
    if voyage_id:
        stmt = stmt.where(PortCall.voyage_id == voyage_id)
    rows = db.scalars(stmt.order_by(PortCall.seq)).all()
    return [PortCallOut.model_validate(r) for r in rows]


@router.get("/port-calls/{port_call_id}/sof-summary")
def sof_summary(port_call_id: UUID, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    """SOF 标准事件时间线 + 作业/等泊时长，供 laytime from-sof 消费。"""
    pc = db.get(PortCall, port_call_id)
    if not pc or pc.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Port call not found")
    rows = db.scalars(
        select(SofEvent)
        .where(SofEvent.tenant_id == auth.tenant_id, SofEvent.port_call_id == pc.id)
        .order_by(SofEvent.event_at.asc())
    ).all()
    by_code: dict[str, datetime] = {}
    for r in rows:
        by_code.setdefault(r.event_code.upper(), r.event_at)

    def _hours(start: datetime | None, end: datetime | None) -> float | None:
        if start and end:
            return round((_as_utc(end) - _as_utc(start)).total_seconds() / 3600.0, 2)
        return None

    return {
        "port_call_id": str(pc.id),
        "port_id": str(pc.port_id) if pc.port_id else None,
        "timezone": pc.timezone,
        "events": [{"code": r.event_code, "at": r.event_at.isoformat() if r.event_at else None} for r in rows],
        "working_hours": _hours(by_code.get("COMMENCED"), by_code.get("COMPLETED")),
        "waiting_hours": _hours(by_code.get("NOR"), by_code.get("COMMENCED")),
    }


@router.post("/noon-reports", response_model=NoonOut)
def create_noon(body: NoonIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    v = db.get(Voyage, body.voyage_id)
    if not v or v.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    deviation = None
    # ETA deviation vs first port call ETA
    pc = db.scalar(select(PortCall).where(PortCall.voyage_id == v.id).order_by(PortCall.seq).limit(1))
    if pc and pc.eta and body.eta_next:
        eta = pc.eta if pc.eta.tzinfo else pc.eta.replace(tzinfo=timezone.utc)
        eta_next = body.eta_next if body.eta_next.tzinfo else body.eta_next.replace(tzinfo=timezone.utc)
        deviation = Decimal(str((eta_next - eta).total_seconds() / 3600.0))
        if abs(deviation) >= 6:
            db.add(
                TwinAlert(
                    tenant_id=auth.tenant_id,
                    level="warn",
                    title=f"ETA deviation {float(deviation):.1f}h",
                    body=f"Voyage {v.voyage_no} noon ETA drift",
                    href=f"/operations/voyages/{v.id}",
                    vessel_id=v.vessel_id,
                    voyage_id=v.id,
                )
            )
    row = NoonReport(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        report_at=body.report_at,
        lat=body.lat,
        lon=body.lon,
        speed=body.speed,
        rob_fo=body.rob_fo,
        rob_do=body.rob_do,
        eta_next=body.eta_next,
        remarks=body.remarks,
        wind_bf=body.wind_bf,
        sea_state=body.sea_state,
        current_kn=body.current_kn,
        eta_deviation_hours=deviation,
    )
    db.add(row)
    db.commit()
    return NoonOut(
        id=row.id,
        eta_deviation_hours=float(deviation) if deviation is not None else None,
        wind_bf=body.wind_bf,
        sea_state=body.sea_state,
        current_kn=body.current_kn,
    )


@router.post("/sof-events")
def create_sof(body: SofIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    pc = db.get(PortCall, body.port_call_id)
    if not pc or pc.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Port call not found")
    code = body.event_code.upper()
    if code not in SOF_EVENT_CODES:
        raise HTTPException(
            422,
            detail={
                "code": "INVALID_SOF_EVENT_CODE",
                "message": f"Unknown SOF event code '{body.event_code}'",
                "allowed": sorted(SOF_EVENT_CODES),
            },
        )
    existing = db.scalars(select(SofEvent).where(SofEvent.port_call_id == pc.id)).all()
    event_at = _as_utc(body.event_at)
    if code == "NOR":
        # NOR 不得晚于已有最早的非豁免事件（豁免事件本就该早于 NOR）
        non_exempt = [e for e in existing if e.event_code.upper() not in SOF_PRE_NOR_EXEMPT]
        if non_exempt:
            earliest = min(_as_utc(e.event_at) for e in non_exempt)
            if event_at > earliest:
                raise HTTPException(
                    422,
                    detail={"code": "SOF_SEQUENCE_VIOLATION", "message": "NOR must not be later than existing events of this port call"},
                )
    elif code not in SOF_PRE_NOR_EXEMPT:
        # 非豁免事件时间不得早于同 port_call 的 NOR 时间
        nors = [e for e in existing if e.event_code.upper() == "NOR"]
        if nors:
            nor_at = min(_as_utc(e.event_at) for e in nors)
            if event_at < nor_at:
                raise HTTPException(
                    422,
                    detail={"code": "SOF_SEQUENCE_VIOLATION", "message": "Event time must not be earlier than NOR of this port call"},
                )
    row = SofEvent(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    if code == "NOR":
        if not pc.nor_at:
            pc.nor_at = body.event_at
        if not pc.ata:
            pc.ata = body.event_at
    if code == "EOSP" and not pc.eosp_at:
        pc.eosp_at = body.event_at
    if code == "BL_DATE" and not pc.bl_date:
        pc.bl_date = body.event_at
    if code in {"COMPLETED", "SAILED"}:
        pc.atd = body.event_at
    db.commit()
    return {"id": str(row.id), "event_code": row.event_code}


@router.get("/sof-events")
def list_sof_events(
    port_call_id: UUID | None = None,
    voyage_id: UUID | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    q = select(SofEvent).where(SofEvent.tenant_id == auth.tenant_id)
    if port_call_id:
        q = q.where(SofEvent.port_call_id == port_call_id)
    elif voyage_id:
        pc_ids = db.scalars(select(PortCall.id).where(PortCall.tenant_id == auth.tenant_id, PortCall.voyage_id == voyage_id)).all()
        q = q.where(SofEvent.port_call_id.in_(pc_ids or [UUID(int=0)]))
    rows = db.scalars(q.order_by(SofEvent.event_at.asc())).all()
    return [
        {
            "id": str(r.id),
            "port_call_id": str(r.port_call_id),
            "event_code": r.event_code,
            "event_at": r.event_at.isoformat() if r.event_at else None,
            "local_tz": r.local_tz,
            "remarks": r.remarks,
        }
        for r in rows
    ]


@router.get("/twin/fleet")
def twin_fleet(auth: AuthContext = Depends(require_module("twin")), db: Session = Depends(get_db)):
    vessels = db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id)).all()
    voyages = db.scalars(select(Voyage).where(Voyage.tenant_id == auth.tenant_id, Voyage.status == "in_progress")).all()
    by_vessel = {v.vessel_id: v for v in voyages if v.vessel_id}
    points = []
    for ves in vessels:
        voy = by_vessel.get(ves.id)
        noon = None
        if voy:
            noon = db.scalar(
                select(NoonReport).where(NoonReport.voyage_id == voy.id).order_by(NoonReport.report_at.desc()).limit(1)
            )
        points.append(
            {
                "vessel_id": str(ves.id),
                "name": ves.name,
                "imo": ves.imo,
                "voyage_no": voy.voyage_no if voy else None,
                "lat": float(noon.lat) if noon and noon.lat is not None else None,
                "lon": float(noon.lon) if noon and noon.lon is not None else None,
                "status": voy.status if voy else "idle",
            }
        )
    return {"level": "L1", "vessels": points}


@router.get("/twin/voyages/{voyage_id}")
def twin_voyage(voyage_id: UUID, auth: AuthContext = Depends(require_module("twin")), db: Session = Depends(get_db)):
    v = db.get(Voyage, voyage_id)
    if not v or v.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    calls = db.scalars(select(PortCall).where(PortCall.voyage_id == v.id).order_by(PortCall.seq)).all()
    noons = db.scalars(select(NoonReport).where(NoonReport.voyage_id == v.id).order_by(NoonReport.report_at)).all()
    return {
        "level": "L2",
        "voyage": VoyageOut.model_validate(v).model_dump(),
        "port_calls": [PortCallOut.model_validate(c).model_dump() for c in calls],
        "noon_track": [
            {"at": n.report_at.isoformat(), "lat": float(n.lat) if n.lat is not None else None, "lon": float(n.lon) if n.lon is not None else None}
            for n in noons
        ],
    }


@router.get("/twin/alerts")
def twin_alerts(auth: AuthContext = Depends(require_module("twin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(TwinAlert).where(TwinAlert.tenant_id == auth.tenant_id).order_by(TwinAlert.created_at.desc()).limit(50)).all()
    return [
        {"id": str(r.id), "level": r.level, "title": r.title, "body": r.body, "href": r.href, "voyage_id": str(r.voyage_id) if r.voyage_id else None}
        for r in rows
    ]


@router.post("/twin/what-if")
def twin_whatif(
    body: dict,
    auth: AuthContext = Depends(require_module("twin")),
):
    from app.services.estimate_engine import compute_estimate

    _ = auth
    estimate_inputs = body.get("estimate_inputs") or body
    try:
        base = compute_estimate(estimate_inputs)
        faster = dict(estimate_inputs)
        faster["sea_days"] = float(Decimal(str(estimate_inputs.get("sea_days") or 10)) * Decimal("0.9"))
        alt = compute_estimate(faster)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_ESTIMATE_INPUT", "message": str(exc)})
    return {"level": "L4", "base_tce": base["tce"], "faster_tce": alt["tce"], "delta_tce": alt["tce"] - base["tce"]}
