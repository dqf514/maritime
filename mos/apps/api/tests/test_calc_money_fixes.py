"""金额/数值正确性回归 —— 审计 P1-B / P2-B 组（后端计算引擎部分）。

每条用例对应审计报告里的一条缺陷（编号见用例名）。这些用例锁住「正确期望」，
防止旧断言把缺陷固化成期望（审计 §6.1.1）。

覆盖：
- P1-B3  舍入策略统一（显式 ROUND_HALF_UP，不再是银行家舍入）
- P1-B11 费率表解析不出来不再静默按 0 计价
- P1-B13 cii.reference_cii 除零防护
- P1-B14 对账：币种必须相同 + 0.01 金额容差
- P1-B15 FuelEU 零输入不再造出九位数罚款
- P1-B16 显式 address_comm_pct=0 不再回落 commission_pct
- P1-B17 缺 bunker_eca_grade 时港口/ECA 燃油不再按 0 计价
- P1-B18 legs 模式合并顶层 port_days
- P1-B19 多货种继承顶层 differentials / cargo_measure
- P1-B20 per_mt 附加运费在多货种 / legs 模式不再是 0
- P1-B21 滞期多港口模式继承顶层 allowed_hours
- P1-B26 eu_ets_share 单位（份额 vs 百分数）
- P1-B27 佣金百分数上限
- P1-B28 引擎入口的百分数区间校验
- P1-B1/B2 佣金：只算一次、以毛额为基数、认 commission_basis
- P2-B2  滞期根因分摊合计 = 滞期额
- P2-B4  同一结果 dict 内舍入模式一致
- P2-B8  gold fixtures 直接进 pytest（laytime 之前没有任何用例覆盖）
- P2-B13 逐行量化后求和 → 先求和后量化
- P2-B14 turn_time_hours 在量化之前加入
- P2-B15 多货种 parcel 行加总 = 抬头 gross_freight
- P2-B16 cargo_terms 报的 overage_rate 就是实际用的费率
- P2-B17 cargo_terms 自己声明的区间被强制
- P2-B18 decimal.InvalidOperation → ValueError（422 而不是 500）
- P2-B19 评分不再用裸 round()（二进制银行家舍入）
- P2-B20 敏感性分析的扰动值不再回写成 float
- P2-B21 TCE 可用公布值复算
- P2-B22 收入类输入不再接受负数
- P2-B23 CommissionType.base_amount 不再有 float 往返尾巴
"""

from __future__ import annotations

import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

FIXTURES_CALC = Path(__file__).resolve().parents[3] / "fixtures" / "calc"


# ─────────────────────────── helpers ───────────────────────────


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _chartered_invoice(client, h, db_session, *, amount=100000, commission_basis=None,
                       brokerage_pct="1.25", address_comm_pct="2.5"):
    """建一条挂在租约上的运费发票（租约佣金字段由用例自己设置）。"""
    from app.models_domain import Charter

    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    parties = parties["items"] if isinstance(parties, dict) else parties
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "voyage", "counterparty_id": parties[0]["id"]},
    ).json()
    charter = db_session.get(Charter, uuid.UUID(cp["id"]))
    charter.brokerage_pct = Decimal(brokerage_pct)
    charter.address_comm_pct = Decimal(address_comm_pct)
    db_session.commit()

    voy = client.post(
        "/api/v1/voyages",
        headers=h,
        json={"voyage_no": f"CM-{uuid.uuid4().hex[:6]}", "charter_id": cp["id"]},
    ).json()
    payload = {
        "invoice_type": "freight",
        "amount": amount,
        "voyage_id": voy["id"],
        "counterparty_id": parties[0]["id"],
    }
    if commission_basis is not None:
        payload["commission_basis"] = commission_basis
    inv = client.post("/api/v1/invoices", headers=h, json=payload).json()
    return inv


# ─────────────────────────── P1-B3 舍入 ───────────────────────────


def test_p1_b3_half_up_not_bankers():
    """佣金/金额一律 ROUND_HALF_UP：100.005 → 100.01（银行家舍入会给 100.00）。"""
    from app.services.commission import calculate_commission

    out = calculate_commission("address_commission", "100.005", 100)
    assert out["calculated_amount"] == 100.01


def test_p1_b3_estimate_modes_consistent():
    """P2-B4：同一个结果 dict 内不得混用两种舍入模式（全部 HALF_UP）。"""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 50000,
            "freight_rate": 18.555,
            "commission_pct": 2.5,
            "sea_days": 30,
            "port_days": 10,
        }
    )
    # 逐项用 HALF_UP 复算一遍，结果必须一致
    assert out["gross_freight"] == 927750.0
    assert out["address_commission"] == 23193.75
    assert out["net_freight"] == 904556.25
    assert out["total_revenue"] == 904556.25


# ─────────────────────────── P1-B11 费率表 ───────────────────────────


def test_p1_b11_unresolvable_rate_table_raises(client, auth_headers):
    """费率表解析不出来 → 422（不再静默按 0 计价）。"""
    h = auth_headers
    est = client.post(
        "/api/v1/estimates",
        headers=h,
        json={
            "title": "bad rate table",
            "inputs": {
                "cargo_qty": 50000,
                "freight_rate_table_id": str(uuid.uuid4()),
                "sea_days": 10,
            },
        },
    ).json()
    r = client.post(f"/api/v1/estimates/{est['id']}/calculate", headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "INVALID_ESTIMATE_INPUT"
    assert "did not resolve" in r.json()["detail"]["message"]


def test_p1_b11_surcharge_lookup_returns_none(db_session, client, auth_headers):
    """surcharge_lookup 解析不出来时返回 None（不是 0）。"""
    from app.services.rates import surcharge_lookup

    val = surcharge_lookup(
        db_session,
        _tenant_id(db_session),
        uuid.uuid4(),
        "SGSIN-NLRTM",
        "coal",
    )
    assert val is None


def _tenant_id(db_session) -> uuid.UUID:
    from app.models import Tenant

    row = db_session.query(Tenant).first()
    assert row is not None
    return row.id


# ─────────────────────────── P1-B13 CII ───────────────────────────


def test_p1_b13_reference_cii_dwt_zero():
    """dwt=0 时 reference_cii 抛 ValueError（与 attained_cii 口径一致）。"""
    from app.services.cii import rate_cii, reference_cii

    with pytest.raises(ValueError):
        reference_cii(0, "bulk_carrier")
    with pytest.raises(ValueError):
        rate_cii(1000, 0, 100, 2023)


# ─────────────────────────── P1-B14 对账 ───────────────────────────


class _Inv:
    """最小 Invoice 替身（reconciliation 只用到金额/币种/单号）。"""

    def __init__(self, amount, currency="USD", tax=0, invoice_no="INV-1"):
        self.id = uuid.uuid4()
        self.amount = Decimal(str(amount))
        self.tax_amount = Decimal(str(tax))
        self.currency = currency
        self.invoice_no = invoice_no
        self.counterparty_id = None


def test_p1_b14_currency_must_match():
    """同额不同币种不得配对。"""
    from app.services.reconciliation import score_line

    inv = _Inv(100000, currency="USD")
    assert score_line({"amount": 100000, "currency": "EUR"}, inv, None) is None
    assert score_line({"amount": 100000, "currency": "USD"}, inv, None) == 0.6


def test_p1_b14_amount_tolerance():
    """金额容差 0.01（文档承诺的口径，之前是精确相等）。"""
    from app.services.reconciliation import score_line

    inv = _Inv(100000)
    assert score_line({"amount": 100000.005, "currency": "USD"}, inv, None) == 0.6
    assert score_line({"amount": 100000.02, "currency": "USD"}, inv, None) is None


def test_p1_b14_suggest_matches_flags_unverified_currency():
    from app.services.reconciliation import suggest_matches

    inv = _Inv(100000, currency="USD")
    out = suggest_matches([{"amount": 100000}], [inv])
    assert out["suggestions"][0]["currency"] == "USD"
    # 流水行没带币种 → 币种无法核对，必须让操作员看见
    assert out["suggestions"][0]["currency_verified"] is False


# ─────────────────────────── P1-B15 FuelEU ───────────────────────────


def test_p1_b15_fueleu_zero_input_no_penalty():
    """零输入不再造出九位数罚款。"""
    from app.services.carbon_calculator import calculate_fueleu_compliance

    out = calculate_fueleu_compliance(100, "VLSFO", 0, 0)
    assert out["penalty_usd"] == Decimal("0.00")
    assert out["penalty_usd"] < 1
    assert out["assessable"] is False


def test_p1_b15_fueleu_rejects_negative_input():
    from app.services.carbon_calculator import calculate_fueleu_compliance

    with pytest.raises(ValueError):
        calculate_fueleu_compliance(-1, "VLSFO", 10, 10)
    with pytest.raises(ValueError):
        calculate_fueleu_compliance(10, "VLSFO", -1, 10)


# ─────────────────────────── P1-B16 显式 0 ───────────────────────────


def test_p1_b16_explicit_zero_address_commission():
    """显式 address_comm_pct=0 不得回落到 commission_pct。"""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 1000,
            "freight_rate": 100,
            "address_comm_pct": 0,
            "commission_pct": 5,
            "sea_days": 10,
        }
    )
    assert out["address_commission"] == 0.0
    assert out["net_freight"] == out["gross_freight"]


# ─────────────────────────── P1-B17 油种价 ───────────────────────────


def test_p1_b17_eca_grade_fallback_not_zero():
    """缺 bunker_eca_grade 时港口/ECA 燃油不得按 0 计价。"""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 1000,
            "freight_rate": 100,
            "sea_days": 20,
            "port_days": 5,
            "bunker_sea_tpd": 30,
            "bunker_port_tpd": 4,
            "bunker_prices": {"VLSFO": 450},
            "bunker_grade": "VLSFO",
        }
    )
    # 全部燃油（620 mt）按 VLSFO 450 计价，而不是只算海段
    assert out["bunker_cost"] == 620 * 450


def test_p1_b17_ambiguous_grade_list_raises():
    """多价目又没给油种 → 明确报错，不再默默按 0。"""
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError):
        compute_estimate(
            {
                "cargo_qty": 1000,
                "freight_rate": 100,
                "sea_days": 20,
                "bunker_prices": {"VLSFO": 450, "MGO": 620},
            }
        )


# ─────────────────────────── P1-B18 legs ───────────────────────────


def test_p1_b18_legs_merge_top_level_port_days():
    """legs 模式不得丢弃顶层 port_days（TCE 虚高 65%）。"""
    from app.services.estimate_engine import compute_estimate

    base = {"legs": [{"distance_nm": 1000, "speed_kn": 13.5, "cargo_qty": 1000}], "freight_rate": 100}
    with_days = compute_estimate({**base, "port_days": 2})
    assert with_days["port_days"] == 2.0
    assert with_days["total_days"] == pytest.approx(3.0864 + 2, abs=1e-4)


# ─────────────────────────── P1-B19 多货种继承 ───────────────────────────


def test_p1_b19_multi_cargo_inherits_top_level_differentials():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargoes": [{"qty": 1000, "freight_rate": 100}],
            "differentials": [{"basis": "per_mt", "amount": 4}],
            "sea_days": 10,
        }
    )
    assert out["gross_freight"] == 104000.0
    assert out["differentials_total"] == 4000.0


def test_p1_b19_multi_cargo_inherits_top_level_cargo_measure():
    """顶层 cargo_measure 可供 parcel 的 per_measure 附加费使用（以前直接 500）。"""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargoes": [{"qty": 1000, "freight_rate": 100}],
            "cargo_measure": 500,
            "differentials": [{"basis": "per_measure", "amount": 2}],
            "sea_days": 10,
        }
    )
    assert out["gross_freight"] == 101000.0


# ─────────────────────────── P1-B20 附加运费 ───────────────────────────


def test_p1_b20_per_mt_extra_terms_multi_cargo():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargoes": [{"qty": 1000, "freight_rate": 100}],
            "extra_freight_terms": [{"term": "BAF", "basis": "per_mt", "rate": 2.5}],
            "sea_days": 10,
        }
    )
    assert out["extra_freight_total"] == 2500.0
    assert out["gross_freight"] == 102500.0


def test_p1_b20_per_mt_extra_terms_legs():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "legs": [{"distance_nm": 1000, "speed_kn": 13.5, "cargo_qty": 1000}],
            "freight_rate": 100,
            "extra_freight_terms": [{"term": "BAF", "basis": "per_mt", "rate": 2.5}],
        }
    )
    assert out["extra_freight_total"] == 2500.0


# ─────────────────────────── P1-B21 滞期多港口 ───────────────────────────


def test_p1_b21_multi_port_inherits_top_level_allowed_hours():
    """多港口模式继承顶层 allowed_hours → 不再凭空多出 6,000 滞期费。"""
    from app.services.laytime_engine import compute_laytime

    out = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 3000,
            "terms": "SHINC",
            "port_events": [
                {"port": "A", "events": [{"start": "2026-09-01T00:00:00", "end": "2026-09-02T00:00:00"}]},
                {"port": "B", "events": [{"start": "2026-09-01T00:00:00", "end": "2026-09-02T00:00:00"}]},
            ],
        }
    )
    assert out["allowed_hours"] == 48.0
    assert out["used_hours"] == 48.0
    assert out["result_type"] == "on_time"
    assert out["amount"] == 0.0


# ─────────────────────────── P1-B26 EU ETS 单位 ───────────────────────────


def test_p1_b26_eu_ets_share_must_be_ratio():
    """eu_ets_share 按百分数填（50）→ 明确报错，不再 100 倍超算。"""
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="eu_ets_share_pct"):
        compute_estimate(
            {
                "cargo_qty": 1000,
                "freight_rate": 100,
                "sea_days": 10,
                "bunker_sea_tpd": 10,
                "co2_factor": 1,
                "ets_price": 80,
                "eu_ets_share": 50,
            }
        )


def test_p1_b26_eu_ets_share_pct_percent():
    """eu_ets_share_pct = 50 与历史的 eu_ets_share = 0.5 等价。"""
    from app.services.estimate_engine import compute_estimate

    common = {
        "cargo_qty": 1000,
        "freight_rate": 100,
        "sea_days": 10,
        "bunker_sea_tpd": 10,
        "co2_factor": 1,
        "ets_price": 80,
    }
    pct = compute_estimate({**common, "eu_ets_share_pct": 50})
    ratio = compute_estimate({**common, "eu_ets_share": 0.5})
    assert pct["emissions_cost"] == ratio["emissions_cost"] == 4000.0


# ─────────────────────────── P1-B27 佣金上限 ───────────────────────────


def test_p1_b27_commission_rate_pct_upper_bound():
    from app.services.commission import calculate_commission

    with pytest.raises(ValueError):
        calculate_commission("address_commission", 1000, 500)


def test_p1_b27_charter_commission_pct_upper_bound(client, auth_headers, db_session):
    """租约上的佣金百分数越界 → 422（不再按离谱费率计佣）。"""
    h = auth_headers
    inv = _chartered_invoice(client, h, db_session, address_comm_pct="500")

    r = client.get(f"/api/v1/invoices/{inv['id']}/commission-plan", headers=h)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "INVALID_COMMISSION_PCT"


# ─────────────────────────── P1-B28 输入区间校验 ───────────────────────────


@pytest.mark.parametrize(
    "inputs",
    [
        {"address_comm_pct": 500},
        {"commission_pct": 101},
        {"brokerage_pct": -1},
        {"cargo_tolerance_pct": 200},
        {"eu_ets_share_pct": 101},
        {"demurrage_income": -5000},
        {"other_income": -1000},
    ],
)
def test_p1_b28_percent_and_income_ranges(inputs, client, auth_headers):
    """百分数越界 / 收入为负 → 422。

    区间校验现在有**两道闸**：

    1. **存稿时** —— ``EstimateIn.inputs`` 是自由 dict，挂不上 ``ge/le``，
       所以用引擎同一套规则在 Pydantic 校验器里拦（用户填错当场见错）；
    2. **计算时** —— 引擎入口的 ``_validate_inputs``（绕过 API 直接算也拒）。

    存稿这道闸更早，是有意为之：以前要等到点「计算」才报错。
    """
    h = auth_headers
    r = client.post(
        "/api/v1/estimates",
        headers=h,
        json={"title": "out of range", "inputs": {"cargo_qty": 1000, "freight_rate": 10, "sea_days": 10, **inputs}},
    )
    assert r.status_code == 422, r.text

    # 引擎层同样会拒（绕过 API 直接算）
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError):
        compute_estimate({"cargo_qty": 1000, "freight_rate": 10, "sea_days": 10, **inputs})


# ─────────────────────────── P1-B1/B2 佣金 ───────────────────────────


def test_p1_b1_commission_plan_charged_once_on_gross(client, auth_headers, db_session):
    """佣金计划：一个基数、算一次；地址佣金按毛额计。"""
    h = auth_headers
    inv = _chartered_invoice(client, h, db_session, amount=100000)
    body = client.get(f"/api/v1/invoices/{inv['id']}/commission-plan", headers=h).json()
    assert body["base_amount"] == 100000.0
    assert body["address_commission_amount"] == 2500.0
    assert body["brokerage_amount"] == 1250.0
    assert body["total_commission"] == 3750.0


def test_p1_b2_commission_basis_net_uses_gross(client, auth_headers, db_session):
    """commission_basis="net" → 由净额反推毛额，不再按净额二次计佣。"""
    h = auth_headers
    # 毛额 100,000，地址佣金 2.5% → 净额 97,500
    inv = _chartered_invoice(client, h, db_session, amount=97500, commission_basis="net")
    body = client.get(f"/api/v1/invoices/{inv['id']}/commission-plan", headers=h).json()
    assert body["base_basis"] == "net"
    assert body["base_amount"] == 100000.0
    assert body["address_commission_amount"] == 2500.0


def test_p1_b2_hire_invoice_meta_gross_amount_wins(client, auth_headers, db_session):
    """租约租金发票的 meta.hire.gross_amount 是权威毛额。"""
    from app.models_domain import Invoice

    h = auth_headers
    inv = _chartered_invoice(client, h, db_session, amount=97500)
    row = db_session.get(Invoice, uuid.UUID(inv["id"]))
    row.meta = {"hire": {"gross_amount": 100000.0, "address_comm_pct": 2.5}}
    db_session.commit()

    body = client.get(f"/api/v1/invoices/{inv['id']}/commission-plan", headers=h).json()
    assert body["base_basis"] == "gross"
    assert body["base_amount"] == 100000.0
    assert body["address_commission_amount"] == 2500.0


# ─────────────────────────── P2-B2 根因分摊 ───────────────────────────


def test_p2_b2_root_cause_allocation_sums_to_demurrage(client, auth_headers, db_session):
    """Σ allocated_amount == allocated_total == 滞期额（以前 100.00 vs 99.99）。"""
    h = auth_headers
    lay = client.post(
        "/api/v1/laytimes",
        headers=h,
        json={
            "inputs": {
                "allowed_hours": 24,
                "demurrage_rate_per_day": 24000,
                "terms": "SHINC",
                "events": [{"start": "2026-09-01T00:00:00", "end": "2026-09-03T00:00:00"}],
            }
        },
    )
    assert lay.status_code in (200, 201), lay.text
    lay_id = lay.json()["id"]
    calc = client.post(f"/api/v1/laytimes/{lay_id}/calculate", headers=h)
    assert calc.status_code in (200, 201), calc.text

    for cause in ("port_congestion", "weather", "cargo_delay"):
        r = client.post(
            f"/api/v1/laytimes/{lay_id}/root-causes",
            headers=h,
            json={"cause": cause, "delay_hours": 24.0, "responsible_party": "charterer"},
        )
        assert r.status_code in (200, 201), r.text

    body = client.get(f"/api/v1/laytimes/{lay_id}/root-causes", headers=h).json()
    total = sum(Decimal(str(i["allocated_amount"])) for i in body["items"])
    assert total == Decimal(str(body["allocated_total"]))
    assert Decimal(str(body["allocated_total"])) == Decimal(str(body["demurrage_amount"]))


# ─────────────────────────── P2-B8 gold fixtures ───────────────────────────


def test_p2_b8_tce_gold_fixtures_exact():
    """TCE gold fixtures 直接进 pytest（**精确**比较，不放 ±0.02 的模糊带）。

    ±0.02 的容差能放过一次银行家翻转（9953.12 对 9953.13 就过关），
    所以这里逐位精确比较。
    """
    from app.services.estimate_engine import compute_estimate

    for f in sorted((FIXTURES_CALC / "tce").glob("*.json")):
        fx = json.loads(f.read_text(encoding="utf-8"))
        out = compute_estimate(fx["inputs"])
        for k, exp in fx.get("expect", {}).items():
            assert out.get(k) == exp, f"{f.name}: {k} expected {exp} got {out.get(k)}"
        for code in fx.get("expect_warnings", []) or []:
            assert code in [w["code"] for w in out.get("warnings", [])], f"{f.name}: {code}"


def test_p2_b8_laytime_gold_fixtures_exact():
    """Laytime gold fixtures 之前没有任何 pytest 覆盖。"""
    from app.services.laytime_engine import compute_laytime

    seen = 0
    for f in sorted((FIXTURES_CALC / "laytime").glob("*.json")):
        fx = json.loads(f.read_text(encoding="utf-8"))
        out = compute_laytime(fx["inputs"])
        for k, exp in fx.get("expect", {}).items():
            if isinstance(exp, str):
                assert out.get(k) == exp, f"{f.name}: {k}"
            else:
                assert out.get(k) == exp, f"{f.name}: {k} expected {exp} got {out.get(k)}"
        seen += 1
    assert seen >= 6


# ─────────────────────────── P2-B13 先求和后量化 ───────────────────────────


def test_p2_b13_sum_then_round():
    """3 × 0.005 → 0.02（逐行量化再求和会得到 0.03）。"""
    from app.services.freight_terms import parse_extra_freight_terms

    total, _ = parse_extra_freight_terms(
        {
            "extra_freight_terms": [
                {"term": "a", "basis": "per_lump", "rate": 0.005},
                {"term": "b", "basis": "per_lump", "rate": 0.005},
                {"term": "c", "basis": "per_lump", "rate": 0.005},
            ]
        },
        freight_base=Decimal("0"),
    )
    assert total == Decimal("0.02")


def test_p2_b13_differentials_sum_then_round():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 1000,
            "freight_rate": 10,
            "sea_days": 10,
            "differentials": [
                {"basis": "lump", "amount": 0.005},
                {"basis": "lump", "amount": 0.005},
                {"basis": "lump", "amount": 0.005},
            ],
        }
    )
    assert Decimal(str(out["differentials_total"])) == Decimal("0.02")


# ─────────────────────────── P2-B14 turn time ───────────────────────────


def test_p2_b14_turn_time_before_quantize():
    from app.services.laytime_engine import compute_laytime

    out = compute_laytime({"cargo_qty": 49, "load_rate_per_day": 192, "turn_time_hours": 0.005})
    assert out["allowed_hours"] == 6.13


# ─────────────────────────── P2-B15 parcel 行加总 ───────────────────────────


def test_p2_b15_parcel_rows_foot_to_gross_freight():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "sea_days": 10,
            "cargoes": [
                {"qty": 1, "freight_basis": "per_mt", "freight_rate": 18.555},
                {"qty": 1, "freight_basis": "per_mt", "freight_rate": 18.555},
            ],
        }
    )
    assert sum(Decimal(str(r["base_freight"])) for r in out["cargoes"]) == Decimal(
        str(out["gross_freight"])
    )


# ─────────────────────────── P2-B16/P2-B17 cargo terms ───────────────────────────


def test_p2_b16_reported_overage_rate_is_applied_rate():
    """报的 overage_rate 就是实际算钱用的费率。"""
    from app.services.cargo_terms import freight_with_overage

    out = freight_with_overage(
        contract_qty=1000,
        billed_qty=1100,
        freight_rate=Decimal("1.007"),
        tolerance_pct=Decimal("10"),
        overage_pct=Decimal("50"),
    )
    assert out["overage_rate"] == 1.51
    over_qty = Decimal(str(out["qty_at_overage_rate"]))
    assert Decimal(str(out["overage_freight"])) == (over_qty * Decimal("1.51")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def test_p2_b17_declared_ranges_enforced():
    from app.services.cargo_terms import freight_with_overage, quantity_bounds

    with pytest.raises(ValueError):
        quantity_bounds(1000, -10)
    with pytest.raises(ValueError):
        quantity_bounds(1000, 51)
    with pytest.raises(ValueError):
        freight_with_overage(contract_qty=1000, billed_qty=1100, freight_rate=10, overage_pct=Decimal("-150"))
    with pytest.raises(ValueError):
        freight_with_overage(contract_qty=1000, billed_qty=1100, freight_rate=10, overage_pct=Decimal("250"))


# ─────────────────────────── P2-B18 InvalidOperation ───────────────────────────


def test_p2_b18_invalid_number_is_value_error():
    """decimal.InvalidOperation 不是 ValueError → 以前逃成 500。"""
    from app.services.freight_terms import parse_extra_freight_terms

    with pytest.raises(ValueError):
        parse_extra_freight_terms(
            {"cargo_qty": "coal", "extra_freight_terms": [{"term": "X", "basis": "per_mt", "rate": 1}]},
            freight_base=Decimal("0"),
        )


# ─────────────────────────── P2-B19 评分舍入 ───────────────────────────


def test_p2_b19_score_rounding_is_half_up():
    """裸 round() 是二进制银行家舍入（round(2.675, 2) == 2.67）。"""
    from app.services.cargo_terms import score_cargo_vs_leg

    out = score_cargo_vs_leg(
        cargo_load_port_id="A",
        cargo_disch_port_id="B",
        cargo_qty=Decimal("1"),
        leg_load_port_id="A",
        leg_disch_port_id="B",
        leg_qty=Decimal("3"),
    )
    # 25 + 25 + 30×(1/3)=10 + 0 = 60
    assert out["score"] == 60.0


# ─────────────────────────── P2-B20 敏感性 ───────────────────────────


def test_p2_b20_sensitivity_keeps_decimal():
    """扰动值不再回写成 float（尾数会丢）。"""
    from app.services.estimate_engine import sensitivity

    rows = sensitivity(
        {"cargo_qty": 1000, "freight_rate": 100, "sea_days": 10},
        "freight_rate",
        [0.1],
        mode="pct",
    )
    assert rows[0]["result"]["gross_freight"] == 110000.0


# ─────────────────────────── P2-B21 TCE 可复算 ───────────────────────────


def test_p2_b21_tce_reproducible_from_published_values():
    """按公布值复算 TCE 必须得到同一个数。"""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 1000,
            "freight_rate": 100,
            "sea_days": 3.0864,
            "port_days": 2,
            "bunker_sea_tpd": 10,
            "bunker_price": 450,
        }
    )
    recomputed = (out["total_revenue"] - out["voyage_cost"]) / out["total_days"]
    assert round(recomputed, 2) == out["tce"]


# ─────────────────────────── P2-B22 负收入 ───────────────────────────


def test_p2_b22_negative_income_rejected():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError):
        compute_estimate(
            {"cargo_qty": 1000, "freight_rate": 100, "sea_days": 10, "demurrage_income": -5000}
        )


# ─────────────────────────── P2-B23 佣金落库 ───────────────────────────


def test_p2_b23_commission_record_has_no_float_tail(db_session, client, auth_headers):
    """CommissionType.base_amount 不得带 float 往返尾巴（12345.679999999999）。"""
    from app.services.commission import create_commission_record

    row = create_commission_record(
        db_session,
        _tenant_id(db_session),
        "address_commission",
        Decimal("12345.68"),
        Decimal("2.5"),
    )
    assert isinstance(row.base_amount, Decimal)
    assert row.base_amount == Decimal("12345.68")
    assert row.calculated_amount == Decimal("308.64")
