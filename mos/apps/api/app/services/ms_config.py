"""Resolve Microsoft 365 app credentials per tenant.

Priority: tenant override (ms_override_enabled + ms_client_id set on the
tenant row) > global MICROSOFT_CLIENT_* env config > none. The effective
runtime mode maps to tenant | global | stub | disabled for UI display.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Tenant
from app.services.graph_client import MsConfig
from app.services.ops_crypto import decrypt_secret


def _decrypt(value: str | None) -> str:
    if not value:
        return ""
    try:
        return decrypt_secret(value)
    except ValueError:
        # Key rotated or legacy/bad value — treat as missing rather than 500.
        return ""


def resolve_ms_config(db: Session, tenant_id: UUID, *, settings: Settings | None = None) -> MsConfig:
    s = settings or get_settings()
    tenant = db.get(Tenant, tenant_id)
    if tenant is not None and tenant.ms_override_enabled and (tenant.ms_client_id or "").strip():
        return MsConfig(
            client_id=(tenant.ms_client_id or "").strip(),
            client_secret=_decrypt(tenant.ms_client_secret),
            ms_tenant=(tenant.ms_tenant or "").strip() or "common",
            source="tenant",
        )
    if s.microsoft_client_id:
        return MsConfig(
            client_id=s.microsoft_client_id,
            client_secret=s.microsoft_client_secret or "",
            ms_tenant=s.microsoft_tenant or "common",
            source="global",
        )
    return MsConfig(ms_tenant=s.microsoft_tenant or "common", source="none")


def mask_ms_secret(cipher: str | None) -> str | None:
    """Masked preview for API responses — never returns the plaintext."""
    plain = _decrypt(cipher)
    if not plain:
        return None
    return "••••" + plain[-4:]


def effective_mode(cfg: MsConfig, settings: Settings | None = None) -> str:
    """tenant | global | stub | disabled — live mode reports its config source."""
    s = settings or get_settings()
    if cfg.client_id and cfg.client_secret:
        return cfg.source if cfg.source in ("tenant", "global") else "global"
    return "stub" if s.oauth_allow_stub else "disabled"
