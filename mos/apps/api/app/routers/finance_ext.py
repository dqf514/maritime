"""Laytime, Claims, Port Cost, Bunker, Finance, Market, Emissions, Pool, Risk, Portal."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_domain import (
    BunkerOrder,
    Charter,
    Claim,
    DqIssue,
    EmissionRecord,
    Invoice,
    LaytimeCalc,
    MarketQuote,
    NoonReport,
    Payment,
    Pool,
    PoolPeriod,
    PoolVessel,
    PortCall,
    PortDisbursement,
    PortalMessage,
    BerthWindow,
    RiskPosition,
    Document,
    SofEvent,
    Voyage,
    VoyageAccrual,
)
from app.models_finance_ext import BunkerInquiry, CreditNote, OffHireEvent, RiskLimit
from app.models_wave1 import Company, Counterparty, ExchangeRate, Port, Vessel
from app.security import AuthContext, require_module
from app.services import cii as cii_service
from app.services.doc_numbering import next_doc_number
from app.services.laytime_engine import compute_laytime, compute_laytime_statement
from app.services.pnl import PNL_LINE_KEYS, voyage_pnl_rows
from app.services import pnl_engine
from app.services.recycle import soft_delete
from app.services.sanctions import assert_not_sanctioned
from app.services.tenant_guard import scoped_get
from app.services.state_machine import (
    BUNKER_TRANSITIONS,
    CLAIM_TRANSITIONS,
    INVOICE_TRANSITIONS,
    LAYTIME_TRANSITIONS,
    PDA_TRANSITIONS,
    POOL_PERIOD_TRANSITIONS,
    transition,
)

router = APIRouter(tags=["Finance & Claims"])


def _alive(status: str | None) -> bool:
    return status != "deleted"


# New invoice input is restricted to these types; legacy free-text rows stay readable.
INVOICE_TYPES = {
    "freight", "hire", "demurrage", "despatch", "bunker",
    "port_disbursement", "port_da", "tc_hire", "broker_commission",
    "carbon_allowance", "eu_ets", "credit_note", "other",
}

DEFAULT_VAR_LIMIT = 100000.0

TIMEBAR_DAYS_AFTER_BL = 90


def _base_currency(db: Session, tenant_id: UUID) -> str:
    comp = db.scalar(select(Company).where(Company.tenant_id == tenant_id).limit(1))
    return (comp.base_currency if comp and comp.base_currency else "USD")


def _resolve_fx_rate(db: Session, tenant_id: UUID, currency: str, base_ccy: str) -> Decimal | None:
    """Latest tenant (or global) rate converting 1 unit of `currency` into `base_ccy`."""
    if currency == base_ccy:
        return Decimal("1")
    row = db.scalars(
        select(ExchangeRate)
        .where(
            ExchangeRate.base_currency == currency,
            ExchangeRate.quote_currency == base_ccy,
            (ExchangeRate.tenant_id == tenant_id) | (ExchangeRate.tenant_id.is_(None)),
        )
        .order_by(ExchangeRate.rate_date.desc())
        .limit(1)
    ).first()
    return Decimal(str(row.rate)) if row else None


def _days_to_timebar(time_bar: date | None) -> int | None:
    if not time_bar:
        return None
    return (time_bar - date.today()).days


def _credited_amount(db: Session, invoice_id: UUID) -> Decimal:
    notes = db.scalars(
        select(CreditNote).where(CreditNote.invoice_id == invoice_id, CreditNote.status == "issued")
    ).all()
    return sum((Decimal(str(n.amount or 0)) for n in notes), Decimal("0"))


def _as_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# —— Laytime ——
class LaytimeIn(BaseModel):
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    inputs: dict = Field(default_factory=dict)


@router.post("/laytimes")
def create_laytime(body: LaytimeIn, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    if body.voyage_id is not None and scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    if body.port_call_id is not None and scoped_get(db, PortCall, body.port_call_id, auth.tenant_id) is None:
        raise HTTPException(404, "Port call not found")
    row = LaytimeCalc(tenant_id=auth.tenant_id, voyage_id=body.voyage_id, port_call_id=body.port_call_id, inputs=body.inputs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "status": row.status}


@router.post("/laytimes/{laytime_id}/calculate")
def calc_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Laytime not found")
    row.results = compute_laytime(row.inputs or {})
    row.status = transition("laytime", row.status, "calculated", LAYTIME_TRANSITIONS)
    db.commit()
    return {"id": str(row.id), "status": row.status, "results": row.results}


@router.post("/laytimes/{laytime_id}/finalize")
def finalize_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Laytime not found")
    row.status = transition("laytime", row.status, "finalized", LAYTIME_TRANSITIONS)
    row.finalized_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": str(row.id), "status": row.status, "results": row.results}


@router.get("/laytimes")
def list_laytimes(
    voyage_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    q = select(LaytimeCalc).where(LaytimeCalc.tenant_id == auth.tenant_id, LaytimeCalc.status != "deleted")
    if voyage_id is not None:
        q = q.where(LaytimeCalc.voyage_id == voyage_id)
    rows = db.scalars(q).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "port_call_id": str(r.port_call_id) if r.port_call_id else None,
            "status": r.status,
            "inputs": r.inputs or {},
            "results": r.results or {},
        }
        for r in rows
    ]


@router.put("/laytimes/{laytime_id}")
def update_laytime(
    laytime_id: UUID,
    body: LaytimeIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    if row.status == "finalized":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LAYTIME_FINALIZED",
                "message": "Laytime is finalized and locked; create a new revision instead of editing it",
                "status": row.status,
            },
        )
    if body.voyage_id is not None:
        if scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
            raise HTTPException(404, "Voyage not found")
        row.voyage_id = body.voyage_id
    if body.port_call_id is not None:
        if scoped_get(db, PortCall, body.port_call_id, auth.tenant_id) is None:
            raise HTTPException(404, "Port call not found")
        row.port_call_id = body.port_call_id
    row.inputs = body.inputs or row.inputs
    if row.status == "calculated":
        row.status = transition("laytime", "calculated", "draft", LAYTIME_TRANSITIONS)
        row.results = {}
    db.commit()
    return {"id": str(row.id), "status": row.status, "inputs": row.inputs or {}}


@router.delete("/laytimes/{laytime_id}")
def delete_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="laytime",
        row=row,
        title=f"Laytime {str(row.id)[:8]}",
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/laytimes/{laytime_id}/export")
def export_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    """Structured laytime statement (SOF 对照计算书): every event with gross /
    term-excluded / counted hours and the cumulative used time, against the
    allowed time and the settled demurrage/despatch amount."""
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    if not row.inputs:
        raise HTTPException(422, detail={"code": "NO_INPUTS", "message": "Laytime has no inputs to export"})
    statement = compute_laytime_statement(row.inputs)
    return {
        "id": str(row.id),
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "port_call_id": str(row.port_call_id) if row.port_call_id else None,
        "status": row.status,
        "format": "LAYTIME_STATEMENT_v1",
        "finalized_at": row.finalized_at.isoformat() if row.finalized_at else None,
        **statement,
    }


class LaytimeFromSofIn(BaseModel):
    port_call_id: UUID
    allowed_hours: float | None = None
    terms: str | None = None


def _allowed_from_charter(charter: Charter | None, purpose: str) -> Decimal | None:
    """Default allowed hours = charter cargo_qty / load|disch rate (mt/day) * 24."""
    if not charter or not charter.cargo_qty:
        return None
    rate = charter.load_rate_pd if purpose == "load" else charter.disch_rate_pd
    if not rate or Decimal(str(rate)) <= 0:
        return None
    return (Decimal(str(charter.cargo_qty)) / Decimal(str(rate)) * Decimal("24")).quantize(Decimal("0.01"))


@router.post("/laytimes/from-sof")
def laytime_from_sof(body: LaytimeFromSofIn, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    """Build a LaytimeCalc from a port call's Statement of Facts events.

    NOR→COMMENCED becomes the waiting segment and COMMENCED→COMPLETED the
    working segment; both count subject to the charter-party terms (SHINC/SHEX
    weekend/holiday exclusions). Port holidays and timezone come from the Port
    master data. Allowed hours default to charter cargo_qty ÷ load/disch rate.
    """
    pc = db.get(PortCall, body.port_call_id)
    if not pc or pc.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Port call not found")
    sof = db.scalars(
        select(SofEvent).where(SofEvent.port_call_id == pc.id).order_by(SofEvent.event_at.asc())
    ).all()
    by_code: dict[str, list[SofEvent]] = {}
    for ev in sof:
        by_code.setdefault(ev.event_code.upper(), []).append(ev)
    if not by_code.get("COMMENCED") or not by_code.get("COMPLETED"):
        raise HTTPException(
            status_code=422,
            detail={"code": "INSUFFICIENT_SOF", "message": "SOF needs at least COMMENCED and COMPLETED events"},
        )
    commenced = by_code["COMMENCED"][0].event_at
    completed = by_code["COMPLETED"][-1].event_at
    events: list[dict] = []
    if by_code.get("NOR"):
        nor = by_code["NOR"][0].event_at
        if commenced > nor:
            events.append({"start": nor.isoformat(), "end": commenced.isoformat(), "kind": "waiting"})
    events.append({"start": commenced.isoformat(), "end": completed.isoformat(), "kind": "working"})

    voyage = db.get(Voyage, pc.voyage_id)
    charter = db.get(Charter, voyage.charter_id) if voyage and voyage.charter_id else None

    allowed = body.allowed_hours
    if allowed is None:
        derived = _allowed_from_charter(charter, pc.purpose or "load")
        if derived is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ALLOWED_HOURS_REQUIRED",
                    "message": "Cannot derive allowed hours from charter (need cargo_qty and load/disch rate); pass allowed_hours",
                },
            )
        allowed = float(derived)

    port = db.get(Port, pc.port_id) if pc.port_id else None
    inputs: dict = {
        "allowed_hours": allowed,
        "terms": body.terms or (charter.laytime_terms if charter and charter.laytime_terms else "SHINC"),
        "events": events,
    }
    if charter and charter.demurrage_rate:
        inputs["demurrage_rate_per_day"] = float(charter.demurrage_rate)
    if charter and charter.despatch_rate:
        inputs["despatch_rate_per_day"] = float(charter.despatch_rate)
    if port and port.holidays:
        inputs["port_holidays"] = port.holidays
    tz_name = (port.timezone if port else None) or pc.timezone
    if tz_name:
        inputs["port_timezone"] = tz_name

    row = LaytimeCalc(
        tenant_id=auth.tenant_id,
        voyage_id=pc.voyage_id,
        port_call_id=pc.id,
        status="draft",
        inputs=inputs,
    )
    row.results = compute_laytime(inputs)
    row.status = transition("laytime", row.status, "calculated", LAYTIME_TRANSITIONS)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "status": row.status, "inputs": row.inputs, "results": row.results}


# —— Claims ——
class ClaimIn(BaseModel):
    claim_type: str = "demurrage"
    voyage_id: UUID | None = None
    laytime_id: UUID | None = None
    amount: float | None = None
    currency: str = "USD"
    time_bar: date | None = None
    notes: str | None = None
    deductions: dict | list | None = None


@router.post("/claims")
def create_claim(body: ClaimIn, auth: AuthContext = Depends(require_module("claims")), db: Session = Depends(get_db)):
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
    )
    if body.deductions is not None:
        row.deductions = body.deductions
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "claim_no": row.claim_no,
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
        row.claim_type = body.claim_type
    if body.deductions is not None:
        row.deductions = body.deductions
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
    auth: AuthContext = Depends(require_module("claims")),
    db: Session = Depends(get_db),
):
    q = select(Claim).where(Claim.tenant_id == auth.tenant_id, Claim.status != "deleted")
    if voyage_id is not None:
        q = q.where(Claim.voyage_id == voyage_id)
    rows = db.scalars(q).all()
    return [
        {
            "id": str(r.id),
            "claim_no": r.claim_no,
            "status": r.status,
            "amount": float(r.amount or 0),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "time_bar": r.time_bar.isoformat() if r.time_bar else None,
            "days_to_timebar": _days_to_timebar(r.time_bar),
            "settlement_amount": float(r.settlement_amount) if r.settlement_amount is not None else None,
        }
        for r in rows
    ]


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


# —— Port disbursements ——
class PdaIn(BaseModel):
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    pda_amount: float
    currency: str = "USD"
    lines: dict = Field(default_factory=dict)


@router.post("/port-disbursements")
def create_pda(body: PdaIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    row = PortDisbursement(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        port_call_id=body.port_call_id,
        pda_amount=body.pda_amount,
        currency=body.currency,
        lines=body.lines,
        status="draft",
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status, "pda_amount": float(row.pda_amount or 0)}


@router.post("/port-disbursements/{pda_id}/transition")
def pda_transition(
    pda_id: UUID,
    target: str,
    fda_amount: float | None = None,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    row = db.get(PortDisbursement, pda_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "PDA not found")
    row.status = transition("pda/fda", row.status, target, PDA_TRANSITIONS)
    if target == "fda" and fda_amount is not None:
        row.fda_amount = Decimal(str(fda_amount))
        row.variance = Decimal(str(fda_amount)) - Decimal(str(row.pda_amount or 0))
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "pda_amount": float(row.pda_amount or 0),
        "fda_amount": float(row.fda_amount or 0),
        "variance": float(row.variance or 0),
    }


# —— Bunker ——
class BunkerIn(BaseModel):
    vessel_id: UUID | None = None
    voyage_id: UUID | None = None
    grade: str = "VLSFO"
    qty_ordered: float
    unit_price: float | None = None  # required unless index_symbol is given
    rob_before: float | None = None
    counterparty_id: UUID | None = None
    supplier: str | None = None
    index_symbol: str | None = None  # e.g. SIN380 — price = latest quote + differential
    price_differential: float = 0


def _latest_quote(db: Session, tenant_id: UUID, symbol: str) -> MarketQuote | None:
    return db.scalars(
        select(MarketQuote)
        .where(
            MarketQuote.symbol == symbol,
            (MarketQuote.tenant_id == tenant_id) | (MarketQuote.tenant_id.is_(None)),
        )
        .order_by(MarketQuote.quote_date.desc())
        .limit(1)
    ).first()


@router.post("/bunker-orders")
def create_bunker(body: BunkerIn, auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    if body.counterparty_id:
        party = db.get(Counterparty, body.counterparty_id)
        if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
            raise HTTPException(404, "Counterparty not found")
        assert_not_sanctioned(db, auth.tenant_id, party.id)
    if body.vessel_id is not None and scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
        raise HTTPException(404, "Vessel not found")
    if body.voyage_id is not None and scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    index_quote: MarketQuote | None = None
    unit_price = body.unit_price
    if body.index_symbol:
        # Index-linked pricing: unit price = latest market quote + differential (e.g. SIN380+12).
        index_quote = _latest_quote(db, auth.tenant_id, body.index_symbol)
        if index_quote is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "NO_INDEX_QUOTE", "message": f"No market quote available for index '{body.index_symbol}'"},
            )
        unit_price = float(
            (Decimal(str(index_quote.value)) + Decimal(str(body.price_differential))).quantize(Decimal("0.01"))
        )
    if unit_price is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNIT_PRICE_REQUIRED", "message": "unit_price is required unless index_symbol is given"},
        )
    row = BunkerOrder(
        tenant_id=auth.tenant_id,
        order_no=f"BNK-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}",
        vessel_id=body.vessel_id,
        voyage_id=body.voyage_id,
        grade=body.grade,
        qty_ordered=body.qty_ordered,
        unit_price=unit_price,
        rob_before=body.rob_before,
    )
    if body.supplier is not None:
        row.supplier = body.supplier
    db.add(row)
    db.flush()
    pricing_meta: dict | None = None
    if index_quote is not None:
        # Audit trail of the index pricing source (BunkerOrder has no meta column).
        pricing_meta = {
            "source": "index",
            "index_symbol": body.index_symbol,
            "quote_date": index_quote.quote_date.isoformat(),
            "quote_value": float(index_quote.value),
            "price_differential": body.price_differential,
        }
        db.add(
            BunkerInquiry(
                tenant_id=auth.tenant_id,
                order_id=row.id,
                supplier=f"INDEX:{body.index_symbol}",
                quoted_price=Decimal(str(unit_price)),
                status="accepted",
                meta=pricing_meta,
            )
        )
    db.commit()
    return {
        "id": str(row.id),
        "order_no": row.order_no,
        "status": row.status,
        "unit_price": float(row.unit_price or 0),
        "pricing": pricing_meta,
    }


@router.post("/bunker-orders/{order_id}/transition")
def bunker_transition(
    order_id: UUID,
    target: str,
    qty_delivered: float | None = None,
    consumption: float | None = None,
    bdn_qty: float | None = None,
    density_kg_m3: float | None = None,
    sulphur_pct: float | None = None,
    bdn_date: date | None = None,
    supplier: str | None = None,
    barge: str | None = None,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    row = db.get(BunkerOrder, order_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    row.status = transition("bunker_order", row.status, target, BUNKER_TRANSITIONS)
    if bdn_qty is not None and qty_delivered is None:
        qty_delivered = bdn_qty
    if qty_delivered is not None:
        row.qty_delivered = Decimal(str(qty_delivered))
    if consumption is not None:
        row.consumption = Decimal(str(consumption))
    warnings: list[dict] = []
    if target == "delivered":
        before = Decimal(str(row.rob_before or 0))
        delivered = Decimal(str(row.qty_delivered or row.qty_ordered or 0))
        cons = Decimal(str(row.consumption or 0))
        row.rob_after = before + delivered - cons
        if bdn_qty is not None:
            bdn = Decimal(str(bdn_qty))
            ordered = Decimal(str(row.qty_ordered or 0))
            if ordered > 0 and abs(bdn - ordered) / ordered > Decimal("0.02"):
                warnings.append(
                    {
                        "code": "BDN_QTY_DEVIATION",
                        "message": f"BDN qty {float(bdn)} deviates >2% from ordered qty {float(ordered)}",
                    }
                )
            # ROB conservation: rob_after should equal rob_before + BDN qty − consumption (0.5% tolerance)
            expected = before + bdn - cons
            if expected > 0 and abs(Decimal(str(row.rob_after)) - expected) / expected > Decimal("0.005"):
                warnings.append(
                    {
                        "code": "ROB_CONSERVATION",
                        "message": f"rob_after {float(row.rob_after)} != rob_before + bdn_qty − consumption ({float(expected)}) beyond 0.5%",
                    }
                )
    for name, value in (
        ("bdn_qty", bdn_qty),
        ("density_kg_m3", density_kg_m3),
        ("sulphur_pct", sulphur_pct),
        ("bdn_date", bdn_date),
        ("supplier", supplier),
        ("barge", barge),
    ):
        if value is not None:
            setattr(row, name, value)
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "rob_before": float(row.rob_before or 0),
        "rob_after": float(row.rob_after or 0),
        "qty_delivered": float(row.qty_delivered or 0),
        "warnings": warnings,
    }


@router.get("/bunker-orders")
def list_bunker(auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    rows = db.scalars(select(BunkerOrder).where(BunkerOrder.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "order_no": r.order_no,
            "status": r.status,
            "vessel_id": str(r.vessel_id) if r.vessel_id else None,
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "grade": r.grade,
            "qty_ordered": float(r.qty_ordered or 0),
            "qty_delivered": float(r.qty_delivered or 0) if r.qty_delivered is not None else None,
            "unit_price": float(r.unit_price or 0),
            "rob_before": float(r.rob_before or 0) if r.rob_before is not None else None,
            "rob_after": float(r.rob_after or 0) if r.rob_after is not None else None,
            "consumption": float(r.consumption or 0) if r.consumption is not None else None,
            "currency": r.currency,
            "amount": float(r.qty_ordered or 0) * float(r.unit_price or 0),
        }
        for r in rows
    ]


class BunkerUpdate(BaseModel):
    grade: str | None = None
    qty_ordered: float | None = None
    unit_price: float | None = None
    rob_before: float | None = None
    vessel_id: UUID | None = None
    voyage_id: UUID | None = None


@router.patch("/bunker-orders/{order_id}")
def update_bunker(
    order_id: UUID,
    body: BunkerUpdate,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    row = db.get(BunkerOrder, order_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    if body.grade is not None:
        row.grade = body.grade
    if body.qty_ordered is not None:
        row.qty_ordered = body.qty_ordered
    if body.unit_price is not None:
        row.unit_price = body.unit_price
    if body.rob_before is not None:
        row.rob_before = body.rob_before
    if body.vessel_id is not None:
        if scoped_get(db, Vessel, body.vessel_id, auth.tenant_id) is None:
            raise HTTPException(404, "Vessel not found")
        row.vessel_id = body.vessel_id
    if body.voyage_id is not None:
        if scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
            raise HTTPException(404, "Voyage not found")
        row.voyage_id = body.voyage_id
    db.commit()
    return {"id": str(row.id), "order_no": row.order_no, "status": row.status}


class BunkerInquiryIn(BaseModel):
    supplier: str
    quoted_price: float


@router.post("/bunker-orders/{order_id}/inquiries")
def create_bunker_inquiry(
    order_id: UUID,
    body: BunkerInquiryIn,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    order = db.get(BunkerOrder, order_id)
    if not order or order.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    if body.quoted_price <= 0:
        raise HTTPException(422, detail={"code": "INVALID_PRICE", "message": "quoted_price must be > 0"})
    row = BunkerInquiry(
        tenant_id=auth.tenant_id,
        order_id=order.id,
        supplier=body.supplier,
        quoted_price=Decimal(str(body.quoted_price)).quantize(Decimal("0.01")),
        status="quoted",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "order_id": str(order.id), "status": row.status, "quoted_price": float(row.quoted_price)}


@router.get("/bunker-orders/{order_id}/inquiries")
def list_bunker_inquiries(order_id: UUID, auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    """All supplier quotes for a bunker order (含 INDEX: 定价审计行), newest first."""
    order = db.get(BunkerOrder, order_id)
    if not order or order.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    rows = db.scalars(
        select(BunkerInquiry)
        .where(BunkerInquiry.order_id == order.id)
        .order_by(BunkerInquiry.quoted_at.desc())
    ).all()
    return [
        {
            "id": str(r.id),
            "order_id": str(r.order_id),
            "supplier": r.supplier,
            "quoted_price": float(r.quoted_price or 0),
            "status": r.status,
            "quoted_at": r.quoted_at.isoformat() if r.quoted_at else None,
            "meta": r.meta or {},
        }
        for r in rows
    ]


@router.post("/bunker-inquiries/{inquiry_id}/accept")
def accept_bunker_inquiry(
    inquiry_id: UUID,
    auth: AuthContext = Depends(require_module("bunker")),
    db: Session = Depends(get_db),
):
    """Accept one supplier quote: writes price + supplier back to the order and
    rejects the order's remaining quotes."""
    row = db.get(BunkerInquiry, inquiry_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker inquiry not found")
    if row.status != "quoted":
        raise HTTPException(
            status_code=409,
            detail={"code": "INVALID_STATE", "message": f"Cannot accept an inquiry in status {row.status}"},
        )
    order = db.get(BunkerOrder, row.order_id)
    if not order or order.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Bunker order not found")
    row.status = "accepted"
    order.unit_price = row.quoted_price
    if row.supplier:
        order.supplier = row.supplier
    others = db.scalars(
        select(BunkerInquiry).where(
            BunkerInquiry.order_id == order.id,
            BunkerInquiry.id != row.id,
            BunkerInquiry.status == "quoted",
        )
    ).all()
    for other in others:
        other.status = "rejected"
    db.commit()
    return {
        "id": str(row.id),
        "status": row.status,
        "order_id": str(order.id),
        "unit_price": float(order.unit_price or 0),
        "supplier": order.supplier,
    }


@router.get("/voyages/{voyage_id}/bunker-allocation")
def bunker_allocation(voyage_id: UUID, auth: AuthContext = Depends(require_module("bunker")), db: Session = Depends(get_db)):
    """Estimated bunker cost allocation for a voyage.

    简化口径: consumption = sum of positive ROB (FO+DO) drops between
    consecutive noon reports; unit cost = quantity-weighted average price of
    the voyage's delivered bunker orders. Allocation = consumption × weighted
    price. ROB increases (bunkering between reports) are ignored.
    """
    voyage = db.get(Voyage, voyage_id)
    if not voyage or voyage.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Voyage not found")
    noons = db.scalars(
        select(NoonReport)
        .where(NoonReport.tenant_id == auth.tenant_id, NoonReport.voyage_id == voyage.id)
        .order_by(NoonReport.report_at.asc())
    ).all()
    consumption = Decimal("0")
    prev_rob: Decimal | None = None
    for n in noons:
        rob = Decimal(str(n.rob_fo or 0)) + Decimal(str(n.rob_do or 0))
        if prev_rob is not None and rob < prev_rob:
            consumption += prev_rob - rob
        prev_rob = rob
    orders = db.scalars(
        select(BunkerOrder).where(
            BunkerOrder.tenant_id == auth.tenant_id,
            BunkerOrder.voyage_id == voyage.id,
            BunkerOrder.status.in_(["delivered", "closed"]),
        )
    ).all()
    total_qty = Decimal("0")
    total_value = Decimal("0")
    for o in orders:
        qty = Decimal(str(o.qty_delivered or 0))
        if qty > 0:
            total_qty += qty
            total_value += qty * Decimal(str(o.unit_price or 0))
    wavg = (total_value / total_qty).quantize(Decimal("0.01")) if total_qty > 0 else None
    allocated = (consumption * wavg).quantize(Decimal("0.01")) if wavg is not None else None
    return {
        "voyage_id": str(voyage.id),
        "voyage_no": voyage.voyage_no,
        "consumption_mt": float(consumption.quantize(Decimal("0.001"))),
        "weighted_avg_price": float(wavg) if wavg is not None else None,
        "allocated_amount": float(allocated) if allocated is not None else None,
        "currency": "USD",
        "noon_reports": len(noons),
        "delivered_orders": len(orders),
        "basis": "noon ROB(FO+DO) drops x qty-weighted price of delivered bunker orders (simplified)",
    }


@router.get("/port-disbursements")
def list_pda(auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    rows = db.scalars(select(PortDisbursement).where(PortDisbursement.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "port_call_id": str(r.port_call_id) if r.port_call_id else None,
            "status": r.status,
            "pda_amount": float(r.pda_amount or 0),
            "fda_amount": float(r.fda_amount or 0) if r.fda_amount is not None else None,
            "variance": float(r.variance or 0) if r.variance is not None else None,
            "currency": r.currency,
            "lines": r.lines or {},
        }
        for r in rows
    ]


# —— Finance ——
class InvoiceIn(BaseModel):
    invoice_type: str = "freight"
    counterparty_id: UUID | None = None
    voyage_id: UUID | None = None
    amount: float
    tax_amount: float = 0
    currency: str = "USD"
    due_date: date | None = None
    fx_rate: float | None = None
    bill_by: str | None = None
    commission_basis: str | None = None


@router.post("/invoices")
def create_invoice(body: InvoiceIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    if body.invoice_type not in INVOICE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_INVOICE_TYPE", "message": f"invoice_type must be one of {sorted(INVOICE_TYPES)}"},
        )
    if body.counterparty_id:
        party = db.get(Counterparty, body.counterparty_id)
        if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
            raise HTTPException(404, "Counterparty not found")
        assert_not_sanctioned(db, auth.tenant_id, party.id)
    if body.voyage_id:
        voyage = db.get(Voyage, body.voyage_id)
        if not voyage or voyage.tenant_id != auth.tenant_id:
            raise HTTPException(404, "Voyage not found")
    amount = Decimal(str(body.amount)).quantize(Decimal("0.01"))
    tax_amount = Decimal(str(body.tax_amount)).quantize(Decimal("0.01"))
    if amount < 0 or tax_amount < 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "amount/tax_amount must be >= 0"})
    fx_rate = None
    base_amount = None
    if body.fx_rate is not None:
        if body.fx_rate <= 0:
            raise HTTPException(422, detail={"code": "INVALID_FX_RATE", "message": "fx_rate must be > 0"})
        fx_rate = Decimal(str(body.fx_rate))
    else:
        fx_rate = _resolve_fx_rate(db, auth.tenant_id, body.currency, _base_currency(db, auth.tenant_id))
    if fx_rate is not None:
        base_amount = (amount * fx_rate).quantize(Decimal("0.01"))
    row = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type=body.invoice_type,
        counterparty_id=body.counterparty_id,
        voyage_id=body.voyage_id,
        amount=amount,
        tax_amount=tax_amount,
        currency=body.currency,
        due_date=body.due_date,
        bill_by=body.bill_by,
        commission_basis=body.commission_basis,
    )
    if fx_rate is not None:
        row.fx_rate = fx_rate
    if base_amount is not None:
        row.base_amount = base_amount
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "amount": float(row.amount),
        "fx_rate": float(fx_rate) if fx_rate is not None else None,
        "base_amount": float(base_amount) if base_amount is not None else None,
    }


@router.post("/invoices/{invoice_id}/transition")
def invoice_transition(invoice_id: UUID, target: str, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    from app.models_saas import WorkflowDefinition, WorkflowInstance
    from app.services.saas_engine import assert_feature, start_workflow

    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")

    if target in {"pending_approval", "issued"}:
        assert_feature(db, auth.tenant_id, auth.roles, "invoice.issue")

    has_wf = db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.tenant_id == auth.tenant_id,
            WorkflowDefinition.entity_type == "invoice",
            WorkflowDefinition.enabled.is_(True),
        )
    )
    if target == "issued" and has_wf and "tenant_admin" not in auth.roles:
        running = db.scalar(
            select(WorkflowInstance).where(
                WorkflowInstance.tenant_id == auth.tenant_id,
                WorkflowInstance.entity_type == "invoice",
                WorkflowInstance.entity_id == row.id,
                WorkflowInstance.status == "running",
            )
        )
        if running or row.status == "pending_approval":
            raise HTTPException(
                status_code=409,
                detail={"code": "WORKFLOW_REQUIRED", "message": "Invoice must be approved via workflow inbox"},
            )

    if target == "void":
        paid = Decimal(str(row.paid_amount or 0))
        if paid > 0:
            credited = _credited_amount(db, row.id)
            if credited < paid:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "CREDIT_NOTE_REQUIRED",
                        "message": f"Received amount {paid} must be fully credited (红冲) before void; credited so far {credited}",
                        "paid_amount": float(paid),
                        "credited_amount": float(credited),
                    },
                )

    row.status = transition("invoice", row.status, target, INVOICE_TRANSITIONS)
    if target == "pending_approval" and has_wf:
        start_workflow(db, tenant_id=auth.tenant_id, entity_type="invoice", entity_id=row.id, started_by=auth.user_id)
    if target == "issued":
        row.issued_at = datetime.now().astimezone()
    db.commit()
    return {"id": str(row.id), "status": row.status}


class InvoiceUpdate(BaseModel):
    amount: float | None = None
    tax_amount: float | None = None
    due_date: date | None = None
    invoice_type: str | None = None
    bill_by: str | None = None
    commission_basis: str | None = None


@router.patch("/invoices/{invoice_id}")
def update_invoice(
    invoice_id: UUID,
    body: InvoiceUpdate,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")
    if body.invoice_type is not None and body.invoice_type not in INVOICE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_INVOICE_TYPE", "message": f"invoice_type must be one of {sorted(INVOICE_TYPES)}"},
        )
    locked = row.status in {"issued", "partially_paid", "paid"} or row.gl_posted
    requested = {
        f
        for f in ("amount", "tax_amount", "due_date", "invoice_type")
        if f in body.model_fields_set and getattr(body, f) is not None
    }
    if locked and requested:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVOICE_LOCKED",
                "message": f"Cannot modify {sorted(requested)} on invoice in status {row.status}"
                + (" (GL posted)" if row.gl_posted else ""),
                "fields": sorted(requested),
                "status": row.status,
            },
        )
    new_amount = Decimal(str(row.amount))
    new_tax = Decimal(str(row.tax_amount or 0))
    if body.amount is not None:
        new_amount = Decimal(str(body.amount)).quantize(Decimal("0.01"))
    if body.tax_amount is not None:
        new_tax = Decimal(str(body.tax_amount)).quantize(Decimal("0.01"))
    if new_amount < 0 or new_tax < 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "amount/tax_amount must be >= 0"})
    paid = Decimal(str(row.paid_amount or 0))
    if new_amount + new_tax < paid:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AMOUNT_BELOW_PAID",
                "message": f"New total {new_amount + new_tax} is below already paid amount {paid}",
                "paid_amount": float(paid),
            },
        )
    if body.amount is not None:
        row.amount = new_amount
    if body.tax_amount is not None:
        row.tax_amount = new_tax
    if body.due_date is not None:
        row.due_date = body.due_date
    if body.invoice_type is not None:
        row.invoice_type = body.invoice_type
    if body.bill_by is not None:
        row.bill_by = body.bill_by
    if body.commission_basis is not None:
        row.commission_basis = body.commission_basis
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "amount": float(row.amount),
    }


class CreditNoteIn(BaseModel):
    amount: float
    reason: str | None = None


@router.post("/invoices/{invoice_id}/credit-note")
def create_credit_note(
    invoice_id: UUID,
    body: CreditNoteIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """红冲: issue a credit note against an invoice (capped at the un-credited balance)."""
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    amt = Decimal(str(body.amount)).quantize(Decimal("0.01"))
    if amt <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "Credit note amount must be > 0"})
    total = Decimal(str(inv.amount)) + Decimal(str(inv.tax_amount or 0))
    credited = _credited_amount(db, inv.id)
    balance = total - credited
    if amt > balance:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CREDIT_EXCEEDS_BALANCE",
                "message": f"Credit note {amt} exceeds un-credited balance {balance}",
                "balance": float(balance),
            },
        )
    row = CreditNote(
        tenant_id=auth.tenant_id,
        invoice_id=inv.id,
        credit_note_no=next_doc_number(db, auth.tenant_id, CreditNote, CreditNote.credit_note_no, "CN"),
        amount=amt,
        reason=body.reason,
        status="issued",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "credit_note_no": row.credit_note_no, "amount": float(row.amount), "status": row.status}


@router.get("/invoices/{invoice_id}/credit-notes")
def list_credit_notes(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Invoice not found")
    rows = db.scalars(
        select(CreditNote).where(CreditNote.invoice_id == inv.id).order_by(CreditNote.credit_note_no)
    ).all()
    return [
        {
            "id": str(r.id),
            "credit_note_no": r.credit_note_no,
            "amount": float(r.amount or 0),
            "reason": r.reason,
            "status": r.status,
            "issued_at": r.issued_at.isoformat() if r.issued_at else None,
        }
        for r in rows
    ]


class HireScheduleIn(BaseModel):
    charter_id: UUID
    period_start: date
    period_end: date


@router.post("/invoices/hire-schedule")
def hire_schedule(body: HireScheduleIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    """Generate a draft hire invoice for a time-charter period, net of off-hire and address commission."""
    ch = db.get(Charter, body.charter_id)
    if not ch or ch.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Charter not found")
    hire_per_day = getattr(ch, "hire_per_day", None)
    if not hire_per_day:
        raise HTTPException(422, detail={"code": "NO_HIRE_RATE", "message": "Charter has no hire_per_day rate"})
    if body.period_end <= body.period_start:
        raise HTTPException(422, detail={"code": "INVALID_PERIOD", "message": "period_end must be after period_start"})
    ps = datetime.combine(body.period_start, time.min)
    pe = datetime.combine(body.period_end, time.min)
    gross_days = (pe - ps).total_seconds() / 86400
    offhire_days = 0.0
    for ev in db.scalars(
        select(OffHireEvent).where(
            OffHireEvent.tenant_id == auth.tenant_id,
            OffHireEvent.charter_id == ch.id,
            OffHireEvent.deduct_hire.is_(True),
        )
    ).all():
        if ev.end_at is None:
            continue
        s = max(_as_utc_naive(ev.start_at), ps)
        e = min(_as_utc_naive(ev.end_at), pe)
        if e > s:
            offhire_days += (e - s).total_seconds() / 86400
    offhire_days = min(offhire_days, gross_days)
    billable_days = gross_days - offhire_days
    rate = Decimal(str(hire_per_day))
    gross_amount = (rate * Decimal(str(billable_days))).quantize(Decimal("0.01"))
    comm_pct = Decimal(str(getattr(ch, "address_comm_pct", None) or 0))
    comm_amount = (gross_amount * comm_pct / Decimal("100")).quantize(Decimal("0.01"))
    net_amount = gross_amount - comm_amount
    meta = {
        "hire": {
            "charter_id": str(ch.id),
            "period_start": body.period_start.isoformat(),
            "period_end": body.period_end.isoformat(),
            "gross_days": round(gross_days, 4),
            "offhire_days": round(offhire_days, 4),
            "billable_days": round(billable_days, 4),
            "hire_per_day": float(rate),
            "gross_amount": float(gross_amount),
            "address_comm_pct": float(comm_pct),
            "address_comm_amount": float(comm_amount),
        }
    }
    if ch.counterparty_id:
        assert_not_sanctioned(db, auth.tenant_id, ch.counterparty_id)
    row = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type="hire",
        counterparty_id=ch.counterparty_id,
        amount=net_amount,
        tax_amount=Decimal("0"),
        currency="USD",
        meta=meta,
    )
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "invoice_type": row.invoice_type,
        "amount": float(row.amount),
        "meta": row.meta,
    }


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="invoice",
        row=row,
        title=row.invoice_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


# fix payment status assignment
@router.post("/invoices/{invoice_id}/payments")
def add_payment(
    invoice_id: UUID,
    amount: float,
    reference: str | None = None,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    from app.services.saas_engine import assert_feature

    assert_feature(db, auth.tenant_id, auth.roles, "invoice.collect")
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    if inv.counterparty_id:
        assert_not_sanctioned(db, auth.tenant_id, inv.counterparty_id)
    if inv.status not in {"issued", "partially_paid"}:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot pay invoice in status {inv.status}"})
    amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amt <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "Payment amount must be > 0"})
    total = Decimal(str(inv.amount)) + Decimal(str(inv.tax_amount or 0))
    already_paid = Decimal(str(inv.paid_amount or 0))
    open_balance = total - already_paid
    if amt > open_balance:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "OVERPAYMENT",
                "message": f"Payment {amt} exceeds open balance {open_balance}",
                "open_balance": float(open_balance),
            },
        )
    pay = Payment(tenant_id=auth.tenant_id, invoice_id=inv.id, amount=amt, currency=inv.currency, reference=reference)
    db.add(pay)
    inv.paid_amount = already_paid + amt
    if inv.paid_amount >= total:
        inv.status = transition("invoice", inv.status, "paid", INVOICE_TRANSITIONS)
    elif inv.status == "issued":
        inv.status = transition("invoice", "issued", "partially_paid", INVOICE_TRANSITIONS)
    db.commit()
    return {"invoice_id": str(inv.id), "status": inv.status, "paid_amount": float(inv.paid_amount)}

@router.get("/invoices/{invoice_id}/payments")
def list_payments(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Invoice not found")
    rows = (
        db.query(Payment)
        .filter(Payment.invoice_id == inv.id, Payment.tenant_id == auth.tenant_id)
        .order_by(Payment.paid_at.asc())
        .all()
    )
    return [
        {
            "id": str(p.id),
            "amount": float(p.amount),
            "currency": p.currency,
            "reference": p.reference,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "is_void_reversal": bool(p.reference and p.reference.startswith("VOID:")),
        }
        for p in rows
    ]


@router.post("/invoices/{invoice_id}/gl-post")
def gl_post(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Invoice not found")
    if inv.status not in {"issued", "partially_paid", "paid"}:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": "Invoice not issuable for GL"})
    inv.gl_posted = True
    inv.meta = {**(inv.meta or {}), "gl_posted_at": datetime.now(timezone.utc).isoformat()}
    db.commit()
    return {"id": str(inv.id), "gl_posted": True}


@router.post("/payments/{payment_id}/void")
def void_payment(payment_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    """付款冲正: reverse a payment and write the invoice paid_amount / status back.

    折中方案: Payment 模型定义在 models_domain.py(本任务不可改),无法新增
    voided_at 列,因此保留原 payment 记录,另写一条金额为负的反向 payment,
    以 reference = "VOID:<原 payment id>" 作为冲正关联与幂等标记。
    """
    pay = db.get(Payment, payment_id)
    if not pay or pay.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Payment not found")
    if Decimal(str(pay.amount)) <= 0 or (pay.reference or "").startswith("VOID:"):
        raise HTTPException(409, detail={"code": "INVALID_PAYMENT", "message": "Cannot void a reversal entry"})
    inv = db.get(Invoice, pay.invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    if inv.gl_posted:
        raise HTTPException(
            status_code=409,
            detail={"code": "GL_POSTED", "message": "Invoice is GL posted; voiding its payments is forbidden"},
        )
    if inv.status not in {"issued", "partially_paid", "paid"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "INVALID_STATE", "message": f"Cannot void a payment on invoice in status {inv.status}"},
        )
    void_ref = f"VOID:{pay.id}"
    existing = db.scalar(select(Payment).where(Payment.invoice_id == inv.id, Payment.reference == void_ref))
    if existing:
        raise HTTPException(409, detail={"code": "ALREADY_VOIDED", "message": "Payment is already voided"})
    reverse = Payment(
        tenant_id=auth.tenant_id,
        invoice_id=inv.id,
        amount=-Decimal(str(pay.amount)),
        currency=pay.currency,
        reference=void_ref,
    )
    db.add(reverse)
    db.flush()
    total_paid = sum(
        (Decimal(str(p.amount)) for p in db.scalars(select(Payment).where(Payment.invoice_id == inv.id)).all()),
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    inv.paid_amount = total_paid
    total = Decimal(str(inv.amount)) + Decimal(str(inv.tax_amount or 0))
    target = "paid" if total_paid >= total else "partially_paid" if total_paid > 0 else "issued"
    if target != inv.status:
        # Reversal goes backwards through the machine; hop paid → partially_paid first
        # when the payment void reopens a fully paid invoice to zero received.
        if inv.status == "paid" and target == "issued":
            inv.status = transition("invoice", inv.status, "partially_paid", INVOICE_TRANSITIONS)
        inv.status = transition("invoice", inv.status, target, INVOICE_TRANSITIONS)
    db.commit()
    return {
        "payment_id": str(pay.id),
        "reversal_id": str(reverse.id),
        "invoice_id": str(inv.id),
        "status": inv.status,
        "paid_amount": float(inv.paid_amount),
    }


@router.get("/invoices")
def list_invoices(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    voyage_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    q = select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.status != "deleted")
    if voyage_id is not None:
        q = q.where(Invoice.voyage_id == voyage_id)
    rows = db.scalars(
        q.order_by(Invoice.invoice_no)
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": str(r.id),
            "invoice_no": r.invoice_no,
            "invoice_type": r.invoice_type,
            "status": r.status,
            "amount": float(r.amount),
            "paid_amount": float(r.paid_amount or 0),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "counterparty_id": str(r.counterparty_id) if r.counterparty_id else None,
            "currency": r.currency,
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "gl_posted": bool(r.gl_posted),
            "mirror_of_id": str(r.mirror_of_id) if r.mirror_of_id else None,
            "bill_by": r.bill_by,
            "commission_basis": r.commission_basis,
        }
        for r in rows
    ]


@router.get("/finance/aging")
def aging(auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.status.in_(["issued", "partially_paid"]))).all()
    return [
        {
            "invoice_no": r.invoice_no,
            "open_amount": float(Decimal(str(r.amount)) + Decimal(str(r.tax_amount or 0)) - Decimal(str(r.paid_amount or 0))),
            "due_date": r.due_date.isoformat() if r.due_date else None,
        }
        for r in rows
    ]


class AccrualIn(BaseModel):
    voyage_id: UUID | None = None
    period_ym: str
    line_type: str = "freight"
    amount: float
    currency: str = "USD"
    notes: str | None = None


@router.get("/finance/accruals")
def list_accruals(auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    rows = db.scalars(select(VoyageAccrual).where(VoyageAccrual.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "period_ym": r.period_ym,
            "line_type": r.line_type,
            "amount": float(r.amount or 0),
            "currency": r.currency,
            "status": r.status,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/finance/accruals")
def create_accrual(body: AccrualIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = VoyageAccrual(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        period_ym=body.period_ym,
        line_type=body.line_type,
        amount=body.amount,
        currency=body.currency,
        notes=body.notes,
        status="draft",
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/finance/accruals/{accrual_id}/post")
def post_accrual(accrual_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = db.get(VoyageAccrual, accrual_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Accrual not found")
    if row.status != "draft":
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot post from {row.status}"})
    row.status = "posted"
    db.commit()
    return {"id": str(row.id), "status": row.status}


# —— Market / DQ / Emissions / Analytics ——
@router.post("/market/quotes")
def add_quote(symbol: str, value: float, quote_date: date | None = None, auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    qd = quote_date or date.today()
    row = db.scalar(
        select(MarketQuote).where(
            MarketQuote.tenant_id == auth.tenant_id,
            MarketQuote.symbol == symbol,
            MarketQuote.quote_date == qd,
        )
    )
    if row:
        row.value = value
        row.source = "manual"
    else:
        row = MarketQuote(tenant_id=auth.tenant_id, symbol=symbol, value=value, quote_date=qd, source="manual")
        db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "symbol": symbol, "value": float(row.value), "quote_date": qd.isoformat()}


@router.get("/market/quotes")
def list_quotes(auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    rows = db.scalars(select(MarketQuote).where(MarketQuote.tenant_id == auth.tenant_id)).all()
    return [{"symbol": r.symbol, "value": float(r.value), "quote_date": r.quote_date.isoformat()} for r in rows]


@router.post("/dq/issues")
def create_dq(rule_code: str, entity_type: str, entity_id: str, message: str, auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    row = DqIssue(tenant_id=auth.tenant_id, rule_code=rule_code, entity_type=entity_type, entity_id=entity_id, message=message)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.get("/dq/issues")
def list_dq(
    status: str | None = Query(None),
    auth: AuthContext = Depends(require_module("analytics")),
    db: Session = Depends(get_db),
):
    q = select(DqIssue).where(DqIssue.tenant_id == auth.tenant_id)
    if status:
        q = q.where(DqIssue.status == status)
    rows = db.scalars(q).all()
    return [
        {
            "id": str(r.id),
            "rule_code": r.rule_code,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "severity": r.severity,
            "message": r.message,
            "status": r.status,
        }
        for r in rows
    ]


def _eeoi(co2_mt: float, cargo_mt: float | None, distance_nm: float | None) -> float | None:
    """EEOI (Energy Efficiency Operational Indicator) 口径: CO2 排放量(吨) ÷
    (货量 cargo_mt × 航程 distance_nm),单位 吨CO2/吨海里。
    每次按入参即时计算,不落库(EmissionRecord 无对应列,不在本任务范围)。"""
    if not cargo_mt or not distance_nm or cargo_mt <= 0 or distance_nm <= 0 or co2_mt <= 0:
        return None
    return co2_mt / (cargo_mt * distance_nm)


@router.post("/emissions")
def create_emission(
    voyage_id: UUID | None = None,
    vessel_id: UUID | None = None,
    fo_mt: float = 0,
    do_mt: float = 0,
    distance_nm: float | None = None,
    cargo_mt: float | None = None,  # 货量(吨);与 distance_nm 同时给出时响应带 eeoi
    dwt: float | None = None,
    ship_type: str = "bulk_carrier",
    year: int | None = None,
    auth: AuthContext = Depends(require_module("emissions")),
    db: Session = Depends(get_db),
):
    co2 = fo_mt * 3.114 + do_mt * 3.206
    extra: dict = {}
    eeoi = _eeoi(co2, cargo_mt, distance_nm)
    if eeoi is not None:
        extra["eeoi"] = eeoi
    if distance_nm and dwt and co2 > 0:
        res = cii_service.rate_cii(co2_mt=co2, dwt=dwt, distance_nm=distance_nm, year=year or date.today().year, ship_type=ship_type)
        cii = res["rating"]
        extra = {"attained_cii": res["attained_cii"], "required_cii": res["required_cii"], "cii_year": res["year"]}
    else:
        cii = "C" if co2 > 1000 else "B" if co2 > 500 else "A"
    row = EmissionRecord(tenant_id=auth.tenant_id, voyage_id=voyage_id, vessel_id=vessel_id, fo_mt=fo_mt, do_mt=do_mt, co2_mt=co2, cii_rating=cii)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "co2_mt": co2, "cii_rating": cii, **extra}


@router.get("/emissions")
def list_emissions(auth: AuthContext = Depends(require_module("emissions")), db: Session = Depends(get_db)):
    rows = db.scalars(select(EmissionRecord).where(EmissionRecord.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "vessel_id": str(r.vessel_id) if r.vessel_id else None,
            "fo_mt": float(r.fo_mt or 0),
            "do_mt": float(r.do_mt or 0),
            "co2_mt": float(r.co2_mt or 0),
            "cii_rating": r.cii_rating,
            "period": r.period,
        }
        for r in rows
    ]


class FuelEuIn(BaseModel):
    voyage_id: UUID | None = None
    vessel_id: UUID | None = None
    fo_mt: float = 0
    do_mt: float = 0
    lng_mt: float = 0
    distance_nm: float = 0
    cargo_mt: float = 0
    dwt: float = 0
    ship_type: str = "bulk_carrier"
    eu_share: float | None = None  # fraction of voyage in EU scope; auto-inferred from port calls when omitted
    ets_price_eur: float = 70.0
    fueleu_penalty_eur_per_tco2e: float = 2400.0


def _infer_eu_share(db: Session, tenant_id: UUID, voyage_id: UUID) -> float | None:
    """EU scope share from the voyage's port-call sequence (简化口径: unweighted
    leg average): EU↔EU leg = 1.0, EU↔non-EU = 0.5, non-EU↔non-EU = 0.0."""
    pcs = db.scalars(
        select(PortCall)
        .where(PortCall.tenant_id == tenant_id, PortCall.voyage_id == voyage_id)
        .order_by(PortCall.seq.asc())
    ).all()
    flags = []
    for pc in pcs:
        port = db.get(Port, pc.port_id) if pc.port_id else None
        flags.append(bool(port and port.is_eu))
    if len(flags) < 2:
        return None
    legs = [1.0 if a and b else 0.5 if a or b else 0.0 for a, b in zip(flags, flags[1:])]
    return sum(legs) / len(legs)


@router.post("/emissions/fueleu-calc")
def fueleu_calc(body: FuelEuIn, auth: AuthContext = Depends(require_module("emissions")), db: Session = Depends(get_db)):
    """FuelEU / EU ETS style calculator — persists EmissionRecord + returns compliance snapshot."""
    eu_share = body.eu_share
    eu_share_source = "manual"
    if eu_share is None:
        inferred = _infer_eu_share(db, auth.tenant_id, body.voyage_id) if body.voyage_id else None
        eu_share = inferred if inferred is not None else 1.0
        eu_share_source = "auto" if inferred is not None else "default"
    # ETS cost bearer is a commercial hint only — it does not change the amounts.
    borne_by = "owner"
    if body.voyage_id:
        voyage = db.get(Voyage, body.voyage_id)
        charter = db.get(Charter, voyage.charter_id) if voyage and voyage.charter_id else None
        if charter and charter.ets_responsibility == "charterer":
            borne_by = "charterer"
    # Simplified GHG intensity (gCO2e/MJ) vs FuelEU target trajectory
    energy_mj = body.fo_mt * 42700 + body.do_mt * 42700 + body.lng_mt * 48000  # approx LHV MJ/t
    co2e_t = body.fo_mt * 3.114 + body.do_mt * 3.206 + body.lng_mt * 2.75
    intensity = (co2e_t * 1_000_000 / energy_mj) if energy_mj > 0 else 0.0
    target_2025 = 89.34  # illustrative FuelEU reference gCO2e/MJ
    compliance_balance_t = max(0.0, (intensity - target_2025) / 1_000_000 * energy_mj) * eu_share
    ets_allowances = co2e_t * eu_share
    ets_cost = ets_allowances * body.ets_price_eur
    fueleu_penalty = compliance_balance_t * body.fueleu_penalty_eur_per_tco2e
    extra: dict = {}
    if body.dwt > 0 and body.distance_nm > 0 and co2e_t > 0:
        res = cii_service.rate_cii(co2_mt=co2e_t, dwt=body.dwt, distance_nm=body.distance_nm, year=date.today().year, ship_type=body.ship_type)
        cii = res["rating"]
        extra = {"attained_cii": res["attained_cii"], "required_cii": res["required_cii"]}
    else:
        cii = "C" if co2e_t > 1000 else "B" if co2e_t > 500 else "A"
    eeoi = _eeoi(co2e_t, body.cargo_mt or None, body.distance_nm or None)
    if eeoi is not None:
        extra["eeoi"] = eeoi
    row = EmissionRecord(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        vessel_id=body.vessel_id,
        fo_mt=body.fo_mt,
        do_mt=body.do_mt,
        co2_mt=co2e_t,
        cii_rating=cii,
        period="fueleu",
    )
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "co2e_t": round(co2e_t, 3),
        "ghg_intensity": round(intensity, 4),
        "target_intensity": target_2025,
        "compliance_balance_t": round(compliance_balance_t, 4),
        "ets_allowances_t": round(ets_allowances, 3),
        "ets_cost_eur": round(ets_cost, 2),
        "fueleu_penalty_eur": round(fueleu_penalty, 2),
        "total_compliance_cost_eur": round(ets_cost + fueleu_penalty, 2),
        "cii_rating": cii,
        "eu_share": round(eu_share, 4),
        "eu_share_source": eu_share_source,
        "borne_by": borne_by,
        "format": "FuelEU_EU_ETS_v1",
        **extra,
    }


@router.get("/emissions/export")
def export_emissions(auth: AuthContext = Depends(require_module("emissions")), db: Session = Depends(get_db)):
    rows = db.scalars(select(EmissionRecord).where(EmissionRecord.tenant_id == auth.tenant_id)).all()
    return {
        "format": "EU_ETS_FuelEU_v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "rows": [
            {
                "voyage_id": str(r.voyage_id) if r.voyage_id else None,
                "vessel_id": str(r.vessel_id) if r.vessel_id else None,
                "fo_mt": float(r.fo_mt or 0),
                "do_mt": float(r.do_mt or 0),
                "co2_mt": float(r.co2_mt or 0),
                "cii": r.cii_rating,
                "period": r.period,
            }
            for r in rows
        ],
    }


@router.get("/analytics/reports/tce")
def report_tce(auth: AuthContext = Depends(require_module("analytics")), db: Session = Depends(get_db)):
    from app.models_domain import Estimate

    rows = db.scalars(select(Estimate).where(Estimate.tenant_id == auth.tenant_id, Estimate.status.in_(["calculated", "converted"]))).all()
    return [{"title": r.title, "tce": (r.results or {}).get("tce"), "id": str(r.id)} for r in rows]


# P&L aggregation lives in app.services.pnl (shared with the exception centre
# and the voyage 360 overview); PNL_LINE_KEYS re-exported for existing imports.


@router.get("/analytics/reports/voyage-pnl")
def report_pnl(
    basis: str = Query("actual", pattern="^(actual|accrual)$"),
    auth: AuthContext = Depends(require_module("analytics")),
    db: Session = Depends(get_db),
):
    """Dynamic voyage P&L: estimate vs actual revenue/cost drivers.

    basis=actual (default): booked invoices / PDAs / bunker orders.
    basis=accrual: additionally merges non-reversed VoyageAccrual rows into the
    line items (`lines_accrual`, `lines` merged, `accrual_net`, `accrual_pnl`).
    Legacy aggregate keys (actual_revenue/actual_cost/...) are unchanged.
    """
    return voyage_pnl_rows(db, auth.tenant_id, basis)


@router.get("/analytics/reports/pnl-4col")
def report_pnl_4col(
    voyage_id: str | None = Query(None),
    auth: AuthContext = Depends(require_module("analytics")),
    db: Session = Depends(get_db),
):
    """4-column P&L: estimate | actual | posted | variance per voyage."""
    vid = UUID(voyage_id) if voyage_id else None
    return pnl_engine.voyage_pnl_4col(db, auth.tenant_id, vid)


@router.get("/analytics/reports/pnl-fleet")
def report_pnl_fleet(
    auth: AuthContext = Depends(require_module("analytics")),
    db: Session = Depends(get_db),
):
    """Fleet-wide 4-column P&L summary."""
    return pnl_engine.fleet_pnl_summary(db, auth.tenant_id)


# —— Pooling / Risk / Berth / Portal / Docs ——
@router.get("/pools")
def list_pools(auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Pool).where(Pool.tenant_id == auth.tenant_id)).all()
    out = []
    for r in rows:
        vessels = db.scalars(select(PoolVessel).where(PoolVessel.pool_id == r.id, PoolVessel.left_on.is_(None))).all()
        periods = db.scalars(select(PoolPeriod).where(PoolPeriod.pool_id == r.id)).all()
        out.append(
            {
                "id": str(r.id),
                "name": r.name,
                "vessel_count": len(vessels),
                "vessels": [{"id": str(v.id), "vessel_id": str(v.vessel_id), "points": float(v.points)} for v in vessels],
                "periods": [
                    {
                        "id": str(p.id),
                        "label": p.label,
                        "total_pool_result": float(p.total_pool_result or 0),
                        "status": p.status,
                        "distribution": p.distribution or {},
                    }
                    for p in periods
                ],
            }
        )
    return out


@router.post("/pools")
def create_pool(name: str, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    row = Pool(tenant_id=auth.tenant_id, name=name)
    db.add(row)
    db.commit()
    return {"id": str(row.id), "name": name}


@router.post("/pools/{pool_id}/vessels")
def add_pool_vessel(
    pool_id: UUID,
    vessel_id: UUID,
    points: float = 1.0,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    from app.models_wave1 import Vessel

    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    vessel = db.get(Vessel, vessel_id)
    if (
        not vessel
        or vessel.tenant_id != auth.tenant_id
        or vessel.status == "deleted"
        or getattr(vessel, "deleted_at", None) is not None
    ):
        raise HTTPException(404, detail={"code": "VESSEL_NOT_FOUND", "message": "Vessel not found"})
    if points <= 0:
        raise HTTPException(400, detail={"code": "INVALID_POINTS", "message": "Points must be positive"})

    # Already active in this pool
    existing = db.scalar(
        select(PoolVessel).where(
            PoolVessel.pool_id == pool_id,
            PoolVessel.vessel_id == vessel_id,
            PoolVessel.left_on.is_(None),
        )
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VESSEL_ALREADY_IN_POOL",
                "message": "Vessel is already active in this pool",
                "membership_id": str(existing.id),
                "points": float(existing.points),
            },
        )

    # Same vessel cannot be active in two pools of the same tenant at once
    other = db.scalar(
        select(PoolVessel)
        .join(Pool, Pool.id == PoolVessel.pool_id)
        .where(
            Pool.tenant_id == auth.tenant_id,
            PoolVessel.vessel_id == vessel_id,
            PoolVessel.left_on.is_(None),
            PoolVessel.pool_id != pool_id,
        )
    )
    if other:
        other_pool = db.get(Pool, other.pool_id)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VESSEL_IN_OTHER_POOL",
                "message": "Vessel is already active in another pool; leave that pool first",
                "pool_id": str(other.pool_id),
                "pool_name": other_pool.name if other_pool else None,
            },
        )

    row = PoolVessel(pool_id=pool_id, vessel_id=vessel_id, points=points, joined_on=date.today())
    db.add(row)
    db.commit()
    return {"id": str(row.id), "vessel_id": str(vessel_id), "points": float(row.points)}


@router.patch("/pools/{pool_id}/vessels/{membership_id}")
def update_pool_vessel(
    pool_id: UUID,
    membership_id: UUID,
    points: float | None = None,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    row = db.get(PoolVessel, membership_id)
    if not row or row.pool_id != pool_id or row.left_on is not None:
        raise HTTPException(404, "Pool vessel membership not found")
    if points is not None:
        if points <= 0:
            raise HTTPException(400, detail={"code": "INVALID_POINTS", "message": "Points must be positive"})
        row.points = points
    db.commit()
    return {"id": str(row.id), "vessel_id": str(row.vessel_id), "points": float(row.points)}


@router.delete("/pools/{pool_id}/vessels/{membership_id}")
def leave_pool_vessel(
    pool_id: UUID,
    membership_id: UUID,
    auth: AuthContext = Depends(require_module("pooling")),
    db: Session = Depends(get_db),
):
    """Mark vessel as left the pool (historical row kept for settlement audit)."""
    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    row = db.get(PoolVessel, membership_id)
    if not row or row.pool_id != pool_id or row.left_on is not None:
        raise HTTPException(404, "Pool vessel membership not found")
    row.left_on = date.today()
    db.commit()
    return {"ok": True, "id": str(row.id), "left_on": row.left_on.isoformat()}


@router.post("/pools/{pool_id}/periods")
def create_period(pool_id: UUID, label: str, total_pool_result: float, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    pool = db.get(Pool, pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    vessels = db.scalars(select(PoolVessel).where(PoolVessel.pool_id == pool_id, PoolVessel.left_on.is_(None))).all()
    total_points = sum(float(v.points) for v in vessels) or 1.0
    dist = {str(v.vessel_id): round(total_pool_result * float(v.points) / total_points, 2) for v in vessels}
    row = PoolPeriod(pool_id=pool_id, label=label, total_pool_result=total_pool_result, distribution=dist, status="calculating")
    db.add(row)
    db.commit()
    return {"id": str(row.id), "distribution": dist, "status": row.status}


@router.post("/pools/periods/{period_id}/settle")
def settle_period(period_id: UUID, auth: AuthContext = Depends(require_module("pooling")), db: Session = Depends(get_db)):
    row = db.get(PoolPeriod, period_id)
    if not row:
        raise HTTPException(404, "Period not found")
    pool = db.get(Pool, row.pool_id)
    if not pool or pool.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Pool not found")
    row.status = transition("pool_period", row.status, "settled", POOL_PERIOD_TRANSITIONS)
    db.commit()
    return {"id": str(row.id), "status": row.status, "distribution": row.distribution}


def _resolve_var_limit(db: Session, tenant_id: UUID, symbol: str, counterparty: str | None = None) -> float:
    """Most specific active VaR limit wins: counterparty > symbol > global; fallback 100k."""
    scopes = []
    if counterparty:
        scopes.append(f"counterparty:{counterparty}")
    scopes.append(f"symbol:{symbol}")
    scopes.append("global")
    rows = db.scalars(
        select(RiskLimit).where(
            RiskLimit.tenant_id == tenant_id,
            RiskLimit.active.is_(True),
            RiskLimit.scope.in_(scopes),
        )
    ).all()
    by_scope = {r.scope: r for r in rows}
    for scope in scopes:
        if scope in by_scope:
            return float(by_scope[scope].amount)
    return DEFAULT_VAR_LIMIT


class RiskLimitIn(BaseModel):
    scope: str  # "global" | "symbol:<SYMBOL>" | "counterparty:<key>"
    limit_type: str = "var_1d"
    amount: float
    currency: str = "USD"
    active: bool = True


@router.get("/risk/limits")
def list_risk_limits(auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    rows = db.scalars(select(RiskLimit).where(RiskLimit.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "scope": r.scope,
            "limit_type": r.limit_type,
            "amount": float(r.amount or 0),
            "currency": r.currency,
            "active": bool(r.active),
        }
        for r in rows
    ]


@router.post("/risk/limits")
def create_risk_limit(body: RiskLimitIn, auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    if body.amount <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "Limit amount must be > 0"})
    row = RiskLimit(
        tenant_id=auth.tenant_id,
        scope=body.scope,
        limit_type=body.limit_type,
        amount=Decimal(str(body.amount)).quantize(Decimal("0.01")),
        currency=body.currency,
        active=body.active,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "scope": row.scope, "amount": float(row.amount)}


@router.post("/risk/positions")
def create_risk(
    symbol: str,
    qty: float,
    entry_price: float,
    side: str = "long",
    counterparty: str | None = None,
    auth: AuthContext = Depends(require_module("risk")),
    db: Session = Depends(get_db),
):
    var_1d = abs(qty * entry_price * 0.02)
    limit = _resolve_var_limit(db, auth.tenant_id, symbol, counterparty)
    row = RiskPosition(
        tenant_id=auth.tenant_id,
        symbol=symbol,
        side=side,
        qty=qty,
        entry_price=entry_price,
        mark_price=entry_price,
        var_1d=var_1d,
        limit_breach=var_1d > limit,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "var_1d": var_1d, "limit": limit, "limit_breach": row.limit_breach}


@router.get("/risk/positions")
def list_risk(auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    rows = db.scalars(select(RiskPosition).where(RiskPosition.tenant_id == auth.tenant_id)).all()
    return [{"id": str(r.id), "symbol": r.symbol, "var_1d": float(r.var_1d or 0), "limit_breach": r.limit_breach} for r in rows]


@router.get("/risk/hedge-view")
def hedge_view(auth: AuthContext = Depends(require_module("risk")), db: Session = Depends(get_db)):
    """FFA/纸货 vs 实货对冲视图,按 symbol 聚合。

    口径(简化):
    - 纸货 paper_qty = RiskPosition 按 symbol 聚合的有符号数量(long +qty, short −qty)。
    - 实货 physical_qty = active 状态 Charter(在手货盘)的 cargo_qty 合计;
      Charter 无 symbol 字段,映射取其关联 Voyage 的 cargo 文本(去空格大写)
      作为 symbol,同一租约多个航次取第一个非空 cargo,无则归入 "UNMAPPED"。
    - net_exposure = physical − paper;hedge_ratio = paper / physical
      (physical = 0 时为 null)。
    """
    paper: dict[str, Decimal] = {}
    for p in db.scalars(select(RiskPosition).where(RiskPosition.tenant_id == auth.tenant_id)).all():
        sign = Decimal("-1") if (p.side or "long") == "short" else Decimal("1")
        paper[p.symbol] = paper.get(p.symbol, Decimal("0")) + sign * Decimal(str(p.qty or 0))

    physical: dict[str, Decimal] = {}
    charters = db.scalars(
        select(Charter).where(Charter.tenant_id == auth.tenant_id, Charter.status == "active")
    ).all()
    for ch in charters:
        voyages = db.scalars(select(Voyage).where(Voyage.charter_id == ch.id)).all()
        cargo_text = next((v.cargo for v in voyages if v.cargo), None)
        symbol = (cargo_text.strip().upper() if cargo_text and cargo_text.strip() else "UNMAPPED")
        physical[symbol] = physical.get(symbol, Decimal("0")) + Decimal(str(ch.cargo_qty or 0))

    out = []
    for symbol in sorted(set(paper) | set(physical)):
        p = float(paper.get(symbol, Decimal("0")))
        ph = float(physical.get(symbol, Decimal("0")))
        out.append(
            {
                "symbol": symbol,
                "paper_qty": p,
                "physical_qty": ph,
                "net_exposure": ph - p,
                "hedge_ratio": (p / ph) if ph != 0 else None,
            }
        )
    return out



class BerthIn(BaseModel):
    berth_name: str
    start_at: datetime
    end_at: datetime
    port_id: UUID | None = None
    voyage_id: UUID | None = None


@router.post("/berths")
def create_berth(body: BerthIn, auth: AuthContext = Depends(require_module("operations")), db: Session = Depends(get_db)):
    row = BerthWindow(
        tenant_id=auth.tenant_id,
        berth_name=body.berth_name,
        start_at=body.start_at,
        end_at=body.end_at,
        port_id=body.port_id,
        voyage_id=body.voyage_id,
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "berth_name": body.berth_name, "status": row.status}


@router.post("/portal/messages")
def portal_message(counterparty_id: UUID, subject: str, body: str | None = None, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    party = db.get(Counterparty, counterparty_id)
    if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
        raise HTTPException(404, "Counterparty not found")
    assert_not_sanctioned(db, auth.tenant_id, party.id)
    row = PortalMessage(tenant_id=auth.tenant_id, counterparty_id=counterparty_id, subject=subject, body=body)
    db.add(row)
    db.commit()
    return {"id": str(row.id)}


@router.get("/portal/invoices")
def portal_invoices(counterparty_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.counterparty_id == counterparty_id)
    ).all()
    return [{"invoice_no": r.invoice_no, "status": r.status, "amount": float(r.amount)} for r in rows]


@router.post("/documents")
def create_doc(entity_type: str, entity_id: UUID, title: str, doc_type: str = "file", auth: AuthContext = Depends(require_module("docs")), db: Session = Depends(get_db)):
    row = Document(tenant_id=auth.tenant_id, entity_type=entity_type, entity_id=entity_id, title=title, doc_type=doc_type, storage_uri=f"demo://{entity_type}/{entity_id}/{title}")
    db.add(row)
    db.commit()
    return {"id": str(row.id), "storage_uri": row.storage_uri}
