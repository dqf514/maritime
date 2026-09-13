"""Identity helpers — tokens, mail, domain policy, OAuth URL builders."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import urllib.parse
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Tenant, User
from app.models_identity import (
    AuthChallenge,
    OutboundMailLog,
    PlatformIdentitySettings,
    TenantAuthPolicy,
)


def now_local() -> datetime:
    return datetime.now().astimezone()


def as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=now_local().tzinfo)
    return dt


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def ensure_platform_identity(db: Session) -> PlatformIdentitySettings:
    row = db.scalar(select(PlatformIdentitySettings).limit(1))
    if not row:
        s = get_settings()
        row = PlatformIdentitySettings(
            oauth_redirect_base=s.api_public_base,
            web_app_base=s.web_public_base,
            email_channel=s.email_channel,
            email_from=s.email_from,
        )
        db.add(row)
        db.flush()
    return row


def ensure_tenant_policy(db: Session, tenant_id: UUID) -> TenantAuthPolicy:
    row = db.scalar(select(TenantAuthPolicy).where(TenantAuthPolicy.tenant_id == tenant_id))
    if not row:
        plat = ensure_platform_identity(db)
        row = TenantAuthPolicy(
            tenant_id=tenant_id,
            require_email_verify=plat.default_require_email_verify,
            invite_only=plat.default_invite_only,
            allowed_domains=list(plat.default_allowed_domains or []),
            microsoft_enabled=plat.microsoft_enabled,
            google_enabled=plat.google_enabled,
            password_enabled=plat.email_password_enabled,
            magic_link_enabled=plat.magic_link_enabled,
        )
        db.add(row)
        db.flush()
    return row


def email_domain(email: str) -> str:
    return email.split("@")[-1].lower().strip()


def domain_allowed(policy: TenantAuthPolicy, email: str) -> bool:
    domains = [d.lower().strip() for d in (policy.allowed_domains or []) if d]
    if not domains:
        return True
    return email_domain(email) in domains


def create_challenge(
    db: Session,
    *,
    purpose: str,
    email: str,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
    hours: float = 24,
    payload: dict | None = None,
) -> tuple[AuthChallenge, str]:
    raw = new_token()
    row = AuthChallenge(
        tenant_id=tenant_id,
        user_id=user_id,
        email=email.lower().strip(),
        purpose=purpose,
        token_hash=hash_token(raw),
        payload=payload or {},
        expires_at=now_local() + timedelta(hours=hours),
    )
    db.add(row)
    db.flush()
    return row, raw


def consume_challenge(db: Session, purpose: str, raw_token: str) -> AuthChallenge | None:
    row = db.scalar(
        select(AuthChallenge).where(
            AuthChallenge.purpose == purpose,
            AuthChallenge.token_hash == hash_token(raw_token),
            AuthChallenge.consumed_at.is_(None),
        )
    )
    if not row:
        return None
    if as_aware(row.expires_at) < now_local():
        return None
    row.consumed_at = now_local()
    db.flush()
    return row


def send_mail(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
    purpose: str,
    tenant_id: UUID | None = None,
    meta: dict | None = None,
) -> OutboundMailLog:
    plat = ensure_platform_identity(db)
    settings = get_settings()
    channel = plat.email_channel or settings.email_channel
    status = "sent"
    send_meta: dict[str, Any] = dict(meta or {})
    # Prefer Graph when channel is graph and tenant has Office link (or stub)
    if channel in {"graph", "m365", "email.graph"} and tenant_id:
        try:
            from app.services import office_hub as office_hub

            client = office_hub.get_graph_client(db, tenant_id)
            out = client.send_mail(to=to_email, subject=subject, body=body)
            send_meta["graph"] = out
            channel = "graph"
        except Exception as exc:  # noqa: BLE001
            status = "fallback_console"
            send_meta["graph_error"] = str(exc)
    log = OutboundMailLog(
        tenant_id=tenant_id,
        to_email=to_email,
        subject=subject,
        purpose=purpose,
        channel=channel,
        status=status,
        body_preview=body[:2000],
        meta=send_meta,
    )
    db.add(log)
    db.flush()
    return log


def provider_runtime(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    ms_ready = bool(s.microsoft_client_id and s.microsoft_client_secret)
    goog_ready = bool(s.google_client_id and s.google_client_secret)
    return {
        "microsoft": {
            "configured": ms_ready,
            "mode": "live" if ms_ready else ("stub" if s.oauth_allow_stub else "disabled"),
            "client_id_set": bool(s.microsoft_client_id),
            "tenant": s.microsoft_tenant,
        },
        "google": {
            "configured": goog_ready,
            "mode": "live" if goog_ready else ("stub" if s.oauth_allow_stub else "disabled"),
            "client_id_set": bool(s.google_client_id),
        },
        "email": {
            "channel": s.email_channel,
            "from": s.email_from,
        },
        "api_public_base": s.api_public_base,
        "web_public_base": s.web_public_base,
        "oauth_allow_stub": s.oauth_allow_stub,
    }


def build_oauth_authorize_url(
    provider: str,
    *,
    state: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    runtime = provider_runtime(s)
    info = runtime.get(provider)
    if not info:
        raise ValueError("unknown_provider")
    redirect_uri = f"{s.api_public_base.rstrip('/')}/api/v1/auth/oauth/{provider}/callback"
    if info["mode"] == "disabled":
        return {"mode": "disabled", "authorize_url": None, "redirect_uri": redirect_uri}
    if info["mode"] == "stub":
        # Demo path — frontend/callback completes with stub_email
        q = urllib.parse.urlencode(
            {
                "state": state,
                "stub": "1",
                "provider": provider,
            }
        )
        return {
            "mode": "stub",
            "authorize_url": f"{s.web_public_base.rstrip('/')}/login/oauth-stub?{q}",
            "redirect_uri": redirect_uri,
        }
    if provider == "microsoft":
        base = f"https://login.microsoftonline.com/{s.microsoft_tenant}/oauth2/v2.0/authorize"
        q = urllib.parse.urlencode(
            {
                "client_id": s.microsoft_client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "response_mode": "query",
                "scope": "openid profile email offline_access User.Read",
                "state": state,
                "code_challenge_method": "S256",  # PKCE ready — code_verifier stored in challenge payload when live
            }
        )
        return {"mode": "live", "authorize_url": f"{base}?{q}", "redirect_uri": redirect_uri}
    if provider == "google":
        base = "https://accounts.google.com/o/oauth2/v2/auth"
        q = urllib.parse.urlencode(
            {
                "client_id": s.google_client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": "openid email profile",
                "state": state,
                "access_type": "offline",
                "prompt": "select_account",
            }
        )
        return {"mode": "live", "authorize_url": f"{base}?{q}", "redirect_uri": redirect_uri}
    raise ValueError("unknown_provider")


def mark_email_verified(user: User) -> None:
    if not user.email_verified_at:
        user.email_verified_at = now_local()


def soft_sign_state(secret: str, payload: str) -> str:
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def public_auth_options(db: Session, tenant: Tenant) -> dict[str, Any]:
    policy = ensure_tenant_policy(db, tenant.id)
    plat = ensure_platform_identity(db)
    runtime = provider_runtime()
    return {
        "tenant_code": tenant.code,
        "tenant_name": tenant.name,
        "password": bool(policy.password_enabled and plat.email_password_enabled),
        "microsoft": bool(policy.microsoft_enabled and plat.microsoft_enabled and runtime["microsoft"]["mode"] != "disabled"),
        "google": bool(policy.google_enabled and plat.google_enabled and runtime["google"]["mode"] != "disabled"),
        "magic_link": bool(policy.magic_link_enabled and plat.magic_link_enabled),
        "require_email_verify": policy.require_email_verify,
        "invite_only": policy.invite_only,
        "allowed_domains": policy.allowed_domains or [],
        "provider_modes": {
            "microsoft": runtime["microsoft"]["mode"],
            "google": runtime["google"]["mode"],
        },
    }
