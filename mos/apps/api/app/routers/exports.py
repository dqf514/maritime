"""Excel-compatible CSV exports — UTF-8 BOM, bilingual headers, tenant-scoped."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.models_domain import Charter, Invoice, Voyage
from app.models_ship import ShipCertificate
from app.models_task import Task
from app.models_wave1 import Counterparty, Vessel
from app.routers.ship_mgmt import _cert_status_for
from app.security import AuthContext, get_current_auth, require_module

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
