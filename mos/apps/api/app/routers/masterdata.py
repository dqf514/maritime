from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
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
    ExchangeRateIn,
    ExchangeRateOut,
    PortIn,
    PortOut,
    VesselIn,
    VesselOut,
)
from app.security import AuthContext, require_module
from app.services.recycle import soft_delete

router = APIRouter(prefix="/masterdata", tags=["Master Data"])


def _alive(model):
    return model.deleted_at.is_(None)


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Company).where(Company.tenant_id == auth.tenant_id)).all()
    return [CompanyOut(id=r.id, name=r.name, code=r.code, base_currency=r.base_currency, tax_no=r.tax_no, status=r.status) for r in rows]


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
    return CompanyOut(id=row.id, name=row.name, code=row.code, base_currency=row.base_currency, tax_no=row.tax_no, status=row.status)


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
    return VesselOut.model_validate(row, from_attributes=True)


@router.patch("/vessels/{vessel_id}", response_model=VesselOut)
def update_vessel(
    vessel_id: UUID,
    body: VesselIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Vessel, vessel_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at:
        raise HTTPException(404, "Vessel not found")
    for k, v in body.model_dump().items():
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
    body: PortIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_port_admin(auth)
    row = db.get(Port, port_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "Port not found")
    for k, v in body.model_dump().items():
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
    return CounterpartyOut.model_validate(row, from_attributes=True)


@router.patch("/counterparties/{party_id}", response_model=CounterpartyOut)
def update_counterparty(
    party_id: UUID,
    body: CounterpartyIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = db.get(Counterparty, party_id)
    if not row or row.tenant_id != auth.tenant_id or row.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    for k, v in body.model_dump().items():
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
