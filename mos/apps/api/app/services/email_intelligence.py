"""Email intelligence service — enhanced shipping document parsing.

Builds on existing EmailMessage model to provide:
- Fixture Recap field extraction
- Laytime Statement parsing
- NOR (Notice of Readiness) extraction
- Bunker offer parsing
- Contradiction detection between email content and system data
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
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
    if any(kw in text for kw in ["invoice", "disbursement"]):
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

    classification = classify_email(subject, body)
    parse_result = {"classification": classification}

    if classification["type"] == "fixture_recap":
        parse_result["fixture_recap"] = parse_fixture_recap(body)
    elif classification["type"] == "nor":
        parse_result["nor"] = parse_nor(body)
    elif classification["type"] == "laytime_statement":
        parse_result["laytime"] = parse_laytime_statement(body)

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
