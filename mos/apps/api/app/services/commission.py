"""佣金链（长尾 / D4）：运费发票 → 佣金计划 + 经纪人佣金发票草稿。

口径（航运惯例）：
- **地址佣金（address commission）**：船东付租家的运费扣减项
  （bill_by=owner 的结算里作 deduction），此处返回金额供结算引用；
- **经纪佣金（brokerage）**：按租约 brokerage_pct 对发票金额计佣，
  生成 invoice_type="broker_commission" 的**草稿**发票（对手方留空由
  财务指定经纪人，notes 注明来源发票）。

链接链路：invoice.voyage_id → voyage.charter_id → charter 的佣金字段。

Phase 6（财务纵深）：佣金类型扩到 8 类 —— 除 address/brokerage 外新增
demurrage / claim / freight_relet / owner / bareboat / equipment 佣金，
统一走 :func:`calculate_commission` 计佣并落 :class:`CommissionType` 明细。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models_domain import Charter, Invoice, Voyage
from app.models_finance_ext import CommissionType

# 8 类佣金：default_rate_pct 为行业缺省费率，调用方可显式覆盖。
COMMISSION_TYPES: dict[str, dict[str, Any]] = {
    "address_commission": {
        "label": "Address commission",
        "label_zh": "地址佣金",
        "default_rate_pct": Decimal("2.5"),
        "applies_to": ["freight", "hire", "demurrage"],
    },
    "brokerage": {
        "label": "Brokerage",
        "label_zh": "经纪佣金",
        "default_rate_pct": Decimal("1.25"),
        "applies_to": ["freight", "hire", "demurrage"],
    },
    "demurrage_commission": {
        "label": "Demurrage commission",
        "label_zh": "滞期佣金",
        "default_rate_pct": Decimal("5.0"),
        "applies_to": ["demurrage"],
    },
    "claim_commission": {
        "label": "Claim commission",
        "label_zh": "索赔佣金",
        "default_rate_pct": Decimal("5.0"),
        "applies_to": ["claim"],
    },
    "freight_relet_commission": {
        "label": "Freight / relet commission",
        "label_zh": "运费/转租佣金",
        "default_rate_pct": Decimal("2.5"),
        "applies_to": ["freight"],
    },
    "owner_commission": {
        "label": "Owner's commission",
        "label_zh": "船东佣金",
        "default_rate_pct": Decimal("1.25"),
        "applies_to": ["freight", "hire"],
    },
    "bareboat_commission": {
        "label": "Bareboat commission",
        "label_zh": "光租佣金",
        "default_rate_pct": Decimal("1.25"),
        "applies_to": ["hire"],
    },
    "equipment_commission": {
        "label": "Equipment contract commission",
        "label_zh": "设备合同佣金",
        "default_rate_pct": Decimal("1.0"),
        "applies_to": ["other"],
    },
}

COMMISSION_TYPE_NAMES = tuple(COMMISSION_TYPES.keys())


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


def commission_type_catalog() -> list[dict[str, Any]]:
    """静态佣金类型目录（8 类，含缺省费率与适用发票类型）。"""
    return [
        {
            "commission_type": key,
            "label": spec["label"],
            "label_zh": spec["label_zh"],
            "default_rate_pct": float(spec["default_rate_pct"]),
            "applies_to": list(spec["applies_to"]),
        }
        for key, spec in COMMISSION_TYPES.items()
    ]


def calculate_commission(
    commission_type: str,
    base_amount: Decimal | float | str,
    rate_pct: Decimal | float | str | None = None,
) -> dict[str, Any]:
    """按类型计佣：calculated_amount = base × rate_pct / 100（两位小数）。

    ``rate_pct`` 缺省时取该佣金类型的行业缺省费率。未知类型抛 ValueError。
    """
    spec = COMMISSION_TYPES.get(commission_type)
    if spec is None:
        raise ValueError(
            f"Unknown commission_type '{commission_type}'; expected one of {list(COMMISSION_TYPE_NAMES)}"
        )
    base = Decimal(str(base_amount))
    rate = Decimal(str(rate_pct)) if rate_pct is not None else Decimal(str(spec["default_rate_pct"]))
    if rate < 0:
        raise ValueError("rate_pct must be >= 0")
    amount = (base * rate / 100).quantize(Decimal("0.01"))
    return {
        "commission_type": commission_type,
        "base_amount": float(base),
        "rate_pct": float(rate),
        "calculated_amount": float(amount),
    }


def create_commission_record(
    db: Session,
    tenant_id: UUID,
    commission_type: str,
    base_amount: Decimal | float | str,
    rate_pct: Decimal | float | str | None = None,
    *,
    invoice_id: UUID | None = None,
    counterparty_id: UUID | None = None,
    currency: str = "USD",
) -> CommissionType:
    """计佣并落 CommissionType 明细行。commit 留给调用方。"""
    calc = calculate_commission(commission_type, base_amount, rate_pct)
    row = CommissionType(
        tenant_id=tenant_id,
        commission_type=calc["commission_type"],
        base_amount=Decimal(str(calc["base_amount"])),
        rate_pct=Decimal(str(calc["rate_pct"])),
        calculated_amount=Decimal(str(calc["calculated_amount"])),
        currency=currency,
        invoice_id=invoice_id,
        counterparty_id=counterparty_id,
    )
    db.add(row)
    db.flush()
    return row
