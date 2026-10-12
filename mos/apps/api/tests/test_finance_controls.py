"""P1 财务控制：审批额度工作流 / 汇率日期规则 / 发票类型补全。

Covers: ApprovalLimit CRUD + enforcement (within/outside/permissive default,
tenant isolation), FxDateRule CRUD + default basis + as-of rate consumption,
invoice type registry validation (canonical / alias / invalid).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import create_tenant


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _demo_tenant_id(db_session) -> UUID:
    from app.models import Tenant

    return UUID(str(db_session.execute(select(Tenant.id).where(Tenant.code == "demo")).scalar()))


def _create_invoice(client, h, amount=5000, invoice_type="freight", currency="USD"):
    r = client.post(
        "/api/v1/invoices",
        headers=h,
        json={"invoice_type": invoice_type, "amount": amount, "currency": currency},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _try_issue(client, h, invoice_id):
    """draft → pending_approval → issued; return the final transition response."""
    r1 = client.post(f"/api/v1/invoices/{invoice_id}/transition?target=pending_approval", headers=h)
    assert r1.status_code == 200, r1.text
    return client.post(f"/api/v1/invoices/{invoice_id}/transition?target=issued", headers=h)


# ── Feature 1: approval amount workflow ─────────────────────────────────────


def test_approval_limit_crud(client, auth_headers):
    h = auth_headers
    r = client.post(
        "/api/v1/approvals/limits",
        headers=h,
        json={
            "role_code": "finance",
            "entity_type": "invoice",
            "currency": "USD",
            "amount_from": 0,
            "amount_to": 5000,
        },
    )
    assert r.status_code == 200, r.text
    limit = r.json()
    assert limit["role_code"] == "finance"
    assert limit["amount_from"] == 0
    assert limit["amount_to"] == 5000
    assert limit["active"] is True

    rows = client.get("/api/v1/approvals/limits?entity_type=invoice", headers=h).json()["items"]
    assert len(rows) == 1 and rows[0]["id"] == limit["id"]

    upd = client.patch(
        f"/api/v1/approvals/limits/{limit['id']}",
        headers=h,
        json={"amount_to": 9000, "active": False},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["amount_to"] == 9000
    assert upd.json()["active"] is False

    bad_band = client.post(
        "/api/v1/approvals/limits",
        headers=h,
        json={"role_code": "finance", "entity_type": "invoice", "amount_from": 100, "amount_to": 10},
    )
    assert bad_band.status_code == 422
    assert bad_band.json()["detail"]["code"] == "INVALID_APPROVAL_BAND"

    deleted = client.delete(f"/api/v1/approvals/limits/{limit['id']}", headers=h)
    assert deleted.status_code == 200, deleted.text
    assert client.get("/api/v1/approvals/limits", headers=h).json()["items"] == []


def test_approval_enforcement_within_limit(client, auth_headers):
    h = auth_headers
    # admin holds role `tenant_admin`; band covers the invoice amount
    r = client.post(
        "/api/v1/approvals/limits",
        headers=h,
        json={"role_code": "tenant_admin", "entity_type": "invoice", "currency": "USD", "amount_from": 0, "amount_to": 100_000},
    )
    assert r.status_code == 200, r.text

    inv = _create_invoice(client, h, amount=50_000)
    res = _try_issue(client, h, inv["id"])
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "issued"


def test_approval_enforcement_outside_limit(client, auth_headers):
    h = auth_headers
    r = client.post(
        "/api/v1/approvals/limits",
        headers=h,
        json={"role_code": "tenant_admin", "entity_type": "invoice", "currency": "USD", "amount_from": 0, "amount_to": 1_000},
    )
    assert r.status_code == 200, r.text

    inv = _create_invoice(client, h, amount=50_000)
    res = _try_issue(client, h, inv["id"])
    assert res.status_code == 409, res.text
    detail = res.json()["detail"]
    assert detail["code"] == "APPROVAL_LIMIT"
    assert detail["entity_type"] == "invoice"
    assert detail["amount"] == 50_000

    # still pending_approval — the approval was rejected, state unchanged
    row = client.get(f"/api/v1/invoices/{inv['id']}", headers=h).json()
    assert row["status"] == "pending_approval"


def test_approval_permissive_default_when_no_rows(client, auth_headers):
    """Approver without any limit rows may approve any amount (documented default)."""
    h = auth_headers
    assert client.get("/api/v1/approvals/limits", headers=h).json()["items"] == []

    inv = _create_invoice(client, h, amount=999_999)
    res = _try_issue(client, h, inv["id"])
    assert res.status_code == 200, res.text

    # A limit bound to a *different* role must not restrict this approver either
    r = client.post(
        "/api/v1/approvals/limits",
        headers=h,
        json={"role_code": "finance", "entity_type": "invoice", "currency": "USD", "amount_from": 0, "amount_to": 1},
    )
    assert r.status_code == 200, r.text
    inv2 = _create_invoice(client, h, amount=888_888)
    res2 = _try_issue(client, h, inv2["id"])
    assert res2.status_code == 200, res2.text


def test_approval_limit_tenant_isolation(client, auth_headers):
    h = auth_headers
    _, hb = create_tenant(
        client, code="finiso", name="Fin Iso", admin_email="admin@finiso.example.com"
    )

    r = client.post(
        "/api/v1/approvals/limits",
        headers=h,
        json={"role_code": "tenant_admin", "entity_type": "invoice", "currency": "USD", "amount_from": 0, "amount_to": 100},
    )
    assert r.status_code == 200, r.text
    limit_a = r.json()

    # Tenant B sees none of tenant A's rows
    rows_b = client.get("/api/v1/approvals/limits", headers=hb).json()["items"]
    assert rows_b == []

    # Tenant B cannot read/update/delete tenant A's row
    for resp in (
        client.patch(f"/api/v1/approvals/limits/{limit_a['id']}", headers=hb, json={"amount_to": 1}),
        client.delete(f"/api/v1/approvals/limits/{limit_a['id']}", headers=hb),
    ):
        assert resp.status_code == 404, resp.text

    # Tenant A's tight band does not leak into tenant B's approvals
    inv_b = _create_invoice(client, hb, amount=50_000)
    res_b = _try_issue(client, hb, inv_b["id"])
    assert res_b.status_code == 200, res_b.text

    # ...while it does restrict tenant A
    inv_a = _create_invoice(client, h, amount=50_000)
    res_a = _try_issue(client, h, inv_a["id"])
    assert res_a.status_code == 409
    assert res_a.json()["detail"]["code"] == "APPROVAL_LIMIT"


# ── Feature 2: FX rate date rule ────────────────────────────────────────────


def test_fx_date_rule_crud_and_default(client, auth_headers):
    h = auth_headers
    empty = client.get("/api/v1/approvals/fx-date-rules", headers=h).json()
    assert empty["items"] == []
    assert empty["default_basis"] == "invoice"
    assert set(empty["allowed_bases"]) == {"departure", "arrival", "invoice", "posted"}

    # No row → GET-by-type reports the default basis
    dflt = client.get("/api/v1/approvals/fx-date-rules/FRT", headers=h).json()
    assert dflt["is_default"] is True
    assert dflt["rate_date_basis"] == "invoice"

    up = client.put(
        "/api/v1/approvals/fx-date-rules",
        headers=h,
        json={"invoice_type": "FRT", "rate_date_basis": "departure", "active": True},
    )
    assert up.status_code == 200, up.text
    assert up.json()["invoice_type"] == "FRT"
    assert up.json()["rate_date_basis"] == "departure"
    assert up.json()["effective_basis"] == "departure"

    # Alias input normalises onto the same rule row (FRT ≡ freight)
    up_alias = client.put(
        "/api/v1/approvals/fx-date-rules",
        headers=h,
        json={"invoice_type": "freight", "rate_date_basis": "arrival", "active": True},
    )
    assert up_alias.status_code == 200, up_alias.text
    assert up_alias.json()["invoice_type"] == "FRT"
    assert up_alias.json()["rate_date_basis"] == "arrival"

    rows = client.get("/api/v1/approvals/fx-date-rules", headers=h).json()["items"]
    assert len(rows) == 1 and rows[0]["rate_date_basis"] == "arrival"

    got = client.get("/api/v1/approvals/fx-date-rules/freight", headers=h).json()
    assert got["is_default"] is False
    assert got["rate_date_basis"] == "arrival"

    bad_basis = client.put(
        "/api/v1/approvals/fx-date-rules",
        headers=h,
        json={"invoice_type": "DEM", "rate_date_basis": "moon_phase"},
    )
    assert bad_basis.status_code == 422
    assert bad_basis.json()["detail"]["code"] == "INVALID_RATE_DATE_BASIS"

    bad_type = client.put(
        "/api/v1/approvals/fx-date-rules",
        headers=h,
        json={"invoice_type": "NOT_A_TYPE", "rate_date_basis": "invoice"},
    )
    assert bad_type.status_code == 422
    assert bad_type.json()["detail"]["code"] == "INVALID_INVOICE_TYPE"


def test_fx_rate_consumes_rule_with_context_date(client, auth_headers, db_session):
    """Rule + context_date → as-of rate; no rule → unchanged latest-rate default."""
    from app.models_wave1 import ExchangeRate
    from app.services.fx_date_rules import resolve_fx_rate, upsert_rule

    tid = _demo_tenant_id(db_session)
    for rdate, rate in ((date(2026, 1, 1), Decimal("0.50")), (date(2026, 6, 1), Decimal("0.80"))):
        db_session.add(
            ExchangeRate(
                tenant_id=tid,
                base_currency="CNY",
                quote_currency="USD",
                rate=rate,
                rate_date=rdate,
                source="test",
            )
        )
    db_session.commit()

    # No rule row → absolute latest (unchanged default), even with a context date
    latest = resolve_fx_rate(db_session, tid, "CNY", "USD", invoice_type="FRT", context_date=date(2026, 2, 1))
    assert latest == Decimal("0.80")

    upsert_rule(db_session, tid, "FRT", "departure")
    db_session.commit()

    as_of = resolve_fx_rate(db_session, tid, "CNY", "USD", invoice_type="FRT", context_date=date(2026, 2, 1))
    assert as_of == Decimal("0.50")

    # Rule alone without a context date keeps the latest-rate behaviour
    no_ctx = resolve_fx_rate(db_session, tid, "CNY", "USD", invoice_type="FRT")
    assert no_ctx == Decimal("0.80")


def test_fx_rate_date_basis_resolution():
    from app.services.fx_date_rules import (
        DEFAULT_RATE_DATE_BASIS,
        pick_rate_date,
        validate_rate_date_basis,
    )

    assert DEFAULT_RATE_DATE_BASIS == "invoice"
    assert validate_rate_date_basis("departure") == "departure"
    with pytest.raises(ValueError):
        validate_rate_date_basis("nope")
    assert pick_rate_date("arrival", {"arrival_date": "2026-03-05"}) == date(2026, 3, 5)
    assert pick_rate_date("posted", {"gmt_date": date(2026, 3, 6)}) == date(2026, 3, 6)
    assert pick_rate_date("departure", {"arrival": "2026-03-05"}) is None


# ── Feature 3: invoice type completeness ────────────────────────────────────


def test_invoice_type_registry_mapping():
    from app.services.invoice_types import (
        CANONICAL_INVOICE_TYPES,
        normalize_invoice_type,
        is_valid_invoice_type,
    )

    assert set(CANONICAL_INVOICE_TYPES) == {
        "FRT", "DEM", "TCIP", "TCOB", "PDA", "FDA", "BKR", "XEXP", "XREV", "XDIFF",
    }
    assert normalize_invoice_type("freight") == "FRT"
    assert normalize_invoice_type("demurrage") == "DEM"
    assert normalize_invoice_type("hire") == "TCIP"
    assert normalize_invoice_type("port_disbursement") == "PDA"
    assert normalize_invoice_type("port_da") == "FDA"
    assert normalize_invoice_type("bunker") == "BKR"
    assert normalize_invoice_type("credit_note") == "XREV"
    assert normalize_invoice_type("FRT") == "FRT"
    assert is_valid_invoice_type("tc_hire")
    assert not is_valid_invoice_type("bogus")


def test_invoice_type_validation(client, auth_headers):
    h = auth_headers
    # canonical plan code
    ok_code = client.post("/api/v1/invoices", headers=h, json={"invoice_type": "XEXP", "amount": 1})
    assert ok_code.status_code == 200, ok_code.text
    # back-compat legacy alias stays valid and is stored as given
    ok_alias = client.post("/api/v1/invoices", headers=h, json={"invoice_type": "freight", "amount": 1})
    assert ok_alias.status_code == 200, ok_alias.text
    inv = client.get(f"/api/v1/invoices/{ok_alias.json()['id']}", headers=h).json()
    assert inv["invoice_type"] == "freight"

    for legacy in ("hire", "demurrage", "bunker", "port_disbursement", "credit_note", "other"):
        ok = client.post("/api/v1/invoices", headers=h, json={"invoice_type": legacy, "amount": 1})
        assert ok.status_code == 200, (legacy, ok.text)

    bad = client.post("/api/v1/invoices", headers=h, json={"invoice_type": "bogus", "amount": 1})
    assert bad.status_code == 422
    detail = bad.json()["detail"]
    assert detail["code"] == "INVALID_INVOICE_TYPE"
    assert "FRT" in detail["canonical_codes"]
    assert "freight" in detail["valid_types"]
    assert "BKR" in detail["valid_types"]
