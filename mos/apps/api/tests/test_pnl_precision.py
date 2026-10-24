"""P&L / 公司间分摊 的精度护栏（P0-B7 · P2-B24 · P2-B1）。

三条护栏：

- **P0-B7** —— 4 栏 P&L（``services/pnl_engine.py``）与动态 P&L
  （``services/pnl.py``）的发票类型映射必须**完全一致**。以前 4 栏少了
  ``XDIFF``，汇兑差异发票在那张表里**整行消失**（收入/成本分栏失真），
  而动态报表里却有 —— 同一张票两个口径。
- **P2-B24** —— P&L 汇总一律 ``Decimal`` 累加，只在响应组装时**量化一次**
  （显式 ``ROUND_HALF_UP``、两位小数），JSON 里仍然只出 float。
- **P2-B1** —— 公司间分摊用「最大余数法」（``money.allocate_by_weight``）：
  各份之和**精确等于**总额，逐行取整丢掉的尾差不再凭空消失。
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

API = "/api/v1"


# ────────────────────────── P0-B7：类型映射一致 ──────────────────────────


def test_invoice_line_mappings_are_identical():
    """两张发票类型 → P&L 行映射必须**逐条相等**（P0-B7）。

    以前 ``pnl_engine._INVOICE_LINE`` 少了 ``XDIFF``：汇兑差异发票在 4 栏
    视图里一行都不进，而动态 P&L 报表里有 —— 同一个系统两个答案。
    """
    from app.services import pnl, pnl_engine

    assert pnl_engine._INVOICE_LINE == pnl._INVOICE_LINE
    assert set(pnl_engine._INVOICE_LINE) == set(pnl._INVOICE_LINE)
    # 汇兑差异必须在两边都有，且落在同一行
    assert pnl_engine._INVOICE_LINE["XDIFF"] == "other"
    assert pnl._INVOICE_LINE["XDIFF"] == "other"


def test_invoice_line_mappings_cover_every_canonical_type():
    """映射表覆盖所有规范发票类型 —— 规范码不该"整行消失"。

    PDA/FDA/BKR 故意不映射（成本来自 PDA / 油订单，再计一次会双算），
    但它们仍要能被识别，因此这里断言"未映射集合"恰好是这三个。
    """
    from app.services import pnl, pnl_engine
    from app.services.invoice_types import CANONICAL_INVOICE_TYPES

    for mapping in (pnl_engine._INVOICE_LINE, pnl._INVOICE_LINE):
        unmapped = set(CANONICAL_INVOICE_TYPES) - set(mapping)
        assert unmapped == {"PDA", "FDA", "BKR"}


# ────────────────────────── P0-B7：XDIFF 上表 ──────────────────────────


def _mk_voyage(client, h, tag):
    r = client.post(f"{API}/voyages", headers=h, json={"voyage_no": f"{tag}-{uuid4().hex[:6]}"})
    if r.status_code != 200:
        r = client.post(f"{API}/voyages", headers=h, json={"status": "planning"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _mk_invoice(client, h, **kw):
    payload = {"invoice_type": "freight", "amount": 10000}
    payload.update(kw)
    r = client.post(f"{API}/invoices", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _issue(client, h, iid):
    assert client.post(
        f"{API}/invoices/{iid}/transition?target=pending_approval", headers=h
    ).status_code == 200
    assert client.post(f"{API}/invoices/{iid}/transition?target=issued", headers=h).status_code == 200


def test_xdiff_invoice_shows_up_in_4col_pnl(client, auth_headers):
    """汇兑差异发票必须出现在 4 栏 P&L 的 ``other`` 行里（P0-B7）。

    以前它整行消失 —— ``actual`` 的收入/成本分栏因此失真。
    """
    h = auth_headers
    vid = _mk_voyage(client, h, "XDIFF")
    inv = _mk_invoice(client, h, voyage_id=vid, invoice_type="xdiff", amount=1234.56)
    _issue(client, h, inv["id"])

    rows = client.get(f"{API}/analytics/reports/pnl-4col", headers=h).json()
    row = next(r for r in rows if r["voyage_id"] == vid)

    actual = row["columns"]["actual"]
    assert actual["other"] == pytest.approx(1234.56), actual
    # 汇兑差异走收入侧（"other"），所以 revenue 侧合计要带上它
    assert row["totals"]["actual"]["revenue"] == pytest.approx(1234.56)
    assert row["totals"]["actual"]["cost"] == pytest.approx(0.0)
    # 行数没变（不能凭空多一行）
    assert set(actual) == set(row["columns"]["estimate"])


def test_xdiff_invoice_shows_up_in_dynamic_pnl(client, auth_headers):
    """同一张汇兑差异票在动态 P&L 报表里也必须出现（两边口径一致）。"""
    h = auth_headers
    vid = _mk_voyage(client, h, "XDIFF2")
    inv = _mk_invoice(client, h, voyage_id=vid, invoice_type="xdiff", amount=1234.56)
    _issue(client, h, inv["id"])

    rows = client.get(f"{API}/analytics/reports/voyage-pnl?basis=actual", headers=h).json()
    row = next(r for r in rows if r["voyage_id"] == vid)
    assert row["lines_actual"]["other"] == pytest.approx(1234.56)


# ────────────────────────── P2-B24：汇总口径 ──────────────────────────


def test_pnl_aggregation_is_decimal_derived(client, auth_headers):
    """P&L 金额必须是 Decimal 累加、量化一次的结果（≤2 位小数）。"""
    h = auth_headers
    vid = _mk_voyage(client, h, "PREC")
    for amount in (0.1, 0.2, 10.005):
        inv = _mk_invoice(client, h, voyage_id=vid, invoice_type="freight", amount=amount)
        _issue(client, h, inv["id"])

    rows = client.get(f"{API}/analytics/reports/pnl-4col", headers=h).json()
    row = next(r for r in rows if r["voyage_id"] == vid)
    actual = row["columns"]["actual"]
    # 逐行量化：0.10 + 0.20 + 10.01 = 10.31；先求和后量化：10.305 → 10.31
    assert actual["revenue"] == pytest.approx(10.31)
    # 输出不得带超过 2 位小数
    for value in actual.values():
        exponent = Decimal(str(value)).as_tuple().exponent
        assert exponent >= -2, (value, exponent)


def test_fleet_summary_totals_match_voyage_rows(client, auth_headers):
    """船队汇总 = 各航次之和（P2-B24：两边同一套 Decimal 口径）。"""
    h = auth_headers
    vid = _mk_voyage(client, h, "FLEET")
    inv = _mk_invoice(client, h, voyage_id=vid, invoice_type="xdiff", amount=999.99)
    _issue(client, h, inv["id"])

    rows = client.get(f"{API}/analytics/reports/pnl-4col", headers=h).json()
    fleet = client.get(f"{API}/analytics/reports/pnl-fleet", headers=h).json()

    row = next(r for r in rows if r["voyage_id"] == vid)
    assert fleet["columns"]["actual"]["other"] == pytest.approx(
        row["columns"]["actual"]["other"]
    )
    assert fleet["voyage_count"] == len(rows)


# ────────────────────────── P2-B1：分摊尾差 ──────────────────────────


def test_allocate_by_weight_sums_exactly():
    """最大余数法：各份之和**精确等于**总额（100.00 分 3 份）。"""
    from app.services.money import allocate_by_weight

    parts = allocate_by_weight(Decimal("100.00"), [Decimal("33.3333")] * 3)
    assert sum(parts) == Decimal("100.00")
    assert all(p.as_tuple().exponent >= -2 for p in parts)
    # 逐行取整会得到 99.99 —— 尾差凭空消失
    naive = [Decimal("100.00") * Decimal("33.3333") / Decimal(100) for _ in range(3)]
    assert sum(p.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP") for p in naive) != Decimal("100.00")


def test_allocate_by_weight_handles_negative_total():
    """负数池期（亏损）同样精确求和。"""
    from app.services.money import allocate_by_weight

    parts = allocate_by_weight(Decimal("-100.00"), [Decimal("50"), Decimal("30"), Decimal("20")])
    assert sum(parts) == Decimal("-100.00")
    assert all(p.as_tuple().exponent >= -2 for p in parts)


def _pool_with_period(client, h, total_pool_result):
    pool = client.post(f"{API}/pools?name=Test Pool {uuid4().hex[:4]}", headers=h).json()
    pid = pool["id"]
    period = client.post(
        f"{API}/pools/{pid}/periods?label=2026-09&total_pool_result={total_pool_result}", headers=h
    ).json()
    return pid, period["id"]


def _mk_company(client, h, name):
    r = client.post(
        f"{API}/masterdata/companies",
        headers=h,
        json={"name": name, "code": f"{uuid4().hex[:8]}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_intercompany_split_sums_exactly_to_net_total(client, auth_headers):
    """公司间分摊：3 家平分一个**除不尽**的总额，各家之和精确等于 net_total。

    以前逐行取整：33.33 + 33.33 + 33.33 = 99.99 —— 少一分，池期结算对不上账。
    """
    h = auth_headers
    # 总额 100.00（无手续费 → net_total = 100.00），3 家按 33.33/33.33/33.34 分
    pid, per_id = _pool_with_period(client, h, 100.00)
    c1 = _mk_company(client, h, "IC Co A")
    c2 = _mk_company(client, h, "IC Co B")
    c3 = _mk_company(client, h, "IC Co C")

    r = client.post(
        f"{API}/pools/{pid}/periods/{per_id}/intercompany-distribution",
        headers=h,
        json={
            "allocations": [
                {"company_id": c1["id"], "share_pct": 33.3333},
                {"company_id": c2["id"], "share_pct": 33.3333},
                {"company_id": c3["id"], "share_pct": 33.3334},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    amounts = [Decimal(str(a["amount"])) for a in body["allocations"]]
    assert sum(amounts) == Decimal(str(body["net_total"]))
    assert sum(amounts) == Decimal("100.00")
    assert all(a.as_tuple().exponent >= -2 for a in amounts)
    assert len(body["allocations"]) == 3
