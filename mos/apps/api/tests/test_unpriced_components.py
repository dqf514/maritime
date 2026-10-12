"""Unpriced (index-linked) component pricing — 指数联动定价.

Covers each formula's math against hand-computed Decimal expectations, window
edge cases, absent-input legacy equality, floor/cap clamps, basis conversion,
tenant-safe market-series lookup, and the gold fixture gold_unpriced_01.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

FIXTURES_TCE = Path(__file__).resolve().parents[3] / "fixtures" / "calc" / "tce"


def _gold(name: str) -> dict:
    return json.loads((FIXTURES_TCE / f"{name}.json").read_text(encoding="utf-8"))


# Shared voyage economics (gold_01) so deltas isolate the unpriced components.
_BASE = {
    "cargo_qty": 50000,
    "freight_rate": 18.5,
    "commission_pct": 2.5,
    "sea_days": 30,
    "port_days": 10,
    "bunker_sea_tpd": 28,
    "bunker_port_tpd": 3.5,
    "bunker_price": 450,
    "port_costs": 80000,
    "canal_costs": 20000,
    "other_costs": 10000,
    "currency": "USD",
}


_OBS = [
    {"date": "2026-01-07", "value": 900},
    {"date": "2026-01-08", "value": 1200},
    {"date": "2026-01-09", "value": 1400},
    {"date": "2026-01-10", "value": 1600},
]


# ---- formula math (hand-computed Decimal expectations) ----


def test_rolling_index_mean():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "BSI roll",
            "formula": "rolling_index",
            "index_name": "BSI",
            "window_days": 3,
            "pricing_date": "2026-01-10",
            "basis": "per_day",
            "observations": _OBS,
        },
        days=Decimal("10"),
    )
    # window (2026-01-07, 2026-01-10] → 1200, 1400, 1600 → mean 1400
    assert row["value"] == 1400.0
    assert row["rate"] == 1400.0
    # per_day × 10 days
    assert row["amount"] == 14000.0
    assert row["formula"] == "rolling_index"
    assert row["window_days"] == 3
    assert row["pricing_date"] == "2026-01-10"


def test_rolling_index_window_edge_excludes_lower_bound():
    """Observation exactly window_days back is OUTSIDE the (pd-wd, pd] window."""
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "roll",
            "formula": "rolling_index",
            "window_days": 2,
            "pricing_date": "2026-01-10",
            "basis": "per_lump",
            "observations": _OBS,
        },
        days=Decimal("1"),
    )
    # window (2026-01-08, 2026-01-10] → 1400, 1600 → mean 1500 (01-08 at
    # exactly pd-2 is excluded, 01-07 at pd-3 also out)
    assert row["value"] == 1500.0


def test_rolling_index_window_includes_pricing_date():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "roll",
            "formula": "rolling_index",
            "window_days": 1,
            "pricing_date": "2026-01-10",
            "basis": "per_lump",
            "observations": _OBS,
        },
        days=Decimal("1"),
    )
    # window (2026-01-09, 2026-01-10] → only 1600
    assert row["value"] == 1600.0


def test_range_max_and_min():
    from app.services.unpriced_components import resolve_component

    common = {
        "name": "band",
        "formula": "range",
        "window_days": 3,
        "pricing_date": "2026-01-10",
        "basis": "per_lump",
        "observations": _OBS,
    }
    row_max = resolve_component({**common, "range_agg": "max"}, days=Decimal("1"))
    row_min = resolve_component({**common, "range_agg": "min"}, days=Decimal("1"))
    assert row_max["value"] == 1600.0
    assert row_min["value"] == 1200.0
    assert row_max["range_agg"] == "max"


def test_range_default_agg_is_max():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "band",
            "formula": "range",
            "window_days": 3,
            "pricing_date": "2026-01-10",
            "basis": "per_lump",
            "observations": _OBS,
        },
        days=Decimal("1"),
    )
    assert row["value"] == 1600.0


def test_level_spot_at_pricing_date():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "spot",
            "formula": "level",
            "index_name": "BSI",
            "pricing_date": "2026-01-09",
            "basis": "per_lump",
            "observations": _OBS,
        },
        days=Decimal("1"),
    )
    # latest date ≤ 2026-01-09 is 01-09 → 1400 (01-10 is after, ignored)
    assert row["value"] == 1400.0


def test_level_ignores_future_observations():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "spot",
            "formula": "level",
            "pricing_date": "2026-01-08",
            "basis": "per_lump",
            "observations": _OBS,
        },
        days=Decimal("1"),
    )
    assert row["value"] == 1200.0


def test_offset_from_base_value():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "adj",
            "formula": "offset",
            "base_value": 1000,
            "offset_value": -250,
            "basis": "per_lump",
        },
        days=Decimal("1"),
    )
    # 1000 + (-250) = 750 — no observations needed when base_value is present
    assert row["value"] == 750.0
    assert row["amount"] == 750.0


def test_offset_from_spot_without_base():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "adj",
            "formula": "offset",
            "offset_value": 100,
            "pricing_date": "2026-01-09",
            "basis": "per_lump",
            "observations": _OBS,
        },
        days=Decimal("1"),
    )
    # spot at 2026-01-09 = 1400, + 100 = 1500
    assert row["value"] == 1500.0


def test_floor_and_cap_clamp():
    from app.services.unpriced_components import resolve_component

    floored = resolve_component(
        {
            "name": "adj",
            "formula": "offset",
            "base_value": 1000,
            "offset_value": -250,
            "floor": 800,
            "basis": "per_lump",
        },
        days=Decimal("1"),
    )
    # 750 clamped up to floor 800
    assert floored["value"] == 800.0

    capped = resolve_component(
        {
            "name": "adj",
            "formula": "offset",
            "base_value": 1000,
            "offset_value": 500,
            "cap": 1200,
            "basis": "per_lump",
        },
        days=Decimal("1"),
    )
    # 1500 clamped down to cap 1200
    assert capped["value"] == 1200.0


def test_factor_scales_rate_not_value():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "adj",
            "formula": "offset",
            "base_value": 1000,
            "offset_value": 0,
            "factor": 0.5,
            "basis": "per_day",
        },
        days=Decimal("10"),
    )
    assert row["value"] == 1000.0  # raw index value unchanged
    assert row["rate"] == 500.0  # × factor
    assert row["amount"] == 5000.0  # × 10 days


def test_per_lump_ignores_days():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "fee",
            "formula": "offset",
            "base_value": 250,
            "offset_value": 0,
            "basis": "per_lump",
        },
        days=Decimal("40"),
    )
    assert row["amount"] == 250.0


def test_total_and_rows_via_evaluate():
    from app.services.unpriced_components import evaluate_unpriced_components

    total, rows = evaluate_unpriced_components(
        [
            {
                "name": "roll",
                "formula": "rolling_index",
                "window_days": 3,
                "pricing_date": "2026-01-10",
                "basis": "per_day",
                "observations": _OBS,
            },
            {
                "name": "adj",
                "formula": "offset",
                "base_value": 1000,
                "offset_value": -250,
                "floor": 800,
                "basis": "per_lump",
            },
        ],
        days=Decimal("40"),
    )
    # 1400 × 40 = 56000; max(750, floor 800) = 800 → 56800
    assert total == Decimal("56800.00")
    assert [r["name"] for r in rows] == ["roll", "adj"]
    assert rows[0]["amount"] == 56000.0
    assert rows[1]["amount"] == 800.0


def test_rounding_half_up_on_amount():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "fee",
            "formula": "offset",
            "base_value": 0.005,
            "offset_value": 0,
            "basis": "per_lump",
        },
        days=Decimal("1"),
    )
    # 0.005 → ROUND_HALF_UP → 0.01
    assert row["amount"] == 0.01


# ---- window / date edge cases ----


def test_pricing_date_defaults_to_latest_observation():
    from app.services.unpriced_components import resolve_component

    row = resolve_component(
        {
            "name": "roll",
            "formula": "rolling_index",
            "window_days": 3,
            "basis": "per_lump",
            "observations": _OBS,
        },
        days=Decimal("1"),
    )
    # max obs date = 2026-01-10 → same window as the explicit case
    assert row["pricing_date"] == "2026-01-10"
    assert row["value"] == 1400.0


def test_pricing_date_from_rate_as_of_default():
    from app.services.unpriced_components import evaluate_unpriced_components

    # default_pricing_date (engine passes inputs.rate_as_of) anchors the window
    total, rows = evaluate_unpriced_components(
        [
            {
                "name": "roll",
                "formula": "rolling_index",
                "window_days": 1,
                "basis": "per_lump",
                "observations": _OBS,
            }
        ],
        days=Decimal("1"),
        default_pricing_date=date(2026, 1, 8),
    )
    # window (2026-01-07, 2026-01-08] → only 1200
    assert rows[0]["value"] == 1200.0


def test_empty_window_raises():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="no observations in window"):
        resolve_component(
            {
                "name": "roll",
                "formula": "rolling_index",
                "window_days": 3,
                "pricing_date": "2026-01-01",
                "basis": "per_lump",
                "observations": _OBS,
            },
            days=Decimal("1"),
        )


def test_level_before_all_observations_raises():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="no observation on or before"):
        resolve_component(
            {
                "name": "spot",
                "formula": "level",
                "pricing_date": "2026-01-01",
                "basis": "per_lump",
                "observations": _OBS,
            },
            days=Decimal("1"),
        )


def test_unsorted_observations_are_accepted_and_sorted():
    from app.services.unpriced_components import resolve_component

    shuffled = list(reversed(_OBS))
    row = resolve_component(
        {
            "name": "roll",
            "formula": "rolling_index",
            "window_days": 3,
            "pricing_date": "2026-01-10",
            "basis": "per_lump",
            "observations": shuffled,
        },
        days=Decimal("1"),
    )
    assert row["value"] == 1400.0


# ---- validation errors ----


def test_missing_name():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="name is required"):
        resolve_component({"formula": "offset", "base_value": 1, "offset_value": 0}, days=Decimal("1"))


def test_unknown_formula():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="formula must be"):
        resolve_component({"name": "x", "formula": "bogus"}, days=Decimal("1"))


def test_offset_requires_offset_value():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="offset requires offset_value"):
        resolve_component({"name": "x", "formula": "offset", "base_value": 1}, days=Decimal("1"))


def test_offset_without_base_needs_observation():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="offset without base_value"):
        resolve_component(
            {"name": "x", "formula": "offset", "offset_value": 5, "pricing_date": "2026-01-01", "observations": _OBS},
            days=Decimal("1"),
        )


def test_bad_window_days():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="window_days must be > 0"):
        resolve_component(
            {
                "name": "x",
                "formula": "rolling_index",
                "window_days": 0,
                "observations": _OBS,
                "pricing_date": "2026-01-10",
            },
            days=Decimal("1"),
        )


def test_bad_basis():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="basis must be"):
        resolve_component(
            {"name": "x", "formula": "offset", "base_value": 1, "offset_value": 0, "basis": "per_hour"},
            days=Decimal("1"),
        )


def test_bad_range_agg():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="range_agg must be"):
        resolve_component(
            {
                "name": "x",
                "formula": "range",
                "range_agg": "median",
                "observations": _OBS,
                "pricing_date": "2026-01-10",
            },
            days=Decimal("1"),
        )


def test_components_must_be_list():
    from app.services.unpriced_components import evaluate_unpriced_components

    with pytest.raises(ValueError, match="unpriced_components must be a list"):
        evaluate_unpriced_components({"formula": "level"}, days=Decimal("1"))


def test_db_series_without_db_raises():
    from app.services.unpriced_components import resolve_component

    with pytest.raises(ValueError, match="no inline observations"):
        resolve_component(
            {"name": "x", "formula": "rolling_index", "index_name": "BSI", "window_days": 3},
            days=Decimal("1"),
        )


# ---- absent-input legacy equality ----


def test_absent_unpriced_components_legacy_output():
    """No unpriced_components key → byte-identical result to the legacy engine."""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(_BASE)
    g = _gold("gold_01")
    for k, expected in g["expect"].items():
        assert abs(float(out[k]) - float(expected)) <= 0.02, k
    assert "unpriced_components" not in out
    assert "unpriced_components_total" not in out


def test_empty_unpriced_components_list_is_noop():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate({**_BASE, "unpriced_components": []})
    assert "unpriced_components" not in out
    assert "unpriced_components_total" not in out
    assert out["hire_cost"] == 0.0
    assert out["tce"] == pytest.approx(9953.13, abs=0.02)


def test_unpriced_components_additive_to_hire():
    """Unpriced total folds into hire_cost; TCE (hire-exclusive) is unchanged."""
    from app.services.estimate_engine import compute_estimate

    base = compute_estimate(_BASE)
    out = compute_estimate({**_BASE, "unpriced_components": _gold("gold_unpriced_01")["inputs"]["unpriced_components"]})
    assert out["tce"] == base["tce"]
    assert out["voyage_cost"] == base["voyage_cost"]
    assert out["gross_freight"] == base["gross_freight"]
    assert out["unpriced_components_total"] == 56800.0
    assert out["hire_cost"] == 56800.0
    assert out["net_result"] == base["net_result"] - 56800.0
    assert len(out["unpriced_components"]) == 2


# ---- tenant-safe market series ----


def test_market_series_is_tenant_scoped(db_engine):
    """MarketQuote lookup only sees the requesting tenant's quotes."""
    from app.models import Tenant
    from app.models_domain import MarketQuote
    from app.services.unpriced_components import resolve_component

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        t1 = Tenant(name="UC Alpha", code="uc-alpha", status="active", profile_tier="S")
        t2 = Tenant(name="UC Beta", code="uc-beta", status="active", profile_tier="S")
        db.add_all([t1, t2])
        db.flush()
        for tid, val in ((t1.id, 1000), (t2.id, 9999)):
            for offset in (0, 1, 2):
                db.add(
                    MarketQuote(
                        tenant_id=tid,
                        symbol="UC_TEST",
                        quote_date=date(2026, 3, 10 - offset),
                        value=Decimal(val) + offset,
                        source="test",
                    )
                )
        db.commit()

        spec = {
            "name": "scoped",
            "formula": "level",
            "index_name": "UC_TEST",
            "pricing_date": "2026-03-10",
            "basis": "per_lump",
        }
        row1 = resolve_component(spec, days=Decimal("1"), db=db, tenant_id=t1.id)
        row2 = resolve_component(spec, days=Decimal("1"), db=db, tenant_id=t2.id)
        assert row1["value"] == 1000.0
        assert row2["value"] == 9999.0

        # wrong-tenant id resolves nothing
        from uuid import uuid4

        with pytest.raises(ValueError, match="no observation"):
            resolve_component(spec, days=Decimal("1"), db=db, tenant_id=uuid4())


# ---- TC contract field + hire statement wiring ----


def _make_tc(client, h, **overrides):
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    parties = parties["items"] if isinstance(parties, dict) else parties
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    vessels = vessels["items"] if isinstance(vessels, dict) else vessels
    charter = client.post(
        "/api/v1/charters", headers=h, json={"charter_type": "tct", "counterparty_id": parties[0]["id"], "hire_per_day": 12000}
    ).json()
    body = {
        "charter_id": charter["id"],
        "contract_type": "tci",
        "contract_style": "time_charter",
        "vessel_id": vessels[0]["id"],
        "counterparty_id": parties[0]["id"],
        "hire_rate": 10000,
        "delivery_date": "2026-01-01",
        "redelivery_date": "2026-03-01",
    }
    body.update(overrides)
    r = client.post("/api/v1/tc/contracts", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_tc_contract_hire_components_roundtrip(client, auth_headers):
    h = auth_headers
    comps = [
        {
            "name": "BSI rolling",
            "formula": "rolling_index",
            "index_name": "BSI",
            "window_days": 3,
            "pricing_date": "2026-01-10",
            "basis": "per_day",
            "observations": _OBS,
        }
    ]
    tc = _make_tc(client, h, hire_components=comps)
    assert tc["hire_components"] == comps

    # patch replaces / clears the list
    r = client.patch(f"/api/v1/tc/contracts/{tc['id']}", headers=h, json={"hire_components": []})
    assert r.status_code == 200, r.text
    assert r.json()["hire_components"] == []


def test_tc_hire_statement_adds_component_lines(client, auth_headers, db_engine):
    from uuid import UUID

    from app.models_time_charter import TimeCharterContract
    from app.services.hire_engine import calculate_hire_statement

    h = auth_headers
    tc = _make_tc(
        client,
        h,
        hire_components=[
            {
                "name": "Index element",
                "formula": "offset",
                "base_value": 500,
                "offset_value": 100,
                "basis": "per_day",
            }
        ],
    )
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        contract = db.get(TimeCharterContract, UUID(tc["id"]))
        # period is fully inside the contract: 2026-01-01..2026-01-11 = 10 days
        calc = calculate_hire_statement(db, contract, date(2026, 1, 1), date(2026, 1, 11))

    # base hire 10000/day × 10 days = 100000; component (500+100) × 10 = 6000
    assert calc["gross_hire"] == Decimal("100000.00")
    assert calc["other_adjustments"] == Decimal("6000.00")
    assert calc["net_hire"] == Decimal("106000.00")
    labels = [ln["label"] for ln in calc["breakdown"]["lines"]]
    assert labels == ["Gross Hire", "Index element", "Net Hire"]
    assert calc["breakdown"]["lines"][1]["amount"] == "6000.00"


def test_tc_hire_statement_without_components_is_legacy(client, auth_headers, db_engine):
    """No hire_components → other_adjustments stays 0 and no extra lines."""
    from uuid import UUID

    from app.models_time_charter import TimeCharterContract
    from app.services.hire_engine import calculate_hire_statement

    tc = _make_tc(client, auth_headers)  # hire_components omitted
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        contract = db.get(TimeCharterContract, UUID(tc["id"]))
        calc = calculate_hire_statement(db, contract, date(2026, 1, 1), date(2026, 1, 11))

    assert calc["other_adjustments"] == Decimal("0")
    assert calc["gross_hire"] == Decimal("100000.00")
    assert calc["net_hire"] == Decimal("100000.00")
    assert [ln["label"] for ln in calc["breakdown"]["lines"]] == ["Gross Hire", "Net Hire"]


def test_gold_unpriced_01():
    from app.services.estimate_engine import compute_estimate

    g = _gold("gold_unpriced_01")
    out = compute_estimate(g["inputs"])
    for k, expected in g["expect"].items():
        assert abs(float(out[k]) - float(expected)) <= 0.02, f"{k}: expected {expected} got {out[k]}"


def test_gold_tce_suite_including_unpriced():
    """Every fixture in fixtures/calc/tce satisfies its expect block (SelfCheck)."""
    from app.services.estimate_engine import compute_estimate

    failed = []
    for path in sorted(FIXTURES_TCE.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out = compute_estimate(data["inputs"])
        for k, expected in data["expect"].items():
            if abs(float(out.get(k)) - float(expected)) > 0.02:
                failed.append(f"{path.name}:{k} expected {expected} got {out.get(k)}")
    assert not failed, failed
