"""D26 MariAI 业务 Agent：草稿生成（引擎为准，LLM 叙述可选/mocked）。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.services import mari_ai_actions


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def test_laytime_statement_draft_uses_engine(client, auth_headers, monkeypatch):
    h = auth_headers
    lt = client.post(
        "/api/v1/laytimes",
        headers=h,
        json={
            "inputs": {
                "allowed_hours": 24,
                "demurrage_rate_per_day": 24000,
                "events": [{"start": "2026-01-05T00:00:00", "end": "2026-01-06T12:00:00", "excluded": False}],
            }
        },
    ).json()

    monkeypatch.setattr(mari_ai_actions, "_narrative", lambda p: "Please find our laytime statement attached.")
    body = client.post("/api/v1/ai/actions/draft", headers=h, json={"action": "laytime_statement", "laytime_id": lt["id"]})
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["action"] == "laytime_statement"
    assert data["statement"]["used_hours"] == 36.0  # 引擎计算（24+12）
    assert data["statement"]["result_type"] == "demurrage"
    assert "laytime statement" in data["narrative"]


def test_voyage_instruction_draft(client, auth_headers, monkeypatch):
    h = auth_headers
    voyages = client.get("/api/v1/voyages", headers=h).json()
    voyages = voyages["items"] if isinstance(voyages, dict) else voyages
    vid = voyages[0]["id"]

    monkeypatch.setattr(mari_ai_actions, "_narrative", lambda p: "Dear Master, please find voyage instructions below.")
    body = client.post("/api/v1/ai/actions/draft", headers=h, json={"action": "voyage_instruction", "voyage_id": vid})
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["fields"]["voyage_no"]
    assert len(data["instructions"]) == 3
    assert "Dear Master" in data["narrative"]


def test_exception_explanation_with_suggestions(client, auth_headers, monkeypatch):
    h = auth_headers
    monkeypatch.setattr(mari_ai_actions, "_narrative", lambda p: "Priority review suggested.")
    body = client.post("/api/v1/ai/actions/draft", headers=h, json={"action": "exception_explanation"})
    assert body.status_code == 200, body.text
    data = body.json()
    assert data["action"] == "exception_explanation"
    for it in data["items"]:
        assert it["suggested_action"]


def test_unknown_action_rejected(client, auth_headers):
    r = client.post("/api/v1/ai/actions/draft", headers=auth_headers, json={"action": "bogus"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "UNKNOWN_ACTION"


def test_narrative_optional_without_llm(monkeypatch):
    """无 LLM 凭证 → 叙述为 None，草稿照出。"""
    monkeypatch.setattr("app.services.llm_extract.llm_available", lambda: False)
    assert mari_ai_actions._narrative("x") is None
