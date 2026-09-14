"""P3 observability & audit trail tests.

Covers: X-Request-ID middleware, audit rows for login success/failure,
the /admin/security/audit-logs endpoint (RBAC + tenant isolation), and an
import smoke test for the Alembic environment (no migration is run).
"""

import importlib.util
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_audit import AuditLog

from tests.isolation_helpers import create_tenant, login

API = "/api/v1"


def _audit_rows(db_engine, action: str | None = None) -> list[AuditLog]:
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        stmt = select(AuditLog)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        return db.scalars(stmt.order_by(AuditLog.created_at)).all()


# —— Request ID middleware ——
def test_request_id_generated(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    rid = r.headers.get("x-request-id")
    assert rid, "X-Request-ID response header missing"
    uuid.UUID(rid)  # must be a valid uuid4


def test_request_id_propagated(client):
    r = client.get("/healthz", headers={"X-Request-ID": "req-fixed-123"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "req-fixed-123"


# —— Audit rows on login ——
def test_audit_login_success(client, db_engine):
    r = client.post(
        f"{API}/auth/login",
        json={"email": "admin@demo.voyageos", "password": "Demo1234!", "tenant_code": "demo"},
    )
    assert r.status_code == 200, r.text
    rows = _audit_rows(db_engine, "auth.login_success")
    assert len(rows) == 1
    row = rows[0]
    assert row.entity_type == "user"
    assert (row.detail or {}).get("email") == "admin@demo.voyageos"
    assert row.tenant_id is not None
    assert row.actor_user_id is not None
    assert row.ip  # TestClient supplies a client host


def test_audit_login_failure(client, db_engine):
    r = client.post(
        f"{API}/auth/login",
        json={"email": "admin@demo.voyageos", "password": "wrong-password", "tenant_code": "demo"},
    )
    assert r.status_code == 401
    rows = _audit_rows(db_engine, "auth.login_failed")
    assert len(rows) == 1
    row = rows[0]
    assert (row.detail or {}).get("reason") == "bad_credentials"
    # Failure rows are committed even though the request raised (401)
    assert row.tenant_id is not None


def test_audit_login_unknown_tenant(client, db_engine):
    r = client.post(
        f"{API}/auth/login",
        json={"email": "nobody@example.com", "password": "x", "tenant_code": "no-such-tenant"},
    )
    assert r.status_code == 401
    rows = _audit_rows(db_engine, "auth.login_failed")
    assert len(rows) == 1
    assert (rows[0].detail or {}).get("reason") == "unknown_tenant"
    assert rows[0].tenant_id is None


# —— /admin/security/audit-logs endpoint ——
def test_audit_logs_endpoint_admin(client, auth_headers):
    # auth_headers itself performed a successful login, so at least one row exists
    r = client.get(f"{API}/admin/security/audit-logs", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    actions = {i["action"] for i in body["items"]}
    assert "auth.login_success" in actions


def test_audit_logs_endpoint_pagination(client, auth_headers):
    r = client.get(
        f"{API}/admin/security/audit-logs",
        headers=auth_headers,
        params={"action": "auth.login_success", "limit": 1, "offset": 0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["action"] == "auth.login_success"
    assert body["total"] >= 1


def test_audit_logs_endpoint_forbidden_for_non_admin(client):
    headers = login(client, "charterer@demo.voyageos")
    r = client.get(f"{API}/admin/security/audit-logs", headers=headers)
    assert r.status_code == 403


def test_audit_logs_tenant_isolation(client, auth_headers):
    # A second real tenant whose admin performs a login (audited in tenant B)
    _, tenant_b_headers = create_tenant(
        client, code="tenantb", name="Tenant B", admin_email="boss@tenantb.example"
    )
    r_b = client.get(f"{API}/admin/security/audit-logs", headers=tenant_b_headers)
    assert r_b.status_code == 200, r_b.text
    assert r_b.json()["total"] >= 1

    # Demo tenant admin must not see tenant B's rows
    r_a = client.get(f"{API}/admin/security/audit-logs", headers=auth_headers, params={"limit": 200})
    assert r_a.status_code == 200, r_a.text
    items = r_a.json()["items"]
    assert items, "expected audit rows for demo tenant"
    demo_tenant_ids = {i["tenant_id"] for i in items if i["tenant_id"]}
    assert len(demo_tenant_ids) == 1  # every row belongs to the demo tenant
    emails = {i["detail"].get("email") for i in items}
    assert "boss@tenantb.example" not in emails


# —— Alembic env import smoke test (does NOT run migrations) ——
def test_alembic_env_importable():
    api_root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("voyageos_alembic_env", api_root / "alembic" / "env.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # must not connect to a database or raise
    assert mod.target_metadata is not None
    assert "audit_logs" in mod.target_metadata.tables
    assert "users" in mod.target_metadata.tables


def test_alembic_baseline_revision_exists():
    api_root = Path(__file__).resolve().parent.parent
    versions = list((api_root / "alembic" / "versions").glob("*.py"))
    assert versions, "no alembic revisions found"
    baseline = versions[0].read_text(encoding="utf-8")
    assert "down_revision = None" in baseline
