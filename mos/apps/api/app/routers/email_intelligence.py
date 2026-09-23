"""Phase 5 — Email intelligence endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
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
