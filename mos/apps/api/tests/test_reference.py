"""参考数据源 API 冒烟测试。"""


def test_reference_seed_and_list(client, auth_headers):
    ds = client.get("/api/v1/reference/datasets?locale=zh-CN", headers=auth_headers)
    assert ds.status_code == 200
    codes = {d["code"] for d in ds.json()}
    assert "countries" in codes
    assert "timezones" in codes
    assert "currencies" in codes

    countries = client.get("/api/v1/reference/countries/items?locale=zh-CN", headers=auth_headers)
    assert countries.status_code == 200
    rows = countries.json()
    assert len(rows) >= 50
    cn = next(r for r in rows if r["code"] == "CN")
    assert "中国" in cn["label"] or cn["label_zh"] == "中国"

    tz = client.get("/api/v1/reference/timezones/items?q=Shanghai&locale=zh-CN", headers=auth_headers)
    assert tz.status_code == 200
    assert any(r["code"] == "Asia/Shanghai" for r in tz.json())

    clone = client.post("/api/v1/reference/fuel_grades/clone", headers=auth_headers)
    assert clone.status_code == 200
    assert clone.json()["mode"] == "local"
    assert clone.json()["cloned"] >= 5

    create = client.post(
        "/api/v1/reference/fuel_grades/items",
        headers=auth_headers,
        json={"code": "CUSTOM-BIO", "label_en": "Custom Bio", "label_zh": "自定义生物燃料", "sort_order": 999},
    )
    assert create.status_code == 200
    items = client.get("/api/v1/reference/fuel_grades/items?locale=zh-CN", headers=auth_headers)
    assert any(r["code"] == "CUSTOM-BIO" for r in items.json())
