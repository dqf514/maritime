"""邮件闭环动作 — 解析结果 → 业务草稿 / 生成回复。

邮件复核此前只把 parse_result 存成 JSON 给人看，数据到此为止。本模块把
解析结果真正接进业务对象：

- fixture recap → 估算草稿（Estimate，inputs 预填成交条款，来源邮件以
  OfficeResourceLink(resource_kind="mail") 挂回实体）
- NOR → 匹配航次盖 nor_at（PortCall.nor_at + Voyage.meta 快照）
- laytime statement → LaytimeCalc 草稿（SOF 事件 + allowed days 预填）
- 回复生成：按模板（确认成交 / 还盘 / NOR 确认 / 装卸时间质询 / 普通）
  渲染英文业务回函，经平台发送通道（SMTP/Graph/console）投递并回写
  同一线程的 outbound EmailMessage + OutboundMailLog 审计。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import (
    BunkerOrder,
    Charter,
    Claim,
    Estimate,
    Invoice,
    LaytimeCalc,
    PortDisbursement,
    PortCall,
    Voyage,
)
from app.services.domain_events import emit
from app.models_wave1 import (
    Counterparty,
    CounterpartyContact,
    EmailMessage,
    EmailThread,
    Vessel,
)

# 回复模板（正文为英文业务函件 — 航运商务邮件惯例；UI 文案走 i18n）
REPLY_TEMPLATES: tuple[str, ...] = (
    "ack_recap",
    "counter_offer",
    "nor_ack",
    "laytime_query",
    "general",
)

_DT_FORMATS = (
    "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M",
    "%d-%m-%Y %H:%M",
    "%d.%m.%Y %H:%M",
    "%Y-%m-%d %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y-%m-%d",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip().rstrip("LT").strip()
    # 带秒 / ISO 格式优先
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _extract_email_address(raw: str | None) -> str | None:
    if not raw:
        return None
    m = re.search(r"<([^<>]+@[^<>]+)>", raw)
    if m:
        return m.group(1).strip().lower()
    m = re.search(r"([\w.+-]+@[\w-]+\.[\w.-]+)", raw)
    return m.group(1).strip().lower() if m else None


def _flat_fields(parse: dict) -> dict:
    """合并多代落库形状：graph 同步存平铺字段；LLM 管线存 fixture_recap/nor/laytime 子字典。"""
    merged: dict[str, Any] = {}
    for key in ("fixture_recap", "nor", "laytime", "bunker_offer", "port_disbursement", "invoice", "claim"):
        sub = parse.get(key)
        if isinstance(sub, dict):
            merged.update({k: v for k, v in sub.items() if k not in ("_source", "_rule_diffs") and v is not None})
    # 平铺键直接并入（含 events 列表；排除嵌套 dict：matched/classification/applied 等有专门读取路径）
    merged.update({k: v for k, v in parse.items() if not isinstance(v, dict) and v is not None})
    # events 兜底：子字典形状时从 laytime 取
    if not merged.get("events"):
        sub = parse.get("laytime")
        if isinstance(sub, dict) and sub.get("events"):
            merged["events"] = sub["events"]
    return merged


def _email_type_of(parse: dict) -> str:
    etype = parse.get("email_type") or ""
    if not etype or etype == "outbound_reply":
        cls = parse.get("classification")
        if isinstance(cls, dict):
            etype = cls.get("type") or etype
    return str(etype or "general")


def _match_vessel(db: Session, tenant_id: UUID, name: str | None) -> Vessel | None:
    if not name:
        return None
    clean = re.sub(r"^(?:m\.?v\.?|mv\.?|ss\.?)\s*", "", str(name).strip(), flags=re.I)
    # 精确 → 剥前缀精确 → 包含（邮件里常带 IMO / 备注）
    for candidate in (str(name).strip(), clean):
        hit = db.scalar(
            select(Vessel).where(Vessel.tenant_id == tenant_id, Vessel.name.ilike(candidate)).limit(1)
        )
        if hit:
            return hit
    return db.scalar(
        select(Vessel)
        .where(Vessel.tenant_id == tenant_id, Vessel.name.ilike(f"%{clean}%"))
        .limit(1)
    )


def _vessel_from_subject(db: Session, tenant_id: UUID, subject: str | None) -> Vessel | None:
    """主题里的船名回退匹配 —— 新类型（油/使费/发票/索赔）规则抽取不出 vessel，
    但航运惯例把船名写在主题（"Bunker offer — Ocean Star"），按租户船舶逐条探测。"""
    if not subject:
        return None
    text = str(subject)
    for v in db.scalars(select(Vessel).where(Vessel.tenant_id == tenant_id)).all():
        clean = re.sub(r"^(?:m\.?v\.?|mv\.?|ss\.?)\s*", "", v.name.strip(), flags=re.I)
        if v.name.lower() in text.lower() or (clean and clean.lower() in text.lower()):
            return v
    return None


def _match_voyage(db: Session, tenant_id: UUID, vessel: Vessel | None, hint: str | None = None) -> Voyage | None:
    """航次匹配：vessel_id 优先（取最近的未完成航次），主题里的航次号兜底。"""
    if vessel:
        rows = db.scalars(
            select(Voyage)
            .where(
                Voyage.tenant_id == tenant_id,
                Voyage.vessel_id == vessel.id,
                Voyage.status != "deleted",
            )
            .order_by(Voyage.created_at.desc())
        ).all()
        active = [v for v in rows if v.status not in ("completed", "cancelled")]
        if active:
            return active[0]
        if rows:
            return rows[0]
    if hint:
        m = re.search(r"\b([A-Z]{2,4}-?\d{2,5})\b", str(hint))
        if m:
            return db.scalar(
                select(Voyage).where(
                    Voyage.tenant_id == tenant_id,
                    Voyage.voyage_no.ilike(m.group(1)),
                ).limit(1)
            )
    return None


def _counterparty_from(db: Session, tenant_id: UUID, parse: dict, fields: dict) -> tuple[UUID | None, str | None]:
    """对手方：发件人邮箱命中的联系人最准；否则用 Charterers/Owners 名称模糊匹配。"""
    matched = parse.get("matched")
    if isinstance(matched, dict) and matched.get("counterparty_id"):
        return UUID(str(matched["counterparty_id"])), matched.get("counterparty_name")
    sender = _extract_email_address(str(parse.get("from_email") or ""))
    if sender:
        hit = db.execute(
            select(CounterpartyContact, Counterparty.name)
            .join(Counterparty, CounterpartyContact.counterparty_id == Counterparty.id)
            .where(
                CounterpartyContact.tenant_id == tenant_id,
                CounterpartyContact.email.ilike(sender),
            )
            .limit(1)
        ).first()
        if hit:
            contact, name = hit
            return contact.counterparty_id, name
    for key in ("charterers", "owners"):
        name = fields.get(key)
        if isinstance(name, str) and name.strip():
            hit = db.scalar(
                select(Counterparty)
                .where(
                    Counterparty.tenant_id == tenant_id,
                    Counterparty.name.ilike(f"%{name.strip()[:60]}%"),
                )
                .limit(1)
            )
            if hit:
                return hit.id, hit.name
    return None, None


def _link_source_email(db: Session, tenant_id: UUID, entity_type: str, entity_id: UUID, msg: EmailMessage) -> None:
    """把源邮件挂回业务实体（OfficeResourceLink=mail），实体页可回溯原始邮件。"""
    from app.services import office_hub

    office_hub.link_resource(
        db,
        tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        resource_kind="mail",
        resource_id=msg.message_id or str(msg.id),
        display_name=msg.subject,
        meta={"email_message_db_id": str(msg.id), "from_email": msg.from_email},
    )


def _source_meta(msg: EmailMessage) -> dict:
    return {
        "email_message_db_id": str(msg.id),
        "message_id": msg.message_id,
        "subject": msg.subject,
        "from_email": msg.from_email,
    }


def _dec(value: Any, places: str) -> Decimal | None:
    """邮件解析值 → Decimal 量化（Numeric 列写入边界，ROUND_HALF_UP 显式舍入）。"""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    except Exception:  # noqa: BLE001 — 解析值不可信，回 None 由人工补
        return None


def _parse_date(raw: Any) -> date | None:
    dt = _parse_dt(str(raw) if raw is not None else None)
    return dt.date() if dt else None


def _match_counterparty_name(db: Session, tenant_id: UUID, name: str | None) -> tuple[UUID | None, str | None]:
    """按名称模糊匹配对手方（供油方/代理/账单方）。"""
    if not isinstance(name, str) or not name.strip():
        return None, None
    hit = db.scalar(
        select(Counterparty)
        .where(
            Counterparty.tenant_id == tenant_id,
            Counterparty.name.ilike(f"%{name.strip()[:60]}%"),
            Counterparty.deleted_at.is_(None),
        )
        .limit(1)
    )
    return (hit.id, hit.name) if hit else (None, None)


def apply_message(db: Session, tenant_id: UUID, user_id: UUID | None, message_id: UUID) -> dict:
    """把一封已解析的业务邮件落成业务草稿；成功后消息置为 parsed 并记录 applied 清单。

    返回 ``{"created": [...], "warnings": [...], "hints": [...]}`` —— 不可自动落单的
    类型走 hints 明示原因，而不是静默失败。
    """
    msg = db.get(EmailMessage, message_id)
    if not msg or msg.tenant_id != tenant_id:
        raise LookupError("message not found")
    if msg.direction == "outbound":
        return {"created": [], "warnings": ["outbound_message"], "hints": []}

    parse = dict(msg.parse_result or {})
    if parse.get("applied"):
        # 幂等：已落过单的邮件不重复生成草稿
        return {
            "message_id": str(msg.id),
            "email_type": _email_type_of(parse),
            "created": [],
            "warnings": [],
            "hints": ["already_applied"],
        }
    etype = _email_type_of(parse)
    fields = _flat_fields(parse)
    # 键名兼容：规则抽取用 vessel；demo/旧落库形状用 vessel_name；
    # 都没有时按主题里的船名回退（"Bunker offer — Ocean Star" 这类航运惯例）
    vessel = _match_vessel(db, tenant_id, fields.get("vessel") or fields.get("vessel_name"))
    if vessel is None:
        vessel = _vessel_from_subject(db, tenant_id, msg.subject)
    created: list[dict] = []
    warnings: list[str] = []
    hints: list[str] = []

    if etype in ("fixture_recap", "recap"):
        from app.services.doc_numbering import next_doc_number

        cp_id, cp_name = _counterparty_from(db, tenant_id, parse, fields)
        inputs = {
            k: fields.get(k)
            for k in (
                "cargo",
                "load_port",
                "discharge_port",
                "laycan",
                "freight_rate",
                "demurrage_rate",
                "despatch_rate",
                "laytime_load",
                "laytime_discharge",
                "commission",
            )
            if fields.get(k) is not None
        }
        inputs["source_email"] = _source_meta(msg)
        title = (
            f"Recap draft: {fields.get('vessel') or vessel and vessel.name or msg.subject or 'email'}"
        )[:200]
        est = Estimate(
            tenant_id=tenant_id,
            title=title,
            mode="voyage",
            vessel_id=vessel.id if vessel else None,
            counterparty_id=cp_id,
            inputs=inputs,
            results={},
            status="draft",
            created_by=user_id,
        )
        db.add(est)
        db.flush()
        _link_source_email(db, tenant_id, "estimate", est.id, msg)
        created.append(
            {
                "entity": "estimate",
                "id": str(est.id),
                "title": est.title,
                "href": f"/estimates/{est.id}",
                "counterparty": cp_name,
                "vessel": vessel.name if vessel else None,
            }
        )
        if not vessel:
            warnings.append("vessel_not_matched")
        # 租约草稿（P2）：recap 落估算的同时挂一份 CP 草稿，商务可在租约页接着谈条款
        laycan = str(fields.get("laycan") or "")
        laycan_from = _parse_date(laycan.split("-")[0]) if laycan else None
        laycan_to = _parse_date(laycan.split("-")[-1]) if laycan else None
        charter = Charter(
            tenant_id=tenant_id,
            created_by=user_id,
            charter_no=next_doc_number(db, tenant_id, Charter, Charter.charter_no, "CP"),
            charter_type="voyage",
            status="draft",
            vessel_id=vessel.id if vessel else None,
            counterparty_id=cp_id,
            estimate_id=est.id,
            laycan_from=laycan_from,
            laycan_to=laycan_to,
            commission_pct=_dec(fields.get("commission"), "0.01"),
            freight_rate=_dec(fields.get("freight_rate"), "0.0001"),
            demurrage_rate=_dec(fields.get("demurrage_rate"), "0.01"),
            despatch_rate=_dec(fields.get("despatch_rate"), "0.01"),
            freight_terms={"source_email": _source_meta(msg), "laycan_raw": laycan or None},
        )
        db.add(charter)
        db.flush()
        _link_source_email(db, tenant_id, "charter", charter.id, msg)
        created.append(
            {
                "entity": "charter",
                "id": str(charter.id),
                "title": charter.charter_no,
                "href": f"/charters/{charter.id}",
                "counterparty": cp_name,
                "vessel": vessel.name if vessel else None,
            }
        )

    elif etype == "nor":
        voyage = _match_voyage(db, tenant_id, vessel, hint=msg.subject)
        if voyage is None:
            warnings.append("voyage_not_matched")
        else:
            nor_dt = _parse_dt(fields.get("date_time")) or _parse_dt(fields.get("time")) or msg.sent_at or _now()
            if nor_dt.tzinfo is None:
                nor_dt = nor_dt.replace(tzinfo=timezone.utc)
            pc = db.scalar(
                select(PortCall)
                .where(PortCall.tenant_id == tenant_id, PortCall.voyage_id == voyage.id)
                .order_by(PortCall.seq)
                .limit(1)
            )
            if pc is not None:
                pc.nor_at = nor_dt
            voyage.meta = {
                **(voyage.meta or {}),
                "nor_at": nor_dt.isoformat(),
                "nor_email": _source_meta(msg),
                "nor_port": fields.get("port"),
            }
            db.flush()
            _link_source_email(db, tenant_id, "voyage", voyage.id, msg)
            # 域事件：NOR 落位 → Ops 通知（services/automation.py）
            emit(
                db, tenant_id, "portcall.nor_updated", "voyage", voyage.id,
                payload={
                    "voyage_no": voyage.voyage_no,
                    "nor_at": nor_dt.isoformat(),
                    "port": fields.get("port"),
                    "port_call_id": str(pc.id) if pc is not None else None,
                },
                user_id=user_id,
            )
            created.append(
                {
                    "entity": "voyage",
                    "id": str(voyage.id),
                    "action": "nor_stamped",
                    "nor_at": nor_dt.isoformat(),
                    "port_call": str(pc.id) if pc is not None else None,
                    "href": f"/operations/voyages/{voyage.id}",
                    "voyage_no": voyage.voyage_no,
                }
            )

    elif etype == "laytime_statement":
        voyage = _match_voyage(db, tenant_id, vessel, hint=msg.subject)
        inputs = {
            "sof_events": fields.get("events") or [],
            "allowed_days": fields.get("allowed_days"),
            "source_email": _source_meta(msg),
        }
        calc = LaytimeCalc(
            tenant_id=tenant_id,
            voyage_id=voyage.id if voyage else None,
            booking_reference=None,
            inputs={k: v for k, v in inputs.items() if v is not None},
        )
        db.add(calc)
        db.flush()
        _link_source_email(db, tenant_id, "laytime", calc.id, msg)
        # 域事件：邮件生成装卸时间草稿 → Ops 复核任务（services/automation.py）
        emit(
            db, tenant_id, "laytime.draft_created", "laytime", calc.id,
            payload={
                "voyage_id": str(voyage.id) if voyage else None,
                "voyage_no": voyage.voyage_no if voyage else None,
                "events": len(inputs["sof_events"] or []),
            },
            user_id=user_id,
        )
        if voyage is None:
            warnings.append("voyage_not_matched")
        created.append(
            {
                "entity": "laytime",
                "id": str(calc.id),
                "action": "draft_created",
                "events": len(inputs["sof_events"] or []),
                "voyage": voyage.voyage_no if voyage else None,
                "href": f"/finance/laytimes?id={calc.id}",
            }
        )

    elif etype == "bunker_offer":
        voyage = _match_voyage(db, tenant_id, vessel, hint=msg.subject)
        supplier_cp_id, supplier_name = _match_counterparty_name(db, tenant_id, fields.get("supplier"))
        cp_id, cp_name = _counterparty_from(db, tenant_id, parse, fields)
        order = BunkerOrder(
            tenant_id=tenant_id,
            created_by=user_id,
            order_no=f"BNK-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}",
            status="planned",
            vessel_id=vessel.id if vessel else None,
            voyage_id=voyage.id if voyage else None,
            grade=str(fields.get("grade") or "VLSFO"),
            qty_ordered=_dec(fields.get("qty_ordered"), "0.001"),
            unit_price=_dec(fields.get("unit_price"), "0.01"),
            currency=str(fields.get("currency") or "USD").upper()[:3],
            supplier=fields.get("supplier"),
            counterparty_id=supplier_cp_id or cp_id,
        )
        db.add(order)
        db.flush()
        _link_source_email(db, tenant_id, "bunker_order", order.id, msg)
        if not vessel:
            warnings.append("vessel_not_matched")
        if order.unit_price is None:
            warnings.append("unit_price_missing")
        created.append(
            {
                "entity": "bunker_order",
                "id": str(order.id),
                "title": order.order_no,
                "action": "draft_created",
                "href": f"/bunker?order={order.id}",
                "vessel": vessel.name if vessel else None,
                "supplier": supplier_name or cp_name,
            }
        )

    elif etype == "port_disbursement":
        voyage = _match_voyage(db, tenant_id, vessel, hint=msg.subject)
        pc = None
        if voyage is not None:
            pc = db.scalar(
                select(PortCall)
                .where(PortCall.tenant_id == tenant_id, PortCall.voyage_id == voyage.id)
                .order_by(PortCall.seq)
                .limit(1)
            )
        pda = PortDisbursement(
            tenant_id=tenant_id,
            voyage_id=voyage.id if voyage else None,
            port_call_id=pc.id if pc is not None else None,
            status="draft",
            pda_amount=_dec(fields.get("pda_amount"), "0.01"),
            fda_amount=_dec(fields.get("fda_amount"), "0.01"),
            currency=str(fields.get("currency") or "USD").upper()[:3],
            lines={
                "source_email": _source_meta(msg),
                "port": fields.get("port"),
                "agent": fields.get("agent"),
            },
        )
        db.add(pda)
        db.flush()
        _link_source_email(db, tenant_id, "port_disbursement", pda.id, msg)
        if voyage is None:
            warnings.append("voyage_not_matched")
        created.append(
            {
                "entity": "port_disbursement",
                "id": str(pda.id),
                "action": "draft_created",
                "href": f"/operations/voyages{f'?tab=pda&id={pda.id}' if voyage else ''}",
                "voyage": voyage.voyage_no if voyage else None,
                "port": fields.get("port"),
            }
        )

    elif etype == "invoice":
        from app.services.doc_numbering import next_doc_number

        voyage = _match_voyage(db, tenant_id, vessel, hint=msg.subject)
        cp_id, cp_name = _counterparty_from(db, tenant_id, parse, fields)
        amount = _dec(fields.get("amount"), "0.01")
        if amount is None or amount <= 0:
            # 与 /invoices 的 INVALID_AMOUNT 口径一致 —— 零金额发票没有业务含义
            hints.append("invoice_amount_missing")
            warnings.append("invoice_amount_missing")
        else:
            inv = Invoice(
                tenant_id=tenant_id,
                invoice_no=next_doc_number(db, tenant_id, Invoice, Invoice.invoice_no, "INV"),
                invoice_type="freight",
                status="draft",
                counterparty_id=cp_id,
                voyage_id=voyage.id if voyage else None,
                currency=str(fields.get("currency") or "USD").upper()[:3],
                amount=amount,
                tax_amount=Decimal("0.00"),
                paid_amount=Decimal("0.00"),
                due_date=_parse_date(fields.get("due_date")),
                meta={"source_email": _source_meta(msg), "invoice_no_ref": fields.get("invoice_no_ref")},
                created_by=user_id,
            )
            db.add(inv)
            db.flush()
            _link_source_email(db, tenant_id, "invoice", inv.id, msg)
            if voyage is None:
                warnings.append("voyage_not_matched")
            created.append(
                {
                    "entity": "invoice",
                    "id": str(inv.id),
                    "title": inv.invoice_no,
                    "action": "draft_created",
                    "href": f"/finance/invoices/{inv.id}",
                    "counterparty": cp_name,
                    "amount": float(amount),
                }
            )

    elif etype == "claim":
        voyage = _match_voyage(db, tenant_id, vessel, hint=msg.subject)
        cp_id, cp_name = _counterparty_from(db, tenant_id, parse, fields)
        amount = _dec(fields.get("amount"), "0.01")
        # 索赔必须挂靠一个业务对象或一个非零金额（与 /claims 创建口径一致）
        if voyage is None and (amount is None or amount == 0):
            hints.append("claim_needs_anchor")
            warnings.append("claim_needs_anchor")
        else:
            claim_type = str(fields.get("claim_type") or "demurrage")
            from app.services.claim_taxonomy import is_valid_claim_type

            if not is_valid_claim_type(claim_type):
                claim_type = "demurrage"
            claim = Claim(
                tenant_id=tenant_id,
                created_by=user_id,
                claim_no=f"CL-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}",
                claim_type=claim_type,
                status="open",
                voyage_id=voyage.id if voyage else None,
                amount=amount,
                currency=str(fields.get("currency") or "USD").upper()[:3],
                time_bar=_parse_date(fields.get("time_bar")),
                notes=f"From email: {msg.subject or msg.id}",
                contact_id=None,
            )
            db.add(claim)
            db.flush()
            _link_source_email(db, tenant_id, "claim", claim.id, msg)
            created.append(
                {
                    "entity": "claim",
                    "id": str(claim.id),
                    "title": claim.claim_no,
                    "action": "draft_created",
                    "href": f"/finance/claims/{claim.id}",
                    "counterparty": cp_name,
                    "voyage": voyage.voyage_no if voyage else None,
                }
            )

    else:
        hints.append(f"no_auto_draft_for_{etype or 'unknown'}")

    if created:
        msg.parse_status = "parsed"
        parse["applied_at"] = _now().isoformat()
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
    fields = _flat_fields(dict(msg.parse_result or {}))
    fields.setdefault("from_email", msg.from_email)
    to_email = str(extra.get("to_email") or _extract_email_address(msg.from_email) or "").strip()
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
        sent_at=_now(),
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
