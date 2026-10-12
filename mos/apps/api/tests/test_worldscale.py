"""Track C1 — Worldscale freight modes in the TCE estimate engine.

Covers: legacy auto path unchanged, explicit per_mt / lump_sum / ws_differential,
ws_rate_pct alias, freight differentials (per_mt / per_measure / lump), and
validation errors for missing inputs. Gold fixtures gold_07..gold_09 are the
contract — expectations are hand-computed (see each fixture's note).
"""

import json
from pathlib import Path

import pytest

FIXTURES_TCE = Path(__file__).resolve().parents[3] / "fixtures" / "calc" / "tce"


def _gold(name: str) -> dict:
    return json.loads((FIXTURES_TCE / f"{name}.json").read_text(encoding="utf-8"))


# Shared voyage economics (gold_01 costs) so TCE deltas isolate the freight mode.
_BASE = {
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


# ---- legacy auto path unchanged ----


def test_legacy_auto_path_byte_identical():
    """No new inputs → same numbers AND same result keys as before Track C1."""
    from app.services.estimate_engine import compute_estimate

    for name, tce in (("gold_01", 9953.13), ("gold_02", 9664.06)):
        out = compute_estimate(_gold(name)["inputs"])
        assert out["tce"] == pytest.approx(tce, abs=0.02), name
        assert "differentials" not in out
        assert "differentials_total" not in out

    # auto lump sum
    out = compute_estimate({"lump_sum_freight": 100000, "sea_days": 8, "port_days": 2, "port_costs": 20000})
    assert out["freight_basis"] == "lump_sum"
    assert out["gross_freight"] == 100000.0
    assert out["tce"] == 8000.0

    # auto worldscale
    out = compute_estimate({"cargo_qty": 50000, "ws_flat": 20, "ws_pct": 50, "sea_days": 8, "port_days": 2})
    assert out["freight_basis"] == "worldscale"
    assert out["gross_freight"] == 500000.0

    # auto per-mt
    out = compute_estimate({"cargo_qty": 50000, "freight_rate": 18.5, "sea_days": 8, "port_days": 2})
    assert out["freight_basis"] == "rate"
    assert out["gross_freight"] == 925000.0


def test_legacy_auto_detect_precedence_unchanged():
    """lump_sum_freight wins over WS and rate inputs when no explicit basis."""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 50000,
            "freight_rate": 18.5,
            "lump_sum_freight": 100000,
            "ws_flat": 20,
            "ws_pct": 50,
            "sea_days": 8,
            "port_days": 2,
        }
    )
    assert out["freight_basis"] == "lump_sum"
    assert out["gross_freight"] == 100000.0


# ---- per_mt ----


def test_explicit_per_mt():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate({"freight_basis": "per_mt", "cargo_qty": 50000, "freight_rate": 18.5, **_BASE})
    # same economics as gold_01
    assert out["freight_basis"] == "rate"  # legacy output vocabulary
    assert out["gross_freight"] == 925000.0
    assert out["tce"] == pytest.approx(9953.13, abs=0.02)


def test_explicit_per_mt_overrides_auto_lump():
    """Explicit basis beats legacy auto-detect."""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "freight_basis": "per_mt",
            "cargo_qty": 1000,
            "freight_rate": 10,
            "lump_sum_freight": 999999,
            "sea_days": 5,
            "port_days": 1,
        }
    )
    assert out["freight_basis"] == "rate"
    assert out["gross_freight"] == 10000.0


# ---- lump_sum ----


def test_explicit_lump_sum():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate({"freight_basis": "lump_sum", "lump_sum_freight": 1000000, **_BASE})
    assert out["freight_basis"] == "lump_sum"
    assert out["gross_freight"] == 1000000.0
    assert out["tce"] == pytest.approx(11781.25, abs=0.02)


def test_explicit_lump_sum_accepts_freight_rate_as_amount():
    """pricing_engine convention: freight_rate carries the lump amount."""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate({"freight_basis": "lumpsum", "freight_rate": 250000, "sea_days": 5, "port_days": 1})
    assert out["freight_basis"] == "lump_sum"
    assert out["gross_freight"] == 250000.0


# ---- worldscale / ws_differential ----


def test_explicit_worldscale_ws_rate_pct_alias():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {"freight_basis": "worldscale", "cargo_qty": 50000, "ws_flat": 20, "ws_rate_pct": 50, "sea_days": 8, "port_days": 2}
    )
    assert out["freight_basis"] == "worldscale"
    assert out["gross_freight"] == 500000.0  # 50000 × 20 × 50%


def test_ws_differential_all_bases():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "freight_basis": "ws_differential",
            "cargo_qty": 50000,
            "ws_flat": 20,
            "ws_rate_pct": 50,
            "cargo_measure": 20000,
            "differentials": [
                {"basis": "per_mt", "amount": 4, "label": "load port differential"},
                {"basis": "per_measure", "amount": 1.5, "label": "cbm differential"},
                {"basis": "lump", "amount": 25000, "label": "war risk"},
            ],
            **_BASE,
        }
    )
    assert out["freight_basis"] == "ws_differential"
    # WS base 500000 + diffs (200000 + 30000 + 25000)
    assert out["gross_freight"] == 755000.0
    assert out["differentials_total"] == 255000.0
    assert [d["basis"] for d in out["differentials"]] == ["per_mt", "per_measure", "lump"]
    assert out["differentials"][0]["value"] == 200000.0
    assert out["differentials"][1]["value"] == 30000.0
    assert out["differentials"][2]["value"] == 25000.0
    assert out["differentials"][2]["label"] == "war risk"
    assert out["net_freight"] == 736125.0
    assert out["tce"] == pytest.approx(5809.38, abs=0.02)


def test_differentials_on_auto_ws_promote_basis():
    """No explicit basis + differentials on a WS base → ws_differential output."""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 50000,
            "ws_flat": 20,
            "ws_pct": 50,
            "differentials": [{"basis": "lump", "amount": 1000}],
            "sea_days": 8,
            "port_days": 2,
        }
    )
    assert out["freight_basis"] == "ws_differential"
    assert out["gross_freight"] == 501000.0


def test_differential_negative_rebate():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "freight_basis": "ws_differential",
            "cargo_qty": 1000,
            "ws_flat": 10,
            "ws_pct": 100,
            "differentials": [{"basis": "per_mt", "amount": -2}],
            "sea_days": 5,
            "port_days": 1,
        }
    )
    assert out["gross_freight"] == 8000.0  # 10000 − 2×1000
    assert out["differentials_total"] == -2000.0


def test_differentials_on_per_mt_additive():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "freight_basis": "per_mt",
            "cargo_qty": 1000,
            "freight_rate": 10,
            "differentials": [{"basis": "lump", "amount": 500}],
            "sea_days": 5,
            "port_days": 1,
        }
    )
    assert out["freight_basis"] == "rate"
    assert out["gross_freight"] == 10500.0
    assert out["differentials_total"] == 500.0


def test_empty_differentials_list_is_noop():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate({"cargo_qty": 1000, "freight_rate": 10, "differentials": [], "sea_days": 5, "port_days": 1})
    assert "differentials" not in out
    assert "differentials_total" not in out
    assert out["gross_freight"] == 10000.0


# ---- validation errors ----


def test_explicit_per_mt_missing_rate():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="freight_basis=per_mt requires freight_rate"):
        compute_estimate({"freight_basis": "per_mt", "cargo_qty": 1000, "sea_days": 5, "port_days": 1})


def test_explicit_lump_sum_missing_amount():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="freight_basis=lump_sum requires lump_sum_freight"):
        compute_estimate({"freight_basis": "lump_sum", "cargo_qty": 1000, "sea_days": 5, "port_days": 1})


def test_explicit_worldscale_missing_ws_flat():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="ws_flat"):
        compute_estimate({"freight_basis": "worldscale", "cargo_qty": 1000, "ws_pct": 50, "sea_days": 5, "port_days": 1})


def test_explicit_ws_differential_missing_ws_pct():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="ws_pct"):
        compute_estimate(
            {"freight_basis": "ws_differential", "cargo_qty": 1000, "ws_flat": 20, "sea_days": 5, "port_days": 1}
        )


def test_unknown_freight_basis_rejected():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="freight_basis must be"):
        compute_estimate({"freight_basis": "bogus", "cargo_qty": 1000, "freight_rate": 10, "sea_days": 5, "port_days": 1})


def test_per_measure_differential_requires_cargo_measure():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="cargo_measure"):
        compute_estimate(
            {
                "freight_basis": "ws_differential",
                "cargo_qty": 1000,
                "ws_flat": 20,
                "ws_pct": 50,
                "differentials": [{"basis": "per_measure", "amount": 1}],
                "sea_days": 5,
                "port_days": 1,
            }
        )


def test_differential_missing_amount():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="amount is required"):
        compute_estimate(
            {
                "cargo_qty": 1000,
                "freight_rate": 10,
                "differentials": [{"basis": "per_mt"}],
                "sea_days": 5,
                "port_days": 1,
            }
        )


def test_differential_bad_basis():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match=r"differentials\[0\]\.basis"):
        compute_estimate(
            {
                "cargo_qty": 1000,
                "freight_rate": 10,
                "differentials": [{"basis": "per_hour", "amount": 1}],
                "sea_days": 5,
                "port_days": 1,
            }
        )


def test_differentials_must_be_list():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="differentials must be a list"):
        compute_estimate(
            {"cargo_qty": 1000, "freight_rate": 10, "differentials": {"basis": "lump", "amount": 1}, "sea_days": 5, "port_days": 1}
        )


# ---- gold fixtures (contract) ----


@pytest.mark.parametrize("name", ["gold_07", "gold_08", "gold_09"])
def test_gold_new_modes(name):
    from app.services.estimate_engine import compute_estimate

    g = _gold(name)
    out = compute_estimate(g["inputs"])
    for k, expected in g["expect"].items():
        assert abs(float(out[k]) - float(expected)) <= 0.02, f"{name}:{k} expected {expected} got {out[k]}"


def test_gold_tce_suite_all_green():
    """Every fixture in fixtures/calc/tce must satisfy its expect block (SelfCheck contract)."""
    from app.services.estimate_engine import compute_estimate

    failed = []
    for path in sorted(FIXTURES_TCE.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out = compute_estimate(data["inputs"])
        for k, expected in data["expect"].items():
            if abs(float(out.get(k)) - float(expected)) > 0.02:
                failed.append(f"{path.name}:{k} expected {expected} got {out.get(k)}")
    assert not failed, failed
