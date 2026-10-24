"""佣金金额精度 + commission_basis 口径回归（P1-B2 / P1-B8 / P2-B23）。

三件事：

1. **commission_basis 只存规范口径码**（net / gross）。旧实现往这个列里写
   一句 60+ 字的自由文本（"brokerage on INV-001 (charter ...)"）→ PG 上
   ``String(16)`` 直接 StringDataRightTruncation → 500；而且下游按 net/gross
   解析时静默落回 "gross"，口径丢失（P1-B2）。
2. **base_amount 落库前按 Numeric(18,2) 量化**（显式 ROUND_HALF_UP）——
   以前未量化直接落库，PG 静默舍入、SQLite 不舍 → 同一段代码两个库两个值。
3. **rate_pct 落库前按 Numeric(8,4) 量化** —— 以前用 money() 只留 2 位，
   列允许的 4 位精度被静默抹掉。
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_domain import Charter, Invoice
from app.models_finance_ext import CommissionType

CENT = Decimal("0.01")


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db_session) -> uuid.UUID:
    row = db_session.query(Tenant).first()
    assert row is not None
    return row.id


def _chartered_invoice(
    client,
    h,
    db_session,
    *,
    amount=100000,
    commission_basis=None,
    brokerage_pct="1.25",
    address_comm_pct="2.5",
    currency=None,
    fx_rate=None,
):
    """建一条挂在租约上的运费发票（租约佣金字段由用例自己设置）。"""
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
    if currency is not None:
        payload["currency"] = currency
    if fx_rate is not None:
        payload["fx_rate"] = fx_rate
    inv = client.post("/api/v1/invoices", headers=h, json=payload).json()
    return inv


def _basis_col_len() -> int:
    col = Invoice.__table__.c.commission_basis
    return int(col.type.length)


# ─────────────────────────── P1-B2 commission_basis ───────────────────────────


def test_commission_basis_column_fits_legacy_free_text():
    """basis 列必须放得下历史自由文本（PG 上超长 = 500）。"""
    col_len = _basis_col_len()
    legacy = "brokerage on INV-000123 (charter 0f1e2d3c-4b5a-6789-abcd-ef0123456789)"
    assert col_len >= len(legacy)
    assert col_len >= 128


def test_brokerage_invoice_keeps_net_basis(client, auth_headers, db_session):
    """源发票口径是 net → 佣金发票仍然是 net（不再静默变成 gross）。"""
    h = auth_headers
    inv = _chartered_invoice(client, h, db_session, amount=97500, commission_basis="net")
    r = client.post(f"/api/v1/invoices/{inv['id']}/commission-invoices", headers=h)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    row = db_session.get(Invoice, uuid.UUID(r.json()["id"]))
    assert row.commission_basis == "net"
    assert row.commission_basis in ("net", "gross")
    assert len(row.commission_basis) <= _basis_col_len()
    # 净额 97500 + 地址佣金 2.5% → 反推毛额 100000 → 经纪佣金 1.25% = 1250
    assert row.amount == Decimal("1250.00")


def test_brokerage_invoice_defaults_to_gross_basis(client, auth_headers, db_session):
    """源发票没有口径 → 佣金发票落 gross（规范码，不是自由文本）。"""
    h = auth_headers
    inv = _chartered_invoice(client, h, db_session, amount=80000)
    r = client.post(f"/api/v1/invoices/{inv['id']}/commission-invoices", headers=h)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    row = db_session.get(Invoice, uuid.UUID(r.json()["id"]))
    assert row.commission_basis == "gross"
    assert len(row.commission_basis) <= _basis_col_len()
    assert row.amount == Decimal("1000.00")


def test_brokerage_invoice_description_moves_to_meta(client, auth_headers, db_session):
    """说明文字进 meta（Invoice 没有独立的自由文本列），basis 列只留口径码。"""
    h = auth_headers
    inv = _chartered_invoice(client, h, db_session, amount=80000, commission_basis="gross")
    r = client.post(f"/api/v1/invoices/{inv['id']}/commission-invoices", headers=h)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    row = db_session.get(Invoice, uuid.UUID(r.json()["id"]))
    assert "brokerage on" not in (row.commission_basis or "")
    meta = row.meta or {}
    assert meta["commission"]["source_invoice_no"] == inv["invoice_no"]
    assert meta["commission"]["description"].startswith("brokerage on ")
    assert meta["commission"]["base_basis"] == "gross"


# ─────────────────────────── 佣金单的外币口径 ───────────────────────────


def test_brokerage_invoice_carries_source_fx_rate(client, auth_headers, db_session):
    """佣金单与源单同币种 → 沿用源单汇率，本币金额 = 佣金额 × 汇率。

    旧实现只写 ``currency``、``fx_rate`` / ``base_amount`` 留空 → 下游
    ``money.invoice_base_amount()`` 走"原币当本币"的兜底分支，外币佣金被
    当成本位币直接入账（金额错一个汇率倍数）。
    """
    h = auth_headers
    inv = _chartered_invoice(
        client, h, db_session, amount=80000, currency="EUR", fx_rate=0.9
    )
    assert inv.get("id"), inv
    r = client.post(f"/api/v1/invoices/{inv['id']}/commission-invoices", headers=h)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    row = db_session.get(Invoice, uuid.UUID(r.json()["id"]))
    assert row.currency == "EUR"
    assert row.fx_rate == Decimal("0.9")
    assert row.amount == Decimal("1000.00")  # 80000 × 1.25%
    assert row.base_amount == Decimal("900.00")  # 1000 × 0.9


def test_brokerage_invoice_base_currency_uses_rate_one(client, auth_headers, db_session):
    """本位币佣金单：汇率 1、本币金额 = 原币金额。"""
    h = auth_headers
    inv = _chartered_invoice(client, h, db_session, amount=80000)
    r = client.post(f"/api/v1/invoices/{inv['id']}/commission-invoices", headers=h)
    assert r.status_code == 200, r.text

    db_session.expire_all()
    row = db_session.get(Invoice, uuid.UUID(r.json()["id"]))
    assert row.fx_rate == Decimal("1")
    assert row.base_amount == Decimal("1000.00")


# ─────────────────────────── P1-B8 / P2-B23 落库精度 ───────────────────────────


def test_commission_record_base_amount_quantized(db_session):
    """base_amount 落库前按 Numeric(18,2) 量化（HALF_UP），rate_pct 留 4 位。"""
    from app.services.commission import create_commission_record

    row = create_commission_record(
        db_session,
        _tenant_id(db_session),
        "brokerage",
        Decimal("1234.5678"),
        Decimal("1.23456789"),
    )
    assert isinstance(row.base_amount, Decimal)
    assert row.base_amount == Decimal("1234.57")
    assert row.base_amount.as_tuple().exponent >= -2  # 最多 2 位小数
    assert row.rate_pct == Decimal("1.2346")
    assert row.rate_pct.as_tuple().exponent >= -4  # 最多 4 位小数
    # 落库行自洽：用落库的基数与费率复算 == 落库的金额
    assert row.calculated_amount == Decimal("15.24")
    assert (
        row.base_amount * row.rate_pct / Decimal("100")
    ).quantize(CENT, rounding=ROUND_HALF_UP) == row.calculated_amount


def test_commission_api_keeps_four_decimal_rate(client, auth_headers, db_session):
    """POST /commissions：费率保留 4 位（Numeric(8,4)），基数按 2 位量化。"""
    r = client.post(
        "/api/v1/commissions",
        headers=auth_headers,
        json={
            "commission_type": "brokerage",
            "base_amount": 1234.5678,
            "rate_pct": 1.23456789,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rate_pct"] == 1.2346
    assert body["base_amount"] == 1234.57

    db_session.expire_all()
    row = db_session.get(CommissionType, uuid.UUID(body["id"]))
    assert row.base_amount == Decimal("1234.57")
    assert row.rate_pct == Decimal("1.2346")
    assert row.calculated_amount == Decimal("15.24")
    assert row.base_amount.as_tuple().exponent >= -2
    assert row.rate_pct.as_tuple().exponent >= -4


def test_patch_commission_keeps_four_decimal_rate(client, auth_headers, db_session):
    """PATCH /commissions/{id}：费率按 4 位 HALF_UP 量化（2.98765 → 2.9877）。"""
    r = client.post(
        "/api/v1/commissions",
        headers=auth_headers,
        json={"commission_type": "brokerage", "base_amount": 1000, "rate_pct": 1.25},
    )
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    p = client.patch(
        f"/api/v1/commissions/{cid}",
        headers=auth_headers,
        json={"rate_pct": 2.98765},
    )
    assert p.status_code == 200, p.text
    assert p.json()["rate_pct"] == 2.9877

    db_session.expire_all()
    row = db_session.get(CommissionType, uuid.UUID(cid))
    assert row.rate_pct == Decimal("2.9877")
    assert row.calculated_amount == Decimal("29.88")  # 1000 × 2.9877%
