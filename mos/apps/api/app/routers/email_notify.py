from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_wave1 import EmailAccount, EmailMessage, EmailThread, Notification
from app.schemas_wave1 import EmailAccountIn, EmailAccountOut, EmailMessageOut, NotificationOut
from app.security import AuthContext, get_current_auth, require_module

router = APIRouter(tags=["Email & Notify"])


@router.get("/email/accounts", response_model=list[EmailAccountOut])
def list_accounts(
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(EmailAccount).where(EmailAccount.tenant_id == auth.tenant_id)).all()
    return [EmailAccountOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/email/accounts", response_model=EmailAccountOut)
def create_account(
    body: EmailAccountIn,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    row = EmailAccount(tenant_id=auth.tenant_id, status="active", **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return EmailAccountOut.model_validate(row, from_attributes=True)


@router.post("/email/accounts/{account_id}/sync")
def sync_account(
    account_id: UUID,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    account = db.get(EmailAccount, account_id)
    if not account or account.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Account not found")

    thread = EmailThread(
        tenant_id=auth.tenant_id,
        account_id=account.id,
        subject_norm="recap mv ocean star / singapore-rotterdam",
        thread_key=f"demo-{uuid4()}",
        last_message_at=datetime.now(timezone.utc),
        message_count=1,
    )
    db.add(thread)
    db.flush()
    msg = EmailMessage(
        tenant_id=auth.tenant_id,
        account_id=account.id,
        thread_id=thread.id,
        message_id=f"<{uuid4()}@demo.marios>",
        direction="inbound",
        from_email="broker@example.com",
        subject="RECAP: MV OCEAN STAR / SGSIN-NLRTM Coal",
        body_text="Vessel MV OCEAN STAR IMO 9123456. Laycan 12-18 Sep. Freight USD 18.5 PMT.",
        sent_at=datetime.now(timezone.utc),
        parse_status="review",
        parse_confidence=0.91,
        parse_result={
            "email_type": "recap",
            "vessel_name": "MV OCEAN STAR",
            "imo": "9123456",
            "load_port": "SGSIN",
            "discharge_port": "NLRTM",
            "cargo": "Coal",
            "freight_rate": 18.5,
        },
    )
    db.add(msg)
    account.last_sync_at = datetime.now(timezone.utc)
    db.add(
        Notification(
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            title="Email synced",
            body=f"1 message ready for review from {account.email}",
            level="info",
            href="/email/review",
        )
    )
    db.commit()
    return {"synced": 1, "review_queue": 1}


@router.get("/email/messages", response_model=list[EmailMessageOut])
def list_messages(
    parse_status: str | None = None,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    stmt = select(EmailMessage).where(EmailMessage.tenant_id == auth.tenant_id)
    if parse_status:
        stmt = stmt.where(EmailMessage.parse_status == parse_status)
    rows = db.scalars(stmt.order_by(EmailMessage.created_at.desc()).limit(100)).all()
    return [
        EmailMessageOut(
            id=r.id,
            subject=r.subject,
            from_email=r.from_email,
            parse_status=r.parse_status,
            parse_confidence=float(r.parse_confidence) if r.parse_confidence is not None else None,
            parse_result=r.parse_result or {},
            sent_at=r.sent_at,
        )
        for r in rows
    ]


@router.get("/email/review", response_model=list[EmailMessageOut])
def review_queue(
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(EmailMessage)
        .where(EmailMessage.tenant_id == auth.tenant_id, EmailMessage.parse_status == "review")
        .order_by(EmailMessage.created_at.desc())
    ).all()
    return [
        EmailMessageOut(
            id=r.id,
            subject=r.subject,
            from_email=r.from_email,
            parse_status=r.parse_status,
            parse_confidence=float(r.parse_confidence) if r.parse_confidence is not None else None,
            parse_result=r.parse_result or {},
            sent_at=r.sent_at,
        )
        for r in rows
    ]


@router.post("/email/review/{message_id}/confirm")
def confirm_parse(
    message_id: UUID,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    row = db.get(EmailMessage, message_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Message not found")
    row.parse_status = "parsed"
    db.commit()
    return {"status": "parsed", "id": str(row.id)}


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Notification)
        .where(Notification.tenant_id == auth.tenant_id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    ).all()
    return [NotificationOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    row = db.get(Notification, notification_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Not found")
    row.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from sqlalchemy import or_, update  # noqa: PLC0415

    now = datetime.now(timezone.utc)
    res = db.execute(
        update(Notification)
        .where(
            Notification.tenant_id == auth.tenant_id,
            Notification.read_at.is_(None),
            or_(Notification.user_id == auth.user_id, Notification.user_id.is_(None)),
        )
        .values(read_at=now)
    )
    db.commit()
    return {"ok": True, "updated": res.rowcount}
