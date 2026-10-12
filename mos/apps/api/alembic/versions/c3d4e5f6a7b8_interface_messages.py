"""Interface messages (IMOS Data Center 标配).

interface_messages — integration exchange log (inbound/outbound, channel,
interface_code, payload, retry bookkeeping).

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interface_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False, server_default="inbound"),
        sa.Column("channel", sa.Text(), nullable=False, server_default="http"),
        sa.Column("interface_code", sa.Text(), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_interface_messages_tenant_id", "interface_messages", ["tenant_id"])
    op.create_index("ix_interface_messages_status", "interface_messages", ["status"])
    op.create_index("ix_interface_messages_interface_code", "interface_messages", ["interface_code"])


def downgrade() -> None:
    op.drop_index("ix_interface_messages_interface_code", table_name="interface_messages")
    op.drop_index("ix_interface_messages_status", table_name="interface_messages")
    op.drop_index("ix_interface_messages_tenant_id", table_name="interface_messages")
    op.drop_table("interface_messages")
