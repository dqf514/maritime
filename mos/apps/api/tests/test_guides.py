"""Page-level SOP guides — /guides/{page_key}."""

from __future__ import annotations

PAGE_KEYS = [
    "home",
    "tasks",
    "estimates",
    "charters",
    "voyages",
    "voyage_detail",
    "finance",
    "ship",
    "exceptions",
    "masterdata_vessels",
    "workflows_inbox",
]


def test_guides_all_pages_bilingual(client, auth_headers):
    for key in PAGE_KEYS:
        r = client.get(f"/api/v1/guides/{key}", headers=auth_headers)
        assert r.status_code == 200, f"{key}: {r.text}"
        body = r.json()
        assert body["page_key"] == key
        for field in ("title", "purpose", "upstream", "downstream", "roles"):
            assert body[field]["en"], f"{key}.{field}.en"
            assert body[field]["zh"], f"{key}.{field}.zh"
        assert 4 <= len(body["steps"]) <= 7, f"{key}: steps count {len(body['steps'])}"
        for step in body["steps"]:
            assert step["en"] and step["zh"], f"{key}: step missing language"
        assert isinstance(body["help_slugs"], list)


def test_guides_help_slugs_exist(client, auth_headers):
    from app.services import knowledge_base as kb

    for key in PAGE_KEYS:
        body = client.get(f"/api/v1/guides/{key}", headers=auth_headers).json()
        for slug in body["help_slugs"]:
            assert kb.get_article(slug) is not None, f"{key}: unknown slug {slug}"


def test_guides_unknown_page_404(client, auth_headers):
    r = client.get("/api/v1/guides/no_such_page", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "GUIDE_NOT_FOUND"


def test_guides_require_login(client):
    r = client.get("/api/v1/guides/voyages")
    assert r.status_code == 401
