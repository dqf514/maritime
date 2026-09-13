"""Office ecosystem — stub Graph connect, sync, Teams, webhooks, API key."""

from __future__ import annotations


def _login(client, email="admin@demo.voyageos"):
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Demo1234!", "tenant_code": "demo"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_office_status_and_stub_connect(client):
    h = _login(client)
    st = client.get("/api/v1/office/status", headers=h)
    assert st.status_code == 200, st.text
    body = st.json()
    assert body["graph_mode"] in ("stub", "live", "disabled")
    assert "addons" in body
    assert any(a.get("id") == "teams" for a in body["addons"])

    conn = client.get("/api/v1/office/connect", headers=h)
    assert conn.status_code == 200, conn.text
    data = conn.json()
    assert data.get("connected") is True or data.get("authorize_url")

    health = client.get("/api/v1/office/health", headers=h)
    assert health.status_code == 200, health.text
    assert health.json().get("ok") is True


def test_office_sync_mail_files_teams(client):
    h = _login(client)
    client.get("/api/v1/office/connect", headers=h)

    for channel in ("mail", "onedrive", "sharepoint", "teams"):
        res = client.post("/api/v1/office/sync", headers=h, json={"channel": channel})
        assert res.status_code == 200, res.text
        assert res.json()["status"] in ("done", "failed")
        assert res.json()["channel"] == channel

    mail = client.get("/api/v1/office/mail", headers=h)
    assert mail.status_code == 200
    assert len(mail.json()["items"]) >= 1

    drives = client.get("/api/v1/office/drives", headers=h)
    assert drives.status_code == 200
    assert len(drives.json()["items"]) >= 1

    teams = client.get("/api/v1/office/teams", headers=h)
    assert teams.status_code == 200
    assert len(teams.json()["items"]) >= 1

    notify = client.post(
        "/api/v1/office/teams/notify",
        headers=h,
        json={"text": "<b>VoyageOS</b> test alert"},
    )
    assert notify.status_code == 200, notify.text
    assert notify.json().get("id")


def test_office_webhook_and_addon(client):
    h = _login(client)
    wh = client.post(
        "/api/v1/office/webhooks",
        headers=h,
        json={"name": "test-hook", "target_url": "stub://automate", "events": ["*"]},
    )
    assert wh.status_code == 200, wh.text
    wid = wh.json()["id"]
    assert wh.json().get("secret")

    test = client.post(f"/api/v1/office/webhooks/{wid}/test", headers=h)
    assert test.status_code == 200
    assert test.json()["status"] == "delivered"

    addon = client.post("/api/v1/office/addons/outlook", headers=h, json={"status": "installed"})
    assert addon.status_code == 200
    assert addon.json()["status"] == "installed"


def test_office_partner_api_key(client):
    h = _login(client)
    created = client.post(
        "/api/v1/settings/api-keys",
        headers=h,
        json={"name": "office-addin", "scopes": ["office"]},
    )
    assert created.status_code == 200, created.text
    raw = created.json()["raw_key"]
    assert raw.startswith("vos_")

    ping = client.get("/api/v1/office/partner/ping", headers={"X-API-Key": raw})
    assert ping.status_code == 200, ping.text
    assert ping.json()["ok"] is True
    assert ping.json()["ecosystem"] == "office"


def test_connectors_catalog_has_office(client):
    h = _login(client)
    cat = client.get("/api/v1/settings/connectors/catalog", headers=h)
    assert cat.status_code == 200
    types = {c["connector_type"] for c in cat.json()}
    for need in ("m365_mail", "teams", "sharepoint", "onedrive", "m365_files"):
        assert need in types


def test_healthz_office_version(client):
    hz = client.get("/healthz")
    assert hz.status_code == 200
    assert "office" in hz.json()["version"] or hz.json()["version"].startswith("1.5")
