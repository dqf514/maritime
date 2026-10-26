"""merge email folder migration with ai settings fixes

Revision ID: d20728287518
Revises: 42a2637d9597, e3f5a7b9c1d2
Create Date: 2026-10-25 14:29:33.157386

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd20728287518'
down_revision = ('42a2637d9597', 'e3f5a7b9c1d2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
