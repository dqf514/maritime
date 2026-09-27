"""条款库（Phase 1 / D1）：结构化 CP 条款模板。

每条模板携带 ``params``——结构化的计费/作业参数（如 once_on_demurrage、
nor_terms、time_bar_days），勾选拼装到租约（charter.clauses.codes）后，
可物化为 laytime/索赔计算输入（GET /charters/{id}/laytime-inputs）。
``tenant_id`` 为空的行是内置系统包；租户自建条款挂在自己 tenant 下。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ClauseTemplate(Base):
    __tablename__ = "clause_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)  # NULL = 系统内置
    code: Mapped[str] = mapped_column(Text, nullable=False)
    cp_form: Mapped[str | None] = mapped_column(Text, index=True)  # GENCON / NYPE / SHELLTIME / 通用
    category: Mapped[str] = mapped_column(Text, default="general")  # laytime|demurrage|nor|off_hire|general
    title_en: Mapped[str] = mapped_column(Text, nullable=False)
    title_zh: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # 结构化计算参数
    text: Mapped[str | None] = mapped_column(Text)  # 条款正文（模板）
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
