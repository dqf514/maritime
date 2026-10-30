"""邮件同步服务层 —— Graph 拉取 → 落库 → 分类/规则解析。

原先这套逻辑住在路由里（``routers/email_notify.py::_sync_graph_mails``），
定时例行任务（``routine.tick`` / ``email.sync_tick``）要在**没有 HTTP 上下文**的
job handler 里复用它，所以整体下沉到服务层：

- 路由端点行为**零变化**（响应体字段、错误码、通知、Teams 推送全部照旧）；
- 新增 ``SyncOutcome.new_message_ids`` —— 本次新增的 Graph message_id，
  供入站例行任务（触发腿）只处理新邮件、不重复扫描全量收件箱。

同步参数与手动同步端点分离：定时同步用更保守的窗口（天数/条数），
避免后台任务把 Graph 配额打满。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_wave1 import EmailAccount, EmailMessage, EmailThread, Notification
from app.services.identity import as_aware

log = logging.getLogger("marios.email_sync")

#: Graph / M365 邮箱 provider 标识
GRAPH_PROVIDERS = {"microsoft", "m365", "graph", "outlook"}

#: 出站语义的系统文件夹 —— 仅决定 direction 展示元数据（From 列显示收件人）
OUTBOUND_FOLDERS = {"sentitems", "drafts", "deleteditems", "junkemail", "archive", "outbox"}

#: 单次同步的全局条数预算 —— 杜绝多文件夹 × 大条数把系统拖垮
SYNC_GLOBAL_BUDGET = 2000

#: 定时同步的保守窗口（手动同步端点用 7/200 默认，定时再收窄一档）
SCHEDULED_SYNC_DAYS = 7
SCHEDULED_SYNC_COUNT = 200
SCHEDULED_SYNC_FOLDERS = ("inbox", "sentitems")


@dataclass
class SyncOutcome:
    """同步结果 —— ``payload`` 是对外响应体（与旧路由一致），其余是内部增量。"""

    payload: dict[str, Any] = field(default_factory=dict)
    new_message_ids: list[str] = field(default_factory=list)
    new_message_db_ids: list[str] = field(default_factory=list)


#: 文件夹 key 的安全字符（Graph wellKnownName / 自定义文件夹名 / folder id）
FOLDER_RE = re.compile(r"^[A-Za-z0-9=_.-]{1,128}$")

#: 单次同步允许的文件夹数上限
MAX_FOLDERS = 10


def parse_folders(folders: str) -> list[str]:
    """解析逗号分隔的文件夹列表，正则校验 + 去重 + 上限 10 个。"""
    parts = [f.strip() for f in (folders or "").split(",") if f.strip()]
    if not parts:
        return ["inbox"]
    if len(parts) > MAX_FOLDERS:
        raise HTTPException(422, detail={"code": "TOO_MANY_FOLDERS", "message": "max 10 folders per sync"})
    for p in parts:
        if not FOLDER_RE.match(p):
            raise HTTPException(422, detail={"code": "INVALID_FOLDER", "folder": p})
    return list(dict.fromkeys(parts))


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


def sync_graph_mails(
    db: Session,
    *,
    tenant_id,
    user_id=None,
    account: EmailAccount,
    days: int = SCHEDULED_SYNC_DAYS,
    count: int = SCHEDULED_SYNC_COUNT,
    folders: list[str] | tuple[str, ...] = SCHEDULED_SYNC_FOLDERS,
) -> SyncOutcome:
    """拉取已连接的 Graph 邮箱并落进复核管线（按 Graph message id 去重）。

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
        client = office_hub.get_graph_client(db, tenant_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, detail={"code": "GRAPH_SYNC_FAILED", "message": str(exc)}) from exc

    since = datetime.now(timezone.utc) - timedelta(days=days)
    # inbox 永远排第一：复核队列优先于参考浏览
    ordered = sorted({str(f) for f in folders}, key=lambda f: (f.lower() != "inbox", f.lower()))

    synced = 0
    review = 0
    capped = False
    folder_counts: dict[str, int] = {}
    new_message_ids: list[str] = []
    new_message_db_ids: list[str] = []
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
                    EmailMessage.tenant_id == tenant_id, EmailMessage.message_id == str(mid)
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
                    EmailThread.tenant_id == tenant_id, EmailThread.thread_key == thread_key
                )
            )
            if not thread:
                thread = EmailThread(
                    tenant_id=tenant_id,
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
            cls, suppressed = classify_with_memory(db, tenant_id, subject, body, from_email)
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
            elif ctype == "noon_report":
                # 午报走例行任务中枢；这里只保留类型，不生成估算/租约草稿，
                # 也不进入 NOR 复核队列（避免误出「填入航次计算」）。
                status = "parsed"
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

            row = EmailMessage(
                tenant_id=tenant_id,
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
            db.add(row)
            db.flush()
            new_message_ids.append(str(mid))
            new_message_db_ids.append(str(row.id))
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
                tenant_id=tenant_id,
                user_id=user_id,
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
            tenant_id,
            title="Mailbox review queue",
            lines=[
                f"{review} business email(s) awaiting review from {account.email}",
                "Open Email Review to create drafts (recap → estimate, NOR → voyage, SOF → laytime).",
            ],
            href="/email/review",
        )
        db.commit()
    return SyncOutcome(
        payload={
            "synced": synced,
            "review_queue": review,
            "provider": "microsoft",
            "mode": getattr(client, "mode", "live"),
            "window_days": days,
            "count_cap": count,
            "folders": folder_counts,
            "capped": capped,
        },
        new_message_ids=new_message_ids,
        new_message_db_ids=new_message_db_ids,
    )
