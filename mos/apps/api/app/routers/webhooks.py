"""Phase 5 — Webhook subscription and delivery endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module
from app.services import webhook_service as wh_svc

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class SubscriptionOut(BaseModel):
    id: str
    name: str
    url: str
    events: list
    status: str
    created_at: str


class SubscriptionIn(BaseModel):
    name: str
    url: str
    events: list[str]


class SubscriptionUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    events: list[str] | None = None
    is_active: bool | None = None


class DeliveryOut(BaseModel):
    id: str
    endpoint_id: str
    event: str
    status: str
    attempts: int
    response_code: int | None
    created_at: str


class DispatchIn(BaseModel):
    event: str
    payload: dict


@router.get("/subscriptions", response_model=list[SubscriptionOut])
def list_subscriptions(
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    subs = wh_svc.list_subscriptions(db, auth.tenant_id)
    return [
        SubscriptionOut(
            id=str(s.id),
            name=s.name,
            url=s.target_url,
            events=s.events or [],
            status=s.status or "active",
            created_at=s.created_at.isoformat(),
        )
        for s in subs
    ]


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201)
def create_subscription(
    body: SubscriptionIn,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    sub = wh_svc.create_subscription(
        db, auth.tenant_id, body.name, body.url, body.events
    )
    return SubscriptionOut(
        id=str(sub.id),
        name=sub.name,
        url=sub.target_url,
        events=sub.events or [],
        status=sub.status or "active",
        created_at=sub.created_at.isoformat(),
    )


@router.get("/subscriptions/{sub_id}", response_model=SubscriptionOut)
def get_subscription(
    sub_id: UUID,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    sub = wh_svc.get_subscription(db, sub_id, auth.tenant_id)
    if not sub:
        raise HTTPException(404, "Subscription not found")
    return SubscriptionOut(
        id=str(sub.id),
        name=sub.name,
        url=sub.target_url,
        events=sub.events or [],
        status=sub.status or "active",
        created_at=sub.created_at.isoformat(),
    )


@router.patch("/subscriptions/{sub_id}", response_model=SubscriptionOut)
def update_subscription(
    sub_id: UUID,
    body: SubscriptionUpdate,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    sub = wh_svc.get_subscription(db, sub_id, auth.tenant_id)
    if not sub:
        raise HTTPException(404, "Subscription not found")
    sub = wh_svc.update_subscription(
        db, sub,
        name=body.name,
        url=body.url,
        events=body.events,
        is_active=body.is_active,
    )
    return SubscriptionOut(
        id=str(sub.id),
        name=sub.name,
        url=sub.target_url,
        events=sub.events or [],
        status=sub.status or "active",
        created_at=sub.created_at.isoformat(),
    )


@router.delete("/subscriptions/{sub_id}", status_code=204)
def delete_subscription(
    sub_id: UUID,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    sub = wh_svc.get_subscription(db, sub_id, auth.tenant_id)
    if not sub:
        raise HTTPException(404, "Subscription not found")
    wh_svc.delete_subscription(db, sub)


@router.post("/subscriptions/{sub_id}/rotate-secret")
def rotate_secret(
    sub_id: UUID,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    sub = wh_svc.get_subscription(db, sub_id, auth.tenant_id)
    if not sub:
        raise HTTPException(404, "Subscription not found")
    new_secret = wh_svc.rotate_secret(db, sub)
    return {"secret": new_secret}


@router.post("/dispatch")
def dispatch_event(
    body: DispatchIn,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    deliveries = wh_svc.dispatch_event(db, auth.tenant_id, body.event, body.payload)
    return {
        "queued": len(deliveries),
        "deliveries": [
            {"id": str(d.id), "endpoint_id": str(d.endpoint_id), "event": d.event, "status": d.status}
            for d in deliveries
        ],
    }


@router.get("/deliveries", response_model=list[DeliveryOut])
def list_deliveries(
    endpoint_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    deliveries = wh_svc.list_deliveries(db, auth.tenant_id, endpoint_id)
    return [
        DeliveryOut(
            id=str(d.id),
            endpoint_id=str(d.endpoint_id),
            event=d.event,
            status=d.status or "pending",
            attempts=d.attempts or 0,
            response_code=d.response_code,
            created_at=d.created_at.isoformat(),
        )
        for d in deliveries
    ]
