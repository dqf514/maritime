"""Excel-compatible CSV exports — UTF-8 BOM, bilingual headers, tenant-scoped.

Also hosts the XML API surface (task D):
- GET /invoices/{id}/export-xml   发票 XML 导出（模块化）
- POST /forms/submit              表单 XML 提交（校验 + 导入 ShipReport）
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from collections.abc import Callable

from defusedxml import ElementTree as DefusedET
from defusedxml.common import DefusedXmlException
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
from app.models_cargo import CargoName
from app.models_domain import (
    BunkerOrder,
    Charter,
    Claim,
    Invoice,
    LaytimeCalc,
    Payment,
    PaymentBatch,
    Voyage,
)
from app.models_ship import ShipCertificate
from app.models_shipshore import ShipForm, ShipTerminal
from app.models_reference import PortDistance
from app.models_task import Task
from app.models_wave1 import Counterparty, Port, Vessel
from app.routers.ship_mgmt import _cert_status_for
from app.security import AuthContext, get_current_auth, require_module, require_module_read
from app.services.csv_safety import guard_csv_cell
from app.services.data_scope import apply_module_scope
from app.services.money import REVENUE_STATUSES, invoice_gross, invoice_open
from app.services import marilink
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter(tags=["Exports"])

MAX_ROWS = 5000

# D6 公式注入防护：= + @ 制表/回车开头，或非纯数字的 - 开头 → 加撇号
# 规则收敛到 ``services/csv_safety``，与前端 ``lib/csv.ts`` 同源（P0-16）。
_guard_cell = guard_csv_cell


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
        apply_module_scope(
            db,
            select(Voyage).where(Voyage.tenant_id == auth.tenant_id, Voyage.status != "deleted"),
            Voyage,
            auth,
            "operations",
        )
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


def _invoices(db: Session, auth: AuthContext, lang: str, include_drafts: bool = False) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["发票号", "类型", "对手方", "金额", "税额", "总额", "币种", "已付", "未收", "到期日", "状态"],
        "en": [
            "Invoice No", "Type", "Counterparty", "Amount", "Tax", "Total",
            "Currency", "Paid", "Open", "Due Date", "Status",
        ],
    }[lang]
    # P2-B10：默认只导出**已签发**的发票（应收口径）。旧实现只过滤
    # `status != "deleted"`，于是草稿发票也被当成应收导出去，客户对账时
    # 多出一堆根本没签发的行。需要全量工作清单时用 include_drafts=true。
    stmt = select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.status != "deleted")
    # 行级数据权限：scope 收紧到 "own" 时，导出也只出自己建的发票 ——
    # 否则界面上被收窄、导出的 CSV 里却是全租户的行。
    stmt = apply_module_scope(db, stmt, Invoice, auth, "finance")
    if not include_drafts:
        stmt = stmt.where(Invoice.status.in_(REVENUE_STATUSES))
    rows = db.scalars(stmt.order_by(Invoice.invoice_no).limit(MAX_ROWS)).all()
    parties = {c.id: c.name for c in db.scalars(select(Counterparty).where(Counterparty.tenant_id == auth.tenant_id)).all()}
    data = [
        [
            r.invoice_no,
            r.invoice_type,
            parties.get(r.counterparty_id, "") if r.counterparty_id else "",
            _money(r.amount),
            # P1-B12：税额必须进 CSV —— 客户拿 CSV 对账时看不到税会以为少算了
            _money(r.tax_amount),
            float(invoice_gross(r)),
            r.currency,
            _money(r.paid_amount),
            float(invoice_open(r)),
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
        apply_module_scope(
            db,
            select(ShipCertificate).where(ShipCertificate.tenant_id == auth.tenant_id),
            ShipCertificate,
            auth,
            "ship_mgmt",
        )
        .limit(MAX_ROWS)
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
        apply_module_scope(
            db,
            select(Vessel).where(Vessel.tenant_id == auth.tenant_id, Vessel.deleted_at.is_(None)),
            Vessel,
            auth,
            "masterdata",
        )
        .order_by(Vessel.name)
        .limit(MAX_ROWS)
    ).all()
    data = [
        [v.name, v.imo or "", v.mmsi or "", v.flag or "", v.vessel_type or "", _num(v.dwt), v.status]
        for v in rows
    ]
    return headers, data


def _distances(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    # 全局参照表（port_distances 无 tenant_id）——与 /commercial/distances 同口径
    headers = {
        "zh": ["起运港", "到达港", "距离(海里)", "航线", "运河", "过闸(天)", "运河费用", "备注", "数据来源"],
        "en": ["From", "To", "Distance (NM)", "Route", "Canal", "Transit (days)", "Canal toll", "Notes", "Source"],
    }[lang]
    rows = db.scalars(select(PortDistance).order_by(PortDistance.from_port_unlocode).limit(MAX_ROWS)).all()
    data = [
        [
            r.from_port_unlocode,
            r.to_port_unlocode,
            _num(r.distance_nm),
            r.route_type,
            r.canal_transit or "",
            _num(r.transit_days),
            _num(r.canal_toll),
            r.notes or "",
            r.source,
        ]
        for r in rows
    ]
    return headers, data


def _counterparties(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["名称", "类型", "国家", "信用评级", "制裁状态", "联系人", "电话", "邮箱", "SWIFT", "地址"],
        "en": ["Name", "Type", "Country", "Credit Rating", "Sanctions", "Contact", "Phone", "Email", "SWIFT", "Address"],
    }[lang]
    rows = db.scalars(
        apply_module_scope(
            db,
            select(Counterparty).where(Counterparty.tenant_id == auth.tenant_id, Counterparty.deleted_at.is_(None)),
            Counterparty,
            auth,
            "masterdata",
        )
        .order_by(Counterparty.name)
        .limit(MAX_ROWS)
    ).all()
    data = [
        [
            c.name,
            c.type or "",
            c.country or "",
            c.credit_rating or "",
            c.sanctions_status or "",
            c.main_contact or "",
            c.phone or "",
            c.email or "",
            c.swift_code or "",
            c.address or "",
        ]
        for c in rows
    ]
    return headers, data


def _ports(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    # 港口是全局参考表（ports 无 tenant_id 列）——与 /masterdata/ports 同口径
    headers = {
        "zh": ["UN/LOCODE", "名称", "国家", "时区", "纬度", "经度", "类型", "EU", "区域"],
        "en": ["UN/LOCODE", "Name", "Country", "Timezone", "Latitude", "Longitude", "Type", "EU", "Region"],
    }[lang]
    rows = db.scalars(
        select(Port).where(Port.deleted_at.is_(None)).order_by(Port.name).limit(MAX_ROWS)
    ).all()
    data = [
        [
            r.unlocode or "",
            r.name,
            r.country or "",
            r.timezone or "",
            _num(r.latitude),
            _num(r.longitude),
            r.port_type or "",
            "Y" if r.is_eu else "N",
            r.region_code or "",
        ]
        for r in rows
    ]
    return headers, data


def _cargo_names(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["简称", "全称", "货类", "IMO 品名", "IBC", "IMSBC", "UN 号", "危险品", "积载因数 M3/MT", "积载因数 FT3/MT", "状态"],
        "en": ["Short Name", "Full Name", "Class", "IMO Name", "IBC", "IMSBC", "UN No", "Dangerous", "Stow M3/MT", "Stow FT3/MT", "Status"],
    }[lang]
    rows = db.scalars(
        apply_module_scope(
            db,
            select(CargoName).where(CargoName.tenant_id == auth.tenant_id),
            CargoName,
            auth,
            "masterdata",
        )
        .order_by(CargoName.short_name)
        .limit(MAX_ROWS)
    ).all()
    data = [
        [
            c.short_name,
            c.full_name or "",
            c.cargo_class or "",
            c.imo_name or "",
            c.ibc_code or "",
            c.imsbc_code or "",
            c.un_number or "",
            "Y" if c.dangerous else "N",
            _num(c.stow_factor_m3_mt),
            _num(c.stow_factor_ft3_mt),
            "inactive" if c.inactive else "active",
        ]
        for c in rows
    ]
    return headers, data


def _claims(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["索赔号", "类型", "子类", "状态", "航次", "金额", "结算金额", "币种", "时效截止", "备注"],
        "en": ["Claim No", "Type", "Subtype", "Status", "Voyage", "Amount", "Settled", "Currency", "Time Bar", "Notes"],
    }[lang]
    rows = db.scalars(
        apply_module_scope(
            db,
            select(Claim).where(Claim.tenant_id == auth.tenant_id, Claim.status != "deleted"),
            Claim,
            auth,
            "claims",
        )
        .order_by(Claim.claim_no)
        .limit(MAX_ROWS)
    ).all()
    voyages = {v.id: v.voyage_no for v in db.scalars(select(Voyage).where(Voyage.tenant_id == auth.tenant_id)).all()}
    data = [
        [
            c.claim_no,
            c.claim_type or "",
            c.subtype or "",
            c.status or "",
            voyages.get(c.voyage_id, "") if c.voyage_id else "",
            _money(c.amount),
            _money(c.settlement_amount),
            c.currency or "",
            _d(c.time_bar),
            c.notes or "",
        ]
        for c in rows
    ]
    return headers, data


def _charters(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["租约号", "类型", "状态", "船名", "对手方", "装期从", "装期到", "运费率", "运费口径", "货量", "佣金%", "制裁阻断"],
        "en": ["Charter No", "Type", "Status", "Vessel", "Counterparty", "Laycan From", "Laycan To", "Freight Rate", "Basis", "Cargo Qty", "Commission %", "Sanctions Blocked"],
    }[lang]
    rows = db.scalars(
        apply_module_scope(
            db,
            select(Charter).where(Charter.tenant_id == auth.tenant_id, Charter.status != "deleted"),
            Charter,
            auth,
            "chartering",
        )
        .order_by(Charter.charter_no)
        .limit(MAX_ROWS)
    ).all()
    vessels = {v.id: v.name for v in db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id)).all()}
    parties = {c.id: c.name for c in db.scalars(select(Counterparty).where(Counterparty.tenant_id == auth.tenant_id)).all()}
    data = [
        [
            c.charter_no,
            c.charter_type or "",
            c.status or "",
            vessels.get(c.vessel_id, "") if c.vessel_id else "",
            parties.get(c.counterparty_id, "") if c.counterparty_id else "",
            _d(c.laycan_from),
            _d(c.laycan_to),
            _num(c.freight_rate),
            c.freight_basis or "",
            _num(c.cargo_qty),
            _num(c.commission_pct),
            "Y" if c.sanctions_blocked else "N",
        ]
        for c in rows
    ]
    return headers, data


def _laytimes(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["航次", "订舱号", "状态", "允许装卸小时", "实际装卸小时", "超期小时", "结算"],
        "en": ["Voyage", "Booking", "Status", "Allowed Hrs", "Used Hrs", "Demurrage Hrs", "Finalized"],
    }[lang]
    rows = db.scalars(
        apply_module_scope(
            db,
            select(LaytimeCalc).where(LaytimeCalc.tenant_id == auth.tenant_id),
            LaytimeCalc,
            auth,
            "laytime",
        )
        .order_by(LaytimeCalc.created_at.desc())
        .limit(MAX_ROWS)
    ).all()
    voyages = {v.id: v.voyage_no for v in db.scalars(select(Voyage).where(Voyage.tenant_id == auth.tenant_id)).all()}
    data = []
    for r in rows:
        res = r.results or {}
        data.append(
            [
                voyages.get(r.voyage_id, "") if r.voyage_id else "",
                r.booking_reference or "",
                r.status or "",
                _num(res.get("allowed_hours")),
                _num(res.get("used_hours")),
                _num(res.get("demurrage_hours")),
                _d(r.finalized_at),
            ]
        )
    return headers, data


def _bunker_orders(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["订单号", "状态", "船名", "航次", "油种", "订量", "交付量", "单价", "币种", "交船前存量", "交船后存量", "供应商"],
        "en": ["Order No", "Status", "Vessel", "Voyage", "Grade", "Ordered", "Delivered", "Unit Price", "Currency", "ROB Before", "ROB After", "Supplier"],
    }[lang]
    rows = db.scalars(
        apply_module_scope(
            db,
            select(BunkerOrder).where(BunkerOrder.tenant_id == auth.tenant_id, BunkerOrder.status != "deleted"),
            BunkerOrder,
            auth,
            "bunker",
        )
        .order_by(BunkerOrder.order_no)
        .limit(MAX_ROWS)
    ).all()
    vessels = {v.id: v.name for v in db.scalars(select(Vessel).where(Vessel.tenant_id == auth.tenant_id)).all()}
    voyages = {v.id: v.voyage_no for v in db.scalars(select(Voyage).where(Voyage.tenant_id == auth.tenant_id)).all()}
    data = [
        [
            b.order_no,
            b.status or "",
            vessels.get(b.vessel_id, "") if b.vessel_id else "",
            voyages.get(b.voyage_id, "") if b.voyage_id else "",
            b.grade or "",
            _num(b.qty_ordered),
            _num(b.qty_delivered),
            _money(b.unit_price),
            b.currency or "",
            _num(b.rob_before),
            _num(b.rob_after),
            b.supplier or "",
        ]
        for b in rows
    ]
    return headers, data


def _payments(db: Session, auth: AuthContext, lang: str) -> tuple[list[str], list[list[Any]]]:
    headers = {
        "zh": ["付款日期", "发票号", "金额", "币种", "批次", "摘要"],
        "en": ["Paid At", "Invoice No", "Amount", "Currency", "Batch", "Reference"],
    }[lang]
    rows = db.scalars(
        apply_module_scope(
            db,
            select(Payment).where(Payment.tenant_id == auth.tenant_id),
            Payment,
            auth,
            "finance",
        )
        .order_by(Payment.paid_at.desc())
        .limit(MAX_ROWS)
    ).all()
    invoices = {i.id: i.invoice_no for i in db.scalars(select(Invoice).where(Invoice.tenant_id == auth.tenant_id)).all()}
    batches = {b.id: b.batch_number for b in db.scalars(select(PaymentBatch).where(PaymentBatch.tenant_id == auth.tenant_id)).all()}
    data = [
        [
            _d(p.paid_at),
            invoices.get(p.invoice_id, "") if p.invoice_id else "",
            _money(p.amount),
            p.currency or "",
            batches.get(p.batch_id, "") if p.batch_id else "",
            p.reference or "",
        ]
        for p in rows
    ]
    return headers, data


Builder = Callable[[Session, AuthContext, str], tuple[list[str], list[list[Any]]]]

#: 实体 → (许可模块码, 构造器)。
#:
#: **模块码必须与对应列表端点一致**（P2「导出端点角色不齐」）。以前这里写死
#: "finance"，于是：买了 claims / laytime 模块的租户**能看列表却导不出**，
#: 反过来买了 finance 却没买 claims 的租户**不用看列表就能把索赔导出去** ——
#: 许可闸门形同虚设。``tests/test_export_module_parity.py`` 锁住这个一致性。
#:
#: ``tasks`` 留 ``None``：任务列表要管理角色，但导出只给**自己建的/指派给自己
#: 的**行（比列表更窄），不需要管理角色。
ENTITIES: dict[str, tuple[str | None, Builder]] = {
    "voyages": ("operations", _voyages),
    "invoices": ("finance", _invoices),
    "certificates": ("ship_mgmt", _certificates),
    "tasks": (None, _tasks),
    "vessels": ("masterdata", _vessels),
    "distances": ("operations", _distances),
    # P1-2：这 8 个核心列表以前直接 404 EXPORT_NOT_FOUND —— 用户在列表页点
    # "导出"拿到的是"没有这个实体"，等于没有导出功能。全部补齐。
    "counterparties": ("masterdata", _counterparties),
    "ports": ("masterdata", _ports),
    "cargo-names": ("masterdata", _cargo_names),
    "claims": ("claims", _claims),
    "charters": ("chartering", _charters),
    "laytimes": ("laytime", _laytimes),
    "bunker-orders": ("bunker", _bunker_orders),
    "payments": ("finance", _payments),
}


@router.get("/export/{entity}.csv")
def export_csv(
    entity: str,
    lang: str = Query("zh", pattern="^(zh|en)$"),
    include_drafts: bool = Query(False, description="Include draft/pending invoices (invoice export only)"),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    # 实体名归一：前端可能用 "cargo_names" / "cargo-names" 两种写法。
    entity = (entity or "").strip().lower().replace("_", "-")
    spec = ENTITIES.get(entity)
    if spec is None:
        raise HTTPException(
            404,
            detail={
                "code": "EXPORT_NOT_FOUND",
                "entity": entity,
                "message": f"No CSV export for '{entity}'",
                "available": sorted(ENTITIES),
            },
        )
    module_code, builder = spec
    if module_code is not None:
        # 许可 + **读角色**双闸门。以前只有许可轴 → 菜单里看不到该模块的角色
        # 照样能把整张表导出去（"能导不能看"倒挂）。
        require_module_read(module_code)(auth=auth, db=db)
    if entity == "invoices":
        headers, rows = _invoices(db, auth, lang, include_drafts=include_drafts)
    else:
        headers, rows = builder(db, auth, lang)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows([[_guard_cell(c) for c in row] for row in rows])
    content = "\ufeff" + buf.getvalue()
    filename = f"{entity}_{date.today().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# \u2500\u2500 XML API\uff08task D\uff09\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


@router.get("/invoices/{invoice_id}/export-xml")
def export_invoice_xml(
    invoice_id: UUID,
    auth: AuthContext = Depends(require_module_read("finance")),
    db: Session = Depends(get_db),
):
    """Export invoice as modular XML (header + counterparty + payments)."""
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
        # XXE / billion-laughs 防御：禁用 DTD 与实体展开（defusedxml）。
        # 表单 XML 来自客户端 —— 以前直接用 stdlib ElementTree 解析，
        # 带 <!ENTITY> 的载荷可做实体膨胀（十亿 laughs）或外部实体读取。
        root = DefusedET.fromstring(body.xml, forbid_dtd=True)
    except ET.ParseError as exc:
        raise HTTPException(400, detail={"code": "FORM_XML_PARSE", "message": f"Invalid XML: {exc}"})
    except DefusedXmlException as exc:
        raise HTTPException(
            400,
            detail={"code": "FORM_XML_UNSAFE", "message": f"XML contains forbidden constructs: {exc}"},
        )

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
