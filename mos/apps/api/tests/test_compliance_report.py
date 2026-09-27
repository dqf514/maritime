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
    voyages = client.get("/api/v1/voyages", headers=h).json()
    voyages = voyages["items"] if isinstance(voyages, dict) else voyages
    vid = uuid.UUID(voyages[0]["id"])
    tid = db_session.get(Voyage, vid).tenant_id
    # EU↔EU 两港 → eu_share = 1.0
    eu = Port(name="ROT-EU", unlocode=f"EU{uuid.uuid4().hex[:3].upper()}", timezone="UTC", is_eu=True)
    db_session.add(eu)
    db_session.commit()
    for seq in (1, 2):
        db_session.add(PortCall(tenant_id=tid, voyage_id=vid, seq=seq, purpose="load", port_id=eu.id))
    db_session.commit()
    for fo, do, co2 in ((100.0, 20.0, 400.0), (50.0, 10.0, 200.0)):
        db_session.add(
            EmissionRecord(tenant_id=tid, voyage_id=vid, fo_mt=fo, do_mt=do, co2_mt=co2, period="2026")
        )
    db_session.commit()
    return tid, vid


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
    _seed_emissions(db_session, client, h)
    body = client.get("/api/v1/emissions/compliance-report?scheme=ets&period=2026", headers=h).json()
    # EU↔EU → share 1.0 → 配额 = CO2 合计 600t
    assert body["totals"]["allowances_t"] == 600.0
    assert all(r["eu_share"] == 1.0 for r in body["rows"])


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
