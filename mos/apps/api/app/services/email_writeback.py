"""邮件写回层 —— 解析字段 → 业务对象（可复用 creator）。

原先这段逻辑是 ``services/email_actions.py::apply_message`` 里的一长串分支。
抽出来的原因：**写回要被两个调用方复用**——

1. 邮件复核页的「生成业务草稿」（``email_actions.apply_message``，行为不变）
2. 例行任务中枢的写回腿（``services/routine_writeback.py``）—— 人工确认草稿后
   用**字段子集**落库：人只认了 ETA 与船位，就只落 ETA 与船位，其余不写。

每个 creator 的签名统一为::

    creator(db, *, tenant_id, user_id, msg, fields, vessel, ...) -> (created, warnings, hints)

``fields`` 是解析出的扁平字段字典；``confirmed``（可选）是**人确认过的字段名集合**，
为 None 表示全量确认。语义：

- 确认子集里没有的字段 → 视为不存在（不落库、不参与计算）；
- 缺了必填字段 → creator 返回 hints 明示原因（而不是静默落一份残缺单据）。
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
from app.models_wave1 import Counterparty, CounterpartyContact, EmailMessage, Vessel
from app.services.domain_events import emit

# ---------------------------------------------------------------------------
# 解析形状 → 扁平字段
# ---------------------------------------------------------------------------


def flat_fields(parse: dict) -> dict:
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


def email_type_of(parse: dict) -> str:
    etype = parse.get("email_type") or ""
    if not etype or etype == "outbound_reply":
        cls = parse.get("classification")
        if isinstance(cls, dict):
            etype = cls.get("type") or etype
    return str(etype or "general")


def pick(fields: dict, key: str, confirmed: set[str] | None) -> Any:
    """取一个字段 —— 字段子集语义：未确认的字段视为不存在。"""
    if confirmed is not None and key not in confirmed:
        return None
    return fields.get(key)


# ---------------------------------------------------------------------------
# 值解析助手
# ---------------------------------------------------------------------------

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


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(raw: str | None) -> datetime | None:
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


def extract_email_address(raw: str | None) -> str | None:
    if not raw:
        return None
    m = re.search(r"<([^<>]+@[^<>]+)>", raw)
    if m:
        return m.group(1).strip().lower()
    m = re.search(r"([\w.+-]+@[\w-]+\.[\w.-]+)", raw)
    return m.group(1).strip().lower() if m else None


def dec(value: Any, places: str) -> Decimal | None:
    """邮件解析值 → Decimal 量化（Numeric 列写入边界，ROUND_HALF_UP 显式舍入）。"""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    except Exception:  # noqa: BLE001 — 解析值不可信，回 None 由人工补
        return None


def parse_date(raw: Any) -> date | None:
    dt = parse_dt(str(raw) if raw is not None else None)
    return dt.date() if dt else None


#: Laycan 窗口的写法（邮件里五花八门）—— 按顺序尝试
_LAYCAN_RANGE_SEP = re.compile(r"\s*(?:to|until|till)\s+|\s+[-–—]\s+", re.I)
#: "01-10 Nov 2026" / "12-18 Sep" —— 日段 + 尾段（尾段可无年份）
_LAYCAN_DAY_RANGE = re.compile(r"^(\d{1,2})\s*[-–—]\s*(\d{1,2})(?:\s+(.+))?$")


def parse_laycan_window(raw: Any) -> tuple[date | None, date | None]:
    """Laycan 文本 → (起始日, 结束日)。

    邮件里的写法有 ``2026-11-01 - 2026-11-10``（ISO 区间）、``2026-11-01``
    （单日）、``01-10 Nov 2026``、``12-18 Sep``（无年份）等。

    旧实现直接 ``laycan.split("-")`` 取首尾两段 —— 对 ISO 写法必然取错
    （首段成了 "2026"），于是**租约草稿的 laycan 永远是空的**，人工确认过的
    laycan 字段等于白确认。这里按上面几种写法分别解析。
    """
    text = str(raw or "").strip()
    if not text:
        return None, None

    whole = parse_date(text)
    if whole is not None:
        return whole, whole

    parts = [p.strip() for p in _LAYCAN_RANGE_SEP.split(text) if p and p.strip()]
    if len(parts) >= 2:
        d1 = parse_date(parts[0])
        d2 = parse_date(parts[-1])
        if d1 and d2:
            return d1, d2

    m = _LAYCAN_DAY_RANGE.match(text)
    if m:
        day1, day2 = int(m.group(1)), int(m.group(2))
        tail = (m.group(3) or "").strip()
        base = None
        for fmt in ("%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%b %Y", "%B %Y", "%Y"):
            try:
                base = datetime.strptime(tail, fmt)
                break
            except ValueError:
                continue
        if base is None:
            # "12-18 Sep" —— 尾段只有月缩写：按当年补齐（缺年份的 laycan 只能这样）
            month = None
            for fmt in ("%b", "%B"):
                try:
                    month = datetime.strptime(tail, fmt)
                    break
                except ValueError:
                    continue
            if month is None:
                return None, None
            base = month.replace(year=datetime.now(timezone.utc).year)
        try:
            return base.replace(day=day1).date(), base.replace(day=day2).date()
        except ValueError:
            return None, None
    return None, None


# ---------------------------------------------------------------------------
# 主数据匹配
# ---------------------------------------------------------------------------


def match_vessel(db: Session, tenant_id: UUID, name: str | None) -> Vessel | None:
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


def vessel_from_subject(db: Session, tenant_id: UUID, subject: str | None) -> Vessel | None:
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


def resolve_vessel(
    db: Session, tenant_id: UUID, fields: dict, subject: str | None
) -> Vessel | None:
    """键名兼容：规则抽取用 vessel；demo/旧落库形状用 vessel_name；
    都没有时按主题里的船名回退（"Bunker offer — Ocean Star" 这类航运惯例）。"""
    vessel = match_vessel(db, tenant_id, fields.get("vessel") or fields.get("vessel_name"))
    if vessel is None:
        vessel = vessel_from_subject(db, tenant_id, subject)
    return vessel


def match_voyage(
    db: Session, tenant_id: UUID, vessel: Vessel | None, hint: str | None = None
) -> Voyage | None:
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
                select(Voyage)
                .where(
                    Voyage.tenant_id == tenant_id,
                    Voyage.voyage_no.ilike(m.group(1)),
                )
                .limit(1)
            )
    return None


def match_counterparty_name(db: Session, tenant_id: UUID, name: str | None) -> tuple[UUID | None, str | None]:
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


def counterparty_from(
    db: Session, tenant_id: UUID, parse: dict, fields: dict
) -> tuple[UUID | None, str | None]:
    """对手方：发件人邮箱命中的联系人最准；否则用 Charterers/Owners 名称模糊匹配。"""
    matched = parse.get("matched")
    if isinstance(matched, dict) and matched.get("counterparty_id"):
        return UUID(str(matched["counterparty_id"])), matched.get("counterparty_name")
    sender = extract_email_address(str(parse.get("from_email") or ""))
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


# ---------------------------------------------------------------------------
# 来源回链
# ---------------------------------------------------------------------------


def link_source_email(
    db: Session, tenant_id: UUID, entity_type: str, entity_id: UUID, msg: EmailMessage
) -> None:
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


def source_meta(msg: EmailMessage) -> dict:
    return {
        "email_message_db_id": str(msg.id),
        "message_id": msg.message_id,
        "subject": msg.subject,
        "from_email": msg.from_email,
    }


# ---------------------------------------------------------------------------
# Creator —— 每个返回 (created, warnings, hints)
# ---------------------------------------------------------------------------


def create_estimate_charter_from_recap(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    msg: EmailMessage,
    fields: dict,
    vessel: Vessel | None,
    cp_id: UUID | None,
    cp_name: str | None,
    confirmed: set[str] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """fixture recap → 估算草稿（Estimate）+ 租约草稿（Charter）。"""
    from app.services.doc_numbering import next_doc_number

    created: list[dict] = []
    warnings: list[str] = []
    hints: list[str] = []

    inputs = {
        k: pick(fields, k, confirmed)
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
        if pick(fields, k, confirmed) is not None
    }
    inputs["source_email"] = source_meta(msg)
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
    link_source_email(db, tenant_id, "estimate", est.id, msg)
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
    laycan = str(pick(fields, "laycan", confirmed) or "")
    laycan_from, laycan_to = parse_laycan_window(laycan)
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
        commission_pct=dec(pick(fields, "commission", confirmed), "0.01"),
        freight_rate=dec(pick(fields, "freight_rate", confirmed), "0.0001"),
        demurrage_rate=dec(pick(fields, "demurrage_rate", confirmed), "0.01"),
        despatch_rate=dec(pick(fields, "despatch_rate", confirmed), "0.01"),
        freight_terms={"source_email": source_meta(msg), "laycan_raw": laycan or None},
    )
    db.add(charter)
    db.flush()
    link_source_email(db, tenant_id, "charter", charter.id, msg)
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
    return created, warnings, hints


def stamp_nor_on_voyage(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    msg: EmailMessage,
    fields: dict,
    vessel: Vessel | None,
    confirmed: set[str] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """NOR → 匹配航次盖 nor_at（PortCall.nor_at + Voyage.meta 快照）。"""
    created: list[dict] = []
    warnings: list[str] = []
    hints: list[str] = []

    voyage = match_voyage(db, tenant_id, vessel, hint=msg.subject)
    if voyage is None:
        warnings.append("voyage_not_matched")
        return created, warnings, hints
    nor_dt = (
        parse_dt(pick(fields, "date_time", confirmed))
        or parse_dt(pick(fields, "time", confirmed))
        or msg.sent_at
        or now_utc()
    )
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
        "nor_email": source_meta(msg),
        "nor_port": pick(fields, "port", confirmed),
    }
    db.flush()
    link_source_email(db, tenant_id, "voyage", voyage.id, msg)
    # 域事件：NOR 落位 → Ops 通知（services/automation.py）
    emit(
        db, tenant_id, "portcall.nor_updated", "voyage", voyage.id,
        payload={
            "voyage_no": voyage.voyage_no,
            "nor_at": nor_dt.isoformat(),
            "port": pick(fields, "port", confirmed),
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
    return created, warnings, hints


def create_laytime_calc(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    msg: EmailMessage,
    fields: dict,
    vessel: Vessel | None,
    confirmed: set[str] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """laytime statement → LaytimeCalc 草稿（SOF 事件 + allowed days 预填）。"""
    created: list[dict] = []
    warnings: list[str] = []
    hints: list[str] = []

    voyage = match_voyage(db, tenant_id, vessel, hint=msg.subject)
    events = pick(fields, "events", confirmed) or []
    inputs = {
        "sof_events": events,
        "allowed_days": pick(fields, "allowed_days", confirmed),
        "source_email": source_meta(msg),
    }
    calc = LaytimeCalc(
        tenant_id=tenant_id,
        voyage_id=voyage.id if voyage else None,
        booking_reference=None,
        inputs={k: v for k, v in inputs.items() if v is not None},
    )
    db.add(calc)
    db.flush()
    link_source_email(db, tenant_id, "laytime", calc.id, msg)
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
            "href": "/finance?tab=laytime",
        }
    )
    return created, warnings, hints


def create_bunker_order(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    msg: EmailMessage,
    fields: dict,
    vessel: Vessel | None,
    parse: dict,
    confirmed: set[str] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """bunker offer → BunkerOrder 草稿（planned）。"""
    created: list[dict] = []
    warnings: list[str] = []
    hints: list[str] = []

    voyage = match_voyage(db, tenant_id, vessel, hint=msg.subject)
    supplier_cp_id, supplier_name = match_counterparty_name(
        db, tenant_id, pick(fields, "supplier", confirmed)
    )
    cp_id, cp_name = counterparty_from(db, tenant_id, parse, fields)
    order = BunkerOrder(
        tenant_id=tenant_id,
        created_by=user_id,
        order_no=f"BNK-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:5].upper()}",
        status="planned",
        vessel_id=vessel.id if vessel else None,
        voyage_id=voyage.id if voyage else None,
        grade=str(pick(fields, "grade", confirmed) or "VLSFO"),
        qty_ordered=dec(pick(fields, "qty_ordered", confirmed), "0.001"),
        unit_price=dec(pick(fields, "unit_price", confirmed), "0.01"),
        currency=str(pick(fields, "currency", confirmed) or "USD").upper()[:3],
        supplier=pick(fields, "supplier", confirmed),
        counterparty_id=supplier_cp_id or cp_id,
    )
    db.add(order)
    db.flush()
    link_source_email(db, tenant_id, "bunker_order", order.id, msg)
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
    return created, warnings, hints


def create_port_disbursement(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    msg: EmailMessage,
    fields: dict,
    vessel: Vessel | None,
    confirmed: set[str] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """PDA（港口费用账单）→ PortDisbursement 草稿。"""
    created: list[dict] = []
    warnings: list[str] = []
    hints: list[str] = []

    voyage = match_voyage(db, tenant_id, vessel, hint=msg.subject)
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
        pda_amount=dec(pick(fields, "pda_amount", confirmed), "0.01"),
        fda_amount=dec(pick(fields, "fda_amount", confirmed), "0.01"),
        currency=str(pick(fields, "currency", confirmed) or "USD").upper()[:3],
        lines={
            "source_email": source_meta(msg),
            "port": pick(fields, "port", confirmed),
            "agent": pick(fields, "agent", confirmed),
        },
    )
    db.add(pda)
    db.flush()
    link_source_email(db, tenant_id, "port_disbursement", pda.id, msg)
    if voyage is None:
        warnings.append("voyage_not_matched")
    created.append(
        {
            "entity": "port_disbursement",
            "id": str(pda.id),
            "action": "draft_created",
            "href": f"/operations/voyages{f'?tab=pda&id={pda.id}' if voyage else ''}",
            "voyage": voyage.voyage_no if voyage else None,
            "port": pick(fields, "port", confirmed),
        }
    )
    return created, warnings, hints


def create_invoice(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    msg: EmailMessage,
    fields: dict,
    vessel: Vessel | None,
    parse: dict,
    confirmed: set[str] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """invoice → Invoice 草稿；零金额拒写（与 /invoices 的 INVALID_AMOUNT 口径一致）。"""
    from app.services.doc_numbering import next_doc_number

    created: list[dict] = []
    warnings: list[str] = []
    hints: list[str] = []

    voyage = match_voyage(db, tenant_id, vessel, hint=msg.subject)
    cp_id, cp_name = counterparty_from(db, tenant_id, parse, fields)
    amount = dec(pick(fields, "amount", confirmed), "0.01")
    if amount is None or amount <= 0:
        # 与 /invoices 的 INVALID_AMOUNT 口径一致 —— 零金额发票没有业务含义
        hints.append("invoice_amount_missing")
        warnings.append("invoice_amount_missing")
        return created, warnings, hints
    inv = Invoice(
        tenant_id=tenant_id,
        invoice_no=next_doc_number(db, tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type="freight",
        status="draft",
        counterparty_id=cp_id,
        voyage_id=voyage.id if voyage else None,
        currency=str(pick(fields, "currency", confirmed) or "USD").upper()[:3],
        amount=amount,
        tax_amount=Decimal("0.00"),
        paid_amount=Decimal("0.00"),
        due_date=parse_date(pick(fields, "due_date", confirmed)),
        meta={
            "source_email": source_meta(msg),
            "invoice_no_ref": pick(fields, "invoice_no_ref", confirmed),
        },
        created_by=user_id,
    )
    db.add(inv)
    db.flush()
    link_source_email(db, tenant_id, "invoice", inv.id, msg)
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
    return created, warnings, hints


def create_claim(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    msg: EmailMessage,
    fields: dict,
    vessel: Vessel | None,
    parse: dict,
    confirmed: set[str] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """claim → Claim 草稿；索赔必须挂靠业务对象或非零金额（与 /claims 口径一致）。"""
    created: list[dict] = []
    warnings: list[str] = []
    hints: list[str] = []

    voyage = match_voyage(db, tenant_id, vessel, hint=msg.subject)
    cp_id, cp_name = counterparty_from(db, tenant_id, parse, fields)
    amount = dec(pick(fields, "amount", confirmed), "0.01")
    if voyage is None and (amount is None or amount == 0):
        hints.append("claim_needs_anchor")
        warnings.append("claim_needs_anchor")
        return created, warnings, hints
    claim_type = str(pick(fields, "claim_type", confirmed) or "demurrage")
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
        currency=str(pick(fields, "currency", confirmed) or "USD").upper()[:3],
        time_bar=parse_date(pick(fields, "time_bar", confirmed)),
        notes=f"From email: {msg.subject or msg.id}",
        contact_id=None,
    )
    db.add(claim)
    db.flush()
    link_source_email(db, tenant_id, "claim", claim.id, msg)
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
    return created, warnings, hints
