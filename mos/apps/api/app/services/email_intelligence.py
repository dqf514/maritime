"""Email intelligence service — enhanced shipping document parsing.

Builds on existing EmailMessage model to provide:
- Fixture Recap field extraction
- Laytime Statement parsing
- NOR (Notice of Readiness) extraction
- Bunker offer / PDA / invoice / claim field extraction
- Classifier feedback memory（用户「忽略并记住」→ 同源同类型不再进复核队列）
- Contradiction detection between email content and system data
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models_wave1 import EmailMessage, EmailThread


# ── Parsing Patterns ──

FIXTURE_RECAP_PATTERNS = {
    "charterers": re.compile(r"Charterers?[:\s]+(.+?)(?:\n|$)", re.I),
    "owners": re.compile(r"Owners?[:\s]+(.+?)(?:\n|$)", re.I),
    "vessel": re.compile(r"Vessel[:\s]+[\"']?(.+?)[\"']?(?:\n|$)", re.I),
    "cargo": re.compile(r"Cargo[:\s]+(.+?)(?:\n|$)", re.I),
    "load_port": re.compile(r"Load(?:ing)?\s*Port[:\s]+(.+?)(?:\n|$)", re.I),
    "discharge_port": re.compile(r"Disch(?:arge)?(?:ing)?\s*Port[:\s]+(.+?)(?:\n|$)", re.I),
    "laycan": re.compile(r"Laycan[:\s]+(.+?)(?:\n|$)", re.I),
    "freight_rate": re.compile(r"Freight\s*Rate[:\s]+[USD$]*\s*([\d.,]+)", re.I),
    "demurrage_rate": re.compile(r"Demurrage[:\s]+[USD$]*\s*([\d.,]+)", re.I),
    "despatch_rate": re.compile(r"Despatch[:\s]+[USD$]*\s*([\d.,]+)", re.I),
    "laytime_load": re.compile(r"(?:Load(?:ing)?\s*)?Laytime[:\s]+([\d.]+)\s*(?:days|hrs|hours)", re.I),
    "laytime_discharge": re.compile(r"(?:Disch(?:arge)?(?:ing)?\s*)?Laytime[:\s]+([\d.]+)\s*(?:days|hrs|hours)", re.I),
    "commission": re.compile(r"(?:Total\s*)?Commission[:\s]+([\d.]+)\s*%", re.I),
}

NOR_PATTERNS = {
    "vessel": re.compile(r"Vessel[:\s]+[\"']?(.+?)[\"']?(?:\n|$)", re.I),
    "port": re.compile(r"(?:at|port of)[:\s]+(.+?)(?:\n|$)", re.I),
    "date_time": re.compile(r"(?:date|time)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}[\s\d:]+)", re.I),
    "position": re.compile(r"Position[:\s]+(\d+°\s*\d*['']?\s*[NS]\s+\d+°\s*\d*['']?\s*[EW])", re.I),
    "draft": re.compile(r"Draft[:\s]+([\d.]+)\s*m", re.I),
}

# 新类型关键词（航运单证语义）—— PDA 从 invoice 里拆出（disbursement 邮件此前
# 全被归成 invoice，落发票草稿时金额/币种口径完全不同）。短缩写 pda/fda 必须按
# 词边界匹配，否则 "updated" 这类词里带 pda 三个字母就会误分类。
PDA_KEYWORDS = ("port disbursement", "disbursement account", "disbursement estimate")
PDA_ACRONYMS = ("pda", "fda")
BUNKER_GRADES = ("VLSFO", "LSMGO", "VLSFO380", "HSFO", "MGO", "ULSD", "MFO", "RMG")


def _parse_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip().replace(",", "").replace("USD", "").replace("$", "").strip()
    # 去掉尾部单位词（mt / days / % …）与句尾句号（"25,000.00." 这类散句截取）
    text = re.sub(r"\s*(?:mt|tons?|days?|hrs?|hours?|%)\s*$", "", text, flags=re.I).strip()
    text = text.rstrip(".").strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_bunker_offer(body: str) -> dict:
    """供油报价 → 订油单草稿字段（港/油品/价/量/供方/币种）。"""
    result: dict = {}
    m = re.search(r"(?:port|delivery port|stem port|at)\s*[:\-]\s*(.+?)(?:\n|$)", body, re.I)
    if m:
        result["port"] = m.group(1).strip()
    for grade in BUNKER_GRADES:
        if re.search(rf"\b{grade}\b", body, re.I):
            result["grade"] = grade
            break
    m = re.search(r"(?:unit\s*price|price|rate)\s*[:\-]\s*(?:usd|eur|\\$|€)?\s*([\d.,]+)", body, re.I)
    if m:
        result["unit_price"] = _parse_number(m.group(1))
    m = re.search(r"(?:quantity|qty|volume)\s*[:\-]\s*([\d.,]+)\s*(?:mt|tons?)?", body, re.I)
    if m:
        result["qty_ordered"] = _parse_number(m.group(1))
    m = re.search(r"supplier\s*[:\-]\s*(.+?)(?:\n|$)", body, re.I)
    if m:
        result["supplier"] = m.group(1).strip()
    m = re.search(r"currency\s*[:\-]\s*([A-Z]{3})", body, re.I)
    if m:
        result["currency"] = m.group(1).upper()
    elif re.search(r"\beur\b|€", body, re.I):
        result["currency"] = "EUR"
    return result


def parse_port_disbursement(body: str) -> dict:
    """使费账单（PDA/FDA）→ PortDisbursement 草稿字段。"""
    result: dict = {}
    m = re.search(r"port\s*[:\-]\s*(.+?)(?:\n|$)", body, re.I)
    if m:
        result["port"] = m.group(1).strip()
    m = re.search(r"(?:pda|disbursement)\s*(?:amount)?\s*[:\-]\s*(?:usd|eur|\\$|€)?\s*([\d.,]+)", body, re.I)
    if m:
        result["pda_amount"] = _parse_number(m.group(1))
    m = re.search(r"(?:fda|final disbursement)\s*(?:amount)?\s*[:\-]\s*(?:usd|eur|\\$|€)?\s*([\d.,]+)", body, re.I)
    if m:
        result["fda_amount"] = _parse_number(m.group(1))
    m = re.search(r"currency\s*[:\-]\s*([A-Z]{3})", body, re.I)
    if m:
        result["currency"] = m.group(1).upper()
    m = re.search(r"agent\s*[:\-]\s*(.+?)(?:\n|$)", body, re.I)
    if m:
        result["agent"] = m.group(1).strip()
    return result


def parse_invoice(body: str) -> dict:
    """账单邮件 → Invoice 草稿字段（发票号/金额/币种/到期日）。"""
    result: dict = {}
    m = re.search(r"(?:invoice|inv|invoice\s*no\.?)\s*(?:no\.?|number|#)?\s*[:\-#]?\s*([A-Za-z0-9][A-Za-z0-9\-/]{2,})", body, re.I)
    if m:
        result["invoice_no_ref"] = m.group(1).strip()
    m = re.search(r"(?:total\s*amount|amount\s*due|total|amount)\s*[:\-]\s*(?:usd|eur|\\$|€)?\s*([\d.,]+)", body, re.I)
    if m:
        result["amount"] = _parse_number(m.group(1))
    m = re.search(r"currency\s*[:\-]\s*([A-Z]{3})", body, re.I)
    if m:
        result["currency"] = m.group(1).upper()
    elif re.search(r"\beur\b|€", body, re.I):
        result["currency"] = "EUR"
    m = re.search(r"(?:due\s*date|payment\s*due|pay\s*by)\s*[:\-]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", body, re.I)
    if m:
        result["due_date"] = m.group(1).strip()
    return result


def parse_claim(body: str) -> dict:
    """索赔/催告邮件 → Claim 草稿字段（类型/金额/时效）。"""
    result: dict = {}
    text = body.lower()
    if any(kw in text for kw in ("demurrage", "despatch", "detention")):
        result["claim_type"] = "demurrage"
    elif any(kw in text for kw in ("off-hire", "off hire", "off_hire")):
        result["claim_type"] = "off_hire"
    elif any(kw in text for kw in ("speed", "consumption", "performance")):
        result["claim_type"] = "performance"
    elif any(kw in text for kw in ("cargo damage", "damage to cargo", "shortage")):
        result["claim_type"] = "cargo_damage"
    m = re.search(r"(?:claim(?:ed)?|amount|total)\s*(?:amount)?\s*[:\-]\s*(?:usd|eur|\\$|€)?\s*([\d.,]+)", body, re.I)
    if not m:
        # 无冒号的散句式（"claim demurrage USD 25,000"）→ 直接抓币种后的数字
        m = re.search(r"(?:usd|eur|\\$|€)\s*([\d.,]+)", body, re.I)
    if m:
        result["amount"] = _parse_number(m.group(1))
    m = re.search(r"currency\s*[:\-]\s*([A-Z]{3})", body, re.I)
    if m:
        result["currency"] = m.group(1).upper()
    m = re.search(r"(?:time\s*bar|barred|deadline)\s*(?:by|:)?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", body, re.I)
    if m:
        result["time_bar"] = m.group(1).strip()
    return result


# ── 分类反馈记忆（「忽略并记住」）────────────────────────────────────────
# 用户在复核队列里点「忽略」并选择记住时，系统记下「这类发件人不该再被识别成
# 这个类型」；同步/解析分类后查一次，命中则把分类降级为 general，不再进复核
# 队列、不再出现对应的操作按钮。存储走 ConfigService（tenant 作用域 JSON），
# 不新增表。
IGNORE_RULES_KEY = "email.classifier_ignore_rules"
IGNORE_RULES_CAP = 200


def load_ignore_rules(db: Session, tenant_id: UUID) -> list[dict]:
    from app.services.config_service import ConfigService

    raw = ConfigService.get(db, IGNORE_RULES_KEY, tenant_id=tenant_id, default=[])
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict) and r.get("email_type") and r.get("from_pattern")]


def add_ignore_rule(db: Session, tenant_id: UUID, email_type: str, from_pattern: str, user_id: UUID | None = None) -> dict:
    """记住一次误判：同 from_pattern（发件人或域名）不再识别为 email_type。"""
    from app.services.config_service import ConfigService

    rules = load_ignore_rules(db, tenant_id)
    pattern = (from_pattern or "").strip().lower()
    rules = [
        r
        for r in rules
        if not (r.get("email_type") == email_type and str(r.get("from_pattern", "")).lower() == pattern)
    ]
    rule = {
        "email_type": email_type,
        "from_pattern": pattern,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    rules.append(rule)
    ConfigService.set(
        db,
        IGNORE_RULES_KEY,
        rules[-IGNORE_RULES_CAP:],
        tenant_id=tenant_id,
        category="email",
        description="Classifier feedback: do not re-classify this sender/domain as the given type",
        updated_by=user_id,
    )
    return rule


def remove_ignore_rule(db: Session, tenant_id: UUID, email_type: str, from_pattern: str) -> int:
    """删除一条反馈记忆；返回删除条数。"""
    from app.services.config_service import ConfigService

    pattern = (from_pattern or "").strip().lower()
    rules = load_ignore_rules(db, tenant_id)
    kept = [
        r
        for r in rules
        if not (r.get("email_type") == email_type and str(r.get("from_pattern", "")).lower() == pattern)
    ]
    removed = len(rules) - len(kept)
    if removed:
        ConfigService.set(
            db, IGNORE_RULES_KEY, kept, tenant_id=tenant_id, category="email", updated_by=None
        )
    return removed


def _sender_domain(from_email: str | None) -> str | None:
    raw = (from_email or "").strip().lower()
    m = re.search(r"<([^<>]+@[^<>]+)>", raw)
    if m:
        raw = m.group(1)
    m = re.search(r"([\w.+-]+@[\w-]+\.[\w.-]+)", raw)
    if m:
        raw = m.group(1)
    if "@" not in raw:
        return None
    return raw.rsplit("@", 1)[1]


def match_ignore_rule(rules: list[dict], email_type: str, from_email: str | None) -> dict | None:
    """命中反馈记忆：先精确匹配发件人地址，再退到域名。"""
    raw = (from_email or "").strip().lower()
    m = re.search(r"<([^<>]+@[^<>]+)>", raw)
    if m:
        raw = m.group(1)
    m = re.search(r"([\w.+-]+@[\w-]+\.[\w.-]+)", raw)
    address = m.group(1) if m else raw
    domain = address.rsplit("@", 1)[1] if "@" in address else ""
    exact = None
    for rule in rules:
        if rule.get("email_type") != email_type:
            continue
        pattern = str(rule.get("from_pattern", "")).lower()
        if pattern and pattern == address:
            return rule
        if pattern and domain and pattern == domain:
            exact = rule  # 域名命中 —— 继续找地址精确命中，找不到再退回
    return exact


def classify_with_memory(
    db: Session, tenant_id: UUID, subject: str, body: str, from_email: str | None
) -> tuple[dict, dict | None]:
    """classify_email + 反馈记忆：命中「忽略并记住」的规则则降级为 general。"""
    classification = classify_email(subject, body)
    if classification["type"] == "general":
        return classification, None
    rules = load_ignore_rules(db, tenant_id)
    if not rules:
        return classification, None
    hit = match_ignore_rule(rules, classification["type"], from_email)
    if hit:
        original = dict(classification)
        return {"type": "general", "confidence": 0.3}, {"original": original, "rule": hit}
    return classification, None


def _extract_email_address(raw: str) -> str | None:
    """从 'Name <a@b.com>' / 'a@b.com' 提取纯邮箱地址。"""
    m = re.search(r"<([^<>]+@[^<>]+)>", raw)
    if m:
        return m.group(1).strip().lower()
    m = re.search(r"([\w.+-]+@[\w-]+\.[\w.-]+)", raw)
    return m.group(1).strip().lower() if m else None


def classify_email(subject: str, body: str) -> dict:
    """Classify an email into a shipping document type."""
    text = f"{subject or ''} {body or ''}".lower()

    if any(kw in text for kw in ["fixture recap", "fixed recap", "fixture note"]):
        return {"type": "fixture_recap", "confidence": 0.9}
    if any(kw in text for kw in ["laytime statement", "statement of facts", "demurrage calc"]):
        return {"type": "laytime_statement", "confidence": 0.85}
    if any(kw in text for kw in ["notice of readiness", "nor ", "nor."]):
        return {"type": "nor", "confidence": 0.85}
    if any(kw in text for kw in ["bunker offer", "bunker quotation", "stem "]):
        return {"type": "bunker_offer", "confidence": 0.8}
    # PDA 必须先于 invoice 判断 —— disbursement 邮件此前全被归成 invoice
    if any(kw in text for kw in PDA_KEYWORDS) or any(
        re.search(rf"\b{re.escape(kw)}\b", text) for kw in PDA_ACRONYMS
    ):
        return {"type": "port_disbursement", "confidence": 0.8}
    if any(kw in text for kw in ["invoice"]):
        return {"type": "invoice", "confidence": 0.75}
    if any(kw in text for kw in ["claim", "demand"]):
        return {"type": "claim", "confidence": 0.7}
    return {"type": "general", "confidence": 0.5}


def parse_fixture_recap(body: str) -> dict:
    """Extract structured fields from a Fixture Recap email."""
    result = {}
    for field, pattern in FIXTURE_RECAP_PATTERNS.items():
        m = pattern.search(body)
        if m:
            val = m.group(1).strip()
            if field in ("freight_rate", "demurrage_rate", "despatch_rate", "commission",
                         "laytime_load", "laytime_discharge"):
                val = val.replace(",", "")
                try:
                    val = float(val)
                except ValueError:
                    pass
            result[field] = val
    return result


def parse_nor(body: str) -> dict:
    """Extract fields from a Notice of Readiness."""
    result = {}
    for field, pattern in NOR_PATTERNS.items():
        m = pattern.search(body)
        if m:
            result[field] = m.group(1).strip()
    return result


def parse_laytime_statement(body: str) -> dict:
    """Extract laytime events from a Statement of Facts."""
    events = []
    lines = body.split("\n")
    time_pattern = re.compile(r"(\d{1,2}[/-]\d{1,2}\s+\d{1,2}:\d{2})\s+(.+)", re.I)
    for line in lines:
        m = time_pattern.match(line.strip())
        if m:
            events.append({"time": m.group(1).strip(), "event": m.group(2).strip()})
    total_pattern = re.compile(r"(?:total|allowed)[:\s]+([\d.]+)\s*(?:days|hrs)", re.I)
    allowed_m = total_pattern.search(body)
    allowed = float(allowed_m.group(1)) if allowed_m else None
    return {"events": events, "allowed_days": allowed, "event_count": len(events)}


def detect_contradictions(
    parsed: dict, voyage_data: dict | None
) -> list[dict]:
    """Compare parsed email data against system voyage data."""
    if not voyage_data or not parsed:
        return []
    contradictions = []
    if "freight_rate" in parsed and "freight_rate" in voyage_data:
        email_rate = float(parsed["freight_rate"])
        sys_rate = float(voyage_data["freight_rate"])
        if abs(email_rate - sys_rate) > 0.01:
            contradictions.append({
                "field": "freight_rate",
                "email_value": email_rate,
                "system_value": sys_rate,
                "message": f"Freight rate mismatch: email says ${email_rate:,.2f}, system has ${sys_rate:,.2f}",
            })
    if "load_port" in parsed and "load_port" in voyage_data:
        if parsed["load_port"].lower().strip() != voyage_data["load_port"].lower().strip():
            contradictions.append({
                "field": "load_port",
                "email_value": parsed["load_port"],
                "system_value": voyage_data["load_port"],
                "message": f"Load port mismatch: email says '{parsed['load_port']}', system has '{voyage_data['load_port']}'",
            })
    return contradictions


def process_inbound_email(
    db: Session,
    tenant_id: UUID,
    message_id: UUID,
) -> dict:
    """Process an inbound email message: classify, parse, detect contradictions."""
    msg = db.get(EmailMessage, message_id)
    if not msg or msg.tenant_id != tenant_id:
        return {"error": "Message not found"}

    subject = msg.subject or ""
    body = msg.body_text or ""

    classification, suppressed = classify_with_memory(db, tenant_id, subject, body, msg.from_email)
    parse_result = {"classification": classification}
    if suppressed:
        # 命中「忽略并记住」的反馈记忆 —— 保留原判定供人工查看，但不再触发操作按钮
        parse_result["suppressed_by_rule"] = suppressed["rule"]
        parse_result["original_classification"] = suppressed["original"]

    # 闭环：发件人邮箱 → 联系人通讯录 → 对手方自动识别（人工确认后落库）
    sender = _extract_email_address(msg.from_email or "")
    if sender:
        from sqlalchemy import select as _select

        from app.models_wave1 import Counterparty, CounterpartyContact

        hit = db.execute(
            _select(CounterpartyContact, Counterparty.name)
            .join(Counterparty, CounterpartyContact.counterparty_id == Counterparty.id)
            .where(
                CounterpartyContact.tenant_id == tenant_id,
                CounterpartyContact.email.ilike(sender),
            )
            .limit(1)
        ).first()
        if hit:
            contact, party_name = hit
            parse_result["matched"] = {
                "contact_id": str(contact.id),
                "contact_name": contact.name,
                "counterparty_id": str(contact.counterparty_id),
                "counterparty_name": party_name,
                "basis": "sender_email",
            }

    # D25：LLM 结构化抽取（失败自动回落规则），规则并行做字段级交叉校验。
    # 落库形状 = 抽取字段 + _source(llm|rules) + _rule_diffs（人工确认对照）。
    from app.services.llm_extract import extract_fields

    if classification["type"] == "fixture_recap":
        parse_result["fixture_recap"] = extract_fields(
            "fixture_recap", subject, body, rule_fields=parse_fixture_recap(body)
        )
    elif classification["type"] == "nor":
        parse_result["nor"] = extract_fields(
            "nor", subject, body, rule_fields=parse_nor(body)
        )
    elif classification["type"] == "laytime_statement":
        parse_result["laytime"] = extract_fields(
            "laytime_statement", subject, body, rule_fields=parse_laytime_statement(body)
        )
    elif classification["type"] == "bunker_offer":
        parse_result["bunker_offer"] = extract_fields(
            "bunker_offer", subject, body, rule_fields=parse_bunker_offer(body)
        )
    elif classification["type"] == "port_disbursement":
        parse_result["port_disbursement"] = extract_fields(
            "port_disbursement", subject, body, rule_fields=parse_port_disbursement(body)
        )
    elif classification["type"] == "invoice":
        parse_result["invoice"] = extract_fields(
            "invoice", subject, body, rule_fields=parse_invoice(body)
        )
    elif classification["type"] == "claim":
        parse_result["claim"] = extract_fields(
            "claim", subject, body, rule_fields=parse_claim(body)
        )

    msg.parse_status = "parsed"
    msg.parse_confidence = Decimal(str(classification["confidence"]))
    msg.parse_result = parse_result
    db.commit()

    return {
        "message_id": str(message_id),
        "classification": classification,
        "parse_result": parse_result,
    }


def list_unprocessed(db: Session, tenant_id: UUID, limit: int = 50) -> list[EmailMessage]:
    """List inbound emails that haven't been parsed yet."""
    return list(db.scalars(
        select(EmailMessage)
        .where(
            EmailMessage.tenant_id == tenant_id,
            EmailMessage.direction == "inbound",
            EmailMessage.parse_status == "pending",
        )
        .order_by(desc(EmailMessage.sent_at))
        .limit(limit)
    ).all())
