"""例行任务中枢（期一）：routine_tasks / skill_templates / trigger_rules / draft_records

Revision ID: d4e5f6a7b8c9
Revises: b7c8d9e0f1a2
Create Date: 2026-10-30 10:30:00.000000

把「例行 input/output」变成系统一等公民：外部报文进 → 受限技能处理 → 待确认草稿
→ 人工核实 → 落库。四张表都是**租户级**（只有 skill_templates 允许 tenant_id 为空
表示平台模板）。

迁移约定（alembic/README.md）：幂等 —— 表已存在则跳过（测试库由 create_all 建表）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None

_TABLES = ("routine_tasks", "skill_templates", "trigger_rules", "draft_records")


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    insp = _inspector()
    existing = set(insp.get_table_names())

    if "routine_tasks" not in existing:
        op.create_table(
            "routine_tasks",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("direction", sa.Text(), nullable=False, server_default="inbound"),
            sa.Column("module_code", sa.Text(), nullable=False),
            sa.Column("trigger_type", sa.Text(), nullable=False),
            sa.Column("trigger_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("skill_code", sa.Text(), nullable=False),
            sa.Column("output_target", sa.Text(), nullable=True),
            sa.Column("owner_role", sa.Text(), nullable=False, server_default="operations"),
            sa.Column("sla_minutes", sa.Integer(), nullable=False, server_default="120"),
            sa.Column(
                "dedupe_key_template",
                sa.Text(),
                nullable=False,
                server_default="message:{message_id}",
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.UniqueConstraint("tenant_id", "code", name="uq_routine_tasks_tenant_code"),
        )
        op.create_index("ix_routine_tasks_tenant_enabled", "routine_tasks", ["tenant_id", "enabled"])

    if "skill_templates" not in existing:
        op.create_table(
            "skill_templates",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=True),  # NULL = 平台模板
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("purpose", sa.Text(), nullable=True),
            sa.Column("prompt_template", sa.Text(), nullable=True),
            sa.Column("output_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("validator_rules", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("allowed_tools", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("deterministic_engine", sa.Text(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("based_on", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.UniqueConstraint("code", name="uq_skill_templates_code"),
        )

    if "trigger_rules" not in existing:
        op.create_table(
            "trigger_rules",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("routine_task_id", sa.Uuid(), nullable=False),
            sa.Column("sender_emails", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("sender_domains", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("subject_regex", sa.Text(), nullable=True),
            sa.Column("body_markers", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("folder", sa.Text(), nullable=False, server_default="inbox"),
            sa.Column("direction", sa.Text(), nullable=False, server_default="inbound"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["routine_task_id"], ["routine_tasks.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_trigger_rules_tenant_task", "trigger_rules", ["tenant_id", "routine_task_id"])

    if "draft_records" not in existing:
        op.create_table(
            "draft_records",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("routine_task_id", sa.Uuid(), nullable=False),
            sa.Column("source_kind", sa.Text(), nullable=False, server_default="email"),
            sa.Column("source_email_id", sa.Uuid(), nullable=True),
            sa.Column("dedupe_key", sa.Text(), nullable=False),
            sa.Column("target_entity", sa.Text(), nullable=True),
            sa.Column("target_id", sa.Uuid(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("field_diff", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("decided_by", sa.Uuid(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_comment", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Uuid(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["routine_task_id"], ["routine_tasks.id"]),
            sa.ForeignKeyConstraint(["source_email_id"], ["email_messages.id"]),
            sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_draft_records_tenant_dedupe"),
        )
        op.create_index(
            "ix_draft_records_tenant_status", "draft_records", ["tenant_id", "status", "created_at"]
        )


def downgrade() -> None:
    insp = _inspector()
    existing = set(insp.get_table_names())
    for table in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
