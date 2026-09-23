"""Webhook subscription and delivery service.

Uses the existing WebhookEndpoint / WebhookDelivery models from models_office.
Supports event matching with wildcards (e.g. "voyage.*") and HMAC-SHA256 signing.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models_office import WebhookEndpoint, WebhookDelivery


def _generate_secret() -> str:
    return secrets.token_hex(32)


def _matches(subscription_events: list, event: str) -> bool:
    for pattern in subscription_events:
        if pattern == event:
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            if event.startswith(prefix + "."):
                return True
    return False


def create_subscription(
    db: Session,
    tenant_id: UUID,
    name: str,
    url: str,
    events: list[str],
) -> WebhookEndpoint:
    sub = WebhookEndpoint(
        tenant_id=tenant_id,
        name=name,
        target_url=url,
        events=events,
        secret=_generate_secret(),
        status="active",
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def list_subscriptions(db: Session, tenant_id: UUID) -> list[WebhookEndpoint]:
    return list(db.scalars(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.tenant_id == tenant_id)
        .order_by(desc(WebhookEndpoint.created_at))
    ).all())


def get_subscription(
    db: Session, sub_id: UUID, tenant_id: UUID
) -> WebhookEndpoint | None:
    return db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == sub_id,
            WebhookEndpoint.tenant_id == tenant_id,
        )
    ).first()


def update_subscription(
    db: Session,
    sub: WebhookEndpoint,
    name: str | None = None,
    url: str | None = None,
    events: list[str] | None = None,
    is_active: bool | None = None,
) -> WebhookEndpoint:
    if name is not None:
        sub.name = name
    if url is not None:
        sub.target_url = url
    if events is not None:
        sub.events = events
    if is_active is not None:
        sub.status = "active" if is_active else "inactive"
    db.commit()
    db.refresh(sub)
    return sub


def delete_subscription(db: Session, sub: WebhookEndpoint) -> None:
    db.delete(sub)
    db.commit()


def rotate_secret(db: Session, sub: WebhookEndpoint) -> str:
    sub.secret = _generate_secret()
    db.commit()
    return sub.secret


def dispatch_event(
    db: Session,
    tenant_id: UUID,
    event: str,
    payload: dict,
) -> list[WebhookDelivery]:
    """Queue event for all matching active endpoints."""
    subs = db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.tenant_id == tenant_id,
            WebhookEndpoint.status == "active",
        )
    ).all()

    deliveries = []
    for sub in subs:
        if not _matches(sub.events or [], event):
            continue
        delivery = WebhookDelivery(
            endpoint_id=sub.id,
            tenant_id=tenant_id,
            event=event,
            payload=payload,
            status="pending",
        )
        db.add(delivery)
        deliveries.append(delivery)

    db.commit()
    for d in deliveries:
        db.refresh(d)
    return deliveries


def sign_payload(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def list_deliveries(
    db: Session,
    tenant_id: UUID,
    endpoint_id: UUID | None = None,
    limit: int = 50,
) -> list[WebhookDelivery]:
    stmt = select(WebhookDelivery).where(WebhookDelivery.tenant_id == tenant_id)
    if endpoint_id:
        stmt = stmt.where(WebhookDelivery.endpoint_id == endpoint_id)
    stmt = stmt.order_by(desc(WebhookDelivery.created_at)).limit(limit)
    return list(db.scalars(stmt).all())
