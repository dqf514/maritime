"""coa_liftings.tenant_id — tenant-scoped report dataset support.

The Report Designer requires every queryable dataset table to carry
``tenant_id`` (always-filter rule). ``coa_liftings`` was the only entity
scoped through its parent charter; this revision adds the column and
backfills it from ``charters.tenant_id``.

Revision ID: b8c4e2a1d7f9
Revises: a1b2c3d4e5f6
Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8c4e2a1d7f9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("coa_liftings") as batch:
        batch.add_column(sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE coa_liftings SET tenant_id = ("
        " SELECT c.tenant_id FROM charters c WHERE c.id = coa_liftings.charter_id"
        ") WHERE tenant_id IS NULL"
    )
    with op.batch_alter_table("coa_liftings") as batch:
        batch.alter_column("tenant_id", nullable=False)
        batch.create_index("ix_coa_liftings_tenant_id", ["tenant_id"])


def downgrade() -> None:
    with op.batch_alter_table("coa_liftings") as batch:
        batch.drop_index("ix_coa_liftings_tenant_id")
        batch.drop_column("tenant_id")
