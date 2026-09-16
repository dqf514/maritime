"""Security regression tests — fixes for config defaults, token handling,
upload validation, rate limiting, tenant suspension and API key binding."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest


def _login(client, email="admin@demo.marios", tenant="demo", password="Demo1234!"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password, "tenant_code": tenant})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _platform_admin(client):
    return _login(client, email="ops@marios.platform", tenant="sys", password="Ops1234!")


def _db_session(db_engine):
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)()


# —— 1. secure config defaults ——
def test_secure_config_defaults():
    from app.config import Settings

    fields = Settings.model_fields
    assert fields["oauth_allow_stub"].default is False
    assert fields["license_dev_unlock"].default == "none"
    assert fields["seed_demo"].default is False
    assert fields["jwt_secret"].default == ""
    assert fields["s3_access_key"].default == ""
    assert fields["s3_secret_key"].default == ""


def test_random_jwt_secret_generated_with_warning():
    from app.config import Settings, get_settings

    s = Settings(jwt_secret="")
    assert s.jwt_secret == ""
    # get_settings() guarantees a non-empty effective secret (random per process)
    assert get_settings().jwt_secret


# —— 2. demo_token removed & mail preview redacted ——
def test_invite_response_has_no_demo_token_and_preview_redacted(client, auth_headers, mail_capture):
    inv = client.post(
        "/api/v1/admin/security/invites",
        headers=auth_headers,
        json={"email": "sec-invite@example.com", "role_codes": ["viewer"]},
    )
    assert inv.status_code == 200, inv.text
    assert "demo_token" not in inv.json()
    raw = mail_capture.extract_token("invite")

    logs = client.get("/api/v1/admin/security/mail-logs", headers=auth_headers)
    assert logs.status_code == 200
    previews = [r["body_preview"] or "" for r in logs.json()]
    assert previews, "expected at least one mail log"
    assert all(raw not in p for p in previews)


def test_magic_link_response_has_no_demo_token(client, auth_headers, mail_capture):
    client.put(
        "/api/v1/admin/security/policy",
        headers=auth_headers,
        json={"magic_link_enabled": True, "require_email_verify": False},
    )
    req = client.post(
        "/api/v1/auth/magic-link/request",
        json={"email": "admin@demo.marios", "tenant_code": "demo"},
    )
    assert req.status_code == 200, req.text
    assert "demo_token" not in req.json()


# —— 3. uploads static mount no longer exposes backups ——
def test_backups_not_served_statically(client, auth_headers):
    created = client.post("/api/v1/settings/dataops/backups", headers=auth_headers)
    assert created.status_code == 200, created.text
    storage_path = created.json()["storage_path"]
    res = client.get(f"/uploads/{storage_path}")
    assert res.status_code == 404


def test_uploads_root_not_mounted(client):
    assert client.get("/uploads/../uploads/anything.json").status_code in (400, 404)
    assert client.get("/uploads/anything.json").status_code == 404


# —— 3b. branding upload: no svg, magic-byte validation ——
def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_branding_upload_rejects_svg(client):
    h = _platform_admin(client)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    res = client.post(
        "/api/v1/platform/branding/upload?kind=logo",
        headers=h,
        files={"file": ("logo.svg", io.BytesIO(svg), "image/svg+xml")},
    )
    assert res.status_code == 400


def test_branding_upload_validates_magic_bytes(client):
    h = _platform_admin(client)
    fake_png = io.BytesIO(b"not-a-real-png" * 10)
    res = client.post(
        "/api/v1/platform/branding/upload?kind=logo",
        headers=h,
        files={"file": ("logo.png", fake_png, "image/png")},
    )
    assert res.status_code == 400

    ok = client.post(
        "/api/v1/platform/branding/upload?kind=logo",
        headers=h,
        files={"file": ("logo.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert ok.status_code == 200, ok.text


# —— 4. recycle bin: admin-only + sanitized payload ——
def test_recycle_list_requires_admin(client):
    viewer = _login(client, email="charterer@demo.marios")
    res = client.get("/api/v1/recycle-bin", headers=viewer)
    assert res.status_code == 403

    admin = _login(client)
    assert client.get("/api/v1/recycle-bin", headers=admin).status_code == 200


def test_recycle_payload_strips_secrets():
    from app.models import User
    from app.services.recycle import row_to_payload, sanitize_payload

    user = User(email="x@y.z", password_hash="$2b$secret", status="active")
    payload = row_to_payload(user)
    assert "password_hash" not in payload

    masked = sanitize_payload({"config": {"host": "imap.example.com", "inbound_secret": "s3cr3t", "port": 993}})
    assert masked["config"]["inbound_secret"] == "***"
    assert masked["config"]["host"] == "imap.example.com"


# —— 6. office oauth state signature ——
def test_office_callback_requires_auth_and_valid_state(client, oauth_stub):
    from app.config import get_settings
    from app.services.identity import soft_sign_state

    # unauthenticated -> 401
    res = client.get("/api/v1/office/oauth/callback?code=abc&state=whatever")
    assert res.status_code == 401

    h = _login(client)
    # tampered state -> 400
    res = client.get("/api/v1/office/oauth/callback?code=abc&state=tampered.state", headers=h)
    assert res.status_code == 400

    # correctly signed state for the caller's tenant -> accepted
    me = client.get("/api/v1/me", headers=h)
    tenant_id = me.json()["tenant"]["id"]
    state = soft_sign_state(get_settings().jwt_secret, tenant_id)
    ok = client.get(
        f"/api/v1/office/oauth/callback?code=stub-code&state={state}",
        headers=h,
        follow_redirects=False,
    )
    assert ok.status_code == 307  # redirect to web app on success


# —— 7. CORS ——
def test_cors_no_wildcard_with_credentials(client):
    res = client.options(
        "/api/v1/me",
        headers={"Origin": "http://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    allow = res.headers.get("access-control-allow-origin", "")
    assert allow != "*"
    assert "evil.example.com" not in allow


# —— 8. rate limiting ——
def test_login_rate_limited(client, monkeypatch):
    from app.config import get_settings
    from app.services.ratelimit import _limiters

    _limiters.pop("auth.login", None)
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    for i in range(5):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@demo.marios", "password": "wrong", "tenant_code": "demo"},
        )
        assert r.status_code == 401, f"attempt {i} unexpectedly {r.status_code}"
    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@demo.marios", "password": "wrong", "tenant_code": "demo"},
    )
    assert blocked.status_code == 429
    _limiters.pop("auth.login", None)


# —— 9. tenant suspension + password version revocation ——
def test_suspended_tenant_rejected(client, db_engine):
    from sqlalchemy import select

    from app.models import Tenant

    h = _login(client)
    assert client.get("/api/v1/me", headers=h).status_code == 200
    with _db_session(db_engine) as db:
        tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
        tenant.status = "suspended"
        db.commit()
    try:
        res = client.get("/api/v1/me", headers=h)
        assert res.status_code == 403
        # fresh login is also refused
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@demo.marios", "password": "Demo1234!", "tenant_code": "demo"},
        )
        assert login.status_code == 403
    finally:
        with _db_session(db_engine) as db:
            tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
            tenant.status = "active"
            db.commit()


def test_password_change_revokes_old_tokens(client):
    h = _login(client)
    assert client.get("/api/v1/me", headers=h).status_code == 200
    chg = client.post(
        "/api/v1/me/security/password",
        headers=h,
        json={"current_password": "Demo1234!", "new_password": "NewPass123!"},
    )
    assert chg.status_code == 200, chg.text
    # old token revoked
    assert client.get("/api/v1/me", headers=h).status_code == 401
    # new password works
    h2 = _login(client, password="NewPass123!")
    assert client.get("/api/v1/me", headers=h2).status_code == 200
    # restore for other tests sharing this db fixture scope
    client.post(
        "/api/v1/me/security/password",
        headers=h2,
        json={"current_password": "NewPass123!", "new_password": "Demo1234!"},
    )


# —— 10. API key user binding, scope check, expiry ——
def test_api_key_bound_to_creator_and_scoped(client, db_engine):
    from sqlalchemy import select

    from app.models import ApiKey, User

    h = _login(client)
    me = client.get("/api/v1/me", headers=h).json()
    created = client.post("/api/v1/settings/api-keys", headers=h, json={"name": "sec-key", "scopes": ["office"]})
    assert created.status_code == 200, created.text
    raw = created.json()["raw_key"]

    with _db_session(db_engine) as db:
        row = db.scalar(select(ApiKey).where(ApiKey.key_prefix == created.json()["key_prefix"]))
        assert row.user_id is not None
        creator = db.scalar(select(User).where(User.email == "admin@demo.marios"))
        assert row.user_id == creator.id

    ping = client.get("/api/v1/office/partner/ping", headers={"X-API-Key": raw})
    assert ping.status_code == 200, ping.text
    assert ping.json()["user_id"] == me["user"]["id"]

    # key without the required scope is rejected on scoped endpoints
    created2 = client.post("/api/v1/settings/api-keys", headers=h, json={"name": "read-only", "scopes": ["read"]})
    raw2 = created2.json()["raw_key"]
    denied = client.get("/api/v1/office/partner/ping", headers={"X-API-Key": raw2})
    assert denied.status_code == 403


def test_expired_api_key_rejected(client, db_engine):
    from sqlalchemy import select

    from app.models import ApiKey

    h = _login(client)
    created = client.post("/api/v1/settings/api-keys", headers=h, json={"name": "exp-key", "scopes": ["office"]})
    raw = created.json()["raw_key"]
    assert client.get("/api/v1/office/partner/ping", headers={"X-API-Key": raw}).status_code == 200

    with _db_session(db_engine) as db:
        row = db.scalar(select(ApiKey).where(ApiKey.key_prefix == created.json()["key_prefix"]))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.get("/api/v1/office/partner/ping", headers={"X-API-Key": raw}).status_code == 401


# —— 11. Excel upload validation ——
def _migration_job(client, h) -> str:
    job = client.post("/api/v1/settings/dataops/migrations", headers=h, json={"note": "sec"})
    assert job.status_code == 200, job.text
    return job.json()["id"]


def test_excel_upload_validation(client, auth_headers):
    job_id = _migration_job(client, auth_headers)
    # wrong extension
    bad_ext = client.post(
        f"/api/v1/settings/dataops/migrations/{job_id}/upload-excel",
        headers=auth_headers,
        files={"file": ("data.csv", io.BytesIO(b"a,b,c"), "text/csv")},
    )
    assert bad_ext.status_code == 400
    # right extension, non-zip content
    bad_zip = client.post(
        f"/api/v1/settings/dataops/migrations/{job_id}/upload-excel",
        headers=auth_headers,
        files={"file": ("data.xlsx", io.BytesIO(b"definitely not a zip"), "application/vnd.ms-excel")},
    )
    assert bad_zip.status_code == 400


# —— 12. readyz error hygiene ——
def test_readyz_hides_exception_details(client, monkeypatch):
    from app import main as main_mod

    class _Boom:
        def __enter__(self):
            raise RuntimeError("postgres://user:supersecret@db.internal:5432")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(main_mod.engine, "connect", lambda: _Boom())
    res = client.get("/readyz")
    assert res.status_code == 503
    assert "supersecret" not in res.text
    assert res.json()["status"] == "not_ready"


# —— office token at-rest encryption ——
def test_office_tokens_encrypted_at_rest(client, db_engine, oauth_stub):
    from sqlalchemy import select

    from app.models import Tenant
    from app.models_office import OfficeTenantLink

    h = _login(client)
    conn = client.get("/api/v1/office/connect", headers=h)
    assert conn.status_code == 200, conn.text

    with _db_session(db_engine) as db:
        tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
        link = db.scalar(select(OfficeTenantLink).where(OfficeTenantLink.tenant_id == tenant.id))
        assert link.access_token and link.access_token.startswith("v1:")
        assert "stub-access" not in link.access_token

    # decrypted path still works
    mail = client.get("/api/v1/office/mail", headers=h)
    assert mail.status_code == 200
