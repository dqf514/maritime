"""Multi-tenant isolation gate (DDS §18 — "租户隔离绿").

Two real tenants: ``demo`` (tenant A, seeded) and ``globex`` (tenant B,
created through the platform-admin API). The suite asserts a bidirectional
abuse matrix over the core resources:

- direct read / write / delete / transition on foreign IDs → 403/404, data untouched;
- list endpoints never leak foreign rows (incl. recycle bin);
- cross-tenant references on create/update are rejected with 404 (regression
  gate for the fixed commercial/finance/operations IDORs — every foreign
  vessel/counterparty/charter/estimate/voyage/port_call/laytime reference
  is validated via app.services.tenant_guard.scoped_get);
- platform_admin semantics are asserted separately (cross-tenant visibility
  via /platform/* is by design; business endpoints stay scoped to the
  caller's own tenant).

Ports (masterdata /ports) are global reference data by design — readable by
every tenant, writable only by tenant_admin/platform_admin — and are
therefore intentionally excluded from the cross-tenant matrix.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from tests.isolation_helpers import (
    API,
    assert_blocked,
    bootstrap_resources,
    create_tenant,
    make_recycle_entry,
    platform_login,
)


@pytest.fixture()
def tenant_b(client):
    """Second tenant 'globex' with a full set of own resources; returns (headers, ids)."""
    _, hb = create_tenant(client, code="globex", name="Globex Marine", admin_email="Admin@Globex.example.com")
    ids = bootstrap_resources(client, hb, "B")
    return hb, ids


def _ids(resp) -> set[str]:
    return {str(item.get("id")) for item in resp.json() if isinstance(item, dict) and item.get("id")}


# —— 1. Direct read: A cannot read B's resources by ID ——


def test_direct_read_cross_tenant_blocked(client, auth_headers, tenant_b):
    _, b = tenant_b
    ha = auth_headers
    gets = [
        f"/estimates/{b['estimate_id']}",
        f"/masterdata/vessels/{b['vessel_id']}",
        f"/masterdata/counterparties/{b['counterparty_id']}",
        f"/port-calls/{b['port_call_id']}/sof-summary",
        f"/laytimes/{b['laytime_id']}/export",
        f"/invoices/{b['invoice_id']}/payments",
        f"/invoices/{b['invoice_id']}/credit-notes",
        f"/charters/{b['charter_id']}/liftings",
        f"/charters/{b['charter_id']}/hire-summary",
        f"/charters/{b['charter_id']}/amendments",
        f"/voyages/{b['voyage_id']}/off-hire",
        f"/voyages/{b['voyage_id']}/bunker-allocation",
        f"/bunker-orders/{b['bunker_order_id']}/inquiries",
        f"/ship/work-orders/{b['work_order_id']}/spares",
    ]
    for path in gets:
        assert_blocked(client.get(f"{API}{path}", headers=ha), f"GET {path}")


# —— 2. Direct write: A cannot mutate / transition / delete B's resources ——


def test_direct_write_cross_tenant_blocked_and_data_untouched(client, auth_headers, tenant_b):
    hb, b = tenant_b
    ha = auth_headers
    attacks = [
        ("put", f"/estimates/{b['estimate_id']}", {"json": {"title": "HACKED"}}),
        ("delete", f"/estimates/{b['estimate_id']}", {}),
        ("post", f"/estimates/{b['estimate_id']}/calculate", {}),
        ("post", f"/estimates/{b['estimate_id']}/clone", {}),
        ("patch", f"/charters/{b['charter_id']}", {"json": {"commission_pct": 99}}),
        ("delete", f"/charters/{b['charter_id']}", {}),
        ("post", f"/charters/{b['charter_id']}/transition", {"json": {"target": "active"}}),
        ("patch", f"/voyages/{b['voyage_id']}", {"json": {"cargo": "HACKED"}}),
        ("delete", f"/voyages/{b['voyage_id']}", {}),
        ("post", f"/voyages/{b['voyage_id']}/transition", {"json": {"target": "in_progress"}}),
        ("put", f"/laytimes/{b['laytime_id']}", {"json": {"inputs": {"allowed_hours": 1}}}),
        ("delete", f"/laytimes/{b['laytime_id']}", {}),
        ("post", f"/laytimes/{b['laytime_id']}/calculate", {}),
        ("post", f"/laytimes/{b['laytime_id']}/finalize", {}),
        ("patch", f"/claims/{b['claim_id']}", {"json": {"amount": 1}}),
        ("delete", f"/claims/{b['claim_id']}", {}),
        ("post", f"/claims/{b['claim_id']}/transition", {"params": {"target": "negotiating"}}),
        ("post", f"/claims/{b['claim_id']}/to-invoice", {}),
        ("patch", f"/invoices/{b['invoice_id']}", {"json": {"amount": 1}}),
        ("delete", f"/invoices/{b['invoice_id']}", {}),
        ("post", f"/invoices/{b['invoice_id']}/transition", {"params": {"target": "issued"}}),
        ("post", f"/invoices/{b['invoice_id']}/payments", {"params": {"amount": 1}}),
        ("post", f"/invoices/{b['invoice_id']}/credit-note", {"json": {"amount": 1}}),
        ("post", f"/invoices/{b['invoice_id']}/gl-post", {}),
        ("patch", f"/bunker-orders/{b['bunker_order_id']}", {"json": {"unit_price": 1}}),
        ("post", f"/bunker-orders/{b['bunker_order_id']}/transition", {"params": {"target": "confirmed"}}),
        ("post", f"/bunker-orders/{b['bunker_order_id']}/inquiries", {"json": {"supplier": "evil", "quoted_price": 1}}),
        ("patch", f"/masterdata/vessels/{b['vessel_id']}", {"json": {"name": "HACKED"}}),
        ("delete", f"/masterdata/vessels/{b['vessel_id']}", {}),
        ("patch", f"/masterdata/counterparties/{b['counterparty_id']}", {"json": {"name": "HACKED", "type": "charterer"}}),
        ("delete", f"/masterdata/counterparties/{b['counterparty_id']}", {}),
        ("patch", f"/ship/work-orders/{b['work_order_id']}", {"json": {"status": "done"}}),
        ("post", f"/ship/work-orders/{b['work_order_id']}/spares", {"json": {"part_id": str(uuid4()), "qty": 1}}),
        ("patch", f"/admin/users/{b['user_id']}", {"json": {"full_name": "HACKED"}}),
        ("delete", f"/admin/users/{b['user_id']}", {}),
        ("put", f"/admin/users/{b['user_id']}/roles", {"json": {"role_codes": ["tenant_admin"]}}),
    ]
    for method, path, kw in attacks:
        resp = getattr(client, method)(f"{API}{path}", headers=ha, **kw)
        assert_blocked(resp, f"{method.upper()} {path}")

    # B's view: everything untouched and still present
    est = client.get(f"{API}/estimates/{b['estimate_id']}", headers=hb)
    assert est.status_code == 200 and est.json()["title"].startswith("B EST")
    vessel = client.get(f"{API}/masterdata/vessels/{b['vessel_id']}", headers=hb)
    assert vessel.status_code == 200 and vessel.json()["name"].startswith("B Vessel")
    cp = client.get(f"{API}/masterdata/counterparties/{b['counterparty_id']}", headers=hb)
    assert cp.status_code == 200 and cp.json()["name"].startswith("B CP")

    charters = client.get(f"{API}/charters", headers=hb).json()
    assert any(c["id"] == b["charter_id"] and c["status"] == "draft" for c in charters)
    voyages = client.get(f"{API}/voyages", headers=hb).json()
    assert any(v["id"] == b["voyage_id"] and v["status"] == "planned" and v["cargo"] is None for v in voyages)
    laytimes = client.get(f"{API}/laytimes", headers=hb).json()
    assert any(l["id"] == b["laytime_id"] and l["status"] == "draft" for l in laytimes)
    claims = client.get(f"{API}/claims", headers=hb).json()
    assert any(c["id"] == b["claim_id"] and c["amount"] == 1000 for c in claims)
    invoices = client.get(f"{API}/invoices", headers=hb).json()
    assert any(i["id"] == b["invoice_id"] and i["amount"] == 500 and i["status"] == "draft" for i in invoices)
    bunkers = client.get(f"{API}/bunker-orders", headers=hb).json()
    assert any(o["id"] == b["bunker_order_id"] and o["unit_price"] == 600 for o in bunkers)
    orders = client.get(f"{API}/ship/work-orders", headers=hb).json()
    assert any(w["id"] == b["work_order_id"] and w["status"] == "open" for w in orders)
    users = client.get(f"{API}/admin/users", headers=hb).json()
    assert any(u["id"] == b["user_id"] and u["full_name"].startswith("B Crew") for u in users)


# —— 3. Lists: A's list endpoints never contain B's rows ——


def test_lists_are_tenant_scoped(client, auth_headers, tenant_b):
    _, b = tenant_b
    ha = auth_headers
    foreign = set(b.values())
    lists = [
        "/estimates",
        "/charters",
        "/voyages",
        "/port-calls",
        "/laytimes",
        "/claims",
        "/invoices",
        "/bunker-orders",
        "/ship/work-orders",
        "/masterdata/vessels",
        "/masterdata/counterparties",
        "/admin/users",
    ]
    for path in lists:
        resp = client.get(f"{API}{path}", headers=ha)
        assert resp.status_code == 200, f"GET {path} -> {resp.status_code}"
        leaked = _ids(resp) & foreign
        assert not leaked, f"GET {path} leaked B rows: {leaked}"

    # ports are global reference data by design (readable by every tenant),
    # so /masterdata/ports is intentionally excluded from the matrix above
    ports = client.get(f"{API}/masterdata/ports", headers=ha)
    assert ports.status_code == 200


# —— 4. Reference rejection (regression gate for already-fixed IDORs) ——


def test_cross_tenant_reference_rejected_on_create(client, auth_headers, tenant_b):
    _, b = tenant_b
    ha = auth_headers
    attacks = [
        ("post", "/charters", {"json": {"charter_type": "voyage", "counterparty_id": b["counterparty_id"]}}),
        ("post", "/invoices", {"json": {"counterparty_id": b["counterparty_id"], "amount": 100}}),
        ("post", "/invoices", {"json": {"voyage_id": b["voyage_id"], "amount": 100}}),
        ("post", "/port-calls", {"json": {"voyage_id": b["voyage_id"], "seq": 9}}),
        ("post", "/noon-reports", {"json": {"voyage_id": b["voyage_id"], "report_at": "2025-01-01T00:00:00Z"}}),
        (
            "post",
            "/invoices/hire-schedule",
            {"json": {"charter_id": b["charter_id"], "period_start": "2025-01-01", "period_end": "2025-02-01"}},
        ),
        ("post", "/laytimes/from-sof", {"json": {"port_call_id": b["port_call_id"], "allowed_hours": 24}}),
        ("post", "/bunker-orders", {"json": {"counterparty_id": b["counterparty_id"], "qty_ordered": 10, "unit_price": 500}}),
        ("post", "/ship/work-orders", {"json": {"vessel_id": b["vessel_id"], "wo_no": f"WO-X{uuid4().hex[:5]}", "title": "x"}}),
        ("post", "/portal/messages", {"params": {"counterparty_id": b["counterparty_id"], "subject": "hi"}}),
    ]
    for method, path, kw in attacks:
        resp = getattr(client, method)(f"{API}{path}", headers=ha, **kw)
        assert_blocked(resp, f"{method.upper()} {path} (foreign reference)")


# —— 5. Reference rejection on create/update (fixed IDORs — regression gate) ——


def test_estimate_rejects_foreign_references(client, auth_headers, tenant_b):
    _, b = tenant_b
    ha = auth_headers
    r = client.post(
        f"{API}/estimates",
        headers=ha,
        json={"title": "x", "vessel_id": b["vessel_id"], "counterparty_id": b["counterparty_id"]},
    )
    assert r.status_code == 404
    own = bootstrap_resources(client, ha, "A")
    r2 = client.put(f"{API}/estimates/{own['estimate_id']}", headers=ha, json={"counterparty_id": b["counterparty_id"]})
    assert r2.status_code == 404


def test_charter_create_rejects_foreign_vessel_and_estimate(client, auth_headers, tenant_b):
    _, b = tenant_b
    ha = auth_headers
    r = client.post(
        f"{API}/charters",
        headers=ha,
        json={"charter_type": "voyage", "vessel_id": b["vessel_id"], "estimate_id": b["estimate_id"]},
    )
    assert r.status_code == 404


def test_voyage_rejects_foreign_references(client, auth_headers, tenant_b):
    _, b = tenant_b
    ha = auth_headers
    r = client.post(
        f"{API}/voyages",
        headers=ha,
        json={"voyage_no": f"VX-{uuid4().hex[:6]}", "vessel_id": b["vessel_id"], "charter_id": b["charter_id"]},
    )
    assert r.status_code == 404
    own = bootstrap_resources(client, ha, "A")
    r2 = client.patch(f"{API}/voyages/{own['voyage_id']}", headers=ha, json={"vessel_id": b["vessel_id"]})
    assert r2.status_code == 404


def test_laytime_rejects_foreign_references(client, auth_headers, tenant_b):
    _, b = tenant_b
    ha = auth_headers
    r = client.post(
        f"{API}/laytimes",
        headers=ha,
        json={"voyage_id": b["voyage_id"], "port_call_id": b["port_call_id"], "inputs": {}},
    )
    assert r.status_code == 404
    own = bootstrap_resources(client, ha, "A")
    r2 = client.put(f"{API}/laytimes/{own['laytime_id']}", headers=ha, json={"voyage_id": b["voyage_id"]})
    assert r2.status_code == 404


def test_claim_create_rejects_foreign_references(client, auth_headers, tenant_b):
    _, b = tenant_b
    ha = auth_headers
    r = client.post(
        f"{API}/claims",
        headers=ha,
        json={"voyage_id": b["voyage_id"], "laytime_id": b["laytime_id"]},
    )
    assert r.status_code == 404


def test_bunker_order_rejects_foreign_references(client, auth_headers, tenant_b):
    _, b = tenant_b
    ha = auth_headers
    r = client.post(
        f"{API}/bunker-orders",
        headers=ha,
        json={"vessel_id": b["vessel_id"], "voyage_id": b["voyage_id"], "qty_ordered": 10, "unit_price": 500},
    )
    assert r.status_code == 404
    own = bootstrap_resources(client, ha, "A")
    r2 = client.patch(f"{API}/bunker-orders/{own['bunker_order_id']}", headers=ha, json={"voyage_id": b["voyage_id"]})
    assert r2.status_code == 404


# —— 6. Recycle bin isolation ——


def test_recycle_bin_isolation(client, auth_headers, tenant_b):
    hb, _ = tenant_b
    ha = auth_headers
    item_id, vessel_id = make_recycle_entry(client, hb)

    own = client.get(f"{API}/recycle-bin", headers=ha)
    assert own.status_code == 200
    leaked = [i for i in own.json() if i["id"] == item_id or i["entity_id"] == vessel_id]
    assert not leaked, f"A's recycle bin leaked B's entry: {leaked}"

    restore = client.post(f"{API}/recycle-bin/{item_id}/restore", headers=ha)
    assert_blocked(restore, "POST /recycle-bin/{id}/restore (foreign item)")
    purge = client.delete(f"{API}/recycle-bin/{item_id}", headers=ha)
    assert_blocked(purge, "DELETE /recycle-bin/{id} (foreign item)")

    # B's entry is untouched and restorable by B
    ok = client.post(f"{API}/recycle-bin/{item_id}/restore", headers=hb)
    assert ok.status_code == 200, ok.text


# —— 7. Bidirectional symmetry: B cannot reach A either ——


def test_isolation_is_bidirectional(client, auth_headers, tenant_b):
    hb, b = tenant_b
    ha = auth_headers
    a = bootstrap_resources(client, ha, "A")

    assert_blocked(client.get(f"{API}/estimates/{a['estimate_id']}", headers=hb), "B GET A estimate")
    assert_blocked(
        client.patch(f"{API}/invoices/{a['invoice_id']}", headers=hb, json={"amount": 1}), "B PATCH A invoice"
    )
    assert_blocked(
        client.post(f"{API}/charters", headers=hb, json={"charter_type": "voyage", "counterparty_id": a["counterparty_id"]}),
        "B POST charter referencing A counterparty",
    )
    invoices_b = client.get(f"{API}/invoices", headers=hb).json()
    assert a["invoice_id"] not in {i["id"] for i in invoices_b}
    users_b = client.get(f"{API}/admin/users", headers=hb).json()
    assert a["user_id"] not in {u["id"] for u in users_b}


# —— 8. platform_admin semantics (cross-tenant is by design on /platform/*) ——


def test_platform_admin_semantics(client, auth_headers):
    ha = auth_headers
    tenant_id, hb = create_tenant(client, code="globex", name="Globex Marine", admin_email="Admin@Globex.example.com")
    b = bootstrap_resources(client, hb, "B")
    hp = platform_login(client)

    # by design: platform admin sees and manages all tenants via /platform/*
    tenants = client.get(f"{API}/platform/tenants", headers=hp)
    assert tenants.status_code == 200
    codes = {t["code"] for t in tenants.json()}
    assert {"demo", "globex"} <= codes
    detail = client.get(f"{API}/platform/tenants/{tenant_id}", headers=hp)
    assert detail.status_code == 200 and detail.json()["code"] == "globex"

    # tenant admins are not platform operators
    forbidden = client.get(f"{API}/platform/tenants", headers=ha)
    assert forbidden.status_code == 403
    forbidden_b = client.get(f"{API}/platform/tenants", headers=hb)
    assert forbidden_b.status_code == 403

    # business endpoints always scope by the *caller's* tenant (sys for ops):
    # platform admin does NOT see tenant rows through business lists or IDs
    inv = client.get(f"{API}/invoices", headers=hp)
    assert inv.status_code == 200
    assert b["invoice_id"] not in {i["id"] for i in inv.json()}
    assert_blocked(client.get(f"{API}/estimates/{b['estimate_id']}", headers=hp), "platform ops GET B estimate")


# —— 9. tenant_guard service unit tests (no HTTP) ——


def _session(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)()


def _two_tenants(db):
    from app.models import Tenant

    demo = db.scalar(select(Tenant).where(Tenant.code == "demo"))
    assert demo is not None
    other = Tenant(name="Isolation T2", code="iso-t2", status="active", profile_tier="M", default_locale="en", default_timezone="UTC")
    db.add(other)
    db.flush()
    return demo, other


def test_scoped_get_honors_tenant_and_soft_delete(db_engine):
    from app.models_wave1 import Vessel
    from app.services.tenant_guard import scoped_get

    with _session(db_engine) as db:
        demo, other = _two_tenants(db)
        v1 = Vessel(tenant_id=demo.id, name="GUARD-V1", status="active")
        v2 = Vessel(tenant_id=other.id, name="GUARD-V2", status="active")
        vd = Vessel(tenant_id=demo.id, name="GUARD-VD", status="active", deleted_at=datetime.now(timezone.utc))
        db.add_all([v1, v2, vd])
        db.commit()

        assert scoped_get(db, Vessel, v1.id, demo.id) is not None
        assert scoped_get(db, Vessel, v2.id, demo.id) is None  # cross-tenant → None
        assert scoped_get(db, Vessel, uuid4(), demo.id) is None  # missing → None
        assert scoped_get(db, Vessel, vd.id, demo.id) is None  # soft-deleted → None
        assert scoped_get(db, Vessel, vd.id, demo.id, include_deleted=True) is not None


def test_scoped_get_status_only_soft_delete(db_engine):
    from app.models_domain import Estimate
    from app.services.tenant_guard import scoped_get

    with _session(db_engine) as db:
        demo, other = _two_tenants(db)
        e1 = Estimate(tenant_id=demo.id, title="GUARD-E1", status="draft")
        e2 = Estimate(tenant_id=other.id, title="GUARD-E2", status="draft")
        e3 = Estimate(tenant_id=demo.id, title="GUARD-E3", status="deleted")  # status-based deletion, no deleted_at column
        db.add_all([e1, e2, e3])
        db.commit()

        assert scoped_get(db, Estimate, e1.id, demo.id) is not None
        assert scoped_get(db, Estimate, e2.id, demo.id) is None
        assert scoped_get(db, Estimate, e3.id, demo.id) is None
        assert scoped_get(db, Estimate, e3.id, demo.id, include_deleted=True) is not None


def test_scoped_query_filters_tenant_and_deleted(db_engine):
    from app.models_domain import Estimate
    from app.models_wave1 import Vessel
    from app.services.tenant_guard import scoped_query

    with _session(db_engine) as db:
        demo, other = _two_tenants(db)
        v1 = Vessel(tenant_id=demo.id, name="GUARD-Q-V1", status="active")
        v2 = Vessel(tenant_id=other.id, name="GUARD-Q-V2", status="active")
        vd = Vessel(tenant_id=demo.id, name="GUARD-Q-VD", status="active", deleted_at=datetime.now(timezone.utc))
        e1 = Estimate(tenant_id=demo.id, title="GUARD-Q-E1", status="draft")
        e3 = Estimate(tenant_id=demo.id, title="GUARD-Q-E3", status="deleted")
        db.add_all([v1, v2, vd, e1, e3])
        db.commit()

        # deleted_at-style model
        rows = db.scalars(scoped_query(db, Vessel, demo.id).order_by(Vessel.name)).all()
        names = {r.name for r in rows}
        assert "GUARD-Q-V1" in names
        assert "GUARD-Q-V2" not in names  # other tenant
        assert "GUARD-Q-VD" not in names  # soft-deleted
        all_rows = db.scalars(scoped_query(db, Vessel, demo.id, include_deleted=True)).all()
        assert "GUARD-Q-VD" in {r.name for r in all_rows}

        # status-style model; chained clauses still work on the returned Select
        ests = db.scalars(scoped_query(db, Estimate, demo.id).where(Estimate.title.like("GUARD-Q-%"))).all()
        titles = {e.title for e in ests}
        assert titles == {"GUARD-Q-E1"}
