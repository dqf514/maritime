"""tenant ms365 app credentials

Revision ID: 7c1f2a9b4d51
Revises: 54d9ef473ec3
Create Date: 2026-09-18 00:00:00.000000

Per-tenant Microsoft 365 app credentials on `tenants` (platform-admin managed):
ms_client_id / ms_client_secret (Fernet cipher via ops_crypto) / ms_tenant /
ms_override_enabled. Legacy dev databases that predate stamping receive the
same columns from the guarded ALTER patch in app/main.py; this revision covers
Alembic-managed databases.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7c1f2a9b4d51'
down_revision = '54d9ef473ec3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('ms_client_id', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('ms_client_secret', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('ms_tenant', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('ms_override_enabled', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('tenants', 'ms_override_enabled')
    op.drop_column('tenants', 'ms_tenant')
    op.drop_column('tenants', 'ms_client_secret')
    op.drop_column('tenants', 'ms_client_id')
