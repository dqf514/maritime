"""Webhook subscription and delivery service.

Uses the existing WebhookEndpoint / WebhookDelivery models from models_office.
Supports event matching with wildcards (e.g. "voyage.*") and HMAC-SHA256 signing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models_office import WebhookEndpoint, WebhookDelivery
from app.services.job_queue import job_handler


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
    """Queue event for all matching active endpoints.

    每条投递入后台作业队列（webhook.deliver）异步发送，失败指数退避重试；
    idempotency_key 保证同一 delivery 只入队一次。
    """
    from app.services.job_queue import enqueue

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
        enqueue(
            db,
            "webhook.deliver",
            {"delivery_id": str(d.id)},
            tenant_id=tenant_id,
            idempotency_key=f"webhook:{d.id}",
        )
    return deliveries


@job_handler("webhook.deliver")
def _deliver_webhook(db: Session, job) -> None:
    """真实 HTTP 投递：签名、状态回写；非 2xx 抛错触发队列重试。"""
    import httpx

    from app.models_jobs import Job  # noqa: F401 — 类型提示用

    delivery = db.get(WebhookDelivery, UUID(str(job.payload.get("delivery_id"))))
    if delivery is None:
        return
    if delivery.status == "delivered":
        return  # at-least-once 下的幂等短路
    sub = db.get(WebhookEndpoint, delivery.endpoint_id)
    if sub is None or sub.status != "active":
        delivery.status = "failed"
        db.commit()
        return
    body = json.dumps({"event": delivery.event, "payload": delivery.payload}, default=str).encode()
    resp = httpx.post(
        sub.target_url,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-MariOS-Event": delivery.event,
            "X-MariOS-Signature": sign_payload(sub.secret, body),
        },
        timeout=10.0,
    )
    delivery.attempts += 1
    delivery.response_code = resp.status_code
    if resp.status_code < 300:
        delivery.status = "delivered"
        sub.last_delivery = {
            "event": delivery.event,
            "at": datetime.now(timezone.utc).isoformat(),
            "code": resp.status_code,
        }
    else:
        delivery.status = "failed"
        sub.failure_count += 1
        db.commit()
        raise RuntimeError(f"webhook delivery {delivery.id} HTTP {resp.status_code}")
    db.commit()


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
