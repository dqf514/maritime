"""Row-level data-ownership scope (行级数据权限).

Complements the tenant filter: when a role's effective scope for a module is
"own", list queries additionally restrict rows to those the user created
(``created_by == me``). Supervisors keep "all".

Additive & non-breaking: no RoleDataScope rows → every module is "all", so
existing tenants/tests are unaffected until an admin tightens a role in the
permission matrix. Effective scope across a user's roles is the *most
permissive* (all wins), so a supervisor who also holds a narrower role still
sees the whole tenant.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_saas import RoleDataScope

SUPERVISOR_ROLES = frozenset({"management", "tenant_admin", "platform_admin"})


def effective_scope(db: Session, tenant_id: UUID, roles: list[str], module: str) -> str:
    """Resolve a user's effective scope for a module: "own" | "all".

    - supervisors → always "all";
    - no rules for the module → "all" (unrestricted default);
    - any rule granting "all" → "all";
    - otherwise (every rule says "own") → "own".
    """
    if not roles or any(r in SUPERVISOR_ROLES for r in roles):
        return "all"
    rows = db.scalars(
        select(RoleDataScope).where(
            RoleDataScope.tenant_id == tenant_id,
            RoleDataScope.module == module,
            RoleDataScope.role_code.in_(roles),
        )
    ).all()
    scopes = {r.scope for r in rows}
    if not scopes:
        return "all"
    if "all" in scopes:
        return "all"
    return "own"


def apply_data_scope(stmt, model, user_id: UUID | None, scope: str):
    """Narrow a Select to the user's own rows when scope == "own".

    ``model`` must expose a ``created_by`` column; entities without one are left
    unchanged (no row-level restriction) rather than erroring.
    """
    if scope == "own" and user_id is not None and "created_by" in model.__table__.columns:
        stmt = stmt.where(model.created_by == user_id)
    return stmt
