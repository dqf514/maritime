"""审批额度 + 汇率日期规则路由（财务控制 P1）。

/approvals/limits        — approval amount bands per role/group (CRUD)
/approvals/fx-date-rules — FX rate date basis per invoice type (GET/PUT)
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module

from app.models_finance_ext import ApprovalLimit, FxDateRule
from app.services.fx_date_rules import (
    DEFAULT_RATE_DATE_BASIS,
    RATE_DATE_BASES,
    effective_basis,
    get_rule,
    upsert_rule,
    validate_rate_date_basis,
)
from app.services.invoice_types import invalid_invoice_type_detail, is_valid_invoice_type

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _limit_out(r: ApprovalLimit) -> dict:
    return {
        "id": str(r.id),
        "role_code": r.role_code,
        "entity_type": r.entity_type,
        "currency": r.currency,
        "amount_from": float(r.amount_from),
        "amount_to": float(r.amount_to),
        "active": bool(r.active),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


class ApprovalLimitIn(BaseModel):
    role_code: str = Field(min_length=1, max_length=64)
    entity_type: str = Field(min_length=1, max_length=32)  # e.g. invoice|payment
    currency: str = "USD"
    amount_from: float
    amount_to: float
    active: bool = True


class ApprovalLimitUpdate(BaseModel):
    role_code: str | None = Field(default=None, min_length=1, max_length=64)
    entity_type: str | None = Field(default=None, min_length=1, max_length=32)
    currency: str | None = None
    amount_from: float | None = None
    amount_to: float | None = None
    active: bool | None = None


def _check_band(lo: float, hi: float) -> None:
    if Decimal(str(lo)) > Decimal(str(hi)):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_APPROVAL_BAND",
                "message": "amount_from must be <= amount_to",
                "amount_from": lo,
                "amount_to": hi,
            },
        )


@router.get("/limits")
def list_limits(
    entity_type: str | None = Query(None),
    role_code: str | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    q = select(ApprovalLimit).where(ApprovalLimit.tenant_id == auth.tenant_id)
    if entity_type:
        q = q.where(ApprovalLimit.entity_type == entity_type)
    if role_code:
        q = q.where(ApprovalLimit.role_code == role_code)
    rows = db.scalars(q.order_by(ApprovalLimit.entity_type, ApprovalLimit.role_code, ApprovalLimit.amount_from)).all()
    return {"items": [_limit_out(r) for r in rows]}


@router.post("/limits")
def create_limit(
    body: ApprovalLimitIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    _check_band(body.amount_from, body.amount_to)
    row = ApprovalLimit(
        tenant_id=auth.tenant_id,
        role_code=body.role_code,
        entity_type=body.entity_type,
        currency=(body.currency or "USD").upper(),
        amount_from=Decimal(str(body.amount_from)),
        amount_to=Decimal(str(body.amount_to)),
        active=body.active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _limit_out(row)


@router.patch("/limits/{limit_id}")
def update_limit(
    limit_id: UUID,
    body: ApprovalLimitUpdate,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = db.get(ApprovalLimit, limit_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Approval limit not found")
    lo = body.amount_from if body.amount_from is not None else float(row.amount_from)
    hi = body.amount_to if body.amount_to is not None else float(row.amount_to)
    _check_band(lo, hi)
    if body.role_code is not None:
        row.role_code = body.role_code
    if body.entity_type is not None:
        row.entity_type = body.entity_type
    if body.currency is not None:
        row.currency = body.currency.upper()
    if body.amount_from is not None:
        row.amount_from = Decimal(str(body.amount_from))
    if body.amount_to is not None:
        row.amount_to = Decimal(str(body.amount_to))
    if body.active is not None:
        row.active = body.active
    db.commit()
    db.refresh(row)
    return _limit_out(row)


@router.delete("/limits/{limit_id}")
def delete_limit(
    limit_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = db.get(ApprovalLimit, limit_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Approval limit not found")
    db.delete(row)
    db.commit()
    return {"id": str(limit_id), "deleted": True}


# —— 汇率日期规则 FX date rules ——


def _rule_out(r: FxDateRule) -> dict:
    return {
        "id": str(r.id),
        "invoice_type": r.invoice_type,
        "rate_date_basis": r.rate_date_basis,
        "active": bool(r.active),
    }


class FxDateRuleIn(BaseModel):
    invoice_type: str = Field(min_length=1, max_length=32)
    rate_date_basis: str = Field(min_length=1, max_length=16)
    active: bool = True


@router.get("/fx-date-rules")
def list_fx_date_rules(
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(FxDateRule).where(FxDateRule.tenant_id == auth.tenant_id).order_by(FxDateRule.invoice_type)
    ).all()
    return {
        "items": [_rule_out(r) for r in rows],
        "default_basis": DEFAULT_RATE_DATE_BASIS,
        "allowed_bases": list(RATE_DATE_BASES),
    }


@router.get("/fx-date-rules/{invoice_type}")
def get_fx_date_rule(
    invoice_type: str,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    if not is_valid_invoice_type(invoice_type):
        raise HTTPException(status_code=422, detail=invalid_invoice_type_detail(invoice_type))
    row = get_rule(db, auth.tenant_id, invoice_type)
    if row is None:
        return {
            "invoice_type": invoice_type,
            "rate_date_basis": DEFAULT_RATE_DATE_BASIS,
            "active": False,
            "is_default": True,
        }
    out = _rule_out(row)
    out["is_default"] = False
    return out


@router.put("/fx-date-rules")
def put_fx_date_rule(
    body: FxDateRuleIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    if not is_valid_invoice_type(body.invoice_type):
        raise HTTPException(status_code=422, detail=invalid_invoice_type_detail(body.invoice_type))
    try:
        validate_rate_date_basis(body.rate_date_basis)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_RATE_DATE_BASIS",
                "message": str(exc),
                "allowed_bases": list(RATE_DATE_BASES),
            },
        )
    row = upsert_rule(
        db,
        auth.tenant_id,
        body.invoice_type,
        body.rate_date_basis,
        active=body.active,
    )
    db.commit()
    db.refresh(row)
    out = _rule_out(row)
    out["effective_basis"] = effective_basis(db, auth.tenant_id, body.invoice_type)
    return out
