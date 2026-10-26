"""domain_events — 域事件日志表（事件驱动自动化）。

Revision ID: b7e8f9a0c1d2
Revises: e3f5a7b9c1d2
Create Date: 2026-10-26

幂等：表已存在（如 create_all 已建）则跳过 —— 照 d2e3f4a5b6c7 的 inspector 模式。
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e8f9a0c1d2"
down_revision = "e3f5a7b9c1d2"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    if "domain_events" in _inspector().get_table_names():
        return
    op.create_table(
        "domain_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("handler_errors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_domain_events_tenant_id", "domain_events", ["tenant_id"])
    op.create_index("ix_domain_events_kind", "domain_events", ["kind"])
    op.create_index("ix_domain_events_entity_type", "domain_events", ["entity_type"])
    op.create_index("ix_domain_events_entity_id", "domain_events", ["entity_id"])
    op.create_index("ix_domain_events_created_at", "domain_events", ["created_at"])


def downgrade() -> None:
    if "domain_events" not in _inspector().get_table_names():
        return
    op.drop_table("domain_events")
