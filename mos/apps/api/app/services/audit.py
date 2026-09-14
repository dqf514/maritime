"""Audit helper — write AuditLog rows for security-relevant events.

Transaction strategy (chosen after reviewing the routers): audit rows ride the
*caller's* session/transaction so an event commits atomically with the business
change it describes (e.g. password change). For code paths that raise before
any commit (e.g. failed login), pass commit=True to persist the row in its own
transaction. The whole write is wrapped in try/except: an audit failure is
logged and swallowed — it must never break the main flow.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models_audit import AuditLog

log = logging.getLogger("voyageos.audit")


def audit(
    db: Session,
    *,
    action: str,
    tenant_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: object = None,
    detail: dict | None = None,
    ip: str | None = None,
    commit: bool = False,
) -> None:
    """Append one audit row. Never raises."""
    try:
        db.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                detail=detail or {},
                ip=ip,
            )
        )
        if commit:
            db.commit()
    except Exception:  # noqa: BLE001
        log.exception("audit write failed action=%s", action)
        if commit:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
