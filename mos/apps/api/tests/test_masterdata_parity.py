"""P10 IMOS 主数据对齐 —— 序列化字段扩展 + Data Center 子表 CRUD。

对照 IMOS Data Center 截图逐项验证：
- Vessel / Port / Counterparty 的 ``*Out`` 必须暴露 ORM 全部业务列（gap class A，
  此前 Vessel 13 个字段里有 24 个业务列根本不出现在 API 上）；
- 子表：cargo_groups / cargo_names(+properties) / port_berths / port_aliases /
  船舶停泊油耗矩阵 + 航速油耗曲线 / counterparty properties；
- PATCH 走 ``exclude_unset``，只写提交过的字段（回归：不得把存量值清成 None）；
- 唯一键冲突 409；软删除进回收站且可恢复 —— entity_type 已登记进
  ``routers/recycle.py`` 的 ENTITY_LOOKUP，未登记会 400 UNSUPPORTED_TYPE。
"""

from __future__ import annotations

import uuid

from tests.isolation_helpers import create_tenant

API = "/api/v1"
UNIQ = uuid.uuid4().hex[:6]


def _post(client, h, url, json, expect=(200, 201)):
    r = client.post(f"{API}{url}", headers=h, json=json)
    assert r.status_code in expect, f"POST {url} -> {r.status_code}: {r.text}"
    return r.json()


def _f(value):
    """Numeric 字段经 JSON 往返可能是 str/float/Decimal —— 一律按 float 比。"""
    return None if value is None else float(value)


# ── 序列化字段扩展（gap class A）──


def test_vessel_out_exposes_imos_columns(client, auth_headers):
    h = auth_headers
    owner = _post(client, h, "/masterdata/counterparties", {"name": f"Owner {UNIQ}", "type": "owner"})
    created = _post(
        client,
        h,
        "/masterdata/vessels",
        {
            "name": f"IMOS Parity {UNIQ}",
            "imo": f"9{UNIQ[:6]}",
            "vessel_code": f"IM{UNIQ[:4]}",
            "type_code": "B",
            "ownership": "tc",
            "trade_area": "TCE",
            "class_society": "ABS",
            "vessel_owner_id": owner["id"],
            "daily_cost": "5500.00",
            "speed_laden": "14.50",
            "speed_ballast": "13.00",
            "tpc": "180.00",
            "capacity_bale_ft3": "120000.00",
            "capacity_grain_ft3": "125000.00",
            "deck_capacity_m3": "7200.00",
            "vessel_type_corr": "1.020",
            "scrubber": "hybrid",
            "constants_sea": "300.00",
            "constants_lakes": "280.00",
            "fresh_water": "50.00",
            "constants_others": "10.00",
            "beaufort": "MODERATE",
            "sea_state": "4",
            "sea_swell": "SLIGHT",
            "summer_dwt": "300000.00",
            "summer_draft": "20.50",
            "lightship": "45000.00",
            "hull_type": "bl",
            "build_year": 2015,
            "build_yard": "DSIC",
            "ism_manager": "Mgr Co",
            "sea_speed_100": "14.50",
            "port_working": "30.00",
            "ifo_mdo_ratio": "0.900",
            "max_lift_qty": "0",
            "stowage_factor": "1.200",
            "tank_capacity_total": "25000.00",
        },
    )

    got = client.get(f"{API}/masterdata/vessels/{created['id']}", headers=h).json()
    assert got["vessel_code"] == f"IM{UNIQ[:4]}"
    assert got["type_code"] == "B"
    assert got["ownership"] == "tc"
    assert got["class_society"] == "ABS"
    assert got["vessel_owner_id"] == owner["id"]
    assert _f(got["daily_cost"]) == 5500.0
    assert _f(got["speed_laden"]) == 14.5
    assert _f(got["speed_ballast"]) == 13.0
    assert _f(got["tpc"]) == 180.0
    assert _f(got["capacity_bale_ft3"]) == 120000.0
    assert _f(got["deck_capacity_m3"]) == 7200.0
    assert _f(got["vessel_type_corr"]) == 1.02
    assert got["scrubber"] == "hybrid"
    assert _f(got["constants_sea"]) == 300.0
    assert _f(got["fresh_water"]) == 50.0
    assert got["beaufort"] == "MODERATE"
    assert got["sea_swell"] == "SLIGHT"
    assert _f(got["summer_dwt"]) == 300000.0
    assert _f(got["summer_draft"]) == 20.5
    assert _f(got["lightship"]) == 45000.0
    assert got["build_year"] == 2015
    assert got["build_yard"] == "DSIC"
    assert _f(got["port_working"]) == 30.0
    assert _f(got["tank_capacity_total"]) == 25000.0


def test_vessel_partial_patch_preserves_imos_fields(client, auth_headers):
    """回归：PATCH 只提交 name，不得把其余字段按默认值清成 None。"""
    h = auth_headers
    created = _post(
        client,
        h,
        "/masterdata/vessels",
        {"name": f"Wipe Guard {UNIQ}", "imo": f"98{UNIQ[:5]}", "tpc": "155.50", "scrubber": "open_loop"},
    )
    r = client.patch(f"{API}/masterdata/vessels/{created['id']}", headers=h, json={"name": "Renamed Vessel"})
    assert r.status_code == 200, r.text

    got = client.get(f"{API}/masterdata/vessels/{created['id']}", headers=h).json()
    assert got["name"] == "Renamed Vessel"
    assert got["imo"] == f"98{UNIQ[:5]}", "PATCH 把未提交的 imo 清空了"
    assert _f(got["tpc"]) == 155.5, "PATCH 把未提交的 tpc 清空了"
    assert got["scrubber"] == "open_loop", "PATCH 把未提交的 scrubber 清空了"

    # 真正的局部 PATCH：不带 name 也必须成功（VesselUpdate.name 可缺省）
    r = client.patch(f"{API}/masterdata/vessels/{created['id']}", headers=h, json={"tpc": "160.00"})
    assert r.status_code == 200, r.text
    got = client.get(f"{API}/masterdata/vessels/{created['id']}", headers=h).json()
    assert _f(got["tpc"]) == 160.0
    assert got["name"] == "Renamed Vessel"

    # 显式 null 打到 NOT NULL 键 → 422，而不是撞数据库 500
    r = client.patch(f"{API}/masterdata/vessels/{created['id']}", headers=h, json={"name": None})
    assert r.status_code == 422, r.text


def test_port_compliance_flags_and_dual_gmt(client, auth_headers):
    h = auth_headers
    created = _post(
        client,
        h,
        "/masterdata/ports",
        {
            "name": f"IMOS Port {UNIQ}",
            "unlocode": f"ZZ{UNIQ[:4]}",
            "country": "SG",
            "timezone": "Asia/Singapore",
            "latitude": "1.265",
            "longitude": "103.820",
            "port_type": "standard_port",
            "parent_country": "SG",
            "port_operator": "MPA",
            "port_no": 42,
            "port_area": "PASIR PANJANG",
            "region_code": "ASIA",
            "loadline_zone": "SUMMER",
            "std_gmt_offset": "8.00",
            "dst_gmt_offset": "8.00",
            "external_ref": "EXT-42",
            "alerts": "Tidal window",
            "remarks": "Deep draft",
            "fuel_zone_default": "NON_ECA",
            "supported_scrubbers": "open_loop",
            "bunkering_port": True,
            "single_berth": True,
            "eu_ets_port": True,
            "uk_ets_port": True,
            "uk_ets_ni": True,
            "use_high_sulfur_fuel": True,
        },
    )
    got = client.get(f"{API}/masterdata/ports/{created['id']}", headers=h).json()
    assert _f(got["latitude"]) == 1.265
    assert _f(got["longitude"]) == 103.82
    assert got["port_type"] == "standard_port"
    assert got["parent_country"] == "SG"
    assert got["port_operator"] == "MPA"
    assert got["port_no"] == 42
    assert got["region_code"] == "ASIA"
    assert got["loadline_zone"] == "SUMMER"
    assert _f(got["std_gmt_offset"]) == 8.0
    assert _f(got["dst_gmt_offset"]) == 8.0
    assert got["external_ref"] == "EXT-42"
    assert got["supported_scrubbers"] == "open_loop"
    for flag in ("bunkering_port", "single_berth", "eu_ets_port", "uk_ets_port", "uk_ets_ni", "use_high_sulfur_fuel"):
        assert got[flag] is True, flag
    # 未勾选的开关必须显式 False，不能是 null（布尔族是 NOT NULL 列）
    for flag in ("lightering_port", "sts_exclusion", "outermost_region", "fuel_eu", "hide_passing_point"):
        assert got[flag] is False, flag

    # 局部 PATCH（不带 name）：只改 remarks，不得清掉合规开关或时区偏移
    r = client.patch(f"{API}/masterdata/ports/{created['id']}", headers=h, json={"remarks": "updated"})
    assert r.status_code == 200, r.text
    again = client.get(f"{API}/masterdata/ports/{created['id']}", headers=h).json()
    assert again["name"] == f"IMOS Port {UNIQ}"
    assert again["remarks"] == "updated"
    assert again["bunkering_port"] is True
    assert again["eu_ets_port"] is True
    assert _f(again["std_gmt_offset"]) == 8.0


def test_counterparty_identity_credit_and_gl_fields(client, auth_headers):
    h = auth_headers
    created = _post(
        client,
        h,
        "/masterdata/counterparties",
        {
            "name": f"IMOS CP {UNIQ}",
            "type": "charterer",
            "address_types": ["Charterers", "Brokers"],
            "short_name": f"C{UNIQ[:4]}",
            "company_no": "COMP-778",
            "ref_no": "REF-991",
            "cross_ref": "XREF-1",
            "reference_code": "RC-1",
            "veslink_id": "VES-55",
            "fax": "+65 6000 0001",
            "telex": "TESX 1234",
            "department": "Ops",
            "main_contact": "A. Tan",
            "currency": "USD",
            "credit_term": 45,
            "credit_line": "2500000.00",
            "rating_date": "2026-01-15",
            "demurrage_tb_days": "3.00",
            "vat_no": "VAT-1",
            "ap_account": "2100",
            "ar_account": "1200",
            "ic_account": "1300",
            "default_account": "1200",
            "status": "active",
        },
    )
    got = client.get(f"{API}/masterdata/counterparties/{created['id']}", headers=h).json()
    assert got["address_types"] == ["Charterers", "Brokers"]
    assert got["short_name"] == f"C{UNIQ[:4]}"
    assert got["company_no"] == "COMP-778"
    assert got["ref_no"] == "REF-991"
    assert got["veslink_id"] == "VES-55"
    assert got["fax"] == "+65 6000 0001"
    assert got["main_contact"] == "A. Tan"
    assert got["currency"] == "USD"
    assert got["credit_term"] == 45
    assert _f(got["credit_line"]) == 2500000.0
    assert got["rating_date"] in ("2026-01-15", "2026-01-15T00:00:00")
    assert _f(got["demurrage_tb_days"]) == 3.0
    assert got["ap_account"] == "2100"
    assert got["ar_account"] == "1200"
    assert got["default_account"] == "1200"
    assert got["status"] == "active"

    # 局部 PATCH（不带 name）：只改 notes，不得清掉 IMOS 字段
    r = client.patch(f"{API}/masterdata/counterparties/{created['id']}", headers=h, json={"notes": "updated"})
    assert r.status_code == 200, r.text
    again = client.get(f"{API}/masterdata/counterparties/{created['id']}", headers=h).json()
    assert again["name"] == f"IMOS CP {UNIQ}"
    assert again["notes"] == "updated"
    assert again["short_name"] == f"C{UNIQ[:4]}"
    assert again["address_types"] == ["Charterers", "Brokers"]
    assert _f(again["credit_line"]) == 2500000.0


# ── 货物品名主数据 ──


def test_cargo_group_and_name_crud(client, auth_headers):
    h = auth_headers
    group = _post(client, h, "/masterdata/cargo-groups", {"name": f"BULK {UNIQ}", "description": "dry bulk"})
    assert group["name"] == f"BULK {UNIQ}"

    # 重复大类名 → 409，不是 500
    dup = client.post(f"{API}/masterdata/cargo-groups", headers=h, json={"name": f"BULK {UNIQ}"})
    assert dup.status_code == 409, dup.text

    cargo = _post(
        client,
        h,
        "/masterdata/cargo-names",
        {
            "short_name": f"STEAM COAL {UNIQ}",
            "full_name": "Steam Coal, Export Quality",
            "cargo_group_id": group["id"],
            "cargo_class": "coal",
            "imo_name": "Coal",
            "imsbc_code": "A01",
            "un_number": None,
            "imdg_class": None,
            "dangerous": False,
            "special_handling": False,
            "pre_clearance_us_ca": True,
            "stow_factor_m3_mt": "1.4700",
            "stow_factor_ft3_mt": "47.0000",
            "api_gravity": None,
            "product_code": "COAL-SC",
            "default_cp_unit": "MT",
            "capacity_basis": "grain",
            "bill_by": "bl_qty",
            "inactive": False,
            "description": "nutrition-free",
        },
    )
    assert cargo["cargo_group_id"] == group["id"]
    assert cargo["imsbc_code"] == "A01"
    assert cargo["pre_clearance_us_ca"] is True
    assert _f(cargo["stow_factor_m3_mt"]) == 1.47
    assert _f(cargo["stow_factor_ft3_mt"]) == 47.0
    assert cargo["capacity_basis"] == "grain"
    assert cargo["bill_by"] == "bl_qty"

    # 唯一 short_name → 409
    dup2 = client.post(
        f"{API}/masterdata/cargo-names", headers=h, json={"short_name": f"STEAM COAL {UNIQ}"}
    )
    assert dup2.status_code == 409, dup2.text

    # 按 group 过滤
    listed = client.get(f"{API}/masterdata/cargo-names?group_id={group['id']}", headers=h).json()
    assert [r["id"] for r in listed] == [cargo["id"]]

    # 按关键字过滤
    hit = client.get(f"{API}/masterdata/cargo-names?q=STEAM", headers=h).json()
    assert cargo["id"] in [r["id"] for r in hit]

    # 属性子表
    prop = _post(client, h, f"/masterdata/cargo-names/{cargo['id']}/properties", {"title": "HS Code", "value": "2701"})
    assert prop["cargo_name_id"] == cargo["id"]
    props = client.get(f"{API}/masterdata/cargo-names/{cargo['id']}/properties", headers=h).json()
    assert len(props) == 1 and props[0]["value"] == "2701"

    r = client.patch(
        f"{API}/masterdata/cargo-names/{cargo['id']}/properties/{prop['id']}", headers=h, json={"value": "2701.10"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["value"] == "2701.10"

    # 软删除 → 列表消失 + 回收站可恢复
    r = client.delete(f"{API}/masterdata/cargo-names/{cargo['id']}", headers=h)
    assert r.status_code == 200 and r.json()["recycled"] is True

    after = client.get(f"{API}/masterdata/cargo-names?q=STEAM", headers=h).json()
    assert cargo["id"] not in [x["id"] for x in after]

    bin_list = client.get(f"{API}/recycle-bin", headers=h)
    assert bin_list.status_code == 200, bin_list.text
    item = next(
        (i for i in bin_list.json() if i["entity_type"] == "cargo_name" and i["entity_id"] == cargo["id"]), None
    )
    assert item is not None, "cargo_name 软删除未进回收站 —— ENTITY_LOOKUP 漏登记？"

    restored = client.post(f"{API}/recycle-bin/{item['id']}/restore", headers=h)
    assert restored.status_code == 200, restored.text
    back = client.get(f"{API}/masterdata/cargo-names?q=STEAM", headers=h).json()
    assert cargo["id"] in [x["id"] for x in back]


def test_cargo_names_tenant_isolation(client):
    _, h1 = create_tenant(
        client, code=f"mdp1{UNIQ[:4]}", name="MD Parity A", admin_email=f"mdp1-{UNIQ}@example.com"
    )
    _, h2 = create_tenant(
        client, code=f"mdp2{UNIQ[:4]}", name="MD Parity B", admin_email=f"mdp2-{UNIQ}@example.com"
    )

    a = _post(client, h1, "/masterdata/cargo-names", {"short_name": f"ISOLATED {UNIQ}"})
    listed2 = client.get(f"{API}/masterdata/cargo-names?q=ISOLATED", headers=h2).json()
    assert a["id"] not in [r["id"] for r in listed2]

    # 跨租户直接取详情必须 404（scoped_get 不区分"不存在"与"越权"）
    assert client.get(f"{API}/masterdata/cargo-names/{a['id']}", headers=h2).status_code == 404
    assert client.patch(
        f"{API}/masterdata/cargo-names/{a['id']}", headers=h2, json={"short_name": "HACKED"}
    ).status_code == 404
    assert client.delete(f"{API}/masterdata/cargo-names/{a['id']}", headers=h2).status_code == 404


# ── 港口泊位 / 别名（全局参照数据）──


def test_port_berths_and_aliases(client, auth_headers):
    h = auth_headers
    port = _post(client, h, "/masterdata/ports", {"name": f"Berth Port {UNIQ}", "unlocode": f"ZZ{UNIQ[:4]}"})

    berth = _post(client, h, f"/masterdata/ports/{port['id']}/berths", {"short_name": "BERTH-1", "full_name": "Berth One"})
    assert berth["port_id"] == port["id"]
    assert berth["inactive"] is False

    dup = client.post(
        f"{API}/masterdata/ports/{port['id']}/berths", headers=h, json={"short_name": "BERTH-1"}
    )
    assert dup.status_code == 409, dup.text

    # 同名泊位挂到另一个港口是允许的
    other = _post(client, h, "/masterdata/ports", {"name": f"Berth Port B {UNIQ}", "unlocode": f"ZY{UNIQ[:4]}"})
    assert client.post(
        f"{API}/masterdata/ports/{other['id']}/berths", headers=h, json={"short_name": "BERTH-1"}
    ).status_code == 201

    alias = _post(client, h, f"/masterdata/ports/{port['id']}/aliases", {"alias": f"OLD NAME {UNIQ}"})
    dup_a = client.post(
        f"{API}/masterdata/ports/{port['id']}/aliases", headers=h, json={"alias": f"OLD NAME {UNIQ}"}
    )
    assert dup_a.status_code == 409, dup_a.text

    listed = client.get(f"{API}/masterdata/ports/{port['id']}/berths", headers=h).json()
    assert [b["id"] for b in listed] == [berth["id"]]

    # 跨港口取子行 → 404
    assert client.patch(
        f"{API}/masterdata/ports/{other['id']}/berths/{berth['id']}", headers=h, json={"short_name": "X"}
    ).status_code == 404

    r = client.patch(
        f"{API}/masterdata/ports/{port['id']}/berths/{berth['id']}", headers=h, json={"inactive": True}
    )
    assert r.status_code == 200 and r.json()["inactive"] is True

    r = client.delete(f"{API}/masterdata/ports/{port['id']}/aliases/{alias['id']}", headers=h)
    assert r.status_code == 200 and r.json()["recycled"] is True
    assert client.get(f"{API}/masterdata/ports/{port['id']}/aliases", headers=h).json() == []


# ── 船舶油耗矩阵 / 航速曲线 ──


def test_vessel_port_and_speed_consumption(client, auth_headers):
    h = auth_headers
    vessel = _post(client, h, "/masterdata/vessels", {"name": f"Cons Vessel {UNIQ}"})

    row = _post(
        client,
        h,
        f"/masterdata/vessels/{vessel['id']}/port-consumptions",
        {
            "fuel_grade": "VLSFO",
            "unit": "MT",
            "loading": "35.000",
            "discharge": "30.000",
            "idle_on": "12.000",
            "idle_off": "3.000",
            "heat": "8.000",
            "igs": "2.000",
            "manoeuvring": "20.000",
            "auxiliary": "5.000",
            "boiler": "4.000",
        },
    )
    assert row["vessel_id"] == vessel["id"]
    assert _f(row["loading"]) == 35.0
    assert _f(row["idle_on"]) == 12.0

    # 同船同油品唯一
    dup = client.post(
        f"{API}/masterdata/vessels/{vessel['id']}/port-consumptions", headers=h, json={"fuel_grade": "VLSFO"}
    )
    assert dup.status_code == 409, dup.text

    _post(client, h, f"/masterdata/vessels/{vessel['id']}/port-consumptions", {"fuel_grade": "MGO"})
    listed = client.get(f"{API}/masterdata/vessels/{vessel['id']}/port-consumptions", headers=h).json()
    assert len(listed) == 2
    assert [r["fuel_grade"] for r in listed] == ["MGO", "VLSFO"]  # 按牌号排序

    # 只提交一个字段 → 其余保留
    r = client.patch(
        f"{API}/masterdata/vessels/{vessel['id']}/port-consumptions/{row['id']}", headers=h, json={"clean": "1.500"}
    )
    assert r.status_code == 200, r.text
    assert _f(r.json()["clean"]) == 1.5
    assert _f(r.json()["loading"]) == 35.0, "局部 PATCH 把 loading 清空了"

    r = client.delete(f"{API}/masterdata/vessels/{vessel['id']}/port-consumptions/{row['id']}", headers=h)
    assert r.status_code == 200
    assert [x["fuel_grade"] for x in client.get(
        f"{API}/masterdata/vessels/{vessel['id']}/port-consumptions", headers=h
    ).json()] == ["MGO"]

    # 航速油耗曲线
    curve = _post(
        client,
        h,
        f"/masterdata/vessels/{vessel['id']}/speed-consumptions",
        {"speed": "14.50", "ballast_laden": "L", "engine_load": "75.00", "fuel_consumption": {"VLF": 18.0, "LSG": 0.1},
         "basis": "eco_owner"},
    )
    assert curve["vessel_id"] == vessel["id"]
    assert curve["fuel_consumption"]["VLF"] == 18.0

    r = client.patch(
        f"{API}/masterdata/vessels/{vessel['id']}/speed-consumptions/{curve['id']}",
        headers=h,
        json={"engine_load": "80.00"},
    )
    assert r.status_code == 200 and _f(r.json()["engine_load"]) == 80.0
    assert r.json()["fuel_consumption"]["VLF"] == 18.0

    curves = client.get(f"{API}/masterdata/vessels/{vessel['id']}/speed-consumptions", headers=h).json()
    assert len(curves) == 1
    assert client.delete(
        f"{API}/masterdata/vessels/{vessel['id']}/speed-consumptions/{curve['id']}", headers=h
    ).status_code == 200
    assert client.get(f"{API}/masterdata/vessels/{vessel['id']}/speed-consumptions", headers=h).json() == []

    # 不存在的船 → 404
    assert client.get(
        f"{API}/masterdata/vessels/{uuid.uuid4()}/port-consumptions", headers=h
    ).status_code == 404


# ── 对手方属性 ──


def test_counterparty_properties(client, auth_headers):
    h = auth_headers
    party = _post(client, h, "/masterdata/counterparties", {"name": f"Prop CP {UNIQ}", "type": "broker"})

    prop = _post(client, h, f"/masterdata/counterparties/{party['id']}/properties", {"title": "DUNS", "value": "12-345"})
    assert prop["counterparty_id"] == party["id"]

    listed = client.get(f"{API}/masterdata/counterparties/{party['id']}/properties", headers=h).json()
    assert len(listed) == 1

    r = client.patch(
        f"{API}/masterdata/counterparties/{party['id']}/properties/{prop['id']}", headers=h, json={"value": "99-88"}
    )
    assert r.status_code == 200 and r.json()["value"] == "99-88"

    # 属性挂在另一个对手方路径下 → 404
    other = _post(client, h, "/masterdata/counterparties", {"name": f"Other CP {UNIQ}"})
    assert client.patch(
        f"{API}/masterdata/counterparties/{other['id']}/properties/{prop['id']}", headers=h, json={"value": "X"}
    ).status_code == 404
    assert client.delete(
        f"{API}/masterdata/counterparties/{other['id']}/properties/{prop['id']}", headers=h
    ).status_code == 404

    r = client.delete(f"{API}/masterdata/counterparties/{party['id']}/properties/{prop['id']}", headers=h)
    assert r.status_code == 200 and r.json()["recycled"] is True
    assert client.get(f"{API}/masterdata/counterparties/{party['id']}/properties", headers=h).json() == []

    # 不存在的对手方 → 404
    assert client.get(
        f"{API}/masterdata/counterparties/{uuid.uuid4()}/properties", headers=h
    ).status_code == 404
