import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
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

#: 出站语义的系统文件夹 —— 仅决定 direction 展示元数据（From 列显示收件人）；
#: 分类/规则解析/复核队列对所有文件夹一视同仁，不再按 inbound/outbound 分流
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

    多文件夹拉取：inbox 优先，然后其余。所有文件夹统一分类/规则解析 ——
    业务类型进复核队列，其余 parsed；sentitems 等出站文件夹仅 direction
    标记不同。单次总量受 SYNC_GLOBAL_BUDGET 预算保护。
    正文在 classify/规则解析**之前**统一 html_to_text 转纯文本。
    """
    from app.services import office_hub
    from app.services.email_intelligence import (
        classify_with_memory,
        parse_bunker_offer,
        parse_claim,
        parse_fixture_recap,
        parse_invoice,
        parse_laytime_statement,
        parse_nor,
        parse_port_disbursement,
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
        outbound_folder = folder_key in OUTBOUND_FOLDERS
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

            # 所有文件夹统一走 classify + 规则解析（快且确定；LLM 管线仍在
            # /email-intelligence/process 单独可用）。业务类型 → review 队列，
            # 其余 → parsed；出站/杂项文件夹只多带 direction 展示元数据，
            # 不再强制 parsed（收件箱子文件夹/已发送里的 recap 一样要复核）。
            # 反馈记忆（忽略并记住）命中时分类降级为 general —— 不再进复核队列。
            to_recipients = [
                ((r or {}).get("emailAddress") or {}).get("address")
                for r in (m.get("toRecipients") or [])
            ]
            to_recipients = [t for t in to_recipients if t][:5]
            cls, suppressed = classify_with_memory(db, auth.tenant_id, subject, body, from_email)
            ctype = cls["type"]
            parse_result: dict = {"email_type": ctype, "source": "graph", "graph_id": str(mid)}
            if to_recipients:
                parse_result["to_recipients"] = to_recipients
            if suppressed:
                parse_result["suppressed_by_rule"] = suppressed["rule"]
                parse_result["original_classification"] = suppressed["original"]
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
            elif ctype == "bunker_offer":
                parse_result.update(parse_bunker_offer(body))
                status = "review"
            elif ctype == "port_disbursement":
                parse_result.update(parse_port_disbursement(body))
                status = "review"
            elif ctype == "invoice":
                parse_result.update(parse_invoice(body))
                status = "review"
            elif ctype == "claim":
                parse_result.update(parse_claim(body))
                status = "review"

            db.add(
                EmailMessage(
                    tenant_id=auth.tenant_id,
                    account_id=account.id,
                    thread_id=thread.id,
                    message_id=str(mid),
                    direction="outbound" if outbound_folder else "inbound",
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
    """解析结果一键落单：recap→估算+租约草稿 / NOR→盖 nor_at / SOF→装卸时间草稿 /
    bunkers→订油单 / PDA→使费草稿 / invoice→发票草稿 / claim→索赔记录。"""
    from app.services.email_actions import apply_message

    try:
        return apply_message(db, auth.tenant_id, auth.user_id, message_id)
    except LookupError as exc:
        raise HTTPException(404, "Message not found") from exc


class EmailIgnoreIn(BaseModel):
    remember: bool = True  # 记住这次误判（同源同类型不再提示）


def _email_type_of_row(row: EmailMessage) -> str:
    parse = row.parse_result or {}
    etype = str(parse.get("email_type") or "")
    if not etype:
        cls = parse.get("classification")
        if isinstance(cls, dict):
            etype = str(cls.get("type") or "")
    return etype or "general"


@router.post("/email/review/{message_id}/ignore")
def ignore_parse(
    message_id: UUID,
    body: EmailIgnoreIn | None = None,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """忽略这封邮件的自动判定；可选「记住」—— 同发件人/域名不再识别为该类型。

    记忆落在 ConfigService（租户作用域 JSON，key=email.classifier_ignore_rules），
    分类时经 classify_with_memory 命中即降级为 general，不再进复核队列。
    """
    from app.services.email_intelligence import add_ignore_rule

    row = db.get(EmailMessage, message_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Message not found")
    remember = True if body is None else bool(body.remember)
    etype = _email_type_of_row(row)
    rule = None
    if remember and etype not in ("general", "outbound", "outbound_reply"):
        from_pattern = str(row.from_email or "").strip().lower()
        if from_pattern:
            rule = add_ignore_rule(db, auth.tenant_id, etype, from_pattern, user_id=auth.user_id)
    parse = dict(row.parse_result or {})
    parse["ignored_at"] = datetime.now(timezone.utc).isoformat()
    if rule:
        parse["ignore_rule"] = rule
    row.parse_result = parse
    row.parse_status = "parsed"
    db.commit()
    return {"id": str(row.id), "status": "parsed", "remembered": rule}


@router.get("/email/ignore-rules")
def list_ignore_rules(
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """已记住的误判规则清单（可在 UI 里逐条撤销）。"""
    from app.services.email_intelligence import load_ignore_rules

    return {"rules": load_ignore_rules(db, auth.tenant_id)}


class EmailIgnoreRuleIn(BaseModel):
    email_type: str
    from_pattern: str


@router.delete("/email/ignore-rules")
def delete_ignore_rule(
    body: EmailIgnoreRuleIn,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """撤销一条「忽略并记住」的规则 —— 该来源同类型邮件恢复进复核队列。"""
    from app.services.email_intelligence import remove_ignore_rule

    removed = remove_ignore_rule(db, auth.tenant_id, body.email_type, body.from_pattern)
    if not removed:
        raise HTTPException(404, "Rule not found")
    return {"removed": removed}


#: 邮件可存档到的实体类型 → (模块码, 展示名)
ARCHIVE_ENTITY_TYPES: dict[str, str] = {
    "voyage": "operations",
    "port_disbursement": "operations",
    "bunker_order": "bunker",
    "claim": "claims",
    "invoice": "finance",
    "charter": "chartering",
    "estimate": "estimate",
    "laytime": "laytime",
}


class EmailArchiveIn(BaseModel):
    entity_type: str
    entity_id: UUID


@router.post("/email/messages/{message_id}/archive")
def archive_message(
    message_id: UUID,
    body: EmailArchiveIn,
    auth: AuthContext = Depends(require_module("email")),
    db: Session = Depends(get_db),
):
    """把邮件正文存档为项目附件（Attachment 版本化）+ OfficeResourceLink 关联。

    实体必须存在且属于本租户；附件落在 uploads/attachments/{tenant}/{type}/{id}/，
    与人工上传的附件同一列表、同一版本语义。
    """
    from app.models_wave1 import Attachment
    from app.security import tenant_has_module
    from app.services.audit import audit

    row = db.get(EmailMessage, message_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Message not found")
    etype = body.entity_type
    if etype not in ARCHIVE_ENTITY_TYPES:
        raise HTTPException(
            422, detail={"code": "UNKNOWN_ENTITY_TYPE", "allowed": sorted(ARCHIVE_ENTITY_TYPES)}
        )
    if not tenant_has_module(db, auth.tenant_id, ARCHIVE_ENTITY_TYPES[etype]):
        raise HTTPException(
            403, detail={"code": "MODULE_NOT_LICENSED", "module": ARCHIVE_ENTITY_TYPES[etype]}
        )
    from app.models_domain import (
        BunkerOrder,
        Charter,
        Claim,
        Estimate,
        Invoice,
        LaytimeCalc,
        PortDisbursement,
        Voyage,
    )

    entity_model = {
        "voyage": Voyage,
        "port_disbursement": PortDisbursement,
        "bunker_order": BunkerOrder,
        "claim": Claim,
        "invoice": Invoice,
        "charter": Charter,
        "estimate": Estimate,
        "laytime": LaytimeCalc,
    }[etype]
    entity = db.get(entity_model, body.entity_id)
    if entity is None or getattr(entity, "tenant_id", None) != auth.tenant_id:
        raise HTTPException(404, f"{etype} not found")

    # 正文落盘为 .eml 风格纯文本（Outlook 导出惯例 —— 带头信息，可直接打开核对）
    from app.services.files_store import store_entity_file

    stamp = (row.sent_at or row.created_at or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    safe_subject = re.sub(r"[^A-Za-z0-9._ -]+", "_", (row.subject or "email").strip())[:60].strip() or "email"
    filename = f"mail_{stamp}_{safe_subject}.eml.txt"
    content = (
        f"From: {row.from_email or ''}\n"
        f"Subject: {row.subject or ''}\n"
        f"Date: {row.sent_at.isoformat() if row.sent_at else ''}\n"
        f"Message-ID: {row.message_id or ''}\n"
        f"\n{row.body_text or ''}\n"
    ).encode("utf-8")

    next_version = (
        db.scalar(
            select(func.max(Attachment.version_no)).where(
                Attachment.tenant_id == auth.tenant_id,
                Attachment.entity_type == etype,
                Attachment.entity_id == body.entity_id,
            )
        )
        or 0
    ) + 1
    dest = store_entity_file(auth.tenant_id, etype, body.entity_id, next_version, filename, content)
    for prev in db.scalars(
        select(Attachment).where(
            Attachment.tenant_id == auth.tenant_id,
            Attachment.entity_type == etype,
            Attachment.entity_id == body.entity_id,
        )
    ).all():
        prev.is_current = False
    attachment = Attachment(
        tenant_id=auth.tenant_id,
        entity_type=etype,
        entity_id=body.entity_id,
        file_name=filename,
        file_path=str(dest),
        mime_type="text/plain",
        size=len(content),
        version_no=next_version,
        is_current=True,
        note=f"Archived email: {row.subject or ''}",
        uploaded_by=auth.user_id,
    )
    db.add(attachment)
    db.flush()

    # OfficeResourceLink：实体页「关联资源」里回溯原始邮件
    from app.services import office_hub

    office_hub.link_resource(
        db,
        auth.tenant_id,
        entity_type=etype,
        entity_id=body.entity_id,
        resource_kind="mail",
        resource_id=row.message_id or str(row.id),
        display_name=row.subject,
        meta={"email_message_db_id": str(row.id), "attachment_id": str(attachment.id)},
    )
    parse = dict(row.parse_result or {})
    archived = parse.get("archived_to") if isinstance(parse.get("archived_to"), list) else []
    archived.append({"entity_type": etype, "entity_id": str(body.entity_id), "attachment_id": str(attachment.id)})
    parse["archived_to"] = archived
    row.parse_result = parse
    audit(
        db,
        action="email.archive_to_entity",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type=etype,
        entity_id=body.entity_id,
        detail={"email_message_db_id": str(row.id), "attachment_id": str(attachment.id)},
    )
    db.commit()
    return {
        "attachment_id": str(attachment.id),
        "entity_type": etype,
        "entity_id": str(body.entity_id),
        "version_no": next_version,
        "download_url": f"/api/v1/files/{attachment.id}/download",
    }


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
