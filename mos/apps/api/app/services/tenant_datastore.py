"""Tenant datastore resolver — architecture hook for future per-tenant engines.

Runtime still uses the primary SessionLocal / engine. Bindings are stored and
validated so operators can configure local / server / cloud targets safely.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models_ops import TenantDatastoreBinding
from app.services.ops_crypto import decrypt_secret


@dataclass
class DatastoreTarget:
    tenant_id: UUID
    binding_id: UUID | None
    engine: str
    host_mode: str
    routing_policy: str
    status: str
    connection_hint: str
    # When True, callers should use primary; dedicated engines not yet switched
    use_primary: bool = True
    notes: str = "运行时仍使用主库；租户绑定已登记，待启用独立引擎路由。"


class TenantDatastoreResolver:
    """Resolve which datastore a tenant *would* use.

    Phase 1: always return primary session; expose binding metadata for ops UI.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_binding(
        self, tenant_id: UUID, purpose: str = "primary"
    ) -> TenantDatastoreBinding | None:
        return self.db.scalar(
            select(TenantDatastoreBinding).where(
                TenantDatastoreBinding.tenant_id == tenant_id,
                TenantDatastoreBinding.purpose == purpose,
            )
        )

    def resolve(self, tenant_id: UUID, purpose: str = "primary") -> DatastoreTarget:
        row = self.get_binding(tenant_id, purpose)
        if not row:
            return DatastoreTarget(
                tenant_id=tenant_id,
                binding_id=None,
                engine="primary",
                host_mode="shared",
                routing_policy="bind_only",
                status="default",
                connection_hint="(platform primary DATABASE_URL)",
                use_primary=True,
                notes="未绑定独立数据源，使用平台主库。",
            )
        # force_tenant would eventually open a dedicated engine; not wired yet
        use_primary = row.routing_policy != "force_tenant" or row.status != "active"
        return DatastoreTarget(
            tenant_id=tenant_id,
            binding_id=row.id,
            engine=row.engine,
            host_mode=row.host_mode,
            routing_policy=row.routing_policy,
            status=row.status,
            connection_hint=row.connection_hint,
            use_primary=use_primary,
            notes=(
                "策略 force_tenant 且 active 时预留切库；当前版本仍回落主库以保证稳定。"
                if row.routing_policy == "force_tenant"
                else "绑定仅作登记与连通性校验，业务会话仍走主库。"
            ),
        )

    def get_session_for_tenant(self, tenant_id: UUID, purpose: str = "primary") -> Session:
        """Return a session. Dedicated engines reserved — always primary for now."""
        _ = self.resolve(tenant_id, purpose)
        return SessionLocal()

    def peek_connection_url(self, binding: TenantDatastoreBinding) -> str:
        return decrypt_secret(binding.connection_cipher)

    def to_public(self, target: DatastoreTarget) -> dict[str, Any]:
        return {
            "tenant_id": str(target.tenant_id),
            "binding_id": str(target.binding_id) if target.binding_id else None,
            "engine": target.engine,
            "host_mode": target.host_mode,
            "routing_policy": target.routing_policy,
            "status": target.status,
            "connection_hint": target.connection_hint,
            "use_primary": target.use_primary,
            "notes": target.notes,
        }
