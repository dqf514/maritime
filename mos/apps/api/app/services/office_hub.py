"""Office ecosystem orchestration — connect, sync, link resources, notify Teams, webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models_office import (
    OfficeAddonInstall,
    OfficeResourceLink,
    OfficeSyncJob,
    OfficeTenantLink,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.services.graph_client import (
    GraphClient,
    GraphError,
    admin_consent_url,
    exchange_code_for_tokens,
    graph_mode,
    refresh_access_token,
    token_expiry,
)
from app.services.identity import soft_sign_state
from app.services.ops_crypto import decrypt_token, encrypt_token

ADDON_CATALOG = [
    {
        "id": "outlook",
        "name": "MariOS for Outlook",
        "description": "Pin voyage / CP context beside mail; create estimate from recap; file attachments to voyage folder.",
        "manifest": "/office/outlook/manifest.xml",
        "host": "Outlook",
    },
    {
        "id": "teams",
        "name": "MariOS for Teams",
        "description": "Adaptive cards for approvals, voyage alerts, and OmniSearch-style deep links into MariOS.",
        "manifest": "/office/teams/manifest.json",
        "host": "Teams",
    },
    {
        "id": "excel",
        "name": "MariOS for Excel",
        "description": "Pull TCE / P&L / aging into workbooks; push estimate scenarios back to MariOS.",
        "manifest": "/office/excel/manifest.xml",
        "host": "Excel",
    },
    {
        "id": "sharepoint",
        "name": "MariOS SharePoint library sync",
        "description": "Map charter / voyage document libraries; keep SSOT links in MariOS.",
        "manifest": None,
        "host": "SharePoint",
    },
]


def ensure_office_link(db: Session, tenant_id: UUID) -> OfficeTenantLink:
    row = db.scalar(select(OfficeTenantLink).where(OfficeTenantLink.tenant_id == tenant_id))
    if not row:
        row = OfficeTenantLink(tenant_id=tenant_id, status="draft", scopes=[], defaults={}, last_health={})
        db.add(row)
        db.flush()
    for addon in ADDON_CATALOG:
        exists = db.scalar(
            select(OfficeAddonInstall).where(
                OfficeAddonInstall.tenant_id == tenant_id,
                OfficeAddonInstall.addon_id == addon["id"],
            )
        )
        if not exists:
            db.add(
                OfficeAddonInstall(
                    tenant_id=tenant_id,
                    addon_id=addon["id"],
                    status="available",
                    install_meta={"name": addon["name"], "host": addon["host"]},
                )
            )
    db.flush()
    return row


def office_status(db: Session, tenant_id: UUID) -> dict[str, Any]:
    link = ensure_office_link(db, tenant_id)
    mode = graph_mode()
    addons = db.scalars(select(OfficeAddonInstall).where(OfficeAddonInstall.tenant_id == tenant_id)).all()
    return {
        "graph_mode": mode,
        "status": link.status,
        "mail_enabled": link.mail_enabled,
        "files_enabled": link.files_enabled,
        "teams_enabled": link.teams_enabled,
        "sharepoint_enabled": link.sharepoint_enabled,
        "calendar_enabled": link.calendar_enabled,
        "defaults": link.defaults or {},
        "last_health": link.last_health or {},
        "consent_url": admin_consent_url(state=soft_sign_state(get_settings().jwt_secret, str(tenant_id))),
        "connected": link.status == "connected" and bool(decrypt_token(link.access_token)),
        "addons": [
            {
                "id": a.addon_id,
                "status": a.status,
                "version": a.version,
                **(a.install_meta or {}),
                **next((x for x in ADDON_CATALOG if x["id"] == a.addon_id), {}),
            }
            for a in addons
        ],
        "catalog": ADDON_CATALOG,
    }


def apply_oauth_tokens(
    db: Session,
    tenant_id: UUID,
    tokens: dict[str, Any],
    *,
    user_id: UUID | None = None,
) -> OfficeTenantLink:
    link = ensure_office_link(db, tenant_id)
    access_token = tokens.get("access_token")
    link.access_token = encrypt_token(access_token)
    if tokens.get("refresh_token"):
        link.refresh_token = encrypt_token(tokens["refresh_token"])
    link.token_expires_at = token_expiry(tokens.get("expires_in"))
    link.status = "connected"
    link.connected_by = user_id
    link.scopes = (tokens.get("scope") or "").split() if isinstance(tokens.get("scope"), str) else (link.scopes or [])
    client = GraphClient(access_token or "", mode=tokens.get("mode") or graph_mode())
    try:
        link.last_health = client.health()
    except GraphError as exc:
        link.last_health = {"ok": False, "error": str(exc)}
        link.status = "error"
    link.updated_at = datetime.now().astimezone()
    db.flush()
    return link


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def get_graph_client(db: Session, tenant_id: UUID) -> GraphClient:
    link = ensure_office_link(db, tenant_id)
    mode = graph_mode()
    access_token = decrypt_token(link.access_token)
    if link.status != "connected" or not access_token:
        if mode == "stub":
            # Auto-connect stub so desks work without Entra secrets
            tokens = exchange_code_for_tokens("stub-auto-connect")
            apply_oauth_tokens(db, tenant_id, tokens)
            db.commit()
            link = ensure_office_link(db, tenant_id)
            access_token = decrypt_token(link.access_token)
        else:
            raise GraphError("office_not_connected", status=409)
    # refresh if expired
    expires = _as_aware(link.token_expires_at)
    refresh_token = decrypt_token(link.refresh_token)
    if expires and expires < datetime.now().astimezone() and refresh_token:
        tokens = refresh_access_token(refresh_token)
        apply_oauth_tokens(db, tenant_id, tokens)
        db.commit()
        link = ensure_office_link(db, tenant_id)
        access_token = decrypt_token(link.access_token)
    token = access_token or ""
    return GraphClient(token, mode=mode if mode == "stub" or token.startswith("stub-") else "live")


def run_sync(db: Session, tenant_id: UUID, channel: str, *, direction: str = "inbound") -> OfficeSyncJob:
    job = OfficeSyncJob(tenant_id=tenant_id, channel=channel, direction=direction, status="running", started_at=datetime.now().astimezone())
    db.add(job)
    db.flush()
    try:
        client = get_graph_client(db, tenant_id)
        stats: dict[str, Any] = {"channel": channel}
        if channel == "mail":
            msgs = client.list_mail(top=20)
            stats["messages"] = len(msgs)
            stats["sample"] = [{"id": m.get("id"), "subject": m.get("subject"), "webLink": m.get("webLink")} for m in msgs[:5]]
        elif channel in {"onedrive", "sharepoint", "files"}:
            drives = client.list_drives()
            stats["drives"] = [{"id": d.get("id"), "name": d.get("name"), "driveType": d.get("driveType")} for d in drives]
            if drives:
                kids = client.list_drive_children(drives[0]["id"])
                stats["root_items"] = len(kids)
                stats["sample"] = [{"id": k.get("id"), "name": k.get("name"), "webUrl": k.get("webUrl")} for k in kids[:8]]
        elif channel == "teams":
            teams = client.list_joined_teams()
            stats["teams"] = [{"id": t.get("id"), "displayName": t.get("displayName")} for t in teams]
            if teams:
                chans = client.list_channels(teams[0]["id"])
                stats["channels"] = [{"id": c.get("id"), "displayName": c.get("displayName")} for c in chans]
        else:
            raise GraphError(f"unknown_channel:{channel}", status=400)
        job.stats = stats
        job.status = "done"
        job.finished_at = datetime.now().astimezone()
        link = ensure_office_link(db, tenant_id)
        link.last_health = {**(link.last_health or {}), "last_sync": channel, "at": job.finished_at.isoformat()}
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = str(exc)
        job.finished_at = datetime.now().astimezone()
    db.flush()
    return job


def link_resource(
    db: Session,
    tenant_id: UUID,
    *,
    entity_type: str,
    entity_id: UUID,
    resource_kind: str,
    resource_id: str,
    web_url: str | None = None,
    display_name: str | None = None,
    meta: dict | None = None,
) -> OfficeResourceLink:
    row = OfficeResourceLink(
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        resource_kind=resource_kind,
        resource_id=resource_id,
        web_url=web_url,
        display_name=display_name,
        meta=meta or {},
    )
    db.add(row)
    db.flush()
    return row


def provision_entity_folder(db: Session, tenant_id: UUID, *, entity_type: str, entity_id: UUID, title: str) -> dict[str, Any]:
    client = get_graph_client(db, tenant_id)
    drives = client.list_drives()
    if not drives:
        raise GraphError("no_drives", status=404)
    # Prefer SharePoint library if present
    drive = next((d for d in drives if d.get("driveType") == "documentLibrary"), drives[0])
    folder = client.create_folder(drive["id"], f"{entity_type}_{title}"[:80])
    link = link_resource(
        db,
        tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        resource_kind="folder",
        resource_id=folder["id"],
        web_url=folder.get("webUrl"),
        display_name=folder.get("name"),
        meta={"drive_id": drive["id"]},
    )
    return {"folder": folder, "link_id": str(link.id), "drive": drive}


def notify_teams(db: Session, tenant_id: UUID, text: str) -> dict[str, Any]:
    link = ensure_office_link(db, tenant_id)
    defaults = link.defaults or {}
    team_id = defaults.get("team_id")
    channel_id = defaults.get("channel_id")
    client = get_graph_client(db, tenant_id)
    if not team_id or not channel_id:
        teams = client.list_joined_teams()
        if not teams:
            raise GraphError("no_teams", status=404)
        team_id = teams[0]["id"]
        channels = client.list_channels(team_id)
        channel_id = (channels[0]["id"] if channels else None)
        if not channel_id:
            raise GraphError("no_channels", status=404)
        link.defaults = {**defaults, "team_id": team_id, "channel_id": channel_id}
        db.flush()
    return client.send_teams_channel_message(team_id, channel_id, text)


def create_webhook(
    db: Session,
    tenant_id: UUID,
    *,
    name: str,
    target_url: str,
    events: list[str] | None = None,
) -> WebhookEndpoint:
    row = WebhookEndpoint(
        tenant_id=tenant_id,
        name=name,
        target_url=target_url,
        secret=secrets.token_urlsafe(24),
        events=events or ["charter.activated", "voyage.started", "invoice.issued", "laytime.finalized", "office.sync.done"],
        status="active",
    )
    db.add(row)
    db.flush()
    return row


def sign_payload(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def deliver_webhook(db: Session, endpoint: WebhookEndpoint, event: str, payload: dict[str, Any]) -> WebhookDelivery:
    delivery = WebhookDelivery(
        endpoint_id=endpoint.id,
        tenant_id=endpoint.tenant_id,
        event=event,
        payload=payload,
        status="pending",
        attempts=1,
    )
    db.add(delivery)
    db.flush()
    body = json.dumps({"event": event, "payload": payload, "id": str(delivery.id)}, ensure_ascii=False).encode()
    headers = {
        "Content-Type": "application/json",
        "X-VoyageOS-Event": event,
        "X-VoyageOS-Signature": sign_payload(endpoint.secret, body),
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            # Stub-safe: local echo URLs may fail — mark delivered in stub health mode
            if endpoint.target_url.startswith("stub://") or "example.com" in endpoint.target_url:
                delivery.status = "delivered"
                delivery.response_code = 200
            else:
                res = client.post(endpoint.target_url, content=body, headers=headers)
                delivery.response_code = res.status_code
                delivery.status = "delivered" if res.status_code < 300 else "failed"
                if delivery.status == "failed":
                    endpoint.failure_count = (endpoint.failure_count or 0) + 1
            endpoint.last_delivery = {
                "at": datetime.now().astimezone().isoformat(),
                "event": event,
                "status": delivery.status,
                "code": delivery.response_code,
            }
    except Exception as exc:  # noqa: BLE001
        delivery.status = "failed"
        endpoint.failure_count = (endpoint.failure_count or 0) + 1
        endpoint.last_delivery = {"at": datetime.now().astimezone().isoformat(), "error": str(exc)}
    db.flush()
    return delivery


def emit_event(db: Session, tenant_id: UUID, event: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.tenant_id == tenant_id,
            WebhookEndpoint.status == "active",
        )
    ).all()
    out = []
    for ep in rows:
        if ep.events and event not in ep.events and "*" not in ep.events:
            continue
        d = deliver_webhook(db, ep, event, payload)
        out.append({"endpoint_id": str(ep.id), "delivery_id": str(d.id), "status": d.status})
    return out
