"""Knowledge Centre — catalogue, search, ask (public, customer-facing)."""

from __future__ import annotations


def test_help_catalog_and_article(client):
    cat = client.get("/api/v1/help/catalog?locale=zh-CN")
    assert cat.status_code == 200, cat.text
    body = cat.json()
    assert body["locale"] == "zh"
    assert len(body["categories"]) >= 5
    assert any(a["slug"] == "microsoft-365" for a in body["articles"])
    # Customer copy should not leak internal planning language
    blob = " ".join(a["title"] + " " + a["summary"] for a in body["articles"]).lower()
    for banned in ("veson", "对标", "不得弱于", "必须补齐", "gap todo"):
        assert banned not in blob

    art = client.get("/api/v1/help/articles/welcome?locale=zh-CN")
    assert art.status_code == 200
    assert "MariOS" in art.json()["title"] or "航运" in art.json()["body"]
    assert art.json().get("body")


def test_help_search_and_ask(client):
    sr = client.get("/api/v1/help/search", params={"q": "Teams", "locale": "en"})
    assert sr.status_code == 200
    items = sr.json()["items"]
    assert items
    assert any("365" in i["slug"] or "microsoft" in i["slug"] for i in items)

    ask = client.post("/api/v1/help/ask", json={"question": "如何连接 Teams？", "locale": "zh-CN"})
    assert ask.status_code == 200, ask.text
    data = ask.json()
    assert data["answer"]
    assert data["related"]
    assert data["source"] in ("faq", "search")


def test_help_ask_estimate(client):
    ask = client.post("/api/v1/help/ask", json={"question": "How do I calculate TCE Worldscale?", "locale": "en"})
    assert ask.status_code == 200
    assert ask.json()["related"]
    assert any(r["slug"] == "estimates" for r in ask.json()["related"])


def test_healthz_docs_version(client):
    from app.config import get_settings

    hz = client.get("/healthz")
    assert hz.status_code == 200
    assert hz.json()["version"] == get_settings().app_version
