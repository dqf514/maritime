"""D17 合规申报导出：MRV / ETS / FuelEU（口径与 fueleu_calc 同源）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_domain import EmissionRecord, PortCall, Voyage
from app.models_wave1 import Port


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _seed_emissions(db_session, client, h):
    """自建一条**专属**航次 + 两个 EU 港的口挂，再挂两条排放记录。

    以前这里借用了 ``/api/v1/voyages`` 的第一条（演示航次）。那条航次是不是
    带港口挂靠，取决于 ``ORDER BY created_at DESC, id DESC`` 在同一秒创建的
    演示航次里怎么排 —— 而 ``id`` 是随机 UUID，所以**每次重建模板库排出来的
    第一条航次都不一样**：拿到带港口挂靠的那条时 EU 份额会从 1.0 掉到 0.83，
    ETS 配额随之从 600 掉到 500，用例随机红（这是既有的随机失败，不是本次
    改动引入的）。现在改成自建航次，用例与演示数据完全解耦。
    """
    voyages = client.get("/api/v1/voyages", headers=h).json()
    voyages = voyages["items"] if isinstance(voyages, dict) else voyages
    tid = db_session.get(Voyage, uuid.UUID(voyages[0]["id"])).tenant_id

    voyage = Voyage(
        tenant_id=tid,
        voyage_no=f"ETS-TEST-{uuid.uuid4().hex[:8].upper()}",
        status="planned",
    )
    db_session.add(voyage)
    db_session.flush()

    # EU↔EU 两港 → eu_share = 1.0
    eu = Port(name="ROT-EU", unlocode=f"EU{uuid.uuid4().hex[:3].upper()}", timezone="UTC", is_eu=True)
    db_session.add(eu)
    db_session.flush()
    for seq in (1, 2):
        db_session.add(
            PortCall(tenant_id=tid, voyage_id=voyage.id, seq=seq, purpose="load", port_id=eu.id)
        )
    db_session.flush()
    for fo, do, co2 in ((100.0, 20.0, 400.0), (50.0, 10.0, 200.0)):
        db_session.add(
            EmissionRecord(
                tenant_id=tid, voyage_id=voyage.id, fo_mt=fo, do_mt=do, co2_mt=co2, period="2026"
            )
        )
    db_session.commit()
    return tid, voyage.id


def test_mrv_inventory_and_csv(client, auth_headers, db_session):
    h = auth_headers
    _seed_emissions(db_session, client, h)
    body = client.get("/api/v1/emissions/compliance-report?scheme=mrv&period=2026", headers=h)
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["scheme"] == "mrv"
    assert len(data["rows"]) == 2
    assert data["totals"]["co2_mt"] == 600.0
    assert data["totals"]["fo_mt"] == 150.0
    assert "voyage_id" in data["csv"].splitlines()[0]


def test_ets_allowances_with_eu_share(client, auth_headers, db_session):
    h = auth_headers
    _, vid = _seed_emissions(db_session, client, h)
    body = client.get("/api/v1/emissions/compliance-report?scheme=ets&period=2026", headers=h).json()
    # EU↔EU → share 1.0 → 配额 = CO2 合计 600t
    rows = [r for r in body["rows"] if r["voyage_id"] == str(vid)]
    assert len(rows) == 2
    assert all(r["eu_share"] == 1.0 for r in rows)
    assert body["totals"]["allowances_t"] == 600.0
    assert sum(r["allowances_t"] for r in rows) == 600.0


def test_ets_allowances_half_share_for_mixed_eu_legs(client, auth_headers, db_session):
    """非 EU 港只走一半 —— 配额按 EU 份额折算（回归护栏）。"""
    h = auth_headers
    _, vid = _seed_emissions(db_session, client, h)
    non_eu = Port(
        name="ROT-NON-EU", unlocode=f"XX{uuid.uuid4().hex[:3].upper()}", timezone="UTC", is_eu=False
    )
    db_session.add(non_eu)
    db_session.flush()
    # 插一条非 EU 挂靠 → 三港两条腿：EU→EU = 1.0，EU→非EU = 0.5 → 份额 0.75
    db_session.add(PortCall(tenant_id=db_session.get(Voyage, vid).tenant_id, voyage_id=vid, seq=3, purpose="load", port_id=non_eu.id))
    db_session.commit()
    body = client.get("/api/v1/emissions/compliance-report?scheme=ets&period=2026", headers=h).json()
    rows = [r for r in body["rows"] if r["voyage_id"] == str(vid)]
    assert all(r["eu_share"] == 0.75 for r in rows)
    assert sum(r["allowances_t"] for r in rows) == 450.0


def test_fueleu_balance_matches_calc_formula(client, auth_headers, db_session):
    h = auth_headers
    _seed_emissions(db_session, client, h)
    body = client.get("/api/v1/emissions/compliance-report?scheme=fueleu&period=2026", headers=h).json()
    row = body["rows"][0]
    # 公式核对（与 fueleu_calc 同源）：
    # energy = (150 FO + 30 DO) × 42700 = 7,686,000 MJ
    # co2e = 150×3.114 + 30×3.206 = 563.28 t
    # intensity = 563.28e6 / 7.686e6 ≈ 73.28 < 89.34 目标 → balance 0
    assert row["energy_mj"] == 7686000.0
    assert abs(row["intensity_gco2e_mj"] - 73.283) < 0.01
    assert row["compliance_balance_t"] == 0.0
