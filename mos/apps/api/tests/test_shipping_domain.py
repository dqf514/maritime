"""Shipping-domain unit tests: laytime terms/holidays/timezone, estimate
validation + sensitivity modes, and the DDS §5.4 state machines."""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.services.estimate_engine import compute_estimate, sensitivity
from app.services.laytime_engine import compute_laytime
from app.services.state_machine import (
    CONNECTOR_TRANSITIONS,
    EMAIL_PARSE_TRANSITIONS,
    INVOICE_TRANSITIONS,
    LICENSE_TRANSITIONS,
    transition,
)

# 2026-09-01 is a Tuesday: Sep 4=Fri, 5=Sat, 6=Sun, 7=Mon, 8=Tue, 9=Wed.


def test_shex_excludes_weekend():
    out = compute_laytime(
        {
            "allowed_hours": 40,
            "demurrage_rate_per_day": 24000,
            "terms": "SHEX",
            "events": [{"start": "2026-09-04T08:00:00", "end": "2026-09-08T08:00:00"}],
        }
    )
    assert out["used_hours"] == 48.0
    assert out["excluded_hours"] == 48.0
    assert out["result_type"] == "demurrage"
    assert out["amount"] == 8000.0
    assert out["warnings"] == []


def test_shinc_counts_port_holiday():
    out = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 24000,
            "terms": "SHINC",
            "port_holidays": ["2026-09-08"],
            "events": [{"start": "2026-09-07T00:00:00", "end": "2026-09-09T00:00:00"}],
        }
    )
    assert out["used_hours"] == 48.0
    assert out["amount"] == 24000.0


def test_shex_excludes_port_holiday():
    out = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 24000,
            "terms": "SHEX",
            "port_holidays": ["2026-09-08"],
            "events": [{"start": "2026-09-08T00:00:00", "end": "2026-09-09T00:00:00"}],
        }
    )
    assert out["used_hours"] == 0.0
    assert out["excluded_hours"] == 24.0
    assert out["result_type"] == "despatch"


def test_even_if_used_overrides_exclusion():
    out = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 24000,
            "terms": "SHEX",
            "port_holidays": ["2026-09-08"],
            "events": [
                {"start": "2026-09-08T00:00:00", "end": "2026-09-09T00:00:00", "even_if_used": True}
            ],
        }
    )
    assert out["used_hours"] == 24.0
    assert out["result_type"] == "on_time"


def test_eiu_suffix_overrides_exclusion():
    out = compute_laytime(
        {
            "allowed_hours": 96,
            "demurrage_rate_per_day": 24000,
            "terms": "SHEX EIU",
            "events": [{"start": "2026-09-04T08:00:00", "end": "2026-09-08T08:00:00"}],
        }
    )
    assert out["used_hours"] == 96.0
    assert out["excluded_hours"] == 0.0


def test_unknown_terms_warn_not_silent():
    out = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 24000,
            "terms": "WWD",
            "events": [{"start": "2026-09-05T00:00:00", "end": "2026-09-06T00:00:00"}],
        }
    )
    assert out["warnings"], "unknown terms must produce a warning"
    assert out["used_hours"] == 24.0  # Saturday counts: no auto exclusion


def test_caller_excluded_marker_still_wins():
    out = compute_laytime(
        {
            "allowed_hours": 72,
            "turn_time_hours": 6,
            "demurrage_rate_per_day": 24000,
            "terms": "SHINC",
            "events": [
                {"start": "2026-09-01T08:00:00", "end": "2026-09-04T20:00:00", "excluded": False},
                {"start": "2026-09-02T00:00:00", "end": "2026-09-02T12:00:00", "excluded": True},
            ],
        }
    )
    assert out["used_hours"] == 84.0
    assert out["amount"] == 6000.0


def test_naive_events_localized_with_port_timezone():
    out = compute_laytime(
        {
            "allowed_hours": 96,
            "terms": "SHINC",
            "port_timezone": "Asia/Singapore",
            "events": [{"start": "2026-09-07T08:00:00", "end": "2026-09-09T08:00:00"}],
        }
    )
    assert out["used_hours"] == 48.0
    assert out["port_timezone"] == "Asia/Singapore"


def test_aware_events_convert_across_day_boundary():
    out = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 24000,
            "terms": "SSHEX",
            "port_timezone": "Asia/Shanghai",
            "events": [
                {"start": "2026-09-04T17:00:00+00:00", "end": "2026-09-05T17:00:00+00:00"}
            ],
        }
    )
    # Sat 01:00 -> Sun 01:00 Shanghai local: entirely excepted
    assert out["used_hours"] == 0.0
    assert out["result_type"] == "despatch"
    assert out["amount"] == 12000.0


def test_mixed_naive_aware_raises_clear_error():
    with pytest.raises(ValueError, match="naive and timezone-aware"):
        compute_laytime(
            {
                "allowed_hours": 24,
                "events": [
                    {"start": "2026-09-07T00:00:00", "end": "2026-09-07T12:00:00"},
                    {"start": "2026-09-07T12:00:00+08:00", "end": "2026-09-08T00:00:00+08:00"},
                ],
            }
        )


def test_bad_port_timezone_raises():
    with pytest.raises(ValueError, match="port_timezone"):
        compute_laytime(
            {
                "allowed_hours": 24,
                "port_timezone": "Mars/Olympus",
                "events": [{"start": "2026-09-07T00:00:00", "end": "2026-09-07T12:00:00"}],
            }
        )


def test_hours_are_decimal_exact():
    # 1h30m must be exactly 1.5 hours, not a float approximation.
    out = compute_laytime(
        {
            "allowed_hours": 0,
            "demurrage_rate_per_day": 24000,
            "events": [
                {
                    "start": datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc),
                    "end": datetime(2026, 9, 7, 1, 30, tzinfo=timezone.utc),
                }
            ],
        }
    )
    assert out["used_hours"] == 1.5


def test_estimate_zero_days_raises():
    with pytest.raises(ValueError, match="total_days must be > 0"):
        compute_estimate({"lump_sum_freight": 100000, "sea_days": 0, "port_days": 0})


def test_sensitivity_pct_mode_backward_compatible():
    base = {
        "cargo_qty": 50000,
        "freight_rate": 18.5,
        "commission_pct": 2.5,
        "sea_days": 30,
        "port_days": 10,
        "port_costs": 80000,
    }
    rows = sensitivity(base, "freight_rate", [0.0, 0.1])
    assert rows[0]["delta_pct"] == 0.0
    assert rows[0]["tce"] == compute_estimate(base)["tce"]
    plus10 = compute_estimate({**base, "freight_rate": 18.5 * 1.1})
    assert rows[1]["tce"] == plus10["tce"]


def test_sensitivity_abs_mode():
    base = {
        "cargo_qty": 50000,
        "freight_rate": 18.5,
        "sea_days": 30,
        "port_days": 10,
        "bunker_sea_tpd": 28,
        "bunker_price": 450,
        "port_costs": 80000,
    }
    rows = sensitivity(base, "bunker_price", [-50, 0, 50], mode="abs")
    assert rows[1]["tce"] == compute_estimate(base)["tce"]
    cheaper = compute_estimate({**base, "bunker_price": 400})
    dearer = compute_estimate({**base, "bunker_price": 500})
    assert rows[0]["tce"] == cheaper["tce"]
    assert rows[2]["tce"] == dearer["tce"]
    assert rows[0]["delta_abs"] == -50
    with pytest.raises(ValueError, match="mode"):
        sensitivity(base, "bunker_price", [0.1], mode="bogus")


def test_email_parse_state_machine():
    assert transition("email.parse", "pending", "review", EMAIL_PARSE_TRANSITIONS) == "review"
    assert transition("email.parse", "review", "parsed", EMAIL_PARSE_TRANSITIONS) == "parsed"
    assert transition("email.parse", "failed", "pending", EMAIL_PARSE_TRANSITIONS) == "pending"
    with pytest.raises(HTTPException) as exc:
        transition("email.parse", "archived", "pending", EMAIL_PARSE_TRANSITIONS)
    assert exc.value.status_code == 409


def test_license_state_machine():
    assert transition("license", "inactive", "active", LICENSE_TRANSITIONS) == "active"
    assert transition("license", "active", "suspended", LICENSE_TRANSITIONS) == "suspended"
    assert transition("license", "expired", "active", LICENSE_TRANSITIONS) == "active"
    with pytest.raises(HTTPException):
        transition("license", "inactive", "expired", LICENSE_TRANSITIONS)


def test_connector_state_machine():
    assert transition("connector", "draft", "active", CONNECTOR_TRANSITIONS) == "active"
    assert transition("connector", "active", "error", CONNECTOR_TRANSITIONS) == "error"
    assert transition("connector", "error", "active", CONNECTOR_TRANSITIONS) == "active"
    with pytest.raises(HTTPException):
        transition("connector", "deleted", "active", CONNECTOR_TRANSITIONS)


def test_invoice_partially_paid_void_allowed_but_documented():
    # Allowed at state-machine level; the finance router must pair it with a
    # credit note / refund (see comment on INVOICE_TRANSITIONS).
    assert transition("invoice", "partially_paid", "void", INVOICE_TRANSITIONS) == "void"
