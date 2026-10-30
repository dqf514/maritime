"""tenants.ms_sso_scopes — per-tenant OIDC login scopes.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-31 10:00:00.000000

Some tenants register an SSO-only Entra app (no Graph permissions). The global
login scope included User.Read / offline_access, which those apps cannot
consent to. This nullable column lets a tenant override the login scope without
touching other tenants: NULL = platform default (backward compatible).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    insp = sa.inspect(op.get_bind())
    if "tenants" not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns("tenants")}


def upgrade() -> None:
    if "ms_sso_scopes" not in _columns():
        op.add_column("tenants", sa.Column("ms_sso_scopes", sa.Text(), nullable=True))


def downgrade() -> None:
    if "ms_sso_scopes" in _columns():
        op.drop_column("tenants", "ms_sso_scopes")
