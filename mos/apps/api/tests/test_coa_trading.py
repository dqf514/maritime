"""Phase 6 COA 一等公民 + Phase 7 Trading & Risk —— 合同/分摊/燃油中性盈亏、
交易 CRUD、盯市（金样确定性）、持仓净额、状态机与租户隔离。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import create_tenant


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_charter(client, h, charter_type: str = "coa") -> dict:
    r = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": charter_type, "cargo_qty": 30000.0},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _make_coa(client, h, charter_id: str, **over) -> dict:
    body = {
        "charter_id": charter_id,
        "total_qty": 60000.0,
        "qty_unit": "mt",
        "period_from": "2026-01-01",
        "period_to": "2026-12-31",
        "rate_basis": "per_mt",
        "rate": 25.0,
    }
    body.update(over)
    r = client.post("/api/v1/coa/contracts", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _add_itinerary(client, h, coa_id: str, seq: int, qty: float, **over) -> dict:
    body = {"seq": seq, "qty": qty}
    body.update(over)
    r = client.post(f"/api/v1/coa/contracts/{coa_id}/itineraries", headers=h, json=body)
    return r


def _add_lifting(client, h, charter_id: str, period_label: str, qty: float) -> dict:
    r = client.post(
        f"/api/v1/charters/{charter_id}/liftings",
        headers=h,
        params={"period_label": period_label, "planned_qty": qty},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _make_voyage(client, h, charter_id: str, voyage_no: str) -> dict:
    r = client.post(
        "/api/v1/voyages",
        headers=h,
        json={"voyage_no": voyage_no, "charter_id": charter_id},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def _complete_lifting(client, h, lifting_id: str, voyage_id: str, actual_qty: float) -> None:
    """planned → nominated → fixed(voyage) → completed(actual_qty)。"""
    r = client.post(
        f"/api/v1/coa-liftings/{lifting_id}/nominate",
        headers=h,
        json={"laycan_from": "2026-01-01T00:00:00Z", "laycan_to": "2026-01-15T00:00:00Z"},
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/coa-liftings/{lifting_id}/fix", headers=h, json={"voyage_id": voyage_id})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/coa-liftings/{lifting_id}/complete", headers=h, json={"actual_qty": actual_qty})
    assert r.status_code == 200, r.text


def _make_trade(client, h, **over) -> dict:
    body = {
        "kind": "ffa",
        "buy_sell": "buy",
        "route": "C5",
        "period_from": "2026-10-01",
        "period_to": "2026-12-31",
        "qty": 1000.0,
        "qty_unit": "mt",
        "price": 50.0,
        "price_unit": "per_mt",
        "index_symbol": "TCE_C5_PAC",
        "trade_date": "2026-09-01",
    }
    body.update(over)
    r = client.post("/api/v1/trading/trades", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── Phase 6: COA CRUD + itinerary allocation ─────────────────────────────────


def test_coa_contract_crud(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h)
    coa = _make_coa(client, h, charter["id"], cargo_spec="VLSFO max 0.5% S")
    assert coa["coa_no"].startswith("COA-")
    assert coa["status"] == "draft"
    assert coa["total_qty"] == 60000.0

    listed = client.get("/api/v1/coa/contracts", headers=h).json()
    assert listed["total"] >= 1
    assert any(item["id"] == coa["id"] for item in listed["items"])

    detail = client.get(f"/api/v1/coa/contracts/{coa['id']}", headers=h).json()
    assert detail["cargo_spec"] == "VLSFO max 0.5% S"
    assert detail["rate_basis"] == "per_mt"

    patched = client.patch(f"/api/v1/coa/contracts/{coa['id']}", headers=h, json={"rate": 28.5}).json()
    assert patched["rate"] == 28.5

    # 校验：分单量总和不得超合同总量
    ok = _add_itinerary(client, h, coa["id"], 1, 60000.0)
    assert ok.status_code == 201, ok.text
    assert ok.json()["allocated_qty"] == 0.0
    over = _add_itinerary(client, h, coa["id"], 2, 1.0)
    assert over.status_code == 422
    assert over.json()["detail"]["code"] == "COA_ITINERARY_SUM_EXCEEDED"
    # 重复 seq
    dup = _add_itinerary(client, h, coa["id"], 1, 1.0)
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "COA_SEQ_DUPLICATE"


def test_coa_allocation_and_summary(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h)
    coa = _make_coa(client, h, charter["id"], total_qty=30000.0, rate_basis="per_voyage", rate=120000.0)
    assert _add_itinerary(client, h, coa["id"], 1, 30000.0).status_code == 201

    lift_a = _add_lifting(client, h, charter["id"], "2026-Q1", 10000.0)
    lift_b = _add_lifting(client, h, charter["id"], "2026-Q2", 25000.0)

    r = client.post(
        f"/api/v1/coa/{coa['id']}/allocate",
        headers=h,
        json={"lifting_id": lift_a["id"], "itinerary_seq": 1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["qty"] == 10000.0

    # 行内超额分摊 → 422
    over = client.post(
        f"/api/v1/coa/{coa['id']}/allocate",
        headers=h,
        json={"lifting_id": lift_b["id"], "itinerary_seq": 1},
    )
    assert over.status_code == 422
    assert over.json()["detail"]["code"] == "ITINERARY_OVER_ALLOCATED"

    # 同一票重复分摊 → 422
    dup = client.post(
        f"/api/v1/coa/{coa['id']}/allocate",
        headers=h,
        json={"lifting_id": lift_a["id"], "itinerary_seq": 1},
    )
    assert dup.status_code == 422
    assert dup.json()["detail"]["code"] == "LIFTING_ALREADY_ALLOCATED"

    summary = client.get(f"/api/v1/coa/{coa['id']}/allocation", headers=h).json()
    assert summary["total_qty"] == 30000.0
    assert summary["planned_qty"] == 30000.0
    assert summary["allocated_qty"] == 10000.0
    assert summary["remaining_qty"] == 20000.0
    assert summary["itineraries"][0]["allocated_qty"] == 10000.0
    assert summary["itineraries"][0]["remaining_qty"] == 20000.0


def test_coa_fuel_neutral_pnl_gold(client, auth_headers):
    """金样：per_mt 50/mt × 完成 1000mt = 50,000 收入；
    加油 50mt×600 = 30,000（fuel），使费 5,000（other）。
    pnl_fuel_neutral = 50,000 − 5,000 = 45,000；pnl_gross = 15,000。"""
    h = auth_headers
    charter = _make_charter(client, h)
    coa = _make_coa(client, h, charter["id"], total_qty=1000.0, rate_basis="per_mt", rate=50.0)
    assert _add_itinerary(client, h, coa["id"], 1, 1000.0).status_code == 201

    lift = _add_lifting(client, h, charter["id"], "2026-Q1", 1000.0)
    voyage = _make_voyage(client, h, charter["id"], f"V-{coa['coa_no']}")
    _complete_lifting(client, h, lift["id"], voyage["id"], 1000.0)

    r = client.post(
        f"/api/v1/coa/{coa['id']}/allocate",
        headers=h,
        json={"lifting_id": lift["id"], "itinerary_seq": 1},
    )
    assert r.status_code == 200, r.text

    bo = client.post(
        "/api/v1/bunker-orders",
        headers=h,
        json={"voyage_id": voyage["id"], "grade": "VLSFO", "qty_ordered": 50.0, "unit_price": 600.0},
    )
    assert bo.status_code in (200, 201), bo.text
    pda = client.post(
        "/api/v1/port-disbursements",
        headers=h,
        json={"voyage_id": voyage["id"], "pda_amount": 5000.0},
    )
    assert pda.status_code in (200, 201), pda.text

    pnl = client.get(f"/api/v1/coa/{coa['id']}/pnl", headers=h).json()
    assert pnl["completed_liftings"] == 1
    assert pnl["completed_qty"] == 1000.0
    assert pnl["revenue"] == 50000.0
    assert pnl["fuel_cost"] == 30000.0
    assert pnl["other_cost"] == 5000.0
    assert pnl["pnl_fuel_neutral"] == 45000.0
    assert pnl["pnl_gross"] == 15000.0


def test_coa_state_transitions(client, auth_headers):
    h = auth_headers
    charter = _make_charter(client, h)
    coa = _make_coa(client, h, charter["id"])

    # 非法跃迁 draft → completed → 409
    bad = client.post(f"/api/v1/coa/contracts/{coa['id']}/transition", headers=h, params={"target": "completed"})
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "INVALID_STATE"

    assert client.post(f"/api/v1/coa/contracts/{coa['id']}/transition", headers=h, params={"target": "active"}).json()["status"] == "active"
    assert client.post(f"/api/v1/coa/contracts/{coa['id']}/transition", headers=h, params={"target": "completed"}).json()["status"] == "completed"
    # 终态不可再流转
    again = client.post(f"/api/v1/coa/contracts/{coa['id']}/transition", headers=h, params={"target": "active"})
    assert again.status_code == 409

    # 完成后的合同不可再加分单
    late = _add_itinerary(client, h, coa["id"], 9, 1.0)
    assert late.status_code == 422
    assert late.json()["detail"]["code"] == "COA_NOT_EDITABLE"


# ── Phase 7: Trade CRUD + legs ───────────────────────────────────────────────


def test_trade_crud_and_legs(client, auth_headers):
    h = auth_headers
    trade = _make_trade(client, h)
    assert trade["trade_no"].startswith("TRD-")
    assert trade["status"] == "draft"
    assert trade["legs"] == []

    # 带腿创建
    t2 = _make_trade(
        client,
        h,
        legs=[
            {"leg_no": 1, "period_from": "2026-10-01", "period_to": "2026-10-31", "qty": 500.0, "fixed_price": 48.0},
            {"leg_no": 2, "period_from": "2026-11-01", "period_to": "2026-11-30", "qty": 500.0, "fixed_price": 52.0},
        ],
    )
    assert [lg["leg_no"] for lg in t2["legs"]] == [1, 2]
    assert t2["legs"][0]["fixed_price"] == 48.0

    # 腿量合计超交易量 → 422
    _make_trade(client, h, kind="swap", buy_sell="sell", qty=200.0)
    bad = client.post(
        "/api/v1/trading/trades",
        headers=h,
        json={
            "kind": "swap", "buy_sell": "sell", "qty": 100.0, "price": 10.0,
            "legs": [{"leg_no": 1, "period_from": "2026-10-01", "period_to": "2026-10-31", "qty": 200.0}],
        },
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "TRADE_LEG_QTY_EXCEEDED"

    # 更新
    patched = client.patch(f"/api/v1/trading/trades/{trade['id']}", headers=h, json={"price": 55.5}).json()
    assert patched["price"] == 55.5

    # 整体换腿
    replaced = client.post(
        f"/api/v1/trading/trades/{trade['id']}/legs",
        headers=h,
        json={"legs": [{"leg_no": 1, "period_from": "2026-10-01", "period_to": "2026-12-31", "qty": 1000.0, "fixed_price": 51.0}]},
    ).json()
    assert len(replaced["legs"]) == 1
    assert replaced["legs"][0]["qty"] == 1000.0

    # 列表过滤
    listed = client.get("/api/v1/trading/trades", headers=h, params={"kind": "ffa"}).json()
    assert listed["total"] == 2
    assert all(item["kind"] == "ffa" for item in listed["items"])
    listed = client.get("/api/v1/trading/trades", headers=h, params={"kind": "swap"}).json()
    assert listed["total"] >= 1

    # 详情
    detail = client.get(f"/api/v1/trading/trades/{trade['id']}", headers=h).json()
    assert detail["trade_no"] == trade["trade_no"]


def test_trade_state_transitions(client, auth_headers):
    h = auth_headers
    trade = _make_trade(client, h)

    bad = client.post(f"/api/v1/trading/trades/{trade['id']}/transition", headers=h, params={"target": "settled"})
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "INVALID_STATE"

    assert client.post(f"/api/v1/trading/trades/{trade['id']}/transition", headers=h, params={"target": "confirmed"}).json()["status"] == "confirmed"
    # confirmed 只能 → settled | cancelled
    back = client.post(f"/api/v1/trading/trades/{trade['id']}/transition", headers=h, params={"target": "draft"})
    assert back.status_code == 409
    assert client.post(f"/api/v1/trading/trades/{trade['id']}/transition", headers=h, params={"target": "settled"}).json()["status"] == "settled"
    # 终态
    assert client.post(f"/api/v1/trading/trades/{trade['id']}/transition", headers=h, params={"target": "cancelled"}).status_code == 409

    # settled 后锁定不可改
    locked = client.patch(f"/api/v1/trading/trades/{trade['id']}", headers=h, json={"price": 1.0})
    assert locked.status_code == 422
    assert locked.json()["detail"]["code"] == "TRADE_LOCKED"


# ── Phase 7: MtM（确定性金样）────────────────────────────────────────────────


def test_mtm_calculation_gold(client, auth_headers):
    """金样：buy 1000@50，行情 60 → unrealized = +10,000；
    sell 500@50 → unrealized = −5,000；腿已结算 2,000 → realized。"""
    h = auth_headers
    q = client.post("/api/v1/market/quotes", headers=h, params={"symbol": "TCE_C5_PAC", "value": 60.0, "quote_date": "2026-09-01"})
    assert q.status_code == 200, q.text

    buy = _make_trade(client, h)
    sell = _make_trade(client, h, buy_sell="sell", qty=500.0)
    settled = _make_trade(
        client,
        h,
        qty=1000.0,
        legs=[{"leg_no": 1, "period_from": "2026-10-01", "period_to": "2026-12-31", "qty": 1000.0, "fixed_price": 50.0, "settlement_amount": 2000.0}],
    )

    run = client.post("/api/v1/trading/mtm/run", headers=h, params={"date": "2026-09-01"})
    assert run.status_code == 200, run.text
    body = run.json()
    by_id = {row["trade_id"]: row for row in body["trades"]}

    assert by_id[buy["id"]]["market_price"] == 60.0
    assert by_id[buy["id"]]["book_price"] == 50.0
    assert by_id[buy["id"]]["unrealized_pnl"] == 10000.0  # (60−50)×1000×buy
    assert by_id[sell["id"]]["unrealized_pnl"] == -5000.0  # (60−50)×500×sell
    assert by_id[settled["id"]]["unrealized_pnl"] == 10000.0
    assert by_id[settled["id"]]["realized_pnl"] == 2000.0  # 腿结算

    assert body["totals"]["unrealized_pnl"] == 15000.0
    assert body["totals"]["realized_pnl"] == 2000.0
    assert body["by_kind"]["ffa"]["trades"] == 3

    # summary 端点同口径
    summary = client.get("/api/v1/trading/mtm/summary", headers=h, params={"date": "2026-09-01"}).json()
    assert summary["totals"] == body["totals"]


def test_mtm_uses_latest_quote_on_or_before(client, auth_headers):
    h = auth_headers
    client.post("/api/v1/market/quotes", headers=h, params={"symbol": "TCE_C5_PAC", "value": 40.0, "quote_date": "2026-08-01"})
    client.post("/api/v1/market/quotes", headers=h, params={"symbol": "TCE_C5_PAC", "value": 70.0, "quote_date": "2026-08-20"})
    trade = _make_trade(client, h)

    run = client.post("/api/v1/trading/mtm/run", headers=h, params={"date": "2026-08-15"}).json()
    row = run["trades"][0]
    assert row["market_price"] == 40.0  # 估值日只取 <= 的最近一条
    assert row["unrealized_pnl"] == -10000.0  # (40−50)×1000

    run = client.post("/api/v1/trading/mtm/run", headers=h, params={"date": "2026-09-15"}).json()
    assert run["trades"][0]["market_price"] == 70.0
    assert trade["id"]  # smoke


# ── Phase 7: 持仓净额 / 敞口 ─────────────────────────────────────────────────


def test_position_netting(client, auth_headers):
    """纸货-实货净额：physical buy 1000 − paper sell 400 → net 600。"""
    h = auth_headers
    _make_trade(client, h, kind="physical", buy_sell="buy", qty=1000.0, route="C5", index_symbol=None)
    _make_trade(client, h, kind="ffa", buy_sell="sell", qty=400.0, route="C5", index_symbol=None)
    _make_trade(client, h, kind="ffa", buy_sell="buy", qty=100.0, route="P6A", index_symbol=None)

    pos = client.get("/api/v1/trading/positions", headers=h).json()
    routes = {row["route"]: row for row in pos["routes"]}
    assert routes["C5"]["physical_net"] == 1000.0
    assert routes["C5"]["paper_net"] == -400.0
    assert routes["C5"]["net_qty"] == 600.0
    assert routes["P6A"]["paper_net"] == 100.0
    assert pos["totals"]["net_qty"] == 700.0

    # 按 route 过滤
    only = client.get("/api/v1/trading/positions", headers=h, params={"route": "C5"}).json()
    assert [row["route"] for row in only["routes"]] == ["C5"]

    # 按期间过滤：窗口不含 C5 期间 → 0
    window = client.get(
        "/api/v1/trading/positions", headers=h, params={"route": "C5", "period_from": "2027-01-01", "period_to": "2027-03-31"}
    ).json()
    assert window["routes"] == []

    # 敞口端点
    exp = client.get("/api/v1/trading/exposure", headers=h, params={"date": "2026-09-01"}).json()
    assert exp["totals"]["trades"] >= 3
    assert exp["totals"]["gross_qty"] >= 1500.0


def test_trade_and_coa_tenant_isolation(client, auth_headers):
    """跨租户读写一律 404（不泄露存在性）。"""
    ha = auth_headers
    _, hb = create_tenant(client, code="globex-td", name="Globex Trading", admin_email="td-admin@globex.example.com")

    # B 租户建合同 + 交易
    charter_b = _make_charter(client, hb)
    coa_b = _make_coa(client, hb, charter_b["id"])
    trade_b = _make_trade(client, hb)

    # A 不能读/改/流转 B 的资源
    for resp in (
        client.get(f"/api/v1/coa/contracts/{coa_b['id']}", headers=ha),
        client.patch(f"/api/v1/coa/contracts/{coa_b['id']}", headers=ha, json={"rate": 1.0}),
        client.post(f"/api/v1/coa/contracts/{coa_b['id']}/transition", headers=ha, params={"target": "active"}),
        client.get(f"/api/v1/coa/{coa_b['id']}/allocation", headers=ha),
        client.get(f"/api/v1/coa/{coa_b['id']}/pnl", headers=ha),
        client.get(f"/api/v1/trading/trades/{trade_b['id']}", headers=ha),
        client.patch(f"/api/v1/trading/trades/{trade_b['id']}", headers=ha, json={"price": 1.0}),
        client.post(f"/api/v1/trading/trades/{trade_b['id']}/transition", headers=ha, params={"target": "confirmed"}),
        client.delete(f"/api/v1/trading/trades/{trade_b['id']}", headers=ha),
    ):
        assert resp.status_code in (403, 404), resp.text[:200]

    # A 的列表不包含 B 的行
    listed_coa = client.get("/api/v1/coa/contracts", headers=ha).json()
    assert all(item["id"] != coa_b["id"] for item in listed_coa["items"])
    listed_tr = client.get("/api/v1/trading/trades", headers=ha).json()
    assert all(item["id"] != trade_b["id"] for item in listed_tr["items"])

    # A 不能把 B 的票分摊进自己的 COA
    charter_a = _make_charter(client, ha)
    coa_a = _make_coa(client, ha, charter_a["id"], total_qty=1000.0)
    _add_itinerary(client, ha, coa_a["id"], 1, 1000.0)
    lift_b = _add_lifting(client, hb, charter_b["id"], "2026-Q1", 1000.0)
    cross = client.post(
        f"/api/v1/coa/{coa_a['id']}/allocate",
        headers=ha,
        json={"lifting_id": lift_b["id"], "itinerary_seq": 1},
    )
    assert cross.status_code in (403, 404), cross.text[:200]

    # B 的分摊也动不了 A 的分配
    lift_a = _add_lifting(client, ha, charter_a["id"], "2026-Q1", 500.0)
    assert client.post(
        f"/api/v1/coa/{coa_a['id']}/allocate",
        headers=ha,
        json={"lifting_id": lift_a["id"], "itinerary_seq": 1},
    ).status_code == 200
    summary_b = client.get(f"/api/v1/coa/{coa_a['id']}/allocation", headers=hb)
    assert summary_b.status_code in (403, 404)


def test_trade_and_coa_models_are_tenant_scoped(db_engine):
    """模型级：scoped_get 不放行外租户 / 软删除行。"""
    from app.models_coa import CoaContract
    from app.models_domain import Charter
    from app.models_trading import Trade
    from app.services.tenant_guard import scoped_get, scoped_query

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        from sqlalchemy import select

        from app.models import Tenant

        ta = db.scalar(select(Tenant).where(Tenant.code == "demo"))
        tb = db.scalar(select(Tenant).where(Tenant.code != "demo"))
        assert ta is not None
        if tb is None:
            tb = Tenant(name="Iso", code="iso-x", status="active", default_locale="en", default_timezone="UTC", profile_tier="S")
            db.add(tb)
            db.flush()
        ch = Charter(tenant_id=ta.id, charter_no=f"ISO-{ta.id}", charter_type="coa", status="draft")
        db.add(ch)
        db.flush()
        coa = CoaContract(
            tenant_id=ta.id,
            coa_no=f"COA-ISO-{ta.id}",
            charter_id=ch.id,
            total_qty=Decimal("1000"),
            qty_unit="mt",
            period_from=date(2026, 1, 1),
            period_to=date(2026, 12, 31),
            rate_basis="per_mt",
            rate=Decimal("25"),
        )
        trade = Trade(
            tenant_id=ta.id,
            trade_no=f"TRD-ISO-{ta.id}",
            kind="ffa",
            buy_sell="buy",
            qty=Decimal("100"),
            price=Decimal("50"),
            trade_date=date(2026, 9, 1),
        )
        db.add(coa)
        db.add(trade)
        db.commit()

        assert scoped_get(db, CoaContract, coa.id, ta.id) is not None
        assert scoped_get(db, CoaContract, coa.id, tb.id) is None
        assert scoped_get(db, Trade, trade.id, tb.id) is None

        from datetime import datetime, timezone

        coa.deleted_at = datetime.now(timezone.utc)
        db.commit()
        assert scoped_get(db, CoaContract, coa.id, ta.id) is None  # 软删除过滤
        assert scoped_get(db, CoaContract, coa.id, ta.id, include_deleted=True) is not None

        rows = db.scalars(scoped_query(db, Trade, ta.id)).all()
        assert any(t.id == trade.id for t in rows)
        rows = db.scalars(scoped_query(db, Trade, tb.id)).all()
        assert all(t.id != trade.id for t in rows)
