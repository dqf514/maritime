"""P0-22 / P0-23 / P1-B14 回归测试。

覆盖：

- **P0-22** 主数据「空名」被接受 —— 主实体（对手方 / 船舶 / 港口）与二级主数据
  （商品大类 / 联系人 / 泊位 / 别名 / 属性 / 油耗矩阵）都必须拒绝 ``""`` / ``"   "``，
  合法名字仍然可用（且首尾空白会被剥掉）。
- **P0-23** 租船日程生成的发票不允许 0 金额（整段停租 → 应付天数 0 → 400）。
- **P1-B14** 对账行必须带币种，否则币种永远无法核对（currency_verified 恒为 false）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import Charter, OffHireEvent

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


# —— helpers ————————————————————————————————————————————————————————————


def _rows(client, h, path) -> list[dict]:
    body = client.get(f"{API}{path}", headers=h).json()
    if isinstance(body, dict):
        body = body.get("items", [])
    return body


def _first(client, h, path) -> dict:
    rows = _rows(client, h, path)
    assert rows, f"demo seed has no rows for {path}"
    return rows[0]


def _issued(client, h, amount=1000, currency="USD") -> dict:
    """开一张已出账发票（草稿 → pending_approval → issued）。"""
    inv = client.post(
        f"{API}/invoices", headers=h, json={"amount": amount, "currency": currency}
    ).json()
    client.post(f"{API}/invoices/{inv['id']}/transition?target=pending_approval", headers=h)
    client.post(f"{API}/invoices/{inv['id']}/transition?target=issued", headers=h)
    return inv


def _first_voyage_id(client, h) -> str:
    return _first(client, h, "/voyages")["id"]


# —— P0-22：主实体 + 简单二级主数据 ————————————————————————————————————


@pytest.mark.parametrize(
    "entity,payload",
    [
        ("counterparties", {"name": "", "type": "other"}),
        ("vessels", {"name": "   "}),
        ("ports", {"name": "", "unlocode": ""}),
        ("cargo-groups", {"name": ""}),
        ("cargo-groups", {"name": "  "}),
    ],
)
def test_masterdata_rejects_blank_names(client, auth_headers, entity, payload):
    r = client.post(f"{API}/masterdata/{entity}", headers=auth_headers, json=payload)
    assert r.status_code == 422, r.text


def test_masterdata_child_resources_reject_blank_names(client, auth_headers):
    """子表（联系人 / 属性 / 泊位 / 别名 / 油耗矩阵）的键字段同样不能为空。"""
    h = auth_headers
    party = _first(client, h, "/masterdata/counterparties")
    vessel = _first(client, h, "/masterdata/vessels")
    port = _first(client, h, "/masterdata/ports")
    cargo_names = _rows(client, h, "/masterdata/cargo-names")
    if not cargo_names:
        r = client.post(
            f"{API}/masterdata/cargo-names",
            headers=h,
            json={"short_name": "P0-22-CARGO", "full_name": "P0-22 Cargo"},
        )
        assert r.status_code in (200, 201), r.text
        cargo_names = [r.json()]
    cargo_name = cargo_names[0]

    cases = [
        (f"/masterdata/counterparties/{party['id']}/contacts", {"name": ""}),
        (f"/masterdata/counterparties/{party['id']}/contacts", {"name": "   "}),
        (f"/masterdata/counterparties/{party['id']}/properties", {"title": ""}),
        (f"/masterdata/cargo-names/{cargo_name['id']}/properties", {"title": "   "}),
        (f"/masterdata/ports/{port['id']}/berths", {"short_name": ""}),
        (f"/masterdata/ports/{port['id']}/aliases", {"alias": "   "}),
        (f"/masterdata/vessels/{vessel['id']}/port-consumptions", {"fuel_grade": " "}),
    ]
    for path, payload in cases:
        r = client.post(f"{API}{path}", headers=h, json=payload)
        assert r.status_code == 422, (path, r.text)


def test_masterdata_accepts_valid_name_and_strips_whitespace(client, auth_headers):
    """合法名字仍然可用；首尾空白被剥掉（否则 " X " 与 "X" 是两条主数据）。"""
    h = auth_headers
    r = client.post(
        f"{API}/masterdata/cargo-groups",
        headers=h,
        json={"name": "  P0-22 VALID GROUP  ", "description": "d"},
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["name"] == "P0-22 VALID GROUP"

    r = client.post(
        f"{API}/masterdata/cargo-groups", headers=h, json={"name": "P0-22 OTHER GROUP"}
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["name"] == "P0-22 OTHER GROUP"


def test_masterdata_name_length_is_capped(client, auth_headers):
    """超长名字（> 255）被拒 —— Text 列在 DB 层不限长，这里按 VARCHAR(255) 兜底。"""
    h = auth_headers
    r = client.post(f"{API}/masterdata/cargo-groups", headers=h, json={"name": "x" * 256})
    assert r.status_code == 422, r.text
    r = client.post(f"{API}/masterdata/cargo-groups", headers=h, json={"name": "x" * 255})
    assert r.status_code in (200, 201), r.text


# —— P0-22：定义在 app/routers/masterdata_ext.py 里的 4 个 schema ————————————
# 这些 body 定义在路由文件里（不在 schema 模块内）—— 已在 masterdata_ext.py
# 补上同样的「非空 + 长度封顶」校验。


@pytest.mark.parametrize(
    "entity,payload",
    [
        ("holiday-calendars", {"name": "", "year": 2026}),
        ("working-day-patterns", {"name": "   "}),
        ("term-lists", {"category": "laytime_terms", "code": "P022", "label_en": ""}),
        (
            "standard-paragraphs",
            {"category": "invoice_note", "code": "P022", "title": "   ", "content": "c"},
        ),
    ],
)
def test_router_local_masterdata_rejects_blank_names(client, auth_headers, entity, payload):
    r = client.post(f"{API}/masterdata/{entity}", headers=auth_headers, json=payload)
    assert r.status_code == 422, r.text


# —— P0-23：租船日程发票不允许 0 金额 ————————————————————————————————————


def test_hire_schedule_rejects_zero_billable_days(client, auth_headers, db_session):
    """整段停租 → 应付天数 0 → 零金额发票 → 400（不入 GL / 不占账龄）。"""
    h = auth_headers
    vessel = _first(client, h, "/masterdata/vessels")
    cp = client.post(
        f"{API}/charters",
        headers=h,
        json={"charter_type": "time", "vessel_id": vessel["id"]},
    )
    assert cp.status_code == 200, cp.text
    charter = db_session.get(Charter, UUID(cp.json()["id"]))
    charter.hire_per_day = Decimal("30000")
    db_session.add(
        OffHireEvent(
            tenant_id=charter.tenant_id,
            voyage_id=UUID(_first_voyage_id(client, h)),
            charter_id=charter.id,
            start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 16, tzinfo=timezone.utc),
            reason="full period off-hire",
            deduct_hire=True,
        )
    )
    db_session.commit()

    r = client.post(
        f"{API}/invoices/hire-schedule",
        headers=h,
        json={
            "charter_id": cp.json()["id"],
            "period_start": "2026-01-01",
            "period_end": "2026-01-16",
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "NO_BILLABLE_DAYS"

    # 零金额发票没有落库
    invs = _rows(client, h, "/invoices")
    assert all(float(i["amount"]) > 0 for i in invs)


def test_hire_schedule_rejects_zero_amount_after_deductions(client, auth_headers, db_session):
    """扣款（地址佣金 + 显式停租扣款）超过毛租金 → 净额 <= 0 → 400。"""
    h = auth_headers
    vessel = _first(client, h, "/masterdata/vessels")
    cp = client.post(
        f"{API}/charters",
        headers=h,
        json={"charter_type": "time", "vessel_id": vessel["id"]},
    )
    assert cp.status_code == 200, cp.text
    charter = db_session.get(Charter, UUID(cp.json()["id"]))
    charter.hire_per_day = Decimal("1000")
    charter.address_comm_pct = Decimal("100")  # 佣金吃光全部租金
    db_session.commit()

    r = client.post(
        f"{API}/invoices/hire-schedule",
        headers=h,
        json={
            "charter_id": cp.json()["id"],
            "period_start": "2026-03-01",
            "period_end": "2026-03-08",
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "INVALID_AMOUNT"


def test_hire_schedule_still_works_for_normal_period(client, auth_headers, db_session):
    """正常租期的租金发票照旧生成（别把好流程一起堵掉）。"""
    h = auth_headers
    vessel = _first(client, h, "/masterdata/vessels")
    cp = client.post(
        f"{API}/charters",
        headers=h,
        json={"charter_type": "time", "vessel_id": vessel["id"]},
    )
    assert cp.status_code == 200, cp.text
    charter = db_session.get(Charter, UUID(cp.json()["id"]))
    charter.hire_per_day = Decimal("15000")
    db_session.commit()

    r = client.post(
        f"{API}/invoices/hire-schedule",
        headers=h,
        json={
            "charter_id": cp.json()["id"],
            "period_start": "2026-04-01",
            "period_end": "2026-04-16",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 225000.0  # 15 天 × 15000
    assert body["meta"]["hire"]["billable_days"] == 15


# —— P1-B14：对账行带币种 ————————————————————————————————————————————————


def test_reconcile_line_carries_currency(client, auth_headers):
    """流水行带币种 → 币种被核对（currency_verified=true）；同额不同币种不配对。"""
    h = auth_headers
    amount = 123456.78
    inv = _issued(client, h, amount=amount)

    r = client.post(
        f"{API}/finance/reconciliation/preview",
        headers=h,
        json={
            "lines": [
                {"amount": amount, "reference": f"TT {inv['invoice_no']}", "currency": "USD"},
                {"amount": amount, "reference": f"TT {inv['invoice_no']}", "currency": "EUR"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    res = r.json()
    by_idx = {s["line_index"]: s for s in res["suggestions"]}
    assert 0 in by_idx, res
    assert by_idx[0]["invoice_id"] == inv["id"]
    assert by_idx[0]["currency_verified"] is True
    assert by_idx[0]["currency"] == "USD"  # 发票币种
    assert by_idx[0]["line_currency"] == "USD"  # 流水币种
    # 同额不同币种不是同一笔钱 → 不配对
    assert 1 not in by_idx, res
    assert 1 in res["unmatched"]


def test_reconcile_line_without_currency_is_unverified(client, auth_headers):
    """没带币种的流水行仍然能配对（人工确认），但 currency_verified=false。"""
    h = auth_headers
    amount = 654321.99
    inv = _issued(client, h, amount=amount)

    r = client.post(
        f"{API}/finance/reconciliation/preview",
        headers=h,
        json={"lines": [{"amount": amount, "reference": f"TT {inv['invoice_no']}"}]},
    )
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["suggestions"], res
    assert res["suggestions"][0]["currency_verified"] is False
    assert res["suggestions"][0]["currency"] == "USD"


def test_reconcile_line_currency_is_normalized_and_validated(client, auth_headers):
    """币种归一为大写 ISO 代码；非法币种 → 422。"""
    h = auth_headers
    r = client.post(
        f"{API}/finance/reconciliation/preview",
        headers=h,
        json={"lines": [{"amount": 10, "currency": " usd "}]},
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"{API}/finance/reconciliation/preview",
        headers=h,
        json={"lines": [{"amount": 10, "currency": "US"}]},
    )
    assert r.status_code == 422, r.text


def test_reconcile_apply_rejects_currency_mismatch(client, auth_headers):
    """核销时币种与发票不一致 → 400（防止把 EUR 的款核到 USD 发票上）。"""
    h = auth_headers
    amount = 987654.32
    inv = _issued(client, h, amount=amount)

    r = client.post(
        f"{API}/finance/reconciliation/apply",
        headers=h,
        json={
            "matches": [
                {"invoice_id": inv["id"], "amount": amount, "reference": "BANK-CCY", "currency": "EUR"}
            ]
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "CURRENCY_MISMATCH"

    detail = client.get(f"{API}/invoices/{inv['id']}", headers=h).json()
    assert detail["paid_amount"] == 0.0
