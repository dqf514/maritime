"""Platform ops console APIs."""

from uuid import UUID


def _platform_headers(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "ops@voyageos.platform", "password": "Ops1234!", "tenant_code": "sys"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_ops_overview_and_datasource(client):
    h = _platform_headers(client)
    ov = client.get("/api/v1/platform/ops/overview", headers=h)
    assert ov.status_code == 200, ov.text
    body = ov.json()
    assert body["datasource"]["dialect"] in {"sqlite", "postgresql"}
    assert body["capabilities"]["tenant_db_binding"] is True
    assert body["capabilities"]["tenant_engine_switch"] is False

    ds = client.get("/api/v1/platform/ops/datasource", headers=h)
    assert ds.status_code == 200
    assert "url_masked" in ds.json()

    ping = client.post("/api/v1/platform/ops/datasource/test", headers=h, json={})
    assert ping.status_code == 200
    assert ping.json()["ok"] is True


def test_ops_forbidden_for_tenant_admin(client, auth_headers):
    r = client.get("/api/v1/platform/ops/overview", headers=auth_headers)
    assert r.status_code == 403


def test_datastore_binding_crud_and_test(client):
    h = _platform_headers(client)
    tenants = client.get("/api/v1/platform/tenants", headers=h).json()
    demo = next(t for t in tenants if t["code"] == "demo")
    created = client.post(
        "/api/v1/platform/ops/datastores",
        headers=h,
        json={
            "tenant_id": demo["id"],
            "purpose": "primary",
            "engine": "sqlite",
            "host_mode": "local",
            "display_name": "Demo SQLite",
            "connection_url": "sqlite+pysqlite:///:memory:",
            "routing_policy": "bind_only",
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["connection_hint"]
    assert "***" in row["connection_hint"] or "sqlite" in row["connection_hint"]
    assert "password" not in row
    assert "connection_cipher" not in row

    bid = row["id"]
    tested = client.post(f"/api/v1/platform/ops/datastores/{bid}/test", headers=h)
    assert tested.status_code == 200, tested.text
    assert tested.json()["ok"] is True

    resolved = client.get(f"/api/v1/platform/ops/datastores/resolve/{demo['id']}", headers=h)
    assert resolved.status_code == 200
    assert resolved.json()["use_primary"] is True

    deleted = client.delete(f"/api/v1/platform/ops/datastores/{bid}", headers=h)
    assert deleted.status_code == 200


def test_init_steps_and_run(client):
    h = _platform_headers(client)
    steps = client.get("/api/v1/platform/ops/init/steps", headers=h)
    assert steps.status_code == 200
    rows = steps.json()
    assert len(rows) >= 4
    verify = next(s for s in rows if s["code"] == "verify_ready")
    ran = client.post(f"/api/v1/platform/ops/init/steps/{verify['id']}/run", headers=h)
    assert ran.status_code == 200, ran.text
    assert ran.json()["status"] == "done"


def test_deploy_profiles_apply(client):
    h = _platform_headers(client)
    profiles = client.get("/api/v1/platform/ops/deploy/profiles", headers=h)
    assert profiles.status_code == 200
    rows = profiles.json()
    assert any(p["code"] == "compose_local" for p in rows)
    compose = next(p for p in rows if p["code"] == "compose_local")
    applied = client.post(f"/api/v1/platform/ops/deploy/profiles/{compose['id']}/apply", headers=h)
    assert applied.status_code == 200
    assert applied.json()["apply_log"].get("steps")


def test_monitor_snapshot_and_alerts(client):
    h = _platform_headers(client)
    alerts = client.get("/api/v1/platform/ops/monitor/alerts", headers=h)
    assert alerts.status_code == 200
    assert len(alerts.json()) >= 1
    snap = client.get("/api/v1/platform/ops/monitor/snapshot", headers=h)
    assert snap.status_code == 200
    body = snap.json()
    assert body["metrics"]
    codes = {m["code"] for m in body["metrics"]}
    assert "db.ping_ms" in codes

    rule = alerts.json()[0]
    patched = client.patch(
        f"/api/v1/platform/ops/monitor/alerts/{rule['id']}",
        headers=h,
        json={"enabled": False},
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
