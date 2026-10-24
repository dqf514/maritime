"""P2-B6 · 加油模块币种字段 + 金额精度。

以前 ``BunkerOption`` / ``BunkerInquiry`` / ``BunkerCapCollar`` 三张表都**没有币种列**
—— 450 USD 的报价和 450 EUR 的报价在库里长得一模一样；报价总额还在路由里用
``float(qty) * float(price)`` 算（带二进制尾数）。

本文件锁死三件事：

1. 三个单据都记录并回读币种；
2. 请求不带币种时回落到**租户本位币**（公司档案 ``base_currency``），非法码 422；
3. 报价总额由 ``Decimal`` + 显式 ``ROUND_HALF_UP`` 得出（最多 2 位小数，无 float 尾数）。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_domain import BunkerCapCollar, BunkerOption
from app.models_finance_ext import BunkerInquiry
from app.models_wave1 import Company


@pytest.fixture()
def open_db(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)


def _demo_tenant_id(db_engine) -> "UUID":
    db = sessionmaker(bind=db_engine)()
    try:
        row = db.query(Tenant).filter(Tenant.code == "demo").first()
        assert row is not None, "demo tenant missing"
        return row.id
    finally:
        db.close()


def _set_base_currency(db_engine, currency: str) -> list[str]:
    """把 demo 租户下**所有**公司档案的本位币改成 currency，返回原值列表。"""
    tid = _demo_tenant_id(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        rows = db.query(Company).filter(Company.tenant_id == tid).all()
        prev = [r.base_currency for r in rows]
        for r in rows:
            r.base_currency = currency
        db.commit()
        return prev
    finally:
        db.close()


def _restore_base_currency(db_engine, prev: list[str]) -> None:
    tid = _demo_tenant_id(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        rows = db.query(Company).filter(Company.tenant_id == tid).all()
        for r, old in zip(rows, prev):
            r.base_currency = old
        db.commit()
    finally:
        db.close()


def _master_ids(client, h) -> tuple[str, str, str]:
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    ports = client.get("/api/v1/masterdata/ports", headers=h).json()
    assert vessels and parties and ports
    return vessels[0]["id"], parties[0]["id"], ports[0]["id"]


def _make_requirement(client, h, qty=500) -> str:
    vessel_id, _party_id, port_id = _master_ids(client, h)
    r = client.post(
        "/api/v1/bunker/requirements",
        headers=h,
        json={"vessel_id": vessel_id, "fuel_type": "VLSFO", "qty_required": qty, "port_id": port_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── 1. BunkerOption ────────────────────────────────────────────────────


def test_bunker_option_records_and_returns_currency(client, auth_headers, open_db):
    h = auth_headers
    vessel_id, party_id, port_id = _master_ids(client, h)
    rid = _make_requirement(client, h)

    r = client.post(
        "/api/v1/bunker/options",
        headers=h,
        json={
            "requirement_id": rid,
            "supplier_id": party_id,
            "port_id": port_id,
            "qty": 100,
            "price_per_mt": 450,
            "currency": "EUR",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "EUR"

    # 落库也是 EUR（不只是响应里回显）
    db = open_db()
    try:
        row = db.get(BunkerOption, UUID(body["id"]))
        assert row is not None
        assert row.currency == "EUR"
    finally:
        db.close()

    # 列表口径一致
    listing = client.get(f"/api/v1/bunker/options?requirement_id={rid}", headers=h).json()
    item = next(i for i in listing["items"] if i["id"] == body["id"])
    assert item["currency"] == "EUR"

    # PATCH 也能改币种
    patched = client.patch(f"/api/v1/bunker/options/{body['id']}", headers=h, json={"currency": "usd"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["currency"] == "USD"


def test_bunker_option_currency_defaults_to_tenant_base_currency(client, auth_headers, db_engine):
    h = auth_headers
    _vessel_id, party_id, port_id = _master_ids(client, h)

    # 默认：租户本位币（demo 租户公司档案 = USD）
    rid = _make_requirement(client, h)
    r = client.post(
        "/api/v1/bunker/options",
        headers=h,
        json={"requirement_id": rid, "supplier_id": party_id, "port_id": port_id, "price_per_mt": 450},
    )
    assert r.status_code == 200, r.text
    assert r.json()["currency"] == "USD"

    # 把租户本位币改成 EUR → 不传币种时随之变化（不是写死 USD）
    prev = _set_base_currency(db_engine, "EUR")
    try:
        rid2 = _make_requirement(client, h)
        r2 = client.post(
            "/api/v1/bunker/options",
            headers=h,
            json={"requirement_id": rid2, "supplier_id": party_id, "port_id": port_id, "price_per_mt": 450},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["currency"] == "EUR"
    finally:
        _restore_base_currency(db_engine, prev)


def test_bunker_option_rejects_invalid_currency(client, auth_headers):
    h = auth_headers
    _vessel_id, party_id, port_id = _master_ids(client, h)
    rid = _make_requirement(client, h)
    bad = client.post(
        "/api/v1/bunker/options",
        headers=h,
        json={
            "requirement_id": rid,
            "supplier_id": party_id,
            "port_id": port_id,
            "price_per_mt": 450,
            "currency": "EURO",
        },
    )
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["code"] == "INVALID_CURRENCY"


def test_bunker_option_amount_is_decimal_derived(client, auth_headers, open_db):
    """报价总额必须由 Decimal 算出来：8.115 × 390.51 之类的组合在 float 下会带尾数。"""
    h = auth_headers
    _vessel_id, party_id, port_id = _master_ids(client, h)
    rid = _make_requirement(client, h)

    qty = 1686.781
    price = 390.51
    r = client.post(
        "/api/v1/bunker/options",
        headers=h,
        json={
            "requirement_id": rid,
            "supplier_id": party_id,
            "port_id": port_id,
            "qty": qty,
            "price_per_mt": price,
            "currency": "EUR",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # 单价/数量按列精度落库
    assert Decimal(str(body["price_per_mt"])) == Decimal("390.51")
    assert Decimal(str(body["qty"])) == Decimal("1686.781")

    # 总额 = Decimal 精确乘积 + 显式 ROUND_HALF_UP，最多 2 位小数
    exact = (Decimal("1686.781") * Decimal("390.51")).quantize(Decimal("0.01"))
    assert Decimal(str(body["amount"])) == exact == Decimal("658704.85")
    assert len(str(body["amount"]).split(".")[1]) <= 2

    # 旧的 float 乘法会算出 658704.8483099999 —— 现在必须是四舍五入后的分位值
    assert body["amount"] != qty * price

    db = open_db()
    try:
        row = db.get(BunkerOption, UUID(body["id"]))
        assert row is not None
        assert isinstance(row.price_per_mt, Decimal)
        assert row.price_per_mt == Decimal("390.51")
        assert row.qty == Decimal("1686.781")
    finally:
        db.close()


# ── 2. BunkerInquiry ───────────────────────────────────────────────────


def _make_order(client, h, currency: str | None = "EUR") -> str:
    payload = {"qty_ordered": 100, "unit_price": 450}
    if currency is not None:
        payload["currency"] = currency
    r = client.post("/api/v1/bunker-orders", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_bunker_inquiry_currency_inherits_order_and_accept_syncs(client, auth_headers, open_db):
    h = auth_headers
    order_id = _make_order(client, h, currency="EUR")

    # 不传币种 → 跟随加油单的币种
    r = client.post(
        f"/api/v1/bunker-orders/{order_id}/inquiries",
        headers=h,
        json={"supplier": "Bunker A", "quoted_price": 455.5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "EUR"

    db = open_db()
    try:
        row = db.get(BunkerInquiry, UUID(body["id"]))
        assert row is not None
        assert row.currency == "EUR"
    finally:
        db.close()

    # 显式币种优先
    r2 = client.post(
        f"/api/v1/bunker-orders/{order_id}/inquiries",
        headers=h,
        json={"supplier": "Bunker B", "quoted_price": 460.25, "currency": "USD"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["currency"] == "USD"

    # 列表口径一致
    listing = client.get(f"/api/v1/bunker-orders/{order_id}/inquiries", headers=h).json()
    by_id = {i["id"]: i["currency"] for i in listing}
    assert by_id[body["id"]] == "EUR"
    assert by_id[r2.json()["id"]] == "USD"

    # 采纳报价 → 单价与币种一起落到加油单
    acc = client.post(f"/api/v1/bunker-inquiries/{r2.json()['id']}/accept", headers=h)
    assert acc.status_code == 200, acc.text
    assert acc.json()["currency"] == "USD"
    assert Decimal(str(acc.json()["unit_price"])) == Decimal("460.25")

    orders = client.get("/api/v1/bunker-orders", headers=h).json()
    order = next(o for o in orders if o["id"] == order_id)
    assert order["currency"] == "USD"


def test_bunker_inquiry_rejects_invalid_currency(client, auth_headers):
    h = auth_headers
    order_id = _make_order(client, h, currency="EUR")
    bad = client.post(
        f"/api/v1/bunker-orders/{order_id}/inquiries",
        headers=h,
        json={"supplier": "Bunker C", "quoted_price": 450, "currency": "US"},
    )
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["code"] == "INVALID_CURRENCY"


# ── 3. BunkerCapCollar ─────────────────────────────────────────────────


def test_bunker_cap_collar_currency(client, auth_headers, open_db):
    h = auth_headers
    r = client.post(
        "/api/v1/bunker/cap-collar",
        headers=h,
        json={
            "fuel_type": "VLSFO",
            "cap_price": 700,
            "collar_price": 500,
            "currency": "EUR",
            "effective_from": "2026-01-01",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "EUR"

    db = open_db()
    try:
        row = db.get(BunkerCapCollar, UUID(body["id"]))
        assert row is not None
        assert row.currency == "EUR"
    finally:
        db.close()

    listing = client.get("/api/v1/bunker/cap-collar?fuel_type=VLSFO", headers=h).json()
    item = next(i for i in listing["items"] if i["id"] == body["id"])
    assert item["currency"] == "EUR"

    # 不传币种 → 租户本位币（demo = USD）
    r2 = client.post(
        "/api/v1/bunker/cap-collar",
        headers=h,
        json={"fuel_type": "MGO", "cap_price": 700, "effective_from": "2026-01-01"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["currency"] == "USD"

    # 非法币种 422
    bad = client.post(
        "/api/v1/bunker/cap-collar",
        headers=h,
        json={
            "fuel_type": "MGO",
            "cap_price": 700,
            "currency": "EURO",
            "effective_from": "2026-01-01",
        },
    )
    assert bad.status_code == 422, bad.text
    assert bad.json()["detail"]["code"] == "INVALID_CURRENCY"


# ── 4. 加油单本身的币种回落 ────────────────────────────────────────────


def test_bunker_order_currency_defaults_to_tenant_base(client, auth_headers, db_engine):
    h = auth_headers
    r = client.post("/api/v1/bunker-orders", headers=h, json={"qty_ordered": 100, "unit_price": 450})
    assert r.status_code == 200, r.text
    assert r.json()["currency"] == "USD"

    prev = _set_base_currency(db_engine, "EUR")
    try:
        r2 = client.post("/api/v1/bunker-orders", headers=h, json={"qty_ordered": 100, "unit_price": 450})
        assert r2.status_code == 200, r2.text
        assert r2.json()["currency"] == "EUR"
    finally:
        _restore_base_currency(db_engine, prev)
