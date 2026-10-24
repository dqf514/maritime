"""金额舍入口径 + 红冲反分录（审计 P1-B3 / P0-B2）。

三组回归：

1. **舍入**：钱一律 ``Decimal`` + 显式 ``ROUND_HALF_UP``。内建 ``round()`` 走
   银行家舍入（``.5`` 往偶数靠），0.125 → 0.12 —— 与系统其余口径不一致，
   同一张单据在两条链路上能差半分。本文件锁住受影响的两条链路：
   ``routers/finance_ext.py``（FuelEU / ETS 碳成本）与 ``services/sensitivity.py``。

2. **敏感性分析**：内部全程 Decimal，出口才转 float（JSON 形状不变）。

3. **红冲反分录（P0-B2）**：红冲必须把原发票已过账的分录按**同一套科目、
   金额相反**冲回 —— 否则总账与单据（子账）分叉、试算平衡表是错的。
   反向分录必须**幂等**：重复跑不会二次过账。
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_domain import Estimate, Invoice
from app.models_gl import PeriodJournal
from app.models_wave1 import Company
from app.services import money as M
from app.services.finance_workflow import post_credit_note_reversal


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db_session) -> uuid.UUID:
    return db_session.scalar(select(Company).limit(1)).tenant_id


# —— 1. 舍入：ROUND_HALF_UP，不是银行家舍入 ————————————————————


def test_money_ssn_is_half_up():
    """口径 SSOT 本身：0.125 / 2.675 一律「四舍五入」，不往偶数靠。"""
    assert M.money(Decimal("0.125")) == Decimal("0.13")
    assert M.money(Decimal("2.675")) == Decimal("2.68")
    # 银行家舍入会给 0.12 / 2.67 —— 系统里不允许出现这两个值
    assert round(0.125, 2) == 0.12
    assert M.round_half_up(Decimal("0.125"), 2) == Decimal("0.13")


def test_fueleu_calc_rounds_money_half_up(client, auth_headers):
    """``/emissions/fueleu-calc`` 的碳成本按四舍五入，不是银行家舍入。

    lng 1t → co2e 2.75 t；ETS 价 1.82 → ets_cost = 2.75 × 1.82 = **5.005**
    —— 正好落在半分上：四舍五入 = 5.01，银行家舍入 = 5.00。
    """
    h = auth_headers
    r = client.post(
        "/api/v1/emissions/fueleu-calc",
        headers=h,
        json={"lng_mt": 1.0, "ets_price_eur": 1.82},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ets_allowances_t"] == pytest.approx(2.75)
    # 四舍五入（HALF_UP）
    assert body["ets_cost_eur"] == 5.01
    assert body["total_compliance_cost_eur"] == 5.01
    # 银行家舍入会给 5.0 —— 不允许
    assert body["ets_cost_eur"] != 5.0


def test_sensitivity_is_decimal_derived_and_half_up(db_session, client, auth_headers):
    """敏感性分析：内部 Decimal，出口 JSON 仍是 float，且按四舍五入量化。"""
    from app.services import sensitivity as sens

    # 内部口径：收入 / 成本都是 Decimal
    revenue, costs = sens._extract_pnl({"total_revenue": 100.005}, {})
    assert isinstance(revenue, Decimal)
    assert all(isinstance(v, Decimal) for v in costs.values())
    assert sens._recalculate_pnl(revenue, costs, "freight_rate", Decimal("1.1")) == revenue * Decimal("1.1")

    h = auth_headers
    created = client.post(
        "/api/v1/estimates",
        headers=h,
        json={"title": "ROUND-UP", "mode": "voyage", "inputs": {"cargo_qty": 1000, "freight_rate": 30}},
    )
    assert created.status_code in (200, 201), created.text
    eid = created.json()["id"]

    # 手工塞一份「第三位小数是 5」的估价结果
    est = db_session.get(Estimate, uuid.UUID(eid))
    est.results = {"total_revenue": 100.005, "voyage_cost": 0, "bunker_cost": 0, "hire_cost": 0}
    db_session.commit()

    r = client.get(f"/api/v1/estimates/{eid}/sensitivity", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    # base_pnl = 100.005 → 四舍五入 100.01（银行家舍入会给 100.0）
    assert body["base_pnl"] == 100.01
    assert body["base_pnl"] != 100.0
    # JSON 形状不变：仍然是 float
    assert isinstance(body["base_pnl"], float)
    assert isinstance(body["perturbations"], list)
    assert body["perturbations"][0]["parameter"] == "freight_rate"


# —— 2. 红冲的反向分录（P0-B2）———————————————————————————————


def _issue_invoice(client, h, amount=1000.0, tax=0.0) -> str:
    inv = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"amount": amount, "tax_amount": tax, "currency": "USD"},
    ).json()
    iid = inv["id"]
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=issued", headers=h).status_code == 200
    return iid


def _journal_of(db, invoice_id):
    return db.scalar(
        select(PeriodJournal).where(
            PeriodJournal.journal_type == "invoice",
            PeriodJournal.source_type == "invoice",
            PeriodJournal.source_id == invoice_id,
        )
    )


def _net_by_account(journals) -> dict[str, Decimal]:
    """若干张分录的逐科目净额（借 − 贷）。"""
    net: dict[str, Decimal] = {}
    for j in journals:
        for e in j.entries or []:
            code = str(e.get("account_code") or e.get("account") or "")
            if not code:
                continue
            net[code] = net.get(code, Decimal("0")) + Decimal(str(e.get("debit") or 0)) - Decimal(str(e.get("credit") or 0))
    return net


def _ensure_reversal(db, tenant_id, orig, cn_inv):
    """确保红冲的反向分录存在（路由接线前由服务层补，接线后直接命中幂等）。

    返回 ``(journal, created)``。``created=False`` 说明路由已经写过这张分录。
    """
    journal, created = post_credit_note_reversal(db, tenant_id, orig, cn_inv)
    db.commit()
    assert journal is not None, "红冲必须写一张反向分录"
    return journal, created


def test_credit_note_posts_reversing_journal(client, auth_headers, db_session):
    """红冲 → 原分录被冲回：总账净额与单据净额一致（都是 0）。"""
    h = auth_headers
    tenant_id = _tenant_id(db_session)

    iid = _issue_invoice(client, h, amount=1000.0)
    posted = client.post(f"/api/v1/invoices/{iid}/gl-post", headers=h)
    assert posted.status_code == 200, posted.text

    cn = client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 1000.0})
    assert cn.status_code == 200, cn.text
    cn_body = cn.json()
    cn_invoice_id = uuid.UUID(cn_body["invoice_id"])

    orig = db_session.get(Invoice, uuid.UUID(iid))
    cn_inv = db_session.get(Invoice, cn_invoice_id)
    assert cn_inv is not None and cn_inv.credit_note_of_id == orig.id

    # 会计侧：红冲把原分录冲回（路由接线前由服务层补，接线后这里是幂等兜底）
    journal, _created = _ensure_reversal(db_session, tenant_id, orig, cn_inv)
    assert journal.tenant_id == tenant_id

    original_journal = _journal_of(db_session, orig.id)
    assert original_journal is not None

    # 总账净额 = 0（两张分录逐科目相抵）
    net = _net_by_account([original_journal, journal])
    assert net, "分录不能为空"
    assert all(v == 0 for v in net.values()), f"GL 未冲平: {net}"

    # 单据（子账）净额 = 0 —— 总账与单据口径一致
    from app.services.money import invoice_base_gross

    invoice_net = invoice_base_gross(orig) + invoice_base_gross(cn_inv)
    assert invoice_net == 0

    # 反向分录的科目与原分录一一对应（同一套科目、金额相反）
    assert {e["account_code"] for e in journal.entries} == {
        e["account_code"] for e in original_journal.entries
    }


def test_credit_note_reversal_is_idempotent(client, auth_headers, db_session):
    """重复跑红冲的反向分录 → 不会二次过账。"""
    h = auth_headers
    tenant_id = _tenant_id(db_session)

    iid = _issue_invoice(client, h, amount=1000.0)
    assert client.post(f"/api/v1/invoices/{iid}/gl-post", headers=h).status_code == 200
    cn = client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 1000.0}).json()

    orig = db_session.get(Invoice, uuid.UUID(iid))
    cn_inv = db_session.get(Invoice, uuid.UUID(cn["invoice_id"]))

    first, _ = _ensure_reversal(db_session, tenant_id, orig, cn_inv)

    second, created_second = post_credit_note_reversal(db_session, tenant_id, orig, cn_inv)
    db_session.commit()
    assert created_second is False, "重复过账必须幂等"
    assert second.id == first.id

    rows = db_session.scalars(
        select(PeriodJournal).where(
            PeriodJournal.tenant_id == tenant_id,
            PeriodJournal.journal_type == "invoice",
            PeriodJournal.source_type == "invoice",
            PeriodJournal.source_id == cn_inv.id,
        )
    ).all()
    assert len(rows) == 1, "红冲只能有一张分录"

    # 净额仍然相抵（没有多冲一次）
    original_journal = _journal_of(db_session, orig.id)
    net = _net_by_account([original_journal, first])
    assert all(v == 0 for v in net.values())


def test_credit_note_without_posted_original_has_no_journal(client, auth_headers, db_session):
    """原发票没过账 → 总账里没有可冲的分录，不凭空多一张。"""
    h = auth_headers
    tenant_id = _tenant_id(db_session)

    iid = _issue_invoice(client, h, amount=500.0)
    cn = client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 500.0}).json()

    orig = db_session.get(Invoice, uuid.UUID(iid))
    cn_inv = db_session.get(Invoice, uuid.UUID(cn["invoice_id"]))

    journal, created = post_credit_note_reversal(db_session, tenant_id, orig, cn_inv)
    db_session.commit()
    assert journal is None
    assert created is False
    assert _journal_of(db_session, cn_inv.id) is None


def test_credit_note_reversal_uses_original_accounts_for_payable_invoice(
    client, auth_headers, db_session
):
    """成本侧发票（港口使费 PDA）：反分录用**原发票的应付/费用科目**。

    红冲单自己的类型是 XREV（收入侧）—— 如果按红冲单取科目，就会出现
    「冲应付账款却挂到应收账款」的错误，总账越冲越乱。
    """
    h = auth_headers
    tenant_id = _tenant_id(db_session)

    inv = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"invoice_type": "port_disbursement", "amount": 800.0, "currency": "USD"},
    ).json()
    iid = inv["id"]
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=issued", headers=h).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/gl-post", headers=h).status_code == 200

    cn = client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 800.0}).json()
    orig = db_session.get(Invoice, uuid.UUID(iid))
    cn_inv = db_session.get(Invoice, uuid.UUID(cn["invoice_id"]))

    journal, _created = _ensure_reversal(db_session, tenant_id, orig, cn_inv)

    original_journal = _journal_of(db_session, orig.id)
    # 科目集合一致（同一套科目、金额相反）
    assert {e["account_code"] for e in journal.entries} == {
        e["account_code"] for e in original_journal.entries
    }
    # 逐科目净额相抵
    net = _net_by_account([original_journal, journal])
    assert all(v == 0 for v in net.values()), f"GL 未冲平: {net}"
    # 借贷方向确实对调了
    for e in journal.entries:
        orig_entry = next(
            x for x in original_journal.entries if x["account_code"] == e["account_code"]
        )
        assert Decimal(str(e["debit"])) == Decimal(str(orig_entry["credit"]))
        assert Decimal(str(e["credit"])) == Decimal(str(orig_entry["debit"]))


def test_issue_credit_note_service_writes_document_invoice_and_journal(
    client, auth_headers, db_session
):
    """``services.finance_workflow.issue_credit_note`` —— 完整红冲工作流。

    这是路由层（``routers/invoices.py``）接线时要调用的入口：凭证行 + 负数
    发票行 + 反向分录在同一事务里写完。
    """
    from fastapi import HTTPException

    from app.models_finance_ext import CreditNote
    from app.services.finance_workflow import issue_credit_note

    h = auth_headers
    tenant_id = _tenant_id(db_session)

    iid = _issue_invoice(client, h, amount=1000.0)
    assert client.post(f"/api/v1/invoices/{iid}/gl-post", headers=h).status_code == 200

    orig = db_session.get(Invoice, uuid.UUID(iid))
    cn, cn_inv = issue_credit_note(db_session, tenant_id, orig, 1000.0, reason="wrong rate")
    db_session.commit()

    assert cn.status == "issued"
    assert cn.amount == Decimal("1000.00")
    assert cn_inv.amount == Decimal("-1000.00")
    assert cn_inv.credit_note_of_id == orig.id

    original_journal = _journal_of(db_session, orig.id)
    reversal = _journal_of(db_session, cn_inv.id)
    assert reversal is not None, "红冲必须写反向分录"

    net = _net_by_account([original_journal, reversal])
    assert all(v == 0 for v in net.values()), f"GL 未冲平: {net}"

    # 重复跑同一个工作流不会二次过账（幂等键 = 红冲单自己）
    again, created_again = post_credit_note_reversal(db_session, tenant_id, orig, cn_inv)
    db_session.commit()
    assert created_again is False
    assert again.id == reversal.id

    # 红冲上限：超过未红冲余额 → 409
    with pytest.raises(HTTPException) as exc:
        issue_credit_note(db_session, tenant_id, orig, 1.0)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "CREDIT_EXCEEDS_BALANCE"

    # 凭证行确实落库
    rows = db_session.scalars(
        select(CreditNote).where(CreditNote.tenant_id == tenant_id, CreditNote.invoice_id == orig.id)
    ).all()
    assert [r.amount for r in rows] == [Decimal("1000.00")]


def test_credit_note_before_original_post_is_caught_up(client, auth_headers, db_session):
    """顺序反过来：先红冲、后过账原发票 → 原发票过账时把红冲补上。

    这是 ``post_reversals_for_credit_notes`` 的场景：红冲那一刻总账里还没有
    可冲的分录，原发票过账那一刻必须补，否则总账又和单据分叉。
    """
    from app.services.finance_workflow import post_reversals_for_credit_notes

    h = auth_headers
    tenant_id = _tenant_id(db_session)

    iid = _issue_invoice(client, h, amount=700.0)
    cn = client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 700.0}).json()
    orig = db_session.get(Invoice, uuid.UUID(iid))
    cn_inv = db_session.get(Invoice, uuid.UUID(cn["invoice_id"]))

    # 原发票还没过账 → 红冲没有分录可冲
    assert _journal_of(db_session, cn_inv.id) is None

    # 原发票过账 → 补过账红冲
    # （P0-B2 接线后，**过账入口自己**就会补红冲的分录 —— 路由层
    #  gl_post 调 post_reversals_for_credit_notes；这里断言的是端到端结果，
    #  而不是再手工调一次服务。）
    assert client.post(f"/api/v1/invoices/{iid}/gl-post", headers=h).status_code == 200
    cn_journal = _journal_of(db_session, cn_inv.id)
    assert cn_journal is not None, "原发票过账后，红冲的反向分录必须补上"

    original_journal = _journal_of(db_session, orig.id)
    net = _net_by_account([original_journal, cn_journal])
    assert all(v == 0 for v in net.values()), f"GL 未冲平: {net}"

    # 补过一次之后再补 → 不重复（幂等）
    again = post_reversals_for_credit_notes(db_session, tenant_id, orig)
    db_session.commit()
    assert again == []


