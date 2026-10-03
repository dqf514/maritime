"""Excel-compatible CSV exports — UTF-8 BOM, bilingual headers, tenant-scoped.

Also hosts the XML API surface (task D):
- GET /invoices/{id}/export-xml   发票 XML 导出（iMOS 风格）
- POST /forms/submit              表单 XML 提交（校验 + 导入 ShipReport）
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.models_domain import Charter, Invoice, Payment, Voyage
from app.models_ship import ShipCertificate
from app.models_shipshore import ShipForm, ShipTerminal
from app.models_task import Task
from app.models_wave1 import Counterparty, Vessel
from app.routers.ship_mgmt import _cert_status_for
from app.security import AuthContext, get_current_auth, require_module
from app.services import marilink
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter(tags=["Exports"])

MAX_ROWS = 5000


def _d(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def _num(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:g}"


def _voyages(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["航次号", "船名", "状态", "租约号", "开始", "完成"],
        "en": ["Voyage No", "Vessel", "Status", "Charter No", "Started", "Completed"],
    }[lang]
    rows = db.scalars(
        select(Voyage)
        .where(Voyage.tenant_id == auth.tenant_id, Voyage.status != "deleted")
        .order_by(Voyage.created_at.desc())
        .limit(MAX_ROWS)
    ).all()
    vessels = {v.id: v.name for v in db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id)).all()}
    charters = {c.id: c.charter_no for c in db.scalars(select(Charter).where(Charter.tenant_id == auth.tenant_id)).all()}
    data = [
        [
            r.voyage_no,
            vessels.get(r.vessel_id, "") if r.vessel_id else "",
            r.status,
            charters.get(r.charter_id, "") if r.charter_id else "",
            _d(r.started_at),
            _d(r.completed_at),
        ]
        for r in rows
    ]
    return headers, data


def _invoices(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["发票号", "类型", "对手方", "金额", "币种", "已付", "到期日", "状态"],
        "en": ["Invoice No", "Type", "Counterparty", "Amount", "Currency", "Paid", "Due Date", "Status"],
    }[lang]
    rows = db.scalars(
        select(Invoice)
        .where(Invoice.tenant_id == auth.tenant_id, Invoice.status != "deleted")
        .order_by(Invoice.invoice_no)
        .limit(MAX_ROWS)
    ).all()
    parties = {c.id: c.name for c in db.scalars(select(Counterparty).where(Counterparty.tenant_id == auth.tenant_id)).all()}
    data = [
        [
            r.invoice_no,
            r.invoice_type,
            parties.get(r.counterparty_id, "") if r.counterparty_id else "",
            _money(r.amount),
            r.currency,
            _money(r.paid_amount),
            _d(r.due_date),
            r.status,
        ]
        for r in rows
    ]
    return headers, data


def _certificates(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["船名", "证书代码", "名称", "签发", "到期", "状态", "剩余天数"],
        "en": ["Vessel", "Cert Code", "Cert Name", "Issued", "Expires", "Status", "Days to Expiry"],
    }[lang]
    certs = db.scalars(
        select(ShipCertificate).where(ShipCertificate.tenant_id == auth.tenant_id).limit(MAX_ROWS)
    ).all()
    vessels = {v.id: v.name for v in db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id)).all()}
    today = date.today()
    data = [
        [
            vessels.get(c.vessel_id, ""),
            c.cert_code,
            c.cert_name,
            _d(c.issued_on),
            _d(c.expires_on),
            _cert_status_for(c.expires_on, c.status),
            (c.expires_on - today).days if c.expires_on else "",
        ]
        for c in certs
    ]
    return headers, data


def _tasks(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["标题", "优先级", "状态", "指派人", "截止", "创建人"],
        "en": ["Title", "Priority", "Status", "Assignee", "Due", "Created By"],
    }[lang]
    rows = db.scalars(
        select(Task)
        .where(
            Task.tenant_id == auth.tenant_id,
            or_(Task.assignee_user_id == auth.user_id, Task.created_by == auth.user_id),
        )
        .order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.created_at.desc())
        .limit(MAX_ROWS)
    ).all()

    def _name(user_id) -> str:
        if not user_id:
            return ""
        user = db.get(User, user_id)
        return (user.full_name or user.email) if user else ""

    data = [
        [t.title, t.priority, t.status, _name(t.assignee_user_id), _d(t.due_at), _name(t.created_by)]
        for t in rows
    ]
    return headers, data


def _vessels(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["船名", "IMO", "MMSI", "船旗", "船型", "DWT", "状态"],
        "en": ["Name", "IMO", "MMSI", "Flag", "Type", "DWT", "Status"],
    }[lang]
    rows = db.scalars(
        select(Vessel)
        .where(Vessel.tenant_id == auth.tenant_id, Vessel.deleted_at.is_(None))
        .order_by(Vessel.name)
        .limit(MAX_ROWS)
    ).all()
    data = [
        [v.name, v.imo or "", v.mmsi or "", v.flag or "", v.vessel_type or "", _num(v.dwt), v.status]
        for v in rows
    ]
    return headers, data


Builder = Callable[[Session, AuthContext, str], tuple[list[str], list[list[Any]]]]

ENTITIES: dict[str, tuple[str | None, Builder]] = {
    "voyages": ("operations", _voyages),
    "invoices": ("finance", _invoices),
    "certificates": ("ship_mgmt", _certificates),
    "tasks": (None, _tasks),
    "vessels": ("masterdata", _vessels),
}


@router.get("/export/{entity}.csv")
def export_csv(
    entity: str,
    lang: str = Query("zh", pattern="^(zh|en)$"),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    spec = ENTITIES.get(entity)
    if spec is None:
        raise HTTPException(404, detail={"code": "EXPORT_NOT_FOUND", "entity": entity})
    module_code, builder = spec
    if module_code is not None:
        require_module(module_code)(auth=auth, db=db)
    headers, rows = builder(db, auth, lang)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    content = "\ufeff" + buf.getvalue()
    filename = f"{entity}_{date.today().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# \u2500\u2500 XML API\uff08task D\uff09\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


@router.get("/invoices/{invoice_id}/export-xml")
def export_invoice_xml(
    invoice_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """Export invoice as iMOS-style XML (header + counterparty + payments)."""
    inv = scoped_get(db, Invoice, invoice_id, auth.tenant_id)
    if not inv:
        raise HTTPException(404, detail={"code": "INVOICE_NOT_FOUND", "message": "Invoice not found"})

    party = (
        scoped_get(db, Counterparty, inv.counterparty_id, auth.tenant_id)
        if inv.counterparty_id
        else None
    )
    payments = db.scalars(
        scoped_query(db, Payment, auth.tenant_id).where(Payment.invoice_id == invoice_id)
    ).all()

    root = ET.Element("Invoice")
    root.set("id", str(inv.id))
    root.set("number", inv.invoice_no or "")
    root.set("type", inv.invoice_type or "")
    root.set("status", inv.status or "")
    root.set("currency", inv.currency or "USD")

    def _sub(tag: str, value: Any) -> None:
        ET.SubElement(root, tag).text = "" if value is None else str(value)

    _sub("Amount", inv.amount)
    _sub("TaxAmount", inv.tax_amount)
    _sub("PaidAmount", inv.paid_amount)
    _sub("BaseAmount", inv.base_amount)
    _sub("FxRate", inv.fx_rate)
    _sub("IssuedAt", inv.issued_at.isoformat() if inv.issued_at else None)
    _sub("DueDate", inv.due_date.isoformat() if inv.due_date else None)
    _sub("BillBy", inv.bill_by)
    _sub("CommissionBasis", inv.commission_basis)

    cp = ET.SubElement(root, "Counterparty")
    cp.set("id", str(party.id) if party else "")
    cp.set("name", party.name if party else "")
    if inv.voyage_id:
        v = ET.SubElement(root, "Voyage")
        v.set("id", str(inv.voyage_id))

    pays_el = ET.SubElement(root, "Payments")
    for pay in payments:
        p = ET.SubElement(pays_el, "Payment")
        p.set("id", str(pay.id))
        p.set("amount", str(pay.amount))
        p.set("currency", pay.currency or "USD")
        if pay.payment_date:
            p.set("paymentDate", pay.payment_date.isoformat())
        if pay.reference:
            p.set("reference", pay.reference)

    xml = ET.tostring(root, encoding="unicode", xml_declaration=True)
    return Response(content=xml, media_type="application/xml")


class FormSubmitIn(BaseModel):
    xml: str
    terminal_id: UUID | None = None
    voyage_id: UUID | None = None


@router.post("/forms/submit")
def submit_form_xml(
    body: FormSubmitIn = Body(...),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    """Submit form XML (validate + import).

    XML shape:
        <Form formType="noon_report" submittedBy="Captain" terminalKey="T-...">
          <Field name="mt_per_day">12.5</Field>
        </Form>

    Validation: well-formed XML \u2192 root Form \u2192 formType present \u2192 matching active
    ShipForm \u2192 resolvable terminal (envelope terminal_id or terminalKey attr)
    \u2192 required fields per form.fields_json. On success imports a ShipReport
    (status "submitted") via marilink.submit_report.
    """
    try:
        root = ET.fromstring(body.xml)
    except ET.ParseError as exc:
        raise HTTPException(400, detail={"code": "FORM_XML_PARSE", "message": f"Invalid XML: {exc}"})

    if root.tag != "Form":
        raise HTTPException(422, detail={"code": "FORM_XML_ROOT", "message": "Root element must be <Form>"})

    form_type = (root.get("formType") or "").strip()
    if not form_type:
        raise HTTPException(422, detail={"code": "FORM_TYPE_MISSING", "message": "formType attribute is required"})

    forms = marilink.get_active_forms(db, auth.tenant_id, form_type)
    if not forms:
        raise HTTPException(
            422,
            detail={"code": "FORM_TYPE_UNKNOWN", "message": f"No active form template for formType '{form_type}'"},
        )
    form = forms[0]

    # \u5b57\u6bb5\u62bd\u53d6\uff1a<Field name="x">v</Field> + \u4efb\u610f\u5b50\u5143\u7d20 <x>v</x>
    fields: dict[str, str] = {}
    for child in root:
        if child.tag == "Field":
            name = (child.get("name") or "").strip()
            if name:
                fields[name] = (child.text or "").strip()
        else:
            fields[child.tag] = (child.text or "").strip()

    required = [
        f.get("name") or f.get("key")
        for f in (form.fields_json or [])
        if isinstance(f, dict) and f.get("required") and (f.get("name") or f.get("key"))
    ]
    missing = [name for name in required if name not in fields]
    if missing:
        raise HTTPException(
            422,
            detail={"code": "FORM_FIELD_MISSING", "message": f"Missing required fields: {missing}", "missing": missing},
        )

    # \u7ec8\u7aef\u89e3\u6790\uff1aenvelope terminal_id \u4f18\u5148\uff0c\u5176\u6b21 XML terminalKey \u5c5e\u6027
    terminal = None
    if body.terminal_id:
        terminal = scoped_get(db, ShipTerminal, body.terminal_id, auth.tenant_id)
    if not terminal:
        terminal_key = (root.get("terminalKey") or "").strip()
        if terminal_key:
            terminal = db.scalar(
                select(ShipTerminal).where(
                    ShipTerminal.tenant_id == auth.tenant_id,
                    ShipTerminal.terminal_key == terminal_key,
                )
            )
    if not terminal:
        raise HTTPException(
            422,
            detail={"code": "FORM_TERMINAL_REQUIRED", "message": "terminal_id or terminalKey is required"},
        )

    submitted_by = (root.get("submittedBy") or "api").strip()
    report = marilink.submit_report(
        db,
        tenant_id=auth.tenant_id,
        terminal_id=terminal.id,
        form_id=form.id,
        form_type=form_type,
        data_json=fields,
        submitted_by=submitted_by,
        voyage_id=body.voyage_id,
    )
    return {
        "report_id": str(report.id),
        "report_ref": report.report_ref,
        "form_type": report.form_type,
        "status": report.status,
        "fields": fields,
        "imported": True,
        "model": "ship_report",
    }
