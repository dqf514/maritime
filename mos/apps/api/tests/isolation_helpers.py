"""Shared helpers for the tenant-isolation gate (tests/test_tenant_isolation.py).

Builds a second real tenant through the platform-admin API (same pattern as
tests/test_business_integrity.py) and bootstraps a full set of core resources
so the abuse matrix can attack concrete foreign IDs.
"""

from __future__ import annotations

from uuid import uuid4

API = "/api/v1"

PLATFORM_EMAIL = "ops@voyageos.platform"
PLATFORM_TENANT = "sys"
PLATFORM_PASSWORD = "Ops1234!"


def login(client, email: str, tenant_code: str = "demo", password: str = "Demo1234!") -> dict[str, str]:
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password, "tenant_code": tenant_code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def platform_login(client) -> dict[str, str]:
    return login(client, PLATFORM_EMAIL, tenant_code=PLATFORM_TENANT, password=PLATFORM_PASSWORD)


def create_tenant(client, *, code: str, name: str, admin_email: str, admin_password: str = "Demo1234!") -> tuple[str, dict[str, str]]:
    """Create a tenant via the platform API; return (tenant_id, admin_headers)."""
    hp = platform_login(client)
    r = client.post(
        f"{API}/platform/tenants",
        headers=hp,
        json={
            "name": name,
            "code": code,
            "profile_tier": "M",
            "admin_email": admin_email,
            "admin_password": admin_password,
        },
    )
    assert r.status_code == 200, r.text
    # login emails are normalized to lowercase by the identity layer
    return r.json()["id"], login(client, admin_email.lower(), tenant_code=code, password=admin_password)


def _post(client, url: str, headers: dict, **kwargs) -> dict:
    r = client.post(f"{API}{url}", headers=headers, **kwargs)
    assert r.status_code == 200, f"POST {url} -> {r.status_code}: {r.text}"
    return r.json()


def bootstrap_resources(client, h: dict[str, str], tag: str) -> dict[str, str]:
    """Create one of each core resource inside a tenant; return its ids."""
    uniq = uuid4().hex[:6]
    ids: dict[str, str] = {}

    vessel = _post(client, "/masterdata/vessels", h, json={"name": f"{tag} Vessel {uniq}"})
    ids["vessel_id"] = vessel["id"]

    cp = _post(client, "/masterdata/counterparties", h, json={"name": f"{tag} CP {uniq}", "type": "charterer"})
    ids["counterparty_id"] = cp["id"]

    est = _post(client, "/estimates", h, json={"title": f"{tag} EST {uniq}", "mode": "voyage", "inputs": {}})
    ids["estimate_id"] = est["id"]

    ch = _post(client, "/charters", h, json={"charter_type": "voyage", "counterparty_id": cp["id"]})
    ids["charter_id"] = ch["id"]

    voy = _post(
        client,
        "/voyages",
        h,
        json={"voyage_no": f"{tag}-{uniq}", "vessel_id": vessel["id"], "charter_id": ch["id"]},
    )
    ids["voyage_id"] = voy["id"]

    pc = _post(client, "/port-calls", h, json={"voyage_id": voy["id"], "seq": 1, "purpose": "load"})
    ids["port_call_id"] = pc["id"]

    lt = _post(
        client,
        "/laytimes",
        h,
        json={"voyage_id": voy["id"], "port_call_id": pc["id"], "inputs": {"allowed_hours": 24, "events": []}},
    )
    ids["laytime_id"] = lt["id"]

    cl = _post(client, "/claims", h, json={"voyage_id": voy["id"], "amount": 1000, "claim_type": "demurrage"})
    ids["claim_id"] = cl["id"]

    inv = _post(client, "/invoices", h, json={"counterparty_id": cp["id"], "voyage_id": voy["id"], "amount": 500})
    ids["invoice_id"] = inv["id"]

    cn = _post(client, f"/invoices/{inv['id']}/credit-note", h, json={"amount": 100, "reason": f"{tag} correction"})
    ids["credit_note_id"] = cn["id"]

    bo = _post(
        client,
        "/bunker-orders",
        h,
        json={"vessel_id": vessel["id"], "voyage_id": voy["id"], "grade": "VLSFO", "qty_ordered": 100, "unit_price": 600},
    )
    ids["bunker_order_id"] = bo["id"]

    wo = _post(
        client,
        "/ship/work-orders",
        h,
        json={"vessel_id": vessel["id"], "wo_no": f"WO-{uniq}", "title": f"{tag} WO {uniq}"},
    )
    ids["work_order_id"] = wo["id"]

    user = _post(
        client,
        "/admin/users",
        h,
        json={
            "email": f"crew-{tag.lower()}-{uniq}@example.com",
            "full_name": f"{tag} Crew {uniq}",
            "password": "Demo1234!",
            "role_codes": ["viewer"],
        },
    )
    ids["user_id"] = user["id"]

    return ids


def make_recycle_entry(client, h: dict[str, str], tag: str = "RB") -> tuple[str, str]:
    """Create then soft-delete a vessel; return (recycle_item_id, vessel_id)."""
    vessel = _post(client, "/masterdata/vessels", h, json={"name": f"{tag} scrap {uuid4().hex[:6]}"})
    r = client.delete(f"{API}/masterdata/vessels/{vessel['id']}", headers=h)
    assert r.status_code == 200, r.text
    items = client.get(f"{API}/recycle-bin", headers=h)
    assert items.status_code == 200, items.text
    hit = next(i for i in items.json() if i["entity_type"] == "vessel" and i["entity_id"] == vessel["id"])
    return hit["id"], vessel["id"]


def assert_blocked(resp, what: str) -> None:
    """Cross-tenant access must be denied — 404 preferred (no existence leak), 403 tolerated."""
    assert resp.status_code in (403, 404), f"{what}: expected 403/404, got {resp.status_code}: {resp.text[:300]}"
