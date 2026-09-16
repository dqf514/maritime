"""Identity APIs: OAuth, email verify, invites, platform/tenant/user security."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Role, Tenant, User, UserRole
from app.models_identity import OutboundMailLog, PlatformIdentitySettings, TenantAuthPolicy, UserIdentity
from app.security import (
    AuthContext,
    clear_session_cookie,
    create_access_token,
    get_current_auth,
    get_current_auth_optional,
    hash_password,
    require_auth,
    set_session_cookie,
    verify_password,
)
from app.services.audit import audit
from app.services.identity import (
    build_oauth_authorize_url,
    consume_challenge,
    create_challenge,
    domain_allowed,
    ensure_platform_identity,
    ensure_tenant_policy,
    mark_email_verified,
    now_local,
    as_aware,
    provider_runtime,
    public_auth_options,
    send_mail,
)
from app.services.ratelimit import rate_limit

router = APIRouter(tags=["Identity"])


def require_roles(*codes: str):
    def _dep(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if not any(c in auth.roles for c in codes):
            raise HTTPException(status_code=403, detail={"code": "ROLE_REQUIRED", "roles": list(codes)})
        return auth

    return _dep


# —— Schemas ——
class PlatformIdentityOut(BaseModel):
    microsoft_enabled: bool
    google_enabled: bool
    email_password_enabled: bool
    magic_link_enabled: bool
    oauth_redirect_base: str | None
    web_app_base: str | None
    email_channel: str
    email_from: str
    email_from_name: str
    default_require_email_verify: bool
    default_invite_only: bool
    default_allowed_domains: list
    notes: str | None = None
    runtime: dict[str, Any]


class PlatformIdentityIn(BaseModel):
    microsoft_enabled: bool | None = None
    google_enabled: bool | None = None
    email_password_enabled: bool | None = None
    magic_link_enabled: bool | None = None
    oauth_redirect_base: str | None = None
    web_app_base: str | None = None
    email_channel: str | None = None
    email_from: str | None = None
    email_from_name: str | None = None
    default_require_email_verify: bool | None = None
    default_invite_only: bool | None = None
    default_allowed_domains: list | None = None
    notes: str | None = None


class TenantPolicyIn(BaseModel):
    password_enabled: bool | None = None
    microsoft_enabled: bool | None = None
    google_enabled: bool | None = None
    magic_link_enabled: bool | None = None
    require_email_verify: bool | None = None
    invite_only: bool | None = None
    allowed_domains: list[str] | None = None
    session_hours: int | None = None
    microsoft_tenant_hint: str | None = None
    google_hosted_domain: str | None = None
    sso_notes: str | None = None


class InviteIn(BaseModel):
    email: EmailStr
    full_name: str | None = None
    role_codes: list[str] = Field(default_factory=lambda: ["viewer"])


class InviteAcceptIn(BaseModel):
    token: str
    password: str = Field(min_length=8)
    full_name: str | None = None


class VerifyRequestIn(BaseModel):
    email: EmailStr | None = None
    tenant_code: str | None = None


class VerifyConfirmIn(BaseModel):
    token: str


class MagicLinkRequestIn(BaseModel):
    email: EmailStr
    tenant_code: str


class MagicLinkConfirmIn(BaseModel):
    token: str


class OAuthStartIn(BaseModel):
    tenant_code: str
    provider: str  # microsoft|google
    intent: str = "login"  # login|link


class StubOAuthCompleteIn(BaseModel):
    state: str
    email: EmailStr
    full_name: str | None = None
    subject: str | None = None


class PasswordChangeIn(BaseModel):
    current_password: str | None = None
    new_password: str = Field(min_length=8)


def _policy_out(p: TenantAuthPolicy) -> dict:
    return {
        "password_enabled": p.password_enabled,
        "microsoft_enabled": p.microsoft_enabled,
        "google_enabled": p.google_enabled,
        "magic_link_enabled": p.magic_link_enabled,
        "require_email_verify": p.require_email_verify,
        "invite_only": p.invite_only,
        "allowed_domains": p.allowed_domains or [],
        "session_hours": p.session_hours,
        "microsoft_tenant_hint": p.microsoft_tenant_hint,
        "google_hosted_domain": p.google_hosted_domain,
        "sso_notes": p.sso_notes,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _issue_token(user: User, response: Response, db: Session, via: str) -> dict:
    user.last_login_at = now_local()
    token = create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, email=user.email, pwv=user.password_version or 1
    )
    # Callers commit before invoking us, so persist the audit row (and the
    # last_login_at touch above) in its own transaction.
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="auth.token_issued",
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email, "via": via},
        commit=True,
    )
    # Token goes out both ways: JSON body (backward compatible) + HttpOnly cookie
    set_session_cookie(response, token)
    return {"access_token": token, "token_type": "bearer"}


def _check_verified_or_raise(user: User, policy: TenantAuthPolicy) -> None:
    if policy.require_email_verify and not user.email_verified_at:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "EMAIL_NOT_VERIFIED",
                "message": "Email verification required before sign-in",
            },
        )


# —— Public: login methods for a tenant ——
@router.get("/auth/methods")
def auth_methods(tenant_code: str = "demo", db: Session = Depends(get_db)):
    tenant = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
    if not tenant or tenant.status == "suspended":
        raise HTTPException(404, "Tenant not found")
    return public_auth_options(db, tenant)


# —— Platform admin: IdP & mail channel ——
@router.get("/platform/identity")
def platform_identity_get(
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = ensure_platform_identity(db)
    db.commit()
    return {
        **PlatformIdentityOut(
            microsoft_enabled=row.microsoft_enabled,
            google_enabled=row.google_enabled,
            email_password_enabled=row.email_password_enabled,
            magic_link_enabled=row.magic_link_enabled,
            oauth_redirect_base=row.oauth_redirect_base,
            web_app_base=row.web_app_base,
            email_channel=row.email_channel,
            email_from=row.email_from,
            email_from_name=row.email_from_name,
            default_require_email_verify=row.default_require_email_verify,
            default_invite_only=row.default_invite_only,
            default_allowed_domains=row.default_allowed_domains or [],
            notes=row.notes,
            runtime=provider_runtime(),
        ).model_dump(),
        "secret_guidance": {
            "microsoft": "设置环境变量 MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET / MICROSOFT_TENANT",
            "google": "设置环境变量 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET",
            "email": "发件人与通道可在本页保存；SMTP 还需 SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD；SendGrid 用 SENDGRID_API_KEY",
            "smtp": "EMAIL_CHANNEL=smtp 时读取 SMTP_* 环境变量（密钥不下发到浏览器）",
        },
    }


@router.put("/platform/identity")
def platform_identity_put(
    body: PlatformIdentityIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = ensure_platform_identity(db)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = now_local()
    db.commit()
    return platform_identity_get(auth, db)


@router.get("/platform/identity/mail-logs")
def platform_mail_logs(
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    rows = db.scalars(select(OutboundMailLog).order_by(OutboundMailLog.created_at.desc()).limit(50)).all()
    return [
        {
            "id": str(r.id),
            "to_email": r.to_email,
            "subject": r.subject,
            "purpose": r.purpose,
            "channel": r.channel,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "body_preview": r.body_preview,
        }
        for r in rows
    ]


# —— Tenant admin: security policy & invites ——
@router.get("/admin/security/policy")
def get_tenant_policy(
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    p = ensure_tenant_policy(db, auth.tenant_id)
    plat = ensure_platform_identity(db)
    db.commit()
    return {
        **_policy_out(p),
        "platform_gates": {
            "microsoft": plat.microsoft_enabled,
            "google": plat.google_enabled,
            "password": plat.email_password_enabled,
            "magic_link": plat.magic_link_enabled,
        },
        "runtime": provider_runtime(),
    }


@router.put("/admin/security/policy")
def put_tenant_policy(
    body: TenantPolicyIn,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    p = ensure_tenant_policy(db, auth.tenant_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    p.updated_at = now_local()
    db.commit()
    return _policy_out(p)


@router.post("/admin/security/invites")
def create_invite(
    body: InviteIn,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
    _rl: None = Depends(rate_limit("auth.invite")),
):
    policy = ensure_tenant_policy(db, auth.tenant_id)
    email = body.email.lower().strip()
    if not domain_allowed(policy, email):
        raise HTTPException(400, detail={"code": "DOMAIN_NOT_ALLOWED", "message": "Email domain not allowed"})
    existing = db.scalar(select(User).where(User.tenant_id == auth.tenant_id, User.email == email))
    if existing and existing.status == "active" and existing.password_hash:
        raise HTTPException(409, "User already exists")

    role_codes = [c for c in body.role_codes if c != "platform_admin"]
    challenge, raw = create_challenge(
        db,
        purpose="invite",
        email=email,
        tenant_id=auth.tenant_id,
        hours=72,
        payload={"role_codes": role_codes, "full_name": body.full_name},
    )
    settings = get_settings()
    link = f"{settings.web_public_base.rstrip('/')}/login/accept-invite?token={raw}"
    send_mail(
        db,
        to_email=email,
        subject="You're invited to MariOS",
        body=f"Accept your invite:\n{link}",
        purpose="invite",
        tenant_id=auth.tenant_id,
        meta={"challenge_id": str(challenge.id)},
    )
    # Pending user shell (no password yet)
    if not existing:
        user = User(
            tenant_id=auth.tenant_id,
            email=email,
            full_name=body.full_name,
            status="invited",
            password_hash=None,
        )
        db.add(user)
        db.flush()
        for code in role_codes:
            role = db.scalar(select(Role).where(Role.tenant_id == auth.tenant_id, Role.code == code))
            if role:
                db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()
    return {"ok": True, "email": email, "expires_at": challenge.expires_at.isoformat()}


@router.get("/admin/security/invites")
def list_pending_invites(
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    from app.models_identity import AuthChallenge

    rows = db.scalars(
        select(AuthChallenge).where(
            AuthChallenge.tenant_id == auth.tenant_id,
            AuthChallenge.purpose == "invite",
            AuthChallenge.consumed_at.is_(None),
        )
    ).all()
    return [
        {
            "email": r.email,
            "expires_at": r.expires_at.isoformat(),
            "payload": r.payload,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/admin/security/mail-logs")
def tenant_mail_logs(
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(OutboundMailLog)
        .where(OutboundMailLog.tenant_id == auth.tenant_id)
        .order_by(OutboundMailLog.created_at.desc())
        .limit(40)
    ).all()
    return [
        {
            "id": str(r.id),
            "to_email": r.to_email,
            "subject": r.subject,
            "purpose": r.purpose,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "body_preview": r.body_preview,
        }
        for r in rows
    ]


# —— Tenant admin: security audit trail ——
@router.get("/admin/security/audit-logs")
def list_audit_logs(
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
    action: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Tenant-scoped audit trail, newest first. tenant_admin only."""
    from app.models_audit import AuditLog

    stmt = select(AuditLog).where(AuditLog.tenant_id == auth.tenant_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = len(db.scalars(stmt).all())
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": str(r.id),
                "tenant_id": str(r.tenant_id) if r.tenant_id else None,
                "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "detail": r.detail or {},
                "ip": r.ip,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# —— Auth: accept invite / verify / magic / oauth ——
@router.post("/auth/invites/accept")
def accept_invite(body: InviteAcceptIn, response: Response, db: Session = Depends(get_db)):
    ch = consume_challenge(db, "invite", body.token)
    if not ch or not ch.tenant_id:
        raise HTTPException(400, "Invalid or expired invite")
    user = db.scalar(select(User).where(User.tenant_id == ch.tenant_id, User.email == ch.email))
    if not user:
        user = User(tenant_id=ch.tenant_id, email=ch.email, status="active")
        db.add(user)
        db.flush()
        for code in ch.payload.get("role_codes") or ["viewer"]:
            role = db.scalar(select(Role).where(Role.tenant_id == ch.tenant_id, Role.code == code))
            if role:
                db.add(UserRole(user_id=user.id, role_id=role.id))
    user.password_hash = hash_password(body.password)
    user.password_version = (user.password_version or 1) + 1
    user.full_name = body.full_name or ch.payload.get("full_name") or user.full_name
    user.status = "active"
    mark_email_verified(user)
    db.commit()
    return _issue_token(user, response, db, via="invite_accept")


@router.post("/auth/email/verify/request")
def request_email_verify(
    body: VerifyRequestIn,
    db: Session = Depends(get_db),
    auth: AuthContext | None = Depends(get_current_auth_optional),
    _rl: None = Depends(rate_limit("auth.email_verify")),
):
    user = None
    tenant_id = None
    if auth:
        user = auth.user
        tenant_id = auth.tenant_id
        email = user.email
    else:
        if not body.email or not body.tenant_code:
            raise HTTPException(400, "email and tenant_code required")
        tenant = db.scalar(select(Tenant).where(Tenant.code == body.tenant_code))
        if not tenant:
            raise HTTPException(404, "Tenant not found")
        user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == body.email.lower()))
        if not user:
            return {"ok": True, "message": "If the account exists, a verification email was sent"}
        tenant_id = tenant.id
        email = user.email

    if user.email_verified_at:
        return {"ok": True, "message": "Already verified"}

    challenge, raw = create_challenge(
        db, purpose="email_verify", email=email, tenant_id=tenant_id, user_id=user.id, hours=24
    )
    settings = get_settings()
    link = f"{settings.web_public_base.rstrip('/')}/login/verify-email?token={raw}"
    send_mail(
        db,
        to_email=email,
        subject="Verify your MariOS email",
        body=f"Verify email:\n{link}",
        purpose="email_verify",
        tenant_id=tenant_id,
        meta={"challenge_id": str(challenge.id)},
    )
    db.commit()
    return {"ok": True}


@router.post("/auth/email/verify/confirm")
def confirm_email_verify(body: VerifyConfirmIn, db: Session = Depends(get_db)):
    ch = consume_challenge(db, "email_verify", body.token)
    if not ch or not ch.user_id:
        raise HTTPException(400, "Invalid or expired token")
    user = db.get(User, ch.user_id)
    if not user:
        raise HTTPException(400, "User not found")
    mark_email_verified(user)
    db.commit()
    return {"ok": True, "email": user.email, "verified_at": user.email_verified_at.isoformat()}


@router.post("/auth/magic-link/request")
def magic_link_request(
    body: MagicLinkRequestIn,
    db: Session = Depends(get_db),
    _rl: None = Depends(rate_limit("auth.magic_link")),
):
    tenant = db.scalar(select(Tenant).where(Tenant.code == body.tenant_code))
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    policy = ensure_tenant_policy(db, tenant.id)
    plat = ensure_platform_identity(db)
    if not (policy.magic_link_enabled and plat.magic_link_enabled):
        raise HTTPException(403, "Magic link disabled")
    email = body.email.lower().strip()
    if not domain_allowed(policy, email):
        raise HTTPException(400, detail={"code": "DOMAIN_NOT_ALLOWED"})
    user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
    if not user:
        return {"ok": True, "message": "If the account exists, a sign-in link was sent"}
    challenge, raw = create_challenge(
        db, purpose="magic_link", email=email, tenant_id=tenant.id, user_id=user.id, hours=1
    )
    settings = get_settings()
    link = f"{settings.web_public_base.rstrip('/')}/login/magic?token={raw}"
    send_mail(
        db,
        to_email=email,
        subject="Your MariOS sign-in link",
        body=f"Sign in:\n{link}",
        purpose="magic_link",
        tenant_id=tenant.id,
        meta={"challenge_id": str(challenge.id)},
    )
    db.commit()
    return {"ok": True}


@router.post("/auth/magic-link/confirm")
def magic_link_confirm(body: MagicLinkConfirmIn, response: Response, db: Session = Depends(get_db)):
    ch = consume_challenge(db, "magic_link", body.token)
    if not ch or not ch.user_id:
        raise HTTPException(400, "Invalid or expired link")
    user = db.get(User, ch.user_id)
    if not user or user.status != "active":
        raise HTTPException(403, "User inactive")
    policy = ensure_tenant_policy(db, user.tenant_id)
    _check_verified_or_raise(user, policy)
    mark_email_verified(user)
    db.commit()
    return _issue_token(user, response, db, via="magic_link")


@router.post("/auth/oauth/{provider}/start")
def oauth_start(provider: str, body: OAuthStartIn, db: Session = Depends(get_db)):
    if provider not in ("microsoft", "google"):
        raise HTTPException(400, "Unsupported provider")
    tenant = db.scalar(select(Tenant).where(Tenant.code == body.tenant_code))
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    policy = ensure_tenant_policy(db, tenant.id)
    plat = ensure_platform_identity(db)
    enabled = (
        (provider == "microsoft" and policy.microsoft_enabled and plat.microsoft_enabled)
        or (provider == "google" and policy.google_enabled and plat.google_enabled)
    )
    if not enabled:
        raise HTTPException(403, f"{provider} sign-in disabled for this tenant")

    challenge, raw_state = create_challenge(
        db,
        purpose="oauth_state",
        email=f"oauth@{tenant.code}.local",
        tenant_id=tenant.id,
        hours=0.25,
        payload={"provider": provider, "tenant_code": tenant.code, "intent": body.intent},
    )
    built = build_oauth_authorize_url(
        provider,
        state=raw_state,
        microsoft_tenant=policy.microsoft_tenant_hint,
        google_hosted_domain=policy.google_hosted_domain,
    )
    db.commit()
    return {
        "provider": provider,
        "mode": built["mode"],
        "authorize_url": built["authorize_url"],
        "redirect_uri": built["redirect_uri"],
        "state": raw_state,
        "challenge_id": str(challenge.id),
    }


@router.get("/auth/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    state: str = "",
    code: str | None = None,
    error: str | None = None,
    stub_email: str | None = None,
    db: Session = Depends(get_db),
):
    """Live IdP returns here with ?code=. Stub flow uses /auth/oauth/stub/complete instead."""
    from app.models_identity import AuthChallenge
    from app.services.identity import hash_token

    settings = get_settings()
    web = settings.web_public_base.rstrip("/")
    if error:
        return RedirectResponse(f"{web}/login?oauth_error={error}")

    pending = db.scalar(
        select(AuthChallenge).where(
            AuthChallenge.purpose == "oauth_state",
            AuthChallenge.token_hash == hash_token(state),
            AuthChallenge.consumed_at.is_(None),
        )
    )
    if not pending or not pending.tenant_id:
        return RedirectResponse(f"{web}/login?oauth_error=invalid_state")
    if as_aware(pending.expires_at) < now_local():
        return RedirectResponse(f"{web}/login?oauth_error=expired_state")

    email = stub_email
    subject = None
    full_name = None
    if code and provider_runtime().get(provider, {}).get("mode") == "live":
        # Reserved: exchange authorization code with Microsoft/Google token endpoint.
        email = email or f"oauth-user@{provider}.invalid"
        subject = f"{provider}:{code[:12]}"

    if not email:
        # Keep state unconsumed — stub UI will complete
        return RedirectResponse(f"{web}/login/oauth-stub?state={state}&provider={provider}")

    ch = consume_challenge(db, "oauth_state", state)
    if not ch or not ch.tenant_id:
        return RedirectResponse(f"{web}/login?oauth_error=invalid_state")

    email = email.lower().strip()
    policy = ensure_tenant_policy(db, ch.tenant_id)
    if not domain_allowed(policy, email):
        return RedirectResponse(f"{web}/login?oauth_error=domain_not_allowed")

    user = db.scalar(select(User).where(User.tenant_id == ch.tenant_id, User.email == email))
    if not user:
        if policy.invite_only:
            return RedirectResponse(f"{web}/login?oauth_error=invite_only")
        user = User(
            tenant_id=ch.tenant_id,
            email=email,
            full_name=full_name or email.split("@")[0],
            status="active",
            password_hash=None,
        )
        mark_email_verified(user)
        db.add(user)
        db.flush()
        role = db.scalar(select(Role).where(Role.tenant_id == ch.tenant_id, Role.code == "viewer"))
        if role:
            db.add(UserRole(user_id=user.id, role_id=role.id))
    else:
        mark_email_verified(user)
        user.status = "active"

    sub = subject or f"{provider}:{email}"
    ident = db.scalar(select(UserIdentity).where(UserIdentity.user_id == user.id, UserIdentity.provider == provider))
    if not ident:
        db.add(
            UserIdentity(
                tenant_id=ch.tenant_id,
                user_id=user.id,
                provider=provider,
                subject=sub,
                email=email,
                profile={"via": "oauth_callback"},
                last_login_at=now_local(),
            )
        )
    else:
        ident.last_login_at = now_local()
    try:
        _check_verified_or_raise(user, policy)
    except HTTPException:
        return RedirectResponse(f"{web}/login?oauth_error=email_not_verified")
    db.commit()
    # Token issued on the redirect path (not via _issue_token) — audit it here
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        action="auth.token_issued",
        entity_type="user",
        entity_id=user.id,
        detail={"email": user.email, "via": f"oauth_{provider}"},
        commit=True,
    )
    token = create_access_token(
        user_id=user.id, tenant_id=user.tenant_id, email=user.email, pwv=user.password_version or 1
    )
    # Cookie is set on the redirect itself (top-level navigation, stored natively).
    # The ?token= query is kept for backward compatibility but is deprecated —
    # the frontend no longer persists it.
    redirect = RedirectResponse(f"{web}/login/oauth-done?token={token}")
    set_session_cookie(redirect, token)
    return redirect


@router.post("/auth/oauth/stub/complete")
def oauth_stub_complete(body: StubOAuthCompleteIn, response: Response, db: Session = Depends(get_db)):
    """Dev/demo completion when Microsoft/Google secrets are not configured."""
    if not get_settings().oauth_allow_stub:
        raise HTTPException(403, "Stub OAuth disabled")
    ch = consume_challenge(db, "oauth_state", body.state)
    if not ch or not ch.tenant_id:
        raise HTTPException(400, "Invalid state")
    provider = ch.payload.get("provider") or "microsoft"
    email = body.email.lower().strip()
    policy = ensure_tenant_policy(db, ch.tenant_id)
    if not domain_allowed(policy, email):
        raise HTTPException(400, detail={"code": "DOMAIN_NOT_ALLOWED"})
    user = db.scalar(select(User).where(User.tenant_id == ch.tenant_id, User.email == email))
    if not user:
        if policy.invite_only:
            raise HTTPException(403, detail={"code": "INVITE_ONLY"})
        user = User(
            tenant_id=ch.tenant_id,
            email=email,
            full_name=body.full_name or email.split("@")[0],
            status="active",
        )
        db.add(user)
        db.flush()
        role = db.scalar(select(Role).where(Role.tenant_id == ch.tenant_id, Role.code == "viewer"))
        if role:
            db.add(UserRole(user_id=user.id, role_id=role.id))
    mark_email_verified(user)
    user.status = "active"
    sub = body.subject or f"stub:{provider}:{email}"
    ident = db.scalar(
        select(UserIdentity).where(UserIdentity.user_id == user.id, UserIdentity.provider == provider)
    )
    if not ident:
        db.add(
            UserIdentity(
                tenant_id=ch.tenant_id,
                user_id=user.id,
                provider=provider,
                subject=sub,
                email=email,
                profile={"mode": "stub"},
                last_login_at=now_local(),
            )
        )
    _check_verified_or_raise(user, policy)
    db.commit()
    return _issue_token(user, response, db, via="oauth_stub")


# —— Sign-out ——
@router.post("/auth/logout")
def logout(response: Response):
    # No server-side revocation needed here: token invalidation after password
    # change / admin action is already enforced via the password_version (pwv)
    # claim checked on every request. Logout just drops the browser cookie;
    # the (unreadable to JS) cookie is the only thing being discarded.
    clear_session_cookie(response)
    return {"ok": True}


# —— User account security ——
@router.get("/me/security")
def me_security(auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    policy = ensure_tenant_policy(db, auth.tenant_id)
    idents = db.scalars(select(UserIdentity).where(UserIdentity.user_id == auth.user_id)).all()
    return {
        "email": auth.user.email,
        "email_verified": bool(auth.user.email_verified_at),
        "email_verified_at": auth.user.email_verified_at.isoformat() if auth.user.email_verified_at else None,
        "has_password": bool(auth.user.password_hash),
        "last_login_at": auth.user.last_login_at.isoformat() if auth.user.last_login_at else None,
        "policy": _policy_out(policy),
        "identities": [
            {
                "provider": i.provider,
                "email": i.email,
                "linked_at": i.linked_at.isoformat() if i.linked_at else None,
                "last_login_at": i.last_login_at.isoformat() if i.last_login_at else None,
            }
            for i in idents
        ],
    }


@router.post("/me/security/password")
def change_password(
    body: PasswordChangeIn,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    user = db.get(User, auth.user_id)
    assert user
    if user.password_hash:
        if not body.current_password or not verify_password(body.current_password, user.password_hash):
            # commit=True: the 400 below would roll the audit row back
            audit(
                db,
                tenant_id=auth.tenant_id,
                actor_user_id=auth.user_id,
                action="auth.password_change_failed",
                entity_type="user",
                entity_id=user.id,
                detail={"reason": "bad_current_password"},
                commit=True,
            )
            raise HTTPException(400, "Current password incorrect")
    user.password_hash = hash_password(body.new_password)
    user.password_version = (user.password_version or 1) + 1
    # Audit row commits atomically with the password change itself
    audit(
        db,
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        action="auth.password_changed",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()
    return {"ok": True}


@router.delete("/me/identities/{provider}")
def unlink_identity(
    provider: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    user = db.get(User, auth.user_id)
    assert user
    idents = db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id)).all()
    target = [i for i in idents if i.provider == provider]
    if not target:
        raise HTTPException(404, "Identity not linked")
    if not user.password_hash and len(idents) <= 1:
        raise HTTPException(400, "Cannot unlink last sign-in method — set a password first")
    for i in target:
        db.delete(i)
    db.commit()
    return {"ok": True}
