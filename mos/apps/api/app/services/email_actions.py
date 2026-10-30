"""邮件闭环动作 — 解析结果 → 业务草稿 / 生成回复。

邮件复核此前只把 parse_result 存成 JSON 给人看，数据到此为止。本模块把
解析结果真正接进业务对象：

- 业务写回（7 类）已下沉到 :mod:`app.services.email_writeback`（可复用的 creator），
  本模块只做**编排**：按邮件类型选 creator、汇总 created/warnings/hints、
  回写「已应用」标记。对外行为与旧版逐字一致。
- 回复生成：按模板（确认成交 / 还盘 / NOR 确认 / 装卸时间质询 / 普通）
  渲染英文业务回函，经平台发送通道（SMTP/Graph/console）投递并回写
  同一线程的 outbound EmailMessage + OutboundMailLog 审计。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models_wave1 import EmailMessage, EmailThread
from app.services.email_writeback import (
    counterparty_from,
    create_bunker_order,
    create_claim,
    create_estimate_charter_from_recap,
    create_invoice,
    create_laytime_calc,
    create_port_disbursement,
    email_type_of,
    extract_email_address,
    flat_fields,
    now_utc,
    resolve_vessel,
    stamp_nor_on_voyage,
)

# 回复模板（正文为英文业务函件 — 航运商务邮件惯例；UI 文案走 i18n）
REPLY_TEMPLATES: tuple[str, ...] = (
    "ack_recap",
    "counter_offer",
    "nor_ack",
    "laytime_query",
    "general",
)


def apply_message(db: Session, tenant_id: UUID, user_id: UUID | None, message_id: UUID) -> dict:
    """把一封已解析的业务邮件落成业务草稿；成功后消息置为 parsed 并记录 applied 清单。

    返回 ``{"created": [...], "warnings": [...], "hints": [...]}`` —— 不可自动落单的
    类型走 hints 明示原因，而不是静默失败。
    """
    msg = db.get(EmailMessage, message_id)
    if not msg or msg.tenant_id != tenant_id:
        raise LookupError("message not found")

    parse = dict(msg.parse_result or {})
    etype = email_type_of(parse)
    # 出站方向只拦「未分类/系统回写」的行（outbound/outbound_reply）——
    # Sent Items 里被分类为业务类型的邮件同样可落单（同步不再按方向强制 parsed）
    if msg.direction == "outbound" and etype in ("outbound", "outbound_reply"):
        return {"created": [], "warnings": ["outbound_message"], "hints": []}

    if parse.get("applied"):
        # 幂等：已落过单的邮件不重复生成草稿
        return {
            "message_id": str(msg.id),
            "email_type": email_type_of(parse),
            "created": [],
            "warnings": [],
            "hints": ["already_applied"],
        }
    fields = flat_fields(parse)
    vessel = resolve_vessel(db, tenant_id, fields, msg.subject)
    created: list[dict] = []
    warnings: list[str] = []
    hints: list[str] = []

    if etype in ("fixture_recap", "recap"):
        cp_id, cp_name = counterparty_from(db, tenant_id, parse, fields)
        created, warnings, hints = create_estimate_charter_from_recap(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            msg=msg,
            fields=fields,
            vessel=vessel,
            cp_id=cp_id,
            cp_name=cp_name,
        )

    elif etype == "nor":
        created, warnings, hints = stamp_nor_on_voyage(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            msg=msg,
            fields=fields,
            vessel=vessel,
        )

    elif etype == "laytime_statement":
        created, warnings, hints = create_laytime_calc(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            msg=msg,
            fields=fields,
            vessel=vessel,
        )

    elif etype == "bunker_offer":
        created, warnings, hints = create_bunker_order(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            msg=msg,
            fields=fields,
            vessel=vessel,
            parse=parse,
        )

    elif etype == "port_disbursement":
        created, warnings, hints = create_port_disbursement(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            msg=msg,
            fields=fields,
            vessel=vessel,
        )

    elif etype == "invoice":
        created, warnings, hints = create_invoice(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            msg=msg,
            fields=fields,
            vessel=vessel,
            parse=parse,
        )

    elif etype == "claim":
        created, warnings, hints = create_claim(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            msg=msg,
            fields=fields,
            vessel=vessel,
            parse=parse,
        )

    else:
        hints.append(f"no_auto_draft_for_{etype or 'unknown'}")

    if created:
        msg.parse_status = "parsed"
        parse["applied_at"] = now_utc().isoformat()
        parse["applied"] = created
        msg.parse_result = parse
    db.commit()
    return {"message_id": str(msg.id), "email_type": etype, "created": created, "warnings": warnings, "hints": hints}


# ── 回复生成 ────────────────────────────────────────────────────────────


def _num(fields: dict, key: str) -> str:
    v = fields.get(key)
    if v is None:
        return "—"
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def render_reply_body(template: str, fields: dict, extra: dict) -> str:
    """英文业务回函模板；extra 提供个性化覆盖（counter_offer 的 rate 等）。"""
    vessel = fields.get("vessel") or fields.get("vessel_name") or extra.get("vessel") or "the vessel"
    ports = f"{fields.get('load_port') or '—'} – {fields.get('discharge_port') or '—'}"
    rate = extra.get("freight_rate") or _num(fields, "freight_rate")
    laycan = fields.get("laycan") or "per CP"
    cargo = fields.get("cargo") or "the scheduled cargo"

    if template == "ack_recap":
        return (
            f"Dear Principals,\n\n"
            f"We confirm the fixture recap as below, please treat this email as our formal confirmation:\n\n"
            f"  Vessel:      {vessel}\n"
            f"  Cargo:       {cargo}\n"
            f"  Laycan:      {laycan}\n"
            f"  Load – Disch: {ports}\n"
            f"  Freight:     USD {_num(fields, 'freight_rate')} PMT\n"
            f"  Demurrage:   USD {_num(fields, 'demurrage_rate')}/day\n"
            f"  Despatch:    USD {_num(fields, 'despatch_rate')}/day\n\n"
            f"Kindly revert immediately should any term differ from your recap.\n\n"
            f"Best regards,\nMariOS Operations"
        )
    if template == "counter_offer":
        comment = extra.get("comment") or "market conditions"
        return (
            f"Dear Principals,\n\n"
            f"Thank you for your offer on {vessel} ({ports}, laycan {laycan}).\n"
            f"After careful review we are able to counter as follows:\n\n"
            f"  Freight: USD {rate} PMT (all other terms as per your recap)\n\n"
            f"This offer is subject to your acceptance within 24 hours, "
            f"considering current {comment}.\n\n"
            f"Best regards,\nMariOS Operations"
        )
    if template == "nor_ack":
        port = fields.get("port") or "the load port"
        when = fields.get("date_time") or fields.get("time") or "as tendered"
        return (
            f"Dear Principals,\n\n"
            f"We acknowledge Notice of Readiness tendered for {vessel} at {port} "
            f"({when}).\nTime shall count in accordance with the terms of the Charter Party.\n\n"
            f"Please find our records for any discrepancy at your earliest convenience.\n\n"
            f"Best regards,\nMariOS Operations"
        )
    if template == "laytime_query":
        events = fields.get("events") or []
        allowed = fields.get("allowed_days")
        return (
            f"Dear Principals,\n\n"
            f"We are in receipt of your laytime statement concerning {vessel} "
            f"({len(events)} SOF event(s), allowed {allowed if allowed is not None else '—'} day(s)).\n"
            f"We reserve the right to comment after our internal reconciliation "
            f"against SOF and CP terms.\n\n"
            f"Comments: {extra.get('comment') or '[to be completed]'}\n\n"
            f"Best regards,\nMariOS Operations"
        )
    # general
    intro = extra.get("comment") or "We refer to your email below."
    return f"Dear Principals,\n\n{intro}\n\nBest regards,\nMariOS Operations"


def _quote_original(msg: EmailMessage, max_lines: int = 15) -> str:
    body = (msg.body_text or "").strip()
    if not body:
        return ""
    lines = body.splitlines()[:max_lines]
    quoted = "\n".join(f"> {ln}" for ln in lines)
    if len(body.splitlines()) > max_lines:
        quoted += "\n> [...]"
    return quoted


def render_reply(
    db: Session, tenant_id: UUID, message_id: UUID, template: str, extra: dict | None = None
) -> dict:
    """仅渲染不发送 —— UI 预览用。"""
    msg = db.get(EmailMessage, message_id)
    if not msg or msg.tenant_id != tenant_id:
        raise LookupError("message not found")
    if template not in REPLY_TEMPLATES:
        raise ValueError(f"unknown template: {template}")
    extra = extra or {}
    fields = flat_fields(dict(msg.parse_result or {}))
    fields.setdefault("from_email", msg.from_email)
    to_email = str(extra.get("to_email") or extract_email_address(msg.from_email) or "").strip()
    if not to_email:
        raise ValueError("cannot resolve recipient address")
    # body_override：UI 里用户所见即所发（预览已含引用原文）；无 override 走服务端模板渲染
    override = str(extra.get("body_override") or "").strip()
    if override:
        body = override
    else:
        body = render_reply_body(template, fields, extra)
        quote = _quote_original(msg)
        if quote:
            body = f"{body}\n\n----- Original message -----\n{quote}"
    subject = msg.subject or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}" if subject else "Re: (no subject)"
    return {"to": to_email, "subject": subject, "body": body, "template": template}


def send_reply(
    db: Session, tenant_id: UUID, user_id: UUID | None, message_id: UUID, template: str, extra: dict | None = None
) -> dict:
    """渲染并通过平台发送通道投递；回写同线程 outbound 消息 + OutboundMailLog 审计。"""
    from app.services.identity import send_mail

    rendered = render_reply(db, tenant_id, message_id, template, extra)
    msg = db.get(EmailMessage, message_id)
    log = send_mail(
        db,
        to_email=rendered["to"],
        subject=rendered["subject"],
        body=rendered["body"],
        purpose="email.reply",
        tenant_id=tenant_id,
        meta={"email_message_db_id": str(msg.id), "template": template, "user_id": str(user_id) if user_id else None},
    )
    out = EmailMessage(
        tenant_id=tenant_id,
        account_id=msg.account_id,
        thread_id=msg.thread_id,
        message_id=f"<marios-reply-{uuid4().hex[:12]}>",
        direction="outbound",
        from_email=None,
        subject=rendered["subject"],
        body_text=rendered["body"][:20000],
        sent_at=now_utc(),
        parse_status="parsed",
        parse_result={
            "email_type": "outbound_reply",
            "template": template,
            "reply_to": str(msg.id),
            "channel": log.channel,
            "delivery_status": log.status,
        },
    )
    db.add(out)
    if msg.thread_id:
        thread = db.get(EmailThread, msg.thread_id)
        if thread is not None:
            thread.message_count = (thread.message_count or 0) + 1
            thread.last_message_at = out.sent_at
    db.commit()
    db.refresh(out)
    return {
        "mail_log_id": str(log.id),
        "outbound_message_id": str(out.id),
        "channel": log.channel,
        "status": log.status,
        "to": rendered["to"],
        "subject": rendered["subject"],
    }
