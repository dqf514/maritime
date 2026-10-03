"""Bunker / laytime / compliance module gap-fill coverage.

- Bunker requirement procurement chain (draft→tendering→ordered→fulfilled)
- Bunker option selection (winner + sibling rejection)
- Cap/collar price clamping
- Demurrage on account calculation (pure + estimated-demurrage endpoint)
- Root cause allocation (pro-rata by delay hours)
- Delay tracking & laytime exclusion
- IMO 2020 sulphur compliance
- Chinese / Taiwanese ECA detection
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.bunker_procurement import apply_cap_collar
from app.services.carbon_calculator import eca_compliance, imo2020_compliance, sox_compliance
from app.services.laytime_engine import compute_laytime, settle_with_on_account

# 金样：allowed 24h（无 turn time），SHINC；两天工作时间 → used 48h，balance 24h
# → 滞期 1 天 × 24000 = 24000。
DEMURRAGE_INPUTS = {
    "allowed_hours": 24,
    "demurrage_rate_per_day": 24000,
    "terms": "SHINC",
    "events": [
        {"start": "2026-01-05T00:00:00", "end": "2026-01-06T00:00:00", "excluded": False},
        {"start": "2026-01-06T00:00:00", "end": "2026-01-07T00:00:00", "excluded": False},
    ],
}


def _master_ids(client, h) -> tuple[str, str, str]:
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    ports = client.get("/api/v1/masterdata/ports", headers=h).json()
    assert vessels and parties and ports
    return vessels[0]["id"], parties[0]["id"], ports[0]["id"]


def _laytime_with_demurrage(client, h) -> str:
    lt = client.post("/api/v1/laytimes", headers=h, json={"inputs": DEMURRAGE_INPUTS})
    assert lt.status_code == 200, lt.text
    lt_id = lt.json()["id"]
    calc = client.post(f"/api/v1/laytimes/{lt_id}/calculate", headers=h)
    assert calc.status_code == 200, calc.text
    assert calc.json()["results"]["result_type"] == "demurrage"
    assert calc.json()["results"]["amount"] == 24000.0
    return lt_id


# ── A. Bunker module ──


def test_bunker_requirement_lifecycle(client, auth_headers):
    h = auth_headers
    vessel_id, _party_id, port_id = _master_ids(client, h)

    r = client.post(
        "/api/v1/bunker/requirements",
        headers=h,
        json={"vessel_id": vessel_id, "fuel_type": "VLSFO", "qty_required": 500, "port_id": port_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rid = body["id"]
    assert body["status"] == "draft"
    assert body["requirement_no"].startswith("BREQ-")

    # draft → tendering（招标开启）
    t = client.post(f"/api/v1/bunker/requirements/{rid}/tender", headers=h)
    assert t.status_code == 200, t.text
    assert t.json()["status"] == "tendering"

    # tendering → ordered → fulfilled
    o = client.post(f"/api/v1/bunker/requirements/{rid}/transition?target=ordered", headers=h)
    assert o.status_code == 200, o.text
    assert o.json()["status"] == "ordered"
    f = client.post(f"/api/v1/bunker/requirements/{rid}/transition?target=fulfilled", headers=h)
    assert f.status_code == 200, f.text
    assert f.json()["status"] == "fulfilled"

    # 非法流转拒绝：fulfilled 是终态
    bad = client.post(f"/api/v1/bunker/requirements/{rid}/transition?target=cancelled", headers=h)
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "INVALID_STATE"

    # 列表协议（U1 envelope）
    listing = client.get("/api/v1/bunker/requirements", headers=h)
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["total"] >= 1 and any(item["id"] == rid for item in payload["items"])


def test_bunker_option_selection(client, auth_headers):
    h = auth_headers
    vessel_id, party_id, port_id = _master_ids(client, h)

    req = client.post(
        "/api/v1/bunker/requirements",
        headers=h,
        json={"vessel_id": vessel_id, "fuel_type": "VLSFO", "qty_required": 300, "port_id": port_id},
    )
    assert req.status_code == 200, req.text
    rid = req.json()["id"]
    assert client.post(f"/api/v1/bunker/requirements/{rid}/tender", headers=h).status_code == 200

    o1 = client.post(
        "/api/v1/bunker/options",
        headers=h,
        json={"requirement_id": rid, "supplier_id": party_id, "price_per_mt": 620},
    )
    o2 = client.post(
        "/api/v1/bunker/options",
        headers=h,
        json={"requirement_id": rid, "supplier_id": party_id, "price_per_mt": 610},
    )
    assert o1.status_code == 200 and o2.status_code == 200
    o1_id, o2_id = o1.json()["id"], o2.json()["id"]
    assert o1.json()["status"] == "offered"

    sel = client.post(f"/api/v1/bunker/options/{o2_id}/select", headers=h)
    assert sel.status_code == 200, sel.text
    assert sel.json()["status"] == "selected"
    assert sel.json()["requirement_status"] == "ordered"
    assert sel.json()["rejected_options"] == 1

    opts = client.get(f"/api/v1/bunker/options?requirement_id={rid}", headers=h).json()
    by_id = {item["id"]: item["status"] for item in opts["items"]}
    assert by_id[o2_id] == "selected"
    assert by_id[o1_id] == "rejected"

    # 已选定/落选的选项不可再选
    again = client.post(f"/api/v1/bunker/options/{o1_id}/select", headers=h)
    assert again.status_code == 409


def test_cap_collar_price_clamping(client, auth_headers):
    # 纯函数：price 夹紧到 [collar, cap]
    assert apply_cap_collar(900, cap_price=700, collar_price=500) == Decimal("700.00")  # capped
    assert apply_cap_collar(300, cap_price=700, collar_price=500) == Decimal("500.00")  # floored
    assert apply_cap_collar(620, cap_price=700, collar_price=500) == Decimal("620.00")  # in band
    assert apply_cap_collar(999, cap_price=700) == Decimal("700.00")  # cap only
    assert apply_cap_collar(100, collar_price=250) == Decimal("250.00")  # collar only
    with pytest.raises(ValueError):
        apply_cap_collar(600, cap_price=500, collar_price=700)

    # API：创建 cap/collar 条款并按其上下限夹紧
    h = auth_headers
    r = client.post(
        "/api/v1/bunker/cap-collar",
        headers=h,
        json={
            "fuel_type": "VLSFO",
            "cap_price": 700,
            "collar_price": 500,
            "index_symbol": "SIN380",
            "effective_from": "2026-01-01",
        },
    )
    assert r.status_code == 200, r.text
    listing = client.get("/api/v1/bunker/cap-collar?fuel_type=VLSFO", headers=h)
    assert listing.status_code == 200
    rows = listing.json()["items"]
    assert rows and rows[0]["cap_price"] == 700 and rows[0]["collar_price"] == 500
    clamped = apply_cap_collar(900, cap_price=rows[0]["cap_price"], collar_price=rows[0]["collar_price"])
    assert clamped == Decimal("700.00")

    # 校验：collar 不得高于 cap
    bad = client.post(
        "/api/v1/bunker/cap-collar",
        headers=h,
        json={"fuel_type": "VLSFO", "cap_price": 400, "collar_price": 500, "effective_from": "2026-01-01"},
    )
    assert bad.status_code == 422


# ── B. Laytime module ──


def test_demurrage_on_account_calculation(client, auth_headers):
    # 纯计算：on-account 冲抵最终滞期
    s = settle_with_on_account(24000, [8000, 2000])
    assert s["demurrage_amount"] == 24000.0
    assert s["on_account_total"] == 10000.0
    assert s["outstanding"] == 14000.0
    assert s["overpaid"] == 0.0
    assert s["settled"] is False
    over = settle_with_on_account(24000, [30000])
    assert over["outstanding"] == 0.0 and over["overpaid"] == 6000.0 and over["settled"] is True
    # 负数（despatch）不产生可冲抵滞期
    assert settle_with_on_account(-5000, [1000])["demurrage_amount"] == 0.0

    h = auth_headers
    lt_id = _laytime_with_demurrage(client, h)

    for payload in (
        {"amount": 8000, "status": "paid", "payment_date": "2026-01-10"},
        {"amount": 2000, "status": "paid"},
        {"amount": 500, "status": "pending"},
    ):
        r = client.post(f"/api/v1/laytimes/{lt_id}/demurrage-on-account", headers=h, json=payload)
        assert r.status_code == 200, r.text

    est = client.get(f"/api/v1/laytimes/{lt_id}/estimated-demurrage", headers=h)
    assert est.status_code == 200, est.text
    body = est.json()
    assert body["demurrage_amount"] == 24000.0
    assert body["on_account_total"] == 10000.0  # paid + applied
    assert body["on_account_pending"] == 500.0
    assert body["outstanding"] == 14000.0

    listing = client.get(f"/api/v1/laytimes/{lt_id}/demurrage-on-account", headers=h)
    assert listing.status_code == 200
    assert listing.json()["total"] == 3
    assert listing.json()["on_account_paid"] == 10000.0


def test_root_cause_allocation(client, auth_headers):
    h = auth_headers
    lt_id = _laytime_with_demurrage(client, h)

    for payload in (
        {"cause": "port_congestion", "delay_hours": 12, "responsible_party": "port"},
        {"cause": "cargo_delay", "delay_hours": 6, "responsible_party": "charterer"},
        {"cause": "weather", "delay_hours": 6, "responsible_party": "owner"},
    ):
        r = client.post(f"/api/v1/laytimes/{lt_id}/root-causes", headers=h, json=payload)
        assert r.status_code == 200, r.text

    got = client.get(f"/api/v1/laytimes/{lt_id}/root-causes", headers=h)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["total"] == 3
    assert body["total_delay_hours"] == 24.0
    assert body["demurrage_amount"] == 24000.0
    by_cause = {item["cause"]: item for item in body["items"]}
    # 12h / 6h / 6h → 50% / 25% / 25% of 24000
    assert by_cause["port_congestion"]["share_pct"] == 50.0
    assert by_cause["port_congestion"]["allocated_amount"] == 12000.0
    assert by_cause["cargo_delay"]["allocated_amount"] == 6000.0
    assert by_cause["weather"]["allocated_amount"] == 6000.0
    assert body["allocated_total"] == 24000.0

    # 非法枚举拒绝
    bad = client.post(
        f"/api/v1/laytimes/{lt_id}/root-causes",
        headers=h,
        json={"cause": "aliens", "delay_hours": 1, "responsible_party": "other"},
    )
    assert bad.status_code == 422


def test_delay_tracking_and_laytime_exclusion(client, auth_headers):
    h = auth_headers
    lt_id = _laytime_with_demurrage(client, h)

    weather = client.post(
        f"/api/v1/laytimes/{lt_id}/delays",
        headers=h,
        json={
            "delay_type": "weather",
            "start_at": "2026-01-05T00:00:00",
            "end_at": "2026-01-05T06:00:00",
            "excluded_from_laytime": True,
            "cost_impact": 1500,
        },
    )
    assert weather.status_code == 200, weather.text
    assert weather.json()["duration_hours"] == 6.0  # end-start 推导
    assert weather.json()["excluded_from_laytime"] is True

    congestion = client.post(
        f"/api/v1/laytimes/{lt_id}/delays",
        headers=h,
        json={
            "delay_type": "port_congestion",
            "start_at": "2026-01-05T06:00:00",
            "end_at": "2026-01-05T09:00:00",
            "excluded_from_laytime": False,
        },
    )
    assert congestion.status_code == 200, congestion.text

    got = client.get(f"/api/v1/laytimes/{lt_id}/delays", headers=h)
    assert got.status_code == 200, got.text
    summary = got.json()["summary"]
    assert summary["total_delay_hours"] == 9.0
    assert summary["excluded_hours"] == 6.0
    assert summary["counted_hours"] == 3.0
    assert summary["total_cost_impact"] == 1500.0

    # 引擎口径：excluded 事件停表不计 laytime
    r = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 24000,
            "terms": "SHINC",
            "events": [
                {"start": "2026-01-05T00:00:00", "end": "2026-01-06T00:00:00", "excluded": False},
                {"start": "2026-01-06T00:00:00", "end": "2026-01-07T00:00:00", "excluded": True},
                {"start": "2026-01-07T00:00:00", "end": "2026-01-07T12:00:00", "excluded": False},
            ],
        }
    )
    assert r["used_hours"] == 36.0  # 24 + 12，excluded 24h 不计
    assert r["result_type"] == "demurrage"


# ── C. Compliance ──


def test_imo2020_compliance_check():
    # 公海 VLSFO 0.50% — 恰好等于全球上限，合规
    r = imo2020_compliance(vessel_id="v1", fuel_type="VLSFO", route=[{"lat": 0.0, "lon": -30.0}])
    assert r["sulfur_pct"] == 0.50
    assert r["global_cap"] == 0.50
    assert r["imo2020_compliant"] is True

    # HSFO 3.50% — 突破 IMO 2020 全球上限
    r2 = imo2020_compliance(vessel_id="v1", fuel_type="HSFO", route=[{"lat": 0.0, "lon": -30.0}])
    assert r2["imo2020_compliant"] is False
    assert any("IMO 2020 global cap" in v for v in r2["violations"])

    # 实测硫含量覆盖牌号缺省值（脱硫塔后 HSFO 0.45%）
    r3 = imo2020_compliance(vessel_id="v1", fuel_type="HSFO", route=[{"lat": 0.0, "lon": -30.0}], sulfur_pct=0.45)
    assert r3["imo2020_compliant"] is True

    # 波罗的海 ECA 内 VLSFO 0.50% 虽满足全球上限，仍超 ECA 0.10%
    r4 = imo2020_compliance(vessel_id="v1", fuel_type="VLSFO", route=[{"lat": 56.0, "lon": 20.0}])
    assert r4["imo2020_compliant"] is False
    assert r4["eca"]["in_eca"] is True
    assert "Baltic Sea ECA" in r4["eca"]["eca_zones"]

    # MGO 0.10% — ECA 内合规
    r5 = imo2020_compliance(vessel_id="v1", fuel_type="MGO", route=[{"lat": 56.0, "lon": 20.0}])
    assert r5["imo2020_compliant"] is True

    # SOx 年度规则：2019 全球 3.50% 容许 HSFO，2020 起 0.50% 不容许
    s2019 = sox_compliance(vessel_id="v1", fuel_type="HSFO", route=[{"lat": 0.0, "lon": -30.0}], year=2019)
    assert s2019["global_cap"] == 3.50 and s2019["compliant"] is True
    s2020 = sox_compliance(vessel_id="v1", fuel_type="HSFO", route=[{"lat": 0.0, "lon": -30.0}], year=2020)
    assert s2020["global_cap"] == 0.50 and s2020["compliant"] is False
    # SOx 2015 ECA 0.10% 规则
    s_eca = sox_compliance(vessel_id="v1", fuel_type="VLSFO", route=[{"lat": 56.0, "lon": 20.0}], year=2016)
    assert s_eca["compliant"] is False and s_eca["eca_cap"] == 0.10


def test_chinese_taiwanese_eca_detection():
    # 上海（长三角 ECA）
    shanghai = eca_compliance(vessel_id="v1", route=[{"lat": 31.2, "lon": 121.5}], fuel_type="VLSFO")
    assert shanghai["in_eca"] is True
    assert "China Yangtze River Delta ECA" in shanghai["eca_zones"]
    assert shanghai["compliant"] is False  # 0.50% > 0.10%
    assert shanghai["eca_sulfur_cap"] == 0.10

    # 珠江口（珠三角 ECA）
    pearl = eca_compliance(vessel_id="v1", route=[{"lat": 22.3, "lon": 113.9}], fuel_type="MGO")
    assert "China Pearl River Delta ECA" in pearl["eca_zones"]
    assert pearl["compliant"] is True

    # 天津（环渤海 ECA）
    bohai = eca_compliance(vessel_id="v1", route=[{"lat": 38.9, "lon": 117.8}], fuel_type="MGO")
    assert "China Bohai Rim ECA" in bohai["eca_zones"]

    # 高雄（台湾 ECA）
    kaohsiung = eca_compliance(vessel_id="v1", route=[{"lat": 22.6, "lon": 120.3}], fuel_type="MGO")
    assert "Taiwan ECA" in kaohsiung["eca_zones"]
    assert kaohsiung["compliant"] is True

    # 公海无 ECA
    ocean = eca_compliance(vessel_id="v1", route=[{"lat": 0.0, "lon": -30.0}], fuel_type="VLSFO")
    assert ocean["in_eca"] is False and ocean["compliant"] is True

    # 航线仅一段进入台湾 ECA
    crossing = eca_compliance(
        vessel_id="v1",
        route=[{"lat": 10.0, "lon": 130.0}, {"lat": 22.6, "lon": 120.3}],
        fuel_type="MGO",
    )
    assert crossing["points_total"] == 2
    assert crossing["points_in_eca"] == 1

    # IMO 2020 检查同样识别中国/台湾 ECA
    imo = imo2020_compliance(vessel_id="v1", fuel_type="VLSFO", route=[{"lat": 31.2, "lon": 121.5}])
    assert imo["imo2020_compliant"] is False
    assert "China Yangtze River Delta ECA" in imo["eca"]["eca_zones"]
