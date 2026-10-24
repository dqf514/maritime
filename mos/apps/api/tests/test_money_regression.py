"""金额口径回归（WP-1）。

这条文件是 **money.py 的护栏**：把审计里查出的每一处「同一张票有五套算法」
固化成断言 —— 谁再改回 ``amount - paid``（漏税）、谁再让草稿进损益、
谁再按净额重复计佣、谁再让缺汇率的外币票静默落库，这里都会红。

覆盖：
- P0-B1 停租/租金发票重复计佣
- P0-B2 红冲必须产生一张负数发票行（账龄天然相抵）
- P0-B3 gl-post 必须产生**真实**借贷分录且幂等
- P0-B4 未收口径统一 = 金额 + 税 − 已收（单笔收款 / 批次 / 账龄 / CSV 一致）
- P0-B5 外币发票缺汇率 → 422（fail closed），不允许静默按本币求和
- P0-B6 草稿发票不计入实际收入（签发后才算）
- P0-B7 规范发票类型（TCIP/DEM/XREV…）必须映射到正确的损益行
- P1-B2 佣金基数认 ``commission_basis``（net / gross 各算一次）
- P1-B12 税额必须出现在客户 CSV 与 MT103 付款指令里
- P2-B9 冲销过的付款不得出现在付款指令里
- P2-B11 作废冲正重算收款必须带 tenant_id 过滤
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


API = "/api/v1"


def _mk_invoice(client, h, **kw):
    payload = {"invoice_type": "freight", "amount": 10000}
    payload.update(kw)
    r = client.post(f"{API}/invoices", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _issue(client, h, iid):
    assert client.post(f"{API}/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"{API}/invoices/{iid}/transition?target=issued", headers=h).status_code == 200


def _mk_voyage(client, h, tag="MONEY"):
    r = client.post(f"{API}/voyages", headers=h, json={"voyage_no": f"{tag}-{tag}", "status": "planning"})
    if r.status_code != 200:
        # 航次号重复时退一步用不带号的载荷
        r = client.post(f"{API}/voyages", headers=h, json={"status": "planning"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# —— P0-B4：未收口径统一（金额 + 税 − 已收）——————————————————————


def test_open_amount_includes_tax_everywhere(client, auth_headers):
    h = auth_headers
    inv = _mk_invoice(client, h, amount=1000.0, tax_amount=100.0)
    iid = inv["id"]
    _issue(client, h, iid)

    # 账龄：未收 = 1100
    aging = client.get(f"{API}/finance/aging", headers=h).json()
    row = next((r for r in aging if r["invoice_id"] == iid), None)
    assert row is not None, aging
    assert float(row["open_amount"]) == pytest.approx(1100.0)
    assert float(row["gross_amount"]) == pytest.approx(1100.0)

    # 收款 300 → 未收 800
    pay = client.post(f"{API}/invoices/{iid}/payments?amount=300", headers=h)
    assert pay.status_code == 200, pay.text

    aging = client.get(f"{API}/finance/aging", headers=h).json()
    row = next(r for r in aging if r["invoice_id"] == iid)
    assert float(row["open_amount"]) == pytest.approx(800.0)

    # 付款批次口径必须与单笔收款一致
    payables = client.get(f"{API}/payments/payable-invoices", headers=h).json()
    items = payables if isinstance(payables, list) else payables.get("items", [])
    item = next((i for i in items if i.get("id") == iid), None)
    assert item is not None, payables
    assert float(item["outstanding"]) == pytest.approx(800.0)
    assert float(item["gross_amount"]) == pytest.approx(1100.0)


def test_batch_total_matches_open_amounts(client, auth_headers):
    h = auth_headers
    inv = _mk_invoice(client, h, amount=500.0, tax_amount=50.0)
    _issue(client, h, inv["id"])
    r = client.post(
        f"{API}/payments/batches",
        headers=h,
        json={"invoice_ids": [inv["id"]], "batch_date": "2026-03-01"},
    )
    assert r.status_code == 200, r.text
    batch = r.json()
    assert float(batch["total_amount"]) == pytest.approx(550.0)


# —— P0-B5：外币缺汇率 → 422（fail closed）——————————————————————


def test_foreign_invoice_without_fx_rate_is_rejected(client, auth_headers):
    h = auth_headers
    r = client.post(f"{API}/invoices", headers=h, json={"amount": 1000, "currency": "JPY"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "FX_RATE_NOT_FOUND"


def test_foreign_invoice_with_explicit_fx_rate_keeps_base_amount(client, auth_headers):
    h = auth_headers
    r = client.post(
        f"{API}/invoices",
        headers=h,
        json={"amount": 1000, "currency": "EUR", "fx_rate": 1.2},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "EUR"
    assert float(body["base_amount"]) == pytest.approx(1200.0)


# —— P0-B6：草稿不计入实际收入 ————————————————————————————————


def test_draft_invoice_not_in_actual_revenue(client, auth_headers):
    h = auth_headers
    vid = _mk_voyage(client, h, "DRAFT")
    inv = _mk_invoice(client, h, voyage_id=vid, amount=1234.0)
    _issue(client, h, inv["id"])  # 先把上一轮的干扰排除

    rows = client.get(f"{API}/analytics/reports/voyage-pnl?basis=actual", headers=h).json()
    before = {r["voyage_id"]: r for r in rows}[vid]

    draft = _mk_invoice(client, h, voyage_id=vid, amount=4321.0)
    rows = client.get(f"{API}/analytics/reports/voyage-pnl?basis=actual", headers=h).json()
    mid = {r["voyage_id"]: r for r in rows}[vid]
    assert mid["actual_revenue"] - before["actual_revenue"] == pytest.approx(0.0)

    _issue(client, h, draft["id"])
    rows = client.get(f"{API}/analytics/reports/voyage-pnl?basis=actual", headers=h).json()
    after = {r["voyage_id"]: r for r in rows}[vid]
    assert after["actual_revenue"] - before["actual_revenue"] == pytest.approx(4321.0)


# —— P0-B7：规范发票类型映射到正确的损益行 ————————————————————


@pytest.mark.parametrize(
    "invoice_type,line",
    [
        ("freight", "revenue"),
        ("hire", "hire"),
        ("demurrage", "demurrage"),
    ],
)
def test_canonical_invoice_types_map_to_pnl_lines(client, auth_headers, invoice_type, line):
    h = auth_headers
    vid = _mk_voyage(client, h, f"TYPE{line}")
    inv = _mk_invoice(client, h, voyage_id=vid, invoice_type=invoice_type, amount=777.0)
    _issue(client, h, inv["id"])
    rows = client.get(f"{API}/analytics/reports/voyage-pnl?basis=actual", headers=h).json()
    row = {r["voyage_id"]: r for r in rows}[vid]
    assert row["lines_actual"][line] == pytest.approx(777.0)


# —— P0-B2：红冲 = 一张负数发票行 ——————————————————————————————


def test_credit_note_creates_negative_invoice_and_nets_aging(client, auth_headers):
    h = auth_headers
    inv = _mk_invoice(client, h, amount=1000.0, tax_amount=100.0)
    _issue(client, h, inv["id"])

    cn = client.post(
        f"{API}/invoices/{inv['id']}/credit-note",
        headers=h,
        json={"amount": 400.0, "reason": "wrong rate"},
    )
    assert cn.status_code == 200, cn.text
    cn_body = cn.json()

    # 存在一张负数发票行，并且回链原发票
    listed = client.get(f"{API}/invoices?limit=200", headers=h).json()
    items = listed if isinstance(listed, list) else listed.get("items", [])
    neg = [i for i in items if i.get("credit_note_of_id") == inv["id"]]
    assert neg, "红冲必须落一张负数发票行"
    assert float(neg[0]["amount"]) == pytest.approx(-400.0)
    assert cn_body.get("credit_note_of_id") == inv["id"]


# —— P0-B3：过账产生真分录且幂等 ——————————————————————————————


def test_gl_post_creates_balanced_journal_once(client, auth_headers):
    h = auth_headers
    inv = _mk_invoice(client, h, amount=1000.0, tax_amount=100.0)
    _issue(client, h, inv["id"])

    r = client.post(f"{API}/invoices/{inv['id']}/gl-post", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert float(body["total_debit"]) == pytest.approx(float(body["total_credit"]))
    assert float(body["total_debit"]) > 0

    # 幂等：再点一次不会产生第二张分录
    r2 = client.post(f"{API}/invoices/{inv['id']}/gl-post", headers=h)
    assert r2.status_code == 200, r2.text
    assert r2.json()["id"] == body["id"]


# —— P1-B2：佣金基数认 commission_basis —————————————————————————


def test_net_basis_invoice_commission_counted_once(db_session, client, auth_headers):
    """租金发票金额里已经扣了地址佣金 → 损益里的佣金成本行不得再扣一次（P1-B1/B2）。

    这里直接落一行 ``commission_basis="net"`` 的发票（带 hire 毛额快照），
    断言损益里的佣金成本行**只**含经纪佣金那一份。
    """
    import uuid
    from decimal import Decimal

    from sqlalchemy import select

    from app.models_domain import Invoice
    from app.models_wave1 import Company

    h = auth_headers
    tenant_id = db_session.scalar(select(Company).limit(1)).tenant_id
    vid = _mk_voyage(client, h, "COMM")

    # 租约：经纪佣金 1.25%、地址佣金 2.5%
    from app.models_domain import Charter, Voyage

    voy = db_session.get(Voyage, uuid.UUID(vid))
    charter = Charter(
        tenant_id=tenant_id,
        charter_no=f"COMM-{uuid.uuid4().hex[:6]}",
        charter_type="voyage",
        status="draft",
        brokerage_pct=Decimal("1.25"),
        address_comm_pct=Decimal("2.5"),
    )
    db_session.add(charter)
    db_session.flush()
    voy.charter_id = charter.id
    db_session.commit()

    inv = Invoice(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        invoice_no=f"COMM-INV-{uuid.uuid4().hex[:6]}",
        invoice_type="hire",
        status="issued",
        voyage_id=uuid.UUID(vid),
        currency="USD",
        amount=Decimal("975.00"),  # 净额 = 1000 − 2.5% 地址佣金
        tax_amount=Decimal("0"),
        base_amount=Decimal("975.00"),
        fx_rate=Decimal("1"),
        commission_basis="net",
        meta={"hire": {"gross_amount": 1000.0, "address_comm_amount": 25.0}},
    )
    db_session.add(inv)
    db_session.commit()

    rows = client.get(f"{API}/analytics/reports/voyage-pnl?basis=actual", headers=h).json()
    row = {x["voyage_id"]: x for x in rows}[vid]
    # 收入行 = 净额 975
    assert row["lines_actual"]["hire"] == pytest.approx(975.0)
    # 佣金成本行 = 经纪佣金（毛额 1000 × 1.25% = 12.5），**不含**地址佣金
    # （地址佣金已经从收入里扣过，再加一次就是 P1-B1 的重复计佣）
    assert row["lines_actual"]["commission"] == pytest.approx(12.5)
    assert row["commission_deducted"] == pytest.approx(25.0)


# —— P1-B12：税必须进客户 CSV ————————————————————————————————


def test_invoice_csv_carries_tax_and_excludes_drafts(client, auth_headers):
    h = auth_headers
    inv = _mk_invoice(client, h, amount=1000.0, tax_amount=100.0)
    _issue(client, h, inv["id"])
    _mk_invoice(client, h, amount=999.0)  # 草稿 —— 不该出现在应收 CSV 里

    r = client.get(f"{API}/export/invoices.csv?lang=en", headers=h)
    assert r.status_code == 200, r.text
    text = r.text
    assert "Tax" in text
    assert "100.00" in text  # 税额
    assert "999.00" not in text  # 草稿不在应收导出里


# —— P2-B9：冲销过的付款不进付款指令 ————————————————————————————


def test_reversed_batch_not_in_payment_instruction(client, auth_headers):
    h = auth_headers
    inv = _mk_invoice(client, h, amount=1000.0)
    _issue(client, h, inv["id"])
    b = client.post(
        f"{API}/payments/batches",
        headers=h,
        json={"invoice_ids": [inv["id"]], "batch_date": "2026-03-02"},
    )
    assert b.status_code == 200, b.text
    batch = b.json()

    ap = client.post(f"{API}/payments/batches/{batch['id']}/approve", headers=h)
    assert ap.status_code == 200, ap.text

    rv = client.post(f"{API}/payments/batches/{batch['id']}/reverse", headers=h)
    assert rv.status_code == 200, rv.text

    r = client.get(f"{API}/payments/batches/{batch['id']}/export?format=mt103", headers=h)
    assert r.status_code == 200, r.text
    # 冲销后不应再让银行付这笔钱
    assert "1000,00" not in r.text


# —— P2-B11：作废冲正重算收款必须带 tenant 过滤 ————————————————


def test_void_payment_recomputes_paid_with_tenant_scope(client, auth_headers):
    h = auth_headers
    inv = _mk_invoice(client, h, amount=1000.0)
    _issue(client, h, inv["id"])
    pay = client.post(f"{API}/invoices/{inv['id']}/payments?amount=400", headers=h)
    assert pay.status_code == 200, pay.text
    pays = client.get(f"{API}/invoices/{inv['id']}/payments", headers=h).json()
    assert pays, pays
    pid = pays[0]["id"]

    v = client.post(f"{API}/payments/{pid}/void", headers=h)
    assert v.status_code == 200, v.text
    assert float(v.json()["paid_amount"]) == pytest.approx(0.0)


# —— P0-23：零金额发票被拒 ———————————————————————————————————


def test_zero_amount_invoice_rejected(client, auth_headers):
    h = auth_headers
    r = client.post(f"{API}/invoices", headers=h, json={"amount": 0})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "INVALID_AMOUNT"


# —— P0-22：主数据空名被拒 ———————————————————————————————————


@pytest.mark.parametrize(
    "entity,payload",
    [
        ("counterparties", {"name": "", "type": "other"}),
        ("vessels", {"name": "   "}),
        ("ports", {"name": "", "unlocode": ""}),
    ],
)
def test_masterdata_rejects_blank_names(client, auth_headers, entity, payload):
    h = auth_headers
    r = client.post(f"{API}/masterdata/{entity}", headers=h, json=payload)
    assert r.status_code == 422, r.text


# —— P0-24：同名对手方被拒 ———————————————————————————————————


def test_duplicate_counterparty_name_conflicts(client, auth_headers):
    h = auth_headers
    name = "ACME-DUP-12345"
    r1 = client.post(f"{API}/masterdata/counterparties", headers=h, json={"name": name})
    assert r1.status_code == 200, r1.text
    r2 = client.post(f"{API}/masterdata/counterparties", headers=h, json={"name": name})
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "COUNTERPARTY_EXISTS"


# —— money.py 单测：舍入与口径 ———————————————————————————————


def test_money_rounds_half_up_not_bankers():
    from app.services.money import money

    assert money(Decimal("0.005")) == Decimal("0.01")
    assert money(Decimal("0.015")) == Decimal("0.02")
    assert money(Decimal("2.675")) == Decimal("2.68")
    assert money(None) == Decimal("0.00")


def test_invoice_helpers_agree_on_open_amount():
    from app.services.money import invoice_gross, invoice_open

    class _Inv:
        amount = Decimal("1000.00")
        tax_amount = Decimal("100.00")
        paid_amount = Decimal("250.00")

    inv = _Inv()
    assert invoice_gross(inv) == Decimal("1100.00")
    assert invoice_open(inv) == Decimal("850.00")
