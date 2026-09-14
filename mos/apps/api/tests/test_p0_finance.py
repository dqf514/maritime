"""P0 finance-domain fixes: credit notes, multi-currency, claims time-bar,
hire schedule, BDN, CII rating, risk limits, sanctions enforcement.

Uses the models_domain P0 contract columns (Charter.hire_per_day /
address_comm_pct, PortCall.bl_date, Invoice.base_amount / fx_rate,
Claim.deductions, BunkerOrder BDN fields, OffHireEvent).
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_domain import BunkerOrder, Charter, Claim, OffHireEvent, PortCall
from app.models_finance_ext import RiskLimit, SanctionsScreening
from app.models_wave1 import Company, Counterparty, ExchangeRate


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _tenant_id(db):
    return db.scalar(select(Company).limit(1)).tenant_id


def _first_party_id(client, h):
    return client.get("/api/v1/masterdata/counterparties", headers=h).json()[0]["id"]


def _first_voyage_id(client, h):
    return client.get("/api/v1/voyages", headers=h).json()[0]["id"]


def _create_invoice(client, h, **kw):
    payload = {"invoice_type": "freight", "amount": 10000}
    payload.update(kw)
    r = client.post("/api/v1/invoices", headers=h, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _issue(client, h, iid):
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=issued", headers=h).status_code == 200


# —— 1. Credit notes （红冲） ——


def test_credit_note_flow_and_void_guard(client, auth_headers):
    h = auth_headers
    iid = _create_invoice(client, h, amount=10000)
    _issue(client, h, iid)
    pay = client.post(f"/api/v1/invoices/{iid}/payments?amount=4000", headers=h)
    assert pay.status_code == 200, pay.text

    # void blocked while the received amount is not credited
    void = client.post(f"/api/v1/invoices/{iid}/transition?target=void", headers=h)
    assert void.status_code == 409
    assert void.json()["detail"]["code"] == "CREDIT_NOTE_REQUIRED"

    # over-credit rejected (balance is 10000 before any credit note)
    over = client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 10000.01})
    assert over.status_code == 409
    assert over.json()["detail"]["code"] == "CREDIT_EXCEEDS_BALANCE"

    bad = client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 0})
    assert bad.status_code == 422

    cn = client.post(f"/api/v1/invoices/{iid}/credit-note", headers=h, json={"amount": 4000, "reason": "refund paid part"})
    assert cn.status_code == 200, cn.text
    assert re.fullmatch(r"CN-\d{4}-\d{5}", cn.json()["credit_note_no"])

    listed = client.get(f"/api/v1/invoices/{iid}/credit-notes", headers=h)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["amount"] == 4000.0

    # paid part now fully credited -> void allowed
    void2 = client.post(f"/api/v1/invoices/{iid}/transition?target=void", headers=h)
    assert void2.status_code == 200, void2.text
    assert void2.json()["status"] == "void"

    # cumulative cap: a second credit note may not exceed the remaining balance
    iid2 = _create_invoice(client, h, amount=1000)
    assert client.post(f"/api/v1/invoices/{iid2}/credit-note", headers=h, json={"amount": 700}).status_code == 200
    cap = client.post(f"/api/v1/invoices/{iid2}/credit-note", headers=h, json={"amount": 300.01})
    assert cap.status_code == 409


# —— 2. Multi-currency ——


def test_invoice_fx_rate_and_base_amount(client, auth_headers, db_session):
    h = auth_headers
    tid = _tenant_id(db_session)
    db_session.add(
        ExchangeRate(tenant_id=tid, base_currency="EUR", quote_currency="USD", rate=Decimal("1.2"), rate_date=date.today())
    )
    db_session.commit()

    # auto rate from ExchangeRate (tenant base currency is USD)
    r = client.post("/api/v1/invoices", headers=h, json={"amount": 1000, "currency": "EUR"})
    assert r.status_code == 200, r.text
    assert r.json()["fx_rate"] == 1.2
    assert r.json()["base_amount"] == 1200.0

    # explicit fx_rate wins
    r2 = client.post("/api/v1/invoices", headers=h, json={"amount": 1000, "currency": "EUR", "fx_rate": 1.5})
    assert r2.json()["fx_rate"] == 1.5
    assert r2.json()["base_amount"] == 1500.0

    # no rate available -> base_amount left empty (P&L falls back to amount)
    r3 = client.post("/api/v1/invoices", headers=h, json={"amount": 1000, "currency": "JPY"})
    assert r3.status_code == 200
    assert r3.json()["base_amount"] is None


def test_pnl_aggregates_base_amount(client, auth_headers):
    h = auth_headers
    vid = _first_voyage_id(client, h)
    before = {r["voyage_id"]: r for r in client.get("/api/v1/analytics/reports/voyage-pnl", headers=h).json()}
    rev_before = before.get(vid, {}).get("actual_revenue", 0)

    r = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"amount": 1000, "currency": "USD", "voyage_id": vid, "fx_rate": 1.1},
    )
    assert r.status_code == 200, r.text

    after = {r["voyage_id"]: r for r in client.get("/api/v1/analytics/reports/voyage-pnl", headers=h).json()}
    assert after[vid]["actual_revenue"] - rev_before == pytest.approx(1100.0)


def test_invoice_type_validation(client, auth_headers):
    h = auth_headers
    bad = client.post("/api/v1/invoices", headers=h, json={"invoice_type": "bogus", "amount": 1})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "INVALID_INVOICE_TYPE"
    for t in ("freight", "hire", "demurrage", "bunker", "port_disbursement", "credit_note", "other"):
        ok = client.post("/api/v1/invoices", headers=h, json={"invoice_type": t, "amount": 1})
        assert ok.status_code == 200, (t, ok.text)


# —— 3. Claims P0 ——


def test_claim_timebar_inference_and_days_to_timebar(client, auth_headers, db_session):
    h = auth_headers
    vid = _first_voyage_id(client, h)
    pc = client.post("/api/v1/port-calls", headers=h, json={"voyage_id": vid, "seq": 9, "purpose": "discharge"})
    assert pc.status_code == 200, pc.text
    row = db_session.get(PortCall, UUID(pc.json()["id"]))
    row.bl_date = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    db_session.commit()

    claim = client.post("/api/v1/claims", headers=h, json={"voyage_id": vid, "amount": 5000})
    assert claim.status_code == 200, claim.text
    expected_tb = date(2026, 3, 10) + timedelta(days=90)
    assert claim.json()["time_bar"] == expected_tb.isoformat()

    items = {c["id"]: c for c in client.get("/api/v1/claims", headers=h).json()}
    got = items[claim.json()["id"]]
    assert got["days_to_timebar"] == (expected_tb - date.today()).days

    # explicit time_bar wins; no voyage / no B/L date -> stays empty
    explicit = client.post("/api/v1/claims", headers=h, json={"amount": 1, "time_bar": "2027-01-01"})
    assert explicit.json()["time_bar"] == "2027-01-01"
    plain = client.post("/api/v1/claims", headers=h, json={"amount": 1})
    assert plain.json()["time_bar"] is None


def test_claim_deductions_and_partial_settlement(client, auth_headers, db_session):
    h = auth_headers
    claim = client.post(
        "/api/v1/claims",
        headers=h,
        json={"amount": 10000, "deductions": [{"reason": "weather", "amount": 300}]},
    )
    assert claim.status_code == 200, claim.text
    cid = claim.json()["id"]
    row = db_session.get(Claim, UUID(cid))
    assert row.deductions == [{"reason": "weather", "amount": 300}]

    upd = client.patch(f"/api/v1/claims/{cid}", headers=h, json={"deductions": []})
    assert upd.status_code == 200

    assert client.post(f"/api/v1/claims/{cid}/transition?target=negotiating", headers=h).status_code == 200
    settled = client.post(f"/api/v1/claims/{cid}/transition?target=settled&settlement_amount=7000", headers=h)
    assert settled.status_code == 200, settled.text
    assert settled.json()["settlement_amount"] == 7000.0

    # default remains full amount
    claim2 = client.post("/api/v1/claims", headers=h, json={"amount": 10000})
    cid2 = claim2.json()["id"]
    full = client.post(f"/api/v1/claims/{cid2}/transition?target=settled", headers=h)
    assert full.json()["settlement_amount"] == 10000.0

    items = {c["id"]: c for c in client.get("/api/v1/claims", headers=h).json()}
    assert items[cid]["settlement_amount"] == 7000.0


# —— 4. Hire schedule ——


def test_hire_schedule_invoice_with_offhire_and_commission(client, auth_headers, db_session):
    h = auth_headers
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    cp = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "time", "vessel_id": vessels[0]["id"], "counterparty_id": _first_party_id(client, h)},
    )
    assert cp.status_code == 200, cp.text
    charter = db_session.get(Charter, UUID(cp.json()["id"]))
    charter.hire_per_day = Decimal("30000")
    charter.address_comm_pct = Decimal("1.25")
    vid = _first_voyage_id(client, h)
    db_session.add(
        OffHireEvent(
            tenant_id=charter.tenant_id,
            voyage_id=UUID(vid),
            charter_id=charter.id,
            start_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 7, tzinfo=timezone.utc),
            reason="main engine repair",
            deduct_hire=True,
        )
    )
    # non-deductible event must not reduce hire
    db_session.add(
        OffHireEvent(
            tenant_id=charter.tenant_id,
            voyage_id=UUID(vid),
            charter_id=charter.id,
            start_at=datetime(2026, 1, 9, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            reason="owner's survey (not deductible)",
            deduct_hire=False,
        )
    )
    db_session.commit()

    r = client.post(
        "/api/v1/invoices/hire-schedule",
        headers=h,
        json={"charter_id": cp.json()["id"], "period_start": "2026-01-01", "period_end": "2026-01-16"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 15 gross days - 2 off-hire days = 13 billable * 30000 = 390000 gross; 1.25% comm = 4875
    assert body["invoice_type"] == "hire"
    assert body["status"] == "draft"
    assert body["amount"] == 385125.0
    meta = body["meta"]["hire"]
    assert meta["gross_days"] == 15
    assert meta["offhire_days"] == 2
    assert meta["billable_days"] == 13
    assert meta["gross_amount"] == 390000.0
    assert meta["address_comm_amount"] == 4875.0


def test_hire_schedule_requires_rate(client, auth_headers):
    h = auth_headers
    vessels = client.get("/api/v1/masterdata/vessels", headers=h).json()
    cp = client.post("/api/v1/charters", headers=h, json={"charter_type": "time", "vessel_id": vessels[0]["id"]})
    assert cp.status_code == 200, cp.text
    r = client.post(
        "/api/v1/invoices/hire-schedule",
        headers=h,
        json={"charter_id": cp.json()["id"], "period_start": "2026-01-01", "period_end": "2026-01-16"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "NO_HIRE_RATE"


# —— 5. BDN ——


def _deliverable_bunker(client, h, **kw):
    payload = {"qty_ordered": 500, "unit_price": 450, "rob_before": 800}
    payload.update(kw)
    r = client.post("/api/v1/bunker-orders", headers=h, json=payload)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    assert client.post(f"/api/v1/bunker-orders/{oid}/transition?target=inquiry", headers=h).status_code == 200
    assert client.post(f"/api/v1/bunker-orders/{oid}/transition?target=ordered", headers=h).status_code == 200
    return oid


def test_bdn_qty_deviation_warning(client, auth_headers, db_session):
    h = auth_headers
    oid = _deliverable_bunker(client, h)
    delivered = client.post(
        f"/api/v1/bunker-orders/{oid}/transition?target=delivered&bdn_qty=520&density_kg_m3=991&sulphur_pct=0.48&supplier=AcmeBunker&barge=B-12",
        headers=h,
    )
    assert delivered.status_code == 200, delivered.text
    codes = [w["code"] for w in delivered.json()["warnings"]]
    assert "BDN_QTY_DEVIATION" in codes  # 520 vs 500 ordered = 4% > 2%
    assert delivered.json()["qty_delivered"] == 520.0
    assert delivered.json()["rob_after"] == 1320.0  # 800 + 520, consistent -> no ROB warning
    assert "ROB_CONSERVATION" not in codes

    row = db_session.get(BunkerOrder, UUID(oid))
    assert float(row.bdn_qty) == 520.0
    assert row.supplier == "AcmeBunker"
    assert row.barge == "B-12"


def test_bdn_rob_conservation_warning_not_blocking(client, auth_headers):
    h = auth_headers
    oid = _deliverable_bunker(client, h)
    # delivered 500 but BDN says 520 -> rob_after (1300) off by 20 vs expected (1320) = 1.5% > 0.5%
    delivered = client.post(
        f"/api/v1/bunker-orders/{oid}/transition?target=delivered&qty_delivered=500&bdn_qty=520",
        headers=h,
    )
    assert delivered.status_code == 200, delivered.text
    codes = [w["code"] for w in delivered.json()["warnings"]]
    assert "ROB_CONSERVATION" in codes
    assert delivered.json()["rob_after"] == 1300.0


# —— 6. CII ——


def test_cii_service_rating_boundaries():
    from app.services.cii import rate_cii, reference_cii, required_cii

    ref = reference_cii(60000, "bulk_carrier")
    assert ref == pytest.approx(5.0609, abs=1e-3)
    req = required_cii(60000, 2023, "bulk_carrier")
    assert req == pytest.approx(ref * 0.95)

    def rating_for(attained):
        co2_mt = attained * 60000 * 2500 / 1_000_000
        return rate_cii(co2_mt=co2_mt, dwt=60000, distance_nm=2500, year=2023, ship_type="bulk_carrier")

    assert rating_for(4.0)["rating"] == "A"
    assert rating_for(4.4)["rating"] == "B"
    assert rating_for(5.0)["rating"] == "C"
    assert rating_for(5.5)["rating"] == "D"
    assert rating_for(6.0)["rating"] == "E"
    assert rating_for(5.0)["attained_cii"] == 5.0


def test_emission_endpoint_real_cii(client, auth_headers):
    h = auth_headers
    r = client.post("/api/v1/emissions?fo_mt=100&do_mt=0&distance_nm=1600&dwt=60000&year=2023", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["co2_mt"] == pytest.approx(311.4)
    assert body["attained_cii"] == pytest.approx(3.2438, abs=1e-3)
    assert body["cii_rating"] == "A"
    assert body["required_cii"] == pytest.approx(4.8078, abs=1e-3)

    # legacy behaviour without distance/dwt
    r2 = client.post("/api/v1/emissions?fo_mt=900&do_mt=40", headers=h)
    assert r2.status_code == 200
    assert "attained_cii" not in r2.json()


# —— 7. Risk limits ——


def test_risk_limit_scope_priority(client, auth_headers, db_session):
    h = auth_headers
    for scope, amount in (("global", 50000), ("symbol:FFA_C5", 30000), ("counterparty:acme", 100000)):
        r = client.post("/api/v1/risk/limits", headers=h, json={"scope": scope, "amount": amount})
        assert r.status_code == 200, r.text
    listed = client.get("/api/v1/risk/limits", headers=h)
    assert {r["scope"] for r in listed.json()} >= {"global", "symbol:FFA_C5", "counterparty:acme"}

    # var = 100 * 20000 * 0.02 = 40000
    pos = client.post("/api/v1/risk/positions?symbol=FFA_C5&qty=100&entry_price=20000", headers=h)
    assert pos.status_code == 200
    assert pos.json()["limit"] == 30000.0  # symbol beats global
    assert pos.json()["limit_breach"] is True

    pos_cp = client.post("/api/v1/risk/positions?symbol=FFA_C5&qty=100&entry_price=20000&counterparty=acme", headers=h)
    assert pos_cp.json()["limit"] == 100000.0  # counterparty beats symbol
    assert pos_cp.json()["limit_breach"] is False

    pos_other = client.post("/api/v1/risk/positions?symbol=BDI&qty=100&entry_price=20000", headers=h)
    assert pos_other.json()["limit"] == 50000.0  # global applies
    assert pos_other.json()["limit_breach"] is False

    # deactivate every configured limit -> hard 100k fallback preserved
    for row in db_session.scalars(select(RiskLimit)).all():
        row.active = False
    db_session.commit()
    pos_default = client.post("/api/v1/risk/positions?symbol=FFA_C5&qty=100&entry_price=200000", headers=h)
    assert pos_default.json()["limit"] == 100000.0
    assert pos_default.json()["limit_breach"] is True


# —— 8. Sanctions ——


def _blocked_party(client, h):
    r = client.post(
        "/api/v1/masterdata/counterparties",
        headers=h,
        json={"name": "Blocked Finance Co", "type": "charterer", "sanctions_status": "blocked"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_sanctions_assertion_hooks_and_audit(client, auth_headers, db_session):
    h = auth_headers
    pid = _blocked_party(client, h)

    inv = client.post("/api/v1/invoices", headers=h, json={"amount": 100, "counterparty_id": pid})
    assert inv.status_code == 409
    assert inv.json()["detail"]["code"] == "SANCTIONS_BLOCKED"

    msg = client.post(f"/api/v1/portal/messages?counterparty_id={pid}&subject=hi", headers=h)
    assert msg.status_code == 409
    assert msg.json()["detail"]["code"] == "SANCTIONS_BLOCKED"

    bnk = client.post(
        "/api/v1/bunker-orders",
        headers=h,
        json={"qty_ordered": 100, "unit_price": 500, "counterparty_id": pid},
    )
    assert bnk.status_code == 409
    assert bnk.json()["detail"]["code"] == "SANCTIONS_BLOCKED"

    # payment hook: create + issue an invoice for a clear party, then block the party
    clear_id = _first_party_id(client, h)
    iid = _create_invoice(client, h, amount=500, counterparty_id=clear_id)
    _issue(client, h, iid)
    party = db_session.get(Counterparty, UUID(clear_id))
    party.sanctions_status = "blocked"
    db_session.commit()
    try:
        pay = client.post(f"/api/v1/invoices/{iid}/payments?amount=100", headers=h)
        assert pay.status_code == 409
        assert pay.json()["detail"]["code"] == "SANCTIONS_BLOCKED"
    finally:
        party.sanctions_status = "clear"
        db_session.commit()

    rows = db_session.scalars(
        select(SanctionsScreening).where(SanctionsScreening.tenant_id == _tenant_id(db_session))
    ).all()
    assert len([r for r in rows if r.result == "blocked"]) >= 4
    assert all(r.provider for r in rows)


# —— 9. Claim → invoice ——


def test_claim_to_invoice(client, auth_headers):
    h = auth_headers
    claim = client.post("/api/v1/claims", headers=h, json={"amount": 8000})
    cid = claim.json()["id"]

    # open claim cannot be invoiced
    early = client.post(f"/api/v1/claims/{cid}/to-invoice", headers=h)
    assert early.status_code == 409
    assert early.json()["detail"]["code"] == "INVALID_STATE"

    # negotiating: falls back to the claim amount
    assert client.post(f"/api/v1/claims/{cid}/transition?target=negotiating", headers=h).status_code == 200
    neg = client.post(f"/api/v1/claims/{cid}/to-invoice", headers=h)
    assert neg.status_code == 200, neg.text
    assert neg.json()["amount"] == 8000.0
    inv = {i["id"]: i for i in client.get("/api/v1/invoices", headers=h).json()}[neg.json()["id"]]
    assert inv["invoice_type"] == "demurrage"
    assert inv["status"] == "draft"

    # settled with partial settlement: invoice takes the settlement amount
    assert client.post(f"/api/v1/claims/{cid}/transition?target=settled&settlement_amount=6500", headers=h).status_code == 200
    settled = client.post(f"/api/v1/claims/{cid}/to-invoice", headers=h)
    assert settled.status_code == 200, settled.text
    assert settled.json()["amount"] == 6500.0
