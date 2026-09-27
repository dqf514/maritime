"""D23 船队敞口：已锁定租金窗口 + 敏感度 + 市场对比（金样手工推演）。"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import Charter
from app.services.exposure import fleet_exposure


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def test_exposure_windows_and_sensitivity(db_session):
    """金样：TC 12000/天，还船在 45 天后。
    30d 窗口 → 30×12000 = 360k；60/90d 窗口 → 45×12000 = 540k（还船截断）。
    敏感度 ±1000/天：30d 上浮 +30k；60/90d +45k。市场 11000/天 → vs_market = 差额。
    """
    from sqlalchemy import select

    from app.models import Tenant

    tid = db_session.scalar(select(Tenant.id).where(Tenant.code == "demo"))
    today = date(2026, 9, 1)
    db_session.add(
        Charter(
            tenant_id=tid,
            charter_no="EXP-1",
            charter_type="tct",
            status="active",
            hire_per_day=12000,
            redelivery_at=datetime(2026, 10, 16, tzinfo=timezone.utc),  # 45 天后
        )
    )
    db_session.commit()

    r = fleet_exposure(db_session, tid, today=today, market_hire_rate=11000)
    w = r["windows"]
    assert w["30"]["locked_hire"] == 360000.0
    assert w["60"]["locked_hire"] == 540000.0
    assert w["90"]["locked_hire"] == 540000.0
    assert w["30"]["sensitivity_up"] == 390000.0
    assert w["30"]["sensitivity_down"] == 330000.0
    assert w["60"]["sensitivity_up"] == 585000.0
    assert w["30"]["market_hire"] == 330000.0
    assert w["30"]["vs_market"] == 30000.0  # 锁定贵 3 万
    assert len(r["charters"]) == 1


def test_exposure_endpoint(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.models import Tenant

    h = auth_headers
    tid = db_session.scalar(select(Tenant.id).where(Tenant.code == "demo"))
    db_session.add(
        Charter(
            tenant_id=tid,
            charter_no="EXP-2",
            charter_type="time",
            status="active",
            hire_per_day=8000,
        )
    )
    # 一条 draft 不计入
    db_session.add(
        Charter(tenant_id=tid, charter_no="EXP-D", charter_type="time", status="draft", hire_per_day=99999)
    )
    db_session.commit()

    body = client.get("/api/v1/risk/exposure?horizon_days=90", headers=h)
    assert body.status_code == 200, body.text
    data = body.json()
    assert [c["charter_no"] for c in data["charters"]] == ["EXP-2"]
    # 无还船期 → 满窗口：30×8000=240k, 60×8000=480k, 90×8000=720k
    assert data["windows"]["30"]["locked_hire"] == 240000.0
    assert data["windows"]["90"]["locked_hire"] == 720000.0


def test_risk_limit_inline_edit_patch(client, auth_headers, db_session):
    """U6 行内编辑落点：限额安全字段 PATCH。"""
    from sqlalchemy import select

    from app.models import Tenant
    from app.models_finance_ext import RiskLimit

    h = auth_headers
    tid = db_session.scalar(select(Tenant.id).where(Tenant.code == "demo"))
    row = RiskLimit(tenant_id=tid, scope="global", limit_type="exposure", amount=1000)
    db_session.add(row)
    db_session.commit()

    r = client.patch(f"/api/v1/risk/limits/{row.id}", headers=h, json={"amount": 2500, "active": False})
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 2500.0
    assert r.json()["active"] is False
    db_session.refresh(row)
    assert float(row.amount) == 2500.0
