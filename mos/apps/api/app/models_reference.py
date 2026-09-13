"""租户可复制/自定义的参考数据（国家、时区、货币、船型、油种等）。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ReferenceDataset(Base):
    """数据源目录（系统级定义）。"""

    __tablename__ = "reference_datasets"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    description_en: Mapped[str | None] = mapped_column(Text)
    description_zh: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TenantReferenceConfig(Base):
    """租户对某数据源使用系统包还是本地副本。"""

    __tablename__ = "tenant_reference_configs"
    __table_args__ = (UniqueConstraint("tenant_id", "dataset_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    dataset_code: Mapped[str] = mapped_column(String(64), ForeignKey("reference_datasets.code"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="system")  # system | local
    cloned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReferenceItem(Base):
    """参考条目：scope_key=system 为内置；否则为租户 UUID 字符串（本地副本/自定义）。"""

    __tablename__ = "reference_items"
    __table_args__ = (UniqueConstraint("scope_key", "dataset_code", "code", name="uq_ref_item_scope_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_code: Mapped[str] = mapped_column(String(64), ForeignKey("reference_datasets.code"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"), index=True)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False, default="system", index=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    label_en: Mapped[str] = mapped_column(Text, nullable=False)
    label_zh: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(32), default="system")  # system | cloned | custom
    origin_code: Mapped[str | None] = mapped_column(String(128))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
