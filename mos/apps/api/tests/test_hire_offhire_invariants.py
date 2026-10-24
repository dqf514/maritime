"""停租 / 租金不变量回归 —— 审计 P0-B1 · P1-B22 · P1-B23 · P1-B24 · P1-B25。

这些用例锁住**正确期望**，不是把缺陷固化成期望（审计 §6.1.1）。

此前全仓**没有任何** ``net_hire == gross_hire − off_hire_deduction`` 这类不变量断言
（审计报告 §7：「P0-B1 停租双扣 ❌ 无」），所以停租被扣两次、重叠停租被双计、
12 小时停租扣 0 元、1 月的停租事件出现在 2 月账单上 —— 全部无人拦截。

覆盖：
- P0-B1  停租只扣一次：``net_hire == gross_hire − off_hire_deduction``
- P1-B22 重叠停租事件**去重**（合并区间后只扣一次）
- P1-B23 停租**按小时**计算（12 小时停租扣 0.5 天，不是 0）
- P1-B24 期间外的停租事件**不扣**在本期（1 月事件不出现在 2 月账单）
- P1-B25 利润分成阶梯**去重叠** + 百分数**上限 100**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import Charter, OffHireEvent
from app.models_time_charter import ProfitShareRule, TimeCharterContract


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _items(payload):
    return payload["items"] if isinstance(payload, dict) else payload


def _make_tc(client, h, **overrides):
    """建一条期租合同（charter_type=tct → hire_rate 是日租）。"""
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    vessels = _items(client.get("/api/v1/masterdata/vessels", headers=h).json())
    charter = client.post(
        "/api/v1/charters",
        headers=h,
        json={
            "charter_type": "tct",
            "counterparty_id": parties[0]["id"],
            "hire_per_day": 10000,
        },
    ).json()
    body = {
        "charter_id": charter["id"],
        "contract_type": "tci",
        "contract_style": "time_charter",
        "vessel_id": vessels[0]["id"],
        "counterparty_id": parties[0]["id"],
        "hire_rate": 10000,
        "delivery_date": "2026-01-01",
        "redelivery_date": "2026-03-01",
    }
    body.update(overrides)
    r = client.post("/api/v1/tc/contracts", headers=h, json=body)
    assert r.status_code == 201, r.text
    return charter, r.json()


def _make_voyage(client, h, charter_id):
    r = client.post(
        "/api/v1/voyages",
        headers=h,
        json={"voyage_no": f"OH-{uuid.uuid4().hex[:6]}", "charter_id": charter_id},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _tenant_of(db, charter_id) -> uuid.UUID:
    """租户 id —— 从租约行上取（对外 schema 不暴露 tenant_id）。"""
    charter = db.get(Charter, uuid.UUID(charter_id))
    assert charter is not None
    return charter.tenant_id


def _add_off_hire(
    db,
    *,
    tenant_id,
    charter_id,
    voyage_id,
    start: str,
    end: str,
    hire_deduction: str | None = None,
):
    """插一条停租事件（``start``/``end`` 为 ``YYYY-MM-DD HH:MM``；``end=None`` = 仍在继续）。"""
    ev = OffHireEvent(
        tenant_id=tenant_id,
        charter_id=charter_id,
        voyage_id=voyage_id,
        start_at=datetime.fromisoformat(start),
        end_at=datetime.fromisoformat(end) if end else None,
        reason="test",
        event_type="breakdown",
        deduct_hire=True,
        hire_deduction=Decimal(hire_deduction) if hire_deduction is not None else None,
        status="open",
    )
    db.add(ev)
    db.commit()
    return ev


def _statement(db, tc_id, start: date, end: date):
    from app.services import hire_engine

    contract = db.get(TimeCharterContract, uuid.UUID(tc_id))
    assert contract is not None
    return hire_engine.calculate_hire_statement(db, contract, start, end)


# ─────────────────────────── P0-B1 停租只扣一次 ───────────────────────────


def test_p0_b1_net_hire_invariant(client, auth_headers, db_session):
    """``net_hire == gross_hire − off_hire_deduction``，且三者互相自洽。

    旧实现：``gross_hire`` 已扣停租、``net_hire`` 又减一次 ``time_deduction``
    —— 每期账单少算一整个停租期（审计 P0-B1）。
    """
    h = auth_headers
    charter, tc = _make_tc(client, h, hire_rate=10000)
    voyage = _make_voyage(client, h, charter["id"])

    _add_off_hire(
        db_session,
        tenant_id=_tenant_of(db_session, charter["id"]),
        charter_id=uuid.UUID(charter["id"]),
        voyage_id=uuid.UUID(voyage["id"]),
        start="2026-01-10 00:00",
        end="2026-01-12 12:00",  # 2.5 天
    )

    calc = _statement(db_session, tc["id"], date(2026, 1, 1), date(2026, 1, 31))

    gross = calc["gross_hire"]
    deduction = calc["off_hire_deduction"]
    net = calc["net_hire"]

    # 核心不变量
    assert gross - deduction == net
    # 毛租金 = 期间应付天数 × 日租（**未扣停租**）
    assert gross == Decimal("300000.00")
    # 2.5 天 × 10000 = 25000
    assert calc["off_hire_days"] == Decimal("2.5")
    assert deduction == Decimal("25000.00")
    assert net == Decimal("275000.00")

    # breakdown 里展示的 Gross Hire 必须与 gross_hire 一致（不能再是净额）
    lines = {ln["label"]: ln["amount"] for ln in calc["breakdown"]["lines"]}
    assert Decimal(lines["Gross Hire"]) == gross
    assert Decimal(lines["Net Hire"]) == net


# ─────────────────────────── P1-B22 重叠停租去重 ───────────────────────────


def test_p1_b22_overlapping_off_hire_not_double_counted(client, auth_headers, db_session):
    """两段重叠的停租只扣一次（合并区间：Jan 5 → Jan 15 = 10 天，不是 12 天）。"""
    h = auth_headers
    charter, tc = _make_tc(client, h, hire_rate=10000)
    voyage = _make_voyage(client, h, charter["id"])
    tenant_id = _tenant_of(db_session, charter["id"])
    charter_id = uuid.UUID(charter["id"])
    voyage_id = uuid.UUID(voyage["id"])

    _add_off_hire(
        db_session, tenant_id=tenant_id, charter_id=charter_id, voyage_id=voyage_id,
        start="2026-01-05 00:00", end="2026-01-10 00:00",  # 5 天
    )
    _add_off_hire(
        db_session, tenant_id=tenant_id, charter_id=charter_id, voyage_id=voyage_id,
        start="2026-01-08 00:00", end="2026-01-15 00:00",  # 7 天（与上一段重叠 2 天）
    )

    calc = _statement(db_session, tc["id"], date(2026, 1, 1), date(2026, 1, 31))

    assert calc["off_hire_days"] == Decimal("10")
    assert calc["off_hire_deduction"] == Decimal("100000.00")
    assert calc["gross_hire"] - calc["off_hire_deduction"] == calc["net_hire"]
    assert calc["net_hire"] == Decimal("200000.00")


# ─────────────────────────── P1-B23 按小时算停租 ───────────────────────────


def test_p1_b23_off_hire_computed_by_the_hour(client, auth_headers, db_session):
    """12 小时停租要扣 0.5 天 —— 旧实现截断到整天，12 小时停租扣 0 元。"""
    h = auth_headers
    charter, tc = _make_tc(client, h, hire_rate=10000)
    voyage = _make_voyage(client, h, charter["id"])

    _add_off_hire(
        db_session,
        tenant_id=_tenant_of(db_session, charter["id"]),
        charter_id=uuid.UUID(charter["id"]),
        voyage_id=uuid.UUID(voyage["id"]),
        start="2026-01-05 00:00",
        end="2026-01-05 12:00",
    )

    calc = _statement(db_session, tc["id"], date(2026, 1, 1), date(2026, 1, 31))

    assert calc["off_hire_days"] == Decimal("0.5")
    assert calc["off_hire_deduction"] == Decimal("5000.00")
    assert calc["gross_hire"] - calc["off_hire_deduction"] == calc["net_hire"]


# ─────────────────────────── P1-B24 期间外事件不扣 ───────────────────────────


def test_p1_b24_off_hire_outside_period_is_not_deducted(client, auth_headers, db_session):
    """1 月的停租事件不能出现在 2 月账单上（期间外不扣）。"""
    h = auth_headers
    charter, tc = _make_tc(client, h, hire_rate=10000)
    voyage = _make_voyage(client, h, charter["id"])

    _add_off_hire(
        db_session,
        tenant_id=_tenant_of(db_session, charter["id"]),
        charter_id=uuid.UUID(charter["id"]),
        voyage_id=uuid.UUID(voyage["id"]),
        start="2026-01-20 00:00",
        end="2026-01-25 00:00",
    )

    feb = _statement(db_session, tc["id"], date(2026, 2, 1), date(2026, 2, 28))
    assert feb["off_hire_days"] == Decimal("0")
    assert feb["off_hire_deduction"] == Decimal("0.00")
    # 账期口径是 [起, 止) —— Feb 1 → Feb 28 = 27 天
    assert feb["gross_hire"] == Decimal("270000.00")
    assert feb["net_hire"] == feb["gross_hire"]

    # 事件本身所在的那一期仍然要扣（不能因为跨期就整段丢失）
    jan = _statement(db_session, tc["id"], date(2026, 1, 1), date(2026, 1, 31))
    assert jan["off_hire_days"] == Decimal("5")
    assert jan["off_hire_deduction"] == Decimal("50000.00")


def test_p1_b24_explicit_deduction_is_clipped_to_period(client, auth_headers, db_session):
    """跨月的显式 ``hire_deduction`` 必须**裁剪到本期**（不能两期都扣全额）。"""
    h = auth_headers
    charter, tc = _make_tc(client, h, hire_rate=10000)
    voyage = _make_voyage(client, h, charter["id"])

    _add_off_hire(
        db_session,
        tenant_id=_tenant_of(db_session, charter["id"]),
        charter_id=uuid.UUID(charter["id"]),
        voyage_id=uuid.UUID(voyage["id"]),
        start="2026-01-25 00:00",
        end="2026-02-05 00:00",  # 11 天，跨 2 月
        hire_deduction="5000",
    )

    p1 = _statement(db_session, tc["id"], date(2026, 1, 1), date(2026, 2, 1))
    p2 = _statement(db_session, tc["id"], date(2026, 2, 1), date(2026, 3, 1))

    # 1 月：停租 7 天（Jan 25 → Feb 1），显式扣款按 7/11 摊
    assert p1["off_hire_days"] == Decimal("7")
    assert p1["off_hire_deduction"] == Decimal("70000.00") + Decimal("3181.82")
    # 2 月：停租 4 天（Feb 1 → Feb 5），显式扣款按 4/11 摊
    assert p2["off_hire_days"] == Decimal("4")
    assert p2["off_hire_deduction"] == Decimal("40000.00") + Decimal("1818.18")
    # 两期合计 = 事件金额（既不双扣也不漏扣）
    assert p1["off_hire_deduction"] + p2["off_hire_deduction"] == Decimal(
        "110000.00"
    ) + Decimal("5000.00")
    for calc in (p1, p2):
        assert calc["gross_hire"] - calc["off_hire_deduction"] == calc["net_hire"]


def test_p1_b24_open_off_hire_explicit_deduction_counted_once(client, auth_headers, db_session):
    """未关闭的停租事件：显式扣款只在**开始**的那一期计一次。"""
    h = auth_headers
    charter, tc = _make_tc(client, h, hire_rate=10000)
    voyage = _make_voyage(client, h, charter["id"])

    _add_off_hire(
        db_session,
        tenant_id=_tenant_of(db_session, charter["id"]),
        charter_id=uuid.UUID(charter["id"]),
        voyage_id=uuid.UUID(voyage["id"]),
        start="2026-01-25 00:00",
        end=None,  # 仍在继续
        hire_deduction="5000",
    )

    p1 = _statement(db_session, tc["id"], date(2026, 1, 1), date(2026, 2, 1))
    p2 = _statement(db_session, tc["id"], date(2026, 2, 1), date(2026, 3, 1))

    # 1 月：全额显式扣款
    assert p1["off_hire_deduction"] == Decimal("70000.00") + Decimal("5000.00")
    # 2 月：停租天数照算（船确实还在停租），但显式扣款不再重复扣
    assert p2["off_hire_days"] == Decimal("28")
    assert p2["off_hire_deduction"] == Decimal("280000.00")


# ─────────────────────────── P1-B25 分层去重 + 百分数上限 ───────────────────────────


def test_p1_b25_profit_share_tiers_deduplicated(client, auth_headers, db_session):
    """阶梯区间重叠不能双计：Jan 10k–20k 与 15k–25k 只按游标推进一次。"""
    h = auth_headers
    charter, tc = _make_tc(client, h, profit_share_threshold=10000)
    tenant_id = _tenant_of(db_session, charter["id"])
    tc_id = uuid.UUID(tc["id"])

    db_session.add_all(
        [
            ProfitShareRule(
                tenant_id=tenant_id,
                tc_contract_id=tc_id,
                tier_from=Decimal("10000"),
                tier_to=Decimal("20000"),
                share_pct=Decimal("50"),
                basis="tce",
            ),
            ProfitShareRule(
                tenant_id=tenant_id,
                tc_contract_id=tc_id,
                tier_from=Decimal("15000"),
                tier_to=Decimal("25000"),
                share_pct=Decimal("50"),
                basis="tce",
            ),
        ]
    )
    db_session.commit()

    from app.services import hire_engine

    out = hire_engine.calculate_profit_share(db_session, tc_id, Decimal("25000"))

    # 超额 15000：10k 段拿 50% = 5000，剩下 5k 段拿 50% = 2500 → 合计 7500
    assert out["owner_share"] == 7500.0
    assert out["charterer_share"] == 7500.0
    assert out["excess"] == 15000.0
    # 两层都应用了，但没有重叠段
    assert len(out["tiers"]) == 2
    assert out["tiers"][0]["band_amount"] == 10000.0
    assert out["tiers"][1]["band_amount"] == 5000.0


def test_p1_b25_profit_share_pct_capped_at_100(client, auth_headers, db_session):
    """``profit_share_pct = 150`` 必须夹到 100 并记录告警，不能算出负分成。

    两道防线：
    - **接口层**：``POST /tc/contracts`` 拒绝 >100 的百分数（422）—— 录入
      错误在边界就被挡住（P1-B27 同类）。
    - **引擎层**：越界值即使绕过接口写进库，``calculate_profit_share`` 仍
      夹到 100 并留告警 —— 存量脏数据不会算出负分成。
    """
    h = auth_headers

    # 接口层：150% 直接被拒
    r = client.post(
        "/api/v1/tc/contracts",
        headers=h,
        json={
            "charter_id": _make_tc(client, h)[0]["id"],
            "contract_type": "tci",
            "contract_style": "time_charter",
            "counterparty_id": _items(
                client.get("/api/v1/masterdata/counterparties", headers=h).json()
            )[0]["id"],
            "hire_rate": 10000,
            "delivery_date": "2026-01-01",
            "redelivery_date": "2026-03-01",
            "profit_share_pct": 150,
        },
    )
    assert r.status_code == 422, r.text

    # 引擎层：绕过接口写入 150 → 计算时夹到 100
    _charter, tc = _make_tc(client, h, profit_share_threshold=10000, profit_share_pct=100)
    row = db_session.get(TimeCharterContract, uuid.UUID(tc["id"]))
    row.profit_share_pct = Decimal("150")
    db_session.commit()

    from app.services import hire_engine

    out = hire_engine.calculate_profit_share(
        db_session, uuid.UUID(tc["id"]), Decimal("20000")
    )

    assert out["owner_share"] == 10000.0
    assert out["charterer_share"] == 0.0
    assert out["warnings"], "越界的 profit_share_pct 必须留告警"
