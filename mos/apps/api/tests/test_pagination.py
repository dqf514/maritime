"""U1 列表协议: list endpoints return the {items,total,limit,offset} envelope.

Protocol home: app/pagination.py (see docs/internal/system-upgrade-plan.md §3.9).
Migrated endpoints: GET /invoices, /claims, /laytimes. New list endpoints must
follow the same shape.
"""

from __future__ import annotations

MIGRATED = ("/api/v1/invoices", "/api/v1/claims", "/api/v1/laytimes")


def test_list_envelope_shape(client, auth_headers):
    for path in MIGRATED:
        body = client.get(path, headers=auth_headers).json()
        assert set(body) == {"items", "total", "limit", "offset"}, path
        assert isinstance(body["items"], list), path
        assert isinstance(body["total"], int) and body["total"] >= len(body["items"]), path
        assert body["limit"] > 0 and body["offset"] >= 0, path


def test_invoices_paging_slices_deterministically(client, auth_headers):
    page1 = client.get("/api/v1/invoices?limit=1&offset=0", headers=auth_headers).json()
    page2 = client.get("/api/v1/invoices?limit=1&offset=1", headers=auth_headers).json()
    assert page1["limit"] == 1 and page1["offset"] == 0
    assert page2["limit"] == 1 and page2["offset"] == 1
    assert page1["total"] == page2["total"]
    if page1["total"] >= 2:
        assert page1["items"][0]["id"] != page2["items"][0]["id"]
    # offset past the end: empty items, total unchanged
    tail = client.get(f"/api/v1/invoices?limit=1&offset={page1['total'] + 5}", headers=auth_headers).json()
    assert tail["items"] == []
    assert tail["total"] == page1["total"]


def test_claims_and_laytimes_respect_limit(client, auth_headers):
    for path in ("/api/v1/claims", "/api/v1/laytimes"):
        body = client.get(f"{path}?limit=2", headers=auth_headers).json()
        assert body["limit"] == 2
        assert len(body["items"]) <= 2
        # limit bounds are enforced (422 outside 1..500)
        assert client.get(f"{path}?limit=0", headers=auth_headers).status_code == 422
        assert client.get(f"{path}?limit=501", headers=auth_headers).status_code == 422
