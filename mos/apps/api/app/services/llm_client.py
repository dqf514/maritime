"""Unified LLM client — Anthropic (official SDK) + OpenAI-compatible (HTTP).

MariAI 的模型调用统一入口：

- Anthropic 走官方 ``anthropic`` SDK（tool_use 原生支持）；
- OpenAI 兼容端点走 ``httpx``（chat/completions + function tools）；
- 配置优先级：租户 ``AiProvider``（含 skill binding）→ ``config.py`` 平台默认；
- 熔断：``MARIOS_LLM_OFF=1`` 或无凭证 → :class:`LLMNotConfigured`，
  调用方（mari_ai）回落规则引擎，保证零网络、优雅降级；
- 采样参数兼容：新一代 Claude（Opus 5/4.6+、Sonnet 5/4.6、Fable/Mythos 5）
  已移除 temperature/top_p，发送即 400 —— 对这些模型自动省略 temperature。

测试不触网：monkeypatch :func:`chat_completion` / :func:`resolve_provider_config`，
或 ``MARIOS_LLM_OFF=1``（conftest 默认开启）。
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger("marios.llm_client")

DEFAULT_TIMEOUT_SECONDS = 60
OPENAI_COMPAT_PATH = "/chat/completions"
OPENAI_MODELS_PATH = "/models"


class LLMNotConfigured(Exception):
    """No usable LLM credential/config (or kill switch) — caller falls back to rules."""


class LLMError(Exception):
    """Provider/API failure after configuration resolved — caller may fall back."""


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ToolCall:
    """Provider-agnostic tool invocation request from the model."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str = ""
    model: str = ""
    latency_ms: int = 0
    usage: LLMUsage = field(default_factory=LLMUsage)
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    provider_type: str = "anthropic"
    raw: Any = None


@dataclass
class LLMProviderConfig:
    """Resolved endpoint + credential + defaults for one LLM provider."""

    provider_type: str = "anthropic"  # anthropic | openai
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    max_tokens: int = 4096
    temperature: float | None = 0.3
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    provider_id: str | None = None
    provider_name: str | None = None


# ── kill switch / availability ──


def llm_off() -> bool:
    """``MARIOS_LLM_OFF=1`` 熔断：测试零网络、生产紧急关闭。"""
    return os.environ.get("MARIOS_LLM_OFF") == "1"


def _ambient_anthropic_creds() -> bool:
    """SDK 可解析的环境/本机凭证（与 llm_extract.llm_available 同口径）。"""
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.path.exists(os.path.expanduser("~/.config/anthropic"))
    )


# ── provider resolution ──

_SKILL_CODE_DEFAULTS = ("platform.assist.copilot",)


def _config_from_row(row: Any) -> LLMProviderConfig:
    s = get_settings()
    api_key = ""
    secret_ref = getattr(row, "secret_ref", None)
    if secret_ref:
        try:
            from app.services.ops_crypto import decrypt_token

            api_key = decrypt_token(secret_ref) or ""
        except Exception:  # noqa: BLE001 — 密钥不可解密时不阻断，走 SDK 环境凭证
            log.warning("llm_client: cannot decrypt provider secret_ref, using ambient creds")
            api_key = ""
    if not api_key:
        cfg = getattr(row, "config", None) or {}
        if isinstance(cfg, dict):
            api_key = str(cfg.get("api_key") or "")
    ptype = (getattr(row, "provider_type", None) or "anthropic").lower()
    if ptype in ("openai_compatible", "openai-compatible", "azure_openai"):
        ptype = "openai"
    if ptype not in ("anthropic", "openai"):
        ptype = "anthropic"
    base_url = getattr(row, "base_url", None) or (
        s.anthropic_base_url if ptype == "anthropic" else s.openai_base_url
    )
    model = getattr(row, "model_default", None) or s.llm_model
    return LLMProviderConfig(
        provider_type=ptype,
        api_key=api_key,
        base_url=str(base_url),
        model=str(model),
        max_tokens=s.llm_max_tokens,
        temperature=s.llm_temperature,
        timeout_seconds=s.llm_timeout_seconds,
        provider_id=str(getattr(row, "id", "") or "") or None,
        provider_name=getattr(row, "name", None),
    )


def _find_provider_row(db: Any, tenant_id: Any, *, skill_code: str | None, agent_name: str | None):
    """Skill binding → 默认 provider → 空（回落平台配置）。"""
    from sqlalchemy import select

    from app.models_wave1 import AiProvider, AiSkillBinding

    candidates: list[str] = []
    if skill_code:
        candidates.append(skill_code)
    if agent_name:
        candidates.append(f"agent.{agent_name}")
    candidates.extend(_SKILL_CODE_DEFAULTS)
    for code in candidates:
        binding = db.scalars(
            select(AiSkillBinding).where(
                AiSkillBinding.tenant_id == tenant_id,
                AiSkillBinding.skill_code == code,
                AiSkillBinding.enabled.is_(True),
            )
        ).first()
        if binding and binding.primary_provider_id:
            row = db.get(AiProvider, binding.primary_provider_id)
            if row and row.tenant_id == tenant_id:
                return row
    return db.scalars(
        select(AiProvider)
        .where(AiProvider.tenant_id == tenant_id, AiProvider.status == "active")
        .order_by(AiProvider.created_at)
    ).first()


def config_from_provider_row(row: Any) -> LLMProviderConfig:
    """Build an :class:`LLMProviderConfig` from an ``AiProvider`` ORM row.

    Decrypts ``secret_ref`` when present (falls back to ``config.api_key``).
    Used by the AI-settings provider test / model listing endpoints.
    """
    return _config_from_row(row)


def resolve_provider_config(
    db: Any = None,
    tenant_id: Any = None,
    *,
    skill_code: str | None = None,
    agent_name: str | None = None,
) -> LLMProviderConfig:
    """Resolve the effective LLM provider: tenant AiProvider → config.py defaults."""
    if llm_off():
        raise LLMNotConfigured("MARIOS_LLM_OFF=1 kill switch active")
    s = get_settings()
    if db is not None and tenant_id is not None:
        try:
            row = _find_provider_row(
                db, tenant_id, skill_code=skill_code, agent_name=agent_name
            )
        except Exception:  # noqa: BLE001 — 解析失败不阻断，回落平台配置
            log.exception("llm_client: provider lookup failed, using platform defaults")
            row = None
        if row is not None:
            return _config_from_row(row)
    if s.anthropic_api_key or _ambient_anthropic_creds():
        return LLMProviderConfig(
            provider_type="anthropic",
            api_key=s.anthropic_api_key,
            base_url=s.anthropic_base_url,
            model=s.llm_model,
            max_tokens=s.llm_max_tokens,
            temperature=s.llm_temperature,
            timeout_seconds=s.llm_timeout_seconds,
        )
    if s.openai_api_key:
        return LLMProviderConfig(
            provider_type="openai",
            api_key=s.openai_api_key,
            base_url=s.openai_base_url,
            model=s.llm_model,
            max_tokens=s.llm_max_tokens,
            temperature=s.llm_temperature,
            timeout_seconds=s.llm_timeout_seconds,
        )
    raise LLMNotConfigured("no LLM provider configured (set ANTHROPIC_API_KEY or an AiProvider)")


# ── message format helpers (normalized ⇄ provider) ──
#
# Normalized messages (mari_ai side):
#   {"role": "user", "content": str}
#   {"role": "assistant", "content": str, "tool_calls": [ToolCall|dict, ...]}
#   {"role": "tool", "tool_call_id": str, "name": str, "content": str}


def _tool_calls_as_dicts(tool_calls: list) -> list[dict]:
    out = []
    for tc in tool_calls or []:
        if isinstance(tc, ToolCall):
            out.append({"id": tc.id, "name": tc.name, "arguments": tc.arguments})
        elif isinstance(tc, dict):
            out.append(
                {
                    "id": tc.get("id") or tc.get("tool_call_id") or "",
                    "name": tc.get("name") or "",
                    "arguments": tc.get("arguments") or {},
                }
            )
    return out


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m.get("tool_call_id") or "",
                "content": str(m.get("content") or ""),
            }
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif role == "assistant":
            content: list[dict] = []
            text = m.get("content") or ""
            if text:
                content.append({"type": "text", "text": text})
            for tc in _tool_calls_as_dicts(m.get("tool_calls")):
                content.append(
                    {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]}
                )
            out.append({"role": "assistant", "content": content or [{"type": "text", "text": ""}]})
        else:
            out.append({"role": "user", "content": str(m.get("content") or "")})
    return out


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id") or "",
                    "content": str(m.get("content") or ""),
                }
            )
        elif role == "assistant":
            tcs = _tool_calls_as_dicts(m.get("tool_calls"))
            item: dict = {"role": "assistant", "content": m.get("content") or ""}
            if tcs:
                item["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": _json_dumps(tc["arguments"] or {}),
                        },
                    }
                    for tc in tcs
                ]
            out.append(item)
        else:
            out.append({"role": "user", "content": str(m.get("content") or "")})
    return out


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)


def _to_anthropic_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    out = []
    for t in tools:
        out.append(
            {
                "name": t["name"],
                "description": t.get("description") or "",
                "input_schema": t.get("input_schema")
                or t.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return out


def _to_openai_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description") or "",
                "parameters": t.get("input_schema")
                or t.get("parameters")
                or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


_NO_SAMPLING_RE = re.compile(
    r"^claude-(opus-(5|5-5|4-[678])|sonnet-(5|4-6)|fable-5(-1)?|mythos-5(-1)?)"
)


def anthropic_accepts_sampling(model: str) -> bool:
    """新一代 Claude 移除 temperature/top_p（发送即 400）；旧模型仍接受。"""
    return not bool(_NO_SAMPLING_RE.match((model or "").strip()))


# ── chat completion ──


def chat_completion(
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    system: str | None = None,
    tools: list[dict] | None = None,
    provider: LLMProviderConfig | None = None,
) -> LLMResponse:
    """One chat turn. Raises :class:`LLMNotConfigured` / :class:`LLMError`."""
    if llm_off():
        raise LLMNotConfigured("MARIOS_LLM_OFF=1 kill switch active")
    cfg = provider or resolve_provider_config()
    use_model = model or cfg.model
    use_max = max_tokens if max_tokens is not None else cfg.max_tokens
    use_temp = temperature if temperature is not None else cfg.temperature
    if cfg.provider_type == "openai":
        return _chat_openai(cfg, messages, use_model, use_max, use_temp, system, tools)
    return _chat_anthropic(cfg, messages, use_model, use_max, use_temp, system, tools)


def _chat_anthropic(
    cfg: LLMProviderConfig,
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float | None,
    system: str | None,
    tools: list[dict] | None,
) -> LLMResponse:
    import anthropic

    client = anthropic.Anthropic(
        api_key=cfg.api_key or None,
        base_url=cfg.base_url or None,
        timeout=float(cfg.timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": _to_anthropic_messages(messages),
    }
    if system:
        kwargs["system"] = system
    ant_tools = _to_anthropic_tools(tools)
    if ant_tools:
        kwargs["tools"] = ant_tools
    if temperature is not None and anthropic_accepts_sampling(model):
        kwargs["temperature"] = temperature
    start = time.time()
    try:
        resp = client.messages.create(**kwargs)
    except anthropic.NotFoundError as exc:
        raise LLMError(f"model/endpoint not found: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(f"rate limited: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"API error {exc.status_code}: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"connection error: {exc}") from exc
    latency = int((time.time() - start) * 1000)

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in getattr(resp, "content", None) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(getattr(block, "text", "") or "")
        elif btype == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=getattr(block, "id", "") or f"call_{len(tool_calls)}",
                    name=getattr(block, "name", "") or "",
                    arguments=dict(getattr(block, "input", None) or {}),
                )
            )
    usage_obj = getattr(resp, "usage", None)
    usage = LLMUsage(
        input_tokens=int(getattr(usage_obj, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage_obj, "output_tokens", 0) or 0),
    )
    return LLMResponse(
        text="".join(text_parts).strip(),
        model=getattr(resp, "model", None) or model,
        latency_ms=latency,
        usage=usage,
        tool_calls=tool_calls,
        stop_reason=getattr(resp, "stop_reason", None),
        provider_type="anthropic",
        raw=resp,
    )


def _chat_openai(
    cfg: LLMProviderConfig,
    messages: list[dict],
    model: str,
    max_tokens: int,
    temperature: float | None,
    system: str | None,
    tools: list[dict] | None,
) -> LLMResponse:
    oai_messages: list[dict] = []
    if system:
        oai_messages.append({"role": "system", "content": system})
    oai_messages.extend(_to_openai_messages(messages))
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": oai_messages,
    }
    if temperature is not None:
        body["temperature"] = temperature
    oai_tools = _to_openai_tools(tools)
    if oai_tools:
        body["tools"] = oai_tools
        body["tool_choice"] = "auto"
    base = (cfg.base_url or "").rstrip("/")
    start = time.time()
    try:
        resp = httpx.post(
            f"{base}{OPENAI_COMPAT_PATH}",
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=float(cfg.timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
        )
    except httpx.HTTPError as exc:
        raise LLMError(f"connection error: {exc}") from exc
    latency = int((time.time() - start) * 1000)
    if resp.status_code == 404:
        raise LLMError(f"model/endpoint not found: {resp.status_code}")
    if resp.status_code == 429:
        raise LLMError(f"rate limited: {resp.status_code}")
    if resp.status_code >= 400:
        raise LLMError(f"API error {resp.status_code}: {resp.text[:400]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise LLMError(f"invalid JSON response: {exc}") from exc

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    tool_calls: list[ToolCall] = []
    for i, tc in enumerate(message.get("tool_calls") or []):
        fn = tc.get("function") or {}
        raw_args = fn.get("arguments") or "{}"
        try:
            import json

            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except ValueError:
            args = {"_raw": raw_args}
        tool_calls.append(
            ToolCall(
                id=tc.get("id") or f"call_{i}",
                name=fn.get("name") or "",
                arguments=args if isinstance(args, dict) else {"value": args},
            )
        )
    usage_raw = data.get("usage") or {}
    usage = LLMUsage(
        input_tokens=int(usage_raw.get("prompt_tokens") or 0),
        output_tokens=int(usage_raw.get("completion_tokens") or 0),
    )
    return LLMResponse(
        text=(message.get("content") or "").strip(),
        model=data.get("model") or model,
        latency_ms=latency,
        usage=usage,
        tool_calls=tool_calls,
        stop_reason=choice.get("finish_reason"),
        provider_type="openai",
        raw=data,
    )


# ── connectivity probe / model listing (AI settings) ──


def list_models(provider: LLMProviderConfig, *, limit: int = 50) -> list[str]:
    """List model ids exposed by the provider endpoint (live call)."""
    if llm_off():
        raise LLMNotConfigured("MARIOS_LLM_OFF=1 kill switch active")
    if provider.provider_type == "openai":
        base = (provider.base_url or "").rstrip("/")
        try:
            resp = httpx.get(
                f"{base}{OPENAI_MODELS_PATH}",
                headers={"Authorization": f"Bearer {provider.api_key}"},
                timeout=float(provider.timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"connection error: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMError(f"API error {resp.status_code}: {resp.text[:400]}")
        data = resp.json().get("data") or []
        return [m.get("id") for m in data if m.get("id")][:limit]

    import anthropic

    client = anthropic.Anthropic(
        api_key=provider.api_key or None,
        base_url=provider.base_url or None,
        timeout=float(provider.timeout_seconds or DEFAULT_TIMEOUT_SECONDS),
    )
    try:
        page = client.models.list()
    except anthropic.NotFoundError as exc:
        raise LLMError(f"models endpoint not found: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError(f"rate limited: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"API error {exc.status_code}: {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"connection error: {exc}") from exc
    ids: list[str] = []
    for m in page:
        mid = getattr(m, "id", None)
        if mid:
            ids.append(mid)
        if len(ids) >= limit:
            break
    return ids


def test_provider(provider: LLMProviderConfig) -> dict:
    """Live connectivity probe: model list + actual latency. Never raises."""
    start = time.time()
    if llm_off():
        return {
            "ok": False,
            "provider_type": provider.provider_type,
            "model": provider.model,
            "latency_ms": int((time.time() - start) * 1000),
            "models": [],
            "message": "MARIOS_LLM_OFF=1 kill switch active — probe skipped",
        }
    try:
        models = list_models(provider)
    except LLMError as exc:
        return {
            "ok": False,
            "provider_type": provider.provider_type,
            "model": provider.model,
            "latency_ms": int((time.time() - start) * 1000),
            "models": [],
            "message": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        log.exception("llm_client: provider probe failed")
        return {
            "ok": False,
            "provider_type": provider.provider_type,
            "model": provider.model,
            "latency_ms": int((time.time() - start) * 1000),
            "models": [],
            "message": f"probe failed: {exc}",
        }
    return {
        "ok": True,
        "provider_type": provider.provider_type,
        "model": provider.model,
        "latency_ms": int((time.time() - start) * 1000),
        "models": models,
        "message": "connected",
    }


# Static catalog — offline fallback for the models endpoint when no live probe.
ANTHROPIC_MODEL_CATALOG = [
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "claude-opus-4-8",
    "claude-sonnet-4-6",
]
OPENAI_MODEL_CATALOG = ["gpt-4o", "gpt-4o-mini"]


def model_catalog(provider_type: str) -> list[str]:
    return OPENAI_MODEL_CATALOG if provider_type == "openai" else ANTHROPIC_MODEL_CATALOG
