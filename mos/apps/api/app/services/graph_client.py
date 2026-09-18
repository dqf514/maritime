"""Microsoft Graph client — live when credentials set, otherwise deterministic stub mode.

Credentials resolve per tenant (see app.services.ms_config): a tenant-specific
Entra app override wins, otherwise the global MICROSOFT_CLIENT_* env config is
used. Functions below accept an optional ``ms_config``; when omitted they fall
back to the global settings, preserving pre-tenant-aware behavior.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPES = [
    "openid",
    "profile",
    "email",
    "offline_access",
    "User.Read",
    "Mail.ReadWrite",
    "Mail.Send",
    "Files.ReadWrite.All",
    "Sites.ReadWrite.All",
    "ChannelMessage.Send",
    "Chat.ReadWrite",
    "Calendars.ReadWrite",
]


@dataclass
class MsConfig:
    """Resolved Microsoft 365 app credentials for one tenant."""

    client_id: str = ""
    client_secret: str = ""
    ms_tenant: str = "common"
    source: str = "none"  # tenant | global | none


class GraphError(Exception):
    def __init__(self, message: str, *, status: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


def _global_ms_config(s: Settings) -> MsConfig:
    return MsConfig(
        client_id=s.microsoft_client_id or "",
        client_secret=s.microsoft_client_secret or "",
        ms_tenant=s.microsoft_tenant or "common",
        source="global" if s.microsoft_client_id else "none",
    )


def graph_mode_resolved(cfg: MsConfig | None = None, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    c = cfg if cfg is not None else _global_ms_config(s)
    if c.client_id and c.client_secret:
        return "live"
    return "stub" if s.oauth_allow_stub else "disabled"


def graph_mode(settings: Settings | None = None) -> str:
    return graph_mode_resolved(None, settings)


def admin_consent_url(
    settings: Settings | None = None,
    *,
    state: str | None = None,
    ms_config: MsConfig | None = None,
) -> str | None:
    s = settings or get_settings()
    c = ms_config if ms_config is not None else _global_ms_config(s)
    if not c.client_id:
        return None
    redirect = f"{s.api_public_base.rstrip('/')}/api/v1/office/oauth/callback"
    q = {
        "client_id": c.client_id,
        "response_type": "code",
        "redirect_uri": redirect,
        "response_mode": "query",
        "scope": " ".join(DEFAULT_SCOPES),
        "state": state or secrets.token_urlsafe(16),
    }
    return f"https://login.microsoftonline.com/{c.ms_tenant or 'common'}/oauth2/v2.0/authorize?{urlencode(q)}"


def exchange_code_for_tokens(
    code: str,
    *,
    settings: Settings | None = None,
    ms_config: MsConfig | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    c = ms_config if ms_config is not None else _global_ms_config(s)
    if graph_mode_resolved(c, s) == "stub":
        return {
            "access_token": f"stub-access-{hashlib.sha256(code.encode()).hexdigest()[:24]}",
            "refresh_token": f"stub-refresh-{secrets.token_hex(8)}",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": " ".join(DEFAULT_SCOPES),
            "mode": "stub",
        }
    redirect = f"{s.api_public_base.rstrip('/')}/api/v1/office/oauth/callback"
    data = {
        "client_id": c.client_id,
        "client_secret": c.client_secret,
        "code": code,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=30.0) as client:
        res = client.post(
            f"https://login.microsoftonline.com/{c.ms_tenant or 'common'}/oauth2/v2.0/token",
            data=data,
        )
        if res.status_code >= 400:
            raise GraphError("token_exchange_failed", status=res.status_code, detail=res.text)
        out = res.json()
        out["mode"] = "live"
        return out


def refresh_access_token(
    refresh_token: str,
    *,
    settings: Settings | None = None,
    ms_config: MsConfig | None = None,
) -> dict[str, Any]:
    s = settings or get_settings()
    c = ms_config if ms_config is not None else _global_ms_config(s)
    if graph_mode_resolved(c, s) == "stub":
        return {
            "access_token": f"stub-access-{secrets.token_hex(12)}",
            "refresh_token": refresh_token,
            "expires_in": 3600,
            "mode": "stub",
        }
    data = {
        "client_id": c.client_id,
        "client_secret": c.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": " ".join(DEFAULT_SCOPES),
    }
    with httpx.Client(timeout=30.0) as client:
        res = client.post(
            f"https://login.microsoftonline.com/{c.ms_tenant or 'common'}/oauth2/v2.0/token",
            data=data,
        )
        if res.status_code >= 400:
            raise GraphError("token_refresh_failed", status=res.status_code, detail=res.text)
        out = res.json()
        out["mode"] = "live"
        return out


def request_client_credentials_token(cfg: MsConfig, *, timeout: float = 10.0) -> httpx.Response:
    """Probe app credentials via the client_credentials grant (daemon-style check).

    Extracted as a standalone function so tests can monkeypatch the HTTP layer.
    """
    with httpx.Client(timeout=timeout) as client:
        return client.post(
            f"https://login.microsoftonline.com/{cfg.ms_tenant or 'common'}/oauth2/v2.0/token",
            data={
                "client_id": cfg.client_id,
                "client_secret": cfg.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )


class GraphClient:
    def __init__(self, access_token: str, *, mode: str = "live"):
        self.access_token = access_token
        self.mode = mode

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def me(self) -> dict[str, Any]:
        if self.mode == "stub":
            return {
                "id": "stub-user-001",
                "displayName": "MariOS Demo User",
                "mail": "demo@contoso.onmicrosoft.com",
                "userPrincipalName": "demo@contoso.onmicrosoft.com",
            }
        return self._get("/me")

    def list_mail(self, *, top: int = 25, folder: str = "inbox") -> list[dict[str, Any]]:
        if self.mode == "stub":
            now = datetime.now().astimezone().isoformat()
            return [
                {
                    "id": "stub-mail-1",
                    "subject": "FIRM OFFER — MV DEMO WAVE / SGSIN-NLRTM",
                    "from": {"emailAddress": {"address": "charterer@broker.com", "name": "Atlantic Brokers"}},
                    "receivedDateTime": now,
                    "bodyPreview": "We are pleased to offer MV DEMO WAVE for your cargo...",
                    "hasAttachments": True,
                    "webLink": "https://outlook.office.com/mail/stub-mail-1",
                },
                {
                    "id": "stub-mail-2",
                    "subject": "NOR tendered — Rotterdam",
                    "from": {"emailAddress": {"address": "master@vessel.demo", "name": "Master"}},
                    "receivedDateTime": now,
                    "bodyPreview": "NOR tendered at 08:00 LT awaiting free pratique.",
                    "hasAttachments": False,
                    "webLink": "https://outlook.office.com/mail/stub-mail-2",
                },
            ][:top]
        data = self._get(f"/me/mailFolders/{folder}/messages?$top={top}&$orderby=receivedDateTime desc")
        return data.get("value") or []

    def send_mail(self, *, to: str, subject: str, body: str, content_type: str = "Text") -> dict[str, Any]:
        if self.mode == "stub":
            return {"id": f"stub-sent-{secrets.token_hex(4)}", "status": "queued", "mode": "stub"}
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": content_type, "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }
        self._post("/me/sendMail", payload)
        return {"status": "sent", "mode": "live"}

    def list_drives(self) -> list[dict[str, Any]]:
        if self.mode == "stub":
            return [
                {"id": "stub-drive-onedrive", "name": "OneDrive - Demo", "driveType": "personal", "webUrl": "https://onedrive.live.com/stub"},
                {"id": "stub-drive-sp", "name": "SharePoint - Chartering Docs", "driveType": "documentLibrary", "webUrl": "https://contoso.sharepoint.com/sites/chartering"},
            ]
        data = self._get("/me/drives")
        return data.get("value") or []

    def list_drive_children(self, drive_id: str, *, path: str = "root") -> list[dict[str, Any]]:
        if self.mode == "stub":
            return [
                {"id": "stub-folder-cp", "name": "Charter Parties", "folder": {}, "webUrl": "https://contoso.sharepoint.com/CP"},
                {"id": "stub-file-recap", "name": "Recap_DEMO_WAVE.pdf", "file": {"mimeType": "application/pdf"}, "size": 182000, "webUrl": "https://contoso.sharepoint.com/Recap.pdf"},
                {"id": "stub-file-sof", "name": "SOF_Rotterdam.xlsx", "file": {"mimeType": "application/vnd.openxmlformats"}, "size": 42000, "webUrl": "https://contoso.sharepoint.com/SOF.xlsx"},
            ]
        segment = "root/children" if path == "root" else f"root:/{path}:/children"
        data = self._get(f"/drives/{drive_id}/{segment}")
        return data.get("value") or []

    def create_folder(self, drive_id: str, name: str, *, parent: str = "root") -> dict[str, Any]:
        if self.mode == "stub":
            return {
                "id": f"stub-folder-{hashlib.md5(name.encode()).hexdigest()[:8]}",
                "name": name,
                "folder": {},
                "webUrl": f"https://contoso.sharepoint.com/{name}",
                "mode": "stub",
            }
        parent_path = "root/children" if parent == "root" else f"items/{parent}/children"
        return self._post(f"/drives/{drive_id}/{parent_path}", {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"})

    def upload_small_file(self, drive_id: str, filename: str, content: bytes, *, parent: str = "root") -> dict[str, Any]:
        if self.mode == "stub":
            return {
                "id": f"stub-file-{hashlib.md5(filename.encode()).hexdigest()[:8]}",
                "name": filename,
                "size": len(content),
                "webUrl": f"https://contoso.sharepoint.com/{filename}",
                "mode": "stub",
            }
        path = f"root:/{filename}:/content" if parent == "root" else f"items/{parent}:/{filename}:/content"
        with httpx.Client(timeout=60.0) as client:
            res = client.put(
                f"{GRAPH_BASE}/drives/{drive_id}/{path}",
                headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/octet-stream"},
                content=content,
            )
            if res.status_code >= 400:
                raise GraphError("upload_failed", status=res.status_code, detail=res.text)
            return res.json()

    def send_teams_channel_message(self, team_id: str, channel_id: str, text: str) -> dict[str, Any]:
        if self.mode == "stub":
            return {
                "id": f"stub-msg-{secrets.token_hex(4)}",
                "body": {"content": text},
                "webUrl": f"https://teams.microsoft.com/l/message/{channel_id}",
                "mode": "stub",
            }
        return self._post(
            f"/teams/{team_id}/channels/{channel_id}/messages",
            {"body": {"contentType": "html", "content": text}},
        )

    def list_joined_teams(self) -> list[dict[str, Any]]:
        if self.mode == "stub":
            return [
                {"id": "stub-team-ops", "displayName": "Voyage Operations", "description": "Ops & port calls"},
                {"id": "stub-team-charter", "displayName": "Chartering Desk", "description": "Fixtures & estimates"},
            ]
        data = self._get("/me/joinedTeams")
        return data.get("value") or []

    def list_channels(self, team_id: str) -> list[dict[str, Any]]:
        if self.mode == "stub":
            return [
                {"id": "stub-ch-general", "displayName": "General"},
                {"id": "stub-ch-alerts", "displayName": "Voyage Alerts"},
            ]
        data = self._get(f"/teams/{team_id}/channels")
        return data.get("value") or []

    def health(self) -> dict[str, Any]:
        me = self.me()
        return {
            "ok": True,
            "mode": self.mode,
            "user": me.get("displayName") or me.get("userPrincipalName"),
            "tested_at": datetime.now().astimezone().isoformat(),
        }

    def _get(self, path: str) -> dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            res = client.get(f"{GRAPH_BASE}{path}", headers=self._headers())
            if res.status_code >= 400:
                raise GraphError("graph_get_failed", status=res.status_code, detail=res.text)
            return res.json()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            res = client.post(f"{GRAPH_BASE}{path}", headers=self._headers(), json=payload)
            if res.status_code >= 400:
                raise GraphError("graph_post_failed", status=res.status_code, detail=res.text)
            if res.status_code == 202 or not res.content:
                return {"status": "accepted"}
            return res.json()


def token_expiry(expires_in: int | None) -> datetime:
    return datetime.now().astimezone() + timedelta(seconds=int(expires_in or 3600) - 60)
