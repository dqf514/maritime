from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_wave1 import EmailAccount, EmailMessage, EmailThread, Notification
from app.schemas_wave1 import EmailAccountIn, EmailAccountOut, EmailMessageOut, NotificationOut
from app.security import AuthContext, get_current_auth, require_module
from app.services.recycle import soft_delete

router = APIRouter(tags=["Email & Notify"])


@router.get("/email/accounts", response_model=list[EmailAccountOut])
def list_accounts(
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(EmailAccount).where(
            EmailAccount.tenant_id == auth.tenant_id, EmailAccount.status != "deleted"
        )
    ).all()
    return [EmailAccountOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/email/accounts", response_model=EmailAccountOut)
def create_account(
    body: EmailAccountIn,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    data = body.model_dump()
    email = (str(data.get("email") or "")).strip().lower() or None
    provider = (data.get("provider") or "").strip().lower()
    if not email and provider in GRAPH_PROVIDERS:
        # Microsoft 365 account without explicit address → the connected mailbox
        from app.services import office_hub

        try:
            me = office_hub.get_graph_client(db, auth.tenant_id).me()
            email = (me.get("mail") or me.get("userPrincipalName") or "").strip().lower() or None
        except Exception:  # noqa: BLE001
            email = None
        if not email:
            raise HTTPException(400, detail={"code": "MAILBOX_ADDRESS_UNKNOWN", "message": "Cannot resolve the connected mailbox address; set email explicitly"})
    if not email:
        raise HTTPException(422, detail={"code": "EMAIL_REQUIRED"})
    dup = db.scalar(
        select(EmailAccount).where(EmailAccount.tenant_id == auth.tenant_id, EmailAccount.email == email)
    )
    if dup and dup.status != "deleted":
        raise HTTPException(409, detail={"code": "ACCOUNT_EXISTS"})
    row = EmailAccount(tenant_id=auth.tenant_id, status="active", **{**data, "email": email})
    db.add(row)
    db.commit()
    db.refresh(row)
    return EmailAccountOut.model_validate(row, from_attributes=True)


class EmailAccountUpdate(BaseModel):
    """All-optional PATCH body — model_fields_set marks explicitly provided fields
    (including secret keys inside ``config``) so omitted secrets are never overwritten."""

    provider: str | None = None
    email: EmailStr | None = None
    display_name: str | None = None
    config: dict | None = None
    status: str | None = None


@router.patch("/email/accounts/{account_id}", response_model=EmailAccountOut)
def update_account(
    account_id: UUID,
    body: EmailAccountUpdate,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """Partial update. No test-connection revalidation on patch.

    Secret/config keys apply only when explicitly provided (model_fields_set);
    an omitted ``config`` leaves stored credentials untouched.
    """
    row = db.get(EmailAccount, account_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Account not found")
    fields = body.model_fields_set
    if "provider" in fields and body.provider is not None:
        row.provider = body.provider
    if "email" in fields and body.email is not None and body.email != row.email:
        dup = db.scalar(
            select(EmailAccount).where(
                EmailAccount.tenant_id == auth.tenant_id,
                EmailAccount.email == body.email,
                EmailAccount.id != account_id,
            )
        )
        if dup:
            raise HTTPException(409, "Email already linked to another account")
        row.email = body.email
    if "display_name" in fields:
        row.display_name = body.display_name
    if "config" in fields and body.config is not None:
        # explicit config payload replaces config (secrets included only if sent)
        row.config = body.config
    if "status" in fields and body.status is not None:
        if body.status not in ("active", "paused", "deleted"):
            raise HTTPException(422, "status must be active|paused")
        row.status = body.status
    db.commit()
    db.refresh(row)
    return EmailAccountOut.model_validate(row, from_attributes=True)


@router.delete("/email/accounts/{account_id}")
def delete_account(
    account_id: UUID,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """Soft-delete an email account (recycle bin). Config row — messages/threads keep their FK."""
    row = db.get(EmailAccount, account_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Account not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="email_account",
        row=row,
        title=row.email,
    )
    db.commit()
    return {"ok": True, "recycled": True}


GRAPH_PROVIDERS = {"microsoft", "m365", "graph", "outlook"}


def _graph_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _sync_graph_inbox(db: Session, auth: AuthContext, account: EmailAccount, top: int) -> dict:
    """Pull the connected mailbox via Microsoft Graph and persist new messages
    into the review pipeline (dedupe by Graph message id).

    Business mail (fixture recap / NOR / laytime statement) lands in the review
    queue with rule-based parse results; general mail is stored as parsed so it
    doesn't clog the human review queue but remains searchable everywhere.
    """
    from app.services import office_hub
    from app.services.email_intelligence import (
        classify_email,
        parse_fixture_recap,
        parse_laytime_statement,
        parse_nor,
    )

    try:
        client = office_hub.get_graph_client(db, auth.tenant_id)
        mails = client.list_mail(top=top)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, detail={"code": "GRAPH_SYNC_FAILED", "message": str(exc)}) from exc

    synced = 0
    review = 0
    for m in mails:
        mid = m.get("id")
        if not mid:
            continue
        exists = db.scalar(
            select(EmailMessage.id).where(
                EmailMessage.tenant_id == auth.tenant_id, EmailMessage.message_id == str(mid)
            )
        )
        if exists:
            continue
        subject = (m.get("subject") or "").strip() or "(no subject)"
        body = (m.get("body") or {}).get("content") or m.get("bodyPreview") or ""
        frm = (m.get("from") or {}).get("emailAddress") or {}
        from_email = frm.get("address") or m.get("sender", {}).get("emailAddress", {}).get("address")
        sent_at = _graph_dt(m.get("receivedDateTime")) or datetime.now(timezone.utc)

        conv = m.get("conversationId") or mid
        thread_key = f"graph-{conv}"
        thread = db.scalar(
            select(EmailThread).where(
                EmailThread.tenant_id == auth.tenant_id, EmailThread.thread_key == thread_key
            )
        )
        if not thread:
            thread = EmailThread(
                tenant_id=auth.tenant_id,
                account_id=account.id,
                subject_norm=subject.lower(),
                thread_key=thread_key,
                last_message_at=sent_at,
                message_count=0,
            )
            db.add(thread)
            db.flush()

        # Classify + rule-based parse (fast & deterministic; the LLM pipeline
        # remains available separately via /email-intelligence/process).
        cls = classify_email(subject, body)
        ctype = cls["type"]
        parse_result: dict = {"email_type": ctype, "source": "graph", "graph_id": str(mid)}
        status = "parsed"
        if ctype == "fixture_recap":
            parse_result.update(parse_fixture_recap(body))
            status = "review"
        elif ctype == "nor":
            parse_result.update(parse_nor(body))
            status = "review"
        elif ctype == "laytime_statement":
            parse_result.update(parse_laytime_statement(body))
            status = "review"

        db.add(
            EmailMessage(
                tenant_id=auth.tenant_id,
                account_id=account.id,
                thread_id=thread.id,
                message_id=str(mid),
                direction="inbound",
                from_email=from_email,
                subject=subject,
                body_text=body[:20000],
                sent_at=sent_at,
                parse_status=status,
                parse_confidence=Decimal(str(cls["confidence"])),
                parse_result=parse_result,
            )
        )
        thread.message_count = (thread.message_count or 0) + 1
        thread.last_message_at = max(thread.last_message_at or sent_at, sent_at)
        synced += 1
        if status == "review":
            review += 1

    account.last_sync_at = datetime.now(timezone.utc)
    db.add(account)
    if review:
        db.add(
            Notification(
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                title="Microsoft 365 mail synced",
                body=f"{review} message(s) ready for review from {account.email}",
                level="info",
                href="/email/review",
            )
        )
    db.commit()
    return {
        "synced": synced,
        "review_queue": review,
        "provider": "microsoft",
        "mode": getattr(client, "mode", "live"),
    }


@router.post("/email/accounts/{account_id}/sync")
def sync_account(
    account_id: UUID,
    top: int = Query(20, ge=1, le=100),
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    account = db.get(EmailAccount, account_id)
    if not account or account.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Account not found")

    if (account.provider or "").strip().lower() in GRAPH_PROVIDERS:
        # Real (or stub) Microsoft 365 mailbox — persisted into the review pipeline
        return _sync_graph_inbox(db, auth, account, top)

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


@router.get("/email/related")
def related_messages(
    q: str = Query("", max_length=300),
    top: int = Query(20, ge=1, le=100),
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """Keyword search across the tenant mailbox for the per-entity mail sidebar.

    ``q`` accepts comma/semicolon-separated terms (e.g. voyage no, vessel name,
    counterparty); any term matching subject or body pulls the message in (OR).
    """
    stmt = select(EmailMessage).where(EmailMessage.tenant_id == auth.tenant_id)
    terms = [t.strip() for t in q.replace(";", ",").split(",") if t.strip()]
    if terms:
        conds = []
        for term in terms:
            like = f"%{term}%"
            conds.append(
                or_(EmailMessage.subject.ilike(like), EmailMessage.body_text.ilike(like))
            )
        stmt = stmt.where(or_(*conds))
    rows = db.scalars(stmt.order_by(EmailMessage.sent_at.desc()).limit(top)).all()
    return [
        {
            "id": str(r.id),
            "subject": r.subject,
            "from_email": r.from_email,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            "parse_status": r.parse_status,
            "email_type": (r.parse_result or {}).get("email_type"),
            "body_preview": (r.body_text or "")[:300],
        }
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
