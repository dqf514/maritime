"""Tenant-wide task system (manual + system generated) — 任务中心 2.0 的载体。

一张 ``tasks`` 表同时承载四种视角：
  * 个人 todo（自己建、自己做）
  * 团队协同（上级 → 下级指派，主责 + 协作人）
  * 系统动作联动（``action_code`` 绑到动作目录，业务动作做完自动勾完成）
  * OKR 分解（``objective_id`` + ``weight``，子任务进度加权上卷）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Numeric, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        # 真正的幂等键（替掉"标题字符串当键"）。SQLite 里 NULL 互不相等，
        # 所以多个 dedupe_key=NULL 的行可以共存。
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_tasks_tenant_dedupe"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="todo")  # todo|in_progress|done|cancelled
    priority: Mapped[str] = mapped_column(Text, default="normal")  # low|normal|high|urgent
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(Text, default="manual")  # manual|system
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ── 任务中心 2.0 ─────────────────────────────────────────────
    # 子任务（两级树）：父任务是"工作包/合同"这一层，子是具体动作
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tasks.id"))
    # 绑定的系统动作（见 services/action_catalog.py）—— 业务动作做完自动完成
    action_code: Mapped[str | None] = mapped_column(Text)
    # 权重（进度加权）：子任务/工作包/OKR 的进度按它折算
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("1"), server_default="1")
    # 协作人（可评论/可协助，不承担完成责任）—— 主责仍是 assignee_user_id
    # 存 NULL 表示"无协作人"（历史行无法回填 JSON，代码里按 [] 读）
    collaborator_ids: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    # 是否允许系统自动完成（绑了 action_code 时默认开）
    auto_complete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # 本次完成是否由系统判定（人工可覆盖）
    auto_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # 完成人（人工完成时=操作人；系统完成时为空）
    completed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    # 幂等键：系统任务用 "动作码:单据类型:单据ID" 之类，标题改了也不重复建
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    # 所属工作包（一份合同/航次/项目）
    work_package_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("work_packages.id"))
    # 所属 OKR 目标
    objective_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("objectives.id"))


class UserViewState(Base):
    """Per-user "last viewed" marker for shared tabs (tab badges / unread counts).

    Unread = rows created after ``last_seen_at`` for that (user, entity, tab).
    Rows are tiny and rewritten in place; never surfaced in the recycle bin.
    """

    __tablename__ = "user_view_state"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "entity_type", "entity_id", "tab_key",
            name="uq_user_view_state_user_entity_tab",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)  # voyage | invoice | charter | ...
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    tab_key: Mapped[str] = mapped_column(Text, nullable=False)  # notes | instructions | ...
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
