"""user_view_state tab badges

Revision ID: 264afcd37d1c
Revises: 71396c451053
Create Date: 2026-10-23 22:36:06.605019

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '264afcd37d1c'
down_revision = '71396c451053'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 只建 user_view_state（tab 未读上标的 per-user last-seen 标记）。
    # autogenerate 同时吐出了一批与本次改动无关的历史漂移（vessels/charters/claims
    # 等列型差异），属 dev 库与模型的既存偏差，已剔除，避免 batch_alter 重建既有表。
    op.create_table(
        'user_view_state',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=False),
        sa.Column('tab_key', sa.Text(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'user_id', 'entity_type', 'entity_id', 'tab_key',
                            name='uq_user_view_state_user_entity_tab'),
    )


def downgrade() -> None:
    op.drop_table('user_view_state')
