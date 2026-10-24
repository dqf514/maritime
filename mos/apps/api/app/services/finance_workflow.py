"""复合财务工作流显式化（Phase 1）：不变量集中在服务层，路由只做编排。

不变量（tests/test_finance_workflow.py 锁定）：

- **INV-VOID-CREDIT**：发票作废（void）前，已收款项必须**全额红冲**
  （credit note ≥ paid_amount），否则 409 ``CREDIT_NOTE_REQUIRED``。
  这是 DDS 红冲语义：钱已经收了，作废单据必须先有等额反向凭证。
- 状态转移本身由 ``app.services.state_machine`` 的 ``INVOICE_TRANSITIONS`` 把守。

会计侧（审计 P0-B2 · 红冲必须写反分录）：

红冲（credit note）现在**三样东西一起写**，单据与总账不再分叉：

1. ``CreditNote`` 凭证行；
2. 一张**负数** ``Invoice`` 行（``credit_note_of_id`` 指回原发票）——
   账龄（``/finance/aging``）与航次 P&L（``services/pnl.py``）只认 Invoice 行；
3. **反向分录**（``PeriodJournal``）—— 原发票已过账时，红冲按**同一套科目、
   金额相反**把原分录冲回。旧实现只写前两样：单据（子账）里有红冲，总账里
   没有 —— 试算平衡表是错的。

反向分录走 ``services.gl_engine`` 的既有口径（科目 / 本位币 / 期间），
并由 ``(tenant_id, journal_type, source_type, source_id)`` 唯一约束保证
**幂等**：同一张红冲重复跑只会拿到同一张分录，不会二次过账。

边界说明：作废（void）本身**不**生成 GL 反冲分录 —— 作废的是单据状态，
红冲才是会计动作；已收款项的**反向收款**由 ``record_payment`` 的冲正流程
处理。本模块保证的是单据侧不变量与红冲的会计侧在同一事务内原子完成。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
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


def record_payment(
    db: Session,
    invoice: Invoice,
    amount,
    reference: str | None = None,
    created_by=None,
):
    """登记一笔收款。

    ``created_by`` 是登记人（行级数据权限的归属列）—— 不传则留空
    （系统/邮件来源的收款），此时「只看自己建的」的用户看不到该行。
    """
    """记收款（add_payment / D21 银行核销共用的记账内核）。

    校验金额与余额，写 Payment 行并推进发票状态（issued→partially_paid→paid）。
    commit 留给调用方。返回 Payment。

    并发安全（25 用户并发验收发现的双花缺陷修复）：余额认领改为**条件 UPDATE**——
    由数据库串行化（SQLite 写锁 / PostgreSQL 行锁），锁等待结束后 WHERE 按最新已提交
    数据重算，`paid_amount + amt <= total` 不再成立即认领失败。旧实现读-改-写依赖
    请求开始时的内存快照，25 线程同时全额支付会出现多笔同时通过余额校验（TOCTOU）。
    """
    from app.models_domain import Payment

    from app.services.money import invoice_gross, money

    amt = money(amount)
    if amt <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "Payment amount must be > 0"})
    if invoice.status not in {"issued", "partially_paid"}:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot pay invoice in status {invoice.status}"})
    # 总额口径 = 金额 + 税（与账龄、付款批次一致）
    total = invoice_gross(invoice)

    # 原子认领：同一发票的并发收款在数据库层排队，WHERE 按提交后状态重算
    claimed = (
        db.query(Invoice)
        .filter(
            Invoice.id == invoice.id,
            Invoice.tenant_id == invoice.tenant_id,
            Invoice.status.in_(("issued", "partially_paid")),
            func.coalesce(Invoice.paid_amount, 0) + amt <= total,
        )
        .update({Invoice.paid_amount: func.coalesce(Invoice.paid_amount, 0) + amt}, synchronize_session=False)
    )
    if claimed != 1:
        # 认领失败：已被并发收款占满余额或状态已流转——刷新取权威值给准确错误码
        db.expire(invoice)
        db.refresh(invoice)
        if invoice.status not in {"issued", "partially_paid"}:
            raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot pay invoice in status {invoice.status}"})
        open_balance = total - Decimal(str(invoice.paid_amount or 0))
        raise HTTPException(
            status_code=409,
            detail={
                "code": "OVERPAYMENT",
                "message": f"Payment {amt} exceeds open balance {open_balance}",
                "open_balance": float(open_balance),
            },
        )

    # 认领成功（paid_amount 已在库中原子累加）→ refresh 拿权威值，写 Payment 行并推进状态
    db.expire(invoice)
    db.refresh(invoice)
    pay = Payment(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        amount=amt,
        currency=invoice.currency,
        reference=reference,
        created_by=created_by,
    )
    db.add(pay)
    if invoice.paid_amount >= total:
        invoice.status = transition("invoice", invoice.status, "paid", INVOICE_TRANSITIONS)
    elif invoice.status == "issued":
        invoice.status = transition("invoice", "issued", "partially_paid", INVOICE_TRANSITIONS)
    return pay


# —— 红冲的会计侧（审计 P0-B2）—————————————————————————————————


def _cn_amounts(credit_note_invoice: Invoice) -> tuple[Decimal, Decimal, Decimal]:
    """红冲单的本位币金额 → ``(总额, 税前, 税额)``（均为正数）。

    口径与 ``services.money.invoice_base_gross`` 一致：有 ``base_amount`` 用它，
    否则按发票汇率折算原币金额；都没有就是原币值（单币种租户）。
    符号取绝对值 —— 方向（借/贷）在调用处按"反向分录"翻。
    """
    from app.services import money as M

    base = getattr(credit_note_invoice, "base_amount", None)
    rate = M.invoice_rate(credit_note_invoice)
    if base is not None:
        net = abs(M.money(base))
    else:
        amount = abs(M.invoice_amount(credit_note_invoice))
        net = M.money(amount * rate) if rate else amount
    tax = abs(M.invoice_tax(credit_note_invoice))
    if rate and base is not None:
        tax = M.money(tax * rate)
    gross = M.money(net + tax)
    return gross, net, tax


def _reversal_entries(
    db: Session,
    tenant_id,
    original_invoice: Invoice,
    credit_note_invoice: Invoice,
) -> list[dict]:
    """红冲的反向分录行 —— **同一套科目、金额相反**。

    科目取自**原发票**（不是红冲单自己的类型）：红冲冲的是应收 / 应付，
    科目必须与原分录一致，否则总账一边冲应收账款、一边冲应付账款。
    金额取红冲单自己的本位币口径（税前 + 税），与单据（子账）逐科目对齐。

    收入侧原分录：借 应收账款(总额) / 贷 营业收入(税前) + 应交税费(销项)
      → 反向：贷 应收账款 / 借 营业收入 + 借 应交税费
    成本侧原分录：借 费用(税前) + 进项税 / 贷 应付账款(总额)
      → 反向：贷 费用 + 贷 进项税 / 借 应付账款
    """
    from app.services import money as M
    from app.services.gl_engine import _account_name, _invoice_account_codes

    codes = _invoice_account_codes(db, tenant_id, M.invoice_type_code(original_invoice))
    gross, net, tax = _cn_amounts(credit_note_invoice)

    if M.is_revenue_side(original_invoice):
        legs = [
            (codes["receivable"], gross, "credit"),
            (codes["revenue"], net, "debit"),
        ]
        if tax != 0:
            legs.append((codes["tax_payable"], tax, "debit"))
    else:
        legs = [
            (codes["expense"], net, "credit"),
            (codes["payable"], gross, "debit"),
        ]
        if tax != 0:
            legs.append((codes["tax_receivable"], tax, "credit"))

    entries: list[dict] = []
    for account, amount, direction in legs:
        if amount == 0:
            continue
        debit = amount if direction == "debit" else Decimal("0")
        credit = amount if direction == "credit" else Decimal("0")
        entries.append(
            {
                "account_code": account,
                "account_name": _account_name(db, tenant_id, account),
                "debit": str(M.money(debit)),
                "credit": str(M.money(credit)),
                "reference": f"INV:{credit_note_invoice.invoice_no}",
                "description": (
                    f"Credit note reversal of {original_invoice.invoice_no} "
                    f"({credit_note_invoice.invoice_no})"
                ),
            }
        )
    return entries


def post_credit_note_reversal(
    db: Session,
    tenant_id,
    original_invoice: Invoice,
    credit_note_invoice: Invoice,
    user_id=None,
):
    """红冲的**反向分录**（审计 P0-B2）—— 总账必须与单据一致。

    - 原发票**没有**过账 → 总账里没有可冲的分录，返回 ``(None, False)``
      （红冲单仍可作为独立单据单独过账，不会凭空多出一张分录）；
    - 原发票已过账 → 按**同一套科目、金额相反**写一张分录，把原分录冲回，
      总账净额与单据净额一致；
    - **幂等**：分录挂在红冲单自己身上（``journal_type="invoice"`` +
      ``source_type="invoice"`` + ``source_id=红冲发票 id``），重复跑只会拿到
      同一张分录（``created=False``），不会二次过账。

    返回 ``(journal, created)``；**commit 留给调用方**（过账失败不应留下
    半张红冲单）。
    """
    from app.models_gl import PeriodJournal
    from app.services.gl_engine import _tenant_base_currency, post_journal
    from app.services.timeutil import utcnow_naive

    # 幂等：这笔红冲已经过账 → 返回原分录，不再写第二张
    existing = db.scalar(
        select(PeriodJournal).where(
            PeriodJournal.tenant_id == tenant_id,
            PeriodJournal.journal_type == "invoice",
            PeriodJournal.source_type == "invoice",
            PeriodJournal.source_id == credit_note_invoice.id,
        )
    )
    if existing is not None:
        return existing, False

    # 原发票的分录 —— 没有它，总账里没有可冲的东西
    original_journal = db.scalar(
        select(PeriodJournal).where(
            PeriodJournal.tenant_id == tenant_id,
            PeriodJournal.journal_type == "invoice",
            PeriodJournal.source_type == "invoice",
            PeriodJournal.source_id == original_invoice.id,
        )
    )
    if original_journal is None:
        return None, False

    entries = _reversal_entries(db, tenant_id, original_invoice, credit_note_invoice)
    if not entries:
        return None, False

    issued_at = getattr(credit_note_invoice, "issued_at", None) or utcnow_naive()
    period = issued_at.strftime("%Y-%m")
    gross, _net, _tax = _cn_amounts(credit_note_invoice)
    journal = post_journal(
        db,
        tenant_id,
        period=period,
        journal_type="invoice",
        entries=entries,
        description=(
            f"Credit note reversal of {original_invoice.invoice_no} "
            f"({credit_note_invoice.invoice_no})"
        ),
        user_id=user_id,
        currency=_tenant_base_currency(db, tenant_id),
        source_type="invoice",
        source_id=credit_note_invoice.id,
    )
    # 红冲单自身的过账标记 —— 与 /invoices/{id}/gl-post 的口径一致
    credit_note_invoice.gl_posted = True
    credit_note_invoice.meta = {
        **(credit_note_invoice.meta or {}),
        "gl_posted_at": datetime.now(timezone.utc).isoformat(),
        "gl_journal_id": str(journal.id),
        "gl_reversal_of": str(original_invoice.id),
        "gl_reversal_amount": str(gross),
    }
    return journal, True


def issue_credit_note(
    db: Session,
    tenant_id,
    original_invoice: Invoice,
    amount,
    reason: str | None = None,
    user_id=None,
):
    """红冲完整工作流（审计 P0-B2）：凭证行 + 负数发票行 + 反向分录。

    三样东西在**同一事务**里写完（commit 留给调用方），单据与总账一起动：

    1. ``CreditNote`` 凭证行；
    2. 负数 ``Invoice`` 行（账龄 / 航次 P&L 靠它与原发票天然相抵）；
    3. 反向分录（原发票已过账时；见 :func:`post_credit_note_reversal`）。

    金额上限 = 发票总额 − 已红冲额；超了 409 ``CREDIT_EXCEEDS_BALANCE``。
    返回 ``(credit_note, credit_note_invoice)``。

    路由接线点：``app/routers/invoices.py::create_credit_note``（红冲入口）。
    路由里原来的"写 CreditNote + 写负数 Invoice"两段可以整体换成调本函数，
    金额校验 / 单号 / 反向分录都在这里，路由只留编排。
    """
    from app.services import money as M
    from app.services.doc_numbering import next_doc_number
    from app.services.timeutil import utcnow_naive

    amt = M.money(amount)
    if amt <= 0:
        raise HTTPException(
            422, detail={"code": "INVALID_AMOUNT", "message": "Credit note amount must be > 0"}
        )
    total = M.invoice_gross(original_invoice)
    balance = total - credited_amount(db, original_invoice.id)
    if amt > balance:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CREDIT_EXCEEDS_BALANCE",
                "message": f"Credit note {amt} exceeds un-credited balance {balance}",
                "balance": float(balance),
            },
        )

    row = CreditNote(
        tenant_id=tenant_id,
        invoice_id=original_invoice.id,
        credit_note_no=next_doc_number(db, tenant_id, CreditNote, CreditNote.credit_note_no, "CN"),
        amount=amt,
        reason=reason,
        status="issued",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()

    # 负数发票行 —— 账龄 / P&L 靠它相抵
    cn_inv = Invoice(
        tenant_id=tenant_id,
        invoice_no=next_doc_number(db, tenant_id, Invoice, Invoice.invoice_no, "CN"),
        invoice_type="credit_note",
        status="issued",
        counterparty_id=original_invoice.counterparty_id,
        voyage_id=original_invoice.voyage_id,
        amount=-amt,
        tax_amount=Decimal("0"),
        currency=original_invoice.currency,
        fx_rate=original_invoice.fx_rate,
        base_amount=(
            -M.invoice_to_base(original_invoice, amt)
            if (original_invoice.fx_rate or original_invoice.base_amount is not None)
            else None
        ),
        credit_note_of_id=original_invoice.id,
        issued_at=utcnow_naive(),
        created_by=user_id,
        updated_by=user_id,
        meta={
            "credit_note_id": str(row.id),
            "credit_note_no": row.credit_note_no,
            "credit_note_of_id": str(original_invoice.id),
            "credit_note_of_no": original_invoice.invoice_no,
            "reason": reason,
        },
    )
    db.add(cn_inv)
    db.flush()

    # 会计侧：把原分录冲回（幂等；原发票没过账时无分录可冲）
    post_credit_note_reversal(db, tenant_id, original_invoice, cn_inv, user_id=user_id)
    return row, cn_inv


def post_reversals_for_credit_notes(
    db: Session,
    tenant_id,
    original_invoice: Invoice,
    user_id=None,
) -> list:
    """原发票过账后，把针对它、还没冲回的红冲**补过账**。

    顺序问题：红冲先于原发票过账时（红冲那一刻总账里还没有可冲的分录），
    原发票过账的那一刻必须把红冲补上，否则总账又和单据分叉。

    路由接线点：``app/routers/invoices.py::gl_post``（发票过账入口）——
    在 ``post_invoice_journal`` 之后调一次本函数即可。

    返回本次补写的分录列表（已冲过的不重复写）。
    """
    rows = db.scalars(
        select(Invoice).where(
            Invoice.tenant_id == tenant_id,
            Invoice.credit_note_of_id == original_invoice.id,
        )
    ).all()
    out: list = []
    for cn_inv in rows:
        journal, created = post_credit_note_reversal(
            db, tenant_id, original_invoice, cn_inv, user_id=user_id
        )
        if journal is not None and created:
            out.append(journal)
    return out

