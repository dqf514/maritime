"""10-round full business-cycle simulation — 真实商业运营十轮循环测试.

Each round models one complete desk cycle of a shipping company, covering
compatibility (多单证形态), integrity (账务/状态机/黄金用例) and resilience
(冲突/制裁/告警/跨租户/冲正) so the system is delivery-grade:

  R1  标准航次商业闭环      estimate → CP → voyage → laytime → claim → invoice → GL → complete
  R2  多货估算 + 逾期应收    multi-cargo TCE, AR aging, overdue exception scan, partial payment
  R3  期租租金周期          TC contract → hire surveys → statements → billing schedule
  R4  COA 航次分摊          contract → itineraries → liftings → allocate → fuel-neutral P&L
  R5  滞期费 + PDA/FDA     laytime finalize → demurrage claim settle → disbursement variance
  R6  红冲与付款冲正        credit-note 红冲, payment reversal, GL-posted lock
  R7  偏航监测 + 排期冲突    ETA deviation watch, schedule conflict 409, open positions
  R8  合规阻断              sanctions block, alert-rule block, report-sequence guardrail
  R9  跨租户隔离 + 回收站    tenant B cannot touch A; soft delete → recycle → restore
  R10 平台治理 + 账务审计    GL trial balance/balance sheet, period close lock, SelfCheck, platform RBAC
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

API = "/api/v1"
T0 = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


# ---------- shared helpers ----------

def _items(resp):
    """列表接口信封不统一：裸数组或 {items:[...]} 都兼容。"""
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["items"] if isinstance(data, dict) else data


def _ids(rows):
    return {r["id"] for r in rows if isinstance(r, dict) and "id" in r}


def _first(client, h, path):
    rows = _items(client.get(f"{API}{path}", headers=h))
    assert rows, f"no data at {path}"
    return rows[0]


def _mk_voyage(client, h, tag):
    vessel = _first(client, h, "/masterdata/vessels")
    charter = client.post(
        f"{API}/charters",
        headers=h,
        json={"charter_type": "voyage", "vessel_id": vessel["id"]},
    )
    assert charter.status_code == 200, charter.text
    r = client.post(
        f"{API}/voyages",
        headers=h,
        json={"voyage_no": f"SIM-{tag}", "vessel_id": vessel["id"], "charter_id": charter.json()["id"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _issue_invoice(client, h, *, amount, counterparty_id=None, due_date=None, voyage_id=None):
    body = {"invoice_type": "freight", "amount": amount}
    if counterparty_id:
        body["counterparty_id"] = counterparty_id
    if due_date:
        body["due_date"] = due_date
    if voyage_id:
        body["voyage_id"] = voyage_id
    r = client.post(f"{API}/invoices", headers=h, json=body)
    assert r.status_code == 200, r.text
    iid = r.json()["id"]
    assert client.post(f"{API}/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"{API}/invoices/{iid}/transition?target=issued", headers=h).status_code == 200
    return iid


# ---------- R1 标准航次商业闭环 ----------

def test_round1_standard_voyage_cycle(client, auth_headers):
    """R1: 从估价到航次完成与总账入账的一次完整商业循环。"""
    h = auth_headers
    vessel = _first(client, h, "/masterdata/vessels")
    party = _first(client, h, "/masterdata/counterparties")
    ports = _items(client.get(f"{API}/masterdata/ports", headers=h))
    load, disc = ports[0], ports[1]

    est = client.post(
        f"{API}/estimates",
        headers=h,
        json={
            "title": "SIM-R1 Iron Ore Tubarao–Qingdao",
            "vessel_id": vessel["id"],
            "counterparty_id": party["id"],
            "inputs": {
                "cargo_qty": 180000,
                "freight_rate": 21.0,
                "commission_pct": 2.5,
                "sea_days": 35,
                "port_days": 9,
                "bunker_sea_tpd": 30,
                "bunker_port_tpd": 4,
                "bunker_price": 520,
                "port_costs": 90000,
                "cargo": "Iron Ore",
            },
        },
    )
    assert est.status_code == 200, est.text
    est_id = est.json()["id"]
    calc = client.post(f"{API}/estimates/{est_id}/calculate", headers=h)
    assert calc.status_code == 200
    assert calc.json()["results"]["tce"] > 0

    cp = client.post(f"{API}/estimates/{est_id}/to-charter", headers=h)
    assert cp.status_code == 200, cp.text
    cid = cp.json()["id"]
    # 状态机：草稿直接生效必须被拦
    assert client.post(f"{API}/charters/{cid}/transition", headers=h, json={"target": "active"}).status_code == 409
    assert client.post(f"{API}/charters/{cid}/transition", headers=h, json={"target": "pending_approval"}).status_code == 200
    assert client.post(f"{API}/charters/{cid}/transition", headers=h, json={"target": "active"}).status_code == 200

    voyages = _items(client.get(f"{API}/voyages", headers=h))
    voyage_id = voyages[0]["id"]
    assert client.post(f"{API}/voyages/{voyage_id}/transition", headers=h, json={"target": "in_progress"}).status_code == 200

    now = datetime.now(timezone.utc)
    pc1 = client.post(
        f"{API}/port-calls",
        headers=h,
        json={"voyage_id": voyage_id, "port_id": load["id"], "seq": 1, "purpose": "load",
              "eta": (now + timedelta(days=3)).isoformat()},
    )
    assert pc1.status_code == 200
    pc2 = client.post(
        f"{API}/port-calls",
        headers=h,
        json={"voyage_id": voyage_id, "port_id": disc["id"], "seq": 2, "purpose": "discharge",
              "eta": (now + timedelta(days=25)).isoformat()},
    )
    assert pc2.status_code == 200
    noon = client.post(
        f"{API}/noon-reports",
        headers=h,
        json={"voyage_id": voyage_id, "report_at": now.isoformat(), "speed": 13.0,
              "rob_fo": 900, "eta_next": (now + timedelta(days=3, hours=6)).isoformat()},
    )
    assert noon.status_code == 200
    assert noon.json()["eta_deviation_hours"] is not None
    assert client.post(
        f"{API}/sof-events",
        headers=h,
        json={"port_call_id": pc1.json()["id"], "event_code": "NOR",
              "event_at": now.isoformat(), "local_tz": "Asia/Shanghai"},
    ).status_code == 200

    # 运费发票 → 全额收款 → 入账
    iid = _issue_invoice(client, h, amount=950000, counterparty_id=party["id"],
                         voyage_id=voyage_id, due_date=(date.today() + timedelta(days=30)).isoformat())
    pay = client.post(f"{API}/invoices/{iid}/payments?amount=950000&reference=SIM-R1-FULL", headers=h)
    assert pay.status_code == 200
    assert pay.json()["status"] == "paid"
    posted = client.post(f"{API}/invoices/{iid}/gl-post", headers=h)
    assert posted.status_code == 200 and posted.json()["gl_posted"] is True

    pnl = client.get(f"{API}/analytics/reports/voyage-pnl", headers=h)
    assert pnl.status_code == 200
    assert client.post(f"{API}/voyages/{voyage_id}/transition", headers=h, json={"target": "completed"}).status_code == 200


# ---------- R2 多货估算 + 逾期应收 ----------

def test_round2_multi_cargo_estimate_and_overdue_ar(client, auth_headers):
    """R2: 多港装多货种估算（引擎层）+ 逾期应收扫描与账龄。"""
    h = auth_headers
    # 引擎层多货估算（与 fixtures/calc/tce/gold_multi_* 同一契约）
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "sea_days": 12,
            "port_days": 3,
            "bunker_sea_tpd": 25,
            "bunker_port_tpd": 5,
            "bunker_price": 500,
            "commission_pct": 5,
            "cargoes": [
                {"qty": 50000, "freight_basis": "per_mt", "freight_rate": 12},
                {"qty": 30000, "freight_basis": "lump_sum", "lump_sum_freight": 250000},
            ],
        }
    )
    assert out["freight_basis"] == "multi"
    assert out["cargo_count"] == 2
    assert out["parcel_qty_total"] == 80000
    assert out["tce"] > 0

    # 产品面：场景克隆与对比
    vessel = _first(client, h, "/masterdata/vessels")
    party = _first(client, h, "/masterdata/counterparties")
    est = client.post(
        f"{API}/estimates",
        headers=h,
        json={"title": "SIM-R2 Scenario A", "vessel_id": vessel["id"], "counterparty_id": party["id"],
              "inputs": {"cargo_qty": 80000, "freight_rate": 14.0, "commission_pct": 5,
                         "sea_days": 12, "port_days": 3, "bunker_sea_tpd": 25,
                         "bunker_port_tpd": 5, "bunker_price": 500}},
    )
    assert est.status_code == 200
    est_id = est.json()["id"]
    client.post(f"{API}/estimates/{est_id}/calculate", headers=h)
    clone = client.post(f"{API}/estimates/{est_id}/clone", headers=h)
    assert clone.status_code == 200
    cmp = client.post(f"{API}/estimates/compare", headers=h, json=[est_id, clone.json()["id"]])
    assert cmp.status_code == 200 and len(cmp.json()) == 2

    # 逾期应收：昨天到期未收 → 账龄 + 例外扫描
    iid = _issue_invoice(client, h, amount=1500, counterparty_id=party["id"],
                         due_date=(date.today() - timedelta(days=40)).isoformat())
    assert client.post(f"{API}/invoices/{iid}/payments?amount=400&reference=SIM-R2-PART", headers=h).status_code == 200
    aging = client.get(f"{API}/finance/aging", headers=h)
    assert aging.status_code == 200
    row = next((r for r in aging.json() if r["invoice_no"]), None)
    assert row is not None
    # 部分收款后仍有敞口
    assert any(Decimal(str(r["open_amount"])) > 0 for r in aging.json())
    scan = client.get(f"{API}/exceptions/scan", headers=h)
    assert scan.status_code == 200
    kinds = {i["kind"] for i in scan.json()["items"]}
    assert "invoice_overdue" in kinds
    overdue = next(i for i in scan.json()["items"] if i["kind"] == "invoice_overdue")
    assert overdue["severity"] in ("warning", "critical")


# ---------- R3 期租租金周期 ----------

def test_round3_time_charter_hire_cycle(client, auth_headers):
    """R3: 期租合同 → 交船检验 → 租金账单 → 计费计划 → 还船检验。"""
    h = auth_headers
    vessel = _first(client, h, "/masterdata/vessels")
    party = _first(client, h, "/masterdata/counterparties")

    charter = client.post(
        f"{API}/charters",
        headers=h,
        json={"charter_type": "tct", "counterparty_id": party["id"], "hire_per_day": 15000},
    )
    assert charter.status_code == 200, charter.text
    cid = charter.json()["id"]

    tc = client.post(
        f"{API}/tc/contracts",
        headers=h,
        json={"charter_id": cid, "contract_type": "tci", "contract_style": "time_charter",
              "vessel_id": vessel["id"], "counterparty_id": party["id"], "hire_rate": 15000,
              "delivery_date": "2026-04-01", "redelivery_date": "2026-06-30",
              "payment_frequency": "semi_monthly"},
    )
    assert tc.status_code == 201, tc.text
    tc_id = tc.json()["id"]

    # 非法状态跳转
    assert client.post(f"{API}/tc/contracts/{tc_id}/transition", headers=h,
                       params={"target": "completed"}).status_code == 409
    assert client.post(f"{API}/tc/contracts/{tc_id}/transition", headers=h,
                       params={"target": "active"}).status_code == 200

    # 交船/还船检验
    on = client.post(f"{API}/charters/{cid}/surveys", headers=h,
                     json={"kind": "on_hire", "surveyed_at": "2026-04-01T08:00:00Z",
                           "bunker_fo": 900.0, "bunker_do": 100.0})
    assert on.status_code == 200, on.text
    off = client.post(f"{API}/charters/{cid}/surveys", headers=h,
                      json={"kind": "off_hire", "surveyed_at": "2026-06-29T08:00:00Z",
                            "bunker_fo": 150.0, "bunker_do": 20.0})
    assert off.status_code == 200
    surveys = client.get(f"{API}/charters/{cid}/surveys", headers=h).json()["items"]
    assert [s["kind"] for s in surveys] == ["on_hire", "off_hire"]

    # 租金账单：草稿 → 已发 → 已批 → 已付
    stmt = client.post(f"{API}/hire-statements", headers=h,
                       json={"contract_id": tc_id, "period_start": "2026-04-01", "period_end": "2026-04-30"})
    assert stmt.status_code == 201, stmt.text
    assert stmt.json()["net_hire"] > 0
    sid = stmt.json()["id"]
    for target in ("sent", "approved", "paid"):
        r = client.post(f"{API}/hire-statements/{sid}/transition", headers=h, params={"target": target})
        assert r.status_code == 200, r.text
    assert client.post(f"{API}/hire-statements/{sid}/transition", headers=h,
                       params={"target": "sent"}).status_code == 409

    # 计费计划（半月拆分）→ 已开票
    sched = client.post(f"{API}/tc/contracts/{tc_id}/billing-schedule/generate", headers=h,
                        json={"start_date": "2026-04-01", "end_date": "2026-06-30"})
    assert sched.status_code == 201, sched.text
    assert len(sched.json()) >= 5  # 半月拆分：4/1–6/30 至少 5 期
    rows = client.get(f"{API}/tc/contracts/{tc_id}/billing-schedule", headers=h).json()
    patched = client.patch(f"{API}/tc/billing-schedule/{rows[0]['id']}", headers=h, json={"status": "invoiced"})
    assert patched.status_code == 200 and patched.json()["status"] == "invoiced"

    summary = client.get(f"{API}/tc/contracts/{tc_id}/hire-summary", headers=h)
    assert summary.status_code == 200
    assert summary.json()["statement_count"] == 1

    assert client.post(f"{API}/tc/contracts/{tc_id}/transition", headers=h,
                       params={"target": "completed"}).status_code == 200


# ---------- R4 COA 航次分摊 ----------

def test_round4_coa_lifting_allocation_cycle(client, auth_headers):
    """R4: COA 合同 → 行程 → 提货航次 → 分摊 → 油价中性 P&L。"""
    h = auth_headers
    party = _first(client, h, "/masterdata/counterparties")
    vessel = _first(client, h, "/masterdata/vessels")

    charter = client.post(f"{API}/charters", headers=h, json={"charter_type": "coa", "cargo_qty": 60000.0})
    assert charter.status_code == 200, charter.text
    cid = charter.json()["id"]

    coa = client.post(
        f"{API}/coa/contracts",
        headers=h,
        json={"charter_id": cid, "total_qty": 60000.0, "qty_unit": "mt",
              "period_from": "2026-01-01", "period_to": "2026-12-31",
              "rate_basis": "per_mt", "rate": 24.0},
    )
    assert coa.status_code == 201, coa.text
    coa_id = coa.json()["id"]
    assert coa.json()["coa_no"].startswith("COA-")

    assert client.post(f"{API}/coa/contracts/{coa_id}/itineraries", headers=h,
                       json={"seq": 1, "qty": 30000.0}).status_code == 201
    assert client.post(f"{API}/coa/contracts/{coa_id}/itineraries", headers=h,
                       json={"seq": 2, "qty": 30000.0}).status_code == 201
    # 超总量必须被拒
    over = client.post(f"{API}/coa/contracts/{coa_id}/itineraries", headers=h, json={"seq": 3, "qty": 1000.0})
    assert over.status_code == 422

    voyage = _mk_voyage(client, h, "R4-COA")
    voyage_id = voyage["id"]
    # 关联航次的租金发票油料/港使 → P&L 成本项
    assert client.post(f"{API}/bunker-orders", headers=h,
                       json={"voyage_id": voyage_id, "grade": "VLSFO", "qty_ordered": 50.0,
                             "unit_price": 600.0}).status_code == 200
    assert client.post(f"{API}/port-disbursements", headers=h,
                       json={"voyage_id": voyage_id, "pda_amount": 5000.0}).status_code == 200

    lifts = []
    for seq, qty in ((1, 30000.0), (2, 30000.0)):
        r = client.post(f"{API}/charters/{cid}/liftings", headers=h,
                        params={"period_label": f"2026-Q{seq}", "planned_qty": qty})
        assert r.status_code in (200, 201), r.text
        lid = r.json()["id"]
        assert client.post(f"{API}/coa-liftings/{lid}/nominate", headers=h,
                           json={"laycan_from": "2026-05-01T00:00:00Z",
                                 "laycan_to": "2026-05-15T00:00:00Z"}).status_code == 200
        assert client.post(f"{API}/coa-liftings/{lid}/fix", headers=h,
                           json={"voyage_id": voyage_id}).status_code == 200
        assert client.post(f"{API}/coa-liftings/{lid}/complete", headers=h,
                           json={"actual_qty": qty}).status_code == 200
        assert client.post(f"{API}/coa/{coa_id}/allocate", headers=h,
                           json={"lifting_id": lid, "itinerary_seq": seq}).status_code == 200
        lifts.append(lid)

    # 重复分摊必须被拒
    dup = client.post(f"{API}/coa/{coa_id}/allocate", headers=h,
                      json={"lifting_id": lifts[0], "itinerary_seq": 2})
    assert dup.status_code == 422

    alloc = client.get(f"{API}/coa/{coa_id}/allocation", headers=h).json()
    assert alloc["remaining_qty"] == 0
    assert alloc["allocated_qty"] == 60000.0

    pnl = client.get(f"{API}/coa/{coa_id}/pnl", headers=h).json()
    assert pnl["completed_qty"] == 60000.0
    assert pnl["revenue"] > 0
    # 毛利 = 油价中性口径 − 油料成本；中性口径已扣其他成本
    assert pnl["pnl_gross"] == pytest.approx(pnl["pnl_fuel_neutral"] - pnl["fuel_cost"], rel=1e-6)
    assert pnl["pnl_gross"] == pytest.approx(pnl["revenue"] - pnl["fuel_cost"] - pnl["other_cost"], rel=1e-6)

    assert client.post(f"{API}/coa/contracts/{coa_id}/transition", headers=h,
                       params={"target": "active"}).status_code == 200
    # 完成态后不可回退
    assert client.post(f"{API}/coa/contracts/{coa_id}/transition", headers=h,
                       params={"target": "completed"}).status_code == 200
    assert client.post(f"{API}/coa/contracts/{coa_id}/transition", headers=h,
                       params={"target": "active"}).status_code == 409


# ---------- R5 滞期费 + PDA/FDA ----------

def test_round5_demurrage_and_disbursement_cycle(client, auth_headers):
    """R5: 装卸时间计算 → 终稿 → 滞期费索赔结案 → PDA→FDA 差异。"""
    h = auth_headers
    voyage = _mk_voyage(client, h, "R5-DEMI")
    voyage_id = voyage["id"]
    assert client.post(f"{API}/voyages/{voyage_id}/transition", headers=h, json={"target": "in_progress"}).status_code == 200

    ports = _items(client.get(f"{API}/masterdata/ports", headers=h))
    now = datetime.now(timezone.utc)
    pc = client.post(f"{API}/port-calls", headers=h,
                     json={"voyage_id": voyage_id, "port_id": ports[0]["id"], "seq": 1, "purpose": "load",
                           "eta": (now + timedelta(days=1)).isoformat()})
    assert pc.status_code == 200

    lt = client.post(
        f"{API}/laytimes",
        headers=h,
        json={"voyage_id": voyage_id, "port_call_id": pc.json()["id"],
              "inputs": {"allowed_hours": 48, "turn_time_hours": 4, "demurrage_rate_per_day": 18000,
                         "events": [{"start": "2026-09-01T08:00:00", "end": "2026-09-03T20:00:00", "excluded": False},
                                    {"start": "2026-09-02T00:00:00", "end": "2026-09-02T06:00:00", "excluded": True}]}},
    )
    assert lt.status_code == 200, lt.text
    lt_id = lt.json()["id"]
    calc = client.post(f"{API}/laytimes/{lt_id}/calculate", headers=h).json()
    # 60h 计时 − 6h 除外 = 54h > 48h → 6h 滞期 = 6000 @ 18000/日
    assert calc["results"]["amount"] == pytest.approx(6000.0)
    assert client.post(f"{API}/laytimes/{lt_id}/finalize", headers=h).status_code == 200

    claim = client.post(f"{API}/claims", headers=h,
                        json={"voyage_id": voyage_id, "laytime_id": lt_id, "claim_type": "demurrage"})
    assert claim.status_code == 200
    assert claim.json()["amount"] == pytest.approx(6000.0)
    clid = claim.json()["id"]
    for target in ("negotiating", "settled"):
        assert client.post(f"{API}/claims/{clid}/transition", headers=h, params={"target": target}).status_code == 200

    pda = client.post(f"{API}/port-disbursements", headers=h,
                      json={"voyage_id": voyage_id, "pda_amount": 62000, "lines": {"towage": 6000}})
    assert pda.status_code == 200
    pid = pda.json()["id"]
    for target in ("submitted", "approved"):
        assert client.post(f"{API}/port-disbursements/{pid}/transition", headers=h,
                           params={"target": target}).status_code == 200
    fda = client.post(f"{API}/port-disbursements/{pid}/transition", headers=h,
                      params={"target": "fda", "fda_amount": 65500})
    assert fda.status_code == 200
    assert fda.json()["variance"] == pytest.approx(3500.0)


# ---------- R6 红冲与付款冲正 ----------

def test_round6_credit_note_red_flush_and_payment_reversal(client, auth_headers):
    """R6: 红冲约束 + 付款冲正 + 已入账锁定。"""
    h = auth_headers
    party = _first(client, h, "/masterdata/counterparties")

    # —— 红冲 ——
    iid = _issue_invoice(client, h, amount=10000, counterparty_id=party["id"])
    assert client.post(f"{API}/invoices/{iid}/payments?amount=4000&reference=R6-A", headers=h).status_code == 200
    # 已有收款的发票不允许直接 void，必须先红冲
    void0 = client.post(f"{API}/invoices/{iid}/transition?target=void", headers=h)
    assert void0.status_code == 409 and void0.json()["detail"]["code"] == "CREDIT_NOTE_REQUIRED"
    # 超余额红冲被拒
    over = client.post(f"{API}/invoices/{iid}/credit-note", headers=h, json={"amount": 10000.01})
    assert over.status_code == 409 and over.json()["detail"]["code"] == "CREDIT_EXCEEDS_BALANCE"
    cn = client.post(f"{API}/invoices/{iid}/credit-note", headers=h,
                     json={"amount": 4000, "reason": "SIM-R6 refund paid part"})
    assert cn.status_code == 200, cn.text
    assert cn.json()["credit_note_no"].startswith("CN-")
    cns = client.get(f"{API}/invoices/{iid}/credit-notes", headers=h).json()
    assert len(cns) == 1 and cns[0]["amount"] == 4000.0
    assert client.post(f"{API}/invoices/{iid}/transition?target=void", headers=h).json()["status"] == "void"

    # —— 付款冲正 ——
    iid2 = _issue_invoice(client, h, amount=8000, counterparty_id=party["id"])
    assert client.post(f"{API}/invoices/{iid2}/payments?amount=3000&reference=R6-B", headers=h).status_code == 200
    payments = client.get(f"{API}/invoices/{iid2}/payments", headers=h).json()
    pay_id = payments[0]["id"]
    voided = client.post(f"{API}/payments/{pay_id}/void", headers=h)
    assert voided.status_code == 200, voided.text
    body = voided.json()
    assert body["status"] == "issued" and body["paid_amount"] == 0.0
    assert body["reversal_id"]
    # 二次冲正必须被拒
    assert client.post(f"{API}/payments/{pay_id}/void", headers=h).status_code == 409
    # 入账后禁止冲正
    assert client.post(f"{API}/invoices/{iid2}/gl-post", headers=h).status_code == 200
    assert client.post(f"{API}/payments/{pay_id}/void", headers=h).status_code == 409


# ---------- R7 偏航监测 + 排期冲突 ----------

def test_round7_eta_deviation_and_schedule_conflict(client, auth_headers):
    """R7: 午报偏航重算 + ETA 观察哨 + 排期冲突 409 + 空档计算。"""
    h = auth_headers
    voyage = _mk_voyage(client, h, "R7-ETA")
    voyage_id = voyage["id"]
    assert client.post(f"{API}/voyages/{voyage_id}/transition", headers=h, json={"target": "in_progress"}).status_code == 200

    ports = _items(client.get(f"{API}/masterdata/ports", headers=h))
    pc = client.post(f"{API}/port-calls", headers=h,
                     json={"voyage_id": voyage_id, "port_id": ports[0]["id"], "seq": 1, "purpose": "load",
                           "eta": (T0 + timedelta(days=3)).isoformat()})
    assert pc.status_code == 200
    # 先报午报再补 eta_next → 偏航按 (eta_next − 港口 ETA) 重算
    noon = client.post(f"{API}/noon-reports", headers=h,
                       json={"voyage_id": voyage_id, "report_at": T0.isoformat(), "speed": 11.0, "remarks": "ok"})
    assert noon.status_code == 200
    patched = client.patch(f"{API}/noon-reports/{noon.json()['id']}", headers=h,
                           json={"eta_next": (T0 + timedelta(days=4)).isoformat()})
    assert patched.status_code == 200
    assert abs(patched.json()["eta_deviation_hours"] - 24.0) < 0.01

    # 排期：重叠块标记硬冲突；拖拽到冲突窗口必须 409
    vessels = _items(client.get(f"{API}/masterdata/vessels", headers=h))
    vessel_id = vessels[0]["id"]

    def _block(title, start, end):
        r = client.post(f"{API}/scheduling/blocks", headers=h,
                        json={"vessel_id": vessel_id, "title": title,
                              "start_at": start.isoformat(), "end_at": end.isoformat(), "block_type": "voyage"})
        assert r.status_code == 200, r.text
        return r.json()

    a = _block("SIM-R7-A", T0, T0 + timedelta(days=2))
    b = _block("SIM-R7-B", T0 + timedelta(days=1), T0 + timedelta(days=3))
    assert a["hard_conflict"] is False and b["hard_conflict"] is True
    conflicts = client.get(f"{API}/scheduling/conflicts", headers=h).json()
    assert conflicts["total"] >= 1
    bad = client.post(f"{API}/scheduling/blocks/{b['id']}/move", headers=h,
                      json={"start_at": (T0 + timedelta(days=1)).isoformat(),
                            "end_at": (T0 + timedelta(days=3)).isoformat()})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "SCHEDULE_CONFLICT"
    ok = client.post(f"{API}/scheduling/blocks/{b['id']}/move", headers=h,
                     json={"start_at": (T0 + timedelta(days=7)).isoformat(),
                           "end_at": (T0 + timedelta(days=9)).isoformat()})
    assert ok.status_code == 200

    open_pos = client.get(f"{API}/scheduling/open-positions", headers=h,
                          params={"date_from": T0.isoformat(), "date_to": (T0 + timedelta(days=14)).isoformat()})
    assert open_pos.status_code == 200
    assert any(i["vessel_id"] == vessel_id and i["open_days"] > 0 for i in open_pos.json()["items"])


# ---------- R8 合规阻断 ----------

def test_round8_compliance_blockers(client, auth_headers):
    """R8: 制裁名单阻断生效 + 自定义阻断告警 + 航次报告序列护栏。"""
    h = auth_headers
    party = client.post(f"{API}/masterdata/counterparties", headers=h,
                        json={"name": "SIM-R8 Blocked Co", "type": "charterer", "sanctions_status": "blocked"})
    assert party.status_code == 200
    vessel = _first(client, h, "/masterdata/vessels")
    cp = client.post(f"{API}/charters", headers=h,
                     json={"charter_type": "voyage", "vessel_id": vessel["id"], "counterparty_id": party.json()["id"]})
    assert cp.status_code == 200 and cp.json()["sanctions_blocked"] is True
    assert client.post(f"{API}/charters/{cp.json()['id']}/transition", headers=h,
                       json={"target": "pending_approval"}).status_code == 200
    blocked = client.post(f"{API}/charters/{cp.json()['id']}/transition", headers=h, json={"target": "active"})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "SANCTIONS_BLOCKED"

    # 阻断型告警规则：命中条件的写入必须 409
    rule = client.post(f"{API}/config/alert-rules", headers=h,
                       json={"rule_name": "SIM-R8 blocked cargo", "entity_type": "voyage",
                             "condition": {"field": "voyage.cargo", "operator": "eq", "value": "SIM_BLOCKED"},
                             "alert_message": "Blocked cargo", "alert_priority": "urgent", "blocking": True})
    assert rule.status_code in (200, 201), rule.text
    voyage = _mk_voyage(client, h, "R8-BLOCK")
    hit = client.patch(f"{API}/voyages/{voyage['id']}", headers=h, json={"cargo": "SIM_BLOCKED"})
    assert hit.status_code == 409 and hit.json()["detail"]["code"] == "ALERT_BLOCKED"
    miss = client.patch(f"{API}/voyages/{voyage['id']}", headers=h, json={"cargo": "Clean Grain"})
    assert miss.status_code == 200

    # 航次报告阶段序列护栏：跳阶段 409，配置放宽后放行
    v2 = _mk_voyage(client, h, "R8-SEQ")
    vid2 = v2["id"]
    first = client.post(f"{API}/noon-reports", headers=h,
                        json={"voyage_id": vid2, "report_at": T0.isoformat(), "remarks": "cargo loading commenced"})
    assert first.status_code == 200 and first.json()["stage"] == "cargo"
    jump = client.post(f"{API}/noon-reports", headers=h,
                       json={"voyage_id": vid2, "report_at": (T0 + timedelta(hours=12)).isoformat(),
                             "remarks": "arrival at next port"})
    assert jump.status_code == 409 and jump.json()["detail"]["code"] == "REPORT_SEQUENCE"
    flag = client.post(f"{API}/config/flags", headers=h,
                       json={"key": "CFGRelaxReportSequence", "value": "true", "value_type": "bool",
                             "category": "operations"})
    assert flag.status_code in (200, 201)
    relaxed = client.post(f"{API}/noon-reports", headers=h,
                          json={"voyage_id": vid2, "report_at": (T0 + timedelta(hours=12)).isoformat(),
                                "remarks": "arrival at next port"})
    assert relaxed.status_code == 200


# ---------- R9 跨租户隔离 + 回收站 ----------

def test_round9_cross_tenant_isolation_and_recycle_restore(client, auth_headers):
    """R9: 租户 B 无法触达租户 A 数据；软删 → 回收站 → 恢复。"""
    from tests.isolation_helpers import assert_blocked, bootstrap_resources, create_tenant

    ha = auth_headers
    _, hb = create_tenant(client, code="globex", name="Globex Marine", admin_email="Admin@Globex.example.com")
    b = bootstrap_resources(client, hb, "B")

    # B 的资源对 A 不可读不可写
    for method, path in (
        ("get", f"/estimates/{b['estimate_id']}"),
        ("get", f"/masterdata/vessels/{b['vessel_id']}"),
        ("get", f"/invoices/{b['invoice_id']}"),
        ("patch", f"/voyages/{b['voyage_id']}"),
    ):
        if method == "patch":
            resp = client.patch(f"{API}{path}", headers=ha, json={"cargo": "hijack"})
        else:
            resp = client.get(f"{API}{path}", headers=ha)
        assert_blocked(resp, f"A {method} {path}")

    # 列表不泄漏对方主键
    foreign_ids = {v for k, v in b.items() if k.endswith("_id")}
    for path in ("/estimates", "/charters", "/voyages", "/invoices", "/masterdata/vessels"):
        rows = _items(client.get(f"{API}{path}", headers=ha))
        assert not (_ids(rows) & foreign_ids), f"leak at {path}"

    # A 用 B 的外键创建 → 404
    bad = client.post(f"{API}/estimates", headers=ha,
                      json={"title": "SIM-R9 x-tenant", "vessel_id": b["vessel_id"],
                            "counterparty_id": b["counterparty_id"], "inputs": {}})
    assert bad.status_code == 404

    # 回收站：软删 → 恢复 → 复活
    voyage = _mk_voyage(client, ha, "R9-RB")
    pc = client.post(f"{API}/port-calls", headers=ha,
                     json={"voyage_id": voyage["id"], "seq": 1, "purpose": "load"})
    assert pc.status_code == 200
    assert client.delete(f"{API}/port-calls/{pc.json()['id']}", headers=ha).status_code == 200
    rb = client.get(f"{API}/recycle-bin", headers=ha)
    assert rb.status_code == 200
    hit = [x for x in rb.json() if x["entity_type"] == "port_call" and x["entity_id"] == pc.json()["id"]]
    assert hit, "port_call delete should land in recycle bin"
    # B 不能恢复 A 的回收项
    foreign_restore = client.post(f"{API}/recycle-bin/{hit[0]['id']}/restore", headers=hb)
    assert_blocked(foreign_restore, "B restore A recycle item")
    assert client.post(f"{API}/recycle-bin/{hit[0]['id']}/restore", headers=ha).status_code == 200
    rows = _items(client.get(f"{API}/port-calls?voyage_id={voyage['id']}", headers=ha))
    assert any(x["id"] == pc.json()["id"] for x in rows), "restored port call should be listed again"


# ---------- R10 平台治理 + 账务审计 ----------

def test_round10_platform_admin_and_integrity_audit(client, auth_headers):
    """R10: 总账平衡审计 + 期末关账锁定 + SelfCheck 黄金用例 + 平台 RBAC。"""
    h = auth_headers

    def _account(code, name, atype):
        r = client.post(f"{API}/gl/accounts", headers=h,
                        json={"account_code": code, "account_name": name, "account_type": atype})
        assert r.status_code == 200, r.text

    for code, name, atype in (("9910", "SIM Cash", "asset"), ("9920", "SIM Freight Rev", "revenue")):
        _account(code, name, atype)

    j = client.post(f"{API}/gl/journals", headers=h,
                    json={"period": "2026-11", "journal_type": "non_voyage", "description": "SIM-R10 close cycle",
                          "entries": [{"account_code": "9910", "debit": 5000, "credit": 0, "reference": "R10"},
                                      {"account_code": "9920", "debit": 0, "credit": 5000, "reference": "R10"}]})
    assert j.status_code == 200, j.text
    jid = j.json()["id"]
    assert client.post(f"{API}/gl/journals/{jid}/post", headers=h).status_code == 200

    tb = client.get(f"{API}/gl/trial-balance", headers=h, params={"period": "2026-11"}).json()
    assert tb["balanced"] is True
    assert tb["total_debit"] == pytest.approx(tb["total_credit"])
    bs = client.get(f"{API}/gl/balance-sheet", headers=h, params={"period": "2026-11"}).json()
    assert bs["balanced"] is True
    assert bs["total_assets"] == pytest.approx(bs["total_liabilities"] + bs["total_equity"])
    pnl = client.get(f"{API}/gl/income-statement", headers=h, params={"period": "2026-11"}).json()
    assert pnl["net_income"] == pytest.approx(pnl["total_revenue"] - pnl["total_expenses"])

    # 关账锁定 → 解锁后恢复
    close = client.post(f"{API}/gl/periods/2026-11/close", headers=h)
    assert close.status_code == 200 and close.json()["status"] == "closed"
    blocked = client.post(f"{API}/gl/journals", headers=h,
                          json={"period": "2026-11", "journal_type": "non_voyage", "description": "after close",
                                "entries": [{"account_code": "9910", "debit": 1, "credit": 0},
                                            {"account_code": "9920", "debit": 0, "credit": 1}]})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "PERIOD_CLOSED"
    assert client.post(f"{API}/gl/periods/2026-11/open", headers=h).json()["status"] == "open"

    # 自检：黄金用例 + 计算引擎全绿
    sc = client.post(f"{API}/settings/selfcheck/run", headers=h)
    assert sc.status_code == 200, sc.text
    assert sc.json()["score"] == 100
    ids = {r["check_id"] for r in sc.json()["results"]}
    assert {"calc.tce_gold", "calc.laytime_gold"} <= ids

    # 平台租户管理 RBAC
    from tests.isolation_helpers import platform_login

    hp = platform_login(client)
    assert client.get(f"{API}/platform/tenants", headers=hp).status_code == 200
    assert client.get(f"{API}/platform/tenants", headers=h).status_code == 403
