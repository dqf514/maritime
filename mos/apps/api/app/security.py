import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
from fastapi import Cookie, Depends, Header, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ApiKey, Tenant, TenantModuleLicense, User, UserRole, Role

bearer = HTTPBearer(auto_error=False)
settings = get_settings()

# Dual-track browser session: interactive sign-in issues the JWT both in the
# JSON body (backward compatible) and as this HttpOnly cookie.
# CSRF rationale: the cookie is SameSite=Lax, so cross-site POST/PUT/DELETE
# requests do not carry it — only top-level safe navigations do. Combined with
# CORS allow_credentials restricted to explicit origins (see app/main.py), the
# cross-site request forgery surface is considered acceptable and no separate
# CSRF token is required. Non-cookie callers (API keys, Bearer headers) are
# unaffected by browser CSRF by construction.
SESSION_COOKIE_NAME = "marios_token"
# Pre-rebrand cookie name; still accepted so existing browser sessions stay
# valid until their natural expiry.
LEGACY_SESSION_COOKIE_NAME = "voyageos_token"


def session_cookie_max_age() -> int:
    return settings.jwt_expire_minutes * 60


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
        max_age=session_cookie_max_age(),
    )


def clear_session_cookie(response: Response) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        "",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
        max_age=0,
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def create_access_token(*, user_id: UUID, tenant_id: UUID, email: str, pwv: int = 1) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "pwv": pwv,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


class AuthContext:
    def __init__(self, user: User, roles: list[str]):
        self.user = user
        self.roles = roles
        self.tenant_id = user.tenant_id
        self.user_id = user.id


def _auth_from_user(db: Session, user: User) -> AuthContext:
    role_codes = list(
        db.scalars(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        ).all()
    )
    return AuthContext(user=user, roles=role_codes)


def _auth_from_api_key(db: Session, raw_key: str) -> AuthContext:
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.status == "active"))
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if row.expires_at and _as_aware(row.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")
    user: User | None = None
    if row.user_id:
        # Keys are bound to a specific user at creation time
        bound = db.get(User, row.user_id)
        if bound and bound.tenant_id == row.tenant_id and bound.status == "active":
            user = bound
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner inactive")
    else:
        # Legacy keys without owner binding: fall back to earliest active user
        user = db.scalar(
            select(User).where(User.tenant_id == row.tenant_id, User.status == "active").order_by(User.created_at.asc())
        )
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active user for API key tenant")
    ctx = _auth_from_user(db, user)
    ctx.api_key_id = row.id  # type: ignore[attr-defined]
    ctx.api_key_scopes = list(row.scopes or [])  # type: ignore[attr-defined]
    return ctx


def _assert_tenant_active(db: Session, ctx: AuthContext) -> None:
    tenant = db.get(Tenant, ctx.tenant_id)
    if tenant and tenant.status == "suspended" and "platform_admin" not in ctx.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "TENANT_SUSPENDED", "message": "Tenant suspended"},
        )


def _auth_from_jwt(db: Session, token: str) -> AuthContext:
    """Shared JWT verification for Bearer header and HttpOnly cookie tracks:
    signature, tenant binding, user status and password-version (pwv) revocation."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tenant_id"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    user = db.get(User, user_id)
    if not user or user.tenant_id != tenant_id or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    # Password version: tokens issued before a password change are revoked
    token_pwv = payload.get("pwv")
    if token_pwv is None or int(token_pwv) != int(user.password_version or 1):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    ctx = _auth_from_user(db, user)
    _assert_tenant_active(db, ctx)
    return ctx


def get_current_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    legacy_session_cookie: str | None = Cookie(default=None, alias=LEGACY_SESSION_COOKIE_NAME),
) -> AuthContext:
    # Resolution order: X-API-Key, then Authorization Bearer, then session cookie.
    # A present-but-invalid header/API key fails immediately (no cookie fallback),
    # so programmatic callers get deterministic 401s.
    if x_api_key:
        ctx = _auth_from_api_key(db, x_api_key)
        _assert_tenant_active(db, ctx)
        return ctx
    if creds is not None:
        return _auth_from_jwt(db, creds.credentials)
    token = session_cookie or legacy_session_cookie
    if token:
        return _auth_from_jwt(db, token)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


require_auth = get_current_auth


def get_current_auth_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    legacy_session_cookie: str | None = Cookie(default=None, alias=LEGACY_SESSION_COOKIE_NAME),
) -> AuthContext | None:
    if creds is None and not x_api_key and not session_cookie and not legacy_session_cookie:
        return None
    try:
        return get_current_auth(
            creds=creds,
            db=db,
            x_api_key=x_api_key,
            session_cookie=session_cookie,
            legacy_session_cookie=legacy_session_cookie,
        )
    except HTTPException:
        return None


def require_api_scope(*required: str):
    """Scope check for API-key callers. JWT (interactive) auth passes through —
    user-level authorization is handled by role/module checks."""

    def _dep(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        scopes = getattr(auth, "api_key_scopes", None)
        if scopes is None:
            return auth
        if not any(s in scopes or "*" in scopes for s in required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "SCOPE_REQUIRED", "scopes": list(required)},
            )
        return auth

    return _dep


def require_module(module_code: str):
    def _dep(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)) -> AuthContext:
        if settings.license_dev_unlock == "all":
            return auth
        lic = db.scalar(
            select(TenantModuleLicense).where(
                TenantModuleLicense.tenant_id == auth.tenant_id,
                TenantModuleLicense.module_code == module_code,
                TenantModuleLicense.status.in_(["active", "grace"]),
            )
        )
        if lic and lic.expires_at and _as_aware(lic.expires_at) < datetime.now(timezone.utc):
            lic = None
        if not lic:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "MODULE_NOT_LICENSED", "module": module_code},
            )
        return auth

    return _dep


def require_feature(feature_code: str):
    """Enforce tenant feature permission matrix (see /admin/permissions)."""

    def _dep(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)) -> AuthContext:
        from app.services.saas_engine import assert_feature

        assert_feature(db, auth.tenant_id, auth.roles, feature_code)
        return auth

    return _dep


def error_body(code: str, message: str, details: list[Any] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or []}}
