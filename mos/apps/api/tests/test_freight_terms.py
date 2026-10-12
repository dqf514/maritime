"""Extra freight terms + scale tables (比例运费表).

Covers: scale tier selection and boundary inclusivity, open-ended top tier,
monotonic/overlap validation (ValueError at the service layer), extra-terms
basis math (per_mt / per_lump / pct_of_freight), applies_when predicates,
combined freight through the estimate engine, and absent-input legacy equality.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

# ---- apply_scale_table: tier selection & boundaries ----


_TABLE = [
    {"qty_from": 0, "qty_to": 30000, "rate": 20.0},
    {"qty_from": 30000, "qty_to": 60000, "rate": 18.5},
    {"qty_from": 60000, "qty_to": None, "rate": 17.0},
]


def test_tier_selection_interior():
    from app.services.freight_terms import apply_scale_table

    assert apply_scale_table(15000, _TABLE) == Decimal("20.0")
    assert apply_scale_table(45000, _TABLE) == Decimal("18.5")
    assert apply_scale_table(75000, _TABLE) == Decimal("17.0")


def test_boundary_qty_from_inclusive():
    from app.services.freight_terms import apply_scale_table

    # qty == qty_from selects that tier (half-open [from, to))
    assert apply_scale_table(0, _TABLE) == Decimal("20.0")
    assert apply_scale_table(30000, _TABLE) == Decimal("18.5")
    assert apply_scale_table(60000, _TABLE) == Decimal("17.0")


def test_boundary_qty_to_exclusive():
    from app.services.freight_terms import apply_scale_table

    # qty just below qty_to stays in the tier; qty == qty_to moves up
    assert apply_scale_table(29999, _TABLE) == Decimal("20.0")
    assert apply_scale_table(59999, _TABLE) == Decimal("18.5")
    # 30000 / 60000 covered above — exclusive upper bound


def test_open_ended_top_tier_unbounded():
    from app.services.freight_terms import apply_scale_table

    assert apply_scale_table(10**9, _TABLE) == Decimal("17.0")


def test_qty_to_omitted_means_unbounded():
    from app.services.freight_terms import apply_scale_table

    rows = [
        {"qty_from": 0, "qty_to": 100, "rate": 5},
        {"qty_from": 100, "rate": 4},  # qty_to omitted
    ]
    assert apply_scale_table(50, rows) == Decimal("5")
    assert apply_scale_table(100, rows) == Decimal("4")
    assert apply_scale_table(10**6, rows) == Decimal("4")


def test_rows_may_be_unsorted_input():
    from app.services.freight_terms import apply_scale_table

    shuffled = list(reversed(_TABLE))
    assert apply_scale_table(15000, shuffled) == Decimal("20.0")
    assert apply_scale_table(75000, shuffled) == Decimal("17.0")


def test_decimal_qty_accepted():
    from app.services.freight_terms import apply_scale_table

    assert apply_scale_table(Decimal("30000.00"), _TABLE) == Decimal("18.5")


def test_return_type_is_decimal():
    from app.services.freight_terms import apply_scale_table

    assert isinstance(apply_scale_table(15000, _TABLE), Decimal)


# ---- apply_scale_table: validation ----


def test_empty_table_rejected():
    from app.services.freight_terms import apply_scale_table

    with pytest.raises(ValueError, match="must not be empty"):
        apply_scale_table(100, [])


def test_overlapping_tiers_rejected():
    from app.services.freight_terms import apply_scale_table

    bad = [
        {"qty_from": 0, "qty_to": 30000, "rate": 20},
        {"qty_from": 20000, "qty_to": 60000, "rate": 18},  # overlaps previous
    ]
    with pytest.raises(ValueError, match="overlapping tiers"):
        apply_scale_table(25000, bad)


def test_qty_to_must_exceed_qty_from():
    from app.services.freight_terms import apply_scale_table

    with pytest.raises(ValueError, match="qty_to must be > qty_from"):
        apply_scale_table(100, [{"qty_from": 500, "qty_to": 500, "rate": 1}])


def test_negative_qty_from_rejected():
    from app.services.freight_terms import apply_scale_table

    with pytest.raises(ValueError, match="qty_from must be >= 0"):
        apply_scale_table(100, [{"qty_from": -1, "qty_to": 10, "rate": 1}])


def test_missing_rate_rejected():
    from app.services.freight_terms import apply_scale_table

    with pytest.raises(ValueError, match="rate is required"):
        apply_scale_table(100, [{"qty_from": 0, "qty_to": 10}])


def test_unbounded_tier_must_be_last():
    from app.services.freight_terms import apply_scale_table

    bad = [
        {"qty_from": 0, "qty_to": None, "rate": 20},
        {"qty_from": 30000, "qty_to": 60000, "rate": 18},
    ]
    with pytest.raises(ValueError, match="open-ended tier"):
        apply_scale_table(100, bad)


def test_qty_below_first_tier_rejected():
    from app.services.freight_terms import apply_scale_table

    table = [{"qty_from": 1000, "qty_to": 2000, "rate": 5}]
    with pytest.raises(ValueError, match="no tier covering"):
        apply_scale_table(500, table)


def test_gap_between_tiers_rejected():
    from app.services.freight_terms import apply_scale_table

    table = [
        {"qty_from": 0, "qty_to": 100, "rate": 5},
        {"qty_from": 200, "qty_to": 300, "rate": 4},  # gap (100, 200)
    ]
    with pytest.raises(ValueError, match="no tier covering"):
        apply_scale_table(150, table)


def test_negative_qty_rejected():
    from app.services.freight_terms import apply_scale_table

    with pytest.raises(ValueError, match="quantity must be >= 0"):
        apply_scale_table(-1, _TABLE)


def test_table_must_be_list():
    from app.services.freight_terms import apply_scale_table

    with pytest.raises(ValueError, match="scale_table must be a list"):
        apply_scale_table(100, {"qty_from": 0, "qty_to": 10, "rate": 1})


# ---- extra freight terms: basis math ----


def test_extra_term_per_mt():
    from app.services.freight_terms import parse_extra_freight_terms

    total, rows = parse_extra_freight_terms(
        {"cargo_qty": 50000, "extra_freight_terms": [{"term": "BAF", "basis": "per_mt", "rate": 2.5}]},
        freight_base=Decimal("0"),
    )
    # 2.5 × 50000 = 125000
    assert total == Decimal("125000.00")
    assert rows == [{"term": "BAF", "basis": "per_mt", "rate": 2.5, "value": 125000.0}]


def test_extra_term_per_lump():
    from app.services.freight_terms import parse_extra_freight_terms

    total, rows = parse_extra_freight_terms(
        {"cargo_qty": 50000, "extra_freight_terms": [{"term": "ISPS", "basis": "per_lump", "rate": 1500}]},
        freight_base=Decimal("0"),
    )
    assert total == Decimal("1500.00")
    assert rows[0]["value"] == 1500.0


def test_extra_term_pct_of_freight():
    from app.services.freight_terms import parse_extra_freight_terms

    total, rows = parse_extra_freight_terms(
        {"cargo_qty": 50000, "extra_freight_terms": [{"term": "War Risk", "basis": "pct_of_freight", "rate": 1.25}]},
        freight_base=Decimal("925000"),
    )
    # 1.25% × 925000 = 11562.5
    assert total == Decimal("11562.50")
    assert rows[0]["value"] == 11562.5


def test_extra_term_pct_basis_aliases():
    from app.services.freight_terms import parse_extra_freight_terms

    total, _ = parse_extra_freight_terms(
        {"extra_freight_terms": [{"term": "X", "basis": "pct", "rate": 2}]},
        freight_base=Decimal("1000"),
    )
    assert total == Decimal("20.00")


def test_extra_terms_negative_rebate_allowed():
    from app.services.freight_terms import parse_extra_freight_terms

    total, _ = parse_extra_freight_terms(
        {"cargo_qty": 1000, "extra_freight_terms": [{"term": "rebate", "basis": "per_mt", "rate": -2}]},
        freight_base=Decimal("0"),
    )
    assert total == Decimal("-2000.00")


def test_extra_terms_multiple_bases_sum():
    from app.services.freight_terms import parse_extra_freight_terms

    total, rows = parse_extra_freight_terms(
        {
            "cargo_qty": 50000,
            "extra_freight_terms": [
                {"term": "BAF", "basis": "per_mt", "rate": 2},
                {"term": "ISPS", "basis": "per_lump", "rate": 1500},
                {"term": "War", "basis": "pct_of_freight", "rate": 1},
            ],
        },
        freight_base=Decimal("100000"),
    )
    # 100000 + 1500 + 1000 (1% of 100000) — non-compounding
    assert total == Decimal("102500.00")
    assert [r["term"] for r in rows] == ["BAF", "ISPS", "War"]


def test_pct_terms_do_not_compound():
    """Each pct_of_freight is a share of the pre-terms base, not of the running total."""
    from app.services.freight_terms import parse_extra_freight_terms

    total, _ = parse_extra_freight_terms(
        {
            "extra_freight_terms": [
                {"term": "A", "basis": "pct_of_freight", "rate": 10},
                {"term": "B", "basis": "pct_of_freight", "rate": 10},
            ]
        },
        freight_base=Decimal("1000"),
    )
    # 100 + 100 = 200 (not 100 + 110)
    assert total == Decimal("200.00")


# ---- applies_when predicates ----


def test_applies_when_equality_match_and_skip():
    from app.services.freight_terms import parse_extra_freight_terms

    total, rows = parse_extra_freight_terms(
        {
            "cargo_qty": 50000,
            "cargo_type": "coal",
            "extra_freight_terms": [
                {"term": "Coal levy", "basis": "per_lump", "rate": 100, "applies_when": {"cargo_type": "coal"}},
                {"term": "Grain levy", "basis": "per_lump", "rate": 999, "applies_when": {"cargo_type": "grain"}},
            ],
        },
        freight_base=Decimal("0"),
    )
    assert total == Decimal("100.00")
    assert [r["term"] for r in rows] == ["Coal levy"]  # non-matching term omitted


def test_applies_when_numeric_bounds():
    from app.services.freight_terms import parse_extra_freight_terms

    total, rows = parse_extra_freight_terms(
        {
            "cargo_qty": 40000,
            "extra_freight_terms": [
                {"term": "big-parcel", "basis": "per_lump", "rate": 50, "applies_when": {"cargo_qty_min": 50000}},
                {"term": "small-parcel", "basis": "per_lump", "rate": 25, "applies_when": {"cargo_qty_max": 50000}},
                {"term": "mid", "basis": "per_lump", "rate": 10, "applies_when": {"cargo_qty_min": 30000, "cargo_qty_max": 50000}},
            ],
        },
        freight_base=Decimal("0"),
    )
    # cargo_qty 40000: big-parcel out (min 50000), small-parcel + mid in
    assert total == Decimal("35.00")
    assert [r["term"] for r in rows] == ["small-parcel", "mid"]


def test_applies_when_bad_type_rejected():
    from app.services.freight_terms import parse_extra_freight_terms

    with pytest.raises(ValueError, match="applies_when must be an object"):
        parse_extra_freight_terms(
            {"extra_freight_terms": [{"term": "X", "basis": "per_lump", "rate": 1, "applies_when": "coal"}]},
            freight_base=Decimal("0"),
        )


# ---- extra freight terms: validation ----


def test_term_missing_rate():
    from app.services.freight_terms import parse_extra_freight_terms

    with pytest.raises(ValueError, match="rate is required"):
        parse_extra_freight_terms(
            {"extra_freight_terms": [{"term": "X", "basis": "per_mt"}]},
            freight_base=Decimal("0"),
        )


def test_term_bad_basis():
    from app.services.freight_terms import parse_extra_freight_terms

    with pytest.raises(ValueError, match="basis must be per_mt"):
        parse_extra_freight_terms(
            {"extra_freight_terms": [{"term": "X", "basis": "per_hour", "rate": 1}]},
            freight_base=Decimal("0"),
        )


def test_term_missing_name():
    from app.services.freight_terms import parse_extra_freight_terms

    with pytest.raises(ValueError, match="term is required"):
        parse_extra_freight_terms(
            {"extra_freight_terms": [{"basis": "per_lump", "rate": 1}]},
            freight_base=Decimal("0"),
        )


def test_terms_must_be_list():
    from app.services.freight_terms import parse_extra_freight_terms

    with pytest.raises(ValueError, match="extra_freight_terms must be a list"):
        parse_extra_freight_terms(
            {"extra_freight_terms": {"term": "X", "basis": "per_lump", "rate": 1}},
            freight_base=Decimal("0"),
        )


# ---- estimate-engine integration ----

# gold_01 economics so TCE deltas isolate the freight add-ons.
_BASE_INPUTS = {
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


def test_absent_extra_terms_legacy_output():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(_BASE_INPUTS)
    assert "extra_freight_terms" not in out
    assert "extra_freight_total" not in out
    assert out["gross_freight"] == 925000.0
    assert out["tce"] == pytest.approx(9953.13, abs=0.02)


def test_empty_extra_terms_list_is_noop():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate({**_BASE_INPUTS, "extra_freight_terms": []})
    assert "extra_freight_terms" not in out
    assert out["gross_freight"] == 925000.0


def test_combined_freight_base_plus_extras():
    """Extras append to gross freight and are commissionable (before commission)."""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            **_BASE_INPUTS,
            "extra_freight_terms": [
                {"term": "BAF", "basis": "per_mt", "rate": 2.5},
                {"term": "ISPS", "basis": "per_lump", "rate": 1500},
            ],
        }
    )
    # base 925000 + 125000 + 1500 = 1051500
    assert out["gross_freight"] == 1051500.0
    assert out["extra_freight_total"] == 126500.0
    # commission 2.5% of 1051500 = 26287.50
    assert out["commission"] == 26287.5
    assert out["net_freight"] == pytest.approx(1025212.5, abs=0.02)


def test_extras_on_differentials_pct_uses_post_diff_base():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 1000,
            "freight_rate": 10,
            "differentials": [{"basis": "lump", "amount": 500}],
            "extra_freight_terms": [{"term": "War", "basis": "pct_of_freight", "rate": 10}],
            "sea_days": 5,
            "port_days": 1,
        }
    )
    # base 10000 + diff 500 = 10500; 10% of 10500 = 1050 → gross 11550
    assert out["gross_freight"] == 11550.0
    assert out["extra_freight_total"] == 1050.0
    assert out["differentials_total"] == 500.0


def test_scale_table_fills_freight_rate():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 45000,
            "sea_days": 30,
            "port_days": 10,
            "scale_table": _TABLE,
        }
    )
    # tier [30000, 60000) → 18.5; gross = 45000 × 18.5 = 832500
    assert out["gross_freight"] == 832500.0
    assert out["freight_basis"] == "rate"
    assert out["scale_table_rate"] == 18.5
    assert out["scale_qty"] == 45000.0


def test_direct_freight_rate_wins_over_scale_table():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 45000,
            "freight_rate": 12.0,
            "sea_days": 5,
            "port_days": 1,
            "scale_table": _TABLE,
        }
    )
    assert out["gross_freight"] == 540000.0  # direct 12.0, not 18.5
    assert out["scale_table_rate"] == 18.5  # provenance still reported


def test_scale_qty_override():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            "cargo_qty": 10000,
            "scale_qty": 75000,
            "sea_days": 5,
            "port_days": 1,
            "scale_table": _TABLE,
        }
    )
    # tier selected on scale_qty 75000 → 17.0; freight on cargo_qty 10000
    assert out["gross_freight"] == 170000.0
    assert out["scale_table_rate"] == 17.0


def test_scale_table_conflicts_with_lump_sum():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="scale_table is per-mt only"):
        compute_estimate(
            {
                "freight_basis": "lump_sum",
                "lump_sum_freight": 100000,
                "sea_days": 5,
                "port_days": 1,
                "scale_table": _TABLE,
            }
        )


def test_scale_table_conflicts_with_worldscale():
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="scale_table is per-mt only"):
        compute_estimate(
            {
                "cargo_qty": 50000,
                "ws_flat": 20,
                "ws_pct": 50,
                "sea_days": 5,
                "port_days": 1,
                "scale_table": _TABLE,
            }
        )


def test_scale_table_overlap_surfaces_value_error():
    """Overlapping tiers raise ValueError at the service layer (API → 422)."""
    from app.services.estimate_engine import compute_estimate

    with pytest.raises(ValueError, match="overlapping tiers"):
        compute_estimate(
            {
                "cargo_qty": 25000,
                "sea_days": 5,
                "port_days": 1,
                "scale_table": [
                    {"qty_from": 0, "qty_to": 30000, "rate": 20},
                    {"qty_from": 20000, "qty_to": 60000, "rate": 18},
                ],
            }
        )


def test_absent_scale_table_legacy_output():
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(_BASE_INPUTS)
    assert "scale_table_rate" not in out
    assert "scale_qty" not in out
    assert out["gross_freight"] == 925000.0


def test_unpriced_and_extras_combined():
    """Both additive features stack without touching TCE."""
    from app.services.estimate_engine import compute_estimate

    out = compute_estimate(
        {
            **_BASE_INPUTS,
            "extra_freight_terms": [{"term": "BAF", "basis": "per_lump", "rate": 1000}],
            "unpriced_components": [
                {
                    "name": "idx",
                    "formula": "offset",
                    "base_value": 500,
                    "offset_value": 0,
                    "basis": "per_lump",
                }
            ],
        }
    )
    assert out["gross_freight"] == 926000.0
    assert out["extra_freight_total"] == 1000.0
    assert out["hire_cost"] == 500.0
    assert out["unpriced_components_total"] == 500.0
    # TCE excludes hire; extras change revenue so TCE moves, hire does not
    assert out["tce"] == pytest.approx((926000 - 926000 * 0.025 - 503750) / 40, abs=0.02)
