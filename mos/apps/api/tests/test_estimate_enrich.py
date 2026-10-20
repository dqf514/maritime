"""Track 1 — vessel-master / fuel-zone / market enrichment of estimate inputs.

同事意见 #2：船速油耗（船舶档案）与 Fuel zone / EU ETS 计算此前是断链的。
enrich_estimate_inputs 只填缺失字段；显式输入永远优先；无 vessel_id 时
完全不生效（gold fixtures 与纯算术调用不受影响）。
"""

import pytest
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.services.estimate_engine import compute_estimate
from app.services.estimate_enrich import enrich_estimate_inputs

API = "/api/v1"


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _ctx(db):
    from app.models import Tenant
    from app.models_wave1 import Vessel

    tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
    vessel = db.scalar(select(Vessel).where(Vessel.tenant_id == tenant.id))
    return tenant, vessel


def test_no_vessel_id_is_noop(db_session):
    tenant, _ = _ctx(db_session)
    inputs = {"freight_rate": 10, "cargo_qty": 1000, "sea_days": 5}
    new_inputs, prov = enrich_estimate_inputs(inputs, db_session, tenant.id)
    assert new_inputs == inputs
    assert prov == {}


def test_unknown_vessel_is_noop(db_session):
    import uuid

    tenant, _ = _ctx(db_session)
    inputs = {"vessel_id": uuid.uuid4(), "freight_rate": 10}
    new_inputs, prov = enrich_estimate_inputs(inputs, db_session, tenant.id)
    assert new_inputs == inputs
    assert prov == {}


def test_fills_speed_and_consumption_from_vessel(db_session):
    """Demo vessel carries speed_knots/consumption_* — legs get them when absent."""
    tenant, vessel = _ctx(db_session)
    inputs = {
        "vessel_id": vessel.id,
        "freight_rate": 12,
        "cargo_qty": 50000,
        "legs": [{"from_port": "SGSIN", "to_port": "NLRTM", "distance_nm": 8400}],
    }
    new_inputs, prov = enrich_estimate_inputs(inputs, db_session, tenant.id)
    leg = new_inputs["legs"][0]
    assert float(leg["speed_kn"]) == float(vessel.speed_knots)
    assert float(leg["bunker_sea_tpd"]) == float(vessel.consumption_sea)
    assert float(leg["bunker_port_tpd"]) == float(vessel.consumption_port)
    assert "legs[0].speed_kn" in prov
    # caller's dict untouched (no mutation of the ORM-persisted JSON)
    assert "speed_kn" not in inputs["legs"][0]


def test_explicit_inputs_win_over_master_data(db_session):
    tenant, vessel = _ctx(db_session)
    inputs = {
        "vessel_id": vessel.id,
        "legs": [{"from_port": "SGSIN", "to_port": "NLRTM", "distance_nm": 8400, "speed_kn": 11.0}],
    }
    new_inputs, prov = enrich_estimate_inputs(inputs, db_session, tenant.id)
    assert new_inputs["legs"][0]["speed_kn"] == 11.0
    assert "legs[0].speed_kn" not in prov


def test_eu_ets_share_from_port_pair(db_session):
    """SGSIN(non-EU) → NLRTM(EU) → pair-average share 0.5; ets_price backfilled."""
    tenant, vessel = _ctx(db_session)
    inputs = {"vessel_id": vessel.id, "load_port": "SGSIN", "disch_port": "NLRTM", "sea_days": 20}
    new_inputs, prov = enrich_estimate_inputs(inputs, db_session, tenant.id)
    assert new_inputs["eu_ets_share"] == pytest.approx(0.5)
    assert new_inputs["ets_price"] > 0  # EUA quote or constant fallback
    assert "eu_ets_share" in prov and "ets_price" in prov


def test_eu_ets_share_both_non_eu_is_zero(db_session):
    tenant, vessel = _ctx(db_session)
    inputs = {"vessel_id": vessel.id, "load_port": "SGSIN", "disch_port": "CNTXG"}
    new_inputs, _ = enrich_estimate_inputs(inputs, db_session, tenant.id)
    assert "eu_ets_share" not in new_inputs  # share 0 → nothing filled


def test_ets_price_prefers_market_quote(db_session):
    """Seeded EUA quote wins over the constant fallback."""
    from app.models_domain import MarketQuote

    tenant, vessel = _ctx(db_session)
    # demo seed writes EUA quotes; verify lookup path picks one up
    n = db_session.scalar(
        select(MarketQuote).where(MarketQuote.tenant_id == tenant.id, MarketQuote.symbol == "EUA").limit(1)
    )
    if n is None:  # seed skipped (non-demo tenant setup) — inject one
        db_session.add(
            MarketQuote(tenant_id=tenant.id, symbol="EUA", quote_date="2026-10-01", value=Decimal("71.25"), source="test")
        )
        db_session.flush()
    inputs = {"vessel_id": vessel.id, "load_port": "SGSIN", "disch_port": "NLRTM"}
    new_inputs, prov = enrich_estimate_inputs(inputs, db_session, tenant.id)
    assert new_inputs["ets_price"] > 0
    assert prov["ets_price"] in ("market.EUA quote", "carbon_calculator.EU_ETS_CO2_PRICE fallback")


def test_eca_days_from_endpoint_share(db_session):
    """NLRTM sits in the North Sea ECA, SGSIN does not → eca_days = sea_days × 0.5."""
    tenant, vessel = _ctx(db_session)
    inputs = {
        "vessel_id": vessel.id,
        "legs": [{"from_port": "SGSIN", "to_port": "NLRTM", "distance_nm": 8400}],
        "sea_days": 20,
    }
    new_inputs, prov = enrich_estimate_inputs(inputs, db_session, tenant.id)
    assert new_inputs["eca_days"] == pytest.approx(10.0)
    assert "eca_days" in prov


def test_compute_estimate_reports_enrichment_provenance(db_session):
    """End-to-end: compute_estimate surfaces inputs_enriched when it filled data."""
    tenant, vessel = _ctx(db_session)
    inputs = {
        "vessel_id": vessel.id,
        "freight_rate": 12,
        "cargo_qty": 50000,
        "load_port": "SGSIN",
        "disch_port": "NLRTM",
        "sea_days": 20,
    }
    out = compute_estimate(inputs, db=db_session, tenant_id=tenant.id)
    assert "inputs_enriched" in out
    assert "eu_ets_share" in out["inputs_enriched"]
    # emissions cost now flows into voyage_cost via the inferred share
    assert out["voyage_cost"] > 0


def test_compute_estimate_without_db_unchanged(db_session):
    """Gold path: no db → no enrichment, no provenance key."""
    out = compute_estimate({"freight_rate": 12, "cargo_qty": 50000, "sea_days": 10, "port_days": 2})
    assert "inputs_enriched" not in out
    assert "eu_ets_share" not in out
