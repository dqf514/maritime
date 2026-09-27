"""D24 对手方信用：制裁重筛 + 信用敞口 + 批量重筛作业。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_finance_ext import RiskLimit


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _party_id(client, h):
    rows = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    return rows[0]["id"]


def test_rescreen_records_audit(client, auth_headers, db_session):
    h = auth_headers
    pid = _party_id(client, h)
    body = client.post(f"/api/v1/masterdata/counterparties/{pid}/rescreen", headers=h)
    assert body.status_code == 200, body.text
    assert body.json()["result"] in ("clear", "blocked")
    assert body.json()["screening_id"]

    from app.models_finance_ext import SanctionsScreening

    rows = db_session.query(SanctionsScreening).filter_by(counterparty_id=uuid.UUID(pid)).all()
    assert len(rows) == 1


def test_credit_exposure_vs_limit(client, auth_headers, db_session):
    h = auth_headers
    pid = _party_id(client, h)
    # 两张未结发票 300 + 200（含税 0）→ 敞口 500
    for amt in (300, 200):
        inv = client.post("/api/v1/invoices", headers=h, json={"amount": amt, "counterparty_id": pid}).json()
        client.post(f"/api/v1/invoices/{inv['id']}/transition?target=pending_approval", headers=h)
        client.post(f"/api/v1/invoices/{inv['id']}/transition?target=issued", headers=h)

    # 限额 400 → breach
    tid = db_session.query(Tenant.id).filter(Tenant.code == "demo").scalar()
    db_session.add(
        RiskLimit(
            tenant_id=tid,
            scope=f"counterparty:{pid}",
            limit_type="credit",
            amount=400,
        )
    )
    db_session.commit()

    body = client.get(f"/api/v1/masterdata/counterparties/{pid}/credit-exposure", headers=h).json()
    assert body["open_exposure"] == 500.0
    assert body["open_invoice_count"] == 2
    assert body["credit_limit"] == 400.0
    assert body["breach"] is True
    assert body["utilization_pct"] == 125.0


def test_rescreen_all_enqueues_job(client, auth_headers, db_session):
    from app.models_jobs import Job
    from app.services.job_queue import process_pending

    h = auth_headers
    body = client.post("/api/v1/masterdata/counterparties/rescreen-all", headers=h)
    assert body.status_code == 200, body.text
    job_id = body.json()["job_id"]

    assert process_pending(db_session) >= 1
    job = db_session.get(Job, uuid.UUID(job_id))
    assert job.status == "done"
    # 幂等键：当日重复调用返回同一作业
    again = client.post("/api/v1/masterdata/counterparties/rescreen-all", headers=h).json()
    assert again["job_id"] == job_id
