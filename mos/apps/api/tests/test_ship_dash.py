def test_full_demo_seed_and_ship_fleet(client, auth_headers):
    h = auth_headers
    vessels = client.get("/api/v1/masterdata/vessels", headers=h)
    assert vessels.status_code == 200
    assert len(vessels.json()) >= 4

    fleet = client.get("/api/v1/ship/fleet", headers=h)
    assert fleet.status_code == 200, fleet.text
    body = fleet.json()
    assert body["fleet_size"] >= 4
    assert body["open_work_orders"] >= 1
    assert body["expiring_certificates"] >= 1

    vid = body["vessels"][0]["vessel_id"]
    detail = client.get(f"/api/v1/ship/vessels/{vid}", headers=h)
    assert detail.status_code == 200
    assert detail.json()["certificates"]


def test_pms_inbound_and_adapters(client, auth_headers):
    h = auth_headers
    adapters = client.get("/api/v1/ship/integrations/adapters", headers=h)
    assert adapters.status_code == 200
    assert any(a["code"] == "pms.mock" for a in adapters.json())

    fleet = client.get("/api/v1/ship/fleet", headers=h).json()
    imo = fleet["vessels"][0]["imo"]
    sync = client.post(
        "/api/v1/ship/integrations/inbound",
        headers=h,
        json={
            "system": "pms.mock",
            "entity_type": "work_order",
            "external_ref": "TEST-WO-1",
            "vessel_imo": imo,
            "data": {"title": "Imported WO", "priority": "high", "status": "open"},
        },
    )
    assert sync.status_code == 200, sync.text
    assert sync.json()["vessel_resolved"] is True


def test_role_dashboards(client, auth_headers):
    h = auth_headers
    catalog = client.get("/api/v1/dashboards/catalog", headers=h)
    assert catalog.status_code == 200
    assert catalog.json()["screens"]

    for role in ("management", "chartering", "operations", "finance", "technical"):
        snap = client.get(f"/api/v1/dashboards/{role}/snapshot", headers=h)
        assert snap.status_code == 200, snap.text
        data = snap.json()
        assert data["kpis"]
        assert data["live"] is True
        assert data["generated_at"]


def test_tech_user_dashboard(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "tech@demo.marios", "password": "Demo1234!", "tenant_code": "demo"},
    )
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    snap = client.get("/api/v1/dashboards/technical/snapshot", headers=h)
    assert snap.status_code == 200
    assert snap.json()["title"]
    fleet = client.get("/api/v1/ship/fleet", headers=h)
    assert fleet.status_code == 200
