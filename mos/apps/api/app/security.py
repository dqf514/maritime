import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ApiKey, TenantModuleLicense, User, UserRole, Role

bearer = HTTPBearer(auto_error=False)
settings = get_settings()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(*, user_id: UUID, tenant_id: UUID, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "email": email,
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
    # Prefer a tenant admin user for add-in / partner calls; fall back to any active user
    user = db.scalar(
        select(User).where(User.tenant_id == row.tenant_id, User.status == "active").order_by(User.created_at.asc())
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active user for API key tenant")
    ctx = _auth_from_user(db, user)
    ctx.api_key_id = row.id  # type: ignore[attr-defined]
    ctx.api_key_scopes = list(row.scopes or [])  # type: ignore[attr-defined]
    return ctx


def get_current_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AuthContext:
    if x_api_key:
        return _auth_from_api_key(db, x_api_key)
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tenant_id"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    user = db.get(User, user_id)
    if not user or user.tenant_id != tenant_id or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    return _auth_from_user(db, user)


require_auth = get_current_auth


def get_current_auth_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AuthContext | None:
    if creds is None and not x_api_key:
        return None
    try:
        return get_current_auth(creds=creds, db=db, x_api_key=x_api_key)
    except HTTPException:
        return None


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
        if not lic:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "MODULE_NOT_LICENSED", "module": module_code},
            )
        return auth

    return _dep


def error_body(code: str, message: str, details: list[Any] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or []}}
