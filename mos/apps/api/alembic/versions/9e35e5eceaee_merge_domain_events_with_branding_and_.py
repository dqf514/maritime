"""merge domain events with branding and migration fixes

Revision ID: 9e35e5eceaee
Revises: d20728287518, b7e8f9a0c1d2
Create Date: 2026-10-26 17:35:21.601631

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9e35e5eceaee'
down_revision = ('d20728287518', 'b7e8f9a0c1d2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
