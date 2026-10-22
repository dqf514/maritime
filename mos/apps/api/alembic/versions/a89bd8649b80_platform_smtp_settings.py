"""platform smtp settings

Revision ID: a89bd8649b80
Revises: c7e1f3a5b9d2
Create Date: 2026-10-22 11:12:21.918709

Platform-configurable SMTP delivery on `platform_identity_settings`
(platform-admin managed via /platform/identity): smtp_host / smtp_port /
smtp_security (starttls|ssl|none) / smtp_username / smtp_password_cipher
(Fernet cipher via ops_crypto — plaintext never leaves the server).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a89bd8649b80'
down_revision = 'c7e1f3a5b9d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('platform_identity_settings', sa.Column('smtp_host', sa.Text(), nullable=True))
    op.add_column('platform_identity_settings', sa.Column('smtp_port', sa.Integer(), nullable=True))
    op.add_column(
        'platform_identity_settings',
        sa.Column('smtp_security', sa.Text(), nullable=False, server_default='starttls'),
    )
    op.add_column('platform_identity_settings', sa.Column('smtp_username', sa.Text(), nullable=True))
    op.add_column('platform_identity_settings', sa.Column('smtp_password_cipher', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('platform_identity_settings', 'smtp_password_cipher')
    op.drop_column('platform_identity_settings', 'smtp_username')
    op.drop_column('platform_identity_settings', 'smtp_security')
    op.drop_column('platform_identity_settings', 'smtp_port')
    op.drop_column('platform_identity_settings', 'smtp_host')
