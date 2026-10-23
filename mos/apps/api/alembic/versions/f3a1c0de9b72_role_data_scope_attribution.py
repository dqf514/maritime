"""role_data_scopes + voyage/invoice attribution columns

Revision ID: f3a1c0de9b72
Revises: 264afcd37d1c
Create Date: 2026-10-23 23:55:00.000000

行级数据权限 (RoleDataScope) + 创建人/修改人 (voyages/invoices.created_by/updated_by)。
只包含本次改动；autogenerate 吐出的无关历史漂移（dev 库与模型既存列差）已剔除。
新增列不重建既有表，SQLite 升级路径仅加可空列（外键元数据由 create_all 在全新库建立）。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f3a1c0de9b72'
down_revision = '264afcd37d1c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'role_data_scopes',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('role_code', sa.Text(), nullable=False),
        sa.Column('module', sa.Text(), nullable=False),
        sa.Column('scope', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'role_code', 'module', name='uq_role_data_scope_tenant_role_module'),
    )
    # scope default "all" — additive, non-breaking
    op.execute("UPDATE role_data_scopes SET scope='all' WHERE scope IS NULL")

    op.add_column('voyages', sa.Column('created_by', sa.Uuid(), nullable=True))
    op.add_column('voyages', sa.Column('updated_by', sa.Uuid(), nullable=True))
    op.add_column('invoices', sa.Column('created_by', sa.Uuid(), nullable=True))
    op.add_column('invoices', sa.Column('updated_by', sa.Uuid(), nullable=True))
    op.add_column('invoices', sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('invoices', 'created_at')
    op.drop_column('invoices', 'updated_by')
    op.drop_column('invoices', 'created_by')
    op.drop_column('voyages', 'updated_by')
    op.drop_column('voyages', 'created_by')
    op.drop_table('role_data_scopes')
