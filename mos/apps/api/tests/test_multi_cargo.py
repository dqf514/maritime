"""Track 1 — multi-cargo (parcels) estimates in the TCE engine.

IMOS parity: an estimate may carry several cargo parcels, each priced on its
own basis (per_mt / lump_sum / worldscale / ws_differential + differentials).
Gold fixtures gold_multi_* are the contract; expectations hand-computed
(see each fixture note in _guide_work/gen_multi_gold.py).
"""

import json
from pathlib import Path

import pytest

from app.services.estimate_engine import compute_estimate

FIXTURES_TCE = Path(__file__).resolve().parents[3] / "fixtures" / "calc" / "tce"

_BASE = {
    "sea_days": 10,
    "port_days": 2,
    "bunker_sea_tpd": 25,
    "bunker_port_tpd": 5,
    "bunker_price": 500,
    "commission_pct": 5,
}


def _gold(name: str) -> dict:
    return json.loads((FIXTURES_TCE / f"{name}.json").read_text(encoding="utf-8"))


def test_gold_multi_fixtures():
    """gold_multi_* fixtures: mixed bases and inheritance are part of the gold suite."""
    fx = _gold("gold_multi_per_mt_lump")
    out = compute_estimate(fx["inputs"])
    assert out["tce"] == pytest.approx(fx["expect"]["tce"], abs=0.02)
    assert out["voyage_cost"] == pytest.approx(fx["expect"]["voyage_cost"], abs=0.02)
    assert out["freight_basis"] == "multi"
    assert out["cargo_count"] == 2
    assert out["parcel_qty_total"] == 80000.0
    assert out["gross_freight"] == 850000.0  # 50000×12 + 250000

    fx = _gold("gold_multi_ws_diff")
    out = compute_estimate(fx["inputs"])
    assert out["tce"] == pytest.approx(fx["expect"]["tce"], abs=0.02)
    # gross = 60000×30 + 20000×18 + diffs(48000 − 30000) = 2,178,000
    assert out["gross_freight"] == 2178000.0
    assert out["freight_basis"] == "multi"

    # all-parcels-same-basis inherits the top-level label (not "multi")
    fx = _gold("gold_multi_inherit_basis")
    out = compute_estimate(fx["inputs"])
    assert out["tce"] == pytest.approx(fx["expect"]["tce"], abs=0.02)
    assert out["gross_freight"] == 1000000.0  # (40000+60000)×10
    assert out["freight_basis"] != "multi"


def test_multi_cargo_results_shape():
    """Per-parcel breakdown rows carry index/qty/basis/base_freight."""
    out = compute_estimate(
        {
            **_BASE,
            "cargoes": [
                {"qty": 50000, "freight_basis": "per_mt", "freight_rate": 12},
                {"qty": 30000, "freight_basis": "lump_sum", "lump_sum_freight": 250000},
            ],
        }
    )
    rows = out["cargoes"]
    assert [r["index"] for r in rows] == [0, 1]
    assert [r["qty"] for r in rows] == [50000.0, 30000.0]
    assert [r["base_freight"] for r in rows] == [600000.0, 250000.0]
    # output vocabulary: per_mt reports as legacy "rate" (see _BASIS_OUTPUT)
    assert [r["freight_basis"] for r in rows] == ["rate", "lump_sum"]
    # optional cargo identity fields pass through when provided
    assert "cargo_type" not in rows[0]


def test_multi_cargo_identity_fields_pass_through():
    out = compute_estimate(
        {
            "sea_days": 5,
            "cargoes": [
                {
                    "qty": 10000,
                    "freight_basis": "per_mt",
                    "freight_rate": 20,
                    "cargo_type": "Coal",
                    "load_port": "CNTXG",
                    "disch_port": "NLRTM",
                }
            ],
        }
    )
    row = out["cargoes"][0]
    assert row["cargo_type"] == "Coal"
    assert row["load_port"] == "CNTXG"
    assert row["disch_port"] == "NLRTM"


def test_multi_cargo_inherits_top_level_rate():
    """Missing per-cargo pricing falls back to top-level freight_rate/basis."""
    out = compute_estimate(
        {**_BASE, "freight_basis": "per_mt", "freight_rate": 10, "cargoes": [{"qty": 40000}, {"qty": 60000}]}
    )
    assert out["gross_freight"] == 1000000.0
    assert [r["base_freight"] for r in out["cargoes"]] == [400000.0, 600000.0]


def test_multi_cargo_qty_fallback_and_commission_base():
    """cargo_qty falls back to parcel total; commissions apply to gross + diffs."""
    out = compute_estimate(
        {
            "sea_days": 4,
            "commission_pct": 5,
            "brokerage_pct": 1,
            "cargoes": [
                {"qty": 30000, "freight_basis": "per_mt", "freight_rate": 10,
                 "differentials": [{"basis": "per_mt", "amount": 1}]},
                {"qty": 20000, "freight_basis": "lump_sum", "lump_sum_freight": 150000},
            ],
        }
    )
    assert out["parcel_qty_total"] == 50000.0
    assert out["gross_freight"] == 480000.0  # 30000×11 + 150000
    assert out["address_commission"] == pytest.approx(24000.0)
    assert out["brokerage"] == pytest.approx(4800.0)


def test_multi_cargo_validation_errors():
    base = {"sea_days": 4, "cargoes": [{"qty": 10000, "freight_basis": "per_mt", "freight_rate": 10}]}
    with pytest.raises(ValueError, match="cargoes must be a list"):
        compute_estimate({**base, "cargoes": {"qty": 1}})
    with pytest.raises(ValueError, match="qty"):
        compute_estimate({**base, "cargoes": [{"qty": 0, "freight_basis": "per_mt", "freight_rate": 10}]})
    with pytest.raises(ValueError, match="scale_table"):
        compute_estimate({**base, "scale_table": [{"qty_from": 0, "qty_to": None, "rate": 10}]})
    # per_mt parcel without a usable rate (no inheritance source)
    with pytest.raises(ValueError, match="freight_rate"):
        compute_estimate({**base, "cargoes": [{"qty": 10000, "freight_basis": "per_mt"}]})


def test_single_cargo_path_unchanged_by_multi_support():
    """Legacy inputs (no cargoes key) take the old path — byte-identical keys."""
    legacy = compute_estimate({**_BASE, "freight_rate": 12, "cargo_qty": 50000})
    assert legacy["gross_freight"] == 600000.0
    assert "cargoes" not in legacy
    assert "cargo_count" not in legacy
    assert "parcel_qty_total" not in legacy
