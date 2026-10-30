"""例行任务调度器 —— tick 链路与幂等。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Tenant
from app.models_jobs import Job
from app.models_routine import RoutineTask, TriggerRule
from app.models_wave1 import EmailAccount, EmailMessage
from app.services import routine_scheduler


@pytest.fixture()
def open_db(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)


def _demo_tenant(db) -> Tenant:
    return db.scalar(select(Tenant).where(Tenant.code == "demo"))


def test_routine_tick_chains_and_creates_drafts(open_db):
    """一次 tick → 排下一次 tick + 产出草稿（链不能因为异常断掉）。"""
    db = open_db()
    tenant = _demo_tenant(db)
    task = RoutineTask(
        tenant_id=tenant.id,
        code="tick_noon",
        name="Noon intake",
        direction="inbound",
        module_code="operations",
        trigger_type="inbound_email",
        trigger_config={},
        skill_code="noon_report",
        output_target="noon_report",
        owner_role="operations",
        sla_minutes=60,
        dedupe_key_template="message:{message_id}",
        enabled=True,
    )
    db.add(task)
    db.flush()
    db.add(
        TriggerRule(
            tenant_id=tenant.id,
            routine_task_id=task.id,
            sender_emails=[],
            sender_domains=[],
            subject_regex="noon report",
            body_markers=[],
            folder="inbox",
            direction="inbound",
            priority=100,
            enabled=True,
        )
    )
    db.add(
        EmailMessage(
            tenant_id=tenant.id,
            message_id="<tick-noon-1@x.com>",
            direction="inbound",
            folder="inbox",
            from_email="master@oceanstar.com",
            subject="Noon report — MV DEMO WAVE",
            body_text="Report at: 2026-10-30 06:00\nLat: 12.5\n",
            sent_at=datetime.now(timezone.utc),
            parse_status="pending",
            parse_result={},
        )
    )
    db.commit()

    routine_scheduler.install_scheduler(db)
    routine_scheduler._tick(db, None)
    db.commit()

    jobs = db.scalars(select(Job).where(Job.kind == routine_scheduler.TICK_KIND)).all()
    assert len(jobs) >= 2  # bootstrap + 下一次

    from app.models_routine import DraftRecord

    drafts = db.scalars(
        select(DraftRecord).where(
            DraftRecord.tenant_id == tenant.id, DraftRecord.routine_task_id == task.id
        )
    ).all()
    assert len(drafts) == 1

    # 再跑一次 tick —— 幂等：同一封邮件不再产生第二份草稿
    routine_scheduler._tick(db, None)
    db.commit()
    drafts = db.scalars(
        select(DraftRecord).where(
            DraftRecord.tenant_id == tenant.id, DraftRecord.routine_task_id == task.id
        )
    ).all()
    assert len(drafts) == 1


def test_email_sync_tick_calls_sync_service(monkeypatch, open_db):
    """邮箱同步 tick 只拉 Graph 账户，且调服务层（不自己实现同步）。"""
    db = open_db()
    tenant = _demo_tenant(db)
    db.add(
        EmailAccount(
            tenant_id=tenant.id,
            provider="microsoft",
            email="ops@demo.marios",
            display_name="Demo",
            config={},
            status="active",
        )
    )
    db.commit()

    from app.services.email_sync import SyncOutcome

    calls: list[str] = []

    def _fake(db_, *, tenant_id, account, **kwargs):
        calls.append(account.email)
        return SyncOutcome(payload={"synced": 0})

    monkeypatch.setattr("app.services.email_sync.sync_graph_mails", _fake)
    routine_scheduler._sync_tick(db, None)
    db.commit()
    assert calls == ["ops@demo.marios"]

    jobs = db.scalars(select(Job).where(Job.kind == routine_scheduler.EMAIL_SYNC_TICK_KIND)).all()
    assert len(jobs) >= 1
