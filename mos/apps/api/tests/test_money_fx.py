"""混币口径回归（P1-B10 / P1-B4 · 审计修复）。

把"钱跨币种"这件事锁成断言：

- **基准金额口径唯一**：``invoice_base_amount``（税前）与 ``invoice_base_gross``
  （含税）必须给出同一个本币数 —— 有/无汇率、有/无 ``base_amount`` 四种组合
  全锁死。以前税前口径漏了汇率，损益（P&L）与总账（GL）各算各的。
- **外币发票缺汇率 → fail closed**：claims→invoice / laytime→include-in-freight
  取不到汇率时必须 422（``FX_RATE_NOT_FOUND``），绝不按 1:1 记账。
- **外币信用限额**：先折本币再比；折不动就**不下结论**（``cannot_evaluate``，
  不给假 breach），并把原币/本币两个数都报出来。
- **滞期费预付款混币**：先折本币再冲抵 / 汇总；折不动的单列，不混进合计。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_finance_ext import RiskLimit
from app.models_wave1 import ExchangeRate
from app.services.money import (
    invoice_base_amount,
    invoice_base_gross,
    invoice_base_tax,
)

API = "/api/v1"

# 金样：滞期 1 天 × 24000 = 24000（与 tests/test_bunker_laytime_compliance.py 同源）
DEMURRAGE_INPUTS = {
    "allowed_hours": 24,
    "demurrage_rate_per_day": 24000,
    "terms": "SHINC",
    "events": [
        {"start": "2026-01-05T00:00:00", "end": "2026-01-06T00:00:00", "excluded": False},
        {"start": "2026-01-06T00:00:00", "end": "2026-01-07T00:00:00", "excluded": False},
    ],
}


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db_session) -> str:
    return db_session.query(Tenant.id).filter(Tenant.code == "demo").scalar()


def _add_rate(db_session, base: str, quote: str, rate: str) -> None:
    """登记一条 原币→本币 汇率（base_currency=原币，quote_currency=本币）。"""
    db_session.add(
        ExchangeRate(
            tenant_id=_tenant_id(db_session),
            base_currency=base,
            quote_currency=quote,
            rate=Decimal(rate),
            rate_date=date.today(),
            source="test",
        )
    )
    db_session.commit()


class _Inv:
    """最小发票替身（money.py 的 helper 只读这几个属性）。"""

    def __init__(self, amount, tax=0, fx_rate=None, base_amount=None):
        self.amount = Decimal(str(amount))
        self.tax_amount = Decimal(str(tax))
        self.paid_amount = Decimal("0")
        self.fx_rate = Decimal(str(fx_rate)) if fx_rate is not None else None
        self.base_amount = Decimal(str(base_amount)) if base_amount is not None else None


# —— P1-B10：基准金额口径唯一 ————————————————————————————————————


def test_base_amount_rule_without_fx_rate_is_unchanged():
    """单币种租户（无汇率、无 base_amount）→ 原币金额，历史行为不变。"""
    inv = _Inv(1000, tax=100)
    assert invoice_base_amount(inv) == Decimal("1000.00")
    assert invoice_base_tax(inv) == Decimal("100.00")
    assert invoice_base_gross(inv) == Decimal("1100.00")


def test_base_amount_rule_applies_fx_rate_when_no_base_amount():
    """有汇率、没有 base_amount → 按 金额 × 汇率 折本币（以前税前口径漏了这一步）。"""
    inv = _Inv(1000, tax=100, fx_rate="1.2")
    assert invoice_base_amount(inv) == Decimal("1200.00")
    assert invoice_base_tax(inv) == Decimal("120.00")
    assert invoice_base_gross(inv) == Decimal("1320.00")


def test_base_amount_rule_prefers_stored_base_amount():
    """存了 base_amount → 用它（税按汇率折算）。"""
    inv = _Inv(1000, tax=100, fx_rate="1.2", base_amount="1300")
    assert invoice_base_amount(inv) == Decimal("1300.00")
    assert invoice_base_gross(inv) == Decimal("1420.00")


@pytest.mark.parametrize(
    "amount,tax,fx_rate,base_amount",
    [
        ("1000", "100", None, None),
        ("1000", "100", "1.2", None),
        ("1000", "100", None, "1300"),
        ("1000", "100", "1.2", "1300"),
        ("0", "0", None, None),
        ("0.005", "0.005", "1.005", None),
    ],
)
def test_base_amount_and_gross_always_agree(amount, tax, fx_rate, base_amount):
    """税前口径与含税口径必须永远对得上：gross = 税前 + 税（同一个本币数）。"""
    inv = _Inv(amount, tax=tax, fx_rate=fx_rate, base_amount=base_amount)
    assert invoice_base_gross(inv) == invoice_base_amount(inv) + invoice_base_tax(inv)


# —— P1-B10：外币发票缺汇率 → fail closed ————————————————————————


def _claim(client, h, currency: str = "USD", amount: float = 8000) -> str:
    r = client.post(f"{API}/claims", headers=h, json={"amount": amount, "currency": currency})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert client.post(f"{API}/claims/{cid}/transition?target=negotiating", headers=h).status_code == 200
    return cid


def _laytime_with_demurrage(client, h) -> str:
    lt = client.post(f"{API}/laytimes", headers=h, json={"inputs": DEMURRAGE_INPUTS})
    assert lt.status_code == 200, lt.text
    lt_id = lt.json()["id"]
    calc = client.post(f"{API}/laytimes/{lt_id}/calculate", headers=h)
    assert calc.status_code == 200, calc.text
    assert calc.json()["results"]["result_type"] == "demurrage"
    return lt_id


def test_claim_to_invoice_rejects_foreign_currency_without_rate(client, auth_headers):
    """外币索赔单开票：取不到汇率 → 422，不许按 1:1 记账。"""
    h = auth_headers
    cid = _claim(client, h, currency="EUR")
    r = client.post(f"{API}/claims/{cid}/to-invoice", headers=h)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "FX_RATE_NOT_FOUND"
    assert detail["currency"] == "EUR"
    assert detail["base_currency"] == "USD"


def test_claim_to_invoice_carries_fx_rate_when_resolvable(client, auth_headers, db_session):
    """有汇率 → 发票带上 fx_rate / base_amount（本位币金额可核对）。"""
    _add_rate(db_session, "EUR", "USD", "1.2")
    h = auth_headers
    cid = _claim(client, h, currency="EUR")
    r = client.post(f"{API}/claims/{cid}/to-invoice", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "EUR"
    assert body["fx_rate"] == pytest.approx(1.2)
    assert body["base_amount"] == pytest.approx(9600.0)  # 8000 EUR × 1.2


def test_claim_to_invoice_base_currency_needs_no_rate(client, auth_headers):
    """本币索赔单照旧开票（本币不需要汇率行）。"""
    h = auth_headers
    cid = _claim(client, h, currency="USD")
    r = client.post(f"{API}/claims/{cid}/to-invoice", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "USD"
    assert body["fx_rate"] == pytest.approx(1.0)
    assert body["base_amount"] == pytest.approx(8000.0)


def test_include_in_freight_rejects_foreign_currency_without_rate(client, auth_headers):
    """滞期费并入运费发票：外币没有汇率 → 422。"""
    h = auth_headers
    lt_id = _laytime_with_demurrage(client, h)
    r = client.post(
        f"{API}/laytimes/{lt_id}/include-in-freight",
        headers=h,
        json={"freight_amount": 1000, "currency": "EUR"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "FX_RATE_NOT_FOUND"
    assert detail["currency"] == "EUR"


def test_include_in_freight_carries_fx_rate_when_resolvable(client, auth_headers, db_session):
    _add_rate(db_session, "EUR", "USD", "1.2")
    h = auth_headers
    lt_id = _laytime_with_demurrage(client, h)
    r = client.post(
        f"{API}/laytimes/{lt_id}/include-in-freight",
        headers=h,
        json={"freight_amount": 1000, "currency": "EUR"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "EUR"
    assert body["fx_rate"] == pytest.approx(1.2)
    # 滞期费结算额 24,000 是本币（USD）→ 折成发票币种 20,000 EUR，再与运费相加
    assert body["settlement_amount_base"] == pytest.approx(24000.0)
    assert body["settlement_amount"] == pytest.approx(20000.0)
    assert body["amount"] == pytest.approx(21000.0)  # 运费 1,000 + 滞期费 20,000 EUR
    assert body["base_amount"] == pytest.approx(25200.0)  # 21,000 EUR × 1.2


# —— P1-B4：信用限额混币 ——————————————————————————————————————


def _party_id(client, h) -> str:
    rows = client.get(f"{API}/masterdata/counterparties", headers=h).json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    return rows[0]["id"]


def _issue_invoice(client, h, party_id: str, amount: float) -> None:
    inv = client.post(f"{API}/invoices", headers=h, json={"amount": amount, "counterparty_id": party_id}).json()
    assert client.post(f"{API}/invoices/{inv['id']}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"{API}/invoices/{inv['id']}/transition?target=issued", headers=h).status_code == 200


def _add_limit(db_session, party_id: str, amount: int, currency: str) -> None:
    db_session.add(
        RiskLimit(
            tenant_id=_tenant_id(db_session),
            scope=f"counterparty:{party_id}",
            limit_type="credit",
            amount=amount,
            currency=currency,
        )
    )
    db_session.commit()


def test_foreign_credit_limit_without_rate_reports_no_breach(client, auth_headers, db_session):
    """外币限额没有汇率 → **无法评估**，不给 breach（旧的"假 breach"）。

    敞口 9,000 USD vs 限额 8,000 EUR：直接比数字会得出"超限"，
    但两者币种不同，那个结论毫无意义。
    """
    h = auth_headers
    pid = _party_id(client, h)
    _issue_invoice(client, h, pid, 4500)
    _issue_invoice(client, h, pid, 4500)
    _add_limit(db_session, pid, 8000, "EUR")

    body = client.get(f"{API}/masterdata/counterparties/{pid}/credit-exposure", headers=h).json()
    assert body["open_exposure"] == 9000.0
    assert body["open_exposure_currency"] == "USD"
    assert body["comparison_status"] == "cannot_evaluate"
    assert body["breach"] is False
    assert body["credit_limit"] is None
    assert body["credit_limit_original"] == 8000.0
    assert body["credit_limit_original_currency"] == "EUR"
    assert body["utilization_pct"] is None


def test_foreign_credit_limit_is_converted_before_comparison(client, auth_headers, db_session):
    """外币限额先折本币再比：8,000 EUR × 1.2 = 9,600 USD > 敞口 9,000 → 不超限。"""
    _add_rate(db_session, "EUR", "USD", "1.2")
    h = auth_headers
    pid = _party_id(client, h)
    _issue_invoice(client, h, pid, 4500)
    _issue_invoice(client, h, pid, 4500)
    _add_limit(db_session, pid, 8000, "EUR")

    body = client.get(f"{API}/masterdata/counterparties/{pid}/credit-exposure", headers=h).json()
    assert body["open_exposure"] == 9000.0
    assert body["comparison_status"] == "converted"
    assert body["credit_limit"] == pytest.approx(9600.0)
    assert body["credit_limit_currency"] == "USD"
    assert body["credit_limit_original"] == 8000.0
    assert body["credit_limit_original_currency"] == "EUR"
    # 折算后 9,000 < 9,600 —— 旧实现会误报 breach
    assert body["breach"] is False
    assert body["utilization_pct"] == pytest.approx(93.8)


def test_same_currency_credit_limit_unchanged(client, auth_headers, db_session):
    """本币限额口径不变（老行为回归）。"""
    h = auth_headers
    pid = _party_id(client, h)
    _issue_invoice(client, h, pid, 300)
    _issue_invoice(client, h, pid, 200)
    _add_limit(db_session, pid, 400, "USD")

    body = client.get(f"{API}/masterdata/counterparties/{pid}/credit-exposure", headers=h).json()
    assert body["open_exposure"] == 500.0
    assert body["credit_limit"] == 400.0
    assert body["credit_limit_currency"] == "USD"
    assert body["comparison_status"] == "ok"
    assert body["breach"] is True
    assert body["utilization_pct"] == pytest.approx(125.0)


# —— P1-B4：滞期费预付款混币 ——————————————————————————————————


def _on_account(client, h, lt_id: str, amount: float, currency: str, status: str = "paid") -> None:
    r = client.post(
        f"{API}/laytimes/{lt_id}/demurrage-on-account",
        headers=h,
        json={"amount": amount, "currency": currency, "status": status},
    )
    assert r.status_code == 200, r.text


def test_laytime_on_account_sums_are_converted_to_base(client, auth_headers, db_session):
    """预付款混币：先折本币再汇总/冲抵（USD 1,000 + EUR 500×1.2 = 1,600 USD）。"""
    _add_rate(db_session, "EUR", "USD", "1.2")
    h = auth_headers
    lt_id = _laytime_with_demurrage(client, h)
    _on_account(client, h, lt_id, 1000, "USD")
    _on_account(client, h, lt_id, 500, "EUR")

    listing = client.get(f"{API}/laytimes/{lt_id}/demurrage-on-account", headers=h).json()
    assert listing["on_account_paid"] == pytest.approx(1600.0)
    assert listing["on_account_paid_currency"] == "USD"
    assert listing["on_account_paid_status"] == "ok"
    assert listing["on_account_paid_by_currency"]["USD"] == pytest.approx(1000.0)
    assert listing["on_account_paid_by_currency"]["EUR"] == pytest.approx(500.0)

    est = client.get(f"{API}/laytimes/{lt_id}/estimated-demurrage", headers=h).json()
    assert est["demurrage_amount"] == pytest.approx(24000.0)
    assert est["on_account_total"] == pytest.approx(1600.0)
    assert est["outstanding"] == pytest.approx(22400.0)
    assert est["currency"] == "USD"


def test_laytime_on_account_without_rate_is_not_silently_summed(client, auth_headers):
    """折不动的币种不进合计，也不参与冲抵 —— 宁可少算也不能假"已结清"。"""
    h = auth_headers
    lt_id = _laytime_with_demurrage(client, h)
    _on_account(client, h, lt_id, 1000, "USD")
    _on_account(client, h, lt_id, 500, "JPY")

    listing = client.get(f"{API}/laytimes/{lt_id}/demurrage-on-account", headers=h).json()
    assert listing["on_account_paid"] is None
    assert listing["on_account_paid_status"] == "cannot_evaluate"
    assert listing["on_account_paid_unconverted"]["JPY"] == pytest.approx(500.0)

    est = client.get(f"{API}/laytimes/{lt_id}/estimated-demurrage", headers=h).json()
    assert est["on_account_total"] == pytest.approx(1000.0)  # 只冲抵折得出的 USD 那笔
    assert est["outstanding"] == pytest.approx(23000.0)
    assert est["on_account_status"] == "partial"
    assert est["on_account_unconverted"]["JPY"] == pytest.approx(500.0)
