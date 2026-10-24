"""GL engine — maps voyage/invoice expenses to chart-of-accounts entries.

Resolves BusinessRule matches by entity_type + expense_category + conditions,
generates balanced journal entries (debits == credits), and supports
posting to PeriodJournal for a given accounting period.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models_gl import BusinessRule, ChartOfAccount, PeriodJournal
from app.services.money import money
from app.services.timeutil import utcnow_naive
from app.services.observability import traced


def resolve_accounts(
    db: Session,
    tenant_id: UUID,
    entity_type: str,
    expense_category: str,
    conditions: dict | None = None,
) -> tuple[str, str] | None:
    """Find the best-matching business rule and return (debit_account, credit_account).

    Rules are matched by entity_type + expense_category, then filtered by
    conditions (JSON subset match). Highest priority rule wins.
    """
    stmt = (
        select(BusinessRule)
        .where(
            BusinessRule.tenant_id == tenant_id,
            BusinessRule.entity_type == entity_type,
            BusinessRule.expense_category == expense_category,
            BusinessRule.is_active == True,
        )
        .order_by(BusinessRule.priority.desc())
    )
    rules = db.scalars(stmt).all()

    for rule in rules:
        if _conditions_match(rule.conditions or {}, conditions or {}):
            return (rule.debit_account, rule.credit_account)

    return None


def _conditions_match(rule_conds: dict, actual: dict) -> bool:
    """Check that every key/value in rule_conds exists in actual."""
    for key, val in rule_conds.items():
        if actual.get(key) != val:
            return False
    return True


def build_journal_entries(
    db: Session,
    tenant_id: UUID,
    lines: list[dict],
) -> list[dict]:
    """Convert expense lines into balanced GL entries.

    Each line: {entity_type, expense_category, amount, reference, description, conditions?}
    Returns: [{account_code, account_name, debit, credit, reference, description}]
    """
    entries: list[dict] = []

    for line in lines:
        result = resolve_accounts(
            db,
            tenant_id,
            line["entity_type"],
            line["expense_category"],
            line.get("conditions"),
        )
        if not result:
            raise ValueError(
                f"No GL rule for entity_type='{line['entity_type']}', "
                f"expense_category='{line['expense_category']}'"
            )

        debit_code, credit_code = result
        # P2-B12：金额必须**量化到分**再落库 —— 列是 Numeric(18,2)，
        # 裸 str(amount) 可能带 3 位小数，SQLite 存得进去、Postgres 会截断，
        # 于是同一笔账在两种库上对不上（借贷不平或差半分）。
        amount = money(line["amount"])

        debit_account = _get_account(db, tenant_id, debit_code)
        credit_account = _get_account(db, tenant_id, credit_code)

        entries.append(
            {
                "account_code": debit_code,
                "account_name": debit_account.account_name if debit_account else debit_code,
                "debit": str(amount),
                "credit": "0",
                "reference": line.get("reference", ""),
                "description": line.get("description", ""),
            }
        )
        entries.append(
            {
                "account_code": credit_code,
                "account_name": credit_account.account_name if credit_account else credit_code,
                "debit": "0",
                "credit": str(amount),
                "reference": line.get("reference", ""),
                "description": line.get("description", ""),
            }
        )

    return entries


def _get_account(db: Session, tenant_id: UUID, code: str) -> ChartOfAccount | None:
    stmt = select(ChartOfAccount).where(
        ChartOfAccount.tenant_id == tenant_id,
        ChartOfAccount.account_code == code,
    )
    return db.scalars(stmt).first()


@traced("gl_post")
def post_journal(
    db: Session,
    tenant_id: UUID,
    period: str,
    journal_type: str,
    entries: list[dict],
    description: str | None = None,
    user_id: UUID | None = None,
    *,
    currency: str = "USD",
    source_type: str | None = None,
    source_id: UUID | None = None,
) -> PeriodJournal:
    """Create a PeriodJournal row from pre-built entries and mark it posted.

    Period-close guard (C3-P2): a closed accounting period rejects the posting
    with 409 ``PERIOD_CLOSED`` (see ``services.period_close``).

    ``source_type`` + ``source_id`` 关联业务单据，配合唯一约束
    ``(tenant_id, journal_type, source_type, source_id)`` 实现**幂等过账**：
    同一张发票重复点「过账」不会产生第二张日记账。
    """
    from app.services.period_close import assert_period_open

    assert_period_open(db, tenant_id, period)

    total_debit = sum(Decimal(e["debit"]) for e in entries)
    total_credit = sum(Decimal(e["credit"]) for e in entries)

    if total_debit != total_credit:
        raise ValueError(
            f"Journal is unbalanced: debit={total_debit}, credit={total_credit}"
        )

    journal = PeriodJournal(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        period=period,
        journal_type=journal_type,
        description=description,
        entries=entries,
        total_debit=total_debit,
        total_credit=total_credit,
        status="posted",
        posted_at=utcnow_naive(),
        posted_by=user_id,
        currency=currency or "USD",
        source_type=source_type,
        source_id=source_id,
    )
    try:
        # SAVEPOINT：唯一约束 (tenant_id, journal_type, source_type, source_id)
        # 兜住了并发重复过账 —— 回滚只回滚这一张分录，不会把调用方同事务里的
        # 其他改动一起带走；已存在的那张返回去（幂等），而不是抛 500。
        with db.begin_nested():
            db.add(journal)
            db.flush()
    except IntegrityError:
        if source_type is not None and source_id is not None:
            existing = db.scalar(
                select(PeriodJournal).where(
                    PeriodJournal.tenant_id == tenant_id,
                    PeriodJournal.journal_type == journal_type,
                    PeriodJournal.source_type == source_type,
                    PeriodJournal.source_id == source_id,
                )
            )
            if existing is not None:
                return existing
        raise
    return journal


# —— 发票过账（P0-B3）—————————————————————————————————————

#: 缺省科目（租户没有科目表时的兜底）。可在租户科目表里覆盖。
DEFAULT_INVOICE_ACCOUNTS: dict[str, str] = {
    "receivable": "1200",  # 应收账款
    "payable": "2100",  # 应付账款
    "revenue": "4000",  # 营业收入
    "expense": "5000",  # 营业成本/费用
    "tax_payable": "2200",  # 应交税费（销项）
    "tax_receivable": "1300",  # 进项税
}


def _account_name(db: Session, tenant_id: UUID, code: str) -> str:
    """科目代码 → 科目名（没有科目表就用代码本身）。"""
    from app.models_gl import ChartOfAccount

    row = db.scalar(
        select(ChartOfAccount).where(
            ChartOfAccount.tenant_id == tenant_id,
            ChartOfAccount.account_code == code,
        )
    )
    return row.account_name if row else code


def _invoice_account_codes(
    db: Session, tenant_id: UUID, invoice_type: str
) -> dict[str, str]:
    """发票类型 → 科目代码组。租户配了 BusinessRule 就用它，否则用缺省科目。"""
    from app.models_gl import BusinessRule

    rule = db.scalar(
        select(BusinessRule)
        .where(
            BusinessRule.tenant_id == tenant_id,
            BusinessRule.entity_type == "invoice",
            BusinessRule.expense_category == invoice_type,
            BusinessRule.is_active.is_(True),
        )
        .order_by(BusinessRule.priority.desc())
    )
    codes = dict(DEFAULT_INVOICE_ACCOUNTS)
    if rule:
        # 业务规则给的是 (借方科目, 贷方科目)
        if _is_revenue_type(invoice_type):
            codes["receivable"], codes["revenue"] = rule.debit_account, rule.credit_account
        else:
            codes["expense"], codes["payable"] = rule.debit_account, rule.credit_account
    return codes


def _is_revenue_type(invoice_type: str) -> bool:
    """规范类型码 → 收入侧？与 ``money.is_revenue_side`` **同一口径**（P1-B15）。"""
    from app.services.money import is_revenue_side_code

    return is_revenue_side_code(invoice_type)


def build_invoice_entries(
    db: Session, tenant_id: UUID, invoice
) -> tuple[list[dict], Decimal]:
    """发票 → 借贷分录行（本位币）。

    收入侧（运费/期租/滞期）：借 应收账款 / 贷 营业收入 + 应交税费（销项）
    成本侧（使费/燃油/其他）：借 费用 + 进项税 / 贷 应付账款

    红冲发票金额为负 → 借贷方向自动对调（反向凭证）。
    返回 ``(entries, 总额)``；``entries`` 借贷必然相等。
    """
    from app.services import money as M

    code = M.invoice_type_code(invoice)
    codes = _invoice_account_codes(db, tenant_id, code)

    gross = M.invoice_base_gross(invoice)  # 本位币总额（含税）
    net = M.money(_base_net(invoice))  # 本位币税前净额
    tax = M.money(gross - net)

    if M.is_revenue_side(invoice):
        # 应收：借 应收账款(总额) / 贷 营业收入(税前) + 应交税费(销项)
        legs = [
            (codes["receivable"], gross, "debit"),
            (codes["revenue"], net, "credit"),
        ]
        if tax != 0:
            legs.append((codes["tax_payable"], tax, "credit"))
    else:
        # 应付：借 费用(税前) + 进项税 / 贷 应付账款(总额)
        legs = [
            (codes["expense"], net, "debit"),
            (codes["payable"], gross, "credit"),
        ]
        if tax != 0:
            legs.append((codes["tax_receivable"], tax, "debit"))

    # 金额为负（红冲）→ 借贷方向对调，金额取正
    flip = gross < 0
    entries: list[dict] = []
    for account, amount, direction in legs:
        if amount == 0:
            continue
        if flip:
            amount = -amount
            direction = "credit" if direction == "debit" else "debit"
        debit = amount if direction == "debit" else Decimal("0")
        credit = amount if direction == "credit" else Decimal("0")
        entries.append(
            {
                "account_code": account,
                "account_name": _account_name(db, tenant_id, account),
                "debit": str(M.money(debit)),
                "credit": str(M.money(credit)),
                "reference": f"INV:{invoice.invoice_no}",
                "description": f"{code} {invoice.invoice_no}",
            }
        )
    return entries, gross


def _base_net(invoice) -> Decimal:
    """本币税前净额。

    P1-B10：**唯一口径在 ``services.money.invoice_base_amount``**（SSOT）——
    ``base_amount`` 优先，其次 ``金额 × 汇率``，最后原币金额。以前这里
    自己抄了一份同样的三步规则，两处各改各的迟早分叉。
    """
    from app.services import money as M

    return M.invoice_base_amount(invoice)


def post_invoice_journal(
    db: Session,
    tenant_id: UUID,
    invoice,
    user_id: UUID | None = None,
) -> tuple[PeriodJournal, bool]:
    """把发票过账成一张真正的借贷分录（幂等）。

    返回 ``(journal, created)``；已过过账的发票返回原分录且 ``created=False``，
    不会产生第二张分录。**调用方负责 commit** —— 过账失败时不应该留下
    ``gl_posted=True`` 的半成品。
    """
    from app.services import money as M

    existing = db.scalar(
        select(PeriodJournal).where(
            PeriodJournal.tenant_id == tenant_id,
            PeriodJournal.journal_type == "invoice",
            PeriodJournal.source_type == "invoice",
            PeriodJournal.source_id == invoice.id,
        )
    )
    if existing is not None:
        return existing, False

    entries, gross = build_invoice_entries(db, tenant_id, invoice)
    if not entries:
        raise ValueError("Invoice has no amount to post (0.00)")

    base_ccy = _tenant_base_currency(db, tenant_id)
    period = (invoice.issued_at or utcnow_naive()).strftime("%Y-%m")
    journal = post_journal(
        db,
        tenant_id,
        period=period,
        journal_type="invoice",
        entries=entries,
        description=f"Invoice {invoice.invoice_no} ({invoice.currency} {gross})",
        user_id=user_id,
        currency=base_ccy,
        source_type="invoice",
        source_id=invoice.id,
    )
    return journal, True


def _tenant_base_currency(db: Session, tenant_id: UUID) -> str:
    from app.models_wave1 import Company

    comp = db.scalar(select(Company).where(Company.tenant_id == tenant_id).limit(1))
    return (comp.base_currency if comp and comp.base_currency else "USD")


def export_journal_csv(journal: PeriodJournal) -> str:
    """Export a period journal to standard CSV format (account, debit, credit, reference)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["account_code", "account_name", "debit", "credit", "reference", "description"])

    for entry in journal.entries:
        writer.writerow(
            [
                entry.get("account_code", ""),
                entry.get("account_name", ""),
                entry.get("debit", "0"),
                entry.get("credit", "0"),
                entry.get("reference", ""),
                entry.get("description", ""),
            ]
        )

    return output.getvalue()


def export_journal_sap(journal: PeriodJournal) -> str:
    """Export in SAP BAPI-compatible format (pipe-delimited)."""
    lines = []
    header = f"HEADER|{journal.period}|{journal.journal_type}|{journal.description or ''}"
    lines.append(header)

    for entry in journal.entries:
        row = "|".join(
            [
                "ENTRY",
                entry.get("account_code", ""),
                entry.get("debit", "0"),
                entry.get("credit", "0"),
                entry.get("reference", ""),
                entry.get("description", ""),
            ]
        )
        lines.append(row)

    lines.append(f"TOTAL|{journal.total_debit}|{journal.total_credit}")
    return "\n".join(lines)
