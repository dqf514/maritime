"""发票/收款/红冲/应计路由（红冲不变量见 services/finance_workflow）。"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module

from app.models_domain import Charter, Invoice, Payment, Voyage, VoyageAccrual
from app.models_finance_ext import CreditNote, OffHireEvent
from app.services.doc_numbering import next_doc_number
from app.services.finance_workflow import (
    assert_void_allowed,
    post_credit_note_reversal,
    post_reversals_for_credit_notes,
    record_payment,
)
from app.services.hire_engine import _off_hire_in_period, create_hire_statement
from app.services.audit import audit
from app.services.domain_events import emit, ensure_task
from app.services.system_text import text
from app.services.ui_text import user_locale
from app.services.recycle import soft_delete
from app.services.state_machine import INVOICE_TRANSITIONS, transition
from app.services.optimistic_lock import assert_fresh

from app.routers._finance_common import _alive, _base_currency, _credited_amount, _resolve_fx_rate
from app.services.approval_limits import assert_within_limit
from app.services.invoice_mirror import assert_mirror_writable, sync_mirrors
from app.services.invoice_types import invalid_invoice_type_detail, is_valid_invoice_type
from app.services.data_scope import apply_module_scope
from app.services.money import (
    invoice_gross,
    invoice_open,
    invoice_to_base,
    invoice_type_code,
    money,
)
from app.services.period_close import assert_period_open

from app.models_wave1 import Counterparty
from app.services.sanctions import assert_not_sanctioned
from app.services.tenant_guard import scoped_get, scoped_query
from app.services.timeutil import utcnow_naive

router = APIRouter()

log = logging.getLogger("marios.invoices")


def _invoice_archive_bytes(db: Session, tenant_id, row) -> tuple[bytes, str, str, dict]:
    """归档用的发票文件 —— PDF 优先，缺引擎退回凭证 CSV。

    返回 ``(content, filename, content_type, meta)``。PDF 路径会顺带写一行
    :class:`DocumentRender` 出档记录，之后在「出档」里能回溯到这一份。
    """
    meta = {"invoice_no": row.invoice_no, "status": row.status}
    from app.services import doc_engine

    try:
        result = doc_engine.render_document(
            db, tenant_id,
            entity_type="invoice", entity_id=row.id,
        )
        pdf = doc_engine.html_to_pdf(result.html)
        doc_engine.record_render(
            db, tenant_id,
            entity_type="invoice", entity_id=row.id,
            result=result, content=pdf, fmt="pdf",
            content_type="application/pdf",
            snapshot=doc_engine.build_letterhead(db, tenant_id),
        )
        meta["template_version"] = result.template_version
        return pdf, result.filename, "application/pdf", meta
    except doc_engine.PDFEngineUnavailable:
        # Chromium 未装 —— 退回 CSV，归档链路不能断
        pass
    except Exception:  # noqa: BLE001
        log.exception("invoice PDF archive failed for %s, falling back to CSV", row.id)

    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["field", "value"])
    for k, v in (
        ("invoice_no", row.invoice_no),
        ("invoice_type", row.invoice_type),
        ("status", row.status),
        ("currency", row.currency),
        ("amount", row.amount),
        ("tax_amount", row.tax_amount),
        ("due_date", row.due_date),
        ("issued_at", row.issued_at),
    ):
        w.writerow([k, v if v is not None else ""])
    return buf.getvalue().encode("utf-8-sig"), f"invoice_{row.invoice_no}.csv", "text/csv", meta


def _office_escalate_invoice(db: Session, tenant_id, row) -> None:
    """发票签发 → 正式 PDF 归档 OneDrive + Teams 频道提醒（软失败，绝不影响签发本身）。

    优先出租户模板渲染的 PDF（带公司抬头/logo/收款银行，可直接转发对手方）；
    Chromium 未装时退回凭证 CSV，归档动作本身不能因为缺 PDF 引擎就丢掉。
    """
    try:
        from app.services import doc_engine, office_hub

        content, filename, ctype, meta = _invoice_archive_bytes(db, tenant_id, row)
        doc = office_hub.push_entity_document(
            db,
            tenant_id,
            entity_type="invoice",
            entity_id=row.id,
            filename=filename,
            content=content,
            content_type=ctype,
            meta=meta,
        )
        lines = [f"Invoice {row.invoice_no} issued — {row.currency} {row.amount}"]
        if doc:
            lines.append(f"Archived to OneDrive: {doc.get('web_url') or doc.get('name')}")
        office_hub.notify_workflow_event(
            db,
            tenant_id,
            title="Invoice issued",
            lines=lines,
            href="/finance/invoices",
        )
    except Exception:  # noqa: BLE001
        log.exception("office escalate failed for invoice %s", row.id)


@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """单据详情（U2）：可深链的发票单条视图。"""
    r = scoped_get(db, Invoice, invoice_id, auth.tenant_id)
    if r is None:
        raise HTTPException(404, "Invoice not found")
    return {
        "id": str(r.id),
        "invoice_no": r.invoice_no,
        "invoice_type": r.invoice_type,
        "status": r.status,
        "amount": float(r.amount),
        "tax_amount": float(r.tax_amount or 0),
        "paid_amount": float(r.paid_amount or 0),
        "voyage_id": str(r.voyage_id) if r.voyage_id else None,
        "counterparty_id": str(r.counterparty_id) if r.counterparty_id else None,
        "currency": r.currency,
        "base_amount": float(r.base_amount) if r.base_amount is not None else None,
        "fx_rate": float(r.fx_rate) if r.fx_rate is not None else None,
        "issued_at": r.issued_at.isoformat() if r.issued_at else None,
        "due_date": r.due_date.isoformat() if r.due_date else None,
        "gl_posted": bool(r.gl_posted),
        "mirror_of_id": str(r.mirror_of_id) if r.mirror_of_id else None,
        "bill_by": r.bill_by,
        "commission_basis": r.commission_basis,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# —— Finance ——
class InvoiceIn(BaseModel):
    invoice_type: str = "freight"
    counterparty_id: UUID | None = None
    voyage_id: UUID | None = None
    amount: float
    tax_amount: float = 0
    currency: str = "USD"
    due_date: date | None = None
    fx_rate: float | None = None
    bill_by: str | None = None
    commission_basis: str | None = None


@router.post("/invoices")
def create_invoice(body: InvoiceIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    if not is_valid_invoice_type(body.invoice_type):
        raise HTTPException(status_code=422, detail=invalid_invoice_type_detail(body.invoice_type))
    if body.counterparty_id:
        party = db.get(Counterparty, body.counterparty_id)
        if not party or party.tenant_id != auth.tenant_id or party.deleted_at:
            raise HTTPException(404, "Counterparty not found")
        assert_not_sanctioned(db, auth.tenant_id, party.id)
    if body.voyage_id:
        voyage = db.get(Voyage, body.voyage_id)
        if not voyage or voyage.tenant_id != auth.tenant_id:
            raise HTTPException(404, "Voyage not found")
    amount = money(body.amount)
    tax_amount = money(body.tax_amount)
    if amount <= 0 or tax_amount < 0:
        # P0-23：零金额发票没有任何业务含义（不产生收入、不入账龄、不占额度），
        # 却会在列表/账龄里占一行，看起来像漏了数据。退款场景走红冲接口。
        raise HTTPException(
            422,
            detail={
                "code": "INVALID_AMOUNT",
                "message": "amount must be > 0 and tax_amount must be >= 0",
            },
        )
    base_ccy = _base_currency(db, auth.tenant_id)
    fx_rate = None
    base_amount = None
    if body.fx_rate is not None:
        if body.fx_rate <= 0:
            raise HTTPException(422, detail={"code": "INVALID_FX_RATE", "message": "fx_rate must be > 0"})
        fx_rate = Decimal(str(body.fx_rate))
    elif (body.currency or "USD").upper() == (base_ccy or "USD").upper():
        # 本位币 → 汇率恒为 1（没有汇率行也必须能开票）
        fx_rate = Decimal("1")
    else:
        fx_rate = _resolve_fx_rate(
            db,
            auth.tenant_id,
            body.currency,
            base_ccy,
            invoice_type=body.invoice_type,
            context_date=date.today(),
        )
    if fx_rate is None:
        # 外币发票缺汇率 → **fail closed**。旧实现静默放行，base_amount 留空，
        # 于是这张外币发票在 P&L / 账龄里被当成本币金额直接求和（P0-B5）。
        raise HTTPException(
            status_code=422,
            detail={
                "code": "FX_RATE_NOT_FOUND",
                "message": (
                    f"No FX rate {body.currency}→{base_ccy} available for "
                    f"{date.today().isoformat()}; supply fx_rate explicitly"
                ),
                "currency": body.currency,
                "base_currency": base_ccy,
            },
        )
    base_amount = money(amount * fx_rate)
    row = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type=body.invoice_type,
        counterparty_id=body.counterparty_id,
        voyage_id=body.voyage_id,
        amount=amount,
        tax_amount=tax_amount,
        currency=body.currency,
        due_date=body.due_date,
        bill_by=body.bill_by,
        commission_basis=body.commission_basis,
        created_by=auth.user_id,
        updated_by=auth.user_id,
        fx_rate=fx_rate,
        base_amount=base_amount,
    )
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "amount": float(row.amount),
        "tax_amount": float(row.tax_amount),
        "currency": row.currency,
        "fx_rate": float(fx_rate),
        "base_amount": float(base_amount),
    }


@router.post("/invoices/{invoice_id}/transition")
def invoice_transition(invoice_id: UUID, target: str, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    from app.models_saas import WorkflowDefinition, WorkflowInstance
    from app.services.saas_engine import assert_feature, start_workflow

    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")

    if target in {"pending_approval", "issued"}:
        assert_feature(db, auth.tenant_id, auth.roles, "invoice.issue")

    has_wf = db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.tenant_id == auth.tenant_id,
            WorkflowDefinition.entity_type == "invoice",
            WorkflowDefinition.enabled.is_(True),
        )
    )
    if target == "issued" and has_wf and "tenant_admin" not in auth.roles:
        running = db.scalar(
            select(WorkflowInstance).where(
                WorkflowInstance.tenant_id == auth.tenant_id,
                WorkflowInstance.entity_type == "invoice",
                WorkflowInstance.entity_id == row.id,
                WorkflowInstance.status == "running",
            )
        )
        if running or row.status == "pending_approval":
            raise HTTPException(
                status_code=409,
                detail={"code": "WORKFLOW_REQUIRED", "message": "Invoice must be approved via workflow inbox"},
            )

    if target == "void":
        # 红冲不变量（INV-VOID-CREDIT）集中在服务层；见 services/finance_workflow.py
        assert_void_allowed(db, row)

    if target == "issued":
        # 审批额度工作流：超出审批人额度 → 409 APPROVAL_LIMIT
        # （approver 无额度行时默认放行 — 见 services/approval_limits.py）
        approval_amount = Decimal(str(row.amount)) + Decimal(str(row.tax_amount or 0))
        # P1-B9：额度比较要按**单据日期**的汇率折算（不是"绝对最新汇率"），
        # 否则同一张单据过两个月再签发，额度结论会漂。
        _ctx_date = row.issued_at or row.created_at
        if hasattr(_ctx_date, "date") and not isinstance(_ctx_date, date):
            _ctx_date = _ctx_date.date()
        assert_within_limit(
            db,
            auth.tenant_id,
            auth,
            "invoice",
            approval_amount,
            row.currency or "USD",
            context_date=_ctx_date if isinstance(_ctx_date, date) else None,
            invoice_type=invoice_type_code(row),
        )

    row.status = transition("invoice", row.status, target, INVOICE_TRANSITIONS)
    if target == "pending_approval" and has_wf:
        start_workflow(db, tenant_id=auth.tenant_id, entity_type="invoice", entity_id=row.id, started_by=auth.user_id)
    if target == "issued":
        row.issued_at = utcnow_naive()
        # 域事件：财务过账任务 + 有计提时的计提对账任务（services/automation.py）
        emit(
            db, auth.tenant_id, "invoice.issued", "invoice", row.id,
            payload={
                "invoice_no": row.invoice_no,
                "amount": float(row.amount or 0),
                "tax_amount": float(row.tax_amount or 0),
                "currency": row.currency or "USD",
                "invoice_type": invoice_type_code(row),
                "voyage_id": str(row.voyage_id) if row.voyage_id else None,
            },
            user_id=auth.user_id,
        )
    db.commit()
    if target == "issued":
        _office_escalate_invoice(db, auth.tenant_id, row)
        db.commit()
    return {"id": str(row.id), "status": row.status}


class InvoiceUpdate(BaseModel):
    amount: float | None = None
    tax_amount: float | None = None
    due_date: date | None = None
    invoice_type: str | None = None
    bill_by: str | None = None
    commission_basis: str | None = None
    # optimistic-lock token (D4/D8) — excluded from model_dump so it never
    # reaches the ORM via field loops / audits
    expected_updated_at: str | None = Field(default=None, exclude=True)


@router.patch("/invoices/{invoice_id}")
def update_invoice(
    invoice_id: UUID,
    body: InvoiceUpdate,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")
    assert_fresh(row, body.expected_updated_at)
    assert_mirror_writable(row)  # 不可独立编辑: mirror follows source
    if body.invoice_type is not None and not is_valid_invoice_type(body.invoice_type):
        raise HTTPException(status_code=422, detail=invalid_invoice_type_detail(body.invoice_type))
    locked = row.status in {"issued", "partially_paid", "paid"} or row.gl_posted
    requested = {
        f
        for f in ("amount", "tax_amount", "due_date", "invoice_type")
        if f in body.model_fields_set and getattr(body, f) is not None
    }
    if locked and requested:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVOICE_LOCKED",
                "message": f"Cannot modify {sorted(requested)} on invoice in status {row.status}"
                + (" (GL posted)" if row.gl_posted else ""),
                "fields": sorted(requested),
                "status": row.status,
            },
        )
    new_amount = money(row.amount)
    new_tax = money(row.tax_amount or 0)
    if body.amount is not None:
        new_amount = money(body.amount)
    if body.tax_amount is not None:
        new_tax = money(body.tax_amount)
    if new_amount <= 0 or new_tax < 0:
        # P0-23：把一张发票改成 0 金额和新建 0 金额一样没意义 —— 会占一行账龄、
        # 不产生收入，纯粹是脏数据。红冲场景必须走红冲接口。
        raise HTTPException(
            422,
            detail={
                "code": "INVALID_AMOUNT",
                "message": "amount must be > 0 and tax_amount must be >= 0",
            },
        )
    paid = money(row.paid_amount or 0)
    if new_amount + new_tax < paid:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AMOUNT_BELOW_PAID",
                "message": f"New total {new_amount + new_tax} is below already paid amount {paid}",
                "paid_amount": float(paid),
            },
        )
    if body.amount is not None:
        row.amount = new_amount
        # 本位币金额必须跟着改，否则 P&L / 账龄折算用的是旧值
        rate = row.fx_rate
        if rate:
            row.base_amount = money(new_amount * Decimal(str(rate)))
        else:
            row.base_amount = new_amount
    if body.tax_amount is not None:
        row.tax_amount = new_tax
    if body.due_date is not None:
        row.due_date = body.due_date
    if body.invoice_type is not None:
        row.invoice_type = body.invoice_type
    if body.bill_by is not None:
        row.bill_by = body.bill_by
    if body.commission_basis is not None:
        row.commission_basis = body.commission_basis
    # 修改人（归属条「修改」栏）——不写的话详情页永远显示旧的操作人。
    row.updated_by = auth.user_id
    # P1-B6：源单改了金额/本币金额，草稿镜像必须跟着走 —— 否则镜像的 P&L /
    # 账龄还按旧金额折算，两边对不上。镜像只同步仍是草稿的那些。
    # P1-17：跨租户的那条腿要带 user_id（公司间镜像开关按用户/租户作用域查）。
    sync_mirrors(db, row, user_id=auth.user_id)
    audit(
        db,
        action="invoice.update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="invoice",
        entity_id=str(row.id),
        detail={"fields": sorted(set(body.model_fields_set) - {"expected_updated_at"})},
    )
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "amount": float(row.amount),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class CreditNoteIn(BaseModel):
    amount: float
    reason: str | None = None


@router.post("/invoices/{invoice_id}/credit-note")
def create_credit_note(
    invoice_id: UUID,
    body: CreditNoteIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """红冲: issue a credit note against an invoice (capped at the un-credited balance).

    **P0-B2**：红冲除了写 ``CreditNote`` 凭证行，还必须写一张**负数 Invoice 行**
    （``amount = -红冲额``，``credit_note_of_id`` 指回原发票）。原因：

    - 账龄（``/finance/aging``）只认 Invoice 行 —— 旧实现红冲完全不进账龄，
      客户欠款一直挂在账上；
    - 航次 P&L（``services/pnl.py``）也只认 Invoice 行 —— 红冲不减收入，
      已开票的运费/租金照算毛利。

    负数行天然与原发票相抵，**不需要**在每条下游链路上再减一次红冲
    （减两次才是错的）。
    """
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    # P0-B2：红冲要写**反向分录**，分录落在红冲单自己的会计期间（= 当前月）——
    # 期间关账了就写不进去。与其写到一半失败，不如一开始就说清楚。
    assert_period_open(db, auth.tenant_id, datetime.now(timezone.utc).strftime("%Y-%m"))
    amt = money(body.amount)
    if amt <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "Credit note amount must be > 0"})
    total = invoice_gross(inv)
    credited = _credited_amount(db, inv.id)
    balance = total - credited
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
        tenant_id=auth.tenant_id,
        invoice_id=inv.id,
        credit_note_no=next_doc_number(db, auth.tenant_id, CreditNote, CreditNote.credit_note_no, "CN"),
        amount=amt,
        reason=body.reason,
        status="issued",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    # 负数发票行 —— 账龄 / P&L 靠它相抵
    cn_inv = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "CN"),
        invoice_type="credit_note",
        status="issued",
        counterparty_id=inv.counterparty_id,
        voyage_id=inv.voyage_id,
        amount=-amt,
        tax_amount=Decimal("0"),
        currency=inv.currency,
        fx_rate=inv.fx_rate,
        base_amount=(-invoice_to_base(inv, amt) if (inv.fx_rate or inv.base_amount is not None) else None),
        credit_note_of_id=inv.id,
        issued_at=utcnow_naive(),
        created_by=auth.user_id,
        updated_by=auth.user_id,
        meta={
            "credit_note_id": str(row.id),
            "credit_note_no": row.credit_note_no,
            "credit_note_of_id": str(inv.id),
            "credit_note_of_no": inv.invoice_no,
            "reason": body.reason,
        },
    )
    db.add(cn_inv)
    db.flush()
    # P0-B2：红冲的**反向分录** —— 总账必须与单据一致（同一套科目、金额相反）。
    # 原发票还没过账 → 这里不写分录，等原发票过账时由 gl_post 补上
    # （post_reversals_for_credit_notes），保证"红冲先于原单过账"也不丢分录。
    # 幂等：分录挂在红冲单自己身上，重复调用只会拿到同一张。
    post_credit_note_reversal(db, auth.tenant_id, inv, cn_inv, user_id=auth.user_id)
    db.commit()
    # 域事件 + 退款跟进：原单已经收过款的话，红冲之后钱多了 —— 必须有人安排退款，
    # 否则这笔差额就悬在那儿（客户多付了，没人管）。
    emit(
        db, auth.tenant_id, "invoice.credit_note_issued", "invoice", cn_inv.id,
        payload={
            "invoice_no": inv.invoice_no,
            "credit_note_no": row.credit_note_no,
            "credit_note_of_id": str(inv.id),
            "amount": float(amt),
            "currency": inv.currency or "USD",
        },
        user_id=auth.user_id,
    )
    if inv.status in ("paid", "partially_paid"):
        locale = user_locale(db, auth.user_id)
        ensure_task(
            db,
            auth.tenant_id,
            title=text("invoice.refund.task.title", locale, invoice_no=inv.invoice_no),
            description=text(
                "invoice.refund.task.desc", locale,
                amount=f"{float(amt):,.2f}", currency=inv.currency or "USD",
            ),
            entity_type="invoice",
            entity_id=inv.id,
            priority="high",
            due_days=3,
            assign_role="finance",
            created_by=auth.user_id,
            dedupe_key=f"invoice.refund:{row.id}",
        )
    # 域事件与跟进任务必须**自己提交** —— 上一次 commit 已经过去了，
    # 不提交的话事件和任务会随会话回滚悄悄消失（"退款没人管"）。
    db.commit()
    return {
        "id": str(row.id),
        "credit_note_no": row.credit_note_no,
        "amount": float(row.amount),
        "status": row.status,
        # 红冲单本身（P0-B2 落的那张负数发票行）
        "invoice_id": str(cn_inv.id),
        "invoice_no": cn_inv.invoice_no,
        # 被红冲的原发票
        "credit_note_of_id": str(inv.id),
        "credit_note_of_no": inv.invoice_no,
    }


@router.get("/invoices/{invoice_id}/credit-notes")
def list_credit_notes(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Invoice not found")
    rows = db.scalars(
        select(CreditNote).where(CreditNote.invoice_id == inv.id).order_by(CreditNote.credit_note_no)
    ).all()
    return [
        {
            "id": str(r.id),
            "credit_note_no": r.credit_note_no,
            "amount": float(r.amount or 0),
            "reason": r.reason,
            "status": r.status,
            "issued_at": r.issued_at.isoformat() if r.issued_at else None,
        }
        for r in rows
    ]


class HireScheduleIn(BaseModel):
    charter_id: UUID
    period_start: date
    period_end: date


@router.post("/invoices/hire-schedule")
def hire_schedule(body: HireScheduleIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    """Generate a draft hire invoice for a time-charter period, net of off-hire and address commission."""
    ch = db.get(Charter, body.charter_id)
    if not ch or ch.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Charter not found")
    hire_per_day = getattr(ch, "hire_per_day", None)
    if not hire_per_day:
        raise HTTPException(422, detail={"code": "NO_HIRE_RATE", "message": "Charter has no hire_per_day rate"})
    if body.period_end <= body.period_start:
        raise HTTPException(422, detail={"code": "INVALID_PERIOD", "message": "period_end must be after period_start"})
    # ── 停租：复用 hire_engine 的同一套口径 ───────────────────────────────
    # 旧实现自己算了一遍：重叠事件**双计**（P1-B22）、12 小时停租被截断成 0 天
    # （P1-B23）、事件里的显式 ``hire_deduction`` 一分钱都不扣。
    # 现在统一走 ``_off_hire_in_period``：合并重叠区间 → 按小时折算 → 按本期裁剪。
    offhire_events = db.scalars(
        select(OffHireEvent).where(
            OffHireEvent.tenant_id == auth.tenant_id,
            OffHireEvent.charter_id == ch.id,
        )
    ).all()
    offhire_days, explicit_deduction, _oh_rows = _off_hire_in_period(
        offhire_events, body.period_start, body.period_end
    )
    gross_days = Decimal(str((body.period_end - body.period_start).days))
    billable_days = gross_days - offhire_days
    if billable_days < 0:
        billable_days = Decimal("0")

    # ── 公布口径的天数（4dp）—— 金额与 meta 用**同一个**天数 ──────────────
    # 旧实现 meta 记 round(days,4) 而金额用未舍入的 float：14.5208 天 × 15000
    # 会差 0.50 元，账单与 meta 永远对不上（P2-B5）。
    gross_days_pub = gross_days.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    offhire_days_pub = offhire_days.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    billable_days_pub = (gross_days_pub - offhire_days_pub).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )

    # P0-23：整段停租 → 应付天数为 0 → 租金为 0。零金额发票没有任何业务含义
    # （不产生收入、不入账龄、不占额度、GL 里是一笔 0 分录），却会在应收列表里
    # 占一行，看起来像漏了数据。退款场景走红冲接口，租金场景没有退款语义。
    if billable_days_pub <= 0:
        raise HTTPException(
            400,
            detail={
                "code": "NO_BILLABLE_DAYS",
                "message": (
                    "The period has no billable hire days (fully off-hire); "
                    "a zero-amount hire invoice cannot be issued"
                ),
                "gross_days": float(gross_days_pub),
                "offhire_days": float(offhire_days_pub),
            },
        )

    rate = Decimal(str(hire_per_day))
    gross_amount = money(rate * billable_days_pub)
    comm_pct = Decimal(str(getattr(ch, "address_comm_pct", None) or 0))
    comm_amount = money(gross_amount * comm_pct / Decimal("100"))
    # 显式停租扣款（事件上直接写的金额）也要扣 —— 以前完全被忽略
    net_amount = money(gross_amount - comm_amount - explicit_deduction)

    # P0-23：扣完佣金/停租后金额 <= 0（同币种同额不是同一笔钱，租金必须是正的）
    if net_amount <= 0:
        raise HTTPException(
            400,
            detail={
                "code": "INVALID_AMOUNT",
                "message": "hire amount must be > 0 (deductions exceed gross hire)",
                "gross_amount": float(gross_amount),
                "amount": float(net_amount),
            },
        )

    # ── 币种：取自租约（P1-B6）───────────────────────────────────────────
    # 旧实现写死租户口径（本位币），EUR 租约的租金被记成本币 —— 收入金额没
    # 错但币种标签错，跨币种汇总时会把两种币种直接相加。
    ft = ch.freight_terms or {}
    hire_ccy = str(
        ft.get("hire_currency") or ft.get("currency") or _base_currency(db, auth.tenant_id) or "USD"
    ).upper()
    base_ccy = (_base_currency(db, auth.tenant_id) or "USD").upper()
    if hire_ccy == base_ccy:
        fx_rate = Decimal("1")
    else:
        fx_rate = _resolve_fx_rate(
            db,
            auth.tenant_id,
            hire_ccy,
            base_ccy,
            invoice_type="hire",
            context_date=body.period_end,
        )
        if fx_rate is None:
            # 外币租金缺汇率 → fail closed（与普通开票同一口径，P0-B5）
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "FX_RATE_NOT_FOUND",
                    "message": (
                        f"No FX rate {hire_ccy}→{base_ccy} available for "
                        f"{body.period_end.isoformat()}; the hire invoice cannot be "
                        f"posted without a rate"
                    ),
                    "currency": hire_ccy,
                    "base_currency": base_ccy,
                },
            )
    base_amount = money(net_amount * fx_rate)

    meta = {
        "hire": {
            "charter_id": str(ch.id),
            "period_start": body.period_start.isoformat(),
            "period_end": body.period_end.isoformat(),
            "gross_days": float(gross_days_pub),
            "offhire_days": float(offhire_days_pub),
            "billable_days": float(billable_days_pub),
            "hire_per_day": float(rate),
            "gross_amount": float(gross_amount),
            "explicit_deduction": float(explicit_deduction),
            "address_comm_pct": float(comm_pct),
            "address_comm_amount": float(comm_amount),
            "currency": hire_ccy,
            "fx_rate": float(fx_rate),
            "base_amount": float(base_amount),
        }
    }
    if ch.counterparty_id:
        assert_not_sanctioned(db, auth.tenant_id, ch.counterparty_id)
    row = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type="hire",
        counterparty_id=ch.counterparty_id,
        amount=net_amount,
        tax_amount=Decimal("0"),
        currency=hire_ccy,
        # 金额已扣地址佣金 → 声明口径，P&L 靠它避免重复计佣（P1-B1/B2）
        commission_basis="net",
        fx_rate=fx_rate,
        base_amount=base_amount,
        meta=meta,
        created_by=auth.user_id,
        updated_by=auth.user_id,
    )
    db.add(row)
    db.commit()
    return {
        "id": str(row.id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "invoice_type": row.invoice_type,
        "amount": float(row.amount),
        "meta": row.meta,
    }


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = db.get(Invoice, invoice_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Invoice not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="invoice",
        row=row,
        title=row.invoice_no,
    )
    db.commit()
    return {"ok": True, "recycled": True}


# fix payment status assignment
@router.post("/invoices/{invoice_id}/payments")
def add_payment(
    invoice_id: UUID,
    amount: float,
    reference: str | None = None,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    from app.services.saas_engine import assert_feature

    assert_feature(db, auth.tenant_id, auth.roles, "invoice.collect")
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    if inv.counterparty_id:
        assert_not_sanctioned(db, auth.tenant_id, inv.counterparty_id)
    if inv.status not in {"issued", "partially_paid"}:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot pay invoice in status {inv.status}"})
    if invoice_type_code(inv) == "XREV" or (inv.amount or 0) < 0:
        # 红冲单据是负数发票行，本身没有可收的钱
        raise HTTPException(
            status_code=409,
            detail={"code": "CREDIT_NOTE_NOT_PAYABLE", "message": "A credit note (negative invoice) cannot receive payment"},
        )
    record_payment(db, inv, amount, reference=reference, created_by=auth.user_id)
    # 域事件：收款登记 → 绑 invoice.payment.record 的任务即时勾掉
    emit(
        db, auth.tenant_id, "invoice.payment_recorded", "invoice", inv.id,
        payload={
            "invoice_no": inv.invoice_no,
            "amount": float(amount or 0),
            "currency": inv.currency or "USD",
            "status": inv.status,
        },
        user_id=auth.user_id,
    )
    db.commit()
    return {"invoice_id": str(inv.id), "status": inv.status, "paid_amount": float(inv.paid_amount)}

@router.get("/invoices/{invoice_id}/payments")
def list_payments(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Invoice not found")
    rows = (
        db.query(Payment)
        .filter(Payment.invoice_id == inv.id, Payment.tenant_id == auth.tenant_id)
        .order_by(Payment.paid_at.asc())
        .all()
    )
    return [
        {
            "id": str(p.id),
            "amount": float(p.amount),
            "currency": p.currency,
            "reference": p.reference,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "is_void_reversal": bool(p.reference and p.reference.startswith("VOID:")),
        }
        for p in rows
    ]


@router.post("/invoices/{invoice_id}/gl-post")
def gl_post(invoice_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    """发票过账到总账 —— 生成**真正的借贷分录**（P0-B3）。

    旧实现只把 ``gl_posted`` 置 True，系统里根本没有对应分录，总账和业务单据
    对不上。现在按本位币生成 DR/CR 分录并落 ``PeriodJournal``：

    - 收入侧：借 应收账款 / 贷 营业收入 + 应交税费（销项）
    - 成本侧：借 费用 + 进项税 / 贷 应付账款
    - 红冲（负数发票）：借贷方向自动对调

    **幂等**：同一张发票重复过账不会产生第二张分录（靠
    ``(tenant_id, journal_type, source_type, source_id)`` 唯一约束）。
    失败时回滚，**不会**留下 ``gl_posted=True`` 的半成品。
    """
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Invoice not found")
    if inv.status not in {"issued", "partially_paid", "paid"}:
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": "Invoice not issuable for GL"})
    from app.services.gl_engine import post_invoice_journal

    try:
        journal, created = post_invoice_journal(db, auth.tenant_id, inv, user_id=auth.user_id)
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 — 过账失败不能留下半成品
        db.rollback()
        log.exception("GL post failed for invoice %s", inv.id)
        raise HTTPException(
            status_code=500,
            detail={"code": "GL_POST_FAILED", "message": str(exc)},
        )
    inv.gl_posted = True
    inv.meta = {
        **(inv.meta or {}),
        "gl_posted_at": datetime.now(timezone.utc).isoformat(),
        "gl_journal_id": str(journal.id),
    }
    # P0-B2：红冲先于原发票过账时，在这里**补**红冲的反向分录（幂等）。
    post_reversals_for_credit_notes(db, auth.tenant_id, inv, user_id=auth.user_id)
    # 域事件：过账完成 → 绑 invoice.post_gl 的任务即时勾掉（原来只能等 5 分钟兜底扫描）
    emit(
        db, auth.tenant_id, "invoice.gl_posted", "invoice", inv.id,
        payload={
            "invoice_no": inv.invoice_no,
            "journal_id": str(journal.id),
            "currency": journal.currency,
        },
        user_id=auth.user_id,
    )
    db.commit()
    return {
        "id": str(inv.id),
        "gl_posted": True,
        "journal_id": str(journal.id),
        "journal_created": created,
        "total_debit": float(journal.total_debit or 0),
        "total_credit": float(journal.total_credit or 0),
        "currency": journal.currency,
    }


@router.post("/payments/{payment_id}/void")
def void_payment(payment_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    """付款冲正: reverse a payment and write the invoice paid_amount / status back.

    折中方案: Payment 模型定义在 models_domain.py(本任务不可改),无法新增
    voided_at 列,因此保留原 payment 记录,另写一条金额为负的反向 payment,
    以 reference = "VOID:<原 payment id>" 作为冲正关联与幂等标记。
    """
    pay = db.get(Payment, payment_id)
    if not pay or pay.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Payment not found")
    if Decimal(str(pay.amount)) <= 0 or (pay.reference or "").startswith("VOID:"):
        raise HTTPException(409, detail={"code": "INVALID_PAYMENT", "message": "Cannot void a reversal entry"})
    inv = db.get(Invoice, pay.invoice_id)
    if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
        raise HTTPException(404, "Invoice not found")
    if inv.gl_posted:
        raise HTTPException(
            status_code=409,
            detail={"code": "GL_POSTED", "message": "Invoice is GL posted; voiding its payments is forbidden"},
        )
    if inv.status not in {"issued", "partially_paid", "paid"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "INVALID_STATE", "message": f"Cannot void a payment on invoice in status {inv.status}"},
        )
    void_ref = f"VOID:{pay.id}"
    existing = db.scalar(
        select(Payment).where(
            Payment.tenant_id == auth.tenant_id,
            Payment.invoice_id == inv.id,
            Payment.reference == void_ref,
        )
    )
    if existing:
        raise HTTPException(409, detail={"code": "ALREADY_VOIDED", "message": "Payment is already voided"})
    reverse = Payment(
        tenant_id=auth.tenant_id,
        invoice_id=inv.id,
        # 必须带上原付款的 batch_id —— 否则这条冲销行游离在批次之外，
        # MT103 / pain.001 按 batch 取净额时看不到它，已冲销的付款仍会出现在
        # 付款指令里（审计 P2-B9）。
        batch_id=pay.batch_id,
        amount=-Decimal(str(pay.amount)),
        currency=pay.currency,
        reference=void_ref,
        created_by=auth.user_id,
    )
    db.add(reverse)
    db.flush()
    total_paid = money(
        sum(
            (
                Decimal(str(p.amount))
                for p in db.scalars(
                    select(Payment).where(
                        Payment.tenant_id == auth.tenant_id,
                        Payment.invoice_id == inv.id,
                    )
                ).all()
            ),
            Decimal("0"),
        )
    )
    inv.paid_amount = total_paid
    total = invoice_gross(inv)
    target = "paid" if total_paid >= total else "partially_paid" if total_paid > 0 else "issued"
    if target != inv.status:
        # Reversal goes backwards through the machine; hop paid → partially_paid first
        # when the payment void reopens a fully paid invoice to zero received.
        if inv.status == "paid" and target == "issued":
            inv.status = transition("invoice", inv.status, "partially_paid", INVOICE_TRANSITIONS)
        inv.status = transition("invoice", inv.status, target, INVOICE_TRANSITIONS)
    # 域事件：付款被冲正 → 绑 invoice.payment.record 的任务应回退（"钱已经收了"不再成立）
    emit(
        db, auth.tenant_id, "invoice.payment_voided", "invoice", inv.id,
        payload={
            "invoice_no": inv.invoice_no,
            "payment_id": str(pay.id),
            "reversal_id": str(reverse.id),
            "status": inv.status,
        },
        user_id=auth.user_id,
    )
    db.commit()
    return {
        "payment_id": str(pay.id),
        "reversal_id": str(reverse.id),
        "invoice_id": str(inv.id),
        "status": inv.status,
        "paid_amount": float(inv.paid_amount),
    }


@router.get("/invoices")
def list_invoices(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    voyage_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    from app.services.data_scope import apply_data_scope, effective_scope

    q = select(Invoice).where(Invoice.tenant_id == auth.tenant_id, Invoice.status != "deleted")
    if voyage_id is not None:
        q = q.where(Invoice.voyage_id == voyage_id)
    q = apply_data_scope(q, Invoice, auth.user_id, effective_scope(db, auth.tenant_id, auth.roles, "finance"))
    rows, total = paginate(db, q.order_by(Invoice.invoice_no), limit, offset)
    return envelope(
        [
            {
                "id": str(r.id),
                "invoice_no": r.invoice_no,
                "invoice_type": r.invoice_type,
                "status": r.status,
                "amount": float(r.amount),
                "tax_amount": float(r.tax_amount or 0),
                "gross_amount": float(invoice_gross(r)),
                "open_amount": float(invoice_open(r)),
                "base_amount": float(r.base_amount) if r.base_amount is not None else None,
                "paid_amount": float(r.paid_amount or 0),
                "voyage_id": str(r.voyage_id) if r.voyage_id else None,
                "counterparty_id": str(r.counterparty_id) if r.counterparty_id else None,
                "currency": r.currency,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "gl_posted": bool(r.gl_posted),
                "mirror_of_id": str(r.mirror_of_id) if r.mirror_of_id else None,
                # P0-B2：红冲行回链原发票（列表里能看出「这是 INV-x 的红冲」）
                "credit_note_of_id": str(r.credit_note_of_id) if r.credit_note_of_id else None,
                "bill_by": r.bill_by,
                "commission_basis": r.commission_basis,
                "created_by": str(r.created_by) if r.created_by else None,
                "updated_by": str(r.updated_by) if r.updated_by else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
        total,
        limit,
        offset,
    )


@router.get("/finance/aging")
def aging(auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    """应收账款账龄。

    口径（P0-B4）：**未收 = 金额 + 税 − 已收**，与单笔收款、付款批次一致。
    红冲是一张负数发票行，所以这里天然相抵，不需要再减一次红冲。
    多币种时 ``currency`` 一并返回（跨币种求和前必须先折本币）。
    """
    rows = db.scalars(
        apply_module_scope(
            db,
            select(Invoice).where(
                Invoice.tenant_id == auth.tenant_id,
                Invoice.status.in_(["issued", "partially_paid"]),
            ),
            Invoice,
            auth,
            "finance",
        )
    ).all()
    return [
        {
            "invoice_id": str(r.id),
            "invoice_no": r.invoice_no,
            "invoice_type": r.invoice_type,
            "counterparty_id": str(r.counterparty_id) if r.counterparty_id else None,
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "open_amount": float(invoice_open(r)),
            "gross_amount": float(invoice_gross(r)),
            "paid_amount": float(r.paid_amount or 0),
            "currency": r.currency,
            "due_date": r.due_date.isoformat() if r.due_date else None,
        }
        for r in rows
    ]


class AccrualIn(BaseModel):
    voyage_id: UUID | None = None
    period_ym: str
    line_type: str = "freight"
    amount: float
    currency: str = "USD"
    notes: str | None = None


class AccrualPatch(BaseModel):
    """草稿计提可改；posted/reversed 只可冲销/重建 → 409 INVALID_STATE。"""

    voyage_id: UUID | None = None
    period_ym: str | None = None
    line_type: str | None = None
    amount: float | None = None
    currency: str | None = None
    notes: str | None = None


@router.get("/finance/accruals")
def list_accruals(auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    rows = db.scalars(scoped_query(db, VoyageAccrual, auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "voyage_id": str(r.voyage_id) if r.voyage_id else None,
            "period_ym": r.period_ym,
            "line_type": r.line_type,
            "amount": float(r.amount or 0),
            "currency": r.currency,
            "status": r.status,
            "notes": r.notes,
        }
        for r in rows
    ]


@router.post("/finance/accruals")
def create_accrual(body: AccrualIn, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    assert_period_open(db, auth.tenant_id, body.period_ym)  # 关账期间禁止新增计提
    row = VoyageAccrual(
        tenant_id=auth.tenant_id,
        voyage_id=body.voyage_id,
        period_ym=body.period_ym,
        line_type=body.line_type,
        amount=body.amount,
        currency=body.currency,
        notes=body.notes,
        status="draft",
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/finance/accruals/{accrual_id}/post")
def post_accrual(accrual_id: UUID, auth: AuthContext = Depends(require_module("finance")), db: Session = Depends(get_db)):
    row = db.get(VoyageAccrual, accrual_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Accrual not found")
    if row.status != "draft":
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Cannot post from {row.status}"})
    assert_period_open(db, auth.tenant_id, row.period_ym)  # 关账期间禁止过账计提
    row.status = "posted"
    db.commit()
    return {"id": str(row.id), "status": row.status}


@router.patch("/finance/accruals/{accrual_id}")
def update_accrual(
    accrual_id: UUID,
    body: AccrualPatch,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """改草稿计提。posted/reversed 锁定 → 409（只可冲销/重建）；关账期间禁止改。"""
    row = db.get(VoyageAccrual, accrual_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Accrual not found")
    if row.status != "draft":
        raise HTTPException(
            409,
            detail={"code": "INVALID_STATE", "message": f"Cannot edit accrual in status {row.status}"},
        )
    assert_period_open(db, auth.tenant_id, row.period_ym)
    fields = body.model_fields_set
    if "voyage_id" in fields and body.voyage_id is not None:
        if scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
            raise HTTPException(404, "Voyage not found")
    if "period_ym" in fields and body.period_ym is not None:
        assert_period_open(db, auth.tenant_id, body.period_ym)
    if "amount" in fields and body.amount is not None and Decimal(str(body.amount)) < 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "amount must be >= 0"})
    for field in ("voyage_id", "period_ym", "line_type", "amount", "currency", "notes"):
        if field in fields:
            val = getattr(body, field)
            # period_ym/line_type/amount/currency 非空列：显式 null 不落地
            if val is None and field in ("period_ym", "line_type", "amount", "currency"):
                continue
            setattr(row, field, val)
    audit(
        db,
        action="accrual.update",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="accrual",
        entity_id=str(row.id),
        detail={"fields": sorted(fields)},
    )
    db.commit()
    return {
        "id": str(row.id),
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "period_ym": row.period_ym,
        "line_type": row.line_type,
        "amount": float(row.amount or 0),
        "currency": row.currency,
        "status": row.status,
        "notes": row.notes,
    }




def _normalize_currency(v: str | None) -> str | None:
    """币种归一为 3 位大写 ISO 代码。

    没给就是「无法核对」（不是默认 USD）—— ``services.reconciliation`` 靠这一点
    把 ``currency_verified`` 置成 false，提醒人工确认。
    """
    if v is None:
        return None
    v = v.strip().upper()
    if not v:
        return None
    if len(v) != 3 or not v.isalpha():
        raise ValueError("currency must be a 3-letter ISO 4217 code (e.g. USD)")
    return v


class ReconcileLine(BaseModel):
    amount: float
    reference: str | None = None
    date: str | None = None
    # P1-B14：银行流水的币种。同额不同币种不是同一笔钱 —— 缺了这个字段，
    # ``services.reconciliation`` 拿不到流水币种，币种永远无法核对
    # （currency_verified 恒为 false），跨币种同额会被误配。
    currency: str | None = None

    @field_validator("currency")
    @classmethod
    def _norm_currency(cls, v: str | None) -> str | None:
        return _normalize_currency(v)


class ReconcilePreviewIn(BaseModel):
    lines: list[ReconcileLine]


class ReconcileMatch(BaseModel):
    invoice_id: UUID
    amount: float
    reference: str | None = None
    paid_at: str | None = None
    # P1-B14：流水币种（回显自 preview 的建议）。与发票币种不一致 → 拒绝核销，
    # 防止把 EUR 的一笔款核到 USD 发票上。
    currency: str | None = None

    @field_validator("currency")
    @classmethod
    def _norm_currency(cls, v: str | None) -> str | None:
        return _normalize_currency(v)


class ReconcileApplyIn(BaseModel):
    matches: list[ReconcileMatch]


@router.post("/finance/reconciliation/preview")
def reconciliation_preview(
    body: ReconcilePreviewIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """D21 银行核销：流水 → 未结发票的配对建议（不落库，人工确认）。"""
    from app.models_wave1 import Counterparty
    from app.services.reconciliation import suggest_matches

    invoices = list(
        db.scalars(
            apply_module_scope(
                db,
                select(Invoice).where(
                    Invoice.tenant_id == auth.tenant_id,
                    Invoice.status.in_(["issued", "partially_paid"]),
                ),
                Invoice,
                auth,
                "finance",
            )
        ).all()
    )
    names = {
        str(c.id): c.name
        for c in db.scalars(select(Counterparty).where(Counterparty.tenant_id == auth.tenant_id)).all()
    }
    result = suggest_matches([l.model_dump() for l in body.lines], invoices, names)
    # P1-B14：建议里的 ``currency`` 是**发票**币种；把流水行自带的币种也回给前端，
    # 好让人工确认时看清「同额不同币种」到底差在哪（没带币种 → currency_verified=false）。
    for s in result.get("suggestions", []):
        idx = s.get("line_index")
        if isinstance(idx, int) and 0 <= idx < len(body.lines):
            s["line_currency"] = body.lines[idx].currency
    return result


@router.post("/finance/reconciliation/apply")
def reconciliation_apply(
    body: ReconcileApplyIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """D21 核销入账：确认的配对逐笔记收款（同一事务，任一失败整体回滚）。"""
    from app.services.saas_engine import assert_feature

    assert_feature(db, auth.tenant_id, auth.roles, "invoice.collect")
    applied = []
    for m in body.matches:
        inv = db.get(Invoice, m.invoice_id)
        if not inv or inv.tenant_id != auth.tenant_id or not _alive(inv.status):
            raise HTTPException(404, detail={"code": "INVOICE_NOT_FOUND", "message": f"invoice {m.invoice_id}"})
        if inv.counterparty_id:
            assert_not_sanctioned(db, auth.tenant_id, inv.counterparty_id)
        # P1-B14：流水币种与发票币种必须一致（同额不同币种不是同一笔钱）
        if m.currency:
            inv_ccy = str(inv.currency or "USD").upper()
            if m.currency != inv_ccy:
                raise HTTPException(
                    400,
                    detail={
                        "code": "CURRENCY_MISMATCH",
                        "message": (
                            f"Bank line currency {m.currency} does not match invoice "
                            f"currency {inv_ccy}"
                        ),
                        "invoice_currency": inv_ccy,
                        "line_currency": m.currency,
                    },
                )
        record_payment(db, inv, m.amount, reference=m.reference, created_by=auth.user_id)
        applied.append({"invoice_id": str(inv.id), "status": inv.status})
    db.commit()
    return {"applied": applied}


@router.get("/invoices/{invoice_id}/commission-plan")
def invoice_commission_plan(
    invoice_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """D4 佣金计划：地址佣金扣减 + 经纪佣金金额（按租约佣金字段）。"""
    from app.services.commission import commission_plan

    inv = scoped_get(db, Invoice, invoice_id, auth.tenant_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found")
    return commission_plan(db, inv)


@router.post("/invoices/{invoice_id}/commission-invoices")
def create_commission_invoices(
    invoice_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """D4 佣金链：按经纪佣金生成草稿佣金发票（无佣金返回 422）。"""
    from app.services.commission import create_brokerage_invoice

    inv = scoped_get(db, Invoice, invoice_id, auth.tenant_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found")
    created = create_brokerage_invoice(db, inv, user_id=auth.user_id)
    if created is None:
        raise HTTPException(422, detail={"code": "NO_COMMISSION", "message": "No brokerage commission on linked charter"})
    db.commit()
    return {"id": str(created.id), "invoice_no": created.invoice_no, "amount": float(created.amount)}
