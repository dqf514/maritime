"""voyage notes instructions

Revision ID: 71396c451053
Revises: ab7195946a51
Create Date: 2026-10-23 17:45:11.578670

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '71396c451053'
down_revision = 'ab7195946a51'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 只建 voyage workspace 需要的两张表。autogenerate 同时吐出了一批与本次改动
    # 无关的历史漂移（vessels/charters/claims 等列型差异），属 dev 库与模型的既存
    # 偏差，已剔除，避免 batch_alter 重建既有表造成破坏。
    op.create_table(
        'voyage_instructions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('voyage_id', sa.Uuid(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('note_date', sa.Date(), nullable=True),
        sa.Column('kind', sa.Text(), nullable=False),
        sa.Column('ack', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['voyage_id'], ['voyages.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('voyage_instructions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_voyage_instructions_voyage_id'), ['voyage_id'], unique=False)

    op.create_table(
        'voyage_notes',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('voyage_id', sa.Uuid(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('note_date', sa.Date(), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.ForeignKeyConstraint(['voyage_id'], ['voyages.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('voyage_notes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_voyage_notes_voyage_id'), ['voyage_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('voyage_notes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_voyage_notes_voyage_id'))
    op.drop_table('voyage_notes')

    with op.batch_alter_table('voyage_instructions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_voyage_instructions_voyage_id'))
    op.drop_table('voyage_instructions')
