"""佣金链（长尾 / D4）：运费发票 → 佣金计划 + 经纪人佣金发票草稿。

口径（航运惯例）：
- **地址佣金（address commission）**：船东付租家的运费扣减项
  （bill_by=owner 的结算里作 deduction），此处返回金额供结算引用；
- **经纪佣金（brokerage）**：按租约 brokerage_pct 对发票金额计佣，
  生成 invoice_type="broker_commission" 的**草稿**发票（对手方留空由
  财务指定经纪人，notes 注明来源发票）。

链接链路：invoice.voyage_id → voyage.charter_id → charter 的佣金字段。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models_domain import Charter, Invoice, Voyage


def commission_plan(db: Session, invoice: Invoice) -> dict[str, Any]:
    charter: Charter | None = None
    if invoice.voyage_id:
        voy = db.get(Voyage, invoice.voyage_id)
        if voy and voy.charter_id:
            charter = db.get(Charter, voy.charter_id)
    base = Decimal(str(invoice.amount or 0))
    brokerage_pct = Decimal(str(charter.brokerage_pct or 0)) if charter else Decimal("0")
    address_pct = Decimal(str(charter.address_comm_pct or 0)) if charter else Decimal("0")
    return {
        "invoice_id": str(invoice.id),
        "charter_id": str(charter.id) if charter else None,
        "base_amount": float(base),
        "brokerage_pct": float(brokerage_pct),
        "brokerage_amount": float((base * brokerage_pct / 100).quantize(Decimal("0.01"))),
        "address_comm_pct": float(address_pct),
        "address_commission_amount": float((base * address_pct / 100).quantize(Decimal("0.01"))),
    }


def create_brokerage_invoice(db: Session, invoice: Invoice, *, user_id=None) -> Invoice | None:
    """按经纪佣金生成草稿发票（无佣金字段时返回 None）。commit 留给调用方。"""
    from app.services.doc_numbering import next_doc_number

    plan = commission_plan(db, invoice)
    if plan["brokerage_amount"] <= 0:
        return None
    inv = Invoice(
        tenant_id=invoice.tenant_id,
        invoice_no=next_doc_number(db, invoice.tenant_id, Invoice, Invoice.invoice_no, "CM"),
        invoice_type="broker_commission",
        status="draft",
        currency=invoice.currency,
        amount=Decimal(str(plan["brokerage_amount"])),
        bill_by="broker",
        commission_basis=f"brokerage on {invoice.invoice_no} (charter {plan['charter_id'] or 'n/a'})",
    )
    db.add(inv)
    return inv
