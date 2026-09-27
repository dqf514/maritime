"""D2 租船报价追踪：生命周期 + fix 一键转 CP。"""

from __future__ import annotations


def test_offer_lifecycle_and_fix_to_charter(client, auth_headers):
    h = auth_headers
    created = client.post(
        "/api/v1/offers",
        headers=h,
        json={"charterer_name": "ACME Chartering", "cargo": "Coal 50k", "rate": 22.5, "demurrage_rate": 18000},
    )
    assert created.status_code == 200, created.text
    oid = created.json()["id"]

    # offer → firm → fixed（转 CP）
    assert client.post(f"/api/v1/offers/{oid}/transition?target=firm", headers=h).status_code == 200
    fixed = client.post(f"/api/v1/offers/{oid}/transition?target=fixed", headers=h)
    assert fixed.status_code == 200, fixed.text
    charter_id = fixed.json()["charter_id"]
    assert charter_id

    # 生成的 CP 为 draft 且带运价/滞期
    charter = client.get(f"/api/v1/charters/{charter_id}", headers=h).json()
    assert charter["status"] == "draft"
    assert charter["freight_rate"] == 22.5
    assert charter["demurrage_rate"] == 18000

    rows = client.get("/api/v1/offers?status=fixed", headers=h).json()["items"]
    hit = next(r for r in rows if r["id"] == oid)
    assert hit["charter_id"] == charter_id


def test_offer_illegal_transition_rejected(client, auth_headers):
    h = auth_headers
    oid = client.post("/api/v1/offers", headers=h, json={"charterer_name": "X", "rate": 10}).json()["id"]
    r = client.post(f"/api/v1/offers/{oid}/transition?target=fixed", headers=h)  # offer → fixed 跨级非法
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "INVALID_STATE"


def test_offer_declined_terminal(client, auth_headers):
    h = auth_headers
    oid = client.post("/api/v1/offers", headers=h, json={"charterer_name": "Y"}).json()["id"]
    assert client.post(f"/api/v1/offers/{oid}/transition?target=declined", headers=h).status_code == 200
    r = client.post(f"/api/v1/offers/{oid}/transition?target=firm", headers=h)
    assert r.status_code == 409
