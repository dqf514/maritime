"""Phase 0 后台作业队列：入队/幂等/重试退避/死信/webhook 真实投递。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_jobs import Job
from app.models_office import WebhookDelivery, WebhookEndpoint
from app.services.job_queue import enqueue, job_handler, process_pending, reclaim_stale
from app.services.webhook_service import dispatch_event


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db_session):
    return db_session.scalar(select(Tenant.id).limit(1))


def test_enqueue_process_and_idempotency(db_session):
    seen = []

    @job_handler("test.echo")
    def _echo(db, job):
        seen.append(job.payload.get("v"))

    tid = _tenant_id(db_session)
    enqueue(db_session, "test.echo", {"v": 1}, tenant_id=tid, idempotency_key="k1")
    again = enqueue(db_session, "test.echo", {"v": 2}, tenant_id=tid, idempotency_key="k1")
    assert again.payload["v"] == 1  # 幂等键命中，返回首个

    assert process_pending(db_session) == 1
    assert seen == [1]
    assert process_pending(db_session) == 0  # 不重复消费
    job = db_session.query(Job).filter_by(idempotency_key="k1").one()
    assert job.status == "done"
    assert job.attempts == 1


def test_retry_backoff_then_dead(db_session):
    @job_handler("test.boom")
    def _boom(db, job):
        raise RuntimeError("nope")

    tid = _tenant_id(db_session)
    job = enqueue(db_session, "test.boom", {}, tenant_id=tid, max_attempts=2)
    assert process_pending(db_session) == 1
    db_session.refresh(job)
    assert job.status == "pending"
    assert job.attempts == 1
    # 退避到未来（SQLite 回读可能为 naive，比较前统一时区）
    ra = job.run_after if job.run_after.tzinfo else job.run_after.replace(tzinfo=timezone.utc)
    assert ra > datetime.now(timezone.utc) - timedelta(seconds=1)
    # 到期前不消费
    assert process_pending(db_session) == 0
    job.run_after = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert process_pending(db_session) == 1
    db_session.refresh(job)
    assert job.status == "dead"
    assert job.attempts == 2
    assert "nope" in (job.last_error or "")


def test_unknown_kind_goes_dead_without_handler(db_session):
    job = enqueue(db_session, "test.missing", {})
    assert process_pending(db_session) == 1
    db_session.refresh(job)
    assert job.status == "dead"


def test_reclaim_stale_running(db_session):
    job = enqueue(db_session, "test.echo", {})
    job.status = "running"
    job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    db_session.commit()
    assert reclaim_stale(db_session) == 1
    db_session.refresh(job)
    assert job.status == "pending"


def test_webhook_dispatch_enqueues_and_delivers(db_session, monkeypatch):
    tid = _tenant_id(db_session)
    sub = WebhookEndpoint(
        tenant_id=tid,
        name="partner",
        target_url="https://example.invalid/hook",
        secret="s3cret",
        events=["voyage.*"],
        status="active",
    )
    db_session.add(sub)
    db_session.commit()

    deliveries = dispatch_event(db_session, tid, "voyage.started", {"id": "v1"})
    assert len(deliveries) == 1
    job = db_session.query(Job).filter_by(idempotency_key=f"webhook:{deliveries[0].id}").one()
    assert job.status == "pending"

    captured = {}

    class _Resp:
        status_code = 200

    def _fake_post(url, content=None, headers=None, timeout=None):
        captured["url"] = url
        captured["body"] = content
        captured["sig"] = headers.get("X-MariOS-Signature")
        return _Resp()

    monkeypatch.setattr("httpx.post", _fake_post)
    # P0-18 的出网白名单在投递前会**解析 DNS**；``example.invalid`` 解析不了
    # → fail-closed 拦下。本用例测的是投递/HMAC/幂等，所以把白名单短路掉；
    # 白名单本身由 test_webhook_delivery_blocks_internal_targets 单独覆盖。
    monkeypatch.setattr(
        "app.services.webhook_service.assert_safe_outbound_url", lambda *a, **k: None
    )
    assert process_pending(db_session) == 1
    d = db_session.get(WebhookDelivery, uuid.UUID(str(deliveries[0].id)))
    assert d.status == "delivered"
    assert d.response_code == 200
    assert captured["url"] == "https://example.invalid/hook"
    assert captured["sig"]  # HMAC 签名随请求发出

    # 幂等短路：job 重放不会二次投递
    job.status = "pending"
    job.run_after = datetime.now(timezone.utc)
    db_session.commit()
    d.status = "delivered"
    db_session.commit()
    calls = []
    monkeypatch.setattr("httpx.post", lambda *a, **k: calls.append(1) or _Resp())
    assert process_pending(db_session) == 1
    assert calls == []


def test_webhook_delivery_blocks_internal_targets(db_session, monkeypatch):
    """P0-18：投递前再校验一次出网地址 —— 环回 / 元数据地址一律不发出去。

    登记时校验过一次不够：域名可能在登记后被改指向内网（DNS rebinding），
    地址也可能在两次投递之间被改过。
    """
    tid = _tenant_id(db_session)
    sub = WebhookEndpoint(
        tenant_id=tid,
        name="internal",
        target_url="http://169.254.169.254/latest/meta-data/",
        secret="s3cret",
        events=["voyage.*"],
        status="active",
    )
    db_session.add(sub)
    db_session.commit()

    deliveries = dispatch_event(db_session, tid, "voyage.started", {"id": "v2"})
    assert len(deliveries) == 1

    calls = []
    monkeypatch.setattr("httpx.post", lambda *a, **k: calls.append(1))
    # 投递被拦 → 作业重试到死信，不产生任何出网请求
    process_pending(db_session)
    assert calls == [], "内网/元数据地址绝不能真的发出去"

    d = db_session.get(WebhookDelivery, uuid.UUID(str(deliveries[0].id)))
    assert d.status == "failed"
