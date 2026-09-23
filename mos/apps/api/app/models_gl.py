"""GL integration models: chart of accounts, business rules, period journals."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ChartOfAccount(Base):
    """科目表 — one row per GL account code per tenant."""

    __tablename__ = "chart_of_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "account_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    account_code: Mapped[str] = mapped_column(String(32), nullable=False)
    account_name: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False)  # revenue|expense|asset|liability|equity
    parent_code: Mapped[str | None] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BusinessRule(Base):
    """费用→科目映射规则 — maps expense categories to debit/credit account codes."""

    __tablename__ = "gl_business_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    rule_name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)  # voyage|invoice|bunker
    expense_category: Mapped[str] = mapped_column(String(32), nullable=False)  # freight|bunker|port|commission|...
    debit_account: Mapped[str] = mapped_column(String(32), nullable=False)
    credit_account: Mapped[str] = mapped_column(String(32), nullable=False)
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PeriodJournal(Base):
    """期间日记账 — batch of debit/credit entries for a given period."""

    __tablename__ = "period_journals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    journal_type: Mapped[str] = mapped_column(String(16), nullable=False)  # voyage|accrual|non_voyage|ic
    description: Mapped[str | None] = mapped_column(Text)
    entries: Mapped[dict] = mapped_column(JSON, default=list)  # [{account, debit, credit, reference, description}]
    total_debit: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total_credit: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    status: Mapped[str] = mapped_column(Text, default="draft")  # draft|posted|reversed
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
