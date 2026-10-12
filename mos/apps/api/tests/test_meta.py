"""Meta endpoints: 状态机转移表 + 实体修订史（Revisions 侧栏数据源）。"""

from __future__ import annotations


def test_transitions_exposed(client, auth_headers):
    r = client.get("/api/v1/meta/transitions", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["voyage"]["planned"] == ["cancelled", "in_progress"]
    assert "paid" in data["invoice"]
    assert len(data) >= 20


def test_transitions_requires_auth(client):
    r = client.get("/api/v1/meta/transitions")
    assert r.status_code == 401


def test_revisions_records_entity_update(client, auth_headers):
    h = auth_headers
    voyages = client.get("/api/v1/voyages", headers=h).json()
    items = voyages["items"] if isinstance(voyages, dict) else voyages
    assert items, "seed should contain a voyage"
    vid = items[0]["id"]

    r = client.patch(f"/api/v1/voyages/{vid}", json={"cargo": "META_TEST_CARGO"}, headers=h)
    assert r.status_code == 200, r.text

    r2 = client.get(f"/api/v1/meta/revisions?entity_type=voyage&entity_id={vid}", headers=h)
    assert r2.status_code == 200, r2.text
    rows = r2.json()["items"]
    hit = next(i for i in rows if i["action"] == "voyage.update")
    assert "cargo" in hit["detail"]["fields"]
    assert hit["created_at"]


def test_revisions_is_tenant_scoped(client, auth_headers, db_engine):
    """别的实体 id 查不到记录（tenant + entity 双过滤）。"""
    r = client.get(
        "/api/v1/meta/revisions?entity_type=voyage&entity_id=00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["items"] == []
