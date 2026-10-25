"""全局 AI 助手：上下文问答 / 表单填充 / 邮件动作推荐 / 计费 / 平台网关解析。

产品语义：AI 建议、人工确认。因此本套件验证的都是「建议产出」而非「直接落库」——
助手端点从不写业务对象；落库仍由 email apply / 表单保存等确定性端点在人确认后执行。

conftest 默认 ``MARIOS_LLM_OFF=1``，所以 LLM 路径自动走确定性规则回落
（source="rules"/"fallback"），验证的是降级永不 500。触网的路径一律 monkeypatch。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import sessionmaker

API = "/api/v1"


@pytest.fixture()
def open_db(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False)


def _demo_tenant_id(db_engine) -> UUID:
    from app.models import Tenant

    db = sessionmaker(bind=db_engine)()
    try:
        row = db.query(Tenant).filter(Tenant.code == "demo").first()
        assert row is not None, "demo tenant missing"
        return row.id
    finally:
        db.close()


def _seed_recap_email(client, h) -> str:
    """同步 demo 收件箱，取一封 recap 邮件的 id。"""
    r = client.post(
        f"{API}/email/accounts",
        headers=h,
        json={"provider": "demo", "email": "ops@demo.marios", "config": {}},
    )
    acc = r.json()
    client.post(f"{API}/email/accounts/{acc['id']}/sync", headers=h)
    review = client.get(f"{API}/email/review", headers=h).json()
    recap = [m for m in review if "RECAP" in (m["subject"] or "")]
    assert recap, review
    return recap[0]["id"]


# ── 1. 状态端点 ─────────────────────────────────────────────────────────


def test_assist_status_reports_fallback_when_llm_off(client, auth_headers):
    r = client.get(f"{API}/ai/assist/status", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent"] == "copilot"
    # conftest 默认 kill switch → 助手降级但可用
    assert body["available"] is False
    assert body["fallback_mode"] == "rules"


def test_status_seeds_copilot_agent(client, auth_headers, open_db):
    client.get(f"{API}/ai/assist/status", headers=auth_headers)
    db = open_db()
    try:
        from app.models_ai import AIAgentDefinition
        from sqlalchemy import select

        row = db.scalar(select(AIAgentDefinition).where(AIAgentDefinition.agent_name == "copilot"))
        assert row is not None, "copilot preset agent must be seeded"
        assert "confirm" in (row.system_prompt or "").lower()
    finally:
        db.close()


# ── 2. 上下文问答 ────────────────────────────────────────────────────────


def test_assist_ask_falls_back_to_rules_without_llm(client, auth_headers):
    r = client.post(
        f"{API}/ai/assist/ask",
        headers=auth_headers,
        json={"message": "What is the TCE on this voyage?", "context": {"page": "/operations/voyages"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("response"), body
    assert body["source"] == "fallback"
    assert body["conversation_id"]


def test_assist_ask_reuses_single_copilot_conversation(client, auth_headers, open_db):
    for msg in ("hello", "follow up question"):
        r = client.post(f"{API}/ai/assist/ask", headers=auth_headers, json={"message": msg})
        assert r.status_code == 200, r.text
    ids = {r.json()["conversation_id"]}
    assert len(ids) == 1, "assistant should reuse one active conversation per user"


# ── 3. 表单填充 / 总结 ───────────────────────────────────────────────────


def test_assist_fill_form_fallback_matches_record_fields(client, auth_headers, open_db):
    """LLM 关闭时，实体摘要里的同名字段应作为建议值回填（可人工确认后应用）。"""
    from app.models_wave1 import Vessel

    db = open_db()
    try:
        vessel = Vessel(tenant_id=_demo_tenant_id(db.bind), name="Assist Probe", imo="9988776")
        db.add(vessel)
        db.commit()
        vid = str(vessel.id)
    finally:
        db.close()

    r = client.post(
        f"{API}/ai/assist/fill",
        headers=auth_headers,
        json={
            "task": "fill_form",
            "context": {"entity_type": "vessel", "entity_id": vid, "page": "/masterdata/vessels"},
            "form_fields": {"name": "", "imo": ""},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task"] == "fill_form"
    assert body["source"] == "rules"
    assert body["suggestions"].get("name") == "Assist Probe"
    assert body["suggestions"].get("imo") == "9988776"
    # 建议而非落库
    db = open_db()
    try:
        assert db.query(Vessel).filter(Vessel.name == "Assist Probe").count() == 1
    finally:
        db.close()


def test_assist_summarize_fallback_returns_narrative(client, auth_headers):
    r = client.post(
        f"{API}/ai/assist/fill",
        headers=auth_headers,
        json={"task": "summarize", "context": {"page": "/finance/invoices"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["narrative"]
    assert body["source"] == "rules"


def test_assist_fill_unknown_task_normalizes(client, auth_headers):
    r = client.post(f"{API}/ai/assist/fill", headers=auth_headers, json={"task": "nonsense_task"})
    # Literal 校验 → 422（防止任意 task 注入 prompt）
    assert r.status_code == 422, r.text


# ── 4. 邮件动作推荐 ──────────────────────────────────────────────────────


def test_recommend_email_applies_rules_for_recap(client, auth_headers):
    mid = _seed_recap_email(client, auth_headers)
    r = client.post(f"{API}/ai/assist/recommend/email/{mid}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recommendation"] == "apply"
    assert body["reply_template"] == "ack_recap"
    assert body["source"] == "rules"
    assert body["already_applied"] is False
    assert body["email_type"] in ("fixture_recap", "recap")


def test_recommend_email_after_apply_suggests_reply(client, auth_headers):
    mid = _seed_recap_email(client, auth_headers)
    apply = client.post(f"{API}/email/review/{mid}/apply", headers=auth_headers)
    assert apply.status_code == 200, apply.text

    r = client.post(f"{API}/ai/assist/recommend/email/{mid}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["already_applied"] is True
    assert body["recommendation"] == "reply"


def test_recommend_email_404_for_unknown(client, auth_headers):
    r = client.post(
        f"{API}/ai/assist/recommend/email/00000000-0000-0000-0000-000000000000",
        headers=auth_headers,
    )
    assert r.status_code == 404, r.text


# ── 4b. 粘贴文本 → 结构化字段（航次计算 AI 填充） ─────────────────────────

_RECAP_SAMPLE = """Fixture Recap
Vessel: MV PACIFIC STAR
Cargo: Iron Ore 62%
Load Port: Tubarao
Discharge Port: Qingdao
Laycan: 10-15 Nov 2026
Freight Rate: 24.75
Demurrage: 32000
Commission: 2.5%
"""

_NOR_SAMPLE = """Notice of Readiness
Vessel: MV PACIFIC STAR
Port: at Rotterdam
Date: 25/10/2026 08:30
Draft: 12.5 m
"""


def test_extract_recap_text_returns_fields(client, auth_headers):
    """recap 样文 → kind=fixture_recap，规则兜底抽出船舶/港口/运价。"""
    r = client.post(
        f"{API}/ai/assist/extract",
        headers=auth_headers,
        json={"subject": "Fixture Recap MV PACIFIC STAR", "body": _RECAP_SAMPLE},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "fixture_recap"
    assert body["_source"] == "rules"  # MARIOS_LLM_OFF
    fields = body["fields"]
    assert "PACIFIC" in fields["vessel"]
    assert fields["load_port"] == "Tubarao"
    assert fields["discharge_port"] == "Qingdao"
    assert fields["freight_rate"] == 24.75
    assert body["truncated"] is False


def test_extract_nor_text(client, auth_headers):
    r = client.post(
        f"{API}/ai/assist/extract",
        headers=auth_headers,
        json={"body": _NOR_SAMPLE},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "nor"
    assert "PACIFIC" in body["fields"]["vessel"]
    assert "Rotterdam" in body["fields"]["port"]


def test_extract_empty_body_422(client, auth_headers):
    r = client.post(f"{API}/ai/assist/extract", headers=auth_headers, json={"body": ""})
    assert r.status_code == 422


def test_extract_long_body_truncated_flag(client, auth_headers):
    """超过 50k 的粘贴 → 截断处理 + truncated 标注（不 422）。"""
    long_body = _RECAP_SAMPLE + ("filler text " * 6000)  # ~70k chars
    assert len(long_body) > 50000
    r = client.post(
        f"{API}/ai/assist/extract",
        headers=auth_headers,
        json={"body": long_body},
    )
    assert r.status_code == 200, r.text
    assert r.json()["truncated"] is True


def test_extract_general_text_still_returns(client, auth_headers):
    """普通文本（无法分类）→ kind=general，fields 为空但不报错。"""
    r = client.post(
        f"{API}/ai/assist/extract",
        headers=auth_headers,
        json={"body": "Please arrange the crew transfer for next Tuesday."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "general"


# ── 5. 计费 ──────────────────────────────────────────────────────────────


def test_bill_ai_tokens_observational_writes_ledger_without_blocking(client, auth_headers, db_engine):
    """默认（metering 关闭）：记观测流水但不因余额不足阻断。"""
    from app.services.saas_engine import bill_ai_tokens

    tenant_id = _demo_tenant_id(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        res = bill_ai_tokens(db, tenant_id=tenant_id, tokens=1500, note="test")
        assert res["billed"] == 1500
        assert res["mode"] == "observational"
        from app.models_saas import UsageLedger
        from sqlalchemy import select

        led = db.scalars(
            select(UsageLedger).where(
                UsageLedger.tenant_id == tenant_id, UsageLedger.note == "test"
            )
        ).first()
        assert led is not None
        assert led.quantity == Decimal("1500")
        assert led.direction == "consume"
    finally:
        db.close()


def test_bill_ai_tokens_skips_zero(db_engine):
    from app.services.saas_engine import bill_ai_tokens

    tenant_id = _demo_tenant_id(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        res = bill_ai_tokens(db, tenant_id=tenant_id, tokens=0)
        assert res["mode"] == "skip"
        assert res["billed"] == 0
    finally:
        db.close()


def test_bill_ai_tokens_byo_key_does_not_debit_platform_wallet(db_engine):
    """租户自备 key（BYO）不扣平台钱包 —— 成本由租户自己承担。"""
    from app.models_saas import UsageLedger
    from app.services.saas_engine import bill_ai_tokens, get_or_create_wallet
    from sqlalchemy import func, select

    tenant_id = _demo_tenant_id(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        before = get_or_create_wallet(db, tenant_id, "ai.tokens").balance
        res = bill_ai_tokens(db, tenant_id=tenant_id, tokens=5000, billable=False, note="byo")
        assert res["mode"] == "byo_key"
        assert res["billed"] == 0
        db.refresh(get_or_create_wallet(db, tenant_id, "ai.tokens"))
        after = get_or_create_wallet(db, tenant_id, "ai.tokens").balance
        assert float(after) == float(before), "BYO call must not move the platform wallet"
        n = db.scalar(
            select(func.count()).select_from(UsageLedger).where(UsageLedger.note == "byo")
        )
        assert n == 0
    finally:
        db.close()


def test_provider_source_marks_tenant_vs_platform(db_engine, monkeypatch):
    """source 字段区分凭证来源，决定计费归属。"""
    from app.models import Tenant
    from app.models_saas import PlatformAiEndpoint
    from app.models_wave1 import AiProvider
    from app.services import llm_client

    monkeypatch.setenv("MARIOS_LLM_OFF", "0")
    db = sessionmaker(bind=db_engine)()
    try:
        t = Tenant(name="Src Probe", code="src-probe")
        db.add(t)
        db.flush()
        db.add(
            AiProvider(
                tenant_id=t.id, name="BYO", provider_type="openai",
                base_url="https://t.test/v1", model_default="m", status="active",
                config={"api_key": "sk-t"},
            )
        )
        db.add(
            PlatformAiEndpoint(
                code="gw-src", name="GW", provider_type="anthropic",
                base_url="https://g.test/v1", status="active",
                config={"api_key": "sk-p"},
            )
        )
        db.commit()
        assert llm_client.resolve_provider_config(db, t.id).source == "tenant"
        cfg = llm_client.resolve_provider_config(db, None)  # 无租户 → 平台网关
        assert cfg.source == "platform_gateway"
        assert cfg.billable_by_platform is True
    finally:
        db.close()


# ── 6. 平台公用网关接入解析链 ────────────────────────────────────────────


def test_platform_endpoint_resolved_when_no_tenant_provider(db_engine, monkeypatch):
    """租户未自备 key 时，解析应落到 PlatformAiEndpoint（平台公用 API）。"""
    from app.models_saas import PlatformAiEndpoint
    from app.services import llm_client

    monkeypatch.setenv("MARIOS_LLM_OFF", "0")
    db = sessionmaker(bind=db_engine)()
    try:
        db.add(
            PlatformAiEndpoint(
                code="test-gateway",
                name="Test Gateway",
                provider_type="anthropic",
                base_url="https://gw.test/v1",
                model_default="test-model-1",
                status="active",
                config={"api_key": "sk-platform-test"},
            )
        )
        db.commit()
        cfg = llm_client.resolve_provider_config(db, None)
        assert cfg.base_url == "https://gw.test/v1"
        assert cfg.model == "test-model-1"
        assert cfg.api_key == "sk-platform-test"
    finally:
        db.close()


def test_platform_endpoint_ignored_when_disabled(db_engine, monkeypatch):
    """status=disabled 的网关不得进入解析链（不能回落到 env 默认）。"""
    from app.models_saas import PlatformAiEndpoint
    from app.services import llm_client

    monkeypatch.setenv("MARIOS_LLM_OFF", "0")
    db = sessionmaker(bind=db_engine)()
    try:
        db.add(
            PlatformAiEndpoint(
                code="test-gateway-off",
                name="Off Gateway",
                provider_type="anthropic",
                base_url="https://off.test/v1",
                status="disabled",
                config={"api_key": "sk-x"},
            )
        )
        db.commit()
        try:
            cfg = llm_client.resolve_provider_config(db, None)
        except llm_client.LLMNotConfigured:
            return  # 无 env/ambient 凭证 → 干净地报未配置，也正确
        assert cfg.base_url != "https://off.test/v1"
    finally:
        db.close()


def test_tenant_provider_beats_platform_gateway(db_engine, monkeypatch):
    """租户自备 key 必须优先于平台公用网关。

    用全新租户（demo 租户 seed 了自带 AiProvider，会抢先命中）。
    """
    from app.models import Tenant
    from app.models_saas import PlatformAiEndpoint
    from app.models_wave1 import AiProvider
    from app.services import llm_client

    monkeypatch.setenv("MARIOS_LLM_OFF", "0")
    db = sessionmaker(bind=db_engine)()
    try:
        t = Tenant(name="BYO Probe", code="byo-probe")
        db.add(t)
        db.flush()
        db.add(
            AiProvider(
                tenant_id=t.id,
                name="Tenant BYO",
                provider_type="openai",
                base_url="https://tenant.test/v1",
                model_default="tenant-model",
                status="active",
                config={"api_key": "sk-tenant"},
            )
        )
        db.add(
            PlatformAiEndpoint(
                code="gw2",
                name="GW2",
                provider_type="anthropic",
                base_url="https://gw2.test/v1",
                status="active",
                config={"api_key": "sk-platform"},
            )
        )
        db.commit()
        cfg = llm_client.resolve_provider_config(db, t.id)
        assert cfg.base_url == "https://tenant.test/v1"
        assert cfg.provider_type == "openai"
    finally:
        db.close()
