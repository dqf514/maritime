"""Surface smoke — key product APIs used by desks, help, office, platform ops."""

from __future__ import annotations


def _login(client, email="admin@demo.voyageos", tenant="demo", password="Demo1234!"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password, "tenant_code": tenant})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_smoke_tenant_surface(client):
    h = _login(client)
    paths = [
        "/healthz",
        "/api/v1/me",
        "/api/v1/shell/bootstrap",
        "/api/v1/estimates",
        "/api/v1/charters",
        "/api/v1/voyages",
        "/api/v1/laytimes",
        "/api/v1/invoices",
        "/api/v1/masterdata/vessels",
        "/api/v1/masterdata/ports",
        "/api/v1/masterdata/counterparties",
        "/api/v1/analytics/reports/voyage-pnl",
        "/api/v1/ship/fleet",
        "/api/v1/office/status",
        "/api/v1/settings/connectors/catalog",
        "/api/v1/help/catalog?locale=en",
    ]
    for path in paths:
        res = client.get(path, headers=h if path.startswith("/api") else None)
        assert res.status_code == 200, f"{path} -> {res.status_code} {res.text[:200]}"


def test_smoke_help_ask_and_search(client):
    s = client.get("/api/v1/help/search", params={"q": "Teams", "locale": "zh-CN"})
    assert s.status_code == 200
    assert len(s.json()["items"]) >= 1
    a = client.post("/api/v1/help/ask", json={"question": "如何连接 Teams？", "locale": "zh-CN"})
    assert a.status_code == 200
    assert "365" in a.json()["answer"] or "Office" in a.json()["answer"] or "Teams" in a.json()["answer"]
    art = client.get("/api/v1/help/articles/welcome", params={"locale": "en"})
    assert art.status_code == 200
    assert art.json()["slug"] == "welcome"


def test_smoke_office_connect_stub(client):
    h = _login(client)
    c = client.get("/api/v1/office/connect", headers=h)
    assert c.status_code == 200
    health = client.get("/api/v1/office/health", headers=h)
    assert health.status_code == 200
    assert health.json().get("ok") is True


def test_smoke_platform_ops(client):
    h = _login(client, email="ops@voyageos.platform", tenant="sys", password="Ops1234!")
    for path in (
        "/api/v1/platform/ops/overview",
        "/api/v1/platform/ops/datasource",
        "/api/v1/platform/ops/init/steps",
        "/api/v1/platform/ops/deploy/profiles",
        "/api/v1/platform/ops/monitor/snapshot",
        "/api/v1/platform/ops/monitor/alerts",
    ):
        res = client.get(path, headers=h)
        assert res.status_code == 200, f"{path} -> {res.status_code} {res.text[:200]}"
