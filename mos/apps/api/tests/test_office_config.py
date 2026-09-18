"""Per-tenant Microsoft 365 app credentials — platform admin API, resolution, callback."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker


def _platform_headers(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "ops@marios.platform", "password": "Ops1234!", "tenant_code": "sys"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _demo_tenant_id(client, platform_headers):
    rows = client.get("/api/v1/platform/tenants", headers=platform_headers)
    assert rows.status_code == 200, rows.text
    return next(r["id"] for r in rows.json() if r["code"] == "demo")


class _FakeRes:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


# —— permissions ——
def test_office_config_permissions(client, auth_headers):
    hp = _platform_headers(client)
    tid = _demo_tenant_id(client, hp)
    base = f"/api/v1/platform/tenants/{tid}/office-config"

    # unauthenticated -> 401 (logins above planted a session cookie on the client)
    client.cookies.clear()
    assert client.get(base).status_code == 401
    assert client.put(base, json={}).status_code == 401
    assert client.post(f"{base}/test").status_code == 401

    # tenant admin (not platform_admin) -> 403
    assert client.get(base, headers=auth_headers).status_code == 403
    assert client.put(base, headers=auth_headers, json={}).status_code == 403
    assert client.post(f"{base}/test", headers=auth_headers).status_code == 403

    # platform admin -> 200
    assert client.get(base, headers=hp).status_code == 200


# —— secret mask semantics ——
def test_office_config_secret_mask_semantics(client):
    hp = _platform_headers(client)
    tid = _demo_tenant_id(client, hp)
    base = f"/api/v1/platform/tenants/{tid}/office-config"

    r = client.put(
        base,
        headers=hp,
        json={
            "override_enabled": True,
            "client_id": "tid-123",
            "client_secret": "supersecretvalue9",
            "ms_tenant": "contoso.onmicrosoft.com",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["override_enabled"] is True
    assert body["client_id"] == "tid-123"
    assert body["ms_tenant"] == "contoso.onmicrosoft.com"
    assert body["has_secret"] is True
    assert body["client_secret_masked"] == "••••lue9"
    assert body["effective_mode"] == "tenant"
    assert body["redirect_uri"].endswith("/api/v1/office/oauth/callback")
    # plaintext secret must never appear in any response
    assert "supersecretvalue9" not in r.text

    g = client.get(base, headers=hp)
    assert g.status_code == 200
    assert g.json()["client_secret_masked"] == "••••lue9"
    assert "supersecretvalue9" not in g.text

    # omitting client_secret keeps the stored value
    r2 = client.put(base, headers=hp, json={"client_id": "tid-456"})
    assert r2.json()["client_id"] == "tid-456"
    assert r2.json()["client_secret_masked"] == "••••lue9"

    # empty string also keeps the stored value
    r3 = client.put(base, headers=hp, json={"client_secret": ""})
    assert r3.json()["client_secret_masked"] == "••••lue9"

    # explicit null clears the secret
    r4 = client.put(base, headers=hp, json={"client_secret": None})
    assert r4.json()["client_secret_masked"] is None
    assert r4.json()["has_secret"] is False


# —— resolution priority: tenant override > global env > stub/disabled ——
def test_resolve_ms_config_priority(db_engine, monkeypatch):
    from app.config import get_settings
    from app.models import Tenant
    from app.services.ms_config import effective_mode, resolve_ms_config
    from app.services.ops_crypto import encrypt_secret

    s = get_settings()
    monkeypatch.setattr(s, "microsoft_client_id", "")
    monkeypatch.setattr(s, "microsoft_client_secret", "")
    monkeypatch.setattr(s, "oauth_allow_stub", False)

    TestingSession = sessionmaker(bind=db_engine)
    with TestingSession() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
        assert tenant is not None

        # nothing configured -> none / disabled; stub allowed -> stub
        cfg = resolve_ms_config(db, tenant.id)
        assert cfg.source == "none"
        assert effective_mode(cfg) == "disabled"
        monkeypatch.setattr(s, "oauth_allow_stub", True)
        assert effective_mode(cfg) == "stub"
        monkeypatch.setattr(s, "oauth_allow_stub", False)

        # global env -> global
        monkeypatch.setattr(s, "microsoft_client_id", "gid")
        monkeypatch.setattr(s, "microsoft_client_secret", "gsecret")
        cfg = resolve_ms_config(db, tenant.id)
        assert cfg.source == "global"
        assert cfg.client_id == "gid"
        assert effective_mode(cfg) == "global"

        # tenant override wins over global env; secret is stored encrypted
        tenant.ms_override_enabled = True
        tenant.ms_client_id = "tid"
        tenant.ms_client_secret = encrypt_secret("tsecret")
        tenant.ms_tenant = "contoso"
        db.flush()
        cfg = resolve_ms_config(db, tenant.id)
        assert cfg.source == "tenant"
        assert cfg.client_id == "tid"
        assert cfg.client_secret == "tsecret"
        assert cfg.ms_tenant == "contoso"
        assert effective_mode(cfg) == "tenant"
        db.rollback()


def test_effective_mode_falls_back_to_global_via_api(client, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "microsoft_client_id", "gid")
    monkeypatch.setattr(s, "microsoft_client_secret", "gsecret")

    hp = _platform_headers(client)
    tid = _demo_tenant_id(client, hp)
    base = f"/api/v1/platform/tenants/{tid}/office-config"

    # no tenant override -> effective mode follows the global env config
    g = client.get(base, headers=hp)
    assert g.json()["effective_mode"] == "global"

    # enabling override without a secret is not live -> falls to stub/disabled
    monkeypatch.setattr(s, "oauth_allow_stub", True)
    r = client.put(base, headers=hp, json={"override_enabled": True, "client_id": "tid-only"})
    assert r.json()["effective_mode"] == "stub"


# —— connectivity test endpoint (HTTP layer monkeypatched) ——
def test_office_config_test_success(client, monkeypatch):
    hp = _platform_headers(client)
    tid = _demo_tenant_id(client, hp)
    base = f"/api/v1/platform/tenants/{tid}/office-config"
    client.put(base, headers=hp, json={"override_enabled": True, "client_id": "cid", "client_secret": "csecret"})

    calls = {}

    def fake_request(cfg, *, timeout):
        calls["cfg"] = cfg
        calls["timeout"] = timeout
        return _FakeRes(200, {"access_token": "x", "token_type": "Bearer"})

    monkeypatch.setattr("app.routers.admin_platform.request_client_credentials_token", fake_request)
    r = client.post(f"{base}/test", headers=hp)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["latency_ms"] >= 0
    # the probe must use the tenant's own (decrypted) credentials
    assert calls["cfg"].client_id == "cid"
    assert calls["cfg"].client_secret == "csecret"
    assert calls["timeout"] == 10.0


def test_office_config_test_invalid_client(client, monkeypatch):
    hp = _platform_headers(client)
    tid = _demo_tenant_id(client, hp)
    base = f"/api/v1/platform/tenants/{tid}/office-config"
    client.put(base, headers=hp, json={"override_enabled": True, "client_id": "cid", "client_secret": "wrong"})

    def fake_request(cfg, *, timeout):
        return _FakeRes(401, {"error": "invalid_client", "error_description": "AADSTS7000215: bad secret"})

    monkeypatch.setattr("app.routers.admin_platform.request_client_credentials_token", fake_request)
    r = client.post(f"{base}/test", headers=hp)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "invalid_client" in body["message"]
    assert "client_id" in body["message"] or "Client authentication" in body["message"]


def test_office_config_test_timeout(client, monkeypatch):
    hp = _platform_headers(client)
    tid = _demo_tenant_id(client, hp)
    base = f"/api/v1/platform/tenants/{tid}/office-config"
    client.put(base, headers=hp, json={"override_enabled": True, "client_id": "cid", "client_secret": "csecret"})

    def fake_request(cfg, *, timeout):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr("app.routers.admin_platform.request_client_credentials_token", fake_request)
    r = client.post(f"{base}/test", headers=hp)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "timeout" in body["message"]


def test_office_config_test_no_credentials(client, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "microsoft_client_id", "")
    monkeypatch.setattr(s, "microsoft_client_secret", "")

    hp = _platform_headers(client)
    tid = _demo_tenant_id(client, hp)
    r = client.post(f"/api/v1/platform/tenants/{tid}/office-config/test", headers=hp)
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["latency_ms"] == 0


# —— OAuth callback exchanges with the tenant's own credentials ——
def test_callback_uses_tenant_credentials(client, auth_headers, monkeypatch):
    from app.config import get_settings
    from app.services.identity import soft_sign_state

    hp = _platform_headers(client)
    tid = _demo_tenant_id(client, hp)
    client.put(
        f"/api/v1/platform/tenants/{tid}/office-config",
        headers=hp,
        json={"override_enabled": True, "client_id": "tenant-cid", "client_secret": "tenant-secret-1"},
    )

    captured = {}

    def fake_exchange(code, *, settings=None, ms_config=None):
        captured["code"] = code
        captured["ms_config"] = ms_config
        return {
            "access_token": "stub-access-cb",
            "refresh_token": "stub-refresh-cb",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "",
            "mode": "stub",
        }

    monkeypatch.setattr("app.routers.office.exchange_code_for_tokens", fake_exchange)
    state = soft_sign_state(get_settings().jwt_secret, tid)
    res = client.get(
        f"/api/v1/office/oauth/callback?code=live-code&state={state}",
        headers=auth_headers,
        follow_redirects=False,
    )
    assert res.status_code == 307, res.text
    assert captured["ms_config"] is not None
    assert captured["ms_config"].client_id == "tenant-cid"
    assert captured["ms_config"].client_secret == "tenant-secret-1"
    assert captured["ms_config"].source == "tenant"


# —— tenant-side status transparency ——
def test_office_status_config_source(client, auth_headers, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "microsoft_client_id", "")
    monkeypatch.setattr(s, "microsoft_client_secret", "")
    monkeypatch.setattr(s, "oauth_allow_stub", True)

    st = client.get("/api/v1/office/status", headers=auth_headers)
    assert st.status_code == 200, st.text
    assert st.json()["config_source"] == "stub"

    hp = _platform_headers(client)
    tid = _demo_tenant_id(client, hp)
    client.put(
        f"/api/v1/platform/tenants/{tid}/office-config",
        headers=hp,
        json={"override_enabled": True, "client_id": "tid", "client_secret": "tsec", "ms_tenant": "contoso"},
    )
    st2 = client.get("/api/v1/office/status", headers=auth_headers)
    assert st2.json()["config_source"] == "tenant"
    assert st2.json()["graph_mode"] == "live"
    assert "/contoso/" in (st2.json()["consent_url"] or "")
