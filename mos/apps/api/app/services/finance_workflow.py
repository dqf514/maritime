"""复合财务工作流显式化（Phase 1）：不变量集中在服务层，路由只做编排。

不变量（tests/test_finance_workflow.py 锁定）：

- **INV-VOID-CREDIT**：发票作废（void）前，已收款项必须**全额红冲**
  （credit note ≥ paid_amount），否则 409 ``CREDIT_NOTE_REQUIRED``。
  这是 DDS 红冲语义：钱已经收了，作废单据必须先有等额反向凭证。
- 状态转移本身由 ``app.services.state_machine`` 的 ``INVOICE_TRANSITIONS`` 把守。

边界说明：void **不**自动生成 GL 反冲分录——红冲（credit note）与 GL 过账
（gl_post）是独立会计动作，由财务人员按确认节奏分别执行。本模块保证的是
单据侧不变量在同一事务内原子完成。
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_finance_ext import CreditNote
from app.models_domain import Invoice
from app.services.state_machine import INVOICE_TRANSITIONS, transition


def credited_amount(db: Session, invoice_id) -> Decimal:
    """该发票项下已签发的红冲合计。"""
    notes = db.scalars(
        select(CreditNote).where(CreditNote.invoice_id == invoice_id, CreditNote.status == "issued")
    ).all()
    return sum((Decimal(str(n.amount or 0)) for n in notes), Decimal("0"))


def assert_void_allowed(db: Session, invoice: Invoice) -> None:
    """INV-VOID-CREDIT：已收款未全额红冲不得作废。"""
    paid = Decimal(str(invoice.paid_amount or 0))
    if paid <= 0:
        return
    credited = credited_amount(db, invoice.id)
    if credited < paid:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CREDIT_NOTE_REQUIRED",
                "message": f"Received amount {paid} must be fully credited (红冲) before void; credited so far {credited}",
                "paid_amount": float(paid),
                "credited_amount": float(credited),
            },
        )


def void_invoice(db: Session, invoice: Invoice) -> Invoice:
    """作废发票：不变量校验 + 状态转移，同事务原子完成（commit 留给调用方）。"""
    assert_void_allowed(db, invoice)
    invoice.status = transition("invoice", invoice.status, "void", INVOICE_TRANSITIONS)
    return invoice


def record_payment(db: Session, invoice: Invoice, amount, reference: str | None = None):
    """记收款（add_payment / D21 银行核销共用的记账内核）。

    校验金额与余额，写 Payment 行并推进发票状态（issued→partially_paid→paid）。
    commit 留给调用方。返回 Payment。
    """
    from app.models_domain import Payment

    amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amt <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "Payment amount must be > 0"})
    if invoice.status not in {"issued", "partially_paid"}:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot pay invoice in status {invoice.status}"})
    total = Decimal(str(invoice.amount)) + Decimal(str(invoice.tax_amount or 0))
    already_paid = Decimal(str(invoice.paid_amount or 0))
    open_balance = total - already_paid
    if amt > open_balance:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "OVERPAYMENT",
                "message": f"Payment {amt} exceeds open balance {open_balance}",
                "open_balance": float(open_balance),
            },
        )
    pay = Payment(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        amount=amt,
        currency=invoice.currency,
        reference=reference,
    )
    db.add(pay)
    invoice.paid_amount = already_paid + amt
    if invoice.paid_amount >= total:
        invoice.status = transition("invoice", invoice.status, "paid", INVOICE_TRANSITIONS)
    elif invoice.status == "issued":
        invoice.status = transition("invoice", "issued", "partially_paid", INVOICE_TRANSITIONS)
    return pay
