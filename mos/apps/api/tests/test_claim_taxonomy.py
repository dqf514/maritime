"""D10 索赔分类体系：受控字典校验 + 过滤 + 字典端点。"""

from __future__ import annotations


def test_claim_types_catalog(client, auth_headers):
    body = client.get("/api/v1/claims/types", headers=auth_headers).json()
    codes = {i["code"] for i in body["items"]}
    assert {"demurrage", "despatch", "off_hire", "performance", "cargo_damage", "other"} <= codes
    for i in body["items"]:
        assert i["gl_account"]
        assert set(i["label"].keys()) == {"en", "zh"}
        assert i["time_bar_days"] > 0


def test_create_claim_validates_type(client, auth_headers):
    ok = client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={"amount": 100, "claim_type": "performance"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["claim_type"] == "performance"

    bad = client.post(
        "/api/v1/claims",
        headers=auth_headers,
        json={"amount": 100, "claim_type": "bogus_type"},
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "INVALID_CLAIM_TYPE"
    assert "demurrage" in bad.json()["detail"]["allowed"]


def test_patch_claim_type_validated(client, auth_headers):
    claim = client.post("/api/v1/claims", headers=auth_headers, json={"amount": 5}).json()
    ok = client.patch(f"/api/v1/claims/{claim['id']}", headers=auth_headers, json={"claim_type": "off_hire"})
    assert ok.status_code == 200, ok.text
    detail = client.get(f"/api/v1/claims/{claim['id']}", headers=auth_headers).json()
    assert detail["claim_type"] == "off_hire"

    bad = client.patch(f"/api/v1/claims/{claim['id']}", headers=auth_headers, json={"claim_type": "nope"})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "INVALID_CLAIM_TYPE"


def test_list_filter_by_type(client, auth_headers):
    client.post("/api/v1/claims", headers=auth_headers, json={"amount": 1, "claim_type": "demurrage"})
    client.post("/api/v1/claims", headers=auth_headers, json={"amount": 2, "claim_type": "cargo_damage"})
    body = client.get("/api/v1/claims?claim_type=cargo_damage", headers=auth_headers).json()
    assert body["items"]
    assert {i["claim_type"] for i in body["items"]} == {"cargo_damage"}
    # 列表行带 claim_type
    all_rows = client.get("/api/v1/claims", headers=auth_headers).json()
    assert all("claim_type" in i for i in all_rows["items"])
