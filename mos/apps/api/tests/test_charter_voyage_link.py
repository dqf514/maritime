"""租约 ↔ 航次联动：激活自动建航次、补建航次（幂等）、COA lifting fix 无航次代建。"""

from __future__ import annotations


def _make_vessel(client, h, tag: str = "cvl") -> dict:
    r = client.post("/api/v1/masterdata/vessels", headers=h, json={"name": f"{tag} vessel"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _make_charter(client, h, *, vessel_id: str | None = None, charter_type: str = "voyage") -> dict:
    body: dict = {"charter_type": charter_type}
    if vessel_id:
        body["vessel_id"] = vessel_id
    r = client.post("/api/v1/charters", headers=h, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _activate(client, h, charter_id: str) -> dict:
    assert (
        client.post(f"/api/v1/charters/{charter_id}/transition", headers=h, json={"target": "pending_approval"}).status_code
        == 200
    )
    r = client.post(f"/api/v1/charters/{charter_id}/transition", headers=h, json={"target": "active"})
    assert r.status_code == 200, r.text
    return r.json()


# ── 激活自动建航次 + 补建幂等 ─────────────────────────────────────────────────


def test_activation_auto_creates_voyage_and_recreate_is_idempotent(client, auth_headers):
    h = auth_headers
    vessel = _make_vessel(client, h)
    charter = _make_charter(client, h, vessel_id=vessel["id"])
    _activate(client, h, charter["id"])

    # 激活副作用：关联航次已存在
    linked = client.get(f"/api/v1/charters/{charter['id']}/voyages", headers=h)
    assert linked.status_code == 200, linked.text
    voyages = linked.json()
    assert len(voyages) == 1
    assert voyages[0]["voyage_no"].startswith("V")
    first_id = voyages[0]["id"]

    # 补建（幂等）：已有存活航次 → created=false，返回同一条
    again = client.post(f"/api/v1/charters/{charter['id']}/voyage", headers=h)
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    assert again.json()["voyage"]["id"] == first_id

    # 删掉航次后再补建 → created=true，新航次号
    assert client.delete(f"/api/v1/voyages/{first_id}", headers=h).status_code == 200
    rebuilt = client.post(f"/api/v1/charters/{charter['id']}/voyage", headers=h)
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["created"] is True
    assert rebuilt.json()["voyage"]["id"] != first_id
    assert rebuilt.json()["voyage"]["voyage_no"].startswith("V")


def test_charter_voyage_requires_active(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h)
    r = client.post(f"/api/v1/charters/{charter['id']}/voyage", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INVALID_STATE"


def test_charter_voyage_works_without_vessel(client, auth_headers):
    """未指定船舶的租约也能补建航次（只是没有日程占用）。"""
    h = auth_headers
    charter = _make_charter(client, h)
    _activate(client, h, charter["id"])
    r = client.post(f"/api/v1/charters/{charter['id']}/voyage", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True


# ── COA lifting fix：无 voyage_id 时自动代建 ─────────────────────────────────


def test_lifting_fix_without_voyage_autocreates(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h, charter_type="coa")
    r = client.post(
        f"/api/v1/charters/{charter['id']}/liftings",
        headers=h,
        params={"period_label": "2026-01", "planned_qty": 30000.0},
    )
    assert r.status_code in (200, 201), r.text
    lifting_id = r.json()["id"]

    r = client.post(
        f"/api/v1/coa-liftings/{lifting_id}/nominate",
        headers=h,
        json={"laycan_from": "2026-01-01T00:00:00Z", "laycan_to": "2026-01-15T00:00:00Z"},
    )
    assert r.status_code == 200, r.text

    # 不传 voyage_id → 代建并回填
    r = client.post(f"/api/v1/coa-liftings/{lifting_id}/fix", headers=h, json={})
    assert r.status_code == 200, r.text
    voyage_id = r.json()["voyage_id"]
    assert voyage_id

    # 代建的航次挂在同一租约下
    linked = client.get(f"/api/v1/charters/{charter['id']}/voyages", headers=h)
    assert linked.status_code == 200
    assert any(v["id"] == voyage_id for v in linked.json())


def test_lifting_fix_with_explicit_voyage_still_works(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h, charter_type="coa")
    r = client.post(
        f"/api/v1/charters/{charter['id']}/liftings",
        headers=h,
        params={"period_label": "2026-02", "planned_qty": 20000.0},
    )
    lifting_id = r.json()["id"]
    client.post(
        f"/api/v1/coa-liftings/{lifting_id}/nominate",
        headers=h,
        json={"laycan_from": "2026-02-01T00:00:00Z", "laycan_to": "2026-02-15T00:00:00Z"},
    )
    v = client.post("/api/v1/voyages", headers=h, json={"voyage_no": "V-TEST-LIFT", "charter_id": charter["id"]})
    assert v.status_code in (200, 201), v.text
    r = client.post(
        f"/api/v1/coa-liftings/{lifting_id}/fix",
        headers=h,
        json={"voyage_id": v.json()["id"]},
    )
    assert r.status_code == 200
    assert r.json()["voyage_id"] == v.json()["id"]
