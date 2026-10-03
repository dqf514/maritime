"""Phase 5 Time Charter depth — bareboat/child TCs, profit share tiers,
billing schedules, broker rules, state machine, GL period-journal allocation.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.orm import sessionmaker

from app.services import hire_engine


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _items(payload):
    return payload["items"] if isinstance(payload, dict) else payload


def _make_charter(client, h, **overrides):
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    body = {
        "charter_type": "tct",
        "counterparty_id": parties[0]["id"],
        "hire_per_day": 12000,
    }
    body.update(overrides)
    return client.post("/api/v1/charters", headers=h, json=body).json()


def _make_tc(client, h, **overrides):
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())
    vessels = _items(client.get("/api/v1/masterdata/vessels", headers=h).json())
    charter = _make_charter(client, h)
    body = {
        "charter_id": charter["id"],
        "contract_type": "tci",
        "contract_style": "time_charter",
        "vessel_id": vessels[0]["id"],
        "counterparty_id": parties[0]["id"],
        "hire_rate": 10000,
        "delivery_date": "2026-01-01",
        "redelivery_date": "2026-03-01",
    }
    body.update(overrides)
    r = client.post("/api/v1/tc/contracts", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── contract_style=bareboat ──────────────────────────────────────────────────


def test_bareboat_contract_crud(client, auth_headers):
    h = auth_headers
    tc = _make_tc(
        client,
        h,
        contract_style="bareboat",
        contract_type="tco",
        address_comm_pct=2.5,
        brokerage_pct=1.25,
        profit_share_pct=30,
        profit_share_threshold=12000,
    )
    assert tc["contract_style"] == "bareboat"
    assert tc["address_comm_pct"] == 2.5
    assert tc["brokerage_pct"] == 1.25
    assert tc["profit_share_pct"] == 30
    assert tc["profit_share_threshold"] == 12000

    detail = client.get(f"/api/v1/tc/contracts/{tc['id']}", headers=h).json()
    assert detail["contract_style"] == "bareboat"
    assert detail["parent_contract_id"] is None

    patched = client.patch(
        f"/api/v1/tc/contracts/{tc['id']}",
        headers=h,
        json={"hire_rate": 11000, "payment_frequency": "semi_monthly"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["hire_rate"] == 11000
    assert patched.json()["payment_frequency"] == "semi_monthly"

    listed = client.get(
        "/api/v1/tc/contracts", headers=h, params={"contract_style": "bareboat"}
    ).json()
    assert tc["id"] in [r["id"] for r in listed]
    listed_tci = client.get(
        "/api/v1/tc/contracts", headers=h, params={"contract_type": "tci"}
    ).json()
    assert tc["id"] not in [r["id"] for r in listed_tci]


def test_bareboat_hire_statement(client, auth_headers, db_session):
    h = auth_headers
    tc = _make_tc(
        client,
        h,
        contract_style="bareboat",
        contract_type="tco",
        hire_rate=10000,
        address_comm_pct=2.5,
        brokerage_pct=1.25,
    )
    calc = hire_engine.bareboat_hire_statement(
        db_session, uuid.UUID(tc["id"]), (date(2026, 1, 1), date(2026, 1, 31))
    )
    # full 30 days, no off-hire relief on bareboat
    assert calc["hire_days"] == 30
    assert calc["off_hire_days"] == 0
    assert calc["gross_hire"] == 300000
    assert calc["address_commission"] == 7500  # 2.5%
    assert calc["brokerage"] == 3750  # 1.25%
    assert calc["net_hire"] == 288750


# ── child TC chain + rollup ──────────────────────────────────────────────────


def test_child_tc_creation_and_rollup(client, auth_headers, db_session):
    h = auth_headers
    parent = _make_tc(client, h, contract_type="tco", hire_rate=12000)

    c1 = client.post(
        f"/api/v1/tc/contracts/{parent['id']}/children",
        headers=h,
        json={"hire_rate": 9000, "delivery_date": "2026-01-01", "redelivery_date": "2026-02-01"},
    )
    assert c1.status_code == 201, c1.text
    c2 = client.post(
        f"/api/v1/tc/contracts/{parent['id']}/children",
        headers=h,
        json={"hire_rate": 8000, "contract_type": "tci"},
    )
    assert c2.status_code == 201, c2.text
    assert c1.json()["parent_contract_id"] == parent["id"]
    assert c1.json()["vessel_id"] == parent["vessel_id"]  # inherited
    assert c2.json()["contract_type"] == "tci"  # overridden

    children = client.get(f"/api/v1/tc/contracts/{parent['id']}/children", headers=h).json()
    assert [c["id"] for c in children] == [c1.json()["id"], c2.json()["id"]]

    # hire statements on both children feed the rollup
    s1 = client.post(
        "/api/v1/hire-statements",
        headers=h,
        json={"contract_id": c1.json()["id"], "period_start": "2026-01-01", "period_end": "2026-01-11"},
    )
    assert s1.status_code == 201, s1.text
    assert s1.json()["net_hire"] == 90000  # 10 days × 9000
    s2 = client.post(
        "/api/v1/hire-statements",
        headers=h,
        json={"contract_id": c2.json()["id"], "period_start": "2026-01-01", "period_end": "2026-01-11"},
    )
    assert s2.status_code == 201, s2.text
    assert s2.json()["net_hire"] == 80000

    rollup = hire_engine.child_tc_rollup(db_session, uuid.UUID(parent["id"]))
    assert rollup["child_count"] == 2
    assert rollup["total_net_hire"] == 170000
    assert rollup["total_gross_hire"] == 170000
    by_id = {c["id"]: c for c in rollup["children"]}
    assert by_id[c1.json()["id"]]["net_hire"] == 90000
    assert by_id[c2.json()["id"]]["net_hire"] == 80000


# ── profit share tiers ───────────────────────────────────────────────────────


def test_profit_share_tiered_calculation(client, auth_headers):
    h = auth_headers
    tc = _make_tc(client, h, profit_share_threshold=10000)

    tiers = [
        {"tier_from": 0, "tier_to": 15000, "share_pct": 50, "basis": "tce"},
        {"tier_from": 15000, "tier_to": 25000, "share_pct": 60},
        {"tier_from": 25000, "tier_to": None, "share_pct": 75},
    ]
    for t in tiers:
        r = client.post(f"/api/v1/tc/contracts/{tc['id']}/profit-share", headers=h, json=t)
        assert r.status_code == 201, r.text

    rules = client.get(f"/api/v1/tc/contracts/{tc['id']}/profit-share", headers=h).json()
    assert [r["share_pct"] for r in rules] == [50, 60, 75]
    assert rules[0]["tier_to"] == 15000
    assert rules[2]["tier_to"] is None

    calc = client.get(
        f"/api/v1/tc/contracts/{tc['id']}/profit-share/calculate",
        headers=h,
        params={"period_tce": 30000},
    ).json()
    # excess 20000 above threshold 10000:
    # (10000,15000]×50% = 2500 + (15000,25000]×60% = 6000 + (25000,30000]×75% = 3750
    assert calc["excess"] == 20000
    assert calc["owner_share"] == 12250
    assert calc["charterer_share"] == 7750
    assert len(calc["tiers"]) == 3

    below = client.get(
        f"/api/v1/tc/contracts/{tc['id']}/profit-share/calculate",
        headers=h,
        params={"period_tce": 8000},
    ).json()
    assert below["excess"] == 0
    assert below["owner_share"] == 0

    # flat fallback when no rules exist
    flat_tc = _make_tc(client, h, profit_share_pct=30, profit_share_threshold=10000)
    flat = client.get(
        f"/api/v1/tc/contracts/{flat_tc['id']}/profit-share/calculate",
        headers=h,
        params={"period_tce": 15000},
    ).json()
    assert flat["excess"] == 5000
    assert flat["owner_share"] == 1500  # 30% of 5000

    # invalid tier ordering rejected
    bad = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/profit-share",
        headers=h,
        json={"tier_from": 20000, "tier_to": 15000, "share_pct": 50},
    )
    assert bad.status_code == 422


# ── billing schedule ─────────────────────────────────────────────────────────


def test_billing_schedule_generation_from_frequency(client, auth_headers):
    h = auth_headers
    monthly = _make_tc(
        client, h, payment_frequency="monthly", hire_rate=10000,
        delivery_date="2026-01-01", redelivery_date="2026-03-01",
    )
    rows = client.post(
        f"/api/v1/tc/contracts/{monthly['id']}/billing-schedule/generate",
        headers=h,
        json={"start_date": "2026-01-01", "end_date": "2026-03-01"},
    )
    assert rows.status_code == 201, rows.text
    periods = rows.json()
    assert [(p["period_start"], p["period_end"]) for p in periods] == [
        ("2026-01-01", "2026-01-31"),
        ("2026-01-31", "2026-03-01"),
    ]
    assert periods[0]["amount"] == 300000  # 30 days × 10000
    assert periods[1]["amount"] == 290000  # 29 days × 10000
    assert all(p["status"] == "draft" for p in periods)
    assert periods[0]["due_date"] == "2026-01-31"

    # regenerate is skip-safe
    again = client.post(
        f"/api/v1/tc/contracts/{monthly['id']}/billing-schedule/generate",
        headers=h,
        json={"start_date": "2026-01-01", "end_date": "2026-03-01"},
    )
    assert again.status_code == 201
    assert again.json() == []
    listed = client.get(
        f"/api/v1/tc/contracts/{monthly['id']}/billing-schedule", headers=h
    ).json()
    assert len(listed) == 2

    # status update
    upd = client.patch(
        f"/api/v1/tc/billing-schedule/{listed[0]['id']}",
        headers=h,
        json={"status": "invoiced"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["status"] == "invoiced"
    bad = client.patch(
        f"/api/v1/tc/billing-schedule/{listed[0]['id']}",
        headers=h,
        json={"status": "bogus"},
    )
    assert bad.status_code == 422

    # semi_monthly → 15-day chunks
    semi = _make_tc(
        client, h, payment_frequency="semi_monthly", hire_rate=1000,
        delivery_date="2026-01-01", redelivery_date="2026-02-01",
    )
    srows = client.post(
        f"/api/v1/tc/contracts/{semi['id']}/billing-schedule/generate",
        headers=h,
        json={"start_date": "2026-01-01", "end_date": "2026-02-01"},
    ).json()
    assert [(p["period_start"], p["period_end"]) for p in srows] == [
        ("2026-01-01", "2026-01-16"),
        ("2026-01-16", "2026-01-31"),
        ("2026-01-31", "2026-02-01"),
    ]
    assert [p["amount"] for p in srows] == [15000, 15000, 1000]


# ── broker rules ─────────────────────────────────────────────────────────────


def test_broker_rules_crud(client, auth_headers):
    h = auth_headers
    tc = _make_tc(client, h)
    parties = _items(client.get("/api/v1/masterdata/counterparties", headers=h).json())

    created = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/broker-rules",
        headers=h,
        json={
            "broker_party_id": parties[0]["id"],
            "commission_type": "brokerage",
            "commission_pct": 1.25,
            "applies_to": "hire",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["commission_pct"] == 1.25

    addr = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/broker-rules",
        headers=h,
        json={
            "broker_party_id": parties[0]["id"],
            "commission_type": "address",
            "commission_pct": 2.5,
        },
    )
    assert addr.status_code == 201, addr.text
    assert addr.json()["applies_to"] == "all"

    rules = client.get(f"/api/v1/tc/contracts/{tc['id']}/broker-rules", headers=h).json()
    assert [r["commission_type"] for r in rules] == ["brokerage", "address"]

    over = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/broker-rules",
        headers=h,
        json={
            "broker_party_id": parties[0]["id"],
            "commission_type": "brokerage",
            "commission_pct": 150,
        },
    )
    assert over.status_code == 422

    missing = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/broker-rules",
        headers=h,
        json={
            "broker_party_id": str(uuid.uuid4()),
            "commission_type": "brokerage",
            "commission_pct": 1,
        },
    )
    assert missing.status_code == 404


# ── state machine ────────────────────────────────────────────────────────────


def test_tc_state_transitions(client, auth_headers):
    h = auth_headers
    tc = _make_tc(client, h)
    assert tc["status"] == "draft"

    # draft → completed is illegal (must go through active)
    early = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/transition", headers=h, params={"target": "completed"}
    )
    assert early.status_code == 409
    assert early.json()["detail"]["code"] == "INVALID_STATE"

    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/transition", headers=h, params={"target": "active"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"

    r = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/transition", headers=h, params={"target": "completed"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"

    after = client.post(
        f"/api/v1/tc/contracts/{tc['id']}/transition", headers=h, params={"target": "cancelled"}
    )
    assert after.status_code == 409

    # cancel from an early state is allowed
    tc2 = _make_tc(client, h)
    r2 = client.post(
        f"/api/v1/tc/contracts/{tc2['id']}/transition", headers=h, params={"target": "cancelled"}
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "cancelled"


def test_hire_statement_transitions(client, auth_headers):
    h = auth_headers
    tc = _make_tc(client, h)
    stmt = client.post(
        "/api/v1/hire-statements",
        headers=h,
        json={"contract_id": tc["id"], "period_start": "2026-01-01", "period_end": "2026-01-31"},
    ).json()
    assert stmt["status"] == "draft"

    for target, expected in [
        ("sent", "sent"),
        ("approved", "approved"),
        ("paid", "paid"),
        ("void", "void"),
    ]:
        r = client.post(
            f"/api/v1/hire-statements/{stmt['id']}/transition", headers=h, params={"target": target}
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == expected

    illegal = client.post(
        f"/api/v1/hire-statements/{stmt['id']}/transition", headers=h, params={"target": "sent"}
    )
    assert illegal.status_code == 409
    assert illegal.json()["detail"]["code"] == "INVALID_STATE"


# ── period journal allocation ────────────────────────────────────────────────


def test_period_journal_allocation(client, auth_headers, db_session):
    h = auth_headers
    tc = _make_tc(
        client, h, contract_type="tco", hire_rate=10000,
        delivery_date="2026-01-01", redelivery_date="2026-01-11",
    )

    journal = hire_engine.allocate_period_journal(
        db_session, uuid.UUID(tc["id"]), date(2026, 1, 1), date(2026, 1, 11)
    )
    db_session.commit()
    assert journal.period == "2026-01"
    assert journal.journal_type == "accrual"
    assert journal.total_debit == 100000  # 10 days × 10000
    assert journal.total_credit == 100000
    accounts = {e["account"]: e for e in journal.entries}
    assert accounts["hire_receivable"]["debit"] == "100000.00"
    assert accounts["hire_revenue"]["credit"] == "100000.00"

    # idempotent — same period+contract returns the same journal
    again = hire_engine.allocate_period_journal(
        db_session, uuid.UUID(tc["id"]), date(2026, 1, 1), date(2026, 1, 11)
    )
    assert again.id == journal.id

    # tci flips the accounts
    tci = _make_tc(
        client, h, contract_type="tci", hire_rate=5000,
        delivery_date="2026-02-01", redelivery_date="2026-02-11",
    )
    j2 = hire_engine.allocate_period_journal(
        db_session, uuid.UUID(tci["id"]), date(2026, 2, 1), date(2026, 2, 11)
    )
    db_session.commit()
    accounts2 = {e["account"]: e for e in j2.entries}
    assert accounts2["hire_expense"]["debit"] == "50000.00"
    assert accounts2["hire_payable"]["credit"] == "50000.00"


# ── hire summary ─────────────────────────────────────────────────────────────


def test_hire_summary_aggregates(client, auth_headers):
    h = auth_headers
    tc = _make_tc(
        client, h, contract_type="tco", hire_rate=10000,
        profit_share_threshold=10000, profit_share_pct=40,
    )
    client.post(
        f"/api/v1/tc/contracts/{tc['id']}/profit-share",
        headers=h,
        json={"tier_from": 0, "tier_to": None, "share_pct": 50},
    )
    client.post(
        f"/api/v1/tc/contracts/{tc['id']}/broker-rules",
        headers=h,
        json={
            "broker_party_id": _items(
                client.get("/api/v1/masterdata/counterparties", headers=h).json()
            )[0]["id"],
            "commission_type": "brokerage",
            "commission_pct": 1.25,
        },
    )
    client.post(
        f"/api/v1/tc/contracts/{tc['id']}/billing-schedule/generate",
        headers=h,
        json={"start_date": "2026-01-01", "end_date": "2026-01-31"},
    )
    client.post(
        "/api/v1/hire-statements",
        headers=h,
        json={"contract_id": tc["id"], "period_start": "2026-01-01", "period_end": "2026-01-31"},
    )

    body = client.get(f"/api/v1/tc/contracts/{tc['id']}/hire-summary", headers=h).json()
    assert body["statement_count"] == 1
    assert body["total_billed"] == 300000  # 30 days × 10000
    assert body["billing_schedule_count"] == 1
    assert body["billing_total"] == 300000
    assert body["profit_share"]["rule_count"] == 1
    assert body["profit_share"]["threshold"] == 10000
    assert body["broker_rules"]["count"] == 1
    assert body["broker_rules"]["total_commission_pct"] == 1.25
    assert body["contract_style"] == "time_charter"
