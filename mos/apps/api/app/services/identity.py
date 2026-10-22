"""Identity helpers — tokens, mail, domain policy, OAuth URL builders."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import urllib.parse
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from jose import JWTError, jwt as jose_jwt
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
from app.services.graph_client import MsConfig
from app.services.ms_config import resolve_ms_config


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


def _redact_body_preview(body: str) -> str:
    """Strip challenge tokens from stored mail previews (defense in depth:
    the log must never persist a usable invite / verify / magic-link token)."""
    preview = re.sub(r"(token=)[^&\s]+", r"\1***", body)
    preview = re.sub(r"(?i)(demo token:\s*)\S+", r"\1***", preview)
    return preview[:2000]


def send_mail(
    db: Session,
    *,
    to_email: str,
    subject: str,
    body: str,
    purpose: str,
    tenant_id: UUID | None = None,
    meta: dict | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> OutboundMailLog:
    """Send (or log) an outbound mail.

    ``attachments`` items: ``{filename, content_type, content_b64 | content(bytes)}``.
    Attachment bytes are never persisted in the mail log — only filename/size meta.
    """
    plat = ensure_platform_identity(db)
    settings = get_settings()
    channel = plat.email_channel or settings.email_channel
    status = "sent"
    send_meta: dict[str, Any] = dict(meta or {})
    atts = list(attachments or [])
    if atts:
        send_meta["attachments"] = [
            {"filename": a.get("filename"), "size": a.get("size") or len(a.get("content") or b"")}
            for a in atts
        ]
    # Prefer Graph when channel is graph and tenant has Office link (or stub)
    if channel in {"graph", "m365", "email.graph"} and tenant_id:
        try:
            from app.services import office_hub as office_hub

            client = office_hub.get_graph_client(db, tenant_id)
            out = client.send_mail(to=to_email, subject=subject, body=body, attachments=atts)
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
        body_preview=_redact_body_preview(body),
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


def tenant_provider_runtime(db: Session, tenant_id: UUID, settings: Settings | None = None) -> dict[str, Any]:
    """Like provider_runtime(), but Microsoft mode is tenant-aware.

    A tenant with its own M365 app override (ms_override_enabled + ms_client_id)
    runs live even when the global MICROSOFT_CLIENT_* env is unset.
    """
    s = settings or get_settings()
    runtime = provider_runtime(s)
    cfg = resolve_ms_config(db, tenant_id, settings=s)
    ms_live = bool(cfg.client_id and cfg.client_secret)
    runtime["microsoft"] = {
        "configured": ms_live,
        "mode": "live" if ms_live else ("stub" if s.oauth_allow_stub else "disabled"),
        "client_id_set": bool(cfg.client_id),
        "tenant": cfg.ms_tenant,
        "source": cfg.source,
    }
    return runtime


class OAuthExchangeError(Exception):
    """Authorization-code exchange failed; ``code`` surfaces as ?oauth_error= on login redirect."""

    def __init__(self, code: str, *, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status


def exchange_login_code(
    db: Session,
    provider: str,
    code: str,
    *,
    tenant_id: UUID,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Exchange the IdP authorization code for identity claims (live login path).

    Microsoft credentials come from resolve_ms_config (tenant override > global
    env). The redirect_uri must exactly match the one used at /start. The
    id_token is delivered over TLS on the back channel with client-secret
    authentication, so we validate aud rather than the signature (OIDC core
    3.1.3.7 — signature checks apply to front-channel id_tokens).
    """
    s = settings or get_settings()
    redirect_uri = f"{s.api_public_base.rstrip('/')}/api/v1/auth/oauth/{provider}/callback"
    if provider == "microsoft":
        cfg = resolve_ms_config(db, tenant_id, settings=s)
        if not (cfg.client_id and cfg.client_secret):
            raise OAuthExchangeError("oauth_not_configured")
        token_url = f"https://login.microsoftonline.com/{cfg.ms_tenant or 'common'}/oauth2/v2.0/token"
        client_id, client_secret = cfg.client_id, cfg.client_secret
    elif provider == "google":
        client_id, client_secret = s.google_client_id or "", s.google_client_secret or ""
        if not (client_id and client_secret):
            raise OAuthExchangeError("oauth_not_configured")
        token_url = "https://oauth2.googleapis.com/token"
    else:
        raise OAuthExchangeError("unsupported_provider")

    form = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        res = httpx.post(token_url, data=form, timeout=20.0)
    except httpx.HTTPError as exc:
        raise OAuthExchangeError("token_endpoint_unreachable") from exc
    if res.status_code >= 400:
        raise OAuthExchangeError("token_exchange_failed", status=res.status_code)
    payload = res.json()
    id_token = (payload or {}).get("id_token") or ""
    if not id_token:
        raise OAuthExchangeError("missing_id_token")
    try:
        claims = jose_jwt.get_unverified_claims(id_token)
    except JWTError as exc:
        raise OAuthExchangeError("invalid_id_token") from exc
    if claims.get("aud") != client_id:
        raise OAuthExchangeError("invalid_id_token")
    email = (claims.get("preferred_username") or claims.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise OAuthExchangeError("identity_missing_email")
    return {
        "email": email,
        "full_name": (claims.get("name") or "").strip() or None,
        "subject": str(claims.get("oid") or claims.get("sub") or email),
    }


def build_oauth_authorize_url(
    provider: str,
    *,
    state: str,
    settings: Settings | None = None,
    microsoft_tenant: str | None = None,
    google_hosted_domain: str | None = None,
    ms_config: MsConfig | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    runtime = provider_runtime(s)
    info = runtime.get(provider)
    if provider == "microsoft" and ms_config is not None:
        # Tenant-resolved credentials override the global env view.
        ms_live = bool(ms_config.client_id and ms_config.client_secret)
        info = {
            "configured": ms_live,
            "mode": "live" if ms_live else ("stub" if s.oauth_allow_stub else "disabled"),
            "client_id_set": bool(ms_config.client_id),
            "tenant": ms_config.ms_tenant,
        }
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
        client_id = (ms_config.client_id if ms_config else s.microsoft_client_id) or ""
        default_seg = (ms_config.ms_tenant if ms_config else s.microsoft_tenant) or "common"
        tenant_seg = (microsoft_tenant or default_seg or "common").strip() or "common"
        base = f"https://login.microsoftonline.com/{tenant_seg}/oauth2/v2.0/authorize"
        q = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "response_mode": "query",
                "scope": "openid profile email offline_access User.Read",
                "state": state,
            }
        )
        return {"mode": "live", "authorize_url": f"{base}?{q}", "redirect_uri": redirect_uri, "microsoft_tenant": tenant_seg}
    if provider == "google":
        base = "https://accounts.google.com/o/oauth2/v2/auth"
        params: dict[str, str] = {
            "client_id": s.google_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        if google_hosted_domain:
            params["hd"] = google_hosted_domain.strip()
        q = urllib.parse.urlencode(params)
        return {"mode": "live", "authorize_url": f"{base}?{q}", "redirect_uri": redirect_uri}
    raise ValueError("unknown_provider")


def mark_email_verified(user: User) -> None:
    if not user.email_verified_at:
        user.email_verified_at = now_local()


def soft_sign_state(secret: str, payload: str) -> str:
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_signed_state(secret: str, state: str) -> str | None:
    """Return the payload when the HMAC signature matches, else None."""
    payload, sep, sig = state.rpartition(".")
    if not sep or not payload or not sig:
        return None
    expect = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    return payload


def public_auth_options(db: Session, tenant: Tenant) -> dict[str, Any]:
    policy = ensure_tenant_policy(db, tenant.id)
    plat = ensure_platform_identity(db)
    runtime = tenant_provider_runtime(db, tenant.id)
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
