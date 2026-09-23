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
from sqlalchemy.orm import Session

from app.models_gl import BusinessRule, ChartOfAccount, PeriodJournal


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
        amount = Decimal(str(line["amount"]))

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


def post_journal(
    db: Session,
    tenant_id: UUID,
    period: str,
    journal_type: str,
    entries: list[dict],
    description: str | None = None,
    user_id: UUID | None = None,
) -> PeriodJournal:
    """Create a PeriodJournal row from pre-built entries and mark it posted."""
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
        posted_at=datetime.now(),
        posted_by=user_id,
    )
    db.add(journal)
    db.flush()
    return journal


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
