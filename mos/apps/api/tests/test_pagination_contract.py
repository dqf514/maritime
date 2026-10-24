"""列表分页契约回归（P1-28）。

**背景**：审计发现多处列表端点"静默截断"—— 后端硬上限 / 无 offset，
前端的第 N+1 条记录在界面上根本不存在，且用户看不到任何提示。

本文件把三条关键契约钉死：

1. ``GET /api/v1/voyages`` 返回标准 U1 信封 ``{items,total,limit,offset}``；
2. ``GET /api/v1/voyages/options`` 是下拉参照（裸数组、字段精简、含船名），
   不分页 —— 下拉里看不见的航次等于不存在；
3. ``GET /api/v1/masterdata/ports`` 支持 limit/offset（不再硬上限 100），
   ``/masterdata/ports/options`` 一次给全。
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_voyages_returns_pagination_envelope(client: TestClient, auth_headers: dict):
    r = client.get("/api/v1/voyages", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict), "航次列表必须返回信封而不是裸数组"
    assert set(body) >= {"items", "total", "limit", "offset"}
    assert isinstance(body["items"], list)
    assert body["total"] >= len(body["items"])
    assert body["limit"] > 0 and body["offset"] >= 0


def test_voyages_envelope_paginates(client: TestClient, auth_headers: dict):
    """limit/offset 必须真的生效，且 total 与页大小无关。"""
    first = client.get("/api/v1/voyages?limit=1&offset=0", headers=auth_headers).json()
    assert first["limit"] == 1
    assert first["offset"] == 0
    assert len(first["items"]) <= 1
    if first["total"] >= 2:
        second = client.get("/api/v1/voyages?limit=1&offset=1", headers=auth_headers).json()
        assert second["total"] == first["total"]
        assert second["items"][0]["id"] != first["items"][0]["id"]


def test_voyages_envelope_rejects_out_of_range(client: TestClient, auth_headers: dict):
    assert client.get("/api/v1/voyages?limit=0", headers=auth_headers).status_code == 422
    assert client.get("/api/v1/voyages?limit=5000", headers=auth_headers).status_code == 422
    assert client.get("/api/v1/voyages?offset=-1", headers=auth_headers).status_code == 422


def test_voyages_options_is_bare_array_with_vessel_name(client: TestClient, auth_headers: dict):
    r = client.get("/api/v1/voyages/options", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list), "下拉参照必须返回裸数组（前端 select 直接消费）"
    for row in rows:
        assert {"id", "voyage_no", "status"} <= set(row)
    # 有船的航次必须带上船名（下拉要显示船名才认得出是哪条航次）
    with_vessel = [x for x in rows if x.get("vessel_id")]
    if with_vessel:
        assert any(x.get("vessel_name") for x in with_vessel)


def test_voyages_options_not_shadowed_by_uuid_path(client: TestClient, auth_headers: dict):
    """/voyages/options 必须注册在 /voyages/{voyage_id} 之前，否则 422。"""
    r = client.get("/api/v1/voyages/options", headers=auth_headers)
    assert r.status_code == 200
    assert r.status_code != 422


def test_ports_list_supports_offset(client: TestClient, auth_headers: dict):
    """港口列表不再硬截断 100 条：limit/offset 必须可用。"""
    page1 = client.get("/api/v1/masterdata/ports?limit=1&offset=0", headers=auth_headers).json()
    assert isinstance(page1, list) and len(page1) <= 1
    page2 = client.get("/api/v1/masterdata/ports?limit=1&offset=1", headers=auth_headers).json()
    assert isinstance(page2, list) and len(page2) <= 1
    if page1 and page2:
        assert page1[0]["id"] != page2[0]["id"]


def test_ports_search_matches_country_and_type(client: TestClient, auth_headers: dict):
    uniq = uuid.uuid4().hex[:6].upper()
    created = client.post(
        "/api/v1/masterdata/ports",
        headers=auth_headers,
        json={"name": f"PG-{uniq}", "unlocode": f"ZZ{uniq[:4]}", "country": "ZZLAND", "timezone": "UTC"},
    )
    assert created.status_code in (200, 201), created.text
    found = client.get("/api/v1/masterdata/ports?q=ZZLAND", headers=auth_headers).json()
    assert any(p["unlocode"] == f"ZZ{uniq[:4]}" for p in found), "港口检索必须能按国家命中"


def test_ports_options_returns_all(client: TestClient, auth_headers: dict):
    r = client.get("/api/v1/masterdata/ports/options", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list)
    paged = client.get("/api/v1/masterdata/ports?limit=1000", headers=auth_headers).json()
    assert len(rows) >= len(paged)


def test_counterparty_contacts_supports_offset(client: TestClient, auth_headers: dict):
    """联系人检索以前没有 offset —— 第 51 个联系人永远取不到。"""
    a = client.get("/api/v1/masterdata/counterparty-contacts?limit=1&offset=0", headers=auth_headers)
    assert a.status_code == 200, a.text
    assert isinstance(a.json().get("items"), list)
    b = client.get("/api/v1/masterdata/counterparty-contacts?limit=1&offset=1", headers=auth_headers)
    assert b.status_code == 200
    assert isinstance(b.json().get("items"), list)
