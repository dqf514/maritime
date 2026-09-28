"""索赔路由（D10 分类体系 + D5 性能索赔）。"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module

from app.models_domain import Charter, Claim, Invoice, LaytimeCalc, NoonReport, PortCall, Voyage
from app.models_wave1 import CounterpartyContact
from app.services.claim_taxonomy import CLAIM_TYPES, assert_claim_type
from app.services.doc_numbering import next_doc_number
from app.services.performance_engine import compute_performance
from app.services.recycle import soft_delete
from app.services.tenant_guard import scoped_get

from app.routers._finance_common import _alive, _days_to_timebar, TIMEBAR_DAYS_AFTER_BL

from datetime import timedelta
from app.services.state_machine import CLAIM_TRANSITIONS, transition
from app.services.sanctions import assert_not_sanctioned

router = APIRouter()


# —— Claims ——
class ClaimIn(BaseModel):
    claim_type: str = "demurrage"
    contact_id: UUID | None = None
    voyage_id: UUID | None = None
    laytime_id: UUID | None = None
    amount: float | None = None
    currency: str = "USD"
    time_bar: date | None = None
    notes: str | None = None
    deductions: dict | list | None = None


@router.get("/claims/types")
def list_claim_types(auth: AuthContext = Depends(require_module("claims"))):
    """索赔分类字典（D10）：前端类型选择器数据源。"""
    return {"items": [{"code": code, **meta} for code, meta in CLAIM_TYPES.items()]}


@router.post("/claims")
def create_claim(body: ClaimIn, auth: AuthContext = Depends(require_module("claims")), db: Session = Depends(get_db)):
    assert_claim_type(body.claim_type)
    if body.voyage_id is not None and scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    if body.laytime_id is not None and scoped_get(db, LaytimeCalc, body.laytime_id, auth.tenant_id) is None:
        raise HTTPException(404, "Laytime not found")
    amount = body.amount
    if amount is None and body.laytime_id:
        lt = db.get(LaytimeCalc, body.laytime_id)
        if lt and lt.results:
            amount = float(lt.results.get("amount") or 0)
    time_bar = body.time_bar
    if time_bar is None and body.voyage_id:
        # Infer time bar from the latest B/L date on the voyage's port calls.
        bl_dates = []
        for pc in db.scalars(
            select(PortCall).where(PortCall.tenant_id == auth.tenant_id, PortCall.voyage_id == body.voyage_id)
        ).all():
            bl = getattr(pc, "bl_date", None)
            if isinstance(bl, datetime):
                bl = bl.date()
            if bl:
                bl_dates.append(bl)
        if bl_dates:
            time_bar = max(bl_dates) + timedelta(days=TIMEBAR_DAYS_AFTER_BL)
    if body.contact_id is not None and scoped_get(db, CounterpartyContact, body.contact_id, auth.tenant_id) is None:
        raise HTTPException(404, "Contact not found")
    row = Claim(
        tenant_id=auth.tenant_id,
        claim_no=f"CL-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}",
        claim_type=body.claim_type,
        voyage_id=body.voyage_id,
        laytime_id=body.laytime_id,
        amount=amount,
        currency=body.currency,
        time_bar=time_bar,
        notes=body.notes,
        contact_id=body.contact_id,
    )
    if body.deductions is not None:
        row.deductions = body.deductions
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "claim_no": row.claim_no,
        "claim_type": row.claim_type,
        "status": row.status,
        "amount": float(row.amount or 0),
        "time_bar": row.time_bar.isoformat() if row.time_bar else None,
    }


@router.post("/claims/{claim_id}/transition")
def claim_transition(
    claim_id: UUID,
    target: str,
    settlement_amount: float | None = None,
    auth: AuthContext = Depends(require_module("claims")),
    db: Session = Depends(get_db),
):
    row = db.get(Claim, claim_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Claim not found")
    row.status = transition("claim", row.status, target, CLAIM_TRANSITIONS)
    if target == "settled":
        row.settlement_amount = (
            Decimal(str(settlement_amount)).quantize(Decimal("0.01"))
            if settlement_amount is not None
            else row.amount
        )
    db.commit()
    return {"id": str(row.id), "status": row.status, "settlement_amount": float(row.settlement_amount or 0) if row.settlement_amount is not None else None}


class ClaimUpdate(BaseModel):
    amount: float | None = None
    notes: str | None = None
    claim_type: str | None = None
    deductions: dict | list | None = None
    contact_id: UUID | None = None


@router.patch("/claims/{claim_id}")
def update_claim(
    claim_id: UUID,
    body: ClaimUpdate,
    auth: AuthContext = Depends(require_module("claims")),
    db: Session = Depends(get_db),
):
    row = db.get(Claim, claim_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Claim not found")
    if body.amount is not None:
        row.amount = body.amount
    if body.notes is not None:
        row.notes = body.notes
    if body.claim_type is not None:
        row.claim_type = assert_claim_type(body.claim_type)
    if body.deductions is not None:
        row.deductions = body.deductions
    if body.contact_id is not None:
        if scoped_get(db, CounterpartyContact, body.contact_id, auth.tenant_id) is None:
            raise HTTPException(404, "Contact not found")
        row.contact_id = body.contact_id
    db.commit()
    return {"id": str(row.id), "claim_no": row.claim_no, "status": row.status, "amount": float(row.amount or 0)}


@router.delete("/claims/{claim_id}")
def delete_claim(claim_id: UUID, auth: AuthContext = Depends(require_module("claims")), db: Session = Depends(get_db)):
    row = db.get(Claim, claim_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Claim not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="claim",
        row=row,
        title=row.claim_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/claims")
def list_claims(
    voyage_id: UUID | None = Query(None),
    claim_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("claims")),
    db: Session = Depends(get_db),
):
    q = select(Claim).where(Claim.tenant_id == auth.tenant_id, Claim.status != "deleted")
    if voyage_id is not None:
        q = q.where(Claim.voyage_id == voyage_id)
    if claim_type is not None:
        q = q.where(Claim.claim_type == claim_type)
    rows, total = paginate(db, q.order_by(Claim.claim_no), limit, offset)
    return envelope(
        [
            {
                "id": str(r.id),
                "claim_no": r.claim_no,
                "claim_type": r.claim_type,
                "contact_id": str(r.contact_id) if r.contact_id else None,
                "status": r.status,
                "amount": float(r.amount or 0),
                "voyage_id": str(r.voyage_id) if r.voyage_id else None,
                "time_bar": r.time_bar.isoformat() if r.time_bar else None,
                "days_to_timebar": _days_to_timebar(r.time_bar),
                "settlement_amount": float(r.settlement_amount) if r.settlement_amount is not None else None,
            }
            for r in rows
        ],
        total,
        limit,
        offset,
    )


@router.get("/claims/{claim_id}")
def get_claim(
    claim_id: UUID,
    auth: AuthContext = Depends(require_module("claims")),
    db: Session = Depends(get_db),
):
    """单据详情（U2）：可深链的索赔单条视图。"""
    r = scoped_get(db, Claim, claim_id, auth.tenant_id)
    if r is None:
        raise HTTPException(404, "Claim not found")
    return {
        "id": str(r.id),
        "claim_no": r.claim_no,
        "claim_type": r.claim_type,
        "status": r.status,
        "contact": (
            {"id": str(ct.id), "name": ct.name, "email": ct.email, "phone": ct.phone}
            if (ct := db.get(CounterpartyContact, r.contact_id)) is not None
            else None
        ),
        "amount": float(r.amount or 0),
        "currency": r.currency,
        "voyage_id": str(r.voyage_id) if r.voyage_id else None,
        "laytime_id": str(r.laytime_id) if r.laytime_id else None,
        "time_bar": r.time_bar.isoformat() if r.time_bar else None,
        "days_to_timebar": _days_to_timebar(r.time_bar),
        "settlement_amount": float(r.settlement_amount) if r.settlement_amount is not None else None,
        "notes": r.notes,
    }


@router.get("/voyages/{voyage_id}/performance-claim")
def performance_claim(
    voyage_id: UUID,
    warranty_speed_kn: float = Query(..., gt=0),
    about_kn: float = Query(0.5, ge=0),
    warranty_consumption_mt_day: float = Query(0, ge=0),
    consumption_tolerance_pct: float = Query(0.05, ge=0),
    good_weather_max_wind_bf: float = Query(4, ge=0),
    claim_rate_per_day: float = Query(0, ge=0),
    fuel_price_per_mt: float = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("claims")),
    db: Session = Depends(get_db),
):
    """D5 航速油耗保证索赔：从午报派生好天气评估 + 失速/超耗金额。"""
    if scoped_get(db, Voyage, voyage_id, auth.tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    reports = db.scalars(
        select(NoonReport)
        .where(NoonReport.tenant_id == auth.tenant_id, NoonReport.voyage_id == voyage_id)
        .order_by(NoonReport.report_at)
    ).all()
    days = []
    prev = None
    for r in reports:
        row = {
            "date": r.report_at.date().isoformat(),
            "speed_kn": float(r.speed) if r.speed is not None else 0.0,
            "cons_mt_day": 0.0,
            "wind_bf": float(r.wind_bf) if r.wind_bf is not None else None,
            "sea_state": r.sea_state,
        }
        if prev is not None:
            gap_h = (r.report_at - prev.report_at).total_seconds() / 3600
            rob_prev = float(prev.rob_fo or 0) + float(prev.rob_do or 0)
            rob_now = float(r.rob_fo or 0) + float(r.rob_do or 0)
            if 20 <= gap_h <= 28 and rob_now <= rob_prev:
                row["cons_mt_day"] = round(rob_prev - rob_now, 2)
        days.append(row)
        prev = r
    result = compute_performance(
        {
            "warranty_speed_kn": warranty_speed_kn,
            "about_kn": about_kn,
            "warranty_consumption_mt_day": warranty_consumption_mt_day,
            "consumption_tolerance_pct": consumption_tolerance_pct,
            "good_weather_max_wind_bf": good_weather_max_wind_bf,
            "claim_rate_per_day": claim_rate_per_day,
            "fuel_price_per_mt": fuel_price_per_mt,
            "days": days,
        }
    )
    result["voyage_id"] = str(voyage_id)
    return result


@router.post("/claims/{claim_id}/to-invoice")
def claim_to_invoice(claim_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    """One-click demurrage invoice (draft) from a settled / negotiating claim."""
    row = db.get(Claim, claim_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Claim not found")
    if row.status not in {"settled", "negotiating"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "INVALID_STATE", "message": f"Cannot invoice a claim in status {row.status}"},
        )
    amount = row.settlement_amount if row.settlement_amount is not None else row.amount
    amount = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
    if amount <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "Claim has no positive amount to invoice"})
    counterparty_id = None
    if row.voyage_id:
        voyage = db.get(Voyage, row.voyage_id)
        if voyage and voyage.charter_id:
            charter = db.get(Charter, voyage.charter_id)
            if charter:
                counterparty_id = charter.counterparty_id
    if counterparty_id:
        assert_not_sanctioned(db, auth.tenant_id, counterparty_id)
    inv = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type="demurrage",
        counterparty_id=counterparty_id,
        voyage_id=row.voyage_id,
        amount=amount,
        tax_amount=Decimal("0"),
        currency=row.currency or "USD",
        meta={"claim_id": str(row.id), "claim_no": row.claim_no},
    )
    db.add(inv)
    db.commit()
    return {"id": str(inv.id), "invoice_no": inv.invoice_no, "status": inv.status, "amount": float(inv.amount), "claim_id": str(row.id)}


