"""Full-chain E2E: Estimate → CP → Voyage → Laytime → Claim → Bunker → Invoice → Pool/Risk/Twin."""

from datetime import datetime, timedelta, timezone


def test_calc_engines_unit():
    from app.services.estimate_engine import compute_estimate
    from app.services.laytime_engine import compute_laytime

    tce = compute_estimate(
        {
            "lump_sum_freight": 100000,
            "commission_pct": 0,
            "sea_days": 8,
            "port_days": 2,
            "port_costs": 20000,
        }
    )
    assert tce["tce"] == 8000.0

    lt = compute_laytime(
        {
            "allowed_hours": 24,
            "demurrage_rate_per_day": 12000,
            "events": [{"start": "2026-01-01T00:00:00", "end": "2026-01-02T12:00:00", "excluded": False}],
        }
    )
    assert lt["result_type"] == "demurrage"
    assert lt["amount"] == 6000.0


def test_state_machine_rejects_illegal():
    from fastapi import HTTPException

    from app.services.state_machine import CHARTER_TRANSITIONS, transition

    try:
        transition("charter", "draft", "active", CHARTER_TRANSITIONS)
        assert False, "expected 409"
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["code"] == "INVALID_STATE"


def test_full_commercial_ops_finance_chain(client, auth_headers):
    h = auth_headers

    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    parties = client.get("/api/v1/masterdata/counterparties", headers=h).json()
    ports = client.get("/api/v1/masterdata/ports", headers=h).json()
    assert vessels and parties and ports
    vessel_id = vessels[0]["id"]
    party_id = parties[0]["id"]
    load_port = ports[0]["id"]
    disc_port = ports[1]["id"] if len(ports) > 1 else ports[0]["id"]

    # Wave2 estimate
    est = client.post(
        "/api/v1/estimates",
        headers=h,
        json={
            "title": "E2E Coal SGSIN-NLRTM",
            "vessel_id": vessel_id,
            "counterparty_id": party_id,
            "inputs": {
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
                "cargo": "Coal",
            },
        },
    )
    assert est.status_code == 200, est.text
    est_id = est.json()["id"]
    calc = client.post(f"/api/v1/estimates/{est_id}/calculate", headers=h)
    assert calc.status_code == 200
    assert calc.json()["results"]["tce"] == 9953.13

    clone = client.post(f"/api/v1/estimates/{est_id}/clone", headers=h)
    assert clone.status_code == 200
    client.post(f"/api/v1/estimates/{clone.json()['id']}/calculate", headers=h)
    cmp = client.post("/api/v1/estimates/compare", headers=h, json=[est_id, clone.json()["id"]])
    assert cmp.status_code == 200
    assert len(cmp.json()) == 2

    cp = client.post(f"/api/v1/estimates/{est_id}/to-charter", headers=h)
    assert cp.status_code == 200, cp.text
    charter_id = cp.json()["id"]
    assert cp.json()["status"] == "draft"

    # illegal: draft -> active
    bad = client.post(f"/api/v1/charters/{charter_id}/transition", headers=h, json={"target": "active"})
    assert bad.status_code == 409

    assert client.post(f"/api/v1/charters/{charter_id}/transition", headers=h, json={"target": "pending_approval"}).status_code == 200
    act = client.post(f"/api/v1/charters/{charter_id}/transition", headers=h, json={"target": "active"})
    assert act.status_code == 200, act.text
    assert act.json()["status"] == "active"

    voyages = client.get("/api/v1/voyages", headers=h).json()
    assert voyages
    voyage_id = voyages[0]["id"]

    schedules = client.get("/api/v1/schedules", headers=h).json()
    assert schedules

    # Wave3 ops
    assert client.post(f"/api/v1/voyages/{voyage_id}/transition", headers=h, json={"target": "in_progress"}).status_code == 200
    now = datetime.now(timezone.utc)
    pc1 = client.post(
        "/api/v1/port-calls",
        headers=h,
        json={"voyage_id": voyage_id, "port_id": load_port, "seq": 1, "purpose": "load", "eta": (now + timedelta(days=2)).isoformat()},
    )
    assert pc1.status_code == 200, pc1.text
    pc2 = client.post(
        "/api/v1/port-calls",
        headers=h,
        json={"voyage_id": voyage_id, "port_id": disc_port, "seq": 2, "purpose": "discharge", "eta": (now + timedelta(days=20)).isoformat()},
    )
    assert pc2.status_code == 200
    noon = client.post(
        "/api/v1/noon-reports",
        headers=h,
        json={
            "voyage_id": voyage_id,
            "report_at": now.isoformat(),
            "lat": 1.2,
            "lon": 103.8,
            "speed": 12.5,
            "rob_fo": 800,
            "eta_next": (now + timedelta(days=2, hours=10)).isoformat(),
        },
    )
    assert noon.status_code == 200
    assert noon.json()["eta_deviation_hours"] is not None

    sof = client.post(
        "/api/v1/sof-events",
        headers=h,
        json={"port_call_id": pc1.json()["id"], "event_code": "NOR", "event_at": now.isoformat(), "local_tz": "Asia/Singapore"},
    )
    assert sof.status_code == 200

    fleet = client.get("/api/v1/twin/fleet", headers=h)
    assert fleet.status_code == 200
    assert fleet.json()["level"] == "L1"

    # Wave4 laytime + claim + PDA
    lt = client.post(
        "/api/v1/laytimes",
        headers=h,
        json={
            "voyage_id": voyage_id,
            "port_call_id": pc1.json()["id"],
            "inputs": {
                "allowed_hours": 72,
                "turn_time_hours": 6,
                "demurrage_rate_per_day": 24000,
                "events": [
                    {"start": "2026-09-01T08:00:00", "end": "2026-09-04T20:00:00", "excluded": False},
                    {"start": "2026-09-02T00:00:00", "end": "2026-09-02T12:00:00", "excluded": True},
                ],
            },
        },
    )
    assert lt.status_code == 200
    lt_id = lt.json()["id"]
    lt_calc = client.post(f"/api/v1/laytimes/{lt_id}/calculate", headers=h)
    assert lt_calc.status_code == 200
    assert lt_calc.json()["results"]["amount"] == 6000.0
    assert client.post(f"/api/v1/laytimes/{lt_id}/finalize", headers=h).status_code == 200

    claim = client.post(
        "/api/v1/claims",
        headers=h,
        json={"voyage_id": voyage_id, "laytime_id": lt_id, "claim_type": "demurrage"},
    )
    assert claim.status_code == 200
    assert claim.json()["amount"] == 6000.0
    assert client.post(f"/api/v1/claims/{claim.json()['id']}/transition?target=negotiating", headers=h).status_code == 200
    assert client.post(f"/api/v1/claims/{claim.json()['id']}/transition?target=settled", headers=h).status_code == 200

    pda = client.post("/api/v1/port-disbursements", headers=h, json={"voyage_id": voyage_id, "pda_amount": 45000, "lines": {"pilotage": 5000}})
    assert pda.status_code == 200
    assert client.post(f"/api/v1/port-disbursements/{pda.json()['id']}/transition?target=submitted", headers=h).status_code == 200
    assert client.post(f"/api/v1/port-disbursements/{pda.json()['id']}/transition?target=approved", headers=h).status_code == 200
    fda = client.post(f"/api/v1/port-disbursements/{pda.json()['id']}/transition?target=fda&fda_amount=47000", headers=h)
    assert fda.status_code == 200
    assert fda.json()["variance"] == 2000.0

    # Wave5 bunker + finance
    bnk = client.post(
        "/api/v1/bunker-orders",
        headers=h,
        json={"vessel_id": vessel_id, "voyage_id": voyage_id, "qty_ordered": 500, "unit_price": 450, "rob_before": 800},
    )
    assert bnk.status_code == 200
    oid = bnk.json()["id"]
    assert client.post(f"/api/v1/bunker-orders/{oid}/transition?target=inquiry", headers=h).status_code == 200
    assert client.post(f"/api/v1/bunker-orders/{oid}/transition?target=ordered", headers=h).status_code == 200
    delivered = client.post(
        f"/api/v1/bunker-orders/{oid}/transition?target=delivered&qty_delivered=500&consumption=50",
        headers=h,
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["rob_after"] == 1250.0

    inv = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"invoice_type": "freight", "counterparty_id": party_id, "voyage_id": voyage_id, "amount": 500000, "due_date": "2026-10-01"},
    )
    assert inv.status_code == 200
    iid = inv.json()["id"]
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=issued", headers=h).status_code == 200
    pay1 = client.post(f"/api/v1/invoices/{iid}/payments?amount=200000&reference=TT1", headers=h)
    assert pay1.status_code == 200
    assert pay1.json()["status"] == "partially_paid"
    pay2 = client.post(f"/api/v1/invoices/{iid}/payments?amount=300000&reference=TT2", headers=h)
    assert pay2.status_code == 200
    assert pay2.json()["status"] == "paid"
    assert client.post(f"/api/v1/invoices/{iid}/gl-post", headers=h).json()["gl_posted"] is True

    # Wave6 market / emissions / analytics
    assert client.post("/api/v1/market/quotes?symbol=BDI&value=1850", headers=h).status_code == 200
    assert client.post(f"/api/v1/emissions?voyage_id={voyage_id}&vessel_id={vessel_id}&fo_mt=900&do_mt=40", headers=h).status_code == 200
    assert client.get("/api/v1/emissions/export", headers=h).status_code == 200
    assert client.get("/api/v1/analytics/reports/tce", headers=h).status_code == 200
    assert client.get("/api/v1/analytics/reports/voyage-pnl", headers=h).status_code == 200
    assert client.post(
        f"/api/v1/dq/issues?rule_code=noon.rob&entity_type=voyage&entity_id={voyage_id}&message=ROB jump",
        headers=h,
    ).status_code == 200

    # Wave7 pool / risk / berth / portal
    pool = client.post("/api/v1/pools?name=Cape Pool", headers=h)
    assert pool.status_code == 200
    pid = pool.json()["id"]
    assert client.post(f"/api/v1/pools/{pid}/vessels?vessel_id={vessel_id}&points=1.25", headers=h).status_code == 200
    dup = client.post(f"/api/v1/pools/{pid}/vessels?vessel_id={vessel_id}&points=2", headers=h)
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "VESSEL_ALREADY_IN_POOL"
    period = client.post(f"/api/v1/pools/{pid}/periods?label=2026-09&total_pool_result=1000000", headers=h)
    assert period.status_code == 200
    assert client.post(f"/api/v1/pools/periods/{period.json()['id']}/settle", headers=h).json()["status"] == "settled"

    risk = client.post("/api/v1/risk/positions?symbol=FFA_C5&qty=10&entry_price=20000", headers=h)
    assert risk.status_code == 200
    assert client.post(
        "/api/v1/berths",
        headers=h,
        json={
            "berth_name": "Tanjong-1",
            "start_at": now.isoformat(),
            "end_at": (now + timedelta(days=1)).isoformat(),
            "voyage_id": voyage_id,
        },
    ).status_code == 200
    assert client.post(
        f"/api/v1/portal/messages?counterparty_id={party_id}&subject=Invoice%20confirm&body=Please%20confirm",
        headers=h,
    ).status_code == 200
    assert client.get(f"/api/v1/portal/invoices?counterparty_id={party_id}", headers=h).status_code == 200
    assert client.post(
        f"/api/v1/documents?entity_type=voyage&entity_id={voyage_id}&title=SOF.pdf",
        headers=h,
    ).status_code == 200

    # Wave8 twin what-if + selfcheck
    whatif = client.post(
        "/api/v1/twin/what-if",
        headers=h,
        json={"lump_sum_freight": 100000, "sea_days": 10, "port_days": 2, "port_costs": 10000},
    )
    assert whatif.status_code == 200
    assert whatif.json()["level"] == "L4"

    sc = client.post("/api/v1/settings/selfcheck/run", headers=h)
    assert sc.status_code == 200, sc.text
    assert sc.json()["score"] == 100
    ids = {r["check_id"] for r in sc.json()["results"]}
    assert "calc.tce_gold" in ids
    assert "calc.laytime_gold" in ids

    # complete voyage
    assert client.post(f"/api/v1/voyages/{voyage_id}/transition", headers=h, json={"target": "completed"}).status_code == 200


def test_sanctions_block_activation(client, auth_headers):
    h = auth_headers
    party = client.post(
        "/api/v1/masterdata/counterparties",
        headers=h,
        json={"name": "Blocked Co", "type": "charterer", "sanctions_status": "blocked"},
    )
    assert party.status_code == 200
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "voyage", "vessel_id": vessels[0]["id"], "counterparty_id": party.json()["id"]},
    )
    assert cp.json()["sanctions_blocked"] is True
    client.post(f"/api/v1/charters/{cp.json()['id']}/transition", headers=h, json={"target": "pending_approval"})
    blocked = client.post(f"/api/v1/charters/{cp.json()['id']}/transition", headers=h, json={"target": "active"})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "SANCTIONS_BLOCKED"
