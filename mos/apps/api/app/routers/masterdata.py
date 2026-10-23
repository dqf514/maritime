from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_wave1 import Company, Counterparty, CounterpartyContact, ExchangeRate, Port, Vessel
from app.schemas_wave1 import (
    CompanyIn,
    CompanyOut,
    CounterpartyContactIn,
    CounterpartyContactOut,
    CounterpartyIn,
    CounterpartyOut,
    CounterpartyUpdate,
    ExchangeRateIn,
    ExchangeRateOut,
    PortIn,
    PortOut,
    PortUpdate,
    VesselIn,
    VesselOut,
    VesselUpdate,
)
from app.security import AuthContext, require_module
from app.services.field_perms import assert_fields_writable, filter_read, get_field_modes
from app.services.optimistic_lock import assert_fresh
from app.services.recycle import soft_delete

router = APIRouter(prefix="/masterdata", tags=["Master Data"])


def _alive(model):
    return model.deleted_at.is_(None)


def _company_out(r: Company) -> CompanyOut:
    return CompanyOut(
        id=r.id, name=r.name, code=r.code, base_currency=r.base_currency, tax_no=r.tax_no, status=r.status
    )


class CompanyPatch(BaseModel):
    name: str | None = None
    code: str | None = None
    base_currency: str | None = None
    tax_no: str | None = None


class ExchangeRatePatch(BaseModel):
    base_currency: str | None = None
    quote_currency: str | None = None
    rate: Decimal | None = None
    rate_date: date | None = None
    source: str | None = None


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Company).where(Company.tenant_id == auth.tenant_id, Company.status != "deleted")
    ).all()
    return [_company_out(r) for r in rows]


@router.post("/companies", response_model=CompanyOut)
def create_company(
    body: CompanyIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = Company(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _company_out(row)


@router.patch("/companies/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: UUID,
    body: CompanyPatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Company, company_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Company not found")
    data = body.model_dump(exclude_unset=True)
    if "code" in data and data["code"] is not None and data["code"] != row.code:
        clash = db.scalars(
            select(Company).where(
                Company.tenant_id == auth.tenant_id,
                Company.code == data["code"],
                Company.id != row.id,
            )
        ).first()
        if clash:
            raise HTTPException(409, detail={"code": "COMPANY_CODE_EXISTS", "message": "Company code already in use"})
    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _company_out(row)


@router.delete("/companies/{company_id}")
def delete_company(
    company_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Company, company_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Company not found")
    soft_delete(db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="company", row=row, title=row.name)
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/vessels", response_model=list[VesselOut])
def list_vessels(
    q: str = "",
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = select(Vessel).where(Vessel.tenant_id == auth.tenant_id, _alive(Vessel))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Vessel.name.ilike(like), Vessel.imo.ilike(like)))
    rows = db.scalars(stmt.order_by(Vessel.name)).all()
    return [VesselOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/vessels", response_model=VesselOut)
def create_vessel(
    body: VesselIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = Vessel(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return VesselOut.model_validate(row, from_attributes=True)


@router.get("/vessels/{vessel_id}", response_model=VesselOut)
def get_vessel(
    vessel_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Vessel, vessel_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at:
        raise HTTPException(404, "Vessel not found")
    modes = get_field_modes(db, auth.tenant_id, "vessel", auth.roles)
    payload = VesselOut.model_validate(row, from_attributes=True).model_dump(mode="json")
    filtered = filter_read(payload, modes)
    # hidden 字段需从 JSON 中消失：绕过 response_model（其会用默认值补齐缺省字段）
    if len(filtered) != len(payload):
        return JSONResponse(content=filtered)
    return VesselOut.model_validate(row, from_attributes=True)


@router.patch("/vessels/{vessel_id}", response_model=VesselOut)
def update_vessel(
    vessel_id: UUID,
    body: VesselUpdate,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Vessel, vessel_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at:
        raise HTTPException(404, "Vessel not found")
    assert_fresh(row, body.expected_updated_at)
    payload_fields = set(body.model_fields_set) - {"expected_updated_at"} or set(body.model_dump().keys())
    assert_fields_writable(db, auth.tenant_id, "vessel", auth.roles, payload_fields)
    # exclude_unset：只写客户端显式提交的字段。全量 model_dump() 会把未提交字段
    # 补成默认值，setattr 就把存量值清成 None —— 字段集扩到 IMOS 规模后尤其危险。
    for k, v in body.model_dump(exclude_unset=True, exclude={"expected_updated_at"}).items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return VesselOut.model_validate(row, from_attributes=True)


@router.delete("/vessels/{vessel_id}")
def delete_vessel(
    vessel_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Vessel, vessel_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at:
        raise HTTPException(404, "Vessel not found")
    soft_delete(db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="vessel", row=row, title=row.name)
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/ports", response_model=list[PortOut])
def list_ports(
    q: str = "",
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = select(Port).where(_alive(Port))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Port.name.ilike(like), Port.unlocode.ilike(like)))
    rows = db.scalars(stmt.order_by(Port.name).limit(100)).all()
    return [PortOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/ports", response_model=PortOut)
def create_port(
    body: PortIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = Port(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return PortOut.model_validate(row, from_attributes=True)


@router.get("/ports/{port_id}", response_model=PortOut)
def get_port(
    port_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = db.get(Port, port_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "Port not found")
    return PortOut.model_validate(row, from_attributes=True)


def _require_port_admin(auth: AuthContext) -> None:
    """Ports are global reference data — only tenant/platform admins may mutate them."""
    if "tenant_admin" not in auth.roles and "platform_admin" not in auth.roles:
        raise HTTPException(
            status_code=403,
            detail={"code": "PORT_READ_ONLY", "message": "Global port reference data requires tenant_admin"},
        )


@router.patch("/ports/{port_id}", response_model=PortOut)
def update_port(
    port_id: UUID,
    body: PortUpdate,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_port_admin(auth)
    row = db.get(Port, port_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "Port not found")
    # exclude_unset —— 同 update_vessel：全量 model_dump() 补默认值会清掉存量值。
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return PortOut.model_validate(row, from_attributes=True)


@router.delete("/ports/{port_id}")
def delete_port(
    port_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_port_admin(auth)
    row = db.get(Port, port_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "Port not found")
    soft_delete(db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="port", row=row, title=row.name)
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/counterparties", response_model=list[CounterpartyOut])
def list_counterparties(
    q: str = "",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = select(Counterparty).where(Counterparty.tenant_id == auth.tenant_id, _alive(Counterparty))
    if q.strip():
        stmt = stmt.where(Counterparty.name.ilike(f"%{q.strip()}%"))
    rows = db.scalars(stmt.order_by(Counterparty.name).offset(offset).limit(limit)).all()
    return [CounterpartyOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/counterparties", response_model=CounterpartyOut)
def create_counterparty(
    body: CounterpartyIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = Counterparty(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return CounterpartyOut.model_validate(row, from_attributes=True)


@router.get("/counterparties/{party_id}", response_model=CounterpartyOut)
def get_counterparty(
    party_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Counterparty, party_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    modes = get_field_modes(db, auth.tenant_id, "counterparty", auth.roles)
    payload = CounterpartyOut.model_validate(row, from_attributes=True).model_dump(mode="json")
    filtered = filter_read(payload, modes)
    if len(filtered) != len(payload):
        return JSONResponse(content=filtered)
    return CounterpartyOut.model_validate(row, from_attributes=True)


@router.patch("/counterparties/{party_id}", response_model=CounterpartyOut)
def update_counterparty(
    party_id: UUID,
    body: CounterpartyUpdate,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Counterparty, party_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    assert_fresh(row, body.expected_updated_at)
    payload_fields = set(body.model_fields_set) - {"expected_updated_at"} or set(body.model_dump().keys())
    assert_fields_writable(db, auth.tenant_id, "counterparty", auth.roles, payload_fields)
    # exclude_unset —— 同 update_vessel，避免未提交字段被默认值清空。
    for k, v in body.model_dump(exclude_unset=True, exclude={"expected_updated_at"}).items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return CounterpartyOut.model_validate(row, from_attributes=True)


@router.delete("/counterparties/{party_id}")
def delete_counterparty(
    party_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Counterparty, party_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="counterparty",
        row=row,
        title=row.name,
    )
    db.commit()
    return {"ok": True, "recycled": True}


# ── Counterparty contacts ─────────────────────────────────────────────


@router.get("/counterparties/{party_id}/contacts", response_model=list[CounterpartyContactOut])
def list_contacts(
    party_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    party = db.get(Counterparty, party_id)
    if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    rows = db.scalars(
        select(CounterpartyContact)
        .where(CounterpartyContact.counterparty_id == party_id, _alive(CounterpartyContact))
        .order_by(CounterpartyContact.is_primary.desc(), CounterpartyContact.name)
    ).all()
    return [CounterpartyContactOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/counterparties/{party_id}/contacts", response_model=CounterpartyContactOut)
def create_contact(
    party_id: UUID,
    body: CounterpartyContactIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    party = db.get(Counterparty, party_id)
    if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    row = CounterpartyContact(tenant_id=auth.tenant_id, counterparty_id=party_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return CounterpartyContactOut.model_validate(row, from_attributes=True)


@router.patch("/counterparties/{party_id}/contacts/{contact_id}", response_model=CounterpartyContactOut)
def update_contact(
    party_id: UUID,
    contact_id: UUID,
    body: CounterpartyContactIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    party = db.get(Counterparty, party_id)
    if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    row = db.get(CounterpartyContact, contact_id)
    if not row or row.counterparty_id != party_id or row.deleted_at:
        raise HTTPException(404, "Contact not found")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return CounterpartyContactOut.model_validate(row, from_attributes=True)


@router.delete("/counterparties/{party_id}/contacts/{contact_id}")
def delete_contact(
    party_id: UUID,
    contact_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    party = db.get(Counterparty, party_id)
    if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    row = db.get(CounterpartyContact, contact_id)
    if not row or row.counterparty_id != party_id or row.deleted_at:
        raise HTTPException(404, "Contact not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="counterparty_contact",
        row=row,
        title=row.name,
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/exchange-rates", response_model=list[ExchangeRateOut])
def list_fx(
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(ExchangeRate)
        .where((ExchangeRate.tenant_id == auth.tenant_id) | (ExchangeRate.tenant_id.is_(None)))
        .order_by(ExchangeRate.rate_date.desc())
        .limit(50)
    ).all()
    return [ExchangeRateOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/exchange-rates", response_model=ExchangeRateOut)
def create_fx(
    body: ExchangeRateIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = ExchangeRate(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return ExchangeRateOut.model_validate(row, from_attributes=True)


def _fx_or_404(db: Session, auth: AuthContext, rate_id: UUID) -> ExchangeRate:
    """Tenant-owned FX rows are editable by the tenant; global (tenant_id NULL) rows need admin."""
    row = db.get(ExchangeRate, rate_id)
    if not row:
        raise HTTPException(404, "Exchange rate not found")
    if row.tenant_id is not None and row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Exchange rate not found")
    if row.tenant_id is None and not ({"tenant_admin", "platform_admin"} & set(auth.roles)):
        raise HTTPException(404, "Exchange rate not found")
    return row


@router.patch("/exchange-rates/{rate_id}", response_model=ExchangeRateOut)
def update_fx(
    rate_id: UUID,
    body: ExchangeRatePatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Correct an FX rate (rate/date/source are the correction surface)."""
    row = _fx_or_404(db, auth, rate_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return ExchangeRateOut.model_validate(row, from_attributes=True)


@router.delete("/exchange-rates/{rate_id}")
def delete_fx(
    rate_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """Hard delete — ExchangeRate has no deleted_at/status column, so soft_delete cannot mark the row."""
    row = _fx_or_404(db, auth, rate_id)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/counterparties/{party_id}/rescreen")
def rescreen_counterparty(
    party_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """D24 制裁重筛：记录一次筛查审计并返回当前判定。"""
    from app.services.counterparty_credit import rescreen

    return rescreen(db, auth.tenant_id, party_id)


@router.get("/counterparties/{party_id}/credit-exposure")
def counterparty_credit_exposure(
    party_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """D24 信用敞口：未结发票 vs 信用限额（RiskLimit scope=counterparty:{id}）。"""
    from app.services.counterparty_credit import credit_exposure

    return credit_exposure(db, auth.tenant_id, party_id)


@router.post("/counterparties/rescreen-all")
def rescreen_all(
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """D24 批量重筛：入后台作业队列逐个重筛（幂等键按天）。"""
    from datetime import date

    from app.services import counterparty_credit  # noqa: F401 — 注册 counterparty.rescreen handler
    from app.services.job_queue import enqueue

    job = enqueue(
        db,
        "counterparty.rescreen",
        {"tenant_id": str(auth.tenant_id)},
        tenant_id=auth.tenant_id,
        idempotency_key=f"cp-rescreen:{auth.tenant_id}:{date.today().isoformat()}",
    )
    return {"job_id": str(job.id), "status": job.status}


@router.get("/counterparty-contacts")
def list_counterparty_contacts(
    q: str = "",
    counterparty_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    """联系人全局检索（跨公司，带公司名）——ContactPicker / 通讯录数据源。"""
    from sqlalchemy import or_

    from app.models_wave1 import CounterpartyContact

    stmt = (
        select(CounterpartyContact, Counterparty.name)
        .join(Counterparty, CounterpartyContact.counterparty_id == Counterparty.id)
        .where(CounterpartyContact.tenant_id == auth.tenant_id, _alive(Counterparty))
    )
    if counterparty_id is not None:
        stmt = stmt.where(CounterpartyContact.counterparty_id == counterparty_id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                CounterpartyContact.name.ilike(like),
                CounterpartyContact.email.ilike(like),
                CounterpartyContact.title.ilike(like),
                CounterpartyContact.department.ilike(like),
                Counterparty.name.ilike(like),
            )
        )
    rows = db.execute(stmt.order_by(CounterpartyContact.name).limit(limit)).all()
    return {
        "items": [
            {
                "id": str(c.id),
                "name": c.name,
                "title": c.title,
                "email": c.email,
                "phone": c.phone,
                "mobile": c.mobile,
                "department": c.department,
                "is_primary": bool(c.is_primary),
                "counterparty_id": str(c.counterparty_id),
                "counterparty_name": party_name,
            }
            for c, party_name in rows
        ]
    }
