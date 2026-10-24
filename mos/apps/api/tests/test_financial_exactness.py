"""财务报表**精确相等**回归 —— 审计 P2-B3 · P2-B24。

这两个编号此前**没有任何**用例锁住：

- **P2-B3** —— 试算平衡/资产负债表的 ``balanced`` 以前用 ``< 0.01`` 的 float
  容差判断，而写路径（``gl_engine.build_journal_entries``）用 Decimal 精确比较
  拒收不平的分录。两套口径互相打架：写路径拒收的报表却放行。
  现在统一为**精确相等**（``total_debit == total_credit``）。
- **P2-B24** —— ``pnl_engine._commission`` 以前是浮点乘除 + ``round(x, 2)``，
  落库前差分；现在全程 Decimal + 显式 ``ROUND_HALF_UP``。

本文件锁的是**正确期望**，不是把缺陷固化成期望（审计 §6.1.1）。
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_gl import BusinessRule, ChartOfAccount, PeriodJournal


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _fresh_tenant(db) -> uuid.UUID:
    """新建一个**空租户**做记账科目/日记账。

    用空租户而不是 demo 租户：demo 里可能有已过账的日记账，会污染
    借贷合计，让"差 1 分"的断言依赖种子数据。
    """
    tenant = Tenant(
        name="Exactness Test",
        code=f"exactness-{uuid.uuid4().hex[:8]}",
        status="active",
        default_locale="en",
        default_timezone="UTC",
    )
    db.add(tenant)
    db.commit()
    return tenant.id


def _account(db, tenant_id, code: str, name: str, account_type: str) -> None:
    db.add(
        ChartOfAccount(
            tenant_id=tenant_id,
            account_code=code,
            account_name=name,
            account_type=account_type,
            currency="USD",
            is_active=True,
        )
    )


def _journal(db, tenant_id, entries, period: str = "2026-01") -> None:
    db.add(
        PeriodJournal(
            tenant_id=tenant_id,
            period=period,
            journal_type="non_voyage",
            description="exactness test",
            entries=entries,
            total_debit=Decimal("0"),
            total_credit=Decimal("0"),
            status="posted",
            currency="USD",
        )
    )
    db.commit()


# ─────────────────────────── P2-B3 试算平衡精确相等 ───────────────────────────


def test_p2_b3_trial_balance_flags_one_cent_imbalance(db_session):
    """借贷差 1 分必须报 **不平** —— float 容差（``<= 0.01``）会把它放过。

    写路径（``gl_engine``）用 Decimal 精确比较拒收不平分录；报表层如果用
    ``< 0.01`` 的容差，同一张不平的分录在报表里却显示"平衡"。
    """
    from app.services import financial_statements as fs

    db = db_session
    tenant_id = _fresh_tenant(db)
    _account(db, tenant_id, "1000", "Cash", "asset")
    _account(db, tenant_id, "2000", "Accounts payable", "liability")
    db.commit()

    _journal(
        db,
        tenant_id,
        [
            {"account_code": "1000", "debit": "100.00", "credit": "0"},
            {"account_code": "2000", "debit": "0", "credit": "99.99"},
        ],
    )

    tb = fs.trial_balance(db, tenant_id, "2026-01", "2026-01")

    assert tb["total_debit"] == 100.0
    assert tb["total_credit"] == 99.99
    assert tb["balanced"] is False, "借贷差 1 分必须报不平（精确相等，不是 float 容差）"


def test_p2_b3_trial_balance_has_no_float_tolerance(db_session):
    """**亚分**差额也必须报不平 —— 任何 ``< 0.01`` 的 float 容差都会放过它。

    ``0.005`` 的差额在旧的"容差"实现里 ``abs(0.005) < 0.01`` → 判定平衡，
    于是写路径（``gl_engine`` 用 Decimal 精确比较）拒收的分录在报表里显示
    "平衡"。现在两边统一为**精确相等**：分位舍入后不等即报不平。
    """
    from app.services import financial_statements as fs

    db = db_session
    tenant_id = _fresh_tenant(db)
    _account(db, tenant_id, "1000", "Cash", "asset")
    _account(db, tenant_id, "2000", "Accounts payable", "liability")
    db.commit()

    _journal(
        db,
        tenant_id,
        [
            {"account_code": "1000", "debit": "100.005", "credit": "0"},
            {"account_code": "2000", "debit": "0", "credit": "100.000"},
        ],
    )

    tb = fs.trial_balance(db, tenant_id, "2026-01", "2026-01")

    assert tb["balanced"] is False, "亚分差额不得被 float 容差吞掉"


def test_p2_b3_trial_balance_reports_balanced_when_exact(db_session):
    """分毫不差时必须报**平衡**（正向用例，防止把恒 False 当成"修好了"）。"""
    from app.services import financial_statements as fs

    db = db_session
    tenant_id = _fresh_tenant(db)
    _account(db, tenant_id, "1000", "Cash", "asset")
    _account(db, tenant_id, "2000", "Accounts payable", "liability")
    db.commit()

    _journal(
        db,
        tenant_id,
        [
            {"account_code": "1000", "debit": "100.00", "credit": "0"},
            {"account_code": "2000", "debit": "0", "credit": "100.00"},
        ],
    )

    tb = fs.trial_balance(db, tenant_id, "2026-01", "2026-01")

    assert tb["total_debit"] == 100.0
    assert tb["total_credit"] == 100.0
    assert tb["balanced"] is True


def test_p2_b3_balance_sheet_identity_is_exact(db_session):
    """A = L + E 也是**精确相等**：差 1 分必须报不平。"""
    from app.services import financial_statements as fs

    db = db_session
    tenant_id = _fresh_tenant(db)
    _account(db, tenant_id, "1000", "Cash", "asset")
    _account(db, tenant_id, "2000", "Accounts payable", "liability")
    db.commit()

    _journal(
        db,
        tenant_id,
        [
            {"account_code": "1000", "debit": "100.00", "credit": "0"},
            {"account_code": "2000", "debit": "0", "credit": "99.99"},
        ],
    )

    from datetime import date

    bs = fs.generate_balance_sheet(db, tenant_id, date(2026, 1, 31))

    assert bs["total_assets"] == 100.0
    assert bs["total_liabilities"] == 99.99
    assert bs["balanced"] is False, "A ≠ L+E（差 1 分）必须报不平"


# ─────────────────────────── P2-B24 佣金 Decimal 口径 ───────────────────────────


def test_p2_b24_commission_uses_decimal_half_up():
    """佣金成本用 Decimal + HALF_UP：``2.675`` → ``2.68``，不是 float 的 ``2.67``。

    旧实现 ``(base * pct / 100)`` 走 float，``2.675`` 实际存的是
    ``2.674999999999999822…``，``round(2.675, 2)`` 得 ``2.67`` —— 比正确的
    HALF_UP 少半分，且这条差额会一路落库到损益表。
    """
    from app.services import pnl_engine

    charter = SimpleNamespace(
        address_comm_pct=Decimal("100"),
        brokerage_pct=Decimal("0"),
    )

    out = pnl_engine._commission(charter, 2.675, 0.0)

    assert out == 2.68, f"期望 HALF_UP 的 2.68，实际 {out}（float 口径会给 2.67）"


def test_p2_b24_commission_sums_address_and_brokerage_in_decimal():
    """地址佣金 + 经纪佣金在 Decimal 上求和后**一次**量化到分。"""
    from app.services import pnl_engine

    charter = SimpleNamespace(
        address_comm_pct=Decimal("2.5"),
        brokerage_pct=Decimal("1.25"),
    )

    out = pnl_engine._commission(charter, 10000.0, 8000.0)

    # 10000 × 2.5% = 250.00；8000 × 1.25% = 100.00 → 350.00
    assert out == 350.0


# ─────────────────────────── P2-B12 GL 分录金额量化到分 ───────────────────────────


def test_p2_b12_journal_entry_amounts_are_quantized_to_cents(db_session):
    """GL 分录金额必须**量化到分**再落库（列是 ``Numeric(18,2)``）。

    以前是 ``str(line["amount"])`` —— 可能带 3 位小数：SQLite 存得进去、
    Postgres 会截断，同一笔账在两种库上对不上（借贷不平或差半分）。
    """
    from app.services import gl_engine

    db = db_session
    tenant_id = _fresh_tenant(db)
    _account(db, tenant_id, "5000", "Bunker expense", "expense")
    _account(db, tenant_id, "2000", "Accounts payable", "liability")
    db.add(
        BusinessRule(
            tenant_id=tenant_id,
            rule_name="bunker default",
            entity_type="bunker",
            expense_category="bunker",
            debit_account="5000",
            credit_account="2000",
            conditions={},
            priority=0,
            is_active=True,
        )
    )
    db.commit()

    entries = gl_engine.build_journal_entries(
        db,
        tenant_id,
        [
            {
                "entity_type": "bunker",
                "expense_category": "bunker",
                "amount": 100.005,
                "reference": "TEST-1",
            }
        ],
    )

    assert len(entries) == 2
    debit, credit = entries
    assert debit["debit"] == "100.01"
    assert debit["credit"] == "0"
    assert credit["credit"] == "100.01"
    assert credit["debit"] == "0"
    # 借贷必须严格相等，且都只到分
    assert Decimal(debit["debit"]) == Decimal(credit["credit"])
    assert all(
        len(str(e["debit"]).split(".")[-1]) <= 2 and len(str(e["credit"]).split(".")[-1]) <= 2
        for e in entries
    )
