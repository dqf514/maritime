"""财务纵深（Phase 6）：转开/代垫、佣金八类、付款批次、付款条件/方式/账户、
预收预付核销、GL 管理（科目/分录/过账/冲销）与三大报表恒等式。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _create_invoice(client, h, amount=10000, invoice_type="freight"):
    r = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"invoice_type": invoice_type, "amount": amount},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _issue(client, h, iid):
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=issued", headers=h).status_code == 200


def _first_counterparty(client, h):
    rows = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    return rows[0]["id"]


def _mk_account(client, h, code, name, account_type):
    r = client.post(
        "/api/v1/gl/accounts",
        headers=h,
        json={"account_code": code, "account_name": name, "account_type": account_type},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _mk_journal(client, h, lines, period="2026-09", journal_type="non_voyage", expect=200):
    r = client.post(
        "/api/v1/gl/journals",
        headers=h,
        json={"period": period, "journal_type": journal_type, "description": "t", "entries": lines},
    )
    assert r.status_code == expect, r.text
    return r.json()


# —— 1. 转开/代垫 Rebill CRUD + 超额度 ——————————————————————————


def test_rebill_crud_and_over_cap(client, auth_headers):
    h = auth_headers
    cp = _first_counterparty(client, h)
    inv = _create_invoice(client, h, amount=5000)

    r = client.post(
        "/api/v1/rebill-invoices",
        headers=h,
        json={
            "source_invoice_id": inv["id"],
            "source_expense_type": "port_expense",
            "counterparty_id": cp,
            "amount": 1500,
            "currency": "USD",
            "cap_amount": 1000,
            "notes": "agency disbursement",
        },
    )
    assert r.status_code == 200, r.text
    rebill = r.json()
    assert rebill["rebill_no"].startswith("RB-")
    assert rebill["status"] == "draft"
    assert rebill["over_cap"] is True  # 1500 > cap 1000

    over = client.get("/api/v1/rebill-invoices/over-cap", headers=h).json()
    assert any(row["id"] == rebill["id"] for row in over)

    # patch 金额回额度内 → over_cap 复位
    r = client.patch(f"/api/v1/rebill-invoices/{rebill['id']}", headers=h, json={"amount": 500})
    assert r.status_code == 200, r.text
    assert r.json()["over_cap"] is False

    # 状态推进：draft → sent → paid；非法回跳 409
    assert client.post(f"/api/v1/rebill-invoices/{rebill['id']}/transition?target=sent", headers=h).status_code == 200
    bad = client.post(f"/api/v1/rebill-invoices/{rebill['id']}/transition?target=draft", headers=h)
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "INVALID_STATE"
    assert client.post(f"/api/v1/rebill-invoices/{rebill['id']}/transition?target=paid", headers=h).status_code == 200

    # 详情 + 软删除后列表不可见
    assert client.get(f"/api/v1/rebill-invoices/{rebill['id']}", headers=h).json()["status"] == "paid"
    assert client.delete(f"/api/v1/rebill-invoices/{rebill['id']}", headers=h).status_code == 200
    listed = client.get("/api/v1/rebill-invoices", headers=h).json()
    assert all(row["id"] != rebill["id"] for row in listed["items"])


def test_rebill_bad_refs_rejected(client, auth_headers):
    h = auth_headers
    r = client.post(
        "/api/v1/rebill-invoices",
        headers=h,
        json={"source_expense_type": "bogus", "amount": 10},
    )
    assert r.status_code == 422
    r = client.post(
        "/api/v1/rebill-invoices",
        headers=h,
        json={"source_invoice_id": "00000000-0000-0000-0000-000000000000", "amount": 10},
    )
    assert r.status_code == 404


# —— 2. 佣金八类 ————————————————————————————————————————————


def test_commission_all_eight_types(client, auth_headers):
    h = auth_headers
    catalog = client.get("/api/v1/commissions/types", headers=h).json()
    assert len(catalog) == 8
    types = {row["commission_type"] for row in catalog}
    assert types == {
        "address_commission",
        "brokerage",
        "demurrage_commission",
        "claim_commission",
        "freight_relet_commission",
        "owner_commission",
        "bareboat_commission",
        "equipment_commission",
    }

    for ctype in sorted(types):
        r = client.post(
            "/api/v1/commissions/calculate",
            headers=h,
            json={"commission_type": ctype, "base_amount": 10000, "rate_pct": 2.5},
        )
        assert r.status_code == 200, (ctype, r.text)
        assert r.json()["calculated_amount"] == 250.0  # 10000 × 2.5%

        created = client.post(
            "/api/v1/commissions",
            headers=h,
            json={"commission_type": ctype, "base_amount": 10000, "rate_pct": 2.5},
        )
        assert created.status_code == 200, (ctype, created.text)
        assert created.json()["calculated_amount"] == 250.0

    listed = client.get("/api/v1/commissions", headers=h).json()
    assert listed["total"] == 8
    assert {row["commission_type"] for row in listed["items"]} == types

    # 缺省费率：brokerage 1.25%
    calc = client.post(
        "/api/v1/commissions/calculate",
        headers=h,
        json={"commission_type": "brokerage", "base_amount": 80000},
    ).json()
    assert calc["rate_pct"] == 1.25
    assert calc["calculated_amount"] == 1000.0

    bad = client.post(
        "/api/v1/commissions/calculate",
        headers=h,
        json={"commission_type": "unknown_type", "base_amount": 1},
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "BAD_COMMISSION_TYPE"


# —— 3. 付款批次 ————————————————————————————————————————————


def test_payment_batch_lifecycle_and_xml(client, auth_headers):
    h = auth_headers
    inv1 = _create_invoice(client, h, amount=3000)
    inv2 = _create_invoice(client, h, amount=2000)
    _issue(client, h, inv1["id"])
    _issue(client, h, inv2["id"])

    payable = client.get("/api/v1/payments/payable-invoices", headers=h).json()
    assert any(p["id"] == inv1["id"] for p in payable)

    r = client.post(
        "/api/v1/payments/batches",
        headers=h,
        json={"invoice_ids": [inv1["id"], inv2["id"]], "batch_date": "2026-09-30", "bank_charge_mode": "shared"},
    )
    assert r.status_code == 200, r.text
    batch = r.json()
    assert batch["batch_number"].startswith("PB-")
    assert batch["status"] == "draft"
    assert batch["payment_count"] == 2
    assert batch["total_amount"] == 5000.0

    detail = client.get(f"/api/v1/payments/batches/{batch['id']}", headers=h).json()
    assert len(detail["payments"]) == 2

    xml = client.get(f"/api/v1/payments/batches/{batch['id']}/export-xml", headers=h)
    assert xml.status_code == 200
    assert "PaymentInstructions" in xml.text
    assert batch["batch_number"] in xml.text

    approved = client.post(f"/api/v1/payments/batches/{batch['id']}/approve", headers=h)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "completed"
    inv1_now = client.get(f"/api/v1/invoices/{inv1['id']}", headers=h).json()
    assert inv1_now["status"] == "paid"
    assert inv1_now["paid_amount"] == 3000.0

    # 已完成批次不可重复审批
    again = client.post(f"/api/v1/payments/batches/{batch['id']}/approve", headers=h)
    assert again.status_code == 409

    reversed_row = client.post(f"/api/v1/payments/batches/{batch['id']}/reverse", headers=h)
    assert reversed_row.status_code == 200, reversed_row.text
    assert reversed_row.json()["status"] == "reversed"
    inv1_back = client.get(f"/api/v1/invoices/{inv1['id']}", headers=h).json()
    assert inv1_back["status"] == "issued"
    assert inv1_back["paid_amount"] == 0.0


def test_payment_batch_validation(client, auth_headers):
    h = auth_headers
    draft = _create_invoice(client, h, amount=100)  # not issued
    r = client.post("/api/v1/payments/batches", headers=h, json={"invoice_ids": [draft["id"]]})
    assert r.status_code == 409

    inv = _create_invoice(client, h, amount=100)
    _issue(client, h, inv["id"])
    r = client.post(
        "/api/v1/payments/batches",
        headers=h,
        json={"invoice_ids": [inv["id"]], "bank_charge_mode": "weird"},
    )
    assert r.status_code == 422


# —— 4. 付款条件 / 方式 / 银行账户 ————————————————————————————


def test_payment_terms_methods_banks_crud(client, auth_headers):
    h = auth_headers
    term = client.post(
        "/api/v1/payments/terms",
        headers=h,
        json={"name": "Net 30", "days": 30, "discount_pct": 1.5, "discount_days": 10},
    )
    assert term.status_code == 200, term.text
    term_id = term.json()["id"]
    assert term.json()["days"] == 30

    terms = client.get("/api/v1/payments/terms", headers=h).json()
    assert any(t["id"] == term_id for t in terms)

    patched = client.patch(
        f"/api/v1/payments/terms/{term_id}", headers=h, json={"name": "Net 45", "days": 45}
    )
    assert patched.status_code == 200
    assert patched.json()["days"] == 45

    method = client.post("/api/v1/payments/methods", headers=h, json={"name": "T/T", "code": "TT"})
    assert method.status_code == 200, method.text
    method_id = method.json()["id"]
    methods = client.get("/api/v1/payments/methods", headers=h).json()
    assert any(m["code"] == "TT" for m in methods)
    patched = client.patch(
        f"/api/v1/payments/methods/{method_id}", headers=h, json={"name": "T/T", "code": "TT", "is_active": False}
    )
    assert patched.json()["is_active"] is False

    cp = _first_counterparty(client, h)
    bank = client.post(
        "/api/v1/payments/bank-accounts",
        headers=h,
        json={
            "bank_name": "HSBC",
            "account_name": "MariOS Demo",
            "account_number": "12345678",
            "swift_code": "HSBCHKHH",
            "currency": "USD",
            "is_default": True,
            "counterparty_id": cp,
        },
    )
    assert bank.status_code == 200, bank.text
    banks = client.get("/api/v1/payments/bank-accounts", headers=h).json()
    assert any(b["bank_name"] == "HSBC" for b in banks)

    assert client.delete(f"/api/v1/payments/terms/{term_id}", headers=h).status_code == 200
    assert client.delete(f"/api/v1/payments/methods/{method_id}", headers=h).status_code == 200
    assert client.delete(f"/api/v1/payments/bank-accounts/{bank.json()['id']}", headers=h).status_code == 200
    assert all(t["id"] != term_id for t in client.get("/api/v1/payments/terms", headers=h).json())


# —— 5. 预收/预付核销 ——————————————————————————————————————————


def test_advance_payment_allocation(client, auth_headers):
    h = auth_headers
    inv = _create_invoice(client, h, amount=1000)
    _issue(client, h, inv["id"])

    adv = client.post(
        "/api/v1/payments/advances",
        headers=h,
        json={"direction": "receipt", "amount": 800, "currency": "USD", "notes": "pre-freight"},
    )
    assert adv.status_code == 200, adv.text
    adv_id = adv.json()["id"]
    assert adv.json()["advance_no"].startswith("AR-")
    assert adv.json()["status"] == "unallocated"

    r = client.post(
        f"/api/v1/payments/advances/{adv_id}/allocate",
        headers=h,
        json={"invoice_id": inv["id"], "amount": 500},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "partially_allocated"
    assert r.json()["allocated_amount"] == 500.0

    over = client.post(
        f"/api/v1/payments/advances/{adv_id}/allocate",
        headers=h,
        json={"invoice_id": inv["id"], "amount": 400},
    )
    assert over.status_code == 409
    assert over.json()["detail"]["code"] == "OVER_ALLOCATION"

    r = client.post(
        f"/api/v1/payments/advances/{adv_id}/allocate",
        headers=h,
        json={"invoice_id": inv["id"], "amount": 300},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "fully_allocated"
    assert r.json()["allocated_amount"] == 800.0
    assert len(r.json()["allocations"]) == 2

    detail = client.get(f"/api/v1/payments/advances/{adv_id}", headers=h).json()
    assert detail["status"] == "fully_allocated"
    assert sum(a["amount"] for a in detail["allocations"]) == 800.0


# —— 6. GL 科目 / 分录 CRUD + 过账 / 冲销 ————————————————————————


def test_gl_account_and_journal_crud(client, auth_headers):
    h = auth_headers
    cash = _mk_account(client, h, "1000", "Cash", "asset")
    revenue = _mk_account(client, h, "4000", "Freight revenue", "revenue")

    dup = client.post(
        "/api/v1/gl/accounts",
        headers=h,
        json={"account_code": "1000", "account_name": "Cash 2", "account_type": "asset"},
    )
    assert dup.status_code == 409

    group = client.post(
        "/api/v1/gl/account-groups",
        headers=h,
        json={"group_code": "CUR", "group_name": "Current assets", "account_type": "asset"},
    )
    assert group.status_code == 200, group.text
    assert any(g["group_code"] == "CUR" for g in client.get("/api/v1/gl/account-groups", headers=h).json())

    period = client.post("/api/v1/gl/periods", headers=h, json={"period": "2026-09", "status": "open"})
    assert period.status_code == 200, period.text
    assert client.post("/api/v1/gl/periods", headers=h, json={"period": "2026-09"}).status_code == 409

    journal = _mk_journal(
        client,
        h,
        [
            {"account_code": "1000", "debit": 1000, "credit": 0, "reference": "J1"},
            {"account_code": "4000", "debit": 0, "credit": 1000, "reference": "J1"},
        ],
    )
    assert journal["status"] == "draft"

    unbalanced = client.post(
        "/api/v1/gl/journals",
        headers=h,
        json={
            "period": "2026-09",
            "journal_type": "non_voyage",
            "entries": [{"account_code": "1000", "debit": 5, "credit": 0}],
        },
    )
    assert unbalanced.status_code == 422

    posted = client.post(f"/api/v1/gl/journals/{journal['id']}/post", headers=h)
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "posted"
    assert client.post(f"/api/v1/gl/journals/{journal['id']}/post", headers=h).status_code == 409

    rev = client.post(f"/api/v1/gl/journals/{journal['id']}/reverse", headers=h)
    assert rev.status_code == 200, rev.text
    assert rev.json()["original"]["status"] == "reversed"
    reversal = rev.json()["reversal"]
    assert reversal["status"] == "posted"
    assert float(reversal["entries"][0]["debit"]) == 0.0  # 借贷对调
    assert float(reversal["entries"][0]["credit"]) == 1000.0

    # 科目可删（清理）
    assert client.delete(f"/api/v1/gl/accounts/{cash['id']}", headers=h).status_code == 200
    assert client.delete(f"/api/v1/gl/accounts/{revenue['id']}", headers=h).status_code == 200
    accounts = client.get("/api/v1/gl/accounts", headers=h).json()
    assert all(a["account_code"] not in ("1000", "4000") for a in accounts["items"])


# —— 6b. TC 租金计提分录暴露（allocate_period_journal → /gl/journals/allocate-tc-hire） ——


def test_allocate_tc_hire_endpoint(client, auth_headers):
    h = auth_headers
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    parties = parties["items"] if isinstance(parties, dict) else parties
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    vessels = vessels["items"] if isinstance(vessels, dict) else vessels
    charter = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "tct", "counterparty_id": parties[0]["id"], "hire_per_day": 12000},
    ).json()
    tc = client.post(
        "/api/v1/tc/contracts",
        headers=h,
        json={
            "charter_id": charter["id"],
            "contract_type": "tci",
            "contract_style": "time_charter",
            "vessel_id": vessels[0]["id"],
            "counterparty_id": parties[0]["id"],
            "hire_rate": 10000,
            "delivery_date": "2026-01-01",
            "redelivery_date": "2026-03-01",
        },
    )
    assert tc.status_code == 201, tc.text

    r = client.post(
        "/api/v1/gl/journals/allocate-tc-hire",
        headers=h,
        params={"tc_contract_id": tc.json()["id"], "period_start": "2026-01-01", "period_end": "2026-01-31"},
    )
    assert r.status_code == 200, r.text
    journal = r.json()
    assert journal["status"] in ("posted", "draft")
    assert journal["total_debit"] == journal["total_credit"]
    # 幂等：同合约同期间再调返回同一分录
    again = client.post(
        "/api/v1/gl/journals/allocate-tc-hire",
        headers=h,
        params={"tc_contract_id": tc.json()["id"], "period_start": "2026-01-01", "period_end": "2026-01-31"},
    ).json()
    assert again["id"] == journal["id"]


# —— 7/8. 三大报表：A = L + E、利润表、现金流量表 ——————————————————


def test_financial_statements(client, auth_headers):
    h = auth_headers
    _mk_account(client, h, "1010", "Bank", "asset")
    _mk_account(client, h, "2000", "Accounts payable", "liability")
    _mk_account(client, h, "3000", "Owner equity", "equity")
    _mk_account(client, h, "4000", "Freight revenue", "revenue")
    _mk_account(client, h, "5000", "Voyage expense", "expense")

    # 资本 + 收入 + 负债：借银行 1500 = 贷权益 500 + 收入 800 + 负债 200
    _mk_journal(
        client,
        h,
        [
            {"account_code": "1010", "debit": 1500, "credit": 0, "reference": "S1"},
            {"account_code": "3000", "debit": 0, "credit": 500, "reference": "S1"},
            {"account_code": "4000", "debit": 0, "credit": 800, "reference": "S1"},
            {"account_code": "2000", "debit": 0, "credit": 200, "reference": "S1"},
        ],
    )
    posted1 = client.get("/api/v1/gl/journals", headers=h).json()["items"][0]["id"]
    assert client.post(f"/api/v1/gl/journals/{posted1}/post", headers=h).status_code == 200

    # 费用 300：借费用 = 贷银行
    _mk_journal(
        client,
        h,
        [
            {"account_code": "5000", "debit": 300, "credit": 0, "reference": "S2"},
            {"account_code": "1010", "debit": 0, "credit": 300, "reference": "S2"},
        ],
    )
    journals = client.get("/api/v1/gl/journals", headers=h).json()["items"]
    draft2 = next(j for j in journals if j["status"] == "draft")
    assert client.post(f"/api/v1/gl/journals/{draft2['id']}/post", headers=h).status_code == 200

    # 利润表：800 − 300 = 500
    pnl = client.get("/api/v1/gl/income-statement", params={"period": "2026-09"}, headers=h).json()
    assert pnl["total_revenue"] == 800.0
    assert pnl["total_expenses"] == 300.0
    assert pnl["net_income"] == 500.0

    # 资产负债表：A 1200 = L 200 + E (500 + 本期损益 500)
    bs = client.get("/api/v1/gl/balance-sheet", params={"period": "2026-09"}, headers=h).json()
    assert bs["total_assets"] == 1200.0
    assert bs["total_liabilities"] == 200.0
    assert bs["total_equity"] == 1000.0
    assert bs["net_income"] == 500.0
    assert bs["balanced"] is True
    assert bs["total_assets"] == pytest.approx(bs["total_liabilities"] + bs["total_equity"])

    # 现金流量表：S1 对方科目含权益 → 筹资 +1500；S2 费用 → 经营 −300；净变动 +1200
    cf = client.get("/api/v1/gl/cashflow", params={"period": "2026-09"}, headers=h).json()
    assert cf["financing"] == pytest.approx(1500.0)
    assert cf["operating"] == pytest.approx(-300.0)
    assert cf["net_change_in_cash"] == pytest.approx(1200.0)
    assert cf["operating"] + cf["investing"] + cf["financing"] == pytest.approx(cf["net_change_in_cash"])
    assert cf["cash_ending"] == pytest.approx(cf["cash_beginning"] + cf["net_change_in_cash"])

    # 试算平衡
    tb = client.get("/api/v1/gl/trial-balance", params={"period": "2026-09"}, headers=h).json()
    assert tb["balanced"] is True
    assert tb["total_debit"] == pytest.approx(1800.0)
    assert tb["total_credit"] == pytest.approx(1800.0)
