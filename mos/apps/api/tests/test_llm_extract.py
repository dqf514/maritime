"""D25 LLM 抽取：LLM 路径 / 规则兜底 / 交叉校验（全部 mock，零网络）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.models_wave1 import EmailMessage
from app.services import llm_extract
from app.services.llm_extract import FixtureRecapExtraction, NorExtraction, extract_fields


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


def test_llm_path_returns_fields_and_rule_diff(monkeypatch):
    def fake_call(schema, subject, body):
        assert schema is FixtureRecapExtraction
        return FixtureRecapExtraction(vessel="MV Test", freight_rate=22.5, laycan="1-5 Oct")

    monkeypatch.setattr(llm_extract, "call_claude", fake_call)
    monkeypatch.setattr(llm_extract, "llm_available", lambda: True)

    out = extract_fields(
        "fixture_recap",
        "Fixture Recap",
        "Vessel: MV Test\nFreight Rate: USD 22.5",
        rule_fields={"vessel": "MV Test", "freight_rate": 25.0, "cargo": "Coal"},
    )
    assert out["_source"] == "llm"
    assert out["vessel"] == "MV Test"
    assert out["freight_rate"] == 22.5
    assert out["laycan"] == "1-5 Oct"
    # 规则侧独有的 cargo 不进 diff（只对共有字段交叉校验）
    diffs = {d["field"]: d for d in out["_rule_diffs"]}
    assert diffs["freight_rate"]["llm_value"] == 22.5
    assert diffs["freight_rate"]["rule_value"] == 25.0
    assert "vessel" not in diffs  # 一致
    assert "cargo" not in diffs  # LLM 未给，规则独有


def test_rules_fallback_on_llm_failure(monkeypatch):
    def boom(schema, subject, body):
        return None

    monkeypatch.setattr(llm_extract, "call_claude", boom)
    monkeypatch.setattr(llm_extract, "llm_available", lambda: True)

    out = extract_fields("nor", "NOR", "x", rule_fields={"vessel": "MV A"})
    assert out["_source"] == "rules"
    assert out["vessel"] == "MV A"
    assert out["_rule_diffs"] == []


def test_rules_fallback_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(llm_extract, "call_claude", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call")))
    monkeypatch.setattr(llm_extract, "llm_available", lambda: False)

    out = extract_fields("fixture_recap", "s", "b", rule_fields={"vessel": "MV B"})
    assert out["_source"] == "rules"
    assert out["vessel"] == "MV B"


def test_unknown_kind_goes_rules():
    out = extract_fields("general", "s", "b", rule_fields={"x": 1})
    assert out["_source"] == "rules"
    assert out["x"] == 1


def test_nor_schema_alignment(monkeypatch):
    monkeypatch.setattr(llm_extract, "llm_available", lambda: True)
    monkeypatch.setattr(
        llm_extract,
        "call_claude",
        lambda schema, s, b: NorExtraction(vessel="MV C", port="Qingdao", draft=12.3),
    )
    out = extract_fields("nor", "NOR", "b", rule_fields={})
    assert out["_source"] == "llm"
    assert out["port"] == "Qingdao"
    assert out["draft"] == 12.3


def test_process_inbound_email_carries_llm_source(db_session, monkeypatch):
    from app.services import email_intelligence as ei

    monkeypatch.setattr(
        "app.services.llm_extract.extract_fields",
        lambda kind, subject, body, rule_fields=None: {**rule_fields, "_source": "llm", "_rule_diffs": []},
    )
    from app.models import Tenant as _T
    tid = uuid.UUID(str(db_session.execute(__import__("sqlalchemy").select(_T.id).where(_T.code == "demo")).scalar()))
    from datetime import datetime, timezone

    msg = EmailMessage(
        tenant_id=tid,
        direction="inbound",
        message_id=f"msg-{uuid.uuid4().hex[:8]}",
        from_email="broker@example.com",
        subject="Fixture Recap - MV Test",
        body_text="Vessel: MV Test\nFreight Rate: USD 20",
        sent_at=datetime.now(timezone.utc),
        parse_status="pending",
    )
    db_session.add(msg)
    db_session.commit()

    result = ei.process_inbound_email(db_session, tid, uuid.UUID(str(msg.id)))
    assert result["classification"]["type"] == "fixture_recap"
    assert result["parse_result"]["fixture_recap"]["_source"] == "llm"
    assert result["parse_result"]["fixture_recap"]["vessel"] == "MV Test"
    db_session.refresh(msg)
    assert msg.parse_status == "parsed"
