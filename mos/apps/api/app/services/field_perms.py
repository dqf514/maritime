"""Field-level permission engine (字段级权限).

Additive: when no FieldPermission rows exist for a tenant/entity/role the
behaviour is unchanged (all fields writable / visible).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_field_perms import FieldPermission

MODES = ("read", "write", "hidden")

# Most-restrictive wins when a user holds several roles.
_RANK = {"write": 0, "read": 1, "hidden": 2}


def _as_roles(role: str | Sequence[str]) -> list[str]:
    if isinstance(role, str):
        return [role]
    return [r for r in role if r]


def get_field_modes(db: Session, tenant_id: UUID, entity: str, role: str | Sequence[str]) -> dict[str, str]:
    """Return {field: mode} for active rules covering the given role(s).

    Multiple roles merge most-restrictively (hidden > read > write).
    Fields without a rule are omitted — callers treat absence as full access.
    """
    roles = _as_roles(role)
    if not roles:
        return {}
    rows = db.scalars(
        select(FieldPermission).where(
            FieldPermission.tenant_id == tenant_id,
            FieldPermission.entity == entity,
            FieldPermission.role.in_(roles),
            FieldPermission.active.is_(True),
        )
    ).all()
    modes: dict[str, str] = {}
    for row in rows:
        cur = modes.get(row.field)
        if cur is None or _RANK.get(row.mode, 1) > _RANK.get(cur, 1):
            modes[row.field] = row.mode
    return modes


def assert_fields_writable(
    db: Session, tenant_id: UUID, entity: str, role: str | Sequence[str], fields: Iterable[str]
) -> None:
    """Raise 403 FIELD_NOT_PERMITTED if any field is read-only or hidden for the role(s).

    Fields without an explicit rule stay writable (additive default).
    """
    wanted = {f for f in fields if f}
    if not wanted:
        return
    modes = get_field_modes(db, tenant_id, entity, role)
    bad = sorted(f for f in wanted if modes.get(f, "write") in ("read", "hidden"))
    if bad:
        raise HTTPException(
            status_code=403,
            detail={"code": "FIELD_NOT_PERMITTED", "message": bad},
        )


def filter_read(payload: dict, modes: dict[str, str]) -> dict:
    """Drop fields whose mode is \"hidden\" from a response payload."""
    return {k: v for k, v in payload.items() if modes.get(k) != "hidden"}
