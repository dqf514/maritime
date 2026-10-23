"""document templates and render archive

Revision ID: fa29e6429092
Revises: a89bd8649b80
Create Date: 2026-10-22 20:20:21.125827

单据模板（DocumentTemplate）与出档留痕（DocumentRender）。

说明：本 revision 由 autogenerate 生成后手工裁剪 —— 原始 diff 混入了
若干既有表的未命名约束 drop（time_charter_contracts / coa_liftings /
claims / charters / bunker_orders），属于历史 schema 漂移，与本次改动
无关，保留会让 `alembic upgrade head` 在既有库上失败。此处只建本模块的
两张表，漂移另行处理。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fa29e6429092'
down_revision = 'a89bd8649b80'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'document_templates',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('format', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('css', sa.Text(), nullable=False),
        sa.Column('locale', sa.Text(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.Column('system_body', sa.Text(), nullable=True),
        sa.Column('system_css', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('meta', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_by', sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'entity_type', 'code', 'locale',
                            name='uq_doc_tpl_key'),
    )
    op.create_index('ix_document_templates_tenant_id', 'document_templates', ['tenant_id'])
    op.create_index('ix_document_templates_entity_type', 'document_templates', ['entity_type'])

    op.create_table(
        'document_renders',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Uuid(), nullable=True),
        sa.Column('template_id', sa.Uuid(), nullable=True),
        sa.Column('template_version', sa.Integer(), nullable=False),
        sa.Column('doc_no', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('format', sa.Text(), nullable=False),
        sa.Column('filename', sa.Text(), nullable=False),
        sa.Column('content_type', sa.Text(), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('storage_path', sa.Text(), nullable=True),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('rendered_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['template_id'], ['document_templates.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['rendered_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_document_renders_tenant_id', 'document_renders', ['tenant_id'])
    op.create_index('ix_document_renders_entity_type', 'document_renders', ['entity_type'])
    op.create_index('ix_document_renders_entity_id', 'document_renders', ['entity_id'])


def downgrade() -> None:
    op.drop_index('ix_document_renders_entity_id', table_name='document_renders')
    op.drop_index('ix_document_renders_entity_type', table_name='document_renders')
    op.drop_index('ix_document_renders_tenant_id', table_name='document_renders')
    op.drop_table('document_renders')
    op.drop_index('ix_document_templates_entity_type', table_name='document_templates')
    op.drop_index('ix_document_templates_tenant_id', table_name='document_templates')
    op.drop_table('document_templates')
