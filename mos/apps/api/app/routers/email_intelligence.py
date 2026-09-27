"""Phase 5 — Email intelligence endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module
from app.services import email_intelligence as ei

router = APIRouter(prefix="/email-intelligence", tags=["Email Intelligence"])


class ClassificationOut(BaseModel):
    type: str
    confidence: float


class ProcessResult(BaseModel):
    message_id: str
    classification: dict
    parse_result: dict


@router.get("/unprocessed")
def list_unprocessed(
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    msgs = ei.list_unprocessed(db, auth.tenant_id, limit)
    return [
        {
            "id": str(m.id),
            "subject": m.subject,
            "from": m.from_email,
            "sent_at": m.sent_at.isoformat() if m.sent_at else None,
            "parse_status": m.parse_status,
        }
        for m in msgs
    ]


@router.post("/process/{message_id}", response_model=ProcessResult)
def process_message(
    message_id: UUID,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    result = ei.process_inbound_email(db, auth.tenant_id, message_id)
    if "error" in result:
        from fastapi import HTTPException
        raise HTTPException(404, result["error"])
    return ProcessResult(**result)


@router.post("/classify")
def classify(
    body: dict,
    auth: AuthContext = Depends(require_module("email")),
):
    subject = body.get("subject", "")
    text = body.get("body", "")
    return ei.classify_email(subject, text)


@router.post("/parse-fixture-recap")
def parse_fixture_recap(
    body: dict,
    auth: AuthContext = Depends(require_module("email")),
):
    return ei.parse_fixture_recap(body.get("body", ""))


class RecapReconcileIn(BaseModel):
    charter_id: UUID
    recap: dict | None = None
    message_id: UUID | None = None


@router.post("/recap-reconcile")
def recap_reconcile(
    body: RecapReconcileIn,
    auth: AuthContext = Depends(require_module("chartering")),
    db: Session = Depends(get_db),
):
    """D3 recap 双向对账：邮件解析字段 vs 租约字段 → 差异清单（人工确认）。"""
    from app.models_domain import Charter
    from app.services.recap_reconcile import reconcile_recap
    from app.services.tenant_guard import scoped_get

    charter = scoped_get(db, Charter, body.charter_id, auth.tenant_id)
    if charter is None:
        raise HTTPException(404, "Charter not found")
    recap = dict(body.recap or {})
    if body.message_id:
        from app.models_wave1 import EmailMessage

        msg = scoped_get(db, EmailMessage, body.message_id, auth.tenant_id)
        if msg is None:
            raise HTTPException(404, "Message not found")
        parsed = (msg.parse_result or {}).get("fixture_recap") or {}
        recap = {**parsed, **recap}
    if not recap:
        raise HTTPException(422, detail={"code": "RECAP_REQUIRED", "message": "recap or message_id required"})
    return reconcile_recap(recap, charter)


@router.get("/laytime-parsed")
def list_laytime_parsed(
    limit: int = Query(20, ge=1, le=100),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """D12 对账直连：已解析的 laytime statement 邮件（供对账面板一键导入）。"""
    from sqlalchemy import desc, select

    from app.models_wave1 import EmailMessage

    rows = db.scalars(
        select(EmailMessage)
        .where(EmailMessage.tenant_id == auth.tenant_id, EmailMessage.parse_status == "parsed")
        .order_by(desc(EmailMessage.sent_at))
        .limit(200)
    ).all()
    out = []
    for msg in rows:
        pr = msg.parse_result or {}
        laytime = pr.get("laytime")
        if laytime:
            out.append(
                {
                    "message_id": str(msg.id),
                    "subject": msg.subject,
                    "sent_at": msg.sent_at.isoformat() if msg.sent_at else None,
                    "parsed": laytime,
                }
            )
        if len(out) >= limit:
            break
    return {"items": out}
