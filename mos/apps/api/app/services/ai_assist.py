"""全局 AI 助手引擎 — 弹出问答 / 表单填充 / 总结汇报 / 邮件动作推荐。

产品语义贯穿全模块：**AI 建议，人工确认**。本模块只产出建议
（回答、字段建议、推荐动作），绝不直接写业务对象；落库动作仍由既有
的确定性端点（email apply、表单 Save 等）在用户确认后执行。

计费与可靠性沿用既有底座：
- provider 解析走 :func:`llm_client.resolve_provider_config`
  （租户 AiProvider → 平台网关 → env 默认）；
- 真实 LLM 调用按 tokens 记账（:func:`saas_engine.bill_ai_tokens`）；
- ``MARIOS_LLM_OFF`` / 无凭证 / provider 报错 → 回落确定性规则，永不 500。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import ai_context, llm_client, mari_ai
from app.services.llm_client import LLMError, LLMNotConfigured

log = logging.getLogger("marios.ai_assist")

COPILOT_AGENT = "copilot"

# 表单填充任务 → 该任务的产出形态说明（注入 prompt）
FILL_TASKS = ("fill_form", "summarize", "daily_report", "draft_note", "explain", "compare")

_TASK_GUIDE = {
    "fill_form": (
        "Return ONLY a JSON object mapping each requested field name to its suggested value. "
        "Use null for fields you cannot confidently determine. No prose, no markdown fences."
    ),
    "summarize": (
        "Return a concise summary (<=180 words) of the record/context provided. "
        "Lead with the headline number or status, then 2-4 supporting bullets."
    ),
    "daily_report": (
        "Return a daily operations report in plain text: Date, Vessels active, Voyages at risk, "
        "Open exceptions, Actions needed tomorrow. Keep it scannable, <=200 words."
    ),
    "draft_note": (
        "Return a short professional note (<=120 words) suitable for pasting into an email or remark field."
    ),
    "explain": (
        "Explain what the values on screen mean and flag anything unusual or worth checking. "
        "Be specific and cite the figures from CONTEXT."
    ),
    "compare": (
        "Compare the options given and recommend one, with the decisive numbers stated explicitly."
    ),
}


def _ensure_copilot_agent(db: Session) -> None:
    """保证 copilot agent 已 seed（老库升级后不自动有）。"""
    from app.models_ai import AIAgentDefinition

    exists = db.scalar(
        select(AIAgentDefinition).where(AIAgentDefinition.agent_name == COPILOT_AGENT)
    )
    if not exists:
        mari_ai.seed_preset_agents(db)


def _get_or_create_assist_conv(
    db: Session, tenant_id: UUID, user_id: UUID, context: dict | None, title: str | None
):
    """为助手取一个可用会话：优先复用最近的 copilot 会话（刷新 context），否则新建。"""
    conv = db.scalar(
        select(mari_ai.AIConversation)
        .where(
            mari_ai.AIConversation.tenant_id == tenant_id,
            mari_ai.AIConversation.user_id == user_id,
            mari_ai.AIConversation.agent_name == COPILOT_AGENT,
            mari_ai.AIConversation.status == "active",
        )
        .order_by(mari_ai.AIConversation.updated_at.desc())
        .limit(1)
    )
    if conv is None:
        conv = mari_ai.create_conversation(
            db, tenant_id, user_id, COPILOT_AGENT, title=title or "Mari Copilot", context=context or {}
        )
    else:
        # 每次调用都刷新上下文 —— 用户可能已切到另一个记录
        if context:
            conv.context_json = {**(conv.context_json or {}), **context}
        if title:
            conv.title = title
        db.commit()
    return conv


def status(db: Session, tenant_id: UUID) -> dict:
    """前端据此决定助手可用性与计费提示。"""
    _ensure_copilot_agent(db)
    available = not llm_client.llm_off()
    provider_name = None
    metering = False
    try:
        from app.config import get_settings

        metering = bool(get_settings().ai_metering_enabled)
        cfg = llm_client.resolve_provider_config(db, tenant_id, agent_name=COPILOT_AGENT)
        provider_name = cfg.provider_name or cfg.provider_type
    except LLMNotConfigured:
        available = False
    except Exception:  # noqa: BLE001
        log.exception("ai_assist: status provider probe failed")
    balance = None
    if metering:
        from app.models_saas import TenantWallet

        w = db.scalar(
            select(TenantWallet).where(
                TenantWallet.tenant_id == tenant_id, TenantWallet.meter_code == "ai.tokens"
            )
        )
        balance = float(w.balance) if w is not None else 0.0
    return {
        "available": available,
        "agent": COPILOT_AGENT,
        "provider": provider_name,
        "metering": metering,
        "balance": balance,
        "fallback_mode": "rules" if not available else None,
    }


def ask(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    message: str,
    context: dict | None = None,
) -> dict:
    """上下文感知问答：把当前记录注入 copilot 会话并对话一轮。"""
    _ensure_copilot_agent(db)
    ctx = context or {}
    conv = _get_or_create_assist_conv(db, tenant_id, user_id, ctx, title=(message or "")[:80])
    result = mari_ai.chat(db, tenant_id, user_id, conv.id, message)
    result.setdefault("conversation_id", str(conv.id))
    return result


def _parse_json_payload(text: str) -> dict | None:
    """从 LLM 回复里抠出 JSON 对象（容忍 ```json 围栏 / 前后废话）。"""
    if not text:
        return None
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", cleaned, re.S)
        if brace:
            cleaned = brace.group(0)
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


def _rule_fill_fallback(task: str, context: dict | None, form_fields: dict | None) -> dict:
    """LLM 不可用时的确定性回落：把上下文摘要/表单值原样回填，标 source=rules。"""
    ctx = context or {}
    summary = ctx.get("summary") or {}
    fields_in = dict(form_fields or {})
    suggestions: dict[str, Any] = {}
    if task == "fill_form":
        # 规则回落：实体摘要里同名字段直接作为建议值
        for k, v in (summary or {}).items():
            if isinstance(v, (str, int, float, bool)) and k in fields_in:
                suggestions[k] = v
        narrative = "No LLM configured — returning values matched from the current record only."
    elif task in ("summarize", "daily_report"):
        parts = [f"{k}: {v}" for k, v in list((summary or {}).items())[:12]]
        narrative = ("; ".join(parts) if parts else "No record context available.") + (
            " (rule-based fallback — configure an AI provider for richer output)"
        )
        suggestions = {}
    else:
        narrative = "AI provider not configured. Configure one in Settings → AI Hub."
        suggestions = {}
    return {
        "task": task,
        "suggestions": suggestions,
        "narrative": narrative,
        "source": "rules",
        "tokens_used": 0,
        "billing": {"billed": 0, "mode": "skip"},
    }


def fill(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    *,
    task: str = "fill_form",
    context: dict | None = None,
    form_fields: dict | None = None,
    instruction: str | None = None,
) -> dict:
    """表单填充 / 总结 / 汇报：产出建议值 + 叙述文本，供 UI 呈现人工确认。"""
    task = task if task in FILL_TASKS else "fill_form"
    ctx = context or {}
    try:
        _ensure_copilot_agent(db)
        provider = llm_client.resolve_provider_config(db, tenant_id, agent_name=COPILOT_AGENT)
    except (LLMNotConfigured, LLMError):
        return _rule_fill_fallback(task, ctx, form_fields)
    except Exception:  # noqa: BLE001
        log.exception("ai_assist: provider resolve failed")
        return _rule_fill_fallback(task, ctx, form_fields)

    guide = _TASK_GUIDE.get(task, _TASK_GUIDE["fill_form"])
    prompt_parts: list[str] = [f"Task: {task}. {guide}"]
    if form_fields:
        names = ", ".join(list(form_fields.keys())[:30])
        prompt_parts.append(f"Fields to consider: {names}.")
    if instruction:
        prompt_parts.append(f"Additional instruction: {instruction}")
    user_msg = "\n".join(prompt_parts)

    conv = _get_or_create_assist_conv(db, tenant_id, user_id, ctx, title=f"Assist: {task}")
    # 走既有 chat 循环（含工具调用 + 会话留痕 + tokens 记账）
    result = mari_ai.chat(db, tenant_id, user_id, conv.id, user_msg)
    text = str(result.get("response") or "")
    source = result.get("source", "llm")

    suggestions: dict[str, Any] = {}
    if task == "fill_form":
        parsed = _parse_json_payload(text)
        if parsed is not None:
            # 只采纳请求字段里的键，避免模型编造字段名
            allowed = set(form_fields or {}) or set(parsed)
            suggestions = {k: v for k, v in parsed.items() if k in allowed}
            text = ""  # 已结构化，叙述交给 narrative 槽
    narrative = text
    if not narrative and task == "fill_form":
        narrative = "Review the suggested values below, then apply and save."

    return {
        "task": task,
        "suggestions": suggestions,
        "narrative": narrative,
        "source": source,
        "tokens_used": result.get("tokens_used", 0),
        "billing": result.get("billing") or {"billed": 0, "mode": "skip"},
        "conversation_id": result.get("conversation_id"),
        "tool_calls": result.get("tool_calls") or [],
    }


# ── 邮件动作推荐 ──────────────────────────────────────────────────────────

# 与 email_actions.REPLY_TEMPLATES 对齐
_EMAIL_TEMPLATE_HINTS = {
    "fixture_recap": "ack_recap",
    "recap": "ack_recap",
    "nor": "nor_ack",
    "laytime_statement": "laytime_query",
}


def recommend_email(db: Session, tenant_id: UUID, user_id: UUID, message_id: UUID) -> dict:
    """邮件下一步动作推荐：规则底稿 + LLM 润色判断；产出推荐，不落库。

    返回 ``{recommendation, confidence, reason, reply_template, source, ...}``。
    真正的落库仍由 ``/email/review/{id}/apply`` 与 ``/reply`` 在员工确认后执行。
    """
    from app.models_wave1 import EmailMessage

    msg = db.get(EmailMessage, message_id)
    if not msg or msg.tenant_id != tenant_id:
        raise LookupError("message not found")

    parse = dict(msg.parse_result or {})
    etype = str(parse.get("email_type") or (parse.get("classification") or {}).get("type") or "general")
    applied = bool(parse.get("applied"))
    fields = _flat_summary(parse)

    # 规则底稿 —— 即使 LLM 不可用也有可执行的推荐
    if applied:
        base = {
            "recommendation": "reply",
            "confidence": 0.9,
            "reason": "Business draft already created from this email — consider replying to confirm.",
            "reply_template": _EMAIL_TEMPLATE_HINTS.get(etype, "general"),
        }
    elif etype in ("fixture_recap", "recap", "nor", "laytime_statement"):
        base = {
            "recommendation": "apply",
            "confidence": 0.8,
            "reason": f"Detected a {etype} — create the matching business draft, then reply.",
            "reply_template": _EMAIL_TEMPLATE_HINTS.get(etype, "general"),
        }
    else:
        base = {
            "recommendation": "review",
            "confidence": 0.4,
            "reason": "No structured business type detected — review manually.",
            "reply_template": "general",
        }

    llm_note = None
    source = "rules"
    tokens = 0
    billing: dict = {"billed": 0, "mode": "skip"}
    try:
        cfg = llm_client.resolve_provider_config(db, tenant_id, agent_name=COPILOT_AGENT)
    except Exception:  # noqa: BLE001 — LLM 不可用则直接用规则推荐
        cfg = None
    if cfg is not None and not llm_client.llm_off():
        try:
            body = (msg.body_text or "")[:6000]
            subject = msg.subject or "(no subject)"
            prompt = (
                "You are reviewing an inbound shipping email for a voyage-ops team.\n"
                f"Subject: {subject}\n"
                f"Detected type: {etype}\n"
                f"Extracted fields: {json.dumps(fields, ensure_ascii=False, default=str)[:1500]}\n"
                f"Body:\n{body}\n\n"
                "Recommend the single best next action for a human operator. Reply ONLY with JSON:\n"
                '{"action": "apply"|"reply"|"review", "confidence": 0.0-1.0, '
                '"reason": "<one sentence>", "reply_template": "ack_recap"|"counter_offer"|'
                '"nor_ack"|"laytime_query"|"general"}'
            )
            resp = llm_client.chat_completion(
                [{"role": "user", "content": prompt}],
                model=None,
                temperature=0.1,
                system="You are a precise shipping-ops triage assistant.",
                provider=cfg,
            )
            tokens = int(resp.usage.total_tokens or 0)
            parsed = _parse_json_payload(resp.text or "")
            if parsed and parsed.get("action") in ("apply", "reply", "review"):
                base = {
                    "recommendation": parsed["action"],
                    "confidence": min(1.0, max(0.0, float(parsed.get("confidence") or 0.5))),
                    "reason": str(parsed.get("reason") or base["reason"])[:400],
                    "reply_template": str(parsed.get("reply_template") or base["reply_template"]),
                }
                source = "llm"
                llm_note = (resp.text or "").strip()[:500]
            from app.services.saas_engine import bill_ai_tokens

            billing = bill_ai_tokens(
                db,
                tenant_id=tenant_id,
                tokens=tokens,
                user_id=user_id,
                ref_type="email_message",
                ref_id=str(msg.id),
                note="email.recommend",
                billable=bool(cfg is not None and cfg.billable_by_platform),
            )
        except (LLMNotConfigured, LLMError):
            pass
        except Exception:  # noqa: BLE001 — 推荐失败回落规则
            log.exception("ai_assist: email recommend LLM path failed")
            billing = {"billed": 0, "mode": "error"}

    return {
        "message_id": str(msg.id),
        "email_type": etype,
        "already_applied": applied,
        **base,
        "source": source,
        "tokens_used": tokens,
        "llm_note": llm_note,
        "billing": billing,
    }


def _flat_summary(parse: dict) -> dict:
    """合并多代落库形状的字段（与 email_actions._flat_fields 同思路，独立副本避免耦合）。"""
    merged: dict[str, Any] = {}
    for key in ("fixture_recap", "nor", "laytime"):
        sub = parse.get(key)
        if isinstance(sub, dict):
            merged.update({k: v for k, v in sub.items() if k not in ("_source", "_rule_diffs") and v is not None})
    merged.update({k: v for k, v in parse.items() if not isinstance(v, dict) and v is not None})
    return merged
