"""Document templates & rendered-document archive（单据模板 / PDF 出档）。

对外单据（发票、装卸时间计算书、租金账单、成交回顾……）需要：
- 带公司抬头（logo/地址/税号/银行账户）的正式版式；
- 租户可自行调整（HTML/CSS 模板），且能恢复系统默认；
- 生成后可归档、可作为邮件附件发送给对手方。

DocumentTemplate  存模板正文（Jinja2 + HTML + CSS）。模板是租户可编辑的
不可信输入 —— 渲染一律走 :class:`jinja2.sandbox.SandboxedEnvironment`。

DocumentRender    每次出档留痕（谁、什么时候、用哪个模板、生成了什么文件）。
PDF 字节落盘在 ``uploads/documents/{tenant_id}/``，库里只存路径 —— 大对象
不进数据库（Postgres TOAST / SQLite 都会为此付出代价）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DocumentTemplate(Base):
    """可编辑单据模板（每租户每单据类型一份默认，可派生多个 code）。"""

    __tablename__ = "document_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", "code", "locale", name="uq_doc_tpl_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    # 单据类型 —— 由 doc_engine.DOC_TYPES 注册表约束，不在 DB 层建外键
    entity_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    # 同一单据类型的变体：default / long_form / cn …；租户改默认版式时仍在 default 上
    code: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # 当前只有 html（Jinja2 模板）；预留 pdf/xlsx 等
    format: Mapped[str] = mapped_column(Text, nullable=False, default="html")
    # Jinja2 + HTML 模板正文
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 附加 CSS（覆盖在内置基础样式之上）
    css: Mapped[str] = mapped_column(Text, nullable=False, default="")
    locale: Mapped[str] = mapped_column(Text, nullable=False, default="en")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 系统内置模板：租户可改，但「恢复默认」用它还原
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    system_body: Mapped[str | None] = mapped_column(Text)
    system_css: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class DocumentRender(Base):
    """出档留痕 —— 每次生成 PDF/HTML 都记一行，便于追溯与重新下载。"""

    __tablename__ = "document_renders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_templates.id", ondelete="SET NULL")
    )
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    doc_no: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str] = mapped_column(Text, nullable=False, default="pdf")
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False, default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # uploads/documents/{tenant_id}/{id}.pdf —— 相对 UPLOAD_ROOT，不存绝对路径
    storage_path: Mapped[str | None] = mapped_column(Text)
    # 生成时的信头快照（公司名/税号/银行），日后公司资料改了仍能还原当时发出的版本
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rendered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
