import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_wave1 import EmailAccount, EmailMessage, EmailThread, Notification
from app.schemas_wave1 import EmailAccountIn, EmailAccountOut, EmailMessageOut, NotificationOut
from app.security import AuthContext, get_current_auth, require_module
from app.services.identity import as_aware
from app.services.integration_adapters import (
    encrypt_email_config,
    mask_email_config,
)
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
    # P0-19：config 里的密钥（SMTP 口令等）**不回吐**
    return [
        EmailAccountOut.model_validate(r, from_attributes=True).model_copy(
            update={"config": mask_email_config(r.config)}
        )
        for r in rows
    ]


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
    # P0-19：密钥字段**加密落库**（不再明文存 SMTP 口令）
    data["config"] = encrypt_email_config(data.get("config") or {})
    row = EmailAccount(tenant_id=auth.tenant_id, status="active", **{**data, "email": email})
    db.add(row)
    db.commit()
    db.refresh(row)
    # P0-19：密钥不回吐
    return EmailAccountOut.model_validate(row, from_attributes=True).model_copy(
        update={"config": mask_email_config(row.config)}
    )


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
        # P0-19：密钥字段加密落库
        row.config = encrypt_email_config(body.config)
    if "status" in fields and body.status is not None:
        if body.status not in ("active", "paused", "deleted"):
            raise HTTPException(422, "status must be active|paused")
        row.status = body.status
    db.commit()
    db.refresh(row)
    # P0-19：密钥不回吐（PATCH 同样要遮 —— 改配置时最容易被顺手回显）
    return EmailAccountOut.model_validate(row, from_attributes=True).model_copy(
        update={"config": mask_email_config(row.config)}
    )


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

#: 非收件箱的系统文件夹：出站语义 —— 只做参考浏览，不进复核队列
OUTBOUND_FOLDERS = {"sentitems", "drafts", "deleteditems", "junkemail", "archive", "outbox"}
#: 文件夹 key 的安全字符（Graph wellKnownName / 自定义文件夹名 / folder id）
_FOLDER_RE = re.compile(r"^[A-Za-z0-9=_.-]{1,128}$")
#: 单次同步的全局条数预算 —— 杜绝多文件夹 × 大条数把系统拖垮
SYNC_GLOBAL_BUDGET = 2000


def _graph_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _clean_body(raw) -> str:
    """Graph body → 纯文本（HTML 片段统一转文本，防止标签进入解析字段）。"""
    from app.services.html_to_text import html_to_text

    if isinstance(raw, dict):
        content = raw.get("content") or ""
    else:
        content = str(raw or "")
    return html_to_text(content)


def _sync_graph_mails(
    db: Session,
    auth: AuthContext,
    account: EmailAccount,
    *,
    days: int,
    count: int,
    folders: list[str],
) -> dict:
    """Pull the connected mailbox via Microsoft Graph and persist new messages
    into the review pipeline (dedupe by Graph message id).

    多文件夹拉取：inbox 优先，然后其余（sentitems 等出站文件夹只做参考浏览，
    强制 parsed 不进复核队列）。单次总量受 SYNC_GLOBAL_BUDGET 预算保护。
    正文在 classify/规则解析**之前**统一 html_to_text 转纯文本。
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
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, detail={"code": "GRAPH_SYNC_FAILED", "message": str(exc)}) from exc

    since = datetime.now(timezone.utc) - timedelta(days=days)
    # inbox 永远排第一：复核队列优先于参考浏览
    ordered = sorted(set(folders), key=lambda f: (f.lower() != "inbox", f.lower()))

    synced = 0
    review = 0
    capped = False
    folder_counts: dict[str, int] = {}
    for folder in ordered:
        if synced >= SYNC_GLOBAL_BUDGET:
            capped = True
            break
        try:
            mails = client.list_mail(top=min(count, SYNC_GLOBAL_BUDGET - synced), folder=folder, since=since)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                502, detail={"code": "GRAPH_SYNC_FAILED", "message": f"{folder}: {exc}"}
            ) from exc
        folder_key = folder.lower()
        inbound = folder_key == "inbox"
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
            # Graph body 形状 = {"content": ...}；先 html_to_text 转纯文本再解析
            body = _clean_body(m.get("body")) or m.get("bodyPreview") or ""
            frm = (m.get("from") or {}).get("emailAddress") or {}
            from_email = frm.get("address") or m.get("sender", {}).get("emailAddress", {}).get("address")
            sent_at = (
                _graph_dt(m.get("receivedDateTime"))
                or _graph_dt(m.get("sentDateTime"))
                or datetime.now(timezone.utc)
            )

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

            if not inbound:
                # 出站/杂项文件夹：强制 parsed（不进复核队列），收件人存档供参考
                to_recipients = [
                    ((r or {}).get("emailAddress") or {}).get("address")
                    for r in (m.get("toRecipients") or [])
                ]
                to_recipients = [t for t in to_recipients if t][:5]
                parse_result: dict = {
                    "email_type": "outbound",
                    "source": "graph",
                    "graph_id": str(mid),
                    "to_recipients": to_recipients,
                }
                status = "parsed"
                cls = {"confidence": 1.0}
            else:
                # Classify + rule-based parse (fast & deterministic; the LLM pipeline
                # remains available separately via /email-intelligence/process).
                cls = classify_email(subject, body)
                ctype = cls["type"]
                parse_result = {"email_type": ctype, "source": "graph", "graph_id": str(mid)}
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
                    direction="inbound" if inbound else "outbound",
                    folder=folder_key,
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
            # SQLite returns naive datetimes; Graph timestamps are timezone-aware.
            prev = as_aware(thread.last_message_at) if thread.last_message_at else sent_at
            thread.last_message_at = max(prev, sent_at)
            synced += 1
            folder_counts[folder_key] = folder_counts.get(folder_key, 0) + 1
            if status == "review":
                review += 1
            if synced >= SYNC_GLOBAL_BUDGET:
                capped = True
                break

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
    if review:
        # Teams 工作流推送（软失败）：复核队列有新业务邮件 → 频道提醒带深链
        from app.services import office_hub

        office_hub.notify_workflow_event(
            db,
            auth.tenant_id,
            title="Mailbox review queue",
            lines=[
                f"{review} business email(s) awaiting review from {account.email}",
                "Open Email Review to create drafts (recap → estimate, NOR → voyage, SOF → laytime).",
            ],
            href="/email/review",
        )
        db.commit()
    return {
        "synced": synced,
        "review_queue": review,
        "provider": "microsoft",
        "mode": getattr(client, "mode", "live"),
        "window_days": days,
        "count_cap": count,
        "folders": folder_counts,
        "capped": capped,
    }


def _parse_folders(folders: str) -> list[str]:
    """解析逗号分隔的文件夹列表，正则校验 + 去重 + 上限 10 个。"""
    parts = [f.strip() for f in (folders or "").split(",") if f.strip()]
    if not parts:
        return ["inbox"]
    if len(parts) > 10:
        raise HTTPException(422, detail={"code": "TOO_MANY_FOLDERS", "message": "max 10 folders per sync"})
    for p in parts:
        if not _FOLDER_RE.match(p):
            raise HTTPException(422, detail={"code": "INVALID_FOLDER", "folder": p})
    return list(dict.fromkeys(parts))


@router.post("/email/accounts/{account_id}/sync")
def sync_account(
    account_id: UUID,
    days: int = Query(7, ge=1, le=30),
    count: int = Query(200, ge=1, le=1000),
    folders: str = Query("inbox,sentitems"),
    top: int | None = Query(None, ge=1, le=1000, description="deprecated: use count"),
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """按「天数 + 条数」双控拉取邮件（days ≤30，count/folder ≤1000，全局预算 2000）。"""
    account = db.get(EmailAccount, account_id)
    if not account or account.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Account not found")
    if top is not None:
        count = top  # deprecated alias
    folder_list = _parse_folders(folders)

    if (account.provider or "").strip().lower() in GRAPH_PROVIDERS:
        # Real (or stub) Microsoft 365 mailbox — persisted into the review pipeline
        return _sync_graph_mails(
            db, auth, account, days=days, count=count, folders=folder_list
        )

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
        folder="inbox",
        from_email="recaps@atlanticbrokers.co.uk",
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
    return {
        "synced": 1,
        "review_queue": 1,
        "window_days": days,
        "count_cap": count,
        "folders": {"inbox": 1},
        "capped": False,
    }


@router.get("/email/messages", response_model=list[EmailMessageOut])
def list_messages(
    parse_status: str | None = None,
    folder: str | None = Query(None, max_length=128),
    days: int | None = Query(None, ge=1, le=30),
    limit: int = Query(200, ge=1, le=1000),
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    stmt = select(EmailMessage).where(EmailMessage.tenant_id == auth.tenant_id)
    if parse_status:
        stmt = stmt.where(EmailMessage.parse_status == parse_status)
    if folder:
        stmt = stmt.where(EmailMessage.folder == folder.lower())
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = stmt.where(EmailMessage.sent_at >= cutoff)
    rows = db.scalars(
        stmt.order_by(EmailMessage.sent_at.desc().nullslast(), EmailMessage.created_at.desc())
        .limit(limit)
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
            folder=r.folder or "inbox",
            direction=r.direction or "inbound",
        )
        for r in rows
    ]


@router.get("/email/folders")
def list_folders(
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """当前邮箱的文件夹清单（Graph 实时拉取；demo/未连 → 静态双 Tab）。

    UI 用它渲染文件夹 Tab；Graph 失败返回 502 GRAPH_FOLDERS_FAILED，
    前端降级为静态 inbox/sentitems 两个 Tab。
    """
    accounts = db.scalars(
        select(EmailAccount).where(
            EmailAccount.tenant_id == auth.tenant_id, EmailAccount.status != "deleted"
        )
    ).all()
    graph_acct = next(
        (a for a in accounts if (a.provider or "").strip().lower() in GRAPH_PROVIDERS), None
    )
    if graph_acct is None:
        return {
            "folders": [
                {"key": "inbox", "display_name": "Inbox", "well_known": "inbox", "parent_key": None},
                {"key": "sentitems", "display_name": "Sent Items", "well_known": "sentitems", "parent_key": None},
            ],
            "source": "static",
        }
    from app.services import office_hub

    try:
        client = office_hub.get_graph_client(db, auth.tenant_id)
        folders = client.list_mail_folders()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, detail={"code": "GRAPH_FOLDERS_FAILED", "message": str(exc)}) from exc
    return {"folders": folders, "source": getattr(client, "mode", "live")}


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
        .order_by(EmailMessage.sent_at.desc().nullslast(), EmailMessage.created_at.desc())
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
            folder=r.folder or "inbox",
            direction=r.direction or "inbound",
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


@router.get("/email/messages/{message_id}")
def get_message_detail(
    message_id: UUID,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """单封邮件详情（含正文）——回复预览 / 人工核对解析结果用。"""
    row = db.get(EmailMessage, message_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Message not found")
    return {
        "id": str(row.id),
        "message_id": row.message_id,
        "direction": row.direction,
        "folder": row.folder or "inbox",
        "subject": row.subject,
        "from_email": row.from_email,
        "body_text": row.body_text or "",
        "parse_status": row.parse_status,
        "parse_confidence": float(row.parse_confidence) if row.parse_confidence is not None else None,
        "parse_result": row.parse_result or {},
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
    }


@router.post("/email/review/{message_id}/apply")
def apply_parse_to_drafts(
    message_id: UUID,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """解析结果一键落单：recap→估算草稿 / NOR→盖 nor_at / SOF→装卸时间草稿。"""
    from app.services.email_actions import apply_message

    try:
        return apply_message(db, auth.tenant_id, auth.user_id, message_id)
    except LookupError as exc:
        raise HTTPException(404, "Message not found") from exc


class EmailReplyIn(BaseModel):
    template: str = "general"
    extra: dict = Field(default_factory=dict)
    preview: bool = False  # True=只渲染不发送（UI 预览）


@router.post("/email/messages/{message_id}/reply")
def reply_to_message(
    message_id: UUID,
    body: EmailReplyIn,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """按模板生成业务回函并发送（SMTP/Graph/console 平台通道），回写同线程。"""
    from app.services.email_actions import REPLY_TEMPLATES, render_reply, send_reply

    if body.template not in REPLY_TEMPLATES:
        raise HTTPException(422, detail={"code": "UNKNOWN_TEMPLATE", "allowed": list(REPLY_TEMPLATES)})
    try:
        if body.preview:
            return render_reply(db, auth.tenant_id, message_id, body.template, body.extra)
        return send_reply(db, auth.tenant_id, auth.user_id, message_id, body.template, body.extra)
    except LookupError as exc:
        raise HTTPException(404, "Message not found") from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "REPLY_NOT_SENDABLE", "message": str(exc)}) from exc


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
