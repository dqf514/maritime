"""C4 字段级权限（Field-level permissions）.

Covers: FieldPermission CRUD (tenant-scoped), write enforcement on
counterparty/vessel updates (403 FIELD_NOT_PERMITTED), additive default when
no rules exist, hidden-field filtering on GET, and the entity registry.
"""

from __future__ import annotations

from tests.isolation_helpers import create_tenant


def _create_rule(client, h, **kwargs):
    body = {"entity": "counterparty", "field": "credit_rating", "role": "tenant_admin", "mode": "read", **kwargs}
    r = client.post("/api/v1/field-permissions", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _make_counterparty(client, h, name="Capesize Chartering"):
    r = client.post(
        "/api/v1/masterdata/counterparties",
        headers=h,
        json={"name": name, "type": "owner", "credit_rating": "BBB"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _make_vessel(client, h, name="MV Aurora", imo="9123456"):
    r = client.post(
        "/api/v1/masterdata/vessels",
        headers=h,
        json={"name": name, "imo": imo},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── CRUD ────────────────────────────────────────────────────────────────────


def test_field_perm_crud_tenant_scoped(client, auth_headers):
    h = auth_headers
    created = _create_rule(client, h)
    assert created["entity"] == "counterparty"
    assert created["field"] == "credit_rating"
    assert created["role"] == "tenant_admin"
    assert created["mode"] == "read"
    assert created["active"] is True

    rows = client.get("/api/v1/field-permissions", headers=h).json()
    assert any(r["id"] == created["id"] for r in rows)

    # duplicate tenant+entity+field+role rejected
    dup = client.post(
        "/api/v1/field-permissions",
        headers=h,
        json={"entity": "counterparty", "field": "credit_rating", "role": "tenant_admin", "mode": "write"},
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "FIELD_PERM_EXISTS"

    upd = client.patch(f"/api/v1/field-permissions/{created['id']}", headers=h, json={"mode": "hidden"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["mode"] == "hidden"

    deleted = client.delete(f"/api/v1/field-permissions/{created['id']}", headers=h)
    assert deleted.status_code == 200, deleted.text
    rows_after = client.get("/api/v1/field-permissions", headers=h).json()
    assert not any(r["id"] == created["id"] for r in rows_after)


def test_field_perm_tenant_isolation(client, auth_headers):
    h = auth_headers
    created = _create_rule(client, h)

    other_tid, hb = create_tenant(
        client,
        code=f"fpiso{created['id'][:4]}",
        name="FP Iso",
        admin_email="admin@fpiso.example.com",
    )
    assert other_tid

    foreign_rows = client.get("/api/v1/field-permissions", headers=hb).json()
    assert not any(r["id"] == created["id"] for r in foreign_rows)

    # foreign tenant cannot patch / delete the demo rule
    patch = client.patch(f"/api/v1/field-permissions/{created['id']}", headers=hb, json={"mode": "write"})
    assert patch.status_code == 404
    delete = client.delete(f"/api/v1/field-permissions/{created['id']}", headers=hb)
    assert delete.status_code == 404

    # demo tenant still sees its own rule
    rows = client.get("/api/v1/field-permissions", headers=h).json()
    assert any(r["id"] == created["id"] for r in rows)


# ── Enforcement ─────────────────────────────────────────────────────────────


def test_write_readonly_field_forbidden(client, auth_headers):
    h = auth_headers
    _create_rule(client, h, entity="counterparty", field="credit_rating", role="tenant_admin", mode="read")
    party = _make_counterparty(client, h)

    r = client.patch(
        f"/api/v1/masterdata/counterparties/{party['id']}",
        headers=h,
        json={"name": party["name"], "credit_rating": "AA"},
    )
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "FIELD_NOT_PERMITTED"
    assert "credit_rating" in detail["message"]

    # vessel field rule is enforced on the vessel path
    _create_rule(client, h, entity="vessel", field="flag", role="tenant_admin", mode="hidden")
    vessel = _make_vessel(client, h)
    rv = client.patch(
        f"/api/v1/masterdata/vessels/{vessel['id']}",
        headers=h,
        json={"name": vessel["name"], "imo": vessel["imo"], "flag": "MH"},
    )
    assert rv.status_code == 403, rv.text
    assert rv.json()["detail"]["code"] == "FIELD_NOT_PERMITTED"


def test_write_allowed_without_rules(client, auth_headers):
    h = auth_headers
    party = _make_counterparty(client, h)
    r = client.patch(
        f"/api/v1/masterdata/counterparties/{party['id']}",
        headers=h,
        json={"name": "Renamed Chartering", "credit_rating": "AA", "type": "owner"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["credit_rating"] == "AA"

    vessel = _make_vessel(client, h, imo="9988776")
    rv = client.patch(
        f"/api/v1/masterdata/vessels/{vessel['id']}",
        headers=h,
        json={"name": "MV Renamed", "imo": "9988776", "flag": "LR"},
    )
    assert rv.status_code == 200, rv.text
    assert rv.json()["flag"] == "LR"


def test_hidden_field_filtered_from_get(client, auth_headers):
    h = auth_headers
    _create_rule(client, h, entity="counterparty", field="notes", role="tenant_admin", mode="hidden")
    party = _make_counterparty(client, h)

    r = client.get(f"/api/v1/masterdata/counterparties/{party['id']}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "notes" not in body
    assert body["name"] == party["name"]

    # with no hidden rules the field is present (additive default)
    rows = client.get("/api/v1/field-permissions", headers=h).json()
    for row in rows:
        deleted = client.delete(f"/api/v1/field-permissions/{row['id']}", headers=h)
        assert deleted.status_code == 200
    r2 = client.get(f"/api/v1/masterdata/counterparties/{party['id']}", headers=h)
    assert r2.status_code == 200
    assert "notes" in r2.json()


# ── Entity registry ─────────────────────────────────────────────────────────


def test_entity_registry_non_empty(client, auth_headers):
    r = client.get("/api/v1/field-permissions/entities", headers=auth_headers)
    assert r.status_code == 200, r.text
    entities = r.json()
    assert entities, "registry must not be empty"
    names = {e["entity"] for e in entities}
    assert {"counterparty", "vessel", "invoice", "port"} <= names
    by_name = {e["entity"]: e["fields"] for e in entities}
    assert "credit_rating" in by_name["counterparty"]
    assert "imo" in by_name["vessel"]
    assert "amount" in by_name["invoice"]
    assert "unlocode" in by_name["port"]
