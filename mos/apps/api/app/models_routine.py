"""例行任务中枢（Routine Task Hub）—— 期一数据模型。

把「例行的 input/output」变成系统一等公民：外部报文进 → 受限技能处理 → **待确认草稿**
→ 人工核实 → 落库。四张表：

- ``RoutineTask``   例行任务定义（租户级）：触发方式 + 技能 + 落库目标 + 功能开关
- ``SkillTemplate`` 技能模板（平台级 ``tenant_id IS NULL`` + 租户级覆盖）
- ``TriggerRule``   入站触发规则（发件人/域/主题/正文标记 → 命中哪个例行任务）
- ``DraftRecord``   统一待确认草稿（期一的核心实体，取代散落的各路草稿）

多租户约定：运行期行一律带 ``tenant_id``；平台级只有 ``SkillTemplate``（``tenant_id`` 可空，
走 ``global_ref_get`` 约定）。软删用 ``deleted_at``（``recycle.py`` 约定）——
**不要**写 ``status="deleted"``：草稿状态机与软删标记必须分开。

注册提醒：新增 ``models_*.py`` 模块必须在**三处** import（main.py / tests/conftest.py /
alembic/env.py），否则生产建表缺失或测试库缺表；部署契约测试会断言三处同步。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RoutineTask(Base):
    """例行任务定义（租户级）。

    ``module_code`` 指向**既有**业务模块码（operations / laytime / finance / email …），
    用于许可与角色闸门 —— 中枢本身不新增商业模块码，老租户零影响。
    """

    __tablename__ = "routine_tasks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_routine_tasks_tenant_code"),
        Index("ix_routine_tasks_tenant_enabled", "tenant_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)  # 租户内唯一
    name: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, default="inbound")  # inbound | outbound（期一只实现 inbound）
    module_code: Mapped[str] = mapped_column(Text, nullable=False)  # 许可/角色闸门用
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)  # inbound_email | schedule | event
    trigger_config: Mapped[dict] = mapped_column(JSON, default=dict)
    skill_code: Mapped[str] = mapped_column(Text, nullable=False)  # → SkillTemplate.code
    output_target: Mapped[str | None] = mapped_column(Text)  # noon_report | laytime_calc | estimate_charter
    owner_role: Mapped[str] = mapped_column(Text, default="operations")  # 待确认提醒发给谁
    sla_minutes: Mapped[int] = mapped_column(Integer, default=120)
    dedupe_key_template: Mapped[str] = mapped_column(Text, default="message:{message_id}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SkillTemplate(Base):
    """技能模板（受限 AI 技能定义）。

    ``tenant_id IS NULL`` = 平台模板（跨租户复用）；租户可自建或基于平台模板覆盖
    （``based_on`` 指向平台模板 code）。``output_schema`` / ``validator_rules`` 存
    **字段级契约与校验规则**（数据，不是可执行代码）—— 执行期由 skill_runtime
    编译成 pydantic 校验器。
    """

    __tablename__ = "skill_templates"
    __table_args__ = (UniqueConstraint("code", name="uq_skill_templates_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id"))
    code: Mapped[str] = mapped_column(Text, nullable=False)  # 全局唯一；租户自建建议带前缀
    name: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    prompt_template: Mapped[str | None] = mapped_column(Text)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    validator_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)
    deterministic_engine: Mapped[str | None] = mapped_column(Text)  # 算账引擎名（AI 不碰金额）
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    based_on: Mapped[str | None] = mapped_column(Text)  # 租户模板 → 平台模板 code
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TriggerRule(Base):
    """入站触发规则 —— 命中哪个例行任务。

    所有条件之间是 **AND**；同一任务下的多条规则之间是 **OR**。
    端点校验要求至少一个条件非空（空规则 = 全匹配，会把整个收件箱变成草稿）。
    """

    __tablename__ = "trigger_rules"
    __table_args__ = (Index("ix_trigger_rules_tenant_task", "tenant_id", "routine_task_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    routine_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("routine_tasks.id", ondelete="CASCADE"), nullable=False
    )
    sender_emails: Mapped[list] = mapped_column(JSON, default=list)
    sender_domains: Mapped[list] = mapped_column(JSON, default=list)
    subject_regex: Mapped[str | None] = mapped_column(Text)
    body_markers: Mapped[list] = mapped_column(JSON, default=list)
    folder: Mapped[str] = mapped_column(Text, default="inbox")
    direction: Mapped[str] = mapped_column(Text, default="inbound")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DraftRecord(Base):
    """待确认草稿 —— 中枢的核心实体。

    一条草稿 = 「某条来源（邮件/计划）经某技能处理后，拟写某个业务对象的字段」，
    外加**证据**（evidence）、**差异**（field_diff）与**置信度**。
    人工确认后才落库（``status: pending → confirmed → applied``）；
    驳回 = ``rejected``；处理失败 = ``failed`` 且 ``error`` 必须写明原因
    ——**失败不许静默**，这是「AI 恒答万能话术」事件的教训。

    幂等：``(tenant_id, dedupe_key)`` 唯一，键由例行任务的 ``dedupe_key_template``
    渲染（如 ``message:{message_id}`` / ``period:{period}``）→ 同一封邮件被拉两次
    不会产生两份草稿。
    """

    __tablename__ = "draft_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_draft_records_tenant_dedupe"),
        Index("ix_draft_records_tenant_status", "tenant_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    routine_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("routine_tasks.id"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(Text, default="email")  # email | schedule | event
    source_email_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("email_messages.id"))
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    target_entity: Mapped[str | None] = mapped_column(Text)  # noon_report | laytime_calc | ...
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # 落库后回填
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # 拟写字段
    field_diff: Mapped[dict] = mapped_column(JSON, default=dict)  # 与现有值/规则值的差异
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # [{source,ref,field,quote,confidence}]
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    status: Mapped[str] = mapped_column(Text, default="pending")
    # pending | confirmed | rejected | applied | superseded | failed
    error: Mapped[str | None] = mapped_column(Text)  # 失败原因（显性，不静默）
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_comment: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
