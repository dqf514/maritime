"""Certificate file upload, versioning, download auth and certificate CRUD."""

from __future__ import annotations

import io
from datetime import date, timedelta

from tests.isolation_helpers import create_tenant

API = "/api/v1"
PDF = b"%PDF-1.4\n% demo certificate payload\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
EXE_IN_PDF_CLOTHING = b"MZ\x90\x00" + b"\x00" * 64


def _vessel_id(client, h) -> str:
    fleet = client.get(f"{API}/ship/fleet", headers=h)
    assert fleet.status_code == 200, fleet.text
    return fleet.json()["vessels"][0]["vessel_id"]


def _make_cert(client, h, code: str = "CERT-F1", expires_on: date | None = None) -> str:
    r = client.post(
        f"{API}/ship/certificates",
        headers=h,
        json={
            "vessel_id": _vessel_id(client, h),
            "cert_code": code,
            "cert_name": f"Cert {code}",
            "expires_on": expires_on.isoformat() if expires_on else None,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload(client, h, cert_id: str, content: bytes = PDF, filename: str = "cert.pdf", note: str | None = None):
    data = {"note": note} if note is not None else {}
    return client.post(
        f"{API}/ship/certificates/{cert_id}/files",
        headers=h,
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        data=data,
    )


def test_upload_pdf_and_png_ok(client, auth_headers):
    h = auth_headers
    cert_id = _make_cert(client, h, "CERT-UP1")
    r = _upload(client, h, cert_id, PDF, "safety cert.pdf", note="initial scan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version_no"] == 1
    assert body["is_current"] is True
    assert body["file_name"] == "safety cert.pdf"
    assert body["note"] == "initial scan"
    assert body["entity_type"] == "ship_certificate"
    assert body["download_url"].endswith(f"/files/{body['id']}/download")
    r2 = _upload(client, h, cert_id, PNG, "endorsement.png")
    assert r2.status_code == 200, r2.text
    assert r2.json()["version_no"] == 2


def test_disguised_exe_rejected(client, auth_headers):
    cert_id = _make_cert(client, auth_headers, "CERT-EXE")
    r = _upload(client, auth_headers, cert_id, EXE_IN_PDF_CLOTHING, "totally-legit.pdf")
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "INVALID_CONTENT"


def test_oversize_rejected(client, auth_headers):
    cert_id = _make_cert(client, auth_headers, "CERT-BIG")
    big = b"%PDF" + b"\x00" * (10 * 1024 * 1024)
    r = _upload(client, auth_headers, cert_id, big, "huge.pdf")
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "FILE_TOO_LARGE"


def test_unsupported_extension_rejected(client, auth_headers):
    cert_id = _make_cert(client, auth_headers, "CERT-SVG")
    r = _upload(client, auth_headers, cert_id, b"<svg></svg>", "vector.svg")
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "UNSUPPORTED_TYPE"


def test_versions_and_set_current(client, auth_headers):
    h = auth_headers
    cert_id = _make_cert(client, h, "CERT-VER")
    v1 = _upload(client, h, cert_id, PDF, "v1.pdf").json()
    v2 = _upload(client, h, cert_id, PDF, "v2.pdf").json()
    v3 = _upload(client, h, cert_id, PNG, "v3.png").json()

    files = client.get(f"{API}/ship/certificates/{cert_id}/files", headers=h)
    assert files.status_code == 200, files.text
    rows = files.json()
    assert [r["version_no"] for r in rows] == [3, 2, 1]
    by_id = {r["id"]: r for r in rows}
    assert by_id[v3["id"]]["is_current"] is True
    assert by_id[v1["id"]]["is_current"] is False
    assert by_id[v2["id"]]["is_current"] is False

    r = client.post(f"{API}/files/{v1['id']}/current", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["is_current"] is True
    rows = client.get(f"{API}/ship/certificates/{cert_id}/files", headers=h).json()
    by_id = {r["id"]: r for r in rows}
    assert by_id[v1["id"]]["is_current"] is True
    assert by_id[v3["id"]]["is_current"] is False


def test_download_auth_and_tenant_isolation(client, auth_headers):
    h = auth_headers
    cert_id = _make_cert(client, h, "CERT-DL")
    att = _upload(client, h, cert_id, PDF, "download me.pdf").json()

    r = client.get(att["download_url"], headers=h)
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")

    client.cookies.clear()
    r = client.get(att["download_url"])
    assert r.status_code == 401, r.text

    _, other_admin = create_tenant(client, code="othcert", name="Other Co", admin_email="other@example.com")
    r = client.get(att["download_url"], headers=other_admin)
    assert r.status_code == 404, r.text


def test_delete_file_removes_row_and_download(client, auth_headers):
    h = auth_headers
    cert_id = _make_cert(client, h, "CERT-DEL-F")
    att = _upload(client, h, cert_id, PDF, "gone.pdf").json()
    r = client.delete(f"{API}/files/{att['id']}", headers=h)
    assert r.status_code == 200, r.text
    assert client.get(att["download_url"], headers=h).status_code == 404
    assert client.get(f"{API}/ship/certificates/{cert_id}/files", headers=h).json() == []


def test_patch_certificate_recomputes_status(client, auth_headers):
    h = auth_headers
    cert_id = _make_cert(client, h, "CERT-PATCH", expires_on=date.today() + timedelta(days=200))
    r = client.patch(
        f"{API}/ship/certificates/{cert_id}",
        headers=h,
        json={"cert_name": "Renamed cert", "issuing_body": "DNV", "expires_on": (date.today() + timedelta(days=10)).isoformat()},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "expiring"
    rows = client.get(f"{API}/ship/certificates", headers=h, params={"vessel_id": _vessel_id(client, h)}).json()
    row = next(c for c in rows if c["id"] == cert_id)
    assert row["cert_name"] == "Renamed cert"
    assert row["issuing_body"] == "DNV"
    assert row["days_to_expiry"] == 10


def test_delete_certificate_removes_files(client, auth_headers):
    h = auth_headers
    cert_id = _make_cert(client, h, "CERT-DEL")
    att = _upload(client, h, cert_id, PDF, "bye.pdf").json()
    r = client.delete(f"{API}/ship/certificates/{cert_id}", headers=h)
    assert r.status_code == 200, r.text
    assert client.get(att["download_url"], headers=h).status_code == 404
    assert client.get(f"{API}/ship/certificates/{cert_id}/files", headers=h).status_code == 404
    remaining = client.get(f"{API}/ship/certificates", headers=h).json()
    assert all(c["id"] != cert_id for c in remaining)


def test_certificate_list_filters_and_current_file(client, auth_headers):
    h = auth_headers
    vid = _vessel_id(client, h)
    expiring_id = _make_cert(client, h, "CERT-LIST-EXP", expires_on=date.today() + timedelta(days=5))
    valid_id = _make_cert(client, h, "CERT-LIST-OK", expires_on=date.today() + timedelta(days=300))
    _upload(client, h, expiring_id, PDF, "current.pdf")

    rows = client.get(f"{API}/ship/certificates", headers=h, params={"vessel_id": vid, "status": "expiring"})
    assert rows.status_code == 200, rows.text
    ids = [c["id"] for c in rows.json()]
    assert expiring_id in ids
    assert valid_id not in ids
    row = next(c for c in rows.json() if c["id"] == expiring_id)
    assert row["vessel_name"]
    assert row["days_to_expiry"] == 5
    assert row["current_file"]["file_name"] == "current.pdf"
    assert row["current_file"]["version_no"] == 1

    soon = client.get(f"{API}/ship/certificates", headers=h, params={"expiring_within_days": 30}).json()
    soon_ids = [c["id"] for c in soon]
    assert expiring_id in soon_ids
    assert valid_id not in soon_ids
