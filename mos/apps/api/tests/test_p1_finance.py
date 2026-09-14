"""P1 finance/bunker/emissions fixes: reversible & averaging laytime, laytime
finalize lock + SOF statement export, from-SOF laytime generation, P&L line
items + accrual basis, bunker inquiries & index pricing, voyage bunker
allocation, EU ETS eu_share inference."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_domain import Charter, Voyage
from app.models_wave1 import Company, Port


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db):
    return db.scalar(select(Company).limit(1)).tenant_id


def _first_vessel_id(client, h):
    return client.get("/api/v1/masterdata/vessels", headers=h).json()[0]["id"]


def _make_charter(client, h, db_session, **fields):
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "voyage", "vessel_id": _first_vessel_id(client, h)},
    )
    assert cp.status_code == 200, cp.text
    charter = db_session.get(Charter, UUID(cp.json()["id"]))
    for k, v in fields.items():
        setattr(charter, k, v)
    db_session.commit()
    return charter


def _make_voyage(client, h, voyage_no, charter_id=None):
    payload = {"voyage_no": voyage_no}
    if charter_id:
        payload["charter_id"] = str(charter_id)
    r = client.post("/api/v1/voyages", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _make_port(db_session, name, is_eu):
    port = Port(name=name, unlocode=name[:5].upper(), timezone="UTC", is_eu=is_eu)
    db_session.add(port)
    db_session.commit()
    return port.id


# —— 1. Reversible / averaging laytime ——


def test_reversible_laytime_merges_ports():
    from app.services.laytime_engine import compute_laytime

    # load port: 36h used vs 24h allowed -> 12h demurrage; discharge port: 16h
    # used vs 24h allowed -> 8h despatch; pooled -> net 4h demurrage @ 24000/day
    out = compute_laytime(
        {
            "reversible": True,
            "terms": "SHINC",
            "demurrage_rate_per_day": 24000,
            "despatch_rate_per_day": 12000,
            "port_events": [
                {
                    "port": "SGSIN",
                    "allowed_hours": 24,
                    "events": [{"start": "2026-09-01T00:00:00", "end": "2026-09-02T12:00:00"}],
                },
                {
                    "port": "NLRTM",
                    "allowed_hours": 24,
                    "events": [{"start": "2026-09-10T00:00:00", "end": "2026-09-10T16:00:00"}],
                },
            ],
        }
    )
    assert out["method"] == "reversible"
    assert out["result_type"] == "demurrage"
    assert out["amount"] == 4000.0
    assert out["allowed_hours"] == 48.0
    assert out["used_hours"] == 52.0
    ports = {p["port"]: p for p in out["ports"]}
    assert ports["SGSIN"]["balance_hours"] == 12.0
    assert ports["SGSIN"]["result_type"] == "demurrage"
    assert ports["SGSIN"]["amount"] == 12000.0
    assert ports["NLRTM"]["balance_hours"] == -8.0
    assert ports["NLRTM"]["result_type"] == "despatch"
    assert ports["NLRTM"]["amount"] == 4000.0


def test_average_laytime_method():
    from app.services.laytime_engine import compute_laytime

    # averaging: settle each port independently then average the signed amounts:
    # (dem 12000 + (-desp 4000)) / 2 = 4000 demurrage
    out = compute_laytime(
        {
            "method": "average",
            "demurrage_rate_per_day": 24000,
            "despatch_rate_per_day": 12000,
            "port_events": [
                {
                    "port": "A",
                    "allowed_hours": 24,
                    "events": [{"start": "2026-09-01T00:00:00", "end": "2026-09-02T12:00:00"}],
                },
                {
                    "port": "B",
                    "allowed_hours": 24,
                    "events": [{"start": "2026-09-10T00:00:00", "end": "2026-09-10T16:00:00"}],
                },
            ],
        }
    )
    assert out["method"] == "average"
    assert out["result_type"] == "demurrage"
    assert out["amount"] == 4000.0
    assert out["allowed_hours"] == 24.0  # mean allowance
    assert out["used_hours"] == 26.0  # mean used


def test_single_port_laytime_unchanged():
    from app.services.laytime_engine import compute_laytime

    out = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 12000,
            "events": [{"start": "2026-01-01T00:00:00", "end": "2026-01-02T12:00:00", "excluded": False}],
        }
    )
    assert out["result_type"] == "demurrage"
    assert out["amount"] == 6000.0
    assert "ports" not in out


# —— 2. Laytime finalize lock + export ——


def _create_simple_laytime(client, h):
    r = client.post(
        "/api/v1/laytimes",
        headers=h,
        json={
            "inputs": {
                "allowed_hours": 24,
                "demurrage_rate_per_day": 12000,
                "events": [{"start": "2026-01-01T00:00:00", "end": "2026-01-02T12:00:00"}],
            }
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_laytime_finalized_locks_update(client, auth_headers):
    h = auth_headers
    lt_id = _create_simple_laytime(client, h)
    assert client.post(f"/api/v1/laytimes/{lt_id}/calculate", headers=h).status_code == 200
    assert client.post(f"/api/v1/laytimes/{lt_id}/finalize", headers=h).status_code == 200
    upd = client.put(f"/api/v1/laytimes/{lt_id}", headers=h, json={"inputs": {"allowed_hours": 48}})
    assert upd.status_code == 409
    assert upd.json()["detail"]["code"] == "LAYTIME_FINALIZED"


def test_laytime_export_statement(client, auth_headers):
    h = auth_headers
    lt_id = _create_simple_laytime(client, h)
    assert client.post(f"/api/v1/laytimes/{lt_id}/calculate", headers=h).status_code == 200
    exp = client.get(f"/api/v1/laytimes/{lt_id}/export", headers=h)
    assert exp.status_code == 200, exp.text
    body = exp.json()
    assert body["format"] == "LAYTIME_STATEMENT_v1"
    assert body["allowed_hours"] == 24.0
    assert body["used_hours"] == 36.0
    assert body["balance_hours"] == 12.0
    assert body["result_type"] == "demurrage"
    assert body["amount"] == 6000.0
    assert len(body["events"]) == 1
    ev = body["events"][0]
    assert ev["gross_hours"] == 36.0
    assert ev["counted_hours"] == 36.0
    assert ev["term_excluded_hours"] == 0.0
    assert ev["cumulative_hours"] == 36.0


def test_laytime_export_reversible_has_per_port_events(client, auth_headers):
    h = auth_headers
    r = client.post(
        "/api/v1/laytimes",
        headers=h,
        json={
            "inputs": {
                "reversible": True,
                "demurrage_rate_per_day": 24000,
                "despatch_rate_per_day": 12000,
                "port_events": [
                    {
                        "port": "SGSIN",
                        "allowed_hours": 24,
                        "events": [{"start": "2026-09-01T00:00:00", "end": "2026-09-02T12:00:00"}],
                    },
                    {
                        "port": "NLRTM",
                        "allowed_hours": 24,
                        "events": [{"start": "2026-09-10T00:00:00", "end": "2026-09-10T16:00:00"}],
                    },
                ],
            }
        },
    )
    assert r.status_code == 200, r.text
    lt_id = r.json()["id"]
    calc = client.post(f"/api/v1/laytimes/{lt_id}/calculate", headers=h)
    assert calc.json()["results"]["amount"] == 4000.0
    exp = client.get(f"/api/v1/laytimes/{lt_id}/export", headers=h)
    assert exp.status_code == 200
    ports = {p["port"]: p for p in exp.json()["ports"]}
    assert ports["SGSIN"]["events"][0]["counted_hours"] == 36.0
    assert ports["NLRTM"]["events"][0]["counted_hours"] == 16.0


# —— 3. from-SOF laytime generation ——


def test_laytime_from_sof_end_to_end(client, auth_headers, db_session):
    h = auth_headers
    charter = _make_charter(
        client,
        h,
        db_session,
        cargo_qty=Decimal("30000"),
        load_rate_pd=Decimal("10000"),
        demurrage_rate=Decimal("24000"),
        laytime_terms="SHINC",
    )
    vid = _make_voyage(client, h, "P1-SOF-1", charter_id=charter.id)
    pc = client.post("/api/v1/port-calls", headers=h, json={"voyage_id": vid, "seq": 1, "purpose": "load"})
    assert pc.status_code == 200, pc.text
    pc_id = pc.json()["id"]
    for code, at in (
        ("NOR", "2026-09-01T00:00:00+00:00"),
        ("COMMENCED", "2026-09-01T06:00:00+00:00"),
        ("COMPLETED", "2026-09-04T06:00:00+00:00"),
    ):
        r = client.post(
            "/api/v1/sof-events",
            headers=h,
            json={"port_call_id": pc_id, "event_code": code, "event_at": at},
        )
        assert r.status_code == 200, r.text

    r = client.post("/api/v1/laytimes/from-sof", headers=h, json={"port_call_id": pc_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "calculated"
    # allowed = 30000 / 10000 * 24 = 72h; used = 6h waiting + 72h working = 78h
    assert body["inputs"]["allowed_hours"] == 72.0
    assert body["inputs"]["terms"] == "SHINC"
    assert len(body["inputs"]["events"]) == 2
    assert body["results"]["used_hours"] == 78.0
    assert body["results"]["balance_hours"] == 6.0
    assert body["results"]["result_type"] == "demurrage"
    assert body["results"]["amount"] == 6000.0

    listed = client.get("/api/v1/laytimes", headers=h).json()
    assert any(row["id"] == body["id"] for row in listed)


def test_laytime_from_sof_requires_derivable_allowed_hours(client, auth_headers, db_session):
    h = auth_headers
    charter = _make_charter(client, h, db_session)  # no cargo_qty / rates
    vid = _make_voyage(client, h, "P1-SOF-2", charter_id=charter.id)
    pc = client.post("/api/v1/port-calls", headers=h, json={"voyage_id": vid, "seq": 1, "purpose": "discharge"})
    pc_id = pc.json()["id"]
    for code, at in (
        ("COMMENCED", "2026-09-01T06:00:00+00:00"),
        ("COMPLETED", "2026-09-02T06:00:00+00:00"),
    ):
        assert client.post(
            "/api/v1/sof-events",
            headers=h,
            json={"port_call_id": pc_id, "event_code": code, "event_at": at},
        ).status_code == 200
    bad = client.post("/api/v1/laytimes/from-sof", headers=h, json={"port_call_id": pc_id})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "ALLOWED_HOURS_REQUIRED"

    ok = client.post("/api/v1/laytimes/from-sof", headers=h, json={"port_call_id": pc_id, "allowed_hours": 12})
    assert ok.status_code == 200, ok.text
    assert ok.json()["results"]["used_hours"] == 24.0
    assert ok.json()["results"]["balance_hours"] == 12.0


# —— 4. P&L line items + accrual basis ——


def test_pnl_lines_and_accrual_basis(client, auth_headers):
    h = auth_headers
    vid = _make_voyage(client, h, "P1-PNL-1")

    def row_for(basis="actual"):
        rows = client.get(f"/api/v1/analytics/reports/voyage-pnl?basis={basis}", headers=h).json()
        return {r["voyage_id"]: r for r in rows}[vid]

    before = row_for()
    assert set(before["lines_actual"]) >= {
        "revenue",
        "hire",
        "demurrage",
        "port_costs",
        "canal",
        "bunker",
        "commission",
        "emissions",
        "other",
    }

    inv = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"invoice_type": "freight", "voyage_id": vid, "amount": 10000},
    )
    assert inv.status_code == 200, inv.text
    hire = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"invoice_type": "hire", "voyage_id": vid, "amount": 3000},
    )
    assert hire.status_code == 200, hire.text

    after = row_for()
    assert after["lines_actual"]["revenue"] - before["lines_actual"]["revenue"] == pytest.approx(10000.0)
    assert after["lines_actual"]["hire"] - before["lines_actual"]["hire"] == pytest.approx(3000.0)
    assert after["basis"] == "actual"
    assert after["lines"] == after["lines_actual"]
    # legacy keys preserved
    assert after["actual_revenue"] - before["actual_revenue"] == pytest.approx(13000.0)

    for line_type, amount in (("bunker", 500), ("port", 200)):
        r = client.post(
            "/api/v1/finance/accruals",
            headers=h,
            json={"voyage_id": vid, "period_ym": "2026-09", "line_type": line_type, "amount": amount},
        )
        assert r.status_code == 200, r.text

    acc = row_for("accrual")
    assert acc["basis"] == "accrual"
    assert acc["lines_accrual"]["bunker"] == pytest.approx(500.0)
    assert acc["lines_accrual"]["port_costs"] == pytest.approx(200.0)
    # accrual net: cost-side accruals reduce the pnl
    assert acc["accrual_net"] == pytest.approx(-700.0)
    assert acc["accrual_pnl"] == pytest.approx(acc["actual_pnl"] - 700.0)
    assert acc["lines"]["bunker"] == pytest.approx(acc["lines_actual"]["bunker"] + 500.0)
    assert acc["lines"]["revenue"] == pytest.approx(acc["lines_actual"]["revenue"])


# —— 5. Bunker inquiries + index pricing ——


def _make_bunker_order(client, h, **kw):
    payload = {"qty_ordered": 500, "unit_price": 450}
    payload.update(kw)
    r = client.post("/api/v1/bunker-orders", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_bunker_inquiry_accept_writes_back(client, auth_headers):
    h = auth_headers
    order = _make_bunker_order(client, h)
    oid = order["id"]
    inq_a = client.post(f"/api/v1/bunker-orders/{oid}/inquiries", headers=h, json={"supplier": "SupA", "quoted_price": 440})
    assert inq_a.status_code == 200, inq_a.text
    inq_b = client.post(f"/api/v1/bunker-orders/{oid}/inquiries", headers=h, json={"supplier": "SupB", "quoted_price": 430})
    assert inq_b.status_code == 200, inq_b.text

    acc = client.post(f"/api/v1/bunker-inquiries/{inq_b.json()['id']}/accept", headers=h)
    assert acc.status_code == 200, acc.text
    assert acc.json()["status"] == "accepted"
    assert acc.json()["unit_price"] == 430.0
    assert acc.json()["supplier"] == "SupB"

    # re-accept is rejected, and the losing quote can no longer be accepted
    again = client.post(f"/api/v1/bunker-inquiries/{inq_b.json()['id']}/accept", headers=h)
    assert again.status_code == 409
    loser = client.post(f"/api/v1/bunker-inquiries/{inq_a.json()['id']}/accept", headers=h)
    assert loser.status_code == 409

    listed = {b["id"]: b for b in client.get("/api/v1/bunker-orders", headers=h).json()}
    assert listed[oid]["unit_price"] == 430.0


def test_bunker_index_pricing(client, auth_headers):
    h = auth_headers
    q = client.post("/api/v1/market/quotes?symbol=SIN380&value=600", headers=h)
    assert q.status_code == 200, q.text

    r = client.post(
        "/api/v1/bunker-orders",
        headers=h,
        json={"qty_ordered": 100, "index_symbol": "SIN380", "price_differential": 12},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unit_price"] == 612.0
    assert body["pricing"]["source"] == "index"
    assert body["pricing"]["index_symbol"] == "SIN380"
    assert body["pricing"]["quote_value"] == 600.0
    assert body["pricing"]["price_differential"] == 12

    missing = client.post(
        "/api/v1/bunker-orders",
        headers=h,
        json={"qty_ordered": 100, "index_symbol": "NO_SUCH_INDEX"},
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "NO_INDEX_QUOTE"

    no_price = client.post("/api/v1/bunker-orders", headers=h, json={"qty_ordered": 100})
    assert no_price.status_code == 422
    assert no_price.json()["detail"]["code"] == "UNIT_PRICE_REQUIRED"


# —— 6. Voyage bunker allocation ——


def test_bunker_allocation(client, auth_headers):
    h = auth_headers
    vid = _make_voyage(client, h, "P1-BNK-1")
    for at, rob in (("2026-01-01T12:00:00+00:00", 800), ("2026-01-02T12:00:00+00:00", 700)):
        r = client.post(
            "/api/v1/noon-reports",
            headers=h,
            json={"voyage_id": vid, "report_at": at, "rob_fo": rob, "rob_do": 0},
        )
        assert r.status_code == 200, r.text

    order = _make_bunker_order(client, h, voyage_id=vid, qty_ordered=200, unit_price=500)
    oid = order["id"]
    assert client.post(f"/api/v1/bunker-orders/{oid}/transition?target=inquiry", headers=h).status_code == 200
    assert client.post(f"/api/v1/bunker-orders/{oid}/transition?target=ordered", headers=h).status_code == 200
    delivered = client.post(f"/api/v1/bunker-orders/{oid}/transition?target=delivered&qty_delivered=200", headers=h)
    assert delivered.status_code == 200, delivered.text

    r = client.get(f"/api/v1/voyages/{vid}/bunker-allocation", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    # consumption = 800 - 700 = 100 mt; weighted price = 500; allocation = 50000
    assert body["consumption_mt"] == pytest.approx(100.0)
    assert body["weighted_avg_price"] == pytest.approx(500.0)
    assert body["allocated_amount"] == pytest.approx(50000.0)
    assert body["noon_reports"] == 2
    assert body["delivered_orders"] == 1


# —— 7. EU ETS eu_share inference ——


def _fueleu(client, h, vid, **extra):
    payload = {"voyage_id": vid, "fo_mt": 100, "do_mt": 0}
    payload.update(extra)
    r = client.post("/api/v1/emissions/fueleu-calc", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_fueleu_eu_share_auto_inference(client, auth_headers, db_session):
    h = auth_headers
    eu_port = _make_port(db_session, "P1 Rotterdam", is_eu=True)
    eu_port2 = _make_port(db_session, "P1 Hamburg", is_eu=True)
    non_eu = _make_port(db_session, "P1 Singapore", is_eu=False)

    def voyage_with_legs(voyage_no, port_ids):
        vid = _make_voyage(client, h, voyage_no)
        for seq, pid in enumerate(port_ids, start=1):
            r = client.post(
                "/api/v1/port-calls",
                headers=h,
                json={"voyage_id": vid, "port_id": str(pid), "seq": seq, "purpose": "load" if seq == 1 else "discharge"},
            )
            assert r.status_code == 200, r.text
        return vid

    # EU <-> EU: share 1.0
    v_eu = voyage_with_legs("P1-ETS-EU", [eu_port, eu_port2])
    body = _fueleu(client, h, v_eu)
    assert body["eu_share"] == 1.0
    assert body["eu_share_source"] == "auto"
    assert body["ets_allowances_t"] == pytest.approx(311.4)
    assert body["borne_by"] == "owner"

    # EU <-> non-EU: share 0.5
    v_mixed = voyage_with_legs("P1-ETS-MIX", [eu_port, non_eu])
    body = _fueleu(client, h, v_mixed)
    assert body["eu_share"] == 0.5
    assert body["eu_share_source"] == "auto"
    assert body["ets_allowances_t"] == pytest.approx(311.4 * 0.5)

    # non-EU <-> non-EU: share 0
    v_out = voyage_with_legs("P1-ETS-OUT", [non_eu, non_eu])
    body = _fueleu(client, h, v_out)
    assert body["eu_share"] == 0.0
    assert body["eu_share_source"] == "auto"
    assert body["ets_allowances_t"] == 0.0

    # explicit eu_share still wins
    body = _fueleu(client, h, v_out, eu_share=0.7)
    assert body["eu_share"] == 0.7
    assert body["eu_share_source"] == "manual"

    # charterer bears ETS when the charter says so (hint only, amounts unchanged)
    charter = _make_charter(client, h, db_session, ets_responsibility="charterer")
    vid = voyage_with_legs("P1-ETS-CH", [eu_port, eu_port2])
    voyage = db_session.get(Voyage, UUID(vid))
    voyage.charter_id = charter.id
    db_session.commit()
    body = _fueleu(client, h, vid)
    assert body["borne_by"] == "charterer"
    assert body["ets_allowances_t"] == pytest.approx(311.4)
