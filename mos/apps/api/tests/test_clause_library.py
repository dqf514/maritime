"""D1 条款库：系统包 / 租户自建 / 参数物化。"""

from __future__ import annotations


def test_system_pack_seeded(client, auth_headers):
    body = client.get("/api/v1/clauses", headers=auth_headers).json()
    codes = {i["code"] for i in body["items"]}
    assert {"DEM_ALWAYS", "DESP_HALF", "NOR_WIBON", "LAY_SHEX_EIU", "TIME_BAR_90D"} <= codes
    dem = next(i for i in body["items"] if i["code"] == "DEM_ALWAYS")
    assert dem["is_system"] is True
    assert dem["params"]["once_on_demurrage"] is True


def test_filter_by_cp_form_and_category(client, auth_headers):
    gencon = client.get("/api/v1/clauses?cp_form=GENCON", headers=auth_headers).json()["items"]
    # 通用条款（cp_form=None）随任何表单返回
    assert any(i["code"] == "DEM_ALWAYS" for i in gencon)
    assert any(i["code"] == "TIME_BAR_90D" for i in gencon)
    laytime = client.get("/api/v1/clauses?category=laytime", headers=auth_headers).json()["items"]
    assert laytime and all(i["category"] == "laytime" for i in laytime)


def test_tenant_custom_clause_crud(client, auth_headers):
    created = client.post(
        "/api/v1/clauses",
        headers=auth_headers,
        json={"code": "MY_CLAUSE", "title_en": "My clause", "params": {"once_on_demurrage": True}},
    )
    assert created.status_code == 200, created.text
    cid = created.json()["id"]

    rows = client.get("/api/v1/clauses", headers=auth_headers).json()["items"]
    mine = next(i for i in rows if i["code"] == "MY_CLAUSE")
    assert mine["is_system"] is False

    # 系统条款不可删
    sys_row = next(i for i in rows if i["code"] == "DEM_ALWAYS")
    assert client.delete(f"/api/v1/clauses/{sys_row['id']}", headers=auth_headers).status_code == 404
    assert client.delete(f"/api/v1/clauses/{cid}", headers=auth_headers).status_code == 200


def test_charter_laytime_inputs_materialize(client, auth_headers):
    parties = client.get("/api/v1/masterdata/counterparties", headers=auth_headers).json()
    party = parties["items"][0]["id"] if isinstance(parties, dict) else parties[0]["id"]
    charter = client.post(
        "/api/v1/charters",
        headers=auth_headers,
        json={
            "charter_type": "voyage",
            "counterparty_id": party,
            "demurrage_rate": 18000,
            "despatch_rate": 9000,
            "clauses": {"codes": ["DEM_ALWAYS", "LAY_SHINC"]},
        },
    ).json()

    body = client.get(f"/api/v1/charters/{charter['id']}/laytime-inputs", headers=auth_headers).json()
    assert body["clause_codes"] == ["DEM_ALWAYS", "LAY_SHINC"]
    inputs = body["inputs"]
    assert inputs["demurrage_rate_per_day"] == 18000
    assert inputs["despatch_rate_per_day"] == 9000
    assert inputs["once_on_demurrage"] is True  # 条款参数进入计算输入
    assert inputs["terms"] == "SHINC"
