"""任务中心 2.0 的协作 / 工作包 / OKR 模型。

与 ``models_task.Task`` 的分工：
  * ``tasks``                —— 工作项本体（个人 todo + 团队任务 + 系统动作 + OKR 子任务）
  * ``task_comments``        —— 任务评论与 @提及（协同的最小单位）
  * ``work_packages``        —— 工作包：一份合同/航次/项目 = 一个带权重的任务组
  * ``objectives``           —— OKR 目标（可再分父目标）
  * ``key_results``          —— 关键结果（目标的量化子项）

进度一律**实时算**（见 ``services/task_progress.py``），表里只存权重与目标值，
不存派生出来的百分比 —— 避免缓存与真相不一致。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TaskComment(Base):
    """任务评论（协同）：@提及的人会收到通知。"""

    __tablename__ = "task_comments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "task_id", "id", name="uq_task_comments_tenant_task"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tasks.id"), nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # 被 @提及的用户 id 列表（JSON）
    mentions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkPackage(Base):
    """工作包：把一份合同/航次/项目拆成一组带权重的任务。

    进度 = 其下根任务按 ``weight`` 加权的完成比例（实时算）。
    """

    __tablename__ = "work_packages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_work_packages_tenant_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # 锚定的业务单据（charter / voyage / coa_contract …），可空
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    # 期间标签（2026Q4 / 2026-11 …），用于 OKR 周期与筛选
    period: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open")  # open|closed
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Objective(Base):
    """OKR 目标（Objective）。可再分子目标，自上而下分解。"""

    __tablename__ = "objectives"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_objectives_tenant_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("objectives.id"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    period: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("1"), server_default="1")
    status: Mapped[str] = mapped_column(Text, default="active")  # draft|active|closed
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class KeyResult(Base):
    """关键结果（KeyResult）：目标的量化子项。

    进度来源有二，优先取"关联任务的加权完成比例"，没有关联任务时用
    ``current_value / target_value``。
    """

    __tablename__ = "key_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    objective_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("objectives.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    # 量化口径说明（例：签发发票金额 / 完成航次数 / TCE 提升）
    metric: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    target_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0")
    current_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0")
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("1"), server_default="1")
    status: Mapped[str] = mapped_column(Text, default="active")  # active|closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
