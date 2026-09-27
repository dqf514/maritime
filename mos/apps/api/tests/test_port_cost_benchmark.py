"""D8 港口费用基准库：历史统计 + 超基准预警。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import PortCall, PortDisbursement, Voyage
from app.models_wave1 import Port


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _seed_pdas(client, h, db_session, n=3, lines_list=None, statuses=None):
    voyages = client.get("/api/v1/voyages", headers=h).json()
    voyages = voyages["items"] if isinstance(voyages, dict) else voyages
    vid = voyages[0]["id"]
    tid = db_session.get(Voyage, uuid.UUID(vid)).tenant_id
    port = Port(name=f"BENCH-{uuid.uuid4().hex[:4]}", unlocode="BENC", timezone="UTC")
    db_session.add(port)
    db_session.commit()
    created = []
    lines_list = lines_list or [{"agency": 5000, "pilotage": 2000}] * n
    statuses = statuses or ["approved"] * n
    for i, (lines, status) in enumerate(zip(lines_list, statuses)):
        pc = PortCall(tenant_id=tid, voyage_id=uuid.UUID(vid), seq=i + 1, purpose="load", port_id=port.id)
        db_session.add(pc)
        db_session.commit()
        pda = PortDisbursement(
            tenant_id=tid,
            voyage_id=uuid.UUID(vid),
            port_call_id=pc.id,
            status=status,
            pda_amount=sum(lines.values()),
            lines=lines,
        )
        db_session.add(pda)
        db_session.commit()
        created.append((pda, port.id))
    return created


def test_benchmark_stats(client, auth_headers, db_session):
    h = auth_headers
    rows = _seed_pdas(
        client,
        h,
        db_session,
        n=3,
        lines_list=[{"agency": 4000}, {"agency": 5000}, {"agency": 6000}],
    )
    port_id = rows[0][1]
    body = client.get(f"/api/v1/port-costs/benchmark?port_id={port_id}", headers=h).json()
    assert body["sample_count"] == 3
    st = body["fees"]["agency"]
    assert st["count"] == 3
    assert st["avg"] == 5000.0
    assert st["p50"] == 5000.0
    assert st["min"] == 4000.0 and st["max"] == 6000.0


def test_over_benchmark_flags_outlier(client, auth_headers, db_session):
    h = auth_headers
    # 3 条已批准基准（pilotage 均 2000）+ 1 条在办超基准（pilotage 4000）
    rows = _seed_pdas(
        client,
        h,
        db_session,
        n=3,
        lines_list=[{"pilotage": 2000}] * 3,
        statuses=["approved"] * 3,
    )
    port_id = rows[0][1]
    tid = rows[0][0].tenant_id
    # 在办单据（draft）挂在同一港口
    pc = PortCall(tenant_id=tid, voyage_id=rows[0][0].voyage_id, seq=9, purpose="load", port_id=port_id)
    db_session.add(pc)
    db_session.commit()
    draft = PortDisbursement(
        tenant_id=tid,
        voyage_id=rows[0][0].voyage_id,
        port_call_id=pc.id,
        status="draft",
        pda_amount=4000,
        lines={"pilotage": 4000},
    )
    db_session.add(draft)
    db_session.commit()

    body = client.get("/api/v1/port-costs/over-benchmark", headers=h).json()
    hit = next(i for i in body["items"] if i["fee"] == "pilotage")
    assert hit["amount"] == 4000.0
    assert hit["benchmark_p50"] == 2000.0
    assert hit["excess_pct"] == 100.0
