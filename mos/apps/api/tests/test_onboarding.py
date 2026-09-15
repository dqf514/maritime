"""New-user onboarding checklist — /onboarding."""

from __future__ import annotations

from uuid import uuid4


def _login(client, email, tenant="demo", password="Demo1234!"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password, "tenant_code": tenant})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _keys(body):
    return [i["key"] for i in body["items"]]


def test_onboarding_structure(client, auth_headers):
    r = client.get("/api/v1/onboarding", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert 1 <= len(body["items"]) <= 8
    for item in body["items"]:
        assert item["key"]
        assert item["label"]["en"] and item["label"]["zh"]
        assert item["hint"]["en"] and item["hint"]["zh"]
        assert isinstance(item["done"], bool)
        assert item["href"].startswith("/")
    assert body["progress"]["total"] == len(body["items"])
    assert body["progress"]["done"] == sum(1 for i in body["items"] if i["done"])
    assert body["dismissed"] is False


def test_onboarding_role_specific_items(client):
    cases = {
        "admin@demo.voyageos": {"company_profile_done", "has_users", "has_vessels", "has_counterparties", "dq_scan_run"},
        "ops@demo.voyageos": {"has_voyage", "has_port_call", "has_noon_report", "has_laytime"},
        "charterer@demo.voyageos": {"has_estimate", "has_charter"},
        "finance@demo.voyageos": {"has_invoice", "has_payment"},
        "demurrage@demo.voyageos": {"has_laytime", "has_claim"},
        "tech@demo.voyageos": {"has_ship_profile", "has_cert", "has_cert_file"},
    }
    for email, expected in cases.items():
        body = client.get("/api/v1/onboarding", headers=_login(client, email)).json()
        assert expected.issubset(set(_keys(body))), f"{email}: {_keys(body)}"
        assert len(body["items"]) <= 8


def test_onboarding_demo_data_detection(client):
    admin = client.get("/api/v1/onboarding", headers=_login(client, "admin@demo.voyageos")).json()
    by_key = {i["key"]: i["done"] for i in admin["items"]}
    # First item is an always-done encouragement
    assert by_key["view_home"] is True
    # Seeded demo data satisfies the setup items
    assert by_key["has_users"] is True
    assert by_key["has_vessels"] is True
    assert by_key["has_counterparties"] is True
    assert by_key["company_profile_done"] is True
    # Nobody ran a DQ scan or received a notification yet in a fresh seed
    assert by_key["dq_scan_run"] is False
    assert 0 < admin["progress"]["done"] < admin["progress"]["total"]

    ops = client.get("/api/v1/onboarding", headers=_login(client, "ops@demo.voyageos")).json()
    ops_done = {i["key"]: i["done"] for i in ops["items"]}
    assert ops_done["has_voyage"] is True
    assert ops_done["has_noon_report"] is True
    assert ops_done["has_laytime"] is True

    tech = client.get("/api/v1/onboarding", headers=_login(client, "tech@demo.voyageos")).json()
    tech_done = {i["key"]: i["done"] for i in tech["items"]}
    assert tech_done["has_ship_profile"] is True
    assert tech_done["has_cert"] is True
    assert tech_done["has_cert_file"] is False  # no certificate file uploaded in seed


def test_onboarding_viewer_fallback_items(client, auth_headers):
    uniq = uuid4().hex[:8]
    email = f"viewer-{uniq}@example.com"
    r = client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={"email": email, "full_name": "V Viewer", "password": "Demo1234!", "role_codes": ["viewer"]},
    )
    assert r.status_code == 200, r.text
    body = client.get("/api/v1/onboarding", headers=_login(client, email)).json()
    assert set(_keys(body)) == {"view_home", "has_notification", "has_tasks"}
    assert body["items"][0]["done"] is True


def test_onboarding_dismiss_and_reset(client, auth_headers):
    r = client.post("/api/v1/onboarding/dismiss", headers=auth_headers)
    assert r.status_code == 200 and r.json()["dismissed"] is True
    assert client.get("/api/v1/onboarding", headers=auth_headers).json()["dismissed"] is True
    # dismiss is idempotent
    assert client.post("/api/v1/onboarding/dismiss", headers=auth_headers).json()["dismissed"] is True

    r = client.post("/api/v1/onboarding/reset", headers=auth_headers)
    assert r.status_code == 200 and r.json()["dismissed"] is False
    assert client.get("/api/v1/onboarding", headers=auth_headers).json()["dismissed"] is False


def test_onboarding_requires_login(client):
    assert client.get("/api/v1/onboarding").status_code == 401
    assert client.post("/api/v1/onboarding/dismiss").status_code == 401
