"""Phase 3 — Cargo entity + centralized scheduling backend.

Covers:
- cargo CRUD + CGO doc numbering + state transitions (CARGO_TRANSITIONS);
- schedule block CRUD + move/resize conflict detection (409 SCHEDULE_CONFLICT);
- open positions computation (availability gaps);
- cargo book summary (open cargo grouped by laycan month);
- tenant isolation (one tenant can't see another's cargo/blocks).
"""

from __future__ import annotations

from datetime import datetime, timezone

from tests.isolation_helpers import create_tenant

API = "/api/v1"
T0 = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _shift(days: float, hours: float = 0) -> datetime:
    from datetime import timedelta

    return T0 + timedelta(days=days, hours=hours)


def _mk_vessel(client, h, name="P3 Carrier", imo="99990001"):
    r = client.post(f"{API}/masterdata/vessels", headers=h, json={"name": name, "imo": imo})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_cargo(client, h, **fields):
    r = client.post(f"{API}/cargo", headers=h, json=fields)
    assert r.status_code == 200, r.text
    return r.json()


def _mk_block(client, h, vessel_id, title, start: datetime, end: datetime, block_type="voyage"):
    r = client.post(
        f"{API}/scheduling/blocks",
        headers=h,
        json={
            "vessel_id": vessel_id,
            "title": title,
            "start_at": _iso(start),
            "end_at": _iso(end),
            "block_type": block_type,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── Cargo CRUD ───────────────────────────────────────────────────────


def test_cargo_crud_roundtrip(client, auth_headers):
    h = auth_headers
    party = client.post(f"{API}/masterdata/counterparties", headers=h, json={"name": "P3 Charterer"}).json()

    row = _mk_cargo(
        client,
        h,
        cargo_type="bulk",
        commodity="Iron Ore",
        qty=50000,
        qty_unit="mt",
        laycan_from="2026-09-10",
        laycan_to="2026-09-20",
        charterer_id=party["id"],
        freight_basis="per_mt",
        freight_rate=12.5,
    )
    assert row["status"] == "open"
    assert row["cargo_no"].startswith("CGO-"), row["cargo_no"]
    assert row["qty"] == 50000
    assert row["commodity"] == "Iron Ore"

    # list + pagination envelope + filters
    res = client.get(f"{API}/cargo", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert {"items", "total", "limit", "offset"} <= set(body)
    ids = {i["id"] for i in body["items"]}
    assert row["id"] in ids

    # date range filter (laycan overlap semantics)
    hit = client.get(f"{API}/cargo", headers=h, params={"date_from": "2026-09-15", "date_to": "2026-09-30"}).json()
    assert row["id"] in {i["id"] for i in hit["items"]}
    miss = client.get(f"{API}/cargo", headers=h, params={"date_from": "2026-09-21"}).json()
    assert row["id"] not in {i["id"] for i in miss["items"]}

    # charterer filter
    by_party = client.get(f"{API}/cargo", headers=h, params={"charterer_id": party["id"]}).json()
    assert row["id"] in {i["id"] for i in by_party["items"]}

    # detail
    det = client.get(f"{API}/cargo/{row['id']}", headers=h)
    assert det.status_code == 200
    assert det.json()["cargo_no"] == row["cargo_no"]

    # patch
    patch = client.patch(f"{API}/cargo/{row['id']}", headers=h, json={"commodity": "Coal", "qty": 60000})
    assert patch.status_code == 200
    assert patch.json()["commodity"] == "Coal"
    assert patch.json()["qty"] == 60000

    # soft delete → gone from list & detail
    dl = client.delete(f"{API}/cargo/{row['id']}", headers=h)
    assert dl.status_code == 200 and dl.json().get("recycled") is True
    assert client.get(f"{API}/cargo/{row['id']}", headers=h).status_code == 404
    after = client.get(f"{API}/cargo", headers=h).json()
    assert row["id"] not in {i["id"] for i in after["items"]}


def test_cargo_doc_numbers_sequential(client, auth_headers):
    h = auth_headers
    a = _mk_cargo(client, h, commodity="A")
    b = _mk_cargo(client, h, commodity="B")
    assert a["cargo_no"] != b["cargo_no"]
    assert a["cargo_no"].startswith("CGO-") and b["cargo_no"].startswith("CGO-")
    assert int(b["cargo_no"].rsplit("-", 1)[1]) == int(a["cargo_no"].rsplit("-", 1)[1]) + 1


# ── State machine ────────────────────────────────────────────────────


def test_cargo_state_transitions(client, auth_headers):
    h = auth_headers
    row = _mk_cargo(client, h, commodity="Grain", laycan_from="2026-04-01", laycan_to="2026-04-10")
    cid = row["id"]

    for target in ("booked", "nominated", "fixed", "completed"):
        r = client.post(f"{API}/cargo/{cid}/transition", headers=h, params={"target": target})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == target

    # terminal: completed cannot go back or cancel
    assert client.post(f"{API}/cargo/{cid}/transition", headers=h, params={"target": "cancelled"}).status_code == 409
    assert client.post(f"{API}/cargo/{cid}/transition", headers=h, params={"target": "open"}).status_code == 409


def test_cargo_illegal_transition_409_and_cancel_from_early_states(client, auth_headers):
    h = auth_headers
    row = _mk_cargo(client, h, commodity="Bauxite")
    cid = row["id"]

    # illegal jump: open → fixed
    bad = client.post(f"{API}/cargo/{cid}/transition", headers=h, params={"target": "fixed"})
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "INVALID_STATE"

    # cancel allowed from early states (open / booked / nominated)
    early = _mk_cargo(client, h, commodity="Phosphate")
    assert client.post(f"{API}/cargo/{early['id']}/transition", headers=h, params={"target": "booked"}).status_code == 200
    assert (
        client.post(f"{API}/cargo/{early['id']}/transition", headers=h, params={"target": "cancelled"}).status_code == 200
    )
    # cancelled is terminal
    assert (
        client.post(f"{API}/cargo/{early['id']}/transition", headers=h, params={"target": "open"}).status_code == 409
    )

    # fixed is late-state: no cancel path
    late = _mk_cargo(client, h, commodity="Gypsum")
    for t in ("booked", "nominated", "fixed"):
        assert client.post(f"{API}/cargo/{late['id']}/transition", headers=h, params={"target": t}).status_code == 200
    assert client.post(f"{API}/cargo/{late['id']}/transition", headers=h, params={"target": "cancelled"}).status_code == 409


# ── Allocate + cargo book ────────────────────────────────────────────


def test_cargo_allocate_to_voyage(client, auth_headers):
    h = auth_headers
    v = client.post(f"{API}/voyages", headers=h, json={"voyage_no": "P3-CARGO-1"}).json()
    row = _mk_cargo(client, h, commodity="Crude")

    res = client.post(f"{API}/cargo/{row['id']}/allocate", headers=h, json={"voyage_id": v["id"]})
    assert res.status_code == 200, res.text
    assert res.json()["voyage_id"] == v["id"]

    det = client.get(f"{API}/cargo/{row['id']}", headers=h).json()
    assert det["voyage_id"] == v["id"]

    # unknown voyage → 404
    from uuid import uuid4

    bad = client.post(f"{API}/cargo/{row['id']}/allocate", headers=h, json={"voyage_id": str(uuid4())})
    assert bad.status_code == 404


def test_cargo_book_summary_groups_by_laycan_month(client, auth_headers):
    h = auth_headers
    a = _mk_cargo(client, h, commodity="Sep cargo", qty=1000, laycan_from="2026-09-05", laycan_to="2026-09-12")
    b = _mk_cargo(client, h, commodity="Oct cargo", qty=2000, laycan_from="2026-10-02", laycan_to="2026-10-09")
    undated = _mk_cargo(client, h, commodity="No laycan", qty=500)
    fixed = _mk_cargo(client, h, commodity="Fixed cargo", qty=3000, laycan_from="2026-09-20", laycan_to="2026-09-25")
    for t in ("booked", "nominated", "fixed"):
        assert client.post(f"{API}/cargo/{fixed['id']}/transition", headers=h, params={"target": t}).status_code == 200

    book = client.get(f"{API}/cargo/book", headers=h)
    assert book.status_code == 200, book.text
    body = book.json()
    months = {m["month"]: m for m in body["months"]}
    assert "2026-09" in months and "2026-10" in months and "unknown" in months
    assert months["2026-09"]["cargo_count"] == 1
    assert months["2026-09"]["total_qty"] == 1000
    assert months["2026-10"]["cargo_count"] == 1
    assert months["unknown"]["cargo_count"] == 1
    # fixed cargo is no longer "open" → excluded from the book
    assert fixed["id"] not in {c["id"] for m in body["months"] for c in m["cargoes"]}
    assert body["total_open"] == 3

    # scheduling view shares the same open-cargo semantics
    sb = client.get(f"{API}/scheduling/cargo-book", headers=h).json()
    assert {i["id"] for i in sb["items"]} == {a["id"], b["id"], undated["id"]}


# ── Schedule blocks ──────────────────────────────────────────────────


def test_schedule_block_crud_and_conflict_flag(client, auth_headers):
    h = auth_headers
    vessel = _mk_vessel(client, h, "P3 Bulk", "99990002")

    a = _mk_block(client, h, vessel["id"], "Voyage A", _shift(0), _shift(2))
    assert a["hard_conflict"] is False

    # overlapping create is allowed but flagged on both sides
    b = _mk_block(client, h, vessel["id"], "Voyage B", _shift(1), _shift(3))
    assert b["hard_conflict"] is True

    conflicts = client.get(f"{API}/scheduling/conflicts", headers=h).json()
    by_id = {i["id"]: i for i in conflicts["items"]}
    assert a["id"] in by_id and b["id"] in by_id
    assert a["id"] in by_id[b["id"]]["conflicts_with"]
    assert b["id"] in by_id[a["id"]]["conflicts_with"]

    # list with filters (envelope protocol)
    res = client.get(f"{API}/scheduling/blocks", headers=h, params={"vessel_id": vessel["id"]}).json()
    assert res["total"] == 2
    by_type = client.get(f"{API}/scheduling/blocks", headers=h, params={"block_type": "repair"}).json()
    assert by_type["total"] == 0

    # patch metadata
    p = client.patch(f"{API}/scheduling/blocks/{b['id']}", headers=h, json={"title": "Voyage B2", "block_type": "offhire"})
    assert p.status_code == 200
    assert p.json()["title"] == "Voyage B2" and p.json()["block_type"] == "offhire"

    # delete clears the counterpart's flag via recompute
    assert client.delete(f"{API}/scheduling/blocks/{b['id']}", headers=h).status_code == 200
    a_after = client.get(f"{API}/scheduling/blocks", headers=h, params={"vessel_id": vessel["id"]}).json()
    assert a_after["total"] == 1
    assert a_after["items"][0]["hard_conflict"] is False
    assert client.get(f"{API}/scheduling/conflicts", headers=h).json()["total"] == 0


def test_schedule_move_resize_conflict_409(client, auth_headers):
    h = auth_headers
    vessel = _mk_vessel(client, h, "P3 Tanker", "99990003")

    a = _mk_block(client, h, vessel["id"], "Dock", _shift(0), _shift(2), block_type="repair")
    b = _mk_block(client, h, vessel["id"], "Trip", _shift(4), _shift(6))

    # move onto A → hard conflict 409
    bad = client.post(
        f"{API}/scheduling/blocks/{b['id']}/move",
        headers=h,
        json={"start_at": _iso(_shift(1)), "end_at": _iso(_shift(3))},
    )
    assert bad.status_code == 409, bad.text
    assert bad.json()["detail"]["code"] == "SCHEDULE_CONFLICT"
    assert a["id"] in bad.json()["detail"]["conflicts"]
    # unchanged
    assert client.get(f"{API}/scheduling/blocks", headers=h, params={"vessel_id": vessel["id"]}).json()["items"][
        0
    ]["title"] == "Dock"

    # move into a free window → 200
    ok = client.post(
        f"{API}/scheduling/blocks/{b['id']}/move",
        headers=h,
        json={"start_at": _iso(_shift(7)), "end_at": _iso(_shift(9))},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["start_at"] == _iso(_shift(7))

    # resize onto A → 409; resize within free space → 200
    bad_r = client.post(
        f"{API}/scheduling/blocks/{b['id']}/resize",
        headers=h,
        json={"start_at": _iso(_shift(1)), "end_at": None},
    )
    assert bad_r.status_code == 409
    assert bad_r.json()["detail"]["code"] == "SCHEDULE_CONFLICT"

    ok_r = client.post(
        f"{API}/scheduling/blocks/{b['id']}/resize",
        headers=h,
        json={"end_at": _iso(_shift(10))},
    )
    assert ok_r.status_code == 200
    assert ok_r.json()["end_at"] == _iso(_shift(10))

    # bad window
    inv = client.post(
        f"{API}/scheduling/blocks/{b['id']}/move",
        headers=h,
        json={"start_at": _iso(_shift(5)), "end_at": _iso(_shift(5))},
    )
    assert inv.status_code == 400


def test_open_positions_computation(client, auth_headers):
    h = auth_headers
    busy = _mk_vessel(client, h, "P3 Busy", "99990004")
    idle = _mk_vessel(client, h, "P3 Idle", "99990005")

    # busy vessel: occupied days 1→3 of a 0→7 window → gaps [0,1] and [3,7]
    _mk_block(client, h, busy["id"], "Trip", _shift(1), _shift(3))

    res = client.get(
        f"{API}/scheduling/open-positions",
        headers=h,
        params={"date_from": _iso(T0), "date_to": _iso(_shift(7))},
    )
    assert res.status_code == 200, res.text
    items = {i["vessel_id"]: i for i in res.json()["items"]}

    assert busy["id"] in items and idle["id"] in items
    gaps = items[busy["id"]]["gaps"]
    assert len(gaps) == 2
    assert gaps[0]["start"] == _iso(T0) and gaps[0]["end"] == _iso(_shift(1))
    assert gaps[1]["start"] == _iso(_shift(3)) and gaps[1]["end"] == _iso(_shift(7))
    assert items[busy["id"]]["open_days"] == 5.0

    # fully idle vessel: one open gap across the whole window
    assert len(items[idle["id"]]["gaps"]) == 1
    assert items[idle["id"]]["open_days"] == 7.0

    # a vessel busy for the entire window is not offered as an open position
    full = _mk_vessel(client, h, "P3 Full", "99990006")
    _mk_block(client, h, full["id"], "Long trip", T0, _shift(7))
    res2 = client.get(
        f"{API}/scheduling/open-positions",
        headers=h,
        params={"date_from": _iso(T0), "date_to": _iso(_shift(7))},
    )
    assert full["id"] not in {i["vessel_id"] for i in res2.json()["items"]}


def test_berth_windows_view(client, auth_headers):
    h = auth_headers
    port = client.post(
        f"{API}/masterdata/ports", headers=h, json={"name": "P3 Test Port", "unlocode": "XXP3"}
    ).json()
    r = client.post(
        f"{API}/berths",
        headers=h,
        json={
            "berth_name": "P3 Berth 1",
            "start_at": _iso(_shift(2)),
            "end_at": _iso(_shift(3)),
            "port_id": port["id"],
        },
    )
    assert r.status_code == 200, r.text

    res = client.get(f"{API}/scheduling/berth-windows", headers=h)
    assert res.status_code == 200, res.text
    names = [i["berth_name"] for i in res.json()["items"]]
    assert "P3 Berth 1" in names

    filtered = client.get(f"{API}/scheduling/berth-windows", headers=h, params={"port_id": port["id"]}).json()
    assert [i["berth_name"] for i in filtered["items"]] == ["P3 Berth 1"]
    assert filtered["items"][0]["start_at"] == _iso(_shift(2))


# ── Tenant isolation ─────────────────────────────────────────────────


def test_tenant_isolation_cargo_and_blocks(client, auth_headers, db_engine):
    ha = auth_headers
    _, hb = create_tenant(client, code="p3globex", name="P3 Globex", admin_email="Admin@P3Globex.example.com")

    # tenant B resources
    b_cargo = _mk_cargo(client, hb, commodity="B's cargo", laycan_from="2026-05-01", laycan_to="2026-05-10")
    b_vessel = _mk_vessel(client, hb, "P3 B Vessel", "99990007")
    b_block = _mk_block(client, hb, b_vessel["id"], "B's trip", _shift(0), _shift(2))

    # tenant A resources
    a_cargo = _mk_cargo(client, ha, commodity="A's cargo")
    a_vessel = _mk_vessel(client, ha, "P3 A Vessel", "99990008")
    a_block = _mk_block(client, ha, a_vessel["id"], "A's trip", _shift(0), _shift(2))

    # —— reads: A cannot see B's rows; B cannot see A's ——
    assert client.get(f"{API}/cargo/{b_cargo['id']}", headers=ha).status_code == 404
    assert client.get(f"{API}/cargo/{a_cargo['id']}", headers=hb).status_code == 404

    a_list = {i["id"] for i in client.get(f"{API}/cargo", headers=ha).json()["items"]}
    b_list = {i["id"] for i in client.get(f"{API}/cargo", headers=hb).json()["items"]}
    assert a_cargo["id"] in a_list and b_cargo["id"] not in a_list
    assert b_cargo["id"] in b_list and a_cargo["id"] not in b_list

    a_blocks = {i["id"] for i in client.get(f"{API}/scheduling/blocks", headers=ha).json()["items"]}
    assert a_block["id"] in a_blocks and b_block["id"] not in a_blocks

    # —— writes: cross-tenant mutation blocked, data untouched ——
    assert client.patch(f"{API}/cargo/{b_cargo['id']}", headers=ha, json={"commodity": "hijack"}).status_code == 404
    assert client.delete(f"{API}/cargo/{b_cargo['id']}", headers=ha).status_code == 404
    assert (
        client.post(f"{API}/cargo/{b_cargo['id']}/transition", headers=ha, params={"target": "booked"}).status_code == 404
    )
    v_a = client.post(f"{API}/voyages", headers=ha, json={"voyage_no": "P3-ISO-A"}).json()
    assert (
        client.post(f"{API}/cargo/{b_cargo['id']}/allocate", headers=ha, json={"voyage_id": v_a["id"]}).status_code
        == 404
    )

    # B's cargo untouched (still open, commodity intact)
    untouched = client.get(f"{API}/cargo/{b_cargo['id']}", headers=hb).json()
    assert untouched["commodity"] == "B's cargo" and untouched["status"] == "open" and untouched["voyage_id"] is None

    # schedule blocks: A cannot move/delete B's block
    assert (
        client.post(
            f"{API}/scheduling/blocks/{b_block['id']}/move",
            headers=ha,
            json={"start_at": _iso(_shift(5)), "end_at": _iso(_shift(6))},
        ).status_code
        == 404
    )
    assert client.post(
        f"{API}/scheduling/blocks/{b_block['id']}/resize", headers=ha, json={"end_at": _iso(_shift(6))}
    ).status_code == 404
    assert client.delete(f"{API}/scheduling/blocks/{b_block['id']}", headers=ha).status_code == 404
    assert client.patch(f"{API}/scheduling/blocks/{b_block['id']}", headers=ha, json={"title": "hijack"}).status_code == 404

    # B's block still in place with original window
    b_after = client.get(f"{API}/scheduling/blocks", headers=hb, params={"vessel_id": b_vessel["id"]}).json()
    assert b_after["total"] == 1
    assert b_after["items"][0]["title"] == "B's trip"
    assert b_after["items"][0]["start_at"] == _iso(_shift(0))

    # cross-tenant conflict views stay scoped: A's conflicts never mention B's block
    conflicts = {i["id"] for i in client.get(f"{API}/scheduling/conflicts", headers=ha).json()["items"]}
    assert b_block["id"] not in conflicts

    # cross-tenant references on create are rejected (IDOR gate)
    bad_ref = client.post(
        f"{API}/scheduling/blocks",
        headers=ha,
        json={
            "vessel_id": b_vessel["id"],
            "title": "A onto B vessel",
            "start_at": _iso(_shift(10)),
            "end_at": _iso(_shift(11)),
        },
    )
    assert bad_ref.status_code == 404
    bad_cargo = client.post(f"{API}/cargo", headers=ha, json={"charterer_id": b_cargo["id"], "commodity": "x"})
    # charterer_id points at a cargo id → not a counterparty → 404
    assert bad_cargo.status_code == 404
