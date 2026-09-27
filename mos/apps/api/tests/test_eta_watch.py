"""D7 ETA 监控：午报船位快照 + 偏差预警 + AIS 适配层。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import NoonReport, Voyage


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def test_eta_watch_flags_deviation(client, auth_headers, db_session):
    h = auth_headers
    voyages = client.get("/api/v1/voyages", headers=h).json()
    voyages = voyages["items"] if isinstance(voyages, dict) else voyages
    vid = uuid.UUID(voyages[0]["id"])
    voy = db_session.get(Voyage, vid)
    voy.status = "in_progress"  # 种子航次可能是 completed，看板只看在航/待航
    tid = voy.tenant_id

    base = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    # 两条午报：只取最新；偏差 +20h → critical（阈值 12）
    db_session.add(
        NoonReport(
            tenant_id=tid,
            voyage_id=vid,
            report_at=base,
            speed=11.0,
            eta_next=base + timedelta(days=3),
            eta_deviation_hours=2,
        )
    )
    db_session.add(
        NoonReport(
            tenant_id=tid,
            voyage_id=vid,
            report_at=base + timedelta(days=1),
            lat=31.2,
            lon=121.5,
            speed=10.5,
            eta_next=base + timedelta(days=4),
            eta_deviation_hours=20,
        )
    )
    db_session.commit()

    body = client.get("/api/v1/ops/eta-watch?deviation_threshold_h=12", headers=h)
    assert body.status_code == 200, body.text
    data = body.json()
    item = next(i for i in data["items"] if i["voyage_id"] == str(vid))
    assert item["eta_deviation_hours"] == 20.0  # 最新一条
    assert item["lat"] == 31.2
    assert item["source"] == "noon"
    alert = next(a for a in data["alerts"] if a["voyage_id"] == str(vid))
    # 20h < 2×12h → warning（≥2×阈值才 critical）
    assert alert["severity"] == "warning"


def test_ais_adapter_interface_and_config_fallback():
    from app.services.ais_adapter import NoonAisProvider, default_provider

    assert isinstance(default_provider(), NoonAisProvider)  # 未配置 AIS → 午报源
