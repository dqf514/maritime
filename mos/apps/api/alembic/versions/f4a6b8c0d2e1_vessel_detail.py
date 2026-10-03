"""Vessel detail extension — DWT/draft spec columns + 8 vessel-card tables.

Merges the two concurrent heads (bunker/laytime depth + finance depth) and
extends ``vessels`` with the IMOS vessel-card spec block, then creates the
detail tables: contacts / routes / tugs / tanks / performance / tce targets /
vettings / loadline zones.

Revision ID: f4a6b8c0d2e1
Revises: c8e4f1a2b7d9, e2f3a4b5c6d7
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4a6b8c0d2e1"
down_revision = ("c8e4f1a2b7d9", "e2f3a4b5c6d7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # —— vessels: DWT/draft tab + type detail + consumption detail + capacity ——
    op.add_column("vessels", sa.Column("summer_dwt", sa.Numeric(12, 2), nullable=True))
    op.add_column("vessels", sa.Column("tropical_dwt", sa.Numeric(12, 2), nullable=True))
    op.add_column("vessels", sa.Column("winter_dwt", sa.Numeric(12, 2), nullable=True))
    op.add_column("vessels", sa.Column("summer_draft", sa.Numeric(6, 2), nullable=True))
    op.add_column("vessels", sa.Column("tropical_draft", sa.Numeric(6, 2), nullable=True))
    op.add_column("vessels", sa.Column("winter_draft", sa.Numeric(6, 2), nullable=True))
    op.add_column("vessels", sa.Column("lightship", sa.Numeric(12, 2), nullable=True))
    op.add_column("vessels", sa.Column("deadweight_scale", sa.JSON(), nullable=True))
    op.add_column("vessels", sa.Column("hull_type", sa.Text(), nullable=True))
    op.add_column("vessels", sa.Column("build_year", sa.Integer(), nullable=True))
    op.add_column("vessels", sa.Column("build_yard", sa.Text(), nullable=True))
    op.add_column("vessels", sa.Column("flag_state", sa.Text(), nullable=True))
    op.add_column("vessels", sa.Column("ism_manager", sa.Text(), nullable=True))
    op.add_column("vessels", sa.Column("isps_manager", sa.Text(), nullable=True))
    op.add_column("vessels", sa.Column("sea_speed_25", sa.Numeric(10, 2), nullable=True))
    op.add_column("vessels", sa.Column("sea_speed_75", sa.Numeric(10, 2), nullable=True))
    op.add_column("vessels", sa.Column("sea_speed_100", sa.Numeric(10, 2), nullable=True))
    op.add_column("vessels", sa.Column("port_working", sa.Numeric(10, 2), nullable=True))
    op.add_column("vessels", sa.Column("port_idle", sa.Numeric(10, 2), nullable=True))
    op.add_column("vessels", sa.Column("port_maneuvering", sa.Numeric(10, 2), nullable=True))
    op.add_column("vessels", sa.Column("ifo_mdo_ratio", sa.Numeric(6, 3), nullable=True))
    op.add_column("vessels", sa.Column("max_lift_qty", sa.Numeric(12, 2), nullable=True))
    op.add_column("vessels", sa.Column("stowage_factor", sa.Numeric(10, 3), nullable=True))
    op.add_column("vessels", sa.Column("design_speed", sa.Numeric(5, 2), nullable=True))
    op.add_column("vessels", sa.Column("tank_capacity_total", sa.Numeric(12, 2), nullable=True))

    def _id_cols(extra_first: bool = True) -> list:
        cols = [
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
            sa.Column("vessel_id", sa.Uuid(), sa.ForeignKey("vessels.id"), nullable=False, index=True),
        ]
        return cols

    def _tail() -> list:
        return [
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        ]

    op.create_table(
        "vessel_contacts",
        *_id_cols(),
        sa.Column("contact_role", sa.Text(), nullable=False, server_default="captain"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        *_tail(),
    )
    op.create_table(
        "vessel_routes",
        *_id_cols(),
        sa.Column("route_name", sa.Text(), nullable=False),
        sa.Column("from_area", sa.Text(), nullable=True),
        sa.Column("to_area", sa.Text(), nullable=True),
        sa.Column("typical_speed", sa.Numeric(5, 2), nullable=True),
        sa.Column("distance_nm", sa.Numeric(10, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_tail(),
    )
    op.create_table(
        "vessel_tugs",
        *_id_cols(),
        sa.Column("tug_name", sa.Text(), nullable=False),
        sa.Column("port_id", sa.Uuid(), sa.ForeignKey("ports.id"), nullable=True),
        sa.Column("power_hp", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_tail(),
    )
    op.create_table(
        "vessel_tanks",
        *_id_cols(),
        sa.Column("tank_name", sa.Text(), nullable=False),
        sa.Column("tank_type", sa.Text(), nullable=False, server_default="fuel"),
        sa.Column("capacity_mt", sa.Numeric(12, 2), nullable=True),
        sa.Column("max_fill_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_tail(),
    )
    op.create_table(
        "vessel_performance",
        *_id_cols(),
        sa.Column("cargo_type", sa.Text(), nullable=False),
        sa.Column("load_rate_mt_hr", sa.Numeric(10, 2), nullable=True),
        sa.Column("discharge_rate_mt_hr", sa.Numeric(10, 2), nullable=True),
        sa.Column("stowage_factor", sa.Numeric(10, 3), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_tail(),
    )
    op.create_table(
        "vessel_tce_targets",
        *_id_cols(),
        sa.Column("year_month", sa.String(7), nullable=False),
        sa.Column("target_tce_usd", sa.Numeric(18, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_tail(),
    )
    op.create_table(
        "vessel_vettings",
        *_id_cols(),
        sa.Column("vetting_type", sa.Text(), nullable=False, server_default="sire"),
        sa.Column("vetting_date", sa.Date(), nullable=True),
        sa.Column("result", sa.Text(), nullable=False, server_default="pass"),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("inspector", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_tail(),
    )
    op.create_table(
        "loadline_zones",
        *_id_cols(),
        sa.Column("zone_name", sa.Text(), nullable=False, server_default="summer"),
        sa.Column("max_draft_m", sa.Numeric(6, 2), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        *_tail(),
    )


def downgrade() -> None:
    for table in (
        "loadline_zones",
        "vessel_vettings",
        "vessel_tce_targets",
        "vessel_performance",
        "vessel_tanks",
        "vessel_tugs",
        "vessel_routes",
        "vessel_contacts",
    ):
        op.drop_table(table)
    for col in (
        "tank_capacity_total",
        "design_speed",
        "stowage_factor",
        "max_lift_qty",
        "ifo_mdo_ratio",
        "port_maneuvering",
        "port_idle",
        "port_working",
        "sea_speed_100",
        "sea_speed_75",
        "sea_speed_25",
        "isps_manager",
        "ism_manager",
        "flag_state",
        "build_yard",
        "build_year",
        "hull_type",
        "deadweight_scale",
        "lightship",
        "winter_draft",
        "tropical_draft",
        "summer_draft",
        "winter_dwt",
        "tropical_dwt",
        "summer_dwt",
    ):
        op.drop_column("vessels", col)
