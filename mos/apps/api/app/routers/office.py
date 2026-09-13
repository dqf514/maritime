"""Office / Microsoft 365 ecosystem API — connect, sync, mail, files, Teams, webhooks, add-ins."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models_office import OfficeAddonInstall, OfficeResourceLink, OfficeSyncJob, WebhookEndpoint
from app.security import AuthContext, get_current_auth_optional, require_auth, require_module
from app.services.graph_client import GraphError, admin_consent_url, exchange_code_for_tokens, graph_mode
from app.services import office_hub as hub

router = APIRouter(prefix="/office", tags=["Office Ecosystem"])


class OfficeSettingsIn(BaseModel):
    mail_enabled: bool | None = None
    files_enabled: bool | None = None
    teams_enabled: bool | None = None
    sharepoint_enabled: bool | None = None
    calendar_enabled: bool | None = None
    defaults: dict[str, Any] | None = None


class ConnectStubIn(BaseModel):
    """Dev-only: connect Graph in stub mode without IdP redirect."""

    label: str = "stub"


class SyncIn(BaseModel):
    channel: str = Field(description="mail|onedrive|sharepoint|files|teams")
    direction: str = "inbound"


class MailSendIn(BaseModel):
    to: str
    subject: str
    body: str
    content_type: str = "Text"


class ResourceLinkIn(BaseModel):
    entity_type: str
    entity_id: UUID
    resource_kind: str
    resource_id: str
    web_url: str | None = None
    display_name: str | None = None
    meta: dict[str, Any] | None = None


class ProvisionFolderIn(BaseModel):
    entity_type: str
    entity_id: UUID
    title: str


class TeamsNotifyIn(BaseModel):
    text: str
    team_id: str | None = None
    channel_id: str | None = None


class WebhookIn(BaseModel):
    name: str
    target_url: str
    events: list[str] | None = None


class AddonStatusIn(BaseModel):
    status: str = "installed"  # available|installed|disabled
    version: str | None = None


def _graph_http(exc: GraphError) -> HTTPException:
    return HTTPException(status_code=exc.status or 400, detail={"code": "GRAPH_ERROR", "message": str(exc), "detail": exc.detail})


@router.get("/status")
def office_status(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    return hub.office_status(db, auth.tenant_id)


@router.get("/connect")
def office_connect(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    """Return consent URL (live) or auto-connect stub."""
    mode = graph_mode()
    if mode == "disabled":
        raise HTTPException(400, detail={"code": "OFFICE_DISABLED", "message": "Set MICROSOFT_CLIENT_ID/SECRET or OAUTH_ALLOW_STUB=true"})
    if mode == "stub":
        tokens = exchange_code_for_tokens("stub-connect")
        hub.apply_oauth_tokens(db, auth.tenant_id, tokens, user_id=auth.user_id)
        db.commit()
        return {"mode": "stub", "connected": True, "status": hub.office_status(db, auth.tenant_id)}
    url = admin_consent_url(state=str(auth.tenant_id))
    return {"mode": "live", "authorize_url": url, "connected": False}


@router.post("/connect/stub")
def office_connect_stub(
    body: ConnectStubIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    if graph_mode() == "disabled":
        raise HTTPException(400, "stub oauth disabled")
    tokens = exchange_code_for_tokens(f"stub-{body.label}")
    hub.apply_oauth_tokens(db, auth.tenant_id, tokens, user_id=auth.user_id)
    db.commit()
    return hub.office_status(db, auth.tenant_id)


@router.get("/oauth/callback")
def office_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext | None = Depends(get_current_auth_optional),
):
    settings = get_settings()
    web = settings.web_public_base.rstrip("/")
    if error:
        return RedirectResponse(f"{web}/settings/office?error={error}")
    if not code or not state:
        raise HTTPException(400, "missing code/state")
    try:
        tenant_id = UUID(state)
    except ValueError as exc:
        raise HTTPException(400, "invalid state") from exc
    try:
        tokens = exchange_code_for_tokens(code)
        hub.apply_oauth_tokens(db, tenant_id, tokens, user_id=auth.user_id if auth else None)
        db.commit()
    except GraphError as exc:
        raise _graph_http(exc) from exc
    return RedirectResponse(f"{web}/settings/office?connected=1")


@router.post("/disconnect")
def office_disconnect(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    link = hub.ensure_office_link(db, auth.tenant_id)
    link.status = "disabled"
    link.access_token = None
    link.refresh_token = None
    link.token_expires_at = None
    link.last_health = {"ok": False, "message": "disconnected", "at": datetime.now().astimezone().isoformat()}
    db.commit()
    return hub.office_status(db, auth.tenant_id)


@router.patch("/settings")
def office_patch_settings(
    body: OfficeSettingsIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    link = hub.ensure_office_link(db, auth.tenant_id)
    data = body.model_dump(exclude_none=True)
    defaults = data.pop("defaults", None)
    for k, v in data.items():
        setattr(link, k, v)
    if defaults is not None:
        link.defaults = {**(link.defaults or {}), **defaults}
    link.updated_at = datetime.now().astimezone()
    db.commit()
    return hub.office_status(db, auth.tenant_id)


@router.post("/sync")
def office_sync(
    body: SyncIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    try:
        job = hub.run_sync(db, auth.tenant_id, body.channel, direction=body.direction)
        hub.emit_event(db, auth.tenant_id, "office.sync.done", {"channel": body.channel, "job_id": str(job.id), "status": job.status})
        db.commit()
    except GraphError as exc:
        raise _graph_http(exc) from exc
    return {
        "id": str(job.id),
        "channel": job.channel,
        "status": job.status,
        "stats": job.stats,
        "error": job.error,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.get("/sync/jobs")
def list_sync_jobs(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    rows = db.scalars(
        select(OfficeSyncJob)
        .where(OfficeSyncJob.tenant_id == auth.tenant_id)
        .order_by(OfficeSyncJob.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": str(r.id),
            "channel": r.channel,
            "direction": r.direction,
            "status": r.status,
            "stats": r.stats,
            "error": r.error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/mail")
def list_mail(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
    top: int = Query(25, ge=1, le=50),
):
    try:
        client = hub.get_graph_client(db, auth.tenant_id)
        db.commit()
        return {"items": client.list_mail(top=top), "mode": client.mode}
    except GraphError as exc:
        raise _graph_http(exc) from exc


@router.post("/mail/send")
def send_mail(
    body: MailSendIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    try:
        client = hub.get_graph_client(db, auth.tenant_id)
        out = client.send_mail(to=body.to, subject=body.subject, body=body.body, content_type=body.content_type)
        db.commit()
        return out
    except GraphError as exc:
        raise _graph_http(exc) from exc


@router.get("/drives")
def list_drives(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    try:
        client = hub.get_graph_client(db, auth.tenant_id)
        db.commit()
        return {"items": client.list_drives(), "mode": client.mode}
    except GraphError as exc:
        raise _graph_http(exc) from exc


@router.get("/drives/{drive_id}/children")
def list_drive_children(
    drive_id: str,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    try:
        client = hub.get_graph_client(db, auth.tenant_id)
        db.commit()
        return {"items": client.list_drive_children(drive_id), "mode": client.mode}
    except GraphError as exc:
        raise _graph_http(exc) from exc


@router.post("/resources/link")
def create_resource_link(
    body: ResourceLinkIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    row = hub.link_resource(db, auth.tenant_id, **body.model_dump())
    db.commit()
    return {
        "id": str(row.id),
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "resource_kind": row.resource_kind,
        "resource_id": row.resource_id,
        "web_url": row.web_url,
        "display_name": row.display_name,
    }


@router.get("/resources")
def list_resources(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
    entity_type: str | None = None,
    entity_id: UUID | None = None,
):
    q = select(OfficeResourceLink).where(OfficeResourceLink.tenant_id == auth.tenant_id)
    if entity_type:
        q = q.where(OfficeResourceLink.entity_type == entity_type)
    if entity_id:
        q = q.where(OfficeResourceLink.entity_id == entity_id)
    rows = db.scalars(q.order_by(OfficeResourceLink.created_at.desc()).limit(100)).all()
    return [
        {
            "id": str(r.id),
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id),
            "resource_kind": r.resource_kind,
            "resource_id": r.resource_id,
            "web_url": r.web_url,
            "display_name": r.display_name,
            "meta": r.meta,
        }
        for r in rows
    ]


@router.post("/resources/provision-folder")
def provision_folder(
    body: ProvisionFolderIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    try:
        out = hub.provision_entity_folder(
            db, auth.tenant_id, entity_type=body.entity_type, entity_id=body.entity_id, title=body.title
        )
        db.commit()
        return out
    except GraphError as exc:
        raise _graph_http(exc) from exc


@router.get("/teams")
def list_teams(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    try:
        client = hub.get_graph_client(db, auth.tenant_id)
        teams = client.list_joined_teams()
        db.commit()
        return {"items": teams, "mode": client.mode}
    except GraphError as exc:
        raise _graph_http(exc) from exc


@router.get("/teams/{team_id}/channels")
def list_channels(
    team_id: str,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    try:
        client = hub.get_graph_client(db, auth.tenant_id)
        db.commit()
        return {"items": client.list_channels(team_id), "mode": client.mode}
    except GraphError as exc:
        raise _graph_http(exc) from exc


@router.post("/teams/notify")
def teams_notify(
    body: TeamsNotifyIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    try:
        link = hub.ensure_office_link(db, auth.tenant_id)
        if body.team_id and body.channel_id:
            link.defaults = {**(link.defaults or {}), "team_id": body.team_id, "channel_id": body.channel_id}
            db.flush()
        out = hub.notify_teams(db, auth.tenant_id, body.text)
        db.commit()
        return out
    except GraphError as exc:
        raise _graph_http(exc) from exc


@router.get("/webhooks")
def list_webhooks(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "target_url": r.target_url,
            "events": r.events,
            "status": r.status,
            "secret_prefix": (r.secret or "")[:8],
            "failure_count": r.failure_count,
            "last_delivery": r.last_delivery,
        }
        for r in rows
    ]


@router.post("/webhooks")
def create_webhook(
    body: WebhookIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    row = hub.create_webhook(db, auth.tenant_id, name=body.name, target_url=body.target_url, events=body.events)
    db.commit()
    return {
        "id": str(row.id),
        "name": row.name,
        "target_url": row.target_url,
        "secret": row.secret,
        "events": row.events,
        "status": row.status,
    }


@router.post("/webhooks/{webhook_id}/test")
def test_webhook(
    webhook_id: UUID,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    row = db.get(WebhookEndpoint, webhook_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Webhook not found")
    delivery = hub.deliver_webhook(
        db,
        row,
        "office.webhook.test",
        {"tenant_id": str(auth.tenant_id), "at": datetime.now().astimezone().isoformat()},
    )
    db.commit()
    return {"delivery_id": str(delivery.id), "status": delivery.status, "response_code": delivery.response_code}


@router.get("/addons")
def list_addons(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    status = hub.office_status(db, auth.tenant_id)
    return {"catalog": status["catalog"], "installs": status["addons"]}


@router.post("/addons/{addon_id}")
def set_addon_status(
    addon_id: str,
    body: AddonStatusIn,
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    hub.ensure_office_link(db, auth.tenant_id)
    row = db.scalar(
        select(OfficeAddonInstall).where(
            OfficeAddonInstall.tenant_id == auth.tenant_id,
            OfficeAddonInstall.addon_id == addon_id,
        )
    )
    if not row:
        raise HTTPException(404, "Addon not found")
    row.status = body.status
    if body.version:
        row.version = body.version
    row.updated_at = datetime.now().astimezone()
    db.commit()
    return {"id": addon_id, "status": row.status, "version": row.version}


@router.get("/health")
def office_health(
    auth: AuthContext = Depends(require_module("integration")),
    db: Session = Depends(get_db),
):
    try:
        client = hub.get_graph_client(db, auth.tenant_id)
        health = client.health()
        link = hub.ensure_office_link(db, auth.tenant_id)
        link.last_health = health
        link.status = "connected"
        db.commit()
        return health
    except GraphError as exc:
        raise _graph_http(exc) from exc


# --- Partner / add-in surface (API key or JWT) ---

@router.get("/partner/ping")
def partner_ping(
    request: Request,
    auth: AuthContext = Depends(require_auth),
):
    """Simple ping for Office add-ins / Power Automate using JWT or X-API-Key."""
    _ = request
    return {
        "ok": True,
        "tenant_id": str(auth.tenant_id),
        "user_id": str(auth.user_id),
        "product": "VoyageOS",
        "ecosystem": "office",
    }
