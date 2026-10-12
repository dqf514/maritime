"""C4-P3 数据字典 / UDF 管理.

Covers: definitions CRUD (tenant-scoped), field_key slug validation (422),
duplicate entity+field_key (409), tenant isolation (404 on foreign patch/delete),
and the entity registry.
"""

from __future__ import annotations

from tests.isolation_helpers import create_tenant


def _create(client, h, **kwargs):
    body = {
        "entity": "vessel",
        "field_key": "custom_grade",
        "label_en": "Custom grade",
        "label_zh": "自定义等级",
        "field_type": "text",
        "required": False,
        "active": True,
        **kwargs,
    }
    r = client.post("/api/v1/udf", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── CRUD ────────────────────────────────────────────────────────────────────


def test_udf_crud(client, auth_headers):
    h = auth_headers
    created = _create(client, h)
    assert created["entity"] == "vessel"
    assert created["field_key"] == "custom_grade"
    assert created["label_en"] == "Custom grade"
    assert created["label_zh"] == "自定义等级"
    assert created["field_type"] == "text"
    assert created["active"] is True

    rows = client.get("/api/v1/udf?entity=vessel&include_inactive=true", headers=h).json()
    assert any(r["id"] == created["id"] for r in rows)

    # default listing is active-only
    active_rows = client.get("/api/v1/udf?entity=vessel", headers=h).json()
    assert any(r["id"] == created["id"] for r in active_rows)

    upd = client.patch(
        f"/api/v1/udf/{created['id']}",
        headers=h,
        json={"label_en": "Grade updated", "active": False},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["label_en"] == "Grade updated"
    assert upd.json()["active"] is False

    # inactive rows are hidden from the default list
    after = client.get("/api/v1/udf?entity=vessel", headers=h).json()
    assert not any(r["id"] == created["id"] for r in after)
    with_inactive = client.get("/api/v1/udf?entity=vessel&include_inactive=true", headers=h).json()
    assert any(r["id"] == created["id"] for r in with_inactive)

    deleted = client.delete(f"/api/v1/udf/{created['id']}", headers=h)
    assert deleted.status_code == 200, deleted.text
    after_del = client.get("/api/v1/udf?entity=vessel&include_inactive=true", headers=h).json()
    assert not any(r["id"] == created["id"] for r in after_del)


def test_udf_select_requires_options(client, auth_headers):
    h = auth_headers
    r = client.post(
        "/api/v1/udf",
        headers=h,
        json={"entity": "vessel", "field_key": "hull_type", "field_type": "select"},
    )
    assert r.status_code == 422, r.text

    ok = client.post(
        "/api/v1/udf",
        headers=h,
        json={
            "entity": "vessel",
            "field_key": "hull_type",
            "field_type": "select",
            "options": ["bulk", "tanker", "container"],
        },
    )
    assert ok.status_code == 201, ok.text
    opts = ok.json()["options"]
    assert opts == {"choices": ["bulk", "tanker", "container"]}


def test_udf_invalid_field_type_422(client, auth_headers):
    r = client.post(
        "/api/v1/udf",
        headers=auth_headers,
        json={"entity": "vessel", "field_key": "bad_type", "field_type": "wibble"},
    )
    assert r.status_code == 422, r.text


# ── Slug validation ─────────────────────────────────────────────────────────


def test_udf_field_key_slug_422(client, auth_headers):
    h = auth_headers
    for bad in ("BadKey", "9leading", "with-dash", "with space", "", "a" * 65):
        r = client.post(
            "/api/v1/udf",
            headers=h,
            json={"entity": "vessel", "field_key": bad, "field_type": "text"},
        )
        assert r.status_code == 422, f"field_key={bad!r} should 422, got {r.status_code}: {r.text}"

    # valid slug accepted
    ok = client.post(
        "/api/v1/udf",
        headers=h,
        json={"entity": "vessel", "field_key": "valid_slug_1", "field_type": "text"},
    )
    assert ok.status_code == 201, ok.text


def test_udf_unknown_entity_422(client, auth_headers):
    r = client.post(
        "/api/v1/udf",
        headers=auth_headers,
        json={"entity": "not_an_entity", "field_key": "some_field", "field_type": "text"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "UNKNOWN_ENTITY"


# ── Duplicate ───────────────────────────────────────────────────────────────


def test_udf_duplicate_409(client, auth_headers):
    h = auth_headers
    _create(client, h, field_key="dup_key")
    dup = client.post(
        "/api/v1/udf",
        headers=h,
        json={"entity": "vessel", "field_key": "dup_key", "field_type": "text"},
    )
    assert dup.status_code == 409, dup.text
    assert dup.json()["detail"]["code"] == "UDF_EXISTS"

    # same key on a different entity is fine
    other = client.post(
        "/api/v1/udf",
        headers=h,
        json={"entity": "voyage", "field_key": "dup_key", "field_type": "text"},
    )
    assert other.status_code == 201, other.text


# ── Tenant isolation ────────────────────────────────────────────────────────


def test_udf_tenant_isolation(client, auth_headers):
    h = auth_headers
    created = _create(client, h, field_key="iso_field")

    other_tid, hb = create_tenant(
        client,
        code=f"udfiso{created['id'][:4]}",
        name="UDF Iso",
        admin_email="admin@udfiso.example.com",
    )
    assert other_tid

    foreign_rows = client.get("/api/v1/udf?include_inactive=true", headers=hb).json()
    assert not any(r["id"] == created["id"] for r in foreign_rows)

    # foreign tenant cannot patch / delete the demo definition
    patch = client.patch(f"/api/v1/udf/{created['id']}", headers=hb, json={"active": False})
    assert patch.status_code == 404
    delete = client.delete(f"/api/v1/udf/{created['id']}", headers=hb)
    assert delete.status_code == 404

    # demo tenant still sees its own definition
    rows = client.get("/api/v1/udf?include_inactive=true", headers=h).json()
    assert any(r["id"] == created["id"] for r in rows)


# ── Entity registry ─────────────────────────────────────────────────────────


def test_udf_entity_registry(client, auth_headers):
    r = client.get("/api/v1/udf/entities", headers=auth_headers)
    assert r.status_code == 200, r.text
    entities = r.json()
    assert entities, "registry must not be empty"
    names = {e["entity"] for e in entities}
    assert {"vessel", "voyage", "charter", "invoice"} <= names
    by_name = {e["entity"]: e["label"] for e in entities}
    assert by_name["vessel"] == "Vessel"
