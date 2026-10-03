"""主数据扩展 — 节假日日历 / 工作日模式 / 术语表 / 标准条款段落。

HolidayCalendar: 年度节假日表（JSON 明细 [{date, name, type}]）
WorkingDayPattern: 周一~周日 工作/休息模式（装卸时间计算用）
TermList: 术语下拉源（laytime_terms / delivery_terms / payment_terms …）
StandardParagraph: 标准段落模板（cp_clause / invoice_note / claim_note）
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class HolidayCalendar(Base):
    __tablename__ = "holiday_calendars"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    holidays: Mapped[dict | list | None] = mapped_column(JSON)  # JSON: [{date, name, type}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkingDayPattern(Base):
    __tablename__ = "working_day_patterns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    monday: Mapped[bool] = mapped_column(Boolean, default=True)
    tuesday: Mapped[bool] = mapped_column(Boolean, default=True)
    wednesday: Mapped[bool] = mapped_column(Boolean, default=True)
    thursday: Mapped[bool] = mapped_column(Boolean, default=True)
    friday: Mapped[bool] = mapped_column(Boolean, default=True)
    saturday: Mapped[bool] = mapped_column(Boolean, default=False)
    sunday: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TermList(Base):
    __tablename__ = "term_lists"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)  # laytime_terms|delivery_terms|payment_terms|etc
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    label_en: Mapped[str] = mapped_column(Text, nullable=False)
    label_zh: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StandardParagraph(Base):
    __tablename__ = "standard_paragraphs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)  # cp_clause|invoice_note|claim_note
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
