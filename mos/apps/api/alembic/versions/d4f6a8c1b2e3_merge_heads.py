"""Merge all branch heads into a single linear head.

Reform-track branches (D5 audit columns, TC hire components, plus the earlier
parallel feature branches) all descend from ``b1c2d3e4f5a6``. This is the
central merge point: after it, ``alembic heads`` must report exactly one.

Revision ID: d4f6a8c1b2e3
Revises: 46baddf23d3c, a5c7e9f1b3d2, a7e1c3f5b2d4, a9f4e2c7b1d3, bb025ca9b1c6, c2d3e4f5a6b7, c3d4e5f6a7b8, d7e8f0a1b2c3, e5c7a9b1d3f2, e8f9a0b1c2d3, f6a7b8c9d0e1, f8a2c4d6e1b0
Create Date: 2026-10-12
"""

from __future__ import annotations

revision = "d4f6a8c1b2e3"
down_revision = (
    "46baddf23d3c",
    "a5c7e9f1b3d2",
    "a7e1c3f5b2d4",
    "a9f4e2c7b1d3",
    "bb025ca9b1c6",
    "c2d3e4f5a6b7",
    "c3d4e5f6a7b8",
    "d7e8f0a1b2c3",
    "e5c7a9b1d3f2",
    "e8f9a0b1c2d3",
    "f6a7b8c9d0e1",
    "f8a2c4d6e1b0",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge revision — no schema change, only head convergence."""


def downgrade() -> None:
    """Downgrade re-splits into the individual branches (no schema change)."""
