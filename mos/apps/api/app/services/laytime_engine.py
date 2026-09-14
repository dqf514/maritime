"""Laytime calculator (fixed allowance + exclusions + charter-party terms).

Supported inputs (all optional unless noted):
- allowed_hours | cargo_qty + load_rate_per_day, turn_time_hours
- terms: SHINC / SHEX / SSHINC / SSHEX / FHINC / FHEX (suffix "EIU" = even if used).
  Unknown terms keep all time counting and return a warning instead of being
  silently ignored.
- events: [{start, end, excluded?, even_if_used?}] — ISO strings or datetimes.
  `excluded: true` events are skipped entirely (caller-judged interruptions).
  `even_if_used: true` events count in full even under SHEX-type terms.
- port_holidays: ["YYYY-MM-DD", ...] port holiday calendar.
- port_timezone: IANA name (e.g. "Asia/Singapore"). Naive event times are
  interpreted as port local time; aware times are converted to it. Mixing
  naive and aware event times is rejected with a clear error.

Multi-port settlement (reversible / averaging):
- port_events: [{port, events, terms?, allowed_hours?, cargo_qty?,
  load_rate_per_day?, turn_time_hours?, port_holidays?, port_timezone?}] —
  per-port entries override the matching top-level defaults.
- Alternatively, flat `events` may carry a `port` marker; they are grouped by
  port. A single group inherits the top-level allowed hours.
- method "reversible" (also enabled by `reversible: true`): allowances and
  used time of all ports are pooled and settled once — demurrage at one port
  offsets despatch at another. Per-port detail is returned under `ports`.
- method "average": each port is settled independently and the signed
  per-port amounts (demurrage positive, despatch negative) are averaged.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

# term -> (excluded weekday indexes, holidays_excluded); weekday: Mon=0..Sun=6
_TERM_RULES: dict[str, tuple[frozenset[int], bool]] = {
    "SHINC": (frozenset(), False),  # Saturdays, Sundays, holidays included
    "SHEX": (frozenset({5, 6}), True),  # Sat/Sun/holidays excepted (unless used)
    "SSHINC": (frozenset(), False),
    "SSHEX": (frozenset({5, 6}), True),
    "FHINC": (frozenset(), False),  # Fridays/holidays included (Middle East trade)
    "FHEX": (frozenset({4}), True),
}

_US_PER_HOUR = Decimal(3_600_000_000)

_MULTI_ONLY_KEYS = {"events", "port_events", "reversible", "method"}
_ALLOWED_KEYS = ("allowed_hours", "cargo_qty", "load_rate_per_day", "turn_time_hours")


def _delta_hours(start: datetime, end: datetime) -> Decimal:
    """Exact Decimal hours between two datetimes (no float round-trip)."""
    if start.tzinfo is not None and end.tzinfo is not None:
        td = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    else:
        td = end - start
    micros = (
        Decimal(td.days) * Decimal(86_400_000_000)
        + Decimal(td.seconds) * Decimal(1_000_000)
        + Decimal(td.microseconds)
    )
    return micros / _US_PER_HOUR


def _parse_dt(value: Any, port_tz: ZoneInfo | None) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if port_tz is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=port_tz)
    return dt.astimezone(port_tz)


def _parse_holidays(values: Any) -> set[date]:
    out: set[date] = set()
    for v in values or []:
        out.add(v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10]))
    return out


def _term_policy(raw_terms: Any, warnings: list[str]) -> tuple[str, frozenset[int], bool, bool]:
    """Return (normalized_terms, excluded_weekdays, holidays_excluded, even_if_used)."""
    terms = str(raw_terms or "SHINC").upper()
    normalized = " ".join(terms.split())
    even_if_used = "EIU" in normalized or "EVEN IF USED" in normalized
    base = normalized.split()[0] if normalized else "SHINC"
    if base not in _TERM_RULES:
        warnings.append(
            f"Unknown laytime terms '{normalized}': no automatic weekend/holiday "
            "exclusions applied; all event time counts unless marked excluded."
        )
        return normalized, frozenset(), False, even_if_used
    weekdays, hol_excl = _TERM_RULES[base]
    return normalized, weekdays, hol_excl, even_if_used


def _auto_excluded_hours(
    start: datetime,
    end: datetime,
    excluded_weekdays: frozenset[int],
    holidays: set[date],
) -> Decimal:
    """Hours inside [start, end) falling on excepted local days (Sat/Sun/holiday...)."""
    excluded = Decimal("0")
    day = start.date()
    last = end.date()
    while day <= last:
        if day.weekday() in excluded_weekdays or day in holidays:
            day_start = datetime.combine(day, time.min, tzinfo=start.tzinfo)
            day_end = day_start + timedelta(days=1)
            lo = start if start > day_start else day_start
            hi = end if end < day_end else day_end
            if hi > lo:
                excluded += _delta_hours(lo, hi)
        day += timedelta(days=1)
    return excluded


def _allowed_hours(inputs: dict[str, Any]) -> Decimal:
    qty = Decimal(str(inputs.get("cargo_qty") or 0))
    load_rate = Decimal(str(inputs.get("load_rate_per_day") or 0))
    fixed = inputs.get("allowed_hours")
    if fixed is not None:
        allowed = Decimal(str(fixed))
    elif load_rate > 0:
        allowed = (qty / load_rate * Decimal("24")).quantize(Decimal("0.01"))
    else:
        allowed = Decimal("0")
    return allowed + Decimal(str(inputs.get("turn_time_hours") or 0))


def _rates(inputs: dict[str, Any]) -> tuple[Decimal, Decimal]:
    dem_rate = Decimal(str(inputs.get("demurrage_rate_per_day") or 0))
    des_rate = Decimal(str(inputs.get("despatch_rate_per_day") or (dem_rate / 2 if dem_rate else 0)))
    return dem_rate, des_rate


def _settle(balance: Decimal, inputs: dict[str, Any]) -> tuple[str, Decimal]:
    """Demurrage/despatch kind + amount for a signed hour balance."""
    dem_rate, des_rate = _rates(inputs)
    amount = Decimal("0")
    kind = "on_time"
    if balance > 0:
        kind = "demurrage"
        amount = (balance / Decimal("24") * dem_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif balance < 0 and inputs.get("despatch_allowed", True):
        kind = "despatch"
        amount = ((-balance) / Decimal("24") * des_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return kind, amount


def _parse_events(inputs: dict[str, Any], port_tz: ZoneInfo | None) -> list[tuple[datetime, datetime, dict]]:
    raw_events = inputs.get("events") or []
    parsed = [(_parse_dt(ev["start"], port_tz), _parse_dt(ev["end"], port_tz), ev) for ev in raw_events]
    awareness = {dt.tzinfo is not None for s, e, _ in parsed for dt in (s, e)}
    if len(awareness) > 1:
        raise ValueError(
            "Laytime events mix naive and timezone-aware datetimes; make all event "
            "times aware, or pass them naive together with port_timezone."
        )
    return parsed


def _port_tz(inputs: dict[str, Any]) -> tuple[ZoneInfo | None, Any]:
    tz_name = inputs.get("port_timezone")
    port_tz: ZoneInfo | None = None
    if tz_name:
        try:
            port_tz = ZoneInfo(str(tz_name))
        except Exception:  # noqa: BLE001 - unknown IANA name
            raise ValueError(f"Unknown port_timezone '{tz_name}': expected an IANA name like 'Asia/Singapore'") from None
    return port_tz, tz_name


def _compute_single(inputs: dict[str, Any], warnings: list[str], include_events: bool = False) -> dict[str, Any]:
    """
    allowed_hours: fixed or qty/rate.
    used_hours = working time after caller-marked exclusions and term-driven
    (SHEX/SHINC...) weekend/holiday exclusions.
    demurrage if used > allowed; despatch if reverse and used < allowed.
    """
    allowed = _allowed_hours(inputs)
    port_tz, tz_name = _port_tz(inputs)
    holidays = _parse_holidays(inputs.get("port_holidays"))
    terms, excl_weekdays, hol_excl, eiu = _term_policy(inputs.get("terms"), warnings)
    parsed = _parse_events(inputs, port_tz)

    used = Decimal("0")
    auto_excluded_total = Decimal("0")
    event_rows: list[dict[str, Any]] = []
    for s, e, ev in parsed:
        if ev.get("excluded"):
            if include_events:
                event_rows.append(
                    {
                        "start": s.isoformat(),
                        "end": e.isoformat(),
                        "kind": ev.get("kind") or "working",
                        "caller_excluded": True,
                        "gross_hours": float(_delta_hours(s, e).quantize(Decimal("0.01"))) if e >= s else 0.0,
                        "term_excluded_hours": 0.0,
                        "counted_hours": 0.0,
                        "cumulative_hours": float(used.quantize(Decimal("0.01"))),
                        "note": "excluded by caller (interruption not counting)",
                    }
                )
            continue
        if e < s:
            raise ValueError(f"Laytime event end {e.isoformat()} is before start {s.isoformat()}")
        span = _delta_hours(s, e)
        skip_days = eiu or bool(ev.get("even_if_used"))
        if skip_days or (not excl_weekdays and not hol_excl):
            used += span
            auto = Decimal("0")
        else:
            auto = _auto_excluded_hours(s, e, excl_weekdays, holidays if hol_excl else set())
            auto_excluded_total += auto
            used += span - auto
        if include_events:
            event_rows.append(
                {
                    "start": s.isoformat(),
                    "end": e.isoformat(),
                    "kind": ev.get("kind") or "working",
                    "caller_excluded": False,
                    "gross_hours": float(span.quantize(Decimal("0.01"))),
                    "term_excluded_hours": float(auto.quantize(Decimal("0.01"))),
                    "counted_hours": float((span - auto).quantize(Decimal("0.01"))),
                    "cumulative_hours": float(used.quantize(Decimal("0.01"))),
                    "note": "counts in full (even if used)" if skip_days and (excl_weekdays or hol_excl) else "",
                }
            )

    balance = used - allowed
    kind, amount = _settle(balance, inputs)

    result: dict[str, Any] = {
        "terms": terms,
        "allowed_hours": float(allowed),
        "used_hours": float(used.quantize(Decimal("0.01"))),
        "excluded_hours": float(auto_excluded_total.quantize(Decimal("0.01"))),
        "balance_hours": float(balance.quantize(Decimal("0.01"))),
        "result_type": kind,
        "amount": float(amount),
        "currency": inputs.get("currency") or "USD",
        "port_timezone": str(tz_name) if tz_name else None,
        "warnings": warnings,
    }
    if include_events:
        result["events"] = event_rows
    return result


def _port_entries(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized per-port entries: explicit port_events, or flat events grouped by `port`."""
    raw = inputs.get("port_events")
    if raw:
        return [dict(p) for p in raw]
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for ev in inputs.get("events") or []:
        label = str(ev.get("port") or ev.get("port_call") or "PORT")
        if label not in groups:
            groups[label] = {"port": label, "events": []}
            order.append(label)
        groups[label]["events"].append(ev)
    entries = [groups[label] for label in order]
    if len(entries) == 1:
        # A single group is just the whole computation: inherit top-level allowance.
        for key in _ALLOWED_KEYS:
            if key in inputs:
                entries[0][key] = inputs[key]
    return entries


def _merge_port_inputs(inputs: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Top-level values act as defaults; the port entry overrides them."""
    merged = {k: v for k, v in inputs.items() if k not in _MULTI_ONLY_KEYS and k not in _ALLOWED_KEYS}
    merged.update({k: v for k, v in entry.items() if v is not None})
    return merged


def _compute_multi(inputs: dict[str, Any], warnings: list[str], include_events: bool) -> dict[str, Any]:
    method = str(inputs.get("method") or ("reversible" if inputs.get("reversible") else "reversible")).lower()
    if method not in {"reversible", "average"}:
        raise ValueError(f"Unknown multi-port laytime method '{method}': expected 'reversible' or 'average'")
    entries = _port_entries(inputs)
    if not entries:
        raise ValueError("Multi-port laytime requires port_events or events with a port marker")

    top_terms, _, _, _ = _term_policy(inputs.get("terms"), warnings)
    per_port: list[dict[str, Any]] = []
    for entry in entries:
        merged = _merge_port_inputs(inputs, entry)
        sub = _compute_single(merged, [], include_events=include_events)
        label = entry.get("port") or merged.get("port")
        port_out = {
            "port": str(label) if label is not None else None,
            "terms": sub["terms"],
            "allowed_hours": sub["allowed_hours"],
            "used_hours": sub["used_hours"],
            "excluded_hours": sub["excluded_hours"],
            "balance_hours": sub["balance_hours"],
            "result_type": sub["result_type"],
            "amount": sub["amount"],
        }
        if sub["warnings"]:
            port_out["warnings"] = sub["warnings"]
        if include_events:
            port_out["events"] = sub["events"]
        per_port.append(port_out)

    total_allowed = sum(Decimal(str(p["allowed_hours"])) for p in per_port)
    total_used = sum(Decimal(str(p["used_hours"])) for p in per_port)
    total_excluded = sum(Decimal(str(p["excluded_hours"])) for p in per_port)

    if method == "average":
        # 平均法: settle each port on its own, then average the signed amounts
        # (demurrage positive = receivable, despatch negative = payable).
        n = Decimal(len(per_port))
        signed = Decimal("0")
        for p in per_port:
            amt = Decimal(str(p["amount"]))
            if p["result_type"] == "despatch":
                signed -= amt
            else:
                signed += amt
        mean = (signed / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        kind = "on_time"
        if mean > 0:
            kind = "demurrage"
        elif mean < 0:
            kind = "despatch"
        allowed_out = total_allowed / n
        used_out = total_used / n
        balance = used_out - allowed_out
        amount = abs(mean)
    else:
        # 可逆/合并: pool allowances and used time across ports, settle once.
        allowed_out = total_allowed
        used_out = total_used
        balance = total_used - total_allowed
        kind, amount = _settle(balance, inputs)

    result: dict[str, Any] = {
        "terms": top_terms,
        "method": method,
        "allowed_hours": float(allowed_out.quantize(Decimal("0.01"))),
        "used_hours": float(used_out.quantize(Decimal("0.01"))),
        "excluded_hours": float(total_excluded.quantize(Decimal("0.01"))),
        "balance_hours": float(balance.quantize(Decimal("0.01"))),
        "result_type": kind,
        "amount": float(amount),
        "currency": inputs.get("currency") or "USD",
        "port_timezone": str(inputs["port_timezone"]) if inputs.get("port_timezone") else None,
        "ports": per_port,
        "warnings": warnings,
    }
    return result


def _is_multi(inputs: dict[str, Any]) -> bool:
    if inputs.get("port_events"):
        return True
    if inputs.get("reversible"):
        return True
    return str(inputs.get("method") or "").lower() in {"reversible", "average"}


def compute_laytime(inputs: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    if _is_multi(inputs):
        return _compute_multi(inputs, warnings, include_events=False)
    return _compute_single(inputs, warnings)


def compute_laytime_statement(inputs: dict[str, Any]) -> dict[str, Any]:
    """SOF-style event-by-event breakdown (计算书) for a laytime calculation.

    Same settlement as compute_laytime, plus per-event rows: gross hours,
    term-driven excluded hours, counted hours and the cumulative used time.
    Multi-port inputs carry the rows under each port entry.
    """
    warnings: list[str] = []
    if _is_multi(inputs):
        return _compute_multi(inputs, warnings, include_events=True)
    return _compute_single(inputs, warnings, include_events=True)
