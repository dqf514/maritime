"""D25 LLM 结构化抽取：Claude 升级邮件解析，规则解析降级为兜底与交叉校验。

设计（保持「AI 建议 + 人工勾选确认落库」的产品语义不变）：

- 分类沿用规则（便宜、稳定）；字段抽取由 Claude 完成
  （官方 anthropic SDK，``client.messages.parse`` + Pydantic schema）；
- 规则解析并行运行，字段级 diff（``_rule_diffs``）供人工确认时对照；
- 无凭证 / 网络失败 / refusal / 任何 SDK 错误 → 自动回落纯规则
  （``_source: "rules"``），行为与升级前完全一致；
- 测试不触网：monkeypatch :func:`call_claude`。

模型：claude-opus-5（SDK 自动解析 ANTHROPIC_API_KEY / ant auth 凭证）。

**租户化（期一 · 例行任务中枢）**：新增 ``provider`` 参数 —— 传入租户自己的
``LLMProviderConfig``（``llm_client.resolve_provider_config`` 解析）时：
anthropic 端点走 ``messages.parse``（带租户 key），OpenAI 兼容端点走
``llm_client.chat_completion`` + JSON 结构化输出。两者都失败 → 规则兜底
（``_source="rules"``），与旧行为一致。**此前本模块写死 anthropic 环境凭证，
租户自备的 minimax / OpenAI 兼容端点在抽取链路上永远用不上** —— 那不是平台能力。
Refusal 处理：``stop_reason == "refusal"`` 时回落规则兜底
（服务端 fallbacks 参数可在凭证就绪后按需启用）。
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from pydantic import BaseModel, Field

log = logging.getLogger("marios.llm_extract")

ModelT = TypeVar("ModelT", bound=BaseModel)

CLAUDE_MODEL = "claude-opus-5"

SYSTEM_PROMPT = (
    "You are a maritime commercial-operations document parser. "
    "Extract the requested fields exactly as they appear in the email; "
    "convert numbers to numbers (no currency symbols or thousands separators); "
    "use null for any field not present. Never invent values."
)


# ── 抽取 schema（与规则解析器输出形状对齐） ──


class FixtureRecapExtraction(BaseModel):
    charterers: str | None = None
    owners: str | None = None
    vessel: str | None = None
    cargo: str | None = None
    load_port: str | None = None
    discharge_port: str | None = None
    laycan: str | None = None
    freight_rate: float | None = None
    demurrage_rate: float | None = None
    despatch_rate: float | None = None
    laytime_load: float | None = None
    laytime_discharge: float | None = None
    commission: float | None = None


class NorExtraction(BaseModel):
    vessel: str | None = None
    port: str | None = None
    date_time: str | None = None
    position: str | None = None
    draft: float | None = None


class LaytimeEventRow(BaseModel):
    time: str
    event: str


class LaytimeStatementExtraction(BaseModel):
    events: list[LaytimeEventRow] = Field(default_factory=list)
    allowed_days: float | None = None


class NoonReportExtraction(BaseModel):
    """船长/代理午报 —— 船位、油耗、ETA 与天气。"""

    vessel: str | None = None
    voyage_no: str | None = None
    report_at: str | None = None
    lat: float | None = None
    lon: float | None = None
    speed: float | None = None
    rob_fo: float | None = None
    rob_do: float | None = None
    eta_next: str | None = None
    remarks: str | None = None
    wind_bf: float | None = None
    sea_state: str | None = None
    current_kn: float | None = None


class BunkerOfferExtraction(BaseModel):
    """供油报价 —— 港/油品/价/量/供方/币种。"""

    vessel: str | None = None
    port: str | None = None
    grade: str | None = None
    unit_price: float | None = None
    qty_ordered: float | None = None
    supplier: str | None = None
    currency: str | None = None


class PortDisbursementExtraction(BaseModel):
    """使费账单（PDA/FDA）。"""

    vessel: str | None = None
    port: str | None = None
    pda_amount: float | None = None
    fda_amount: float | None = None
    currency: str | None = None
    agent: str | None = None


_EXTRACTION_MODELS: dict[str, type[BaseModel]] = {
    "fixture_recap": FixtureRecapExtraction,
    "nor": NorExtraction,
    "laytime_statement": LaytimeStatementExtraction,
    "noon_report": NoonReportExtraction,
    "bunker_offer": BunkerOfferExtraction,
    "port_disbursement": PortDisbursementExtraction,
}


def llm_available() -> bool:
    import os

    if os.environ.get("MARIOS_LLM_OFF") == "1":
        return False  # 测试环境熔断：保证 pytest 零网络
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False

    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.path.exists(os.path.expanduser("~/.config/anthropic"))
    )


def _anthropic_client(provider: Any = None):
    """构造 anthropic 客户端 —— 带租户 provider 的 key/base_url（无则走环境凭证）。"""
    import anthropic

    kwargs: dict[str, Any] = {}
    if provider is not None:
        api_key = getattr(provider, "api_key", "") or ""
        base_url = getattr(provider, "base_url", "") or ""
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
    return anthropic.Anthropic(**kwargs)


def call_claude(
    schema: type[ModelT], subject: str, body: str, *, provider: Any = None
) -> ModelT | None:
    """单次结构化抽取调用；任何失败返回 None（调用方回落规则）。

    错误链按 SDK 规范从具体到宽泛（NotFoundError → RateLimitError →
    APIStatusError → APIConnectionError），refusal 同样走兜底。

    ``provider`` 传入租户自己的 provider 配置时用其凭证与端点。
    """
    import anthropic

    client = _anthropic_client(provider)
    if not hasattr(client.messages, "parse"):
        # 旧 SDK（<0.79）无结构化抽取接口：回落规则，requirements 已钉 >=0.79
        log.warning("llm_extract: anthropic SDK lacks messages.parse (need >=0.79), falling back to rules")
        return None
    try:
        response = client.messages.parse(
            model=CLAUDE_MODEL,
            max_tokens=4096,  # 结构化抽取输出短，4096 足够且不触超时
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Email subject: {subject or '(none)'}\n\nEmail body:\n{body or ''}",
                }
            ],
            output_format=schema,
        )
    except anthropic.NotFoundError:
        log.warning("llm_extract: model/endpoint not found, falling back to rules")
        return None
    except anthropic.RateLimitError:
        log.warning("llm_extract: rate limited, falling back to rules")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("llm_extract: API error %s, falling back to rules", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("llm_extract: connection error, falling back to rules")
        return None
    except Exception:  # noqa: BLE001 — 任何意外（SDK 形状差异等）都不阻塞解析流水线
        log.exception("llm_extract: unexpected failure, falling back to rules")
        return None

    if response.stop_reason == "refusal":
        log.warning("llm_extract: refusal stop reason, falling back to rules")
        return None
    parsed = getattr(response, "parsed_output", None)
    return parsed if isinstance(parsed, schema) else None


def _model_to_dict(instance: BaseModel) -> dict[str, Any]:
    return {k: v for k, v in instance.model_dump().items() if v is not None}


def _diff_vs_rules(llm_fields: dict[str, Any], rule_fields: dict[str, Any]) -> list[dict[str, Any]]:
    """字段级交叉校验：LLM 与规则解析不一致的字段（人工确认对照用）。"""
    diffs = []
    for key in sorted(set(llm_fields) & set(rule_fields)):
        a, b = llm_fields[key], rule_fields[key]
        same = abs(float(a) - float(b)) < 0.01 if isinstance(a, (int, float)) and isinstance(b, (int, float)) else str(a).strip() == str(b).strip()
        if not same:
            diffs.append({"field": key, "llm_value": a, "rule_value": b})
    return diffs


def _strip_fences(text: str) -> str:
    """去掉模型偶尔加的 ```json 代码围栏。"""
    out = (text or "").strip()
    if not out.startswith("```"):
        return out
    parts = out.split("```")
    body = parts[1] if len(parts) > 1 else ""
    if body.lstrip().lower().startswith("json"):
        body = body.lstrip()[4:]
    return body.strip()


def extract_via_chat_json(
    schema: type[ModelT], subject: str, body: str, *, provider: Any = None
) -> ModelT | None:
    """通用 JSON 结构化抽取（OpenAI 兼容端点 / anthropic parse 失败后的兜底）。

    走 :func:`app.services.llm_client.chat_completion` —— provider 无关，
    因此租户配的 minimax 等 OpenAI 兼容端点也能做结构化抽取。
    任何失败返回 None（调用方回落规则）。
    """
    import json

    from app.services.llm_client import chat_completion

    instruction = (
        "You are a maritime commercial-operations document parser. "
        "Extract the requested fields exactly as they appear in the email; "
        "convert numbers to numbers (no currency symbols or thousands separators); "
        "use null for any field not present. Never invent values. "
        "Respond with a single JSON object matching this schema, no prose, no code fences:\n"
        + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    )
    try:
        resp = chat_completion(
            [
                {
                    "role": "user",
                    "content": f"Email subject: {subject or '(none)'}\n\nEmail body:\n{body or ''}",
                }
            ],
            system=instruction,
            provider=provider,
        )
    except Exception:  # noqa: BLE001 — 任何端点/网络/协议错误都回落规则
        log.warning("llm_extract: chat-json extraction failed, falling back to rules", exc_info=True)
        return None
    text = _strip_fences(resp.text or "")
    if not text:
        return None
    try:
        return schema.model_validate_json(text)
    except Exception:  # noqa: BLE001 — 模型没按 schema 输出 → 回落规则
        log.warning("llm_extract: model output did not match schema, falling back to rules")
        return None


def extract_fields(
    kind: str,
    subject: str,
    body: str,
    rule_fields: dict[str, Any] | None = None,
    *,
    provider: Any = None,
) -> dict[str, Any]:
    """D25 入口：LLM 抽取（失败回落规则），附规则交叉校验差异。

    返回 dict：抽取字段 + ``_source``（llm|rules）+ ``_rule_diffs``。

    ``provider``（租户自己的 LLM 配置）给了就用它：
    - anthropic 端点 → ``messages.parse``（结构化输出，失败再试 JSON 模式）
    - OpenAI 兼容端点 → ``chat_completion`` + JSON 结构化输出
    没给则沿用旧行为（环境 anthropic 凭证）。
    """
    rule_fields = rule_fields or {}
    schema = _EXTRACTION_MODELS.get(kind)
    if schema is None:
        return {**rule_fields, "_source": "rules", "_rule_diffs": []}

    parsed: Any = None
    if provider is not None:
        provider_type = (getattr(provider, "provider_type", "") or "").lower()
        if provider_type == "anthropic" and getattr(provider, "api_key", ""):
            parsed = call_claude(schema, subject, body, provider=provider)
        if parsed is None:
            parsed = extract_via_chat_json(schema, subject, body, provider=provider)
    else:
        if not llm_available():
            return {**rule_fields, "_source": "rules", "_rule_diffs": []}
        parsed = call_claude(schema, subject, body)
        if parsed is None:
            parsed = extract_via_chat_json(schema, subject, body)

    if parsed is None:
        return {**rule_fields, "_source": "rules", "_rule_diffs": []}

    llm_fields = _model_to_dict(parsed)
    return {
        **llm_fields,
        "_source": "llm",
        "_rule_diffs": _diff_vs_rules(llm_fields, rule_fields),
    }
