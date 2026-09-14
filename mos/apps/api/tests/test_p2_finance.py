"""P2 finance/risk fixes: EEOI on emission endpoints, FFA paper-vs-physical
hedge view, bunker inquiry listing, payment void (冲正) with GL-posted guard."""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_domain import Charter, Payment, Voyage


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _first_vessel_id(client, h):
    return client.get("/api/v1/masterdata/vessels", headers=h).json()[0]["id"]


def _make_active_charter_with_cargo(client, h, db_session, cargo_text, cargo_qty, voyage_no):
    """Active charter (在手货盘) linked to a voyage whose cargo text maps the symbol."""
    r = client.post(
        "/api/v1/charters",
        headers=h,
        json={"charter_type": "voyage", "vessel_id": _first_vessel_id(client, h)},
    )
    assert r.status_code == 200, r.text
    charter = db_session.get(Charter, UUID(r.json()["id"]))
    charter.status = "active"
    charter.cargo_qty = Decimal(str(cargo_qty))
    v = client.post("/api/v1/voyages", headers=h, json={"voyage_no": voyage_no, "charter_id": str(charter.id)})
    assert v.status_code == 200, v.text
    voyage = db_session.get(Voyage, UUID(v.json()["id"]))
    voyage.cargo = cargo_text
    db_session.commit()
    return charter


def _create_invoice(client, h, amount=10000):
    r = client.post("/api/v1/invoices", headers=h, json={"invoice_type": "freight", "amount": amount})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _issue(client, h, iid):
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=pending_approval", headers=h).status_code == 200
    assert client.post(f"/api/v1/invoices/{iid}/transition?target=issued", headers=h).status_code == 200


# —— 1. EEOI ——


def test_eeoi_on_create_emission(client, auth_headers):
    h = auth_headers
    # co2 = 100 * 3.114 = 311.4 t; eeoi = 311.4 / (50000 * 6000) tCO2/t·nm
    r = client.post(
        "/api/v1/emissions",
        headers=h,
        params={"fo_mt": 100, "do_mt": 0, "cargo_mt": 50000, "distance_nm": 6000},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["co2_mt"] == pytest.approx(311.4)
    assert body["eeoi"] == pytest.approx(311.4 / (50000 * 6000))

    # without cargo_mt / distance_nm there is no eeoi in the response
    r2 = client.post("/api/v1/emissions", headers=h, params={"fo_mt": 100})
    assert r2.status_code == 200, r2.text
    assert "eeoi" not in r2.json()
    r3 = client.post("/api/v1/emissions", headers=h, params={"fo_mt": 100, "cargo_mt": 50000})
    assert "eeoi" not in r3.json()


def test_eeoi_on_fueleu_calc(client, auth_headers):
    h = auth_headers
    r = client.post(
        "/api/v1/emissions/fueleu-calc",
        headers=h,
        json={"fo_mt": 100, "do_mt": 0, "cargo_mt": 40000, "distance_nm": 5000},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # co2e = 311.4 t; eeoi = 311.4 / (40000 * 5000)
    assert body["co2e_t"] == pytest.approx(311.4)
    assert body["eeoi"] == pytest.approx(311.4 / (40000 * 5000))

    r2 = client.post("/api/v1/emissions/fueleu-calc", headers=h, json={"fo_mt": 100})
    assert r2.status_code == 200, r2.text
    assert "eeoi" not in r2.json()


# —— 2. FFA / paper vs physical hedge view ——


def test_hedge_view_aggregation(client, auth_headers, db_session):
    h = auth_headers
    # paper: long 1000 + short 400 on P2IRON -> net paper 600
    for symbol, qty, side in (("P2IRON", 1000, "long"), ("P2IRON", 400, "short"), ("P2PAPER", 50, "long")):
        r = client.post(
            "/api/v1/risk/positions",
            headers=h,
            params={"symbol": symbol, "qty": qty, "entry_price": 100, "side": side},
        )
        assert r.status_code == 200, r.text
    # physical: active charters' cargo_qty mapped by voyage cargo text
    _make_active_charter_with_cargo(client, h, db_session, "p2iron", 3000, "P2-HV-1")
    _make_active_charter_with_cargo(client, h, db_session, "P2COAL", 1000, "P2-HV-2")

    r = client.get("/api/v1/risk/hedge-view", headers=h)
    assert r.status_code == 200, r.text
    rows = {row["symbol"]: row for row in r.json()}

    iron = rows["P2IRON"]
    assert iron["paper_qty"] == pytest.approx(600.0)
    assert iron["physical_qty"] == pytest.approx(3000.0)
    assert iron["net_exposure"] == pytest.approx(2400.0)
    assert iron["hedge_ratio"] == pytest.approx(0.2)

    coal = rows["P2COAL"]
    assert coal["paper_qty"] == pytest.approx(0.0)
    assert coal["physical_qty"] == pytest.approx(1000.0)
    assert coal["net_exposure"] == pytest.approx(1000.0)
    assert coal["hedge_ratio"] == pytest.approx(0.0)

    # paper-only symbol: physical = 0 -> hedge_ratio null, net = -paper
    paper_only = rows["P2PAPER"]
    assert paper_only["physical_qty"] == pytest.approx(0.0)
    assert paper_only["net_exposure"] == pytest.approx(-50.0)
    assert paper_only["hedge_ratio"] is None


# —— 3. Bunker inquiries list GET ——


def test_bunker_inquiries_list(client, auth_headers):
    h = auth_headers
    order = client.post("/api/v1/bunker-orders", headers=h, json={"qty_ordered": 500, "unit_price": 450})
    assert order.status_code == 200, order.text
    oid = order.json()["id"]
    inq_a = client.post(f"/api/v1/bunker-orders/{oid}/inquiries", headers=h, json={"supplier": "SupA", "quoted_price": 440})
    assert inq_a.status_code == 200, inq_a.text
    inq_b = client.post(f"/api/v1/bunker-orders/{oid}/inquiries", headers=h, json={"supplier": "SupB", "quoted_price": 430})
    assert inq_b.status_code == 200, inq_b.text
    acc = client.post(f"/api/v1/bunker-inquiries/{inq_b.json()['id']}/accept", headers=h)
    assert acc.status_code == 200, acc.text

    r = client.get(f"/api/v1/bunker-orders/{oid}/inquiries", headers=h)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 2
    by_supplier = {row["supplier"]: row for row in rows}
    assert by_supplier["SupB"]["status"] == "accepted"
    assert by_supplier["SupB"]["quoted_price"] == pytest.approx(430.0)
    assert by_supplier["SupA"]["status"] == "rejected"
    assert all(row["order_id"] == oid for row in rows)
    # quoted_at descending (non-strict: SQLite server_default has second resolution)
    quoted_ats = [row["quoted_at"] for row in rows]
    assert quoted_ats == sorted(quoted_ats, reverse=True)

    missing = client.get(f"/api/v1/bunker-orders/{UUID(int=0)}/inquiries", headers=h)
    assert missing.status_code == 404


# —— 4. Payment void (冲正) ——


def _payments_for(db_session, iid):
    return db_session.scalars(select(Payment).where(Payment.invoice_id == UUID(iid))).all()


def test_payment_void_rewrites_invoice(client, auth_headers, db_session):
    h = auth_headers
    iid = _create_invoice(client, h, amount=10000)
    _issue(client, h, iid)
    pay = client.post(f"/api/v1/invoices/{iid}/payments?amount=4000", headers=h)
    assert pay.status_code == 200, pay.text
    assert pay.json()["status"] == "partially_paid"
    payment_id = _payments_for(db_session, iid)[0].id

    r = client.post(f"/api/v1/payments/{payment_id}/void", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "issued"
    assert body["paid_amount"] == pytest.approx(0.0)

    # original payment kept; negative reversal row linked via reference marker
    rows = _payments_for(db_session, iid)
    by_amount = sorted((float(p.amount) for p in rows))
    assert by_amount == [-4000.0, 4000.0]
    reversal = [p for p in rows if float(p.amount) < 0][0]
    assert reversal.reference == f"VOID:{payment_id}"
    original = [p for p in rows if float(p.amount) > 0][0]
    assert str(original.id) == str(payment_id)

    listed = {i["id"]: i for i in client.get("/api/v1/invoices", headers=h).json()}
    assert listed[iid]["paid_amount"] == pytest.approx(0.0)
    assert listed[iid]["status"] == "issued"

    # idempotent: second void of the same payment is rejected
    again = client.post(f"/api/v1/payments/{payment_id}/void", headers=h)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "ALREADY_VOIDED"


def test_payment_void_from_paid_goes_partially_paid(client, auth_headers, db_session):
    h = auth_headers
    iid = _create_invoice(client, h, amount=10000)
    _issue(client, h, iid)
    assert client.post(f"/api/v1/invoices/{iid}/payments?amount=4000", headers=h).status_code == 200
    full = client.post(f"/api/v1/invoices/{iid}/payments?amount=6000", headers=h)
    assert full.status_code == 200, full.text
    assert full.json()["status"] == "paid"
    payments = _payments_for(db_session, iid)
    big = [p for p in payments if float(p.amount) == 6000.0][0]

    r = client.post(f"/api/v1/payments/{big.id}/void", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "partially_paid"
    assert r.json()["paid_amount"] == pytest.approx(4000.0)

    # voiding the reversal entry itself is rejected
    rev_id = r.json()["reversal_id"]
    bad = client.post(f"/api/v1/payments/{rev_id}/void", headers=h)
    assert bad.status_code == 409
    assert bad.json()["detail"]["code"] == "INVALID_PAYMENT"


def test_payment_void_blocked_when_gl_posted(client, auth_headers, db_session):
    h = auth_headers
    iid = _create_invoice(client, h, amount=10000)
    _issue(client, h, iid)
    assert client.post(f"/api/v1/invoices/{iid}/payments?amount=4000", headers=h).status_code == 200
    gl = client.post(f"/api/v1/invoices/{iid}/gl-post", headers=h)
    assert gl.status_code == 200, gl.text
    payment_id = _payments_for(db_session, iid)[0].id

    r = client.post(f"/api/v1/payments/{payment_id}/void", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "GL_POSTED"

    # nothing was written back
    listed = {i["id"]: i for i in client.get("/api/v1/invoices", headers=h).json()}
    assert listed[iid]["paid_amount"] == pytest.approx(4000.0)
    assert listed[iid]["status"] == "partially_paid"
