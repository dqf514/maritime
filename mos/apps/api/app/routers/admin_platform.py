"""Platform operator + tenant admin APIs."""

from __future__ import annotations

import secrets
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
from app.services.identity import send_mail
from app.services.ms_config import effective_mode, mask_ms_secret, resolve_ms_config
from app.services.ops_crypto import encrypt_secret
from app.services.search_acl import allowed_path_prefixes
from app.services.upload_policy import (
    KINDS as UPLOAD_KINDS,
    get_all_upload_policies,
    get_upload_policy,
    save_upload_policy,
)
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
    # label_zh — 工作台右上快捷按钮的中文名（前端按 locale 取 label_zh || label）
    actions = [{"label": "Live dashboard", "label_zh": "实时看板", "href": "/dashboards"}]
    if "chartering" in roles or "tenant_admin" in roles:
        actions.append({"label": "New estimate", "label_zh": "新建估算", "href": "/estimates"})
        actions.append({"label": "Email review", "label_zh": "邮件识别", "href": "/email/review"})
    if "operations" in roles or "tenant_admin" in roles:
        actions.append({"label": "Voyages", "label_zh": "航次列表", "href": "/operations/voyages"})
    if "technical" in roles or "operations" in roles or "tenant_admin" in roles:
        actions.append({"label": "Ship management", "label_zh": "船舶管理", "href": "/ship"})
    if "finance" in roles or "tenant_admin" in roles:
        actions.append({"label": "Finance desk", "label_zh": "财务工作台", "href": "/finance"})
    if "tenant_admin" in roles:
        actions.append({"label": "SelfCheck", "label_zh": "系统自检", "href": "/settings/selfcheck"})
        actions.append({"label": "Users", "label_zh": "用户管理", "href": "/admin/users"})
    if "platform_admin" in roles:
        actions.append({"label": "Tenants", "label_zh": "租户管理", "href": "/platform/tenants"})
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


# ── 租户数据运维：一键备份 / 恢复 / 清理（商务交付：测试数据清理） ──


def _platform_tenant_or_404(db: Session, tenant_id: UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if not tenant or tenant.code == "sys":
        raise HTTPException(404, "Tenant not found")
    return tenant


def _backup_job_out(job) -> dict:
    return {
        "id": str(job.id),
        "status": job.status,
        "trigger": job.trigger,
        "storage_path": job.storage_path,
        "checksum": job.checksum,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": job.error,
    }


@router.post("/platform/tenants/{tenant_id}/backup")
def platform_backup_tenant(
    tenant_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    """全量备份租户数据（所有带 tenant_id 的业务表 → JSON + BackupJob 记录）。"""
    from app.services.tenant_backup import dump_tenant, write_backup_file

    tenant = _platform_tenant_or_404(db, tenant_id)
    payload = dump_tenant(db, tenant.id, created_by=auth.user_id, trigger="platform")
    job = write_backup_file(db, tenant.id, payload, created_by=auth.user_id)
    return {**_backup_job_out(job), "row_counts": payload["row_counts"], "total_rows": payload["total_rows"]}


@router.get("/platform/tenants/{tenant_id}/backups")
def platform_list_tenant_backups(
    tenant_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    from app.services.tenant_backup import list_tenant_backups

    tenant = _platform_tenant_or_404(db, tenant_id)
    return [_backup_job_out(j) for j in list_tenant_backups(db, tenant.id)]


class TenantRestoreIn(BaseModel):
    storage_path: str  # backups/tenant/<tid>/<job>.json


@router.post("/platform/tenants/{tenant_id}/restore")
def platform_restore_tenant(
    tenant_id: UUID,
    body: TenantRestoreIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    """从备份文件恢复（已存在主键跳过，不覆盖现有行）。"""
    from app.services.tenant_backup import load_backup_payload, restore_tenant

    tenant = _platform_tenant_or_404(db, tenant_id)
    rel = body.storage_path.replace("\\", "/").strip("/")
    if not rel.startswith(f"backups/tenant/{tenant.id}/") or ".." in rel:
        raise HTTPException(400, detail={"code": "INVALID_BACKUP_PATH"})
    try:
        payload = load_backup_payload(rel)
    except FileNotFoundError:
        raise HTTPException(404, detail={"code": "BACKUP_NOT_FOUND"})
    if payload.get("tenant_id") != str(tenant.id):
        raise HTTPException(400, detail={"code": "BACKUP_TENANT_MISMATCH"})
    result = restore_tenant(db, tenant.id, payload)
    return {"id": str(tenant.id), "code": tenant.code, **result}


class TenantPurgeIn(BaseModel):
    confirm: str  # 必须等于租户 code，防误点
    backup_first: bool = True
    include_users: bool = False


@router.post("/platform/tenants/{tenant_id}/purge")
def platform_purge_tenant(
    tenant_id: UUID,
    body: TenantPurgeIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    """一键清理租户业务数据（默认先自动备份；保留租户/用户/许可底座）。

    ``include_users=True`` 连用户与身份一起删除（角色行保留，仅清人员）。
    """
    from app.services.tenant_backup import dump_tenant, purge_tenant, write_backup_file

    tenant = _platform_tenant_or_404(db, tenant_id)
    if body.confirm != tenant.code:
        raise HTTPException(400, detail={"code": "CONFIRM_MISMATCH", "message": "confirm must equal tenant code"})
    backup_job = None
    if body.backup_first:
        payload = dump_tenant(db, tenant.id, created_by=auth.user_id, trigger="platform_purge")
        backup_job = write_backup_file(db, tenant.id, payload, created_by=auth.user_id)
    result = purge_tenant(db, tenant.id, include_users=body.include_users)
    return {
        "id": str(tenant.id),
        "code": tenant.code,
        "backup": _backup_job_out(backup_job) if backup_job else None,
        **result,
    }


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


@router.delete("/platform/tenants/{tenant_id}")
def platform_delete_tenant(
    tenant_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    """Deactivate a tenant — never hard-deletes the tenant row.

    Uses the documented ``status="suspended"`` value (the only one the auth layer
    blocks in ``security._assert_tenant_active``). Reversible via PUT /status.
    """
    tenant = db.get(Tenant, tenant_id)
    if not tenant or tenant.code == "sys" or tenant.status != "active":
        raise HTTPException(404, "Tenant not found")
    if tenant.id == auth.tenant_id:
        raise HTTPException(400, detail={"code": "CANNOT_DELETE_SELF"})
    active_count = (
        db.scalar(select(func.count()).select_from(Tenant).where(Tenant.status == "active", Tenant.code != "sys")) or 0
    )
    if active_count <= 1:
        raise HTTPException(409, detail={"code": "LAST_ACTIVE_TENANT", "message": "Cannot deactivate the last active tenant"})
    tenant.status = "suspended"
    db.commit()
    audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=auth.user_id,
        action="platform.tenant_deactivated",
        entity_type="tenant",
        entity_id=tenant.id,
        detail={"code": tenant.code, "name": tenant.name},
    )
    db.commit()
    return {"id": str(tenant.id), "code": tenant.code, "status": tenant.status, "ok": True}


@router.get("/platform/modules")
def platform_list_modules(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(Module).order_by(Module.code)).all()
    return [{"code": m.code, "name": m.name, "is_core": m.is_core, "description": m.description} for m in rows]


def _db_size_bytes() -> int | None:
    """Best-effort DB size. SQLite: file size. Others: None (no cheap portable probe)."""
    try:
        url = get_settings().database_url
        if url.startswith("sqlite"):
            path = url.split("///", 1)[-1]
            import os as _os

            return _os.path.getsize(path) if _os.path.exists(path) else None
    except Exception:  # noqa: BLE001
        return None
    return None


def _disk_pct() -> float:
    try:
        import os as _os

        if _os.name == "nt":
            import shutil

            total, used, _free = shutil.disk_usage(_os.path.abspath("."))
            return round(used / total * 100, 2) if total else 0.0
        st = _os.statvfs(".")
        total = st.f_blocks * st.f_frsize
        used = total - st.f_bavail * st.f_frsize
        return round(used / total * 100, 2) if total else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _resource_snapshot(db: Session) -> dict:
    import time as _time
    import os as _os

    t0 = _time.perf_counter()
    try:
        db.execute(select(1))
        ping_ok = True
    except Exception:  # noqa: BLE001
        ping_ok = False
    ping_ms = round((_time.perf_counter() - t0) * 1000, 2)
    return {
        "disk_pct": _disk_pct(),
        "db_ping_ms": ping_ms,
        "db_up": ping_ok,
        "db_size_bytes": _db_size_bytes(),
        "cpu_count": _os.cpu_count(),
    }


def _per_tenant_usage(db: Session) -> list[dict]:
    """Row counts for a few core tables, grouped by tenant (demo-scale cheap)."""
    from app.models_domain import Invoice, Voyage
    from app.models_task import Task

    def _counts(model) -> dict:
        rows = db.execute(select(model.tenant_id, func.count()).group_by(model.tenant_id)).all()
        return {str(tid): n for tid, n in rows if tid}

    v_counts = _counts(Voyage)
    i_counts = _counts(Invoice)
    t_counts = _counts(Task)
    tenants = db.scalars(select(Tenant).where(Tenant.code != "sys").order_by(Tenant.code)).all()
    user_counts = dict(
        db.execute(select(User.tenant_id, func.count()).group_by(User.tenant_id)).all()
    )
    out: list[dict] = []
    for t in tenants:
        tid = str(t.id)
        out.append(
            {
                "id": tid,
                "code": t.code,
                "name": t.name,
                "status": t.status,
                "users": int(user_counts.get(t.id, 0)),
                "voyages": int(v_counts.get(tid, 0)),
                "invoices": int(i_counts.get(tid, 0)),
                "tasks": int(t_counts.get(tid, 0)),
            }
        )
    return out


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
        "resources": _resource_snapshot(db),
        "tenants_usage": _per_tenant_usage(db),
    }


# —— Platform: central upload policy (type + size limits) ——
class UploadPolicyIn(BaseModel):
    max_bytes: int | None = None
    exts: list[str] | None = None


class UploadSettingsIn(BaseModel):
    kinds: dict[str, UploadPolicyIn] = Field(default_factory=dict)


@router.get("/platform/upload-settings")
def get_platform_upload_settings(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    return {"kinds": get_all_upload_policies(db)}


@router.put("/platform/upload-settings")
def put_platform_upload_settings(
    body: UploadSettingsIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    saved: dict = {}
    for kind, patch in body.kinds.items():
        saved[kind] = save_upload_policy(
            db,
            kind,
            max_bytes=patch.max_bytes,
            exts=patch.exts,
            updated_by=auth.user_id,
        )
    return {"kinds": saved}


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


# ── 平台管理员：任意租户的用户（含租户管理员）增删改 + 密码重置（邮件发送） ──


def _platform_user_or_404(db: Session, tenant: Tenant, user_id: UUID) -> User:
    user = db.get(User, user_id)
    if not user or user.tenant_id != tenant.id or user.status == "deleted":
        raise HTTPException(404, detail={"code": "USER_NOT_FOUND"})
    return user


def _active_tenant_admin_ids(db: Session, tenant_id: UUID) -> set[UUID]:
    rows = db.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.tenant_id == tenant_id, User.status == "active", Role.code == "tenant_admin")
    ).all()
    return {r[0] for r in rows}


def _user_role_codes(db: Session, user_id: UUID) -> list[str]:
    return list(
        db.scalars(
            select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
        ).all()
    )


def _gen_temp_password(length: int = 16) -> str:
    """Server-side twin of web/lib/api.ts generateTempPassword()."""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%&*"
    return "".join(chars[secrets.randbelow(len(chars))] for _ in range(length))


def _platform_user_out(db: Session, u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "full_name": u.full_name,
        "status": u.status,
        "roles": _user_role_codes(db, u.id),
        "email_verified": bool(u.email_verified_at),
    }


@router.get("/platform/tenants/{tenant_id}/roles")
def platform_tenant_roles(
    tenant_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    tenant = _platform_tenant_or_404(db, tenant_id)
    rows = db.scalars(select(Role).where(Role.tenant_id == tenant.id).order_by(Role.code)).all()
    return [{"id": str(r.id), "code": r.code, "name": r.name, "permissions": r.permissions or {}} for r in rows]


@router.get("/platform/tenants/{tenant_id}/users")
def platform_list_tenant_users(
    tenant_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    tenant = _platform_tenant_or_404(db, tenant_id)
    users = db.scalars(
        select(User)
        .where(User.tenant_id == tenant.id, User.status != "deleted")
        .order_by(User.email)
        .offset(offset)
        .limit(limit)
    ).all()
    user_ids = [u.id for u in users]
    roles_by_user: dict[UUID, list[str]] = {uid: [] for uid in user_ids}
    if user_ids:
        for uid, code in db.execute(
            select(UserRole.user_id, Role.code)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
        ).all():
            roles_by_user.setdefault(uid, []).append(code)
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "status": u.status,
            "roles": roles_by_user.get(u.id, []),
            "email_verified": bool(u.email_verified_at),
        }
        for u in users
    ]


class PlatformUserCreateIn(BaseModel):
    email: EmailStr
    full_name: str
    role_codes: list[str] = Field(default_factory=lambda: ["viewer"])
    # omitted → server generates a temp password (returned once + emailed)
    password: str | None = Field(default=None, min_length=8)
    send_email: bool = True


@router.post("/platform/tenants/{tenant_id}/users")
def platform_create_tenant_user(
    tenant_id: UUID,
    body: PlatformUserCreateIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    """Platform-provisioned account for any tenant; mails the credentials when send_email."""
    tenant = _platform_tenant_or_404(db, tenant_id)
    email = body.email.strip().lower()
    exists = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
    if exists and exists.status != "deleted":
        raise HTTPException(409, detail={"code": "USER_EXISTS", "message": "Email already in tenant"})
    if "platform_admin" in body.role_codes:
        raise HTTPException(403, detail={"code": "FORBIDDEN_ROLE", "message": "Cannot assign platform_admin"})
    password = body.password or _gen_temp_password()
    user = User(
        tenant_id=tenant.id,
        email=email,
        full_name=body.full_name,
        password_hash=hash_password(password),
        status="active",
        locale="en",
        timezone="UTC",
        # Provisioned with a known password → treated as verified (same as tenant admin path)
        email_verified_at=datetime.now(timezone.utc).astimezone(),
    )
    db.add(user)
    db.flush()
    for code in body.role_codes:
        role = db.scalar(select(Role).where(Role.tenant_id == tenant.id, Role.code == code))
        if not role:
            raise HTTPException(400, detail={"code": "UNKNOWN_ROLE", "role": code})
        db.add(UserRole(user_id=user.id, role_id=role.id))
    emailed = False
    if body.send_email:
        send_mail(
            db,
            to_email=email,
            subject="Your MariOS account",
            body=(
                f"Hello {body.full_name},\n\n"
                f"A platform administrator created your MariOS account for tenant \"{tenant.name}\" ({tenant.code}).\n\n"
                f"Login: {email}\n"
                f"Temporary password: {password}\n\n"
                "Please sign in and change your password after first login."
            ),
            purpose="account_created",
            tenant_id=tenant.id,
            meta={"created_by": str(auth.user_id)},
        )
        emailed = True
    audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=auth.user_id,
        action="platform.user_created",
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email, "roles": body.role_codes, "emailed": emailed},
    )
    db.commit()
    return {
        **_platform_user_out(db, user),
        # Returned once so the platform admin can hand it over directly; never persisted in logs
        "temp_password": password if not body.password else None,
        "emailed": emailed,
    }


class PlatformUserUpdateIn(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = None
    status: str | None = None  # active | disabled | invited
    role_codes: list[str] | None = None


@router.patch("/platform/tenants/{tenant_id}/users/{user_id}")
def platform_update_tenant_user(
    tenant_id: UUID,
    user_id: UUID,
    body: PlatformUserUpdateIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    tenant = _platform_tenant_or_404(db, tenant_id)
    user = _platform_user_or_404(db, tenant, user_id)
    if body.email is not None:
        email = body.email.strip().lower()
        if email != user.email:
            clash = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
            if clash and clash.status != "deleted":
                raise HTTPException(409, detail={"code": "USER_EXISTS"})
            user.email = email
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.status is not None:
        if body.status not in {"active", "disabled", "invited"}:
            raise HTTPException(400, "Invalid status")
        if body.status != user.status:
            admins = _active_tenant_admin_ids(db, tenant.id)
            if user.id in admins and len(admins) <= 1 and body.status != "active":
                raise HTTPException(409, detail={"code": "LAST_TENANT_ADMIN", "message": "Cannot deactivate the last active tenant admin"})
            audit(
                db,
                tenant_id=tenant.id,
                actor_user_id=auth.user_id,
                action="platform.user_status_changed",
                entity_type="user",
                entity_id=user.id,
                detail={"email": user.email, "from": user.status, "to": body.status},
            )
            user.status = body.status
    if body.role_codes is not None:
        if "platform_admin" in body.role_codes:
            raise HTTPException(403, detail={"code": "FORBIDDEN_ROLE"})
        admins = _active_tenant_admin_ids(db, tenant.id)
        keeps_admin = user.id in admins and "tenant_admin" in body.role_codes and user.status == "active"
        if user.id in admins and not keeps_admin and len(admins) <= 1:
            raise HTTPException(409, detail={"code": "LAST_TENANT_ADMIN", "message": "Cannot remove tenant_admin from the last active tenant admin"})
        for ur in db.scalars(select(UserRole).where(UserRole.user_id == user.id)).all():
            db.delete(ur)
        for code in body.role_codes:
            role = db.scalar(select(Role).where(Role.tenant_id == tenant.id, Role.code == code))
            if not role:
                raise HTTPException(400, detail={"code": "UNKNOWN_ROLE", "role": code})
            db.add(UserRole(user_id=user.id, role_id=role.id))
        audit(
            db,
            tenant_id=tenant.id,
            actor_user_id=auth.user_id,
            action="platform.user_roles_changed",
            entity_type="user",
            entity_id=user.id,
            detail={"email": user.email, "roles": body.role_codes},
        )
    audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=auth.user_id,
        action="platform.user_updated",
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email},
    )
    db.commit()
    return _platform_user_out(db, user)


@router.delete("/platform/tenants/{tenant_id}/users/{user_id}")
def platform_delete_tenant_user(
    tenant_id: UUID,
    user_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    from app.services.recycle import soft_delete

    tenant = _platform_tenant_or_404(db, tenant_id)
    user = _platform_user_or_404(db, tenant, user_id)
    admins = _active_tenant_admin_ids(db, tenant.id)
    if user.id in admins and len(admins) <= 1:
        raise HTTPException(409, detail={"code": "LAST_TENANT_ADMIN", "message": "Cannot delete the last active tenant admin"})
    soft_delete(
        db,
        tenant_id=tenant.id,
        user_id=auth.user_id,
        entity_type="user",
        row=user,
        title=user.email,
    )
    audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=auth.user_id,
        action="platform.user_deleted",
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email},
    )
    db.commit()
    return {"ok": True, "recycled": True}


class PlatformPasswordResetIn(BaseModel):
    # omitted → server generates a temp password (returned once + emailed)
    password: str | None = Field(default=None, min_length=8)
    send_email: bool = True


@router.post("/platform/tenants/{tenant_id}/users/{user_id}/reset-password")
def platform_reset_tenant_user_password(
    tenant_id: UUID,
    user_id: UUID,
    body: PlatformPasswordResetIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    """Rotate the account password (invalidates live sessions via password_version)
    and mail the new credential to the account owner."""
    tenant = _platform_tenant_or_404(db, tenant_id)
    user = _platform_user_or_404(db, tenant, user_id)
    password = body.password or _gen_temp_password()
    user.password_hash = hash_password(password)
    user.password_version = (user.password_version or 1) + 1  # kills all existing sessions (pwv check)
    emailed = False
    if body.send_email:
        send_mail(
            db,
            to_email=user.email,
            subject="Your MariOS password has been reset",
            body=(
                f"Hello {user.full_name or user.email},\n\n"
                f"A platform administrator reset the password for your MariOS account ({user.email}), "
                f"tenant \"{tenant.name}\" ({tenant.code}).\n\n"
                f"Temporary password: {password}\n\n"
                "Please sign in and change your password. If you did not expect this change, contact your administrator."
            ),
            purpose="password_reset",
            tenant_id=tenant.id,
            meta={"reset_by": str(auth.user_id)},
        )
        emailed = True
    audit(
        db,
        tenant_id=tenant.id,
        actor_user_id=auth.user_id,
        action="platform.user_password_reset",
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email, "emailed": emailed},
    )
    db.commit()
    return {
        "id": str(user.id),
        "email": user.email,
        "temp_password": password if not body.password else None,
        "emailed": emailed,
        "sessions_invalidated": True,
    }
