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

from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Charter, Invoice, Voyage
from app.models_finance_ext import CommissionType
from app.services.money import CENT, round_half_up

#: 落库精度 —— 与 ``CommissionType`` 的列精度对齐（P1-B8 / P2-B23）：
#: ``base_amount`` → ``Numeric(18,2)``、``rate_pct`` → ``Numeric(8,4)``。
BASE_PLACES = 2
RATE_PLACES = 4

#: ``Invoice.commission_basis`` 只存**规范口径码**（net / gross）。
#: 以前这里写的是一句 60+ 字的自由文本（"brokerage on INV-001 (charter ...)"），
#: 落到 ``String(16)`` 列上 → PG 报 StringDataRightTruncation → 500（P1-B2），
#: 而且下游按 net/gross 解析时静默落回 "gross"，口径丢失。
COMMISSION_BASIS_CODES = ("net", "gross")

# 佣金费率上限（百分数）—— 超过 100% 的佣金必然是录入错误（P1-B27）
MAX_COMMISSION_PCT = Decimal("100")

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


def _charter_commission_pcts(charter: Charter | None) -> tuple[Decimal, Decimal]:
    """(brokerage_pct, address_comm_pct) —— 越界即报错，不静默按离谱费率计佣。"""
    brokerage = Decimal(str(charter.brokerage_pct or 0)) if charter else Decimal("0")
    address = Decimal(str(charter.address_comm_pct or 0)) if charter else Decimal("0")
    for name, pct in (("brokerage_pct", brokerage), ("address_comm_pct", address)):
        if pct < 0 or pct > MAX_COMMISSION_PCT:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_COMMISSION_PCT",
                    "message": (
                        f"charter {name} must be between 0 and {MAX_COMMISSION_PCT}, got {pct}"
                    ),
                },
            )
    return brokerage, address


def _commission_base(invoice: Invoice, address_pct: Decimal) -> tuple[Decimal, str]:
    """佣金计费基数（**毛额**）+ 口径标签。

    发票金额可能是**已扣地址佣金**的净额（租约租金发票路径：
    gross − address commission = invoice.amount）。拿净额再算一次佣金就是
    重复收费（P1-B1）。这里统一以毛额为基数：

    - ``meta.hire.gross_amount``（租约租金发票路径写下的毛额）优先；
    - 否则读 ``Invoice.commission_basis``（``net`` / ``gross``，P1-B2）：
      ``net`` → 由净额反推毛额；``gross`` 或缺省 → 发票金额即毛额。
    """
    meta = invoice.meta if isinstance(invoice.meta, dict) else {}
    hire = meta.get("hire") if isinstance(meta, dict) else None
    if isinstance(hire, dict) and hire.get("gross_amount") is not None:
        return Decimal(str(hire["gross_amount"])), "gross"
    amount = Decimal(str(invoice.amount or 0))
    basis = str(invoice.commission_basis or "").strip().lower()
    if basis == "net" and address_pct > 0:
        gross = (amount / (Decimal("1") - address_pct / Decimal("100"))).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        return gross, "net"
    return amount, basis if basis in ("net", "gross") else "gross"


def _commission_plan_decimal(db: Session, invoice: Invoice) -> dict[str, Any]:
    """佣金计划（Decimal 口径）—— 内部计算与落库都走这里。"""
    charter: Charter | None = None
    if invoice.voyage_id:
        voy = db.get(Voyage, invoice.voyage_id)
        if voy and voy.charter_id:
            charter = db.get(Charter, voy.charter_id)
    brokerage_pct, address_pct = _charter_commission_pcts(charter)
    base, basis = _commission_base(invoice, address_pct)
    brokerage_amount = (base * brokerage_pct / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    address_amount = (base * address_pct / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "invoice_id": str(invoice.id),
        "charter_id": str(charter.id) if charter else None,
        "base_amount": base,
        "base_basis": basis,
        "brokerage_pct": brokerage_pct,
        "brokerage_amount": brokerage_amount,
        "address_comm_pct": address_pct,
        "address_commission_amount": address_amount,
        "total_commission": (brokerage_amount + address_amount).quantize(CENT, rounding=ROUND_HALF_UP),
    }


def commission_plan(db: Session, invoice: Invoice) -> dict[str, Any]:
    """佣金计划：**一个基数、算一次**。

    地址佣金与经纪佣金都按同一毛额基数计算（P1-B1）；基数口径见
    :func:`_commission_base`（识别已扣佣金的净额发票与 ``commission_basis``）。
    """
    p = _commission_plan_decimal(db, invoice)
    return {
        "invoice_id": p["invoice_id"],
        "charter_id": p["charter_id"],
        "base_amount": float(p["base_amount"]),
        "base_basis": p["base_basis"],
        "brokerage_pct": float(p["brokerage_pct"]),
        "brokerage_amount": float(p["brokerage_amount"]),
        "address_comm_pct": float(p["address_comm_pct"]),
        "address_commission_amount": float(p["address_commission_amount"]),
        # 本张发票上应当确认的佣金合计（避免各处重复加总）
        "total_commission": float(p["total_commission"]),
    }


def _tenant_base_currency(db: Session, tenant_id: UUID) -> str:
    """租户本位币（``Company.base_currency``，缺省 USD）。"""
    from app.models_wave1 import Company

    comp = db.scalar(select(Company).where(Company.tenant_id == tenant_id).limit(1))
    return (comp.base_currency if comp and comp.base_currency else "USD").upper()


def _commission_fx(
    db: Session, invoice: Invoice, amount: Decimal
) -> tuple[Decimal | None, Decimal | None]:
    """佣金单的 (fx_rate, base_amount)。

    佣金单与源单**同币种**，所以口径必须与源单一致：源单有汇率就沿用源单汇率，
    本币金额 = 佣金额 × 汇率。以前佣金单只写 ``currency``、``fx_rate`` /
    ``base_amount`` 留空 → 下游 ``money.invoice_base_amount()`` 走"原币当本币"
    的兜底分支，USD 佣金被当成 EUR 本位币直接入账（金额错一个汇率倍数）。
    """
    src_rate = getattr(invoice, "fx_rate", None)
    if src_rate is not None:
        rate = Decimal(str(src_rate))
        if rate > 0:
            return rate, (Decimal(str(amount)) * rate).quantize(CENT, rounding=ROUND_HALF_UP)
        return None, None

    ccy = (invoice.currency or "USD").upper()
    base_ccy = _tenant_base_currency(db, invoice.tenant_id)
    if ccy == base_ccy:
        return Decimal("1"), Decimal(str(amount)).quantize(CENT, rounding=ROUND_HALF_UP)

    # 源单本身没存汇率：按当前汇率补一次；取不到就留空（不猜 1:1）——
    # 与源单同口径，缺汇率的单据在签发前必须补齐。
    from app.services.fx_date_rules import resolve_fx_rate

    rate = resolve_fx_rate(db, invoice.tenant_id, ccy, base_ccy)
    if rate is None or Decimal(str(rate)) <= 0:
        return None, None
    rate = Decimal(str(rate))
    return rate, (Decimal(str(amount)) * rate).quantize(CENT, rounding=ROUND_HALF_UP)


def create_brokerage_invoice(db: Session, invoice: Invoice, *, user_id=None) -> Invoice | None:
    """按经纪佣金生成草稿发票（无佣金字段时返回 None）。commit 留给调用方。

    ``commission_basis`` 只落**规范口径码**（``net`` / ``gross``，即本次计佣
    所用的基数口径），说明文字放 ``meta``（P1-B2）—— 以前这里写的是一句
    60+ 字的自由文本，落到 ``String(16)`` 列上 PG 直接 500，而且按 net/gross
    解析时静默变成 "gross"，口径丢失。
    """
    from app.services.doc_numbering import next_doc_number

    plan = _commission_plan_decimal(db, invoice)
    if plan["brokerage_amount"] <= 0:
        return None
    basis = plan["base_basis"] if plan["base_basis"] in COMMISSION_BASIS_CODES else "gross"
    fx_rate, base_amount = _commission_fx(db, invoice, plan["brokerage_amount"])
    inv = Invoice(
        tenant_id=invoice.tenant_id,
        invoice_no=next_doc_number(db, invoice.tenant_id, Invoice, Invoice.invoice_no, "CM"),
        invoice_type="broker_commission",
        status="draft",
        currency=invoice.currency,
        amount=plan["brokerage_amount"],
        fx_rate=fx_rate,
        base_amount=base_amount,
        bill_by="broker",
        commission_basis=basis,
        meta={
            "commission": {
                "description": (
                    f"brokerage on {invoice.invoice_no} (charter {plan['charter_id'] or 'n/a'})"
                ),
                "source_invoice_id": str(invoice.id),
                "source_invoice_no": invoice.invoice_no,
                "charter_id": plan["charter_id"],
                "base_basis": basis,
                "brokerage_pct": str(plan["brokerage_pct"]),
                "base_amount": str(plan["base_amount"]),
            }
        },
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


def _commission_calc(
    commission_type: str,
    base_amount: Decimal | float | str,
    rate_pct: Decimal | float | str | None = None,
) -> dict[str, Any]:
    """Decimal 口径的计佣核心（全程 Decimal，落库不再经过 float 往返）。

    **先量化再计算**：基数按 ``Numeric(18,2)``、费率按 ``Numeric(8,4)``
    显式 ROUND_HALF_UP 量化（P1-B8 / P2-B23）。以前是把未量化的 Decimal 直接
    丢进 Numeric 列 —— PG 会静默四舍五入、SQLite 不会，同一段代码两个库存出
    两个值，读回来的金额还可能带 3 位小数。量化后再算，落库行与"用落库值
    复算"的结果自洽。
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
    if rate > MAX_COMMISSION_PCT:
        # 500% 的佣金必然是录入错误（P1-B27）
        raise ValueError(f"rate_pct must be <= {MAX_COMMISSION_PCT}, got {rate}")
    base = round_half_up(base, BASE_PLACES)
    rate = round_half_up(rate, RATE_PLACES)
    amount = (base * rate / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "commission_type": commission_type,
        "base_amount": base,
        "rate_pct": rate,
        "calculated_amount": amount,
    }


def calculate_commission(
    commission_type: str,
    base_amount: Decimal | float | str,
    rate_pct: Decimal | float | str | None = None,
) -> dict[str, Any]:
    """按类型计佣：calculated_amount = base × rate_pct / 100（两位小数）。

    ``rate_pct`` 缺省时取该佣金类型的行业缺省费率。未知类型抛 ValueError；
    费率超出 0–100% 抛 ValueError（P1-B27）。
    """
    calc = _commission_calc(commission_type, base_amount, rate_pct)
    return {
        "commission_type": calc["commission_type"],
        "base_amount": float(calc["base_amount"]),
        "rate_pct": float(calc["rate_pct"]),
        "calculated_amount": float(calc["calculated_amount"]),
    }


def calculate_commission_decimal(
    commission_type: str,
    base_amount: Decimal | float | str,
    rate_pct: Decimal | float | str | None = None,
) -> dict[str, Any]:
    """Decimal 口径的计佣（**落库路径用**）。

    与 :func:`calculate_commission` 同一算法，但返回值保持 Decimal —— 落库前
    不做 float 往返（``Decimal(str(float))`` 会把 12345.679999999999 这种
    尾巴带进 Numeric 列，P2-B23）。
    """
    return _commission_calc(commission_type, base_amount, rate_pct)


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
    """计佣并落 CommissionType 明细行。commit 留给调用方。

    落库值按列精度量化：``base_amount`` 2 位、``rate_pct`` 4 位、金额 2 位
    （显式 ROUND_HALF_UP，P1-B8 / P2-B23）。
    """
    calc = _commission_calc(commission_type, base_amount, rate_pct)
    row = CommissionType(
        tenant_id=tenant_id,
        commission_type=calc["commission_type"],
        # 直接落 Decimal —— 以前 Decimal(str(float)) 会把 12345.679999999999
        # 这种 float 往返尾巴存进 Numeric 列（P2-B23）
        base_amount=round_half_up(calc["base_amount"], BASE_PLACES),
        rate_pct=round_half_up(calc["rate_pct"], RATE_PLACES),
        calculated_amount=round_half_up(calc["calculated_amount"], BASE_PLACES),
        currency=currency,
        invoice_id=invoice_id,
        counterparty_id=counterparty_id,
    )
    db.add(row)
    db.flush()
    return row
