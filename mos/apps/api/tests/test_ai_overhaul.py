"""MariAI overhaul: tool registry, LLM chat loop, fallback, provider CRUD, usage.

All LLM paths are mocked or killed via ``MARIOS_LLM_OFF`` (conftest default) —
zero network in tests.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models_ai import AIConversation, AIMessage, AIAgentDefinition
from app.services import mari_ai
from app.services import llm_client
from app.services.llm_client import LLMError, LLMNotConfigured, LLMProviderConfig, LLMResponse, LLMUsage, ToolCall


@pytest.fixture()
def db_session(db_engine):
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        yield db


@pytest.fixture()
def tenant_id(db_session) -> uuid.UUID:
    from app.models import Tenant

    return uuid.UUID(str(db_session.execute(select(Tenant.id).where(Tenant.code == "demo")).scalar()))


@pytest.fixture()
def user_id(db_session) -> uuid.UUID:
    from app.models import User

    return uuid.UUID(
        str(db_session.execute(select(User.id).where(User.email == "admin@demo.marios")).scalar())
    )


@pytest.fixture()
def agents(db_session) -> list:
    mari_ai.seed_preset_agents(db_session)
    return mari_ai.list_agents(db_session)


def _make_conversation(db, tenant_id, user_id, agent_name="voyage_advisor"):
    return mari_ai.create_conversation(db, tenant_id, user_id, agent_name)


# ── 1. Tool registry ──


def test_tool_registry_has_20_plus_tools():
    assert len(mari_ai.TOOL_REGISTRY) >= 20
    for name, tool in mari_ai.TOOL_REGISTRY.items():
        assert tool.name == name
        assert tool.description
        params = tool.parameters
        assert params.get("type") == "object"
        assert "properties" in params
        # definition() feeds llm_client — must be JSON-serializable keys
        d = tool.definition()
        assert d["name"] == name and d["description"] and d["parameters"]


# ── 2. Each tool executes against seed data ──


def _seed_tool_prereqs(db, tenant_id):
    """Rows the demo seed does not create: port distance, cargo, task."""
    from datetime import datetime, timezone

    from app.models_cargo import Cargo
    from app.models_reference import PortDistance
    from app.models_task import Task

    if not db.scalars(
        select(PortDistance).where(
            PortDistance.from_port_unlocode == "ZZAAA",
            PortDistance.to_port_unlocode == "ZZBBB",
        )
    ).first():
        db.add(
            PortDistance(
                from_port_unlocode="ZZAAA",
                to_port_unlocode="ZZBBB",
                distance_nm=123.4,
                route_type="standard",
            )
        )
    if not db.scalars(select(Cargo).where(Cargo.tenant_id == tenant_id)).first():
        db.add(
            Cargo(
                tenant_id=tenant_id,
                cargo_no="CGO-TEST-0001",
                cargo_type="bulk",
                commodity="Coal",
                qty=52000,
                qty_unit="mt",
                status="open",
            )
        )
    if not db.scalars(select(Task).where(Task.tenant_id == tenant_id)).first():
        db.add(
            Task(
                tenant_id=tenant_id,
                title="Review laytime statement",
                status="todo",
                priority="high",
                created_at=datetime.now(timezone.utc),
            )
        )
    db.commit()


def test_each_tool_executes_with_seed_data(db_session, tenant_id):
    from app.models_domain import Claim, Invoice, LaytimeCalc, Voyage
    from app.models_wave1 import Vessel

    _seed_tool_prereqs(db_session, tenant_id)

    vessel = db_session.scalars(select(Vessel).where(Vessel.tenant_id == tenant_id)).first()
    voyage = db_session.scalars(
        select(Voyage).where(Voyage.tenant_id == tenant_id, Voyage.voyage_no == "VOY-2407")
    ).first()
    assert vessel is not None and voyage is not None
    invoice = db_session.scalars(select(Invoice).where(Invoice.tenant_id == tenant_id)).first()
    laytime = db_session.scalars(select(LaytimeCalc).where(LaytimeCalc.tenant_id == tenant_id)).first()
    claim = db_session.scalars(select(Claim).where(Claim.tenant_id == tenant_id)).first()
    assert invoice is not None and laytime is not None and claim is not None

    cases: dict[str, dict] = {
        "calculate_tce": {"freight_revenue": 100000, "bunker_cost": 20000, "port_costs": 10000, "voyage_days": 20},
        "calculate_laytime": {"allowed_days": 5, "actual_days": 7, "demurrage_rate": 20000},
        "search_port_distance": {"from_port": "ZZAAA", "to_port": "ZZBBB"},
        "check_compliance": {"lat": 51.9, "lon": 4.4, "fuel_type": "MGO"},
        "query_voyage_pnl": {"voyage_no": "VOY-2407"},
        "list_vessels": {"limit": 10},
        "get_vessel": {"vessel": vessel.imo or vessel.name},
        "list_voyages": {"limit": 10},
        "get_voyage": {"voyage_no": "VOY-2407"},
        "list_port_calls": {"voyage_no": "VOY-2407"},
        "get_noon_reports": {"voyage_no": "VOY-2407"},
        "list_charters": {"limit": 10},
        "get_charter": {"charter_no": "CP-2407"},
        "list_estimates": {"limit": 10},
        "list_cargo": {"limit": 10},
        "list_invoices": {"limit": 10},
        "get_invoice": {"invoice_no": invoice.invoice_no},
        "list_claims": {"limit": 10},
        "get_laytime": {"laytime_id": str(laytime.id)},
        "list_payments": {"limit": 10},
        "list_exceptions": {"limit": 10},
        "get_exposure": {"horizon_days": 90},
        "get_market_quotes": {"limit": 10},
        "list_tasks": {"limit": 10},
    }
    assert set(cases) == set(mari_ai.TOOL_REGISTRY)

    for name, args in cases.items():
        result = mari_ai.execute_tool(db_session, tenant_id, name, args)
        assert isinstance(result, dict), name
        assert "error" not in result, f"{name}: {result.get('error')}"
        assert "_latency_ms" in result, name

    # spot-check structured payloads
    assert mari_ai.execute_tool(db_session, tenant_id, "get_vessel", {"vessel": vessel.imo})["imo"] == vessel.imo
    assert mari_ai.execute_tool(db_session, tenant_id, "get_voyage", {"voyage_no": "VOY-2407"})["port_calls"]
    assert mari_ai.execute_tool(db_session, tenant_id, "list_vessels", {})["count"] >= 1
    assert mari_ai.execute_tool(db_session, tenant_id, "get_invoice", {"invoice_no": invoice.invoice_no})["payments"] is not None
    assert "windows" in mari_ai.execute_tool(db_session, tenant_id, "get_exposure", {})
    assert mari_ai.execute_tool(db_session, tenant_id, "list_exceptions", {})["items"] is not None
    assert mari_ai.execute_tool(db_session, tenant_id, "search_port_distance", {"from_port": "ZZAAA", "to_port": "ZZBBB"})["distance_nm"] == 123.4


def test_tools_are_tenant_scoped(db_session, tenant_id, user_id, agents):
    """Rows of another tenant must not leak through tools."""
    from app.models import Tenant
    from app.models_wave1 import Vessel

    other = Tenant(name="Other Co", code=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    db_session.flush()
    db_session.add(
        Vessel(tenant_id=other.id, name="MV OTHER", imo="9999999", status="active")
    )
    db_session.commit()

    out = mari_ai.execute_tool(db_session, tenant_id, "list_vessels", {"limit": 100})
    assert all(v["name"] != "MV OTHER" for v in out["vessels"])
    assert mari_ai.execute_tool(db_session, tenant_id, "get_vessel", {"vessel": "9999999"}).get("error")


# ── 3. Chat fallback (LLM not configured) ──


def test_chat_falls_back_to_rules_when_llm_not_configured(db_session, tenant_id, user_id, agents):
    assert llm_client.llm_off()  # conftest kill switch
    conv = _make_conversation(db_session, tenant_id, user_id)
    result = mari_ai.chat(db_session, tenant_id, user_id, conv.id, "tce 100000 20000 10000 20")
    assert result["source"] == "fallback"
    assert "TCE" in result["response"]
    assert "$3,500.00/day" in result["response"]  # (100k-30k)/20
    assert result["tool_calls"]

    msg = db_session.scalars(
        select(AIMessage).where(AIMessage.conversation_id == conv.id, AIMessage.role == "assistant")
    ).first()
    assert msg is not None and "TCE" in msg.content


def test_chat_fallback_on_llm_error(db_session, tenant_id, user_id, agents, monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "resolve_provider_config",
        lambda *a, **k: LLMProviderConfig(api_key="k", model="m"),
    )

    def boom(*a, **k):
        raise LLMError("provider down")

    monkeypatch.setattr(llm_client, "chat_completion", boom)
    conv = _make_conversation(db_session, tenant_id, user_id)
    result = mari_ai.chat(db_session, tenant_id, user_id, conv.id, "laytime 5 7 20000")
    assert result["source"] == "fallback"
    assert "demurrage" in result["response"]


def test_chat_fallback_default_response(db_session, tenant_id, user_id, agents):
    conv = _make_conversation(db_session, tenant_id, user_id, "market_analyst")
    result = mari_ai.chat(db_session, tenant_id, user_id, conv.id, "hello there")
    assert result["source"] == "fallback"
    assert result["response"]
    assert result["tool_calls"] == []


# ── 4. Chat with mocked LLM (tool loop + usage tracking) ──


def _fake_provider(*a, **k):
    return LLMProviderConfig(provider_type="anthropic", api_key="test-key", model="claude-test")


def test_chat_with_mocked_llm_tool_loop(db_session, tenant_id, user_id, agents, monkeypatch):
    monkeypatch.setattr(llm_client, "resolve_provider_config", _fake_provider)

    calls: list[dict] = []
    script = [
        LLMResponse(
            text="",
            tool_calls=[ToolCall(id="call_1", name="list_vessels", arguments={"limit": 5})],
            usage=LLMUsage(input_tokens=10, output_tokens=5),
            latency_ms=12,
        ),
        LLMResponse(
            text="The fleet has 3 active vessels.",
            usage=LLMUsage(input_tokens=20, output_tokens=10),
            latency_ms=34,
        ),
    ]

    def fake_chat(messages, **kwargs):
        calls.append({"messages": list(messages), **kwargs})
        return script[len(calls) - 1]

    monkeypatch.setattr(llm_client, "chat_completion", fake_chat)

    conv = _make_conversation(db_session, tenant_id, user_id)
    result = mari_ai.chat(db_session, tenant_id, user_id, conv.id, "How many vessels do we have?")

    assert result["source"] == "llm"
    assert result["response"] == "The fleet has 3 active vessels."
    assert len(result["tool_calls"]) == 1
    tc = result["tool_calls"][0]
    assert tc["tool"] == "list_vessels" and tc["id"] == "call_1"
    assert tc["result"]["count"] >= 1

    # system prompt + history + tool definitions passed to the LLM
    first = calls[0]
    assert first["system"] == mari_ai.get_agent(db_session, "voyage_advisor").system_prompt
    assert first["tools"] and any(t["name"] == "list_vessels" for t in first["tools"])
    assert first["messages"][-1]["role"] == "user"
    # second round carries the tool result back
    second = calls[1]
    roles = [m["role"] for m in second["messages"]]
    assert "tool" in roles
    tool_msg = next(m for m in second["messages"] if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_1"

    # token + latency accounting: (10+5)+(20+10) = 45; 12+34 = 46
    assert result["tokens_used"] == 45
    assert result["latency_ms"] == 46
    msg = db_session.get(AIMessage, uuid.UUID(result["message_id"]))
    assert msg.tokens_used == 45
    assert msg.latency_ms == 46
    assert msg.tool_calls_json[0]["tool"] == "list_vessels"


def test_chat_records_token_usage_on_message(db_session, tenant_id, user_id, agents, monkeypatch):
    monkeypatch.setattr(llm_client, "resolve_provider_config", _fake_provider)
    monkeypatch.setattr(
        llm_client,
        "chat_completion",
        lambda messages, **k: LLMResponse(
            text="Done.", usage=LLMUsage(input_tokens=7, output_tokens=3), latency_ms=5
        ),
    )
    conv = _make_conversation(db_session, tenant_id, user_id)
    result = mari_ai.chat(db_session, tenant_id, user_id, conv.id, "ping")
    assert result["tokens_used"] == 10
    msg = db_session.scalars(
        select(AIMessage).where(AIMessage.conversation_id == conv.id, AIMessage.role == "assistant")
    ).first()
    assert msg.tokens_used == 10
    assert msg.latency_ms == 5
    # user message recorded without tokens
    user_msg = db_session.scalars(
        select(AIMessage).where(AIMessage.conversation_id == conv.id, AIMessage.role == "user")
    ).first()
    assert user_msg.content == "ping" and user_msg.tokens_used is None


def test_chat_history_includes_prior_turns(db_session, tenant_id, user_id, agents, monkeypatch):
    monkeypatch.setattr(llm_client, "resolve_provider_config", _fake_provider)
    seen: list[list[dict]] = []
    monkeypatch.setattr(
        llm_client,
        "chat_completion",
        lambda messages, **k: seen.append(list(messages))
        or LLMResponse(text="ok", usage=LLMUsage(1, 1), latency_ms=1),
    )
    conv = _make_conversation(db_session, tenant_id, user_id)
    mari_ai.chat(db_session, tenant_id, user_id, conv.id, "first question")
    mari_ai.chat(db_session, tenant_id, user_id, conv.id, "second question")
    history = seen[-1]
    contents = [m.get("content") for m in history if m["role"] == "user"]
    assert "first question" in contents and "second question" in contents


# ── 5. Provider CRUD / test / models (API) ──

PROVIDER_IN = {
    "name": "OpenAI Main",
    "provider_type": "openai",
    "base_url": "https://api.openai.com/v1",
    "model_default": "gpt-4o",
    "config": {"api_key": "sk-test-old"},
}


def test_provider_crud(client, auth_headers):
    r = client.post("/api/v1/settings/ai/providers", json=PROVIDER_IN, headers=auth_headers)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert r.json()["name"] == "OpenAI Main"
    assert r.json()["status"] == "active"

    # list includes it
    r = client.get("/api/v1/settings/ai/providers", headers=auth_headers)
    assert any(p["id"] == pid for p in r.json())

    # patch: rename, rotate api_key, switch default model
    r = client.patch(
        f"/api/v1/settings/ai/providers/{pid}",
        json={"name": "OpenAI Prod", "api_key": "sk-test-new", "model_default": "gpt-4o-mini"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "OpenAI Prod"
    assert r.json()["model_default"] == "gpt-4o-mini"
    # api_key lands encrypted in secret_ref (or config fallback)
    assert (r.json().get("secret_ref") or "").startswith("v1:") or (
        (r.json().get("config") or {}).get("api_key") == "sk-test-new"
    )

    # soft delete
    r = client.delete(f"/api/v1/settings/ai/providers/{pid}", headers=auth_headers)
    assert r.status_code == 200 and r.json()["deleted"] is True

    r = client.get("/api/v1/settings/ai/providers", headers=auth_headers)
    assert all(p["id"] != pid for p in r.json())

    # patch/delete of missing provider → 404
    missing = str(uuid.uuid4())
    assert client.patch(
        f"/api/v1/settings/ai/providers/{missing}", json={"name": "x"}, headers=auth_headers
    ).status_code == 404
    assert client.delete(
        f"/api/v1/settings/ai/providers/{missing}", headers=auth_headers
    ).status_code == 404


def test_provider_test_endpoint_probes_via_llm_client(client, auth_headers, monkeypatch):
    r = client.post("/api/v1/settings/ai/providers", json=PROVIDER_IN, headers=auth_headers)
    pid = r.json()["id"]

    probed: list[dict] = []

    def fake_probe(cfg):
        probed.append({"type": cfg.provider_type, "model": cfg.model, "base_url": cfg.base_url})
        return {
            "ok": True,
            "provider_type": cfg.provider_type,
            "model": cfg.model,
            "latency_ms": 42,
            "models": ["gpt-4o", "gpt-4o-mini"],
            "message": "connected",
        }

    monkeypatch.setattr(llm_client, "test_provider", fake_probe)
    r = client.post(f"/api/v1/settings/ai/providers/{pid}/test", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["provider_id"] == pid
    assert body["latency_ms"] == 42
    assert body["models"] == ["gpt-4o", "gpt-4o-mini"]
    assert probed and probed[0]["type"] == "openai"
    assert "tested_at" in body


def test_models_endpoint_live_and_catalog(client, auth_headers, monkeypatch):
    r = client.post("/api/v1/settings/ai/providers", json=PROVIDER_IN, headers=auth_headers)
    pid = r.json()["id"]

    # kill switch on → no network: static catalog fallback
    r = client.get("/api/v1/settings/ai/models", headers=auth_headers)
    assert r.status_code == 200, r.text
    entry = next(e for e in r.json() if e["provider_id"] == pid)
    assert entry["source"] == "catalog"
    assert "gpt-4o" in entry["models"]  # model_default always surfaced
    assert len(entry["models"]) >= 1

    # live probe path (mocked)
    monkeypatch.setattr(llm_client, "list_models", lambda cfg, **k: ["gpt-4o", "gpt-4o-mini", "o4"])
    r = client.get(f"/api/v1/settings/ai/models?provider_id={pid}", headers=auth_headers)
    entry = r.json()[0]
    assert entry["source"] == "live"
    assert entry["models"] == ["gpt-4o", "gpt-4o-mini", "o4"]

    # unknown provider → 404
    assert client.get(
        f"/api/v1/settings/ai/models?provider_id={uuid.uuid4()}", headers=auth_headers
    ).status_code == 404


# ── 6. Agents PATCH + usage stats (API) ──


def test_patch_agent_model_and_temperature(client, auth_headers, db_session):
    mari_ai.seed_preset_agents(db_session)
    agent = db_session.scalars(
        select(AIAgentDefinition).where(AIAgentDefinition.agent_name == "voyage_advisor")
    ).first()
    agent_id = str(agent.id)

    r = client.patch(
        f"/api/v1/settings/ai/agents/{agent_id}",
        json={"model_name": "claude-sonnet-5", "temperature": 0.7},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["model_name"] == "claude-sonnet-5"
    assert r.json()["temperature"] == 0.7

    # temperature bounds enforced
    r = client.patch(
        f"/api/v1/settings/ai/agents/{agent_id}",
        json={"temperature": 3.5},
        headers=auth_headers,
    )
    assert r.status_code == 422

    # listed with new config
    r = client.get("/api/v1/settings/ai/agents", headers=auth_headers)
    row = next(a for a in r.json() if a["id"] == agent_id)
    assert row["model_name"] == "claude-sonnet-5"

    # unknown agent → 404
    assert client.patch(
        f"/api/v1/settings/ai/agents/{uuid.uuid4()}",
        json={"model_name": "x"},
        headers=auth_headers,
    ).status_code == 404


def test_usage_stats_endpoint(client, auth_headers, db_session, tenant_id, user_id, agents):
    conv = _make_conversation(db_session, tenant_id, user_id)
    mari_ai.add_message(db_session, conv.id, "user", "hi", tokens_used=5, latency_ms=1)
    mari_ai.add_message(db_session, conv.id, "assistant", "hello", tokens_used=25, latency_ms=11)

    r = client.get("/api/v1/settings/ai/usage", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_tokens"] >= 30
    assert body["message_count"] >= 2
    assert body["avg_latency_ms"] >= 1

    by_conv = next(c for c in body["by_conversation"] if c["conversation_id"] == str(conv.id))
    assert by_conv["tokens"] == 30
    assert by_conv["messages"] == 2
    assert by_conv["agent_name"] == "voyage_advisor"

    by_agent = next(a for a in body["by_agent"] if a["agent_name"] == "voyage_advisor")
    assert by_agent["tokens"] >= 30
    assert body["by_day"]
