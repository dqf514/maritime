"""Excel-compatible CSV exports — /export/{entity}.csv."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import Tenant, TenantModuleLicense

ZH_HEADERS = {
    "voyages": "航次号",
    "invoices": "发票号",
    "certificates": "船名",
    "tasks": "标题",
    "vessels": "船名",
}
EN_HEADERS = {
    "voyages": "Voyage No",
    "invoices": "Invoice No",
    "certificates": "Vessel",
    "tasks": "Title",
    "vessels": "Name",
}


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def _login(client, email="admin@demo.marios", tenant="demo", password="Demo1234!"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password, "tenant_code": tenant})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _get_csv(client, entity, headers, lang=None):
    url = f"/api/v1/export/{entity}.csv"
    if lang:
        url += f"?lang={lang}"
    r = client.get(url, headers=headers)
    assert r.status_code == 200, f"{entity}: {r.text}"
    assert "text/csv" in r.headers["content-type"]
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("attachment; filename=")
    assert re.match(rf'attachment; filename="{entity}_\d{{8}}\.csv"', disposition)
    assert r.content.startswith(b"\xef\xbb\xbf"), f"{entity}: missing UTF-8 BOM"
    return r.content.decode("utf-8-sig")


def test_export_all_entities_headers_bilingual(client, auth_headers):
    for entity in ZH_HEADERS:
        text = _get_csv(client, entity, auth_headers)
        assert text.splitlines()[0].startswith(ZH_HEADERS[entity]), f"{entity}: zh header"
        text_en = _get_csv(client, entity, auth_headers, lang="en")
        assert text_en.splitlines()[0].startswith(EN_HEADERS[entity]), f"{entity}: en header"


def test_export_voyages_contains_seeded_rows(client, auth_headers):
    voyages = client.get("/api/v1/voyages", headers=auth_headers).json()
    assert voyages
    text = _get_csv(client, "voyages", auth_headers)
    for v in voyages:
        assert v["voyage_no"] in text


def test_export_invoices_contains_seeded_rows(client, auth_headers):
    invoices = client.get("/api/v1/invoices", headers=auth_headers).json()
    assert invoices
    text = _get_csv(client, "invoices", auth_headers)
    for inv in invoices:
        assert inv["invoice_no"] in text


def test_export_certificates_contains_seeded_rows(client, auth_headers):
    certs = client.get("/api/v1/ship/certificates", headers=auth_headers).json()
    assert certs
    text = _get_csv(client, "certificates", auth_headers)
    for c in certs:
        assert c["cert_code"] in text
    assert "剩余天数" in text.splitlines()[0]


def test_export_vessels_contains_seeded_rows(client, auth_headers):
    vessels = client.get("/api/v1/masterdata/vessels", headers=auth_headers).json()
    assert vessels
    text = _get_csv(client, "vessels", auth_headers)
    for v in vessels:
        assert v["name"] in text
        assert (v.get("imo") or "") in text


def test_export_tasks_my_scope(client):
    admin = _login(client)
    uniq_title = f"Export task {id(admin)}"
    r = client.post("/api/v1/tasks", headers=admin, json={"title": uniq_title})
    assert r.status_code == 200, r.text
    other = _login(client, email="charterer@demo.marios")
    r = client.post("/api/v1/tasks", headers=other, json={"title": "Charterer private task"})
    assert r.status_code == 200, r.text

    text = _get_csv(client, "tasks", admin)
    assert uniq_title in text
    assert "Charterer private task" not in text  # my-scope only

    text_other = _get_csv(client, "tasks", other)
    assert "Charterer private task" in text_other
    assert uniq_title not in text_other


def test_export_unknown_entity_404(client, auth_headers):
    r = client.get("/api/v1/export/unicorns.csv", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "EXPORT_NOT_FOUND"


def test_export_requires_login(client):
    for entity in ZH_HEADERS:
        assert client.get(f"/api/v1/export/{entity}.csv").status_code == 401


def test_export_module_gate_403(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "license_dev_unlock", "none")
    tenant = db_session.scalar(select(Tenant).where(Tenant.code == "demo"))
    db_session.execute(
        delete(TenantModuleLicense).where(
            TenantModuleLicense.tenant_id == tenant.id,
            TenantModuleLicense.module_code == "finance",
        )
    )
    db_session.commit()
    blocked = client.get("/api/v1/export/invoices.csv", headers=auth_headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "MODULE_NOT_LICENSED"
    # tasks export is login-only, no module gate
    assert client.get("/api/v1/export/tasks.csv", headers=auth_headers).status_code == 200


def test_export_tenant_isolation(client, auth_headers):
    # a vessel created in another tenant must not appear in the demo export
    from uuid import uuid4

    from tests.isolation_helpers import create_tenant

    uniq = uuid4().hex[:6]
    _, foreign = create_tenant(client, code=f"exp{uniq}", name=f"Exp {uniq}", admin_email=f"exp-{uniq}@example.com")
    marker = f"FOREIGN VESSEL {uniq}"
    r = client.post("/api/v1/masterdata/vessels", headers=foreign, json={"name": marker})
    assert r.status_code == 200, r.text

    text = _get_csv(client, "vessels", auth_headers)
    assert marker not in text
    foreign_text = _get_csv(client, "vessels", foreign)
    assert marker in foreign_text
