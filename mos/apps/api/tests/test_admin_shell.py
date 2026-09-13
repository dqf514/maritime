"""Admin / platform / role-based shell tests."""


def test_role_nav_differs(client):
    def login(email, tenant="demo"):
        r = client.post("/api/v1/auth/login", json={"email": email, "password": "Demo1234!", "tenant_code": tenant})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    charter = client.get("/api/v1/shell/bootstrap", headers=login("charterer@demo.voyageos")).json()
    ops = client.get("/api/v1/shell/bootstrap", headers=login("ops@demo.voyageos")).json()
    admin = client.get("/api/v1/shell/bootstrap", headers=login("admin@demo.voyageos")).json()

    def hrefs(payload):
        out = []
        for sec in payload["navigation"]:
            out.extend(i["href"] for i in sec["items"])
        return set(out)

    ch, oh, ah = hrefs(charter), hrefs(ops), hrefs(admin)
    assert "/estimates" in ch
    assert "/operations/voyages" not in ch
    assert "/operations/voyages" in oh
    assert "/estimates" not in oh
    assert "/settings" in ah
    assert "/admin/users" not in ah
    assert "chartering_day" in [w["id"] for w in charter["workspaces"]]
    assert "ops_night" in [w["id"] for w in ops["workspaces"]]
    assert "/estimates" in charter.get("allowed_paths", [])
    assert "/operations/voyages" not in charter.get("allowed_paths", [])
    assert "/platform" not in charter.get("allowed_paths", [])


def test_omni_search_respects_roles(client):
    def login(email):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Demo1234!", "tenant_code": "demo"},
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    ch = client.get("/api/v1/search", params={"q": "voyage"}, headers=login("charterer@demo.voyageos")).json()
    assert all("/operations/voyages" != (h.get("href") or "") for h in ch)
    assert all(not str(h.get("href") or "").startswith("/platform") for h in ch)

    ops = client.get("/api/v1/search", params={"q": "estimate"}, headers=login("ops@demo.voyageos")).json()
    assert all("/estimates" != (h.get("href") or "") for h in ops)

    fin = client.get("/api/v1/search", params={"q": "finance"}, headers=login("charterer@demo.voyageos")).json()
    assert all("/finance" != (h.get("href") or "") for h in fin)

    ok = client.get("/api/v1/search", params={"q": "estimate"}, headers=login("charterer@demo.voyageos")).json()
    assert any(h.get("href") == "/estimates" for h in ok)

    r = client.post(
        "/api/v1/auth/login",
        json={"email": "ops@voyageos.platform", "password": "Ops1234!", "tenant_code": "sys"},
    )
    assert r.status_code == 200
    ph = {"Authorization": f"Bearer {r.json()['access_token']}"}
    plat_hits = client.get("/api/v1/search", params={"q": "tenant"}, headers=ph).json()
    assert any((h.get("href") or "") == "/platform/tenants" for h in plat_hits)

    no_plat = client.get("/api/v1/search", params={"q": "tenant"}, headers=login("admin@demo.voyageos")).json()
    assert all(not str(h.get("href") or "").startswith("/platform") for h in no_plat)

def test_platform_tenant_lifecycle(client):
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "ops@voyageos.platform", "password": "Ops1234!", "tenant_code": "sys"},
    )
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    boot = client.get("/api/v1/shell/bootstrap", headers=h).json()
    assert boot["is_platform"] is True
    assert any(s["section"] == "platform" for s in boot["navigation"])

    created = client.post(
        "/api/v1/platform/tenants",
        headers=h,
        json={
            "name": "Acme Tankers",
            "code": "acme",
            "profile_tier": "M",
            "admin_email": "admin@acme.example.com",
            "admin_password": "Demo1234!",
        },
    )
    assert created.status_code == 200, created.text
    tid = created.json()["id"]
    tenants = client.get("/api/v1/platform/tenants", headers=h).json()
    assert any(t["code"] == "acme" for t in tenants)

    sus = client.post(f"/api/v1/platform/tenants/{tid}/status", headers=h, json={"status": "suspended"})
    assert sus.status_code == 200
    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@acme.example.com", "password": "Demo1234!", "tenant_code": "acme"},
    )
    assert blocked.status_code == 403

    client.post(f"/api/v1/platform/tenants/{tid}/status", headers=h, json={"status": "active"})
    ok = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@acme.example.com", "password": "Demo1234!", "tenant_code": "acme"},
    )
    assert ok.status_code == 200


def test_tenant_admin_users(client, auth_headers):
    roles = client.get("/api/v1/admin/roles", headers=auth_headers)
    assert roles.status_code == 200
    assert any(r["code"] == "chartering" for r in roles.json())
    users = client.get("/api/v1/admin/users", headers=auth_headers)
    assert users.status_code == 200
    assert any(u["email"] == "charterer@demo.voyageos" for u in users.json())
    created = client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "newhire@demo.voyageos",
            "full_name": "New Hire",
            "password": "Demo1234!",
            "role_codes": ["viewer"],
        },
    )
    assert created.status_code == 200, created.text
    # charterer cannot access admin
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "charterer@demo.voyageos", "password": "Demo1234!", "tenant_code": "demo"},
    )
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    forbidden = client.get("/api/v1/admin/users", headers=h)
    assert forbidden.status_code == 403
