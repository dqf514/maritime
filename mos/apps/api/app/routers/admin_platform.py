"""Platform operator + tenant admin APIs."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Module, Role, Tenant, TenantModuleLicense, User, UserRole
from app.security import AuthContext, get_current_auth, hash_password, require_module
from app.services.audit import audit
from app.services.graph_client import request_client_credentials_token
from app.services.ms_config import effective_mode, mask_ms_secret, resolve_ms_config
from app.services.ops_crypto import encrypt_secret
from app.services.search_acl import allowed_path_prefixes
from app.services.shell_nav import (
    build_home_widgets,
    build_navigation,
    build_workspaces,
    default_workspace,
)

router = APIRouter(tags=["Admin & Platform"])


def require_roles(*codes: str):
    def _dep(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if not any(c in auth.roles for c in codes):
            raise HTTPException(status_code=403, detail={"code": "ROLE_REQUIRED", "roles": list(codes)})
        return auth

    return _dep


# —— Shell contract for UI ——
class WorkspaceIn(BaseModel):
    workspace_id: str


@router.get("/shell/bootstrap")
def shell_bootstrap(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    from app.models_saas import TenantCompanyProfile

    tenant = db.get(Tenant, auth.tenant_id)
    assert tenant
    ws = default_workspace(auth.roles)
    # user preference stored lightly on user timezone field meta — use locale hack: preferences in JSON would be better
    pref = (auth.user.locale or "").split("|")
    if len(pref) > 1 and pref[1]:
        ws = pref[1]
    company = db.scalar(select(TenantCompanyProfile).where(TenantCompanyProfile.tenant_id == auth.tenant_id))
    return {
        "roles": auth.roles,
        "profile_tier": tenant.profile_tier,
        "is_platform": "platform_admin" in auth.roles,
        "tenant": {"id": str(tenant.id), "code": tenant.code, "name": tenant.name},
        "company": {
            "display_name": (company.display_name if company else None) or tenant.name,
            "logo_url": company.logo_url if company else None,
            "brand_primary": (company.brand_primary if company else None) or "#1A9B96",
            "brand_secondary": company.brand_secondary if company else None,
        },
        "navigation": build_navigation(auth.roles, tenant.profile_tier),
        "workspaces": build_workspaces(auth.roles),
        "active_workspace": ws,
        "home_widgets": build_home_widgets(auth.roles, ws),
        "quick_actions": _quick_actions(auth.roles),
        "allowed_paths": allowed_path_prefixes(db, tenant_id=auth.tenant_id, roles=auth.roles),
    }


@router.post("/shell/workspace")
def set_workspace(body: WorkspaceIn, auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    user = db.get(User, auth.user_id)
    assert user
    base_locale = (user.locale or "en").split("|")[0]
    user.locale = f"{base_locale}|{body.workspace_id}"
    db.commit()
    return {
        "active_workspace": body.workspace_id,
        "home_widgets": build_home_widgets(auth.roles, body.workspace_id),
    }


def _quick_actions(roles: list[str]) -> list[dict]:
    actions = [{"label": "Live dashboard", "href": "/dashboards"}]
    if "chartering" in roles or "tenant_admin" in roles:
        actions.append({"label": "New estimate", "href": "/estimates"})
        actions.append({"label": "Email review", "href": "/email/review"})
    if "operations" in roles or "tenant_admin" in roles:
        actions.append({"label": "Voyages", "href": "/operations/voyages"})
    if "technical" in roles or "operations" in roles or "tenant_admin" in roles:
        actions.append({"label": "Ship management", "href": "/ship"})
    if "finance" in roles or "tenant_admin" in roles:
        actions.append({"label": "Finance desk", "href": "/finance"})
    if "tenant_admin" in roles:
        actions.append({"label": "SelfCheck", "href": "/settings/selfcheck"})
        actions.append({"label": "Users", "href": "/admin/users"})
    if "platform_admin" in roles:
        actions.append({"label": "Tenants", "href": "/platform/tenants"})
    return actions


# —— Tenant admin: org / users / roles ——
class OrgUpdate(BaseModel):
    name: str | None = None
    default_timezone: str | None = None
    default_locale: str | None = None
    profile_tier: str | None = None


@router.get("/admin/organization")
def get_org(auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, auth.tenant_id)
    assert tenant
    user_count = db.scalar(select(func.count()).select_from(User).where(User.tenant_id == tenant.id)) or 0
    lic_count = db.scalar(
        select(func.count()).select_from(TenantModuleLicense).where(
            TenantModuleLicense.tenant_id == tenant.id, TenantModuleLicense.status == "active"
        )
    ) or 0
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "code": tenant.code,
        "status": tenant.status,
        "profile_tier": tenant.profile_tier,
        "default_locale": tenant.default_locale,
        "default_timezone": tenant.default_timezone,
        "user_count": user_count,
        "active_licenses": lic_count,
    }


@router.patch("/admin/organization")
def patch_org(body: OrgUpdate, auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, auth.tenant_id)
    assert tenant
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(tenant, k, v)
    tenant.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "profile_tier": tenant.profile_tier, "name": tenant.name}


@router.get("/admin/roles")
def list_roles(auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Role).where(Role.tenant_id == auth.tenant_id).order_by(Role.code)).all()
    return [{"id": str(r.id), "code": r.code, "name": r.name, "permissions": r.permissions or {}} for r in rows]


@router.get("/admin/users")
def list_users(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    from app.models_saas import OrgUnit, UserOrgMembership

    users = db.scalars(
        select(User)
        .where(User.tenant_id == auth.tenant_id, User.status != "deleted")
        .order_by(User.email)
        .offset(offset)
        .limit(limit)
    ).all()
    user_ids = [u.id for u in users]
    # Batch-load roles / primary org memberships instead of per-user queries.
    roles_by_user: dict[UUID, list[str]] = {uid: [] for uid in user_ids}
    if user_ids:
        for uid, code in db.execute(
            select(UserRole.user_id, Role.code)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
        ).all():
            roles_by_user.setdefault(uid, []).append(code)
    membership_by_user: dict[UUID, UserOrgMembership] = {}
    org_by_id: dict[UUID, OrgUnit] = {}
    if user_ids:
        memberships = db.scalars(
            select(UserOrgMembership).where(
                UserOrgMembership.user_id.in_(user_ids), UserOrgMembership.is_primary.is_(True)
            )
        ).all()
        membership_by_user = {m.user_id: m for m in memberships}
        org_ids = [m.org_unit_id for m in memberships]
        if org_ids:
            org_by_id = {o.id: o for o in db.scalars(select(OrgUnit).where(OrgUnit.id.in_(org_ids))).all()}
    out = []
    for u in users:
        membership = membership_by_user.get(u.id)
        org_unit = org_by_id.get(membership.org_unit_id) if membership else None
        if org_unit and org_unit.status == "deleted":
            org_unit = None
        out.append(
            {
                "id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "status": u.status,
                "roles": roles_by_user.get(u.id, []),
                "org_unit_id": str(org_unit.id) if org_unit else None,
                "org_unit_code": org_unit.code if org_unit else None,
                "org_unit_name": org_unit.name if org_unit else None,
            }
        )
    return out


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=8)
    role_codes: list[str] = Field(default_factory=lambda: ["viewer"])
    org_unit_id: UUID | None = None


@router.post("/admin/users")
def create_user(body: UserCreate, auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    from datetime import datetime

    from app.models_saas import OrgUnit, UserOrgMembership

    email = body.email.strip().lower()
    exists = db.scalar(select(User).where(User.tenant_id == auth.tenant_id, User.email == email))
    if exists and exists.status != "deleted":
        raise HTTPException(409, detail={"code": "USER_EXISTS", "message": "Email already in tenant"})
    # platform_admin cannot be granted from tenant admin
    if "platform_admin" in body.role_codes:
        raise HTTPException(403, detail={"code": "FORBIDDEN_ROLE", "message": "Cannot assign platform_admin"})
    user = User(
        tenant_id=auth.tenant_id,
        email=email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        status="active",
        locale="en",
        timezone="UTC",
        # Admin-provisioned password accounts are treated as verified; prefer /admin/security invites for email proof
        email_verified_at=datetime.now().astimezone(),
    )
    db.add(user)
    db.flush()
    for code in body.role_codes:
        role = db.scalar(select(Role).where(Role.tenant_id == auth.tenant_id, Role.code == code))
        if not role:
            raise HTTPException(400, detail={"code": "UNKNOWN_ROLE", "role": code})
        db.add(UserRole(user_id=user.id, role_id=role.id))
    if body.org_unit_id:
        unit = db.get(OrgUnit, body.org_unit_id)
        if not unit or unit.tenant_id != auth.tenant_id or unit.status == "deleted":
            raise HTTPException(400, detail={"code": "INVALID_ORG_UNIT"})
        db.add(UserOrgMembership(user_id=user.id, org_unit_id=unit.id, is_primary=True))
    # Audit row commits atomically with the new user
    audit(
        db,
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        action="admin.user_created",
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email, "roles": body.role_codes},
    )
    db.commit()
    return {"id": str(user.id), "email": user.email, "roles": body.role_codes, "org_unit_id": str(body.org_unit_id) if body.org_unit_id else None}


class UserUpdateIn(BaseModel):
    full_name: str | None = None
    status: str | None = None
    role_codes: list[str] | None = None
    org_unit_id: UUID | None = None
    clear_org: bool = False


@router.patch("/admin/users/{user_id}")
def update_user(
    user_id: UUID,
    body: UserUpdateIn,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    from app.models_saas import OrgUnit, UserOrgMembership

    user = db.get(User, user_id)
    if not user or user.tenant_id != auth.tenant_id or user.status == "deleted":
        raise HTTPException(404, "User not found")
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.status is not None:
        if body.status not in {"active", "disabled", "invited"}:
            raise HTTPException(400, "Invalid status")
        if body.status != user.status:
            # Status transition (e.g. disable) is security-relevant — audit it
            audit(
                db,
                tenant_id=auth.tenant_id,
                actor_user_id=auth.user_id,
                action="admin.user_status_changed",
                entity_type="user",
                entity_id=user.id,
                detail={"email": user.email, "from": user.status, "to": body.status},
            )
        user.status = body.status
    if body.role_codes is not None:
        if "platform_admin" in body.role_codes:
            raise HTTPException(403, detail={"code": "FORBIDDEN_ROLE"})
        for ur in db.scalars(select(UserRole).where(UserRole.user_id == user.id)).all():
            db.delete(ur)
        for code in body.role_codes:
            role = db.scalar(select(Role).where(Role.tenant_id == auth.tenant_id, Role.code == code))
            if not role:
                raise HTTPException(400, detail={"code": "UNKNOWN_ROLE", "role": code})
            db.add(UserRole(user_id=user.id, role_id=role.id))
        audit(
            db,
            tenant_id=auth.tenant_id,
            actor_user_id=auth.user_id,
            action="admin.user_roles_changed",
            entity_type="user",
            entity_id=user.id,
            detail={"email": user.email, "roles": body.role_codes},
        )
    if body.clear_org or body.org_unit_id is not None:
        for m in db.scalars(select(UserOrgMembership).where(UserOrgMembership.user_id == user.id)).all():
            if m.is_primary:
                m.is_primary = False
        if body.org_unit_id and not body.clear_org:
            unit = db.get(OrgUnit, body.org_unit_id)
            if not unit or unit.tenant_id != auth.tenant_id or unit.status == "deleted":
                raise HTTPException(400, detail={"code": "INVALID_ORG_UNIT"})
            existing = db.scalar(
                select(UserOrgMembership).where(
                    UserOrgMembership.user_id == user.id, UserOrgMembership.org_unit_id == unit.id
                )
            )
            if existing:
                existing.is_primary = True
            else:
                db.add(UserOrgMembership(user_id=user.id, org_unit_id=unit.id, is_primary=True))
    db.commit()
    roles = list(
        db.scalars(select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)).all()
    )
    membership = db.scalar(
        select(UserOrgMembership).where(UserOrgMembership.user_id == user.id, UserOrgMembership.is_primary.is_(True))
    )
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "status": user.status,
        "roles": roles,
        "org_unit_id": str(membership.org_unit_id) if membership else None,
    }


@router.delete("/admin/users/{user_id}")
def delete_user(
    user_id: UUID,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    from app.services.recycle import soft_delete

    user = db.get(User, user_id)
    if not user or user.tenant_id != auth.tenant_id or user.status == "deleted":
        raise HTTPException(404, "User not found")
    if user.id == auth.user_id:
        raise HTTPException(400, detail={"code": "CANNOT_DELETE_SELF"})
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="user",
        row=user,
        title=user.email,
    )
    audit(
        db,
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        action="admin.user_deleted",
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email},
    )
    db.commit()
    return {"ok": True, "recycled": True}


class UserRolesIn(BaseModel):
    role_codes: list[str]


@router.put("/admin/users/{user_id}/roles")
def set_user_roles(
    user_id: UUID,
    body: UserRolesIn,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user or user.tenant_id != auth.tenant_id:
        raise HTTPException(404, "User not found")
    if "platform_admin" in body.role_codes:
        raise HTTPException(403, detail={"code": "FORBIDDEN_ROLE"})
    for ur in db.scalars(select(UserRole).where(UserRole.user_id == user.id)).all():
        db.delete(ur)
    for code in body.role_codes:
        role = db.scalar(select(Role).where(Role.tenant_id == auth.tenant_id, Role.code == code))
        if not role:
            raise HTTPException(400, detail={"code": "UNKNOWN_ROLE", "role": code})
        db.add(UserRole(user_id=user.id, role_id=role.id))
    # Audit row commits atomically with the role assignment
    audit(
        db,
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        action="admin.user_roles_changed",
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email, "roles": body.role_codes},
    )
    db.commit()
    return {"id": str(user.id), "roles": body.role_codes}


# —— Platform operator ——
class TenantCreate(BaseModel):
    name: str
    code: str
    profile_tier: str = "M"
    admin_email: EmailStr
    admin_name: str = "Tenant Admin"
    admin_password: str = Field(min_length=8)


@router.get("/platform/tenants")
def platform_list_tenants(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(Tenant).order_by(Tenant.code)).all()
    out = []
    for t in rows:
        if t.code == "sys":
            continue
        users = db.scalar(select(func.count()).select_from(User).where(User.tenant_id == t.id)) or 0
        lics = db.scalar(
            select(func.count()).select_from(TenantModuleLicense).where(
                TenantModuleLicense.tenant_id == t.id, TenantModuleLicense.status == "active"
            )
        ) or 0
        out.append(
            {
                "id": str(t.id),
                "name": t.name,
                "code": t.code,
                "status": t.status,
                "profile_tier": t.profile_tier,
                "user_count": users,
                "license_count": lics,
            }
        )
    return out


@router.post("/platform/tenants")
def platform_create_tenant(body: TenantCreate, auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    if db.scalar(select(Tenant).where(Tenant.code == body.code)):
        raise HTTPException(409, detail={"code": "TENANT_EXISTS"})
    tenant = Tenant(
        name=body.name,
        code=body.code,
        status="active",
        profile_tier=body.profile_tier,
        default_locale="en",
        default_timezone="UTC",
    )
    db.add(tenant)
    db.flush()
    # clone standard roles
    role_defs = [
        ("tenant_admin", "Tenant Admin", {"*": True}),
        ("chartering", "Chartering", {"estimate": True, "chartering": True}),
        ("operations", "Operations", {"operations": True}),
        ("finance", "Finance", {"finance": True}),
        ("demurrage", "Demurrage", {"laytime": True, "claims": True}),
        ("management", "Management", {"analytics": True, "twin": True}),
        ("viewer", "Viewer", {"read": True}),
    ]
    role_map = {}
    for code, name, perms in role_defs:
        r = Role(tenant_id=tenant.id, code=code, name=name, permissions=perms)
        db.add(r)
        db.flush()
        role_map[code] = r
    admin_email = body.admin_email.strip().lower()
    admin = User(
        tenant_id=tenant.id,
        email=admin_email,
        full_name=body.admin_name,
        password_hash=hash_password(body.admin_password),
        status="active",
        locale="en",
        timezone="UTC",
        email_verified_at=datetime.now(timezone.utc).astimezone(),
    )
    db.add(admin)
    db.flush()
    db.add(UserRole(user_id=admin.id, role_id=role_map["tenant_admin"].id))
    now = datetime.now(timezone.utc)
    for mod in db.scalars(select(Module)).all():
        if mod.is_core or mod.code in {
            "masterdata",
            "estimate",
            "chartering",
            "operations",
            "laytime",
            "finance",
            "email",
            "analytics",
            "twin",
            "dataops",
            "bunker",
            "claims",
        }:
            db.add(
                TenantModuleLicense(
                    tenant_id=tenant.id,
                    module_code=mod.code,
                    status="active",
                    activated_at=now,
                    features={},
                )
            )
    db.commit()
    return {"id": str(tenant.id), "code": tenant.code, "admin_email": admin_email}


class TenantStatusIn(BaseModel):
    status: str  # active | suspended


@router.post("/platform/tenants/{tenant_id}/status")
def platform_tenant_status(
    tenant_id: UUID,
    body: TenantStatusIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    if body.status not in {"active", "suspended"}:
        raise HTTPException(400, "Invalid status")
    tenant = db.get(Tenant, tenant_id)
    if not tenant or tenant.code == "sys":
        raise HTTPException(404, "Tenant not found")
    tenant.status = body.status
    db.commit()
    return {"id": str(tenant.id), "status": tenant.status}


@router.get("/platform/tenants/{tenant_id}/licenses")
def platform_tenant_licenses(
    tenant_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    licensed = {
        r.module_code: r.status
        for r in db.scalars(select(TenantModuleLicense).where(TenantModuleLicense.tenant_id == tenant.id)).all()
    }
    modules = db.scalars(select(Module).order_by(Module.code)).all()
    return [
        {
            "module_code": m.code,
            "name": m.name,
            "is_core": m.is_core,
            "status": licensed.get(m.code, "inactive"),
        }
        for m in modules
    ]


class LicenseSetIn(BaseModel):
    module_code: str
    status: str = "active"


@router.post("/platform/tenants/{tenant_id}/licenses")
def platform_set_license(
    tenant_id: UUID,
    body: LicenseSetIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    if not db.get(Module, body.module_code):
        raise HTTPException(400, "Unknown module")
    if body.status not in {"active", "inactive", "expired"}:
        raise HTTPException(400, "Invalid license status")
    row = db.scalar(
        select(TenantModuleLicense).where(
            TenantModuleLicense.tenant_id == tenant.id,
            TenantModuleLicense.module_code == body.module_code,
        )
    )
    if not row:
        row = TenantModuleLicense(
            tenant_id=tenant.id,
            module_code=body.module_code,
            status=body.status,
            activated_at=datetime.now(timezone.utc),
            features={},
        )
        db.add(row)
    else:
        row.status = body.status
        if body.status == "active" and not row.activated_at:
            row.activated_at = datetime.now(timezone.utc)
    db.commit()
    return {"module_code": body.module_code, "status": body.status}


class TenantUpdateIn(BaseModel):
    name: str | None = None
    profile_tier: str | None = None
    default_locale: str | None = None
    default_timezone: str | None = None
    status: str | None = None


@router.get("/platform/tenants/{tenant_id}")
def platform_get_tenant(
    tenant_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    tenant = db.get(Tenant, tenant_id)
    if not tenant or tenant.code == "sys":
        raise HTTPException(404, "Tenant not found")
    users = db.scalar(select(func.count()).select_from(User).where(User.tenant_id == tenant.id)) or 0
    lics = db.scalar(
        select(func.count()).select_from(TenantModuleLicense).where(
            TenantModuleLicense.tenant_id == tenant.id, TenantModuleLicense.status == "active"
        )
    ) or 0
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "code": tenant.code,
        "status": tenant.status,
        "profile_tier": tenant.profile_tier,
        "default_locale": tenant.default_locale,
        "default_timezone": tenant.default_timezone,
        "user_count": users,
        "license_count": lics,
    }


@router.put("/platform/tenants/{tenant_id}")
def platform_update_tenant(
    tenant_id: UUID,
    body: TenantUpdateIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    tenant = db.get(Tenant, tenant_id)
    if not tenant or tenant.code == "sys":
        raise HTTPException(404, "Tenant not found")
    data = body.model_dump(exclude_none=True)
    if "status" in data and data["status"] not in {"active", "suspended"}:
        raise HTTPException(400, "Invalid status")
    if "profile_tier" in data and data["profile_tier"] not in {"S", "M", "L", "XL"}:
        raise HTTPException(400, "Invalid profile_tier")
    for k, v in data.items():
        setattr(tenant, k, v)
    db.commit()
    return platform_get_tenant(tenant_id, auth, db)


@router.get("/platform/modules")
def platform_list_modules(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(Module).order_by(Module.code)).all()
    return [{"code": m.code, "name": m.name, "is_core": m.is_core, "description": m.description} for m in rows]


@router.get("/platform/health")
def platform_health(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    tenants = db.scalars(select(Tenant).where(Tenant.code != "sys")).all()
    return {
        "tenant_count": len(tenants),
        "active": sum(1 for t in tenants if t.status == "active"),
        "suspended": sum(1 for t in tenants if t.status == "suspended"),
        "api_version": "1.4.2-platform",
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }


# —— Platform: per-tenant Microsoft 365 app credentials ——
class TenantOfficeConfigIn(BaseModel):
    override_enabled: bool | None = None
    client_id: str | None = None
    # secret semantics: omitted / "" = keep current, null = clear, value = replace
    client_secret: str | None = None
    ms_tenant: str | None = None


def _office_config_out(db: Session, tenant: Tenant) -> dict:
    settings = get_settings()
    cfg = resolve_ms_config(db, tenant.id)
    return {
        "override_enabled": bool(tenant.ms_override_enabled),
        "client_id": tenant.ms_client_id,
        "client_secret_masked": mask_ms_secret(tenant.ms_client_secret),
        "ms_tenant": tenant.ms_tenant or "",
        "effective_mode": effective_mode(cfg),
        "redirect_uri": f"{settings.api_public_base.rstrip('/')}/api/v1/office/oauth/callback",
        "has_secret": bool(tenant.ms_client_secret),
    }


def _get_platform_tenant(db: Session, tenant_id: UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if not tenant or tenant.code == "sys":
        raise HTTPException(404, "Tenant not found")
    return tenant


@router.get("/platform/tenants/{tenant_id}/office-config")
def platform_get_office_config(
    tenant_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    tenant = _get_platform_tenant(db, tenant_id)
    return _office_config_out(db, tenant)


@router.put("/platform/tenants/{tenant_id}/office-config")
def platform_put_office_config(
    tenant_id: UUID,
    body: TenantOfficeConfigIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    tenant = _get_platform_tenant(db, tenant_id)
    changed: list[str] = []
    if body.override_enabled is not None:
        tenant.ms_override_enabled = body.override_enabled
        changed.append(f"override_enabled={body.override_enabled}")
    if body.client_id is not None:
        tenant.ms_client_id = body.client_id.strip() or None
        changed.append("client_id")
    if "client_secret" in body.model_fields_set:
        if body.client_secret is None:
            tenant.ms_client_secret = None
            changed.append("client_secret_cleared")
        elif body.client_secret.strip():
            tenant.ms_client_secret = encrypt_secret(body.client_secret.strip())
            changed.append("client_secret_updated")
    if body.ms_tenant is not None:
        tenant.ms_tenant = body.ms_tenant.strip() or None
        changed.append("ms_tenant")
    tenant.updated_at = datetime.now(timezone.utc)
    # Audit trail must never contain the secret value itself
    audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=auth.user_id,
        action="platform.tenant_office_config_updated",
        entity_type="tenant",
        entity_id=tenant.id,
        detail={"changed": changed},
    )
    db.commit()
    return _office_config_out(db, tenant)


_ENTRA_ERROR_HINTS = {
    "invalid_client": "Client authentication failed — check client_id / client_secret",
    "unauthorized_client": "App is not authorized for the client_credentials grant",
    "invalid_request": "Invalid request — check the tenant (authority) value",
    "invalid_grant": "Grant rejected by Entra",
    "temporarily_unavailable": "Entra temporarily unavailable — retry later",
}


@router.post("/platform/tenants/{tenant_id}/office-config/test")
def platform_test_office_config(
    tenant_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    """Validate the tenant's effective credentials via client_credentials grant."""
    _ = auth
    tenant = _get_platform_tenant(db, tenant_id)
    cfg = resolve_ms_config(db, tenant.id)
    if not cfg.client_id or not cfg.client_secret:
        return {"ok": False, "message": "no credentials configured (client_id / client_secret missing)", "latency_ms": 0}
    started = time.perf_counter()
    try:
        res = request_client_credentials_token(cfg, timeout=10.0)
    except httpx.TimeoutException:
        return {
            "ok": False,
            "message": "timeout: token endpoint did not respond within 10s",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "message": f"network error: {exc}",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    latency_ms = int((time.perf_counter() - started) * 1000)
    if res.status_code < 400:
        return {"ok": True, "message": f"credentials accepted (source={cfg.source})", "latency_ms": latency_ms}
    try:
        payload = res.json()
    except ValueError:
        payload = {}
    code = payload.get("error") or f"http_{res.status_code}"
    hint = _ENTRA_ERROR_HINTS.get(code)
    if hint:
        message = f"{hint} [{code}]"
    else:
        desc = str(payload.get("error_description") or res.text or "")[:160]
        message = f"{code}: {desc}" if desc else code
    return {"ok": False, "message": message, "latency_ms": latency_ms}
