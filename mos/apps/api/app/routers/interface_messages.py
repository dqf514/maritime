"""Interface Messages console API (IMOS Data Center 标配).

Tenant-scoped message log for integration exchanges. Admin-module gated.
See ``app.services.interface_messages`` for the (stub) processor contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_interface import InterfaceMessage
from app.security import AuthContext, require_roles
from app.services.interface_messages import process_message
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter(prefix="/interface/messages", tags=["interface-messages"])

_MAX_LIMIT = 200


class InterfaceMessageOut(BaseModel):
    id: str
    direction: str
    channel: str
    interface_code: str
    external_ref: str | None
    status: str
    error_message: str | None
    retry_count: int
    last_retry_at: str | None
    created_at: str
    updated_at: str
    payload: object | None = None


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _to_out(msg: InterfaceMessage, *, include_payload: bool = True) -> InterfaceMessageOut:
    return InterfaceMessageOut(
        id=str(msg.id),
        direction=msg.direction,
        channel=msg.channel,
        interface_code=msg.interface_code,
        external_ref=msg.external_ref,
        status=msg.status,
        error_message=msg.error_message,
        retry_count=msg.retry_count or 0,
        last_retry_at=_iso(msg.last_retry_at),
        created_at=_iso(msg.created_at) or "",
        updated_at=_iso(msg.updated_at) or "",
        payload=msg.payload if include_payload else None,
    )


@router.get("", response_model=list[InterfaceMessageOut])
@router.get("/", response_model=list[InterfaceMessageOut], include_in_schema=False)
def list_messages(
    status: str | None = Query(None, description="pending | success | failed"),
    direction: str | None = Query(None, description="inbound | outbound"),
    interface_code: str | None = Query(None),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    """List interface messages for the current tenant, newest first."""
    stmt = scoped_query(db, InterfaceMessage, auth.tenant_id)
    if status:
        stmt = stmt.where(InterfaceMessage.status == status)
    if direction:
        stmt = stmt.where(InterfaceMessage.direction == direction)
    if interface_code:
        stmt = stmt.where(InterfaceMessage.interface_code == interface_code)
    stmt = stmt.order_by(InterfaceMessage.created_at.desc()).limit(limit).offset(offset)
    rows = db.scalars(stmt).all()
    # List view omits full payload — fetch detail for that.
    return [_to_out(r, include_payload=False) for r in rows]


@router.get("/stats")
def message_stats(
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    """Counts by status overall and within the last 24 hours."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    def _counts(*where) -> dict[str, int]:
        stmt = (
            select(InterfaceMessage.status, func.count())
            .where(InterfaceMessage.tenant_id == auth.tenant_id, *where)
            .group_by(InterfaceMessage.status)
        )
        return {str(status): int(n) for status, n in db.execute(stmt).all()}

    by_status = _counts()
    recent = _counts(InterfaceMessage.created_at >= since)
    return {
        "total": sum(by_status.values()),
        "by_status": {
            "pending": by_status.get("pending", 0),
            "success": by_status.get("success", 0),
            "failed": by_status.get("failed", 0),
        },
        "last_24h": {
            "total": sum(recent.values()),
            "pending": recent.get("pending", 0),
            "success": recent.get("success", 0),
            "failed": recent.get("failed", 0),
        },
    }


@router.get("/{message_id}", response_model=InterfaceMessageOut)
def get_message(
    message_id: UUID,
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    """Message detail including the full payload."""
    msg = scoped_get(db, InterfaceMessage, message_id, auth.tenant_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="INTERFACE_MESSAGE_NOT_FOUND")
    return _to_out(msg, include_payload=True)


@router.post("/{message_id}/retry", response_model=InterfaceMessageOut)
def retry_message(
    message_id: UUID,
    auth: AuthContext = Depends(require_roles("tenant_admin", "platform_admin")),
    db: Session = Depends(get_db),
):
    """Re-queue a message and run the stub processor synchronously.

    Increments ``retry_count``, sets ``status=pending`` / ``last_retry_at=now``,
    then immediately runs ``process_message`` (see that module: inbound
    parse-shaped payloads succeed, everything else fails honestly).
    """
    msg = scoped_get(db, InterfaceMessage, message_id, auth.tenant_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="INTERFACE_MESSAGE_NOT_FOUND")

    msg.retry_count = (msg.retry_count or 0) + 1
    msg.status = "pending"
    msg.last_retry_at = datetime.now(timezone.utc)

    new_status, new_error = process_message(msg)
    msg.status = new_status
    msg.error_message = new_error
    msg.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(msg)
    return _to_out(msg, include_payload=True)
