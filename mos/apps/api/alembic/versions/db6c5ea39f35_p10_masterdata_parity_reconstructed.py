"""P10 masterdata parity (reconstructed locally).

Revision ID: db6c5ea39f35
Revises: ab7195946a51
Create Date: 2026-10-23

Upstream revision ``ab7195946a51`` declares ``down_revision = 26c3fccfee50``,
but that P10 masterdata migration is missing from the repository. This local
revision reconstructs the missing additive schema (vessel/port/counterparty
columns plus cargo group/name, port berth/alias, counterparty property and
vessel consumption tables) from the current ORM metadata.

The autogenerate output was hand-cleaned to keep it purely additive: historical
type/default drift (alter_column), index drops and unnamed foreign keys were
removed so the migration is safe on both SQLite and PostgreSQL.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'db6c5ea39f35'
down_revision = 'ab7195946a51'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('cargo_groups',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'name')
    )

    op.create_table('port_aliases',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('port_id', sa.Uuid(), nullable=False),
    sa.Column('alias', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['port_id'], ['ports.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('port_id', 'alias')
    )

    op.create_table('port_berths',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('port_id', sa.Uuid(), nullable=False),
    sa.Column('short_name', sa.Text(), nullable=False),
    sa.Column('full_name', sa.Text(), nullable=True),
    sa.Column('inactive', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['port_id'], ['ports.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('port_id', 'short_name')
    )

    op.create_table('cargo_names',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('short_name', sa.Text(), nullable=False),
    sa.Column('full_name', sa.Text(), nullable=True),
    sa.Column('cargo_group_id', sa.Uuid(), nullable=True),
    sa.Column('cargo_class', sa.Text(), nullable=True),
    sa.Column('imo_name', sa.Text(), nullable=True),
    sa.Column('ibc_code', sa.Text(), nullable=True),
    sa.Column('imsbc_code', sa.Text(), nullable=True),
    sa.Column('un_number', sa.Text(), nullable=True),
    sa.Column('imdg_class', sa.Text(), nullable=True),
    sa.Column('dangerous', sa.Boolean(), nullable=False),
    sa.Column('special_handling', sa.Boolean(), nullable=False),
    sa.Column('pre_clearance_us_ca', sa.Boolean(), nullable=False),
    sa.Column('stow_factor_m3_mt', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('stow_factor_ft3_mt', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('api_gravity', sa.Numeric(precision=10, scale=4), nullable=True),
    sa.Column('product_code', sa.Text(), nullable=True),
    sa.Column('default_cp_unit', sa.Text(), nullable=True),
    sa.Column('capacity_basis', sa.Text(), nullable=True),
    sa.Column('bill_by', sa.Text(), nullable=True),
    sa.Column('inactive', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['cargo_group_id'], ['cargo_groups.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'short_name')
    )

    op.create_table('counterparty_properties',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('counterparty_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['counterparty_id'], ['counterparties.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('cargo_name_properties',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('cargo_name_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['cargo_name_id'], ['cargo_names.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    op.create_table('vessel_port_consumptions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('vessel_id', sa.Uuid(), nullable=False),
    sa.Column('inactive', sa.Boolean(), nullable=False),
    sa.Column('fuel_grade', sa.Text(), nullable=False),
    sa.Column('unit', sa.Text(), nullable=False),
    sa.Column('gas_flag', sa.Text(), nullable=True),
    sa.Column('capacity', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('margin', sa.Numeric(precision=12, scale=3), nullable=True),
    sa.Column('loading', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('discharge', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('idle_on', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('idle_off', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('heat', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('heat_plus', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('heat_plus_plus', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('igs', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('clean', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('manoeuvring', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('auxiliary', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('cooling', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('boiler', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('incinerator', sa.Numeric(precision=10, scale=3), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['vessel_id'], ['vessels.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('vessel_id', 'fuel_grade')
    )

    op.create_table('vessel_speed_consumptions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('vessel_id', sa.Uuid(), nullable=False),
    sa.Column('speed', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('ballast_laden', sa.Text(), nullable=True),
    sa.Column('engine_load', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('fuel_consumption', sa.JSON(), nullable=True),
    sa.Column('basis', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['vessel_id'], ['vessels.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    with op.batch_alter_table('counterparties', schema=None) as batch_op:
        batch_op.add_column(sa.Column('address_types', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('short_name', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('company_no', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ref_no', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('cross_ref', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('reference_code', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('veslink_id', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('fax', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('telex', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('department', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('main_contact', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('currency', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('credit_term', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('credit_line', sa.Numeric(precision=14, scale=2), nullable=True))
        batch_op.add_column(sa.Column('rating_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('demurrage_tb_days', sa.Numeric(precision=8, scale=2), nullable=True))
        batch_op.add_column(sa.Column('vat_no', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ap_account', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ar_account', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ic_account', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('default_account', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('status', sa.Text(), server_default='active', nullable=False))

    with op.batch_alter_table('ports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('port_type', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('parent_country', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('port_operator', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('port_no', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('port_area', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('region_code', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('loadline_zone', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('std_gmt_offset', sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.add_column(sa.Column('dst_gmt_offset', sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.add_column(sa.Column('external_ref', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('alerts', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('remarks', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('fuel_zone_default', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('supported_scrubbers', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('inactive', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('bunkering_port', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('single_berth', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('port_range', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('hide_passing_point', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('projection_port', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('lightering_port', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('use_high_sulfur_fuel', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('eu_ets_port', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('sts_exclusion', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('outermost_region', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('fuel_eu', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('uk_ets_port', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('uk_ets_ni', sa.Boolean(), server_default=sa.text('0'), nullable=False))

    with op.batch_alter_table('vessels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vessel_code', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('type_code', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('ownership', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('trade_area', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('class_society', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('vessel_owner_id', sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column('daily_cost', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('speed_laden', sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.add_column(sa.Column('speed_ballast', sa.Numeric(precision=5, scale=2), nullable=True))
        batch_op.add_column(sa.Column('tpc', sa.Numeric(precision=10, scale=2), nullable=True))
        batch_op.add_column(sa.Column('capacity_bale_ft3', sa.Numeric(precision=14, scale=2), nullable=True))
        batch_op.add_column(sa.Column('capacity_grain_ft3', sa.Numeric(precision=14, scale=2), nullable=True))
        batch_op.add_column(sa.Column('deck_capacity_m3', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('vessel_type_corr', sa.Numeric(precision=8, scale=3), nullable=True))
        batch_op.add_column(sa.Column('scrubber', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('constants_sea', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('constants_lakes', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('fresh_water', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('constants_others', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('beaufort', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('sea_state', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('sea_swell', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('vessels', schema=None) as batch_op:
        batch_op.drop_column('sea_swell')
        batch_op.drop_column('sea_state')
        batch_op.drop_column('beaufort')
        batch_op.drop_column('constants_others')
        batch_op.drop_column('fresh_water')
        batch_op.drop_column('constants_lakes')
        batch_op.drop_column('constants_sea')
        batch_op.drop_column('scrubber')
        batch_op.drop_column('vessel_type_corr')
        batch_op.drop_column('deck_capacity_m3')
        batch_op.drop_column('capacity_grain_ft3')
        batch_op.drop_column('capacity_bale_ft3')
        batch_op.drop_column('tpc')
        batch_op.drop_column('speed_ballast')
        batch_op.drop_column('speed_laden')
        batch_op.drop_column('daily_cost')
        batch_op.drop_column('vessel_owner_id')
        batch_op.drop_column('class_society')
        batch_op.drop_column('trade_area')
        batch_op.drop_column('ownership')
        batch_op.drop_column('type_code')
        batch_op.drop_column('vessel_code')

    with op.batch_alter_table('ports', schema=None) as batch_op:
        batch_op.drop_column('uk_ets_ni')
        batch_op.drop_column('uk_ets_port')
        batch_op.drop_column('fuel_eu')
        batch_op.drop_column('outermost_region')
        batch_op.drop_column('sts_exclusion')
        batch_op.drop_column('eu_ets_port')
        batch_op.drop_column('use_high_sulfur_fuel')
        batch_op.drop_column('lightering_port')
        batch_op.drop_column('projection_port')
        batch_op.drop_column('hide_passing_point')
        batch_op.drop_column('port_range')
        batch_op.drop_column('single_berth')
        batch_op.drop_column('bunkering_port')
        batch_op.drop_column('inactive')
        batch_op.drop_column('supported_scrubbers')
        batch_op.drop_column('fuel_zone_default')
        batch_op.drop_column('remarks')
        batch_op.drop_column('alerts')
        batch_op.drop_column('external_ref')
        batch_op.drop_column('dst_gmt_offset')
        batch_op.drop_column('std_gmt_offset')
        batch_op.drop_column('loadline_zone')
        batch_op.drop_column('region_code')
        batch_op.drop_column('port_area')
        batch_op.drop_column('port_no')
        batch_op.drop_column('port_operator')
        batch_op.drop_column('parent_country')
        batch_op.drop_column('port_type')

    with op.batch_alter_table('counterparties', schema=None) as batch_op:
        batch_op.drop_column('status')
        batch_op.drop_column('default_account')
        batch_op.drop_column('ic_account')
        batch_op.drop_column('ar_account')
        batch_op.drop_column('ap_account')
        batch_op.drop_column('vat_no')
        batch_op.drop_column('demurrage_tb_days')
        batch_op.drop_column('rating_date')
        batch_op.drop_column('credit_line')
        batch_op.drop_column('credit_term')
        batch_op.drop_column('currency')
        batch_op.drop_column('main_contact')
        batch_op.drop_column('department')
        batch_op.drop_column('telex')
        batch_op.drop_column('fax')
        batch_op.drop_column('veslink_id')
        batch_op.drop_column('reference_code')
        batch_op.drop_column('cross_ref')
        batch_op.drop_column('ref_no')
        batch_op.drop_column('company_no')
        batch_op.drop_column('short_name')
        batch_op.drop_column('address_types')

    op.drop_table('vessel_speed_consumptions')

    op.drop_table('vessel_port_consumptions')

    op.drop_table('cargo_name_properties')

    op.drop_table('counterparty_properties')

    op.drop_table('cargo_names')

    op.drop_table('port_berths')

    op.drop_table('port_aliases')

    op.drop_table('cargo_groups')
