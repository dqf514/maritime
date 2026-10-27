"""AI Hub settings: LLM providers, skill bindings, model catalog, usage, agents.

Provider endpoints: full CRUD (create/list/patch/soft-delete) + live connectivity
probe and model listing via :mod:`app.services.llm_client`.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_ai import AIConversation, AIMessage, AIAgentDefinition
from app.models_wave1 import AiProvider, AiSkillBinding
from app.schemas_wave1 import (
    AiProviderIn,
    AiProviderOut,
    AiSkillBindingIn,
    AiSkillBindingOut,
    SkillCatalogItem,
)
from app.security import AuthContext, require_module
from app.services import llm_client
from app.services.integration_adapters import (
    SECRET_MASK,
    TOKEN_PREFIX,
    encrypt_secret_keys,
    mask_secret_keys,
    mask_token_ref,
)

router = APIRouter(prefix="/settings/ai", tags=["AI Hub"])

SKILL_CATALOG = [
    SkillCatalogItem(skill_code="email.classify", module="email", description="Classify inbound email type"),
    SkillCatalogItem(skill_code="email.extract.recap", module="email", description="Extract recap fields"),
    SkillCatalogItem(skill_code="email.extract.nor", module="email", description="Extract NOR fields"),
    SkillCatalogItem(skill_code="migrate.classify", module="dataops", description="Classify migration artifacts"),
    SkillCatalogItem(skill_code="migrate.map.excel_headers", module="dataops", description="Map Excel headers"),
    SkillCatalogItem(skill_code="migrate.extract.generic", module="dataops", description="Generic migration extract"),
    SkillCatalogItem(skill_code="platform.assist.copilot", module="platform", description="Global read-only copilot"),
]


class AiProviderPatch(BaseModel):
    """Partial provider update. ``api_key`` is stored encrypted in ``secret_ref``."""

    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_default: str | None = None
    secret_ref: str | None = None
    config: dict | None = None


class AIAgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_name: str
    display_name: str
    description: str | None = None
    model_name: str
    temperature: float | None = None
    enabled: bool


class AIAgentPatch(BaseModel):
    model_name: str | None = None
    temperature: float | None = None


class ProviderModelsOut(BaseModel):
    provider_id: str
    provider_name: str
    provider_type: str
    model_default: str | None = None
    models: list[str]
    source: str  # live | catalog


class AiDefaultsIn(BaseModel):
    """Tenant global LLM defaults — stored on the tenant's default provider row."""

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_s: int | None = None


# ── Skills ──


@router.get("/skills/catalog", response_model=list[SkillCatalogItem])
def skill_catalog(auth: AuthContext = Depends(require_module("ai"))):
    _ = auth
    return SKILL_CATALOG


@router.get("/skills/bindings", response_model=list[AiSkillBindingOut])
def list_bindings(
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(AiSkillBinding).where(AiSkillBinding.tenant_id == auth.tenant_id)).all()
    return [AiSkillBindingOut.model_validate(r, from_attributes=True) for r in rows]


@router.put("/skills/{skill_code}/binding", response_model=AiSkillBindingOut)
def upsert_binding(
    skill_code: str,
    body: AiSkillBindingIn,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(AiSkillBinding).where(
            AiSkillBinding.tenant_id == auth.tenant_id,
            AiSkillBinding.skill_code == skill_code,
        )
    )
    payload = body.model_dump()
    payload["skill_code"] = skill_code
    if row:
        for k, v in payload.items():
            setattr(row, k, v)
    else:
        row = AiSkillBinding(tenant_id=auth.tenant_id, **payload)
        db.add(row)
    db.commit()
    db.refresh(row)
    return AiSkillBindingOut.model_validate(row, from_attributes=True)


# ── Providers ──


def _get_provider(db: Session, tenant_id: UUID, provider_id: UUID) -> AiProvider:
    row = db.get(AiProvider, provider_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(404, "Provider not found")
    return row


# ── 凭据处理（P0-19）───────────────────────────────────────────
#
# 供应商的 API Key 有两个落点：``AiProvider.secret_ref``（主）与
# ``AiProvider.config["api_key"]``（历史兼容）。两条路都必须是
# **加密落库 + 响应掩码**，否则任何登录用户都能读到管理员配的密钥。

#: 客户端把掩码原样发回来时按「保持原值不变」处理。
_MASKED_SECRET_INPUTS = frozenset({SECRET_MASK, f"{TOKEN_PREFIX}{SECRET_MASK}"})


def _encrypt_secret(value: str | None, current: str | None = None) -> str | None:
    """把明文密钥加密成 ``v1:`` 版本化令牌。

    - 掩码（``***`` / ``v1:***``）→ 视为「没改」，返回原值；
    - 已是 ``v1:`` 的原样保留（幂等，重复保存不会二次加密）；
    - 其余按明文加密（``ops_crypto.encrypt_token``）。
    """
    if value is None:
        return current
    text = str(value).strip()
    if not text or text in _MASKED_SECRET_INPUTS:
        return current
    if text.startswith(TOKEN_PREFIX):
        return text
    from app.services.ops_crypto import encrypt_token

    try:
        return encrypt_token(text)
    except Exception as exc:  # noqa: BLE001 — 密钥必须加密落库，宁可失败也不落明文
        raise HTTPException(
            503,
            detail={
                "code": "SECRET_ENCRYPTION_UNAVAILABLE",
                "message": "无法加密保存密钥，请检查 OPS_DATA_KEY / JWT_SECRET 配置",
            },
        ) from exc


def _provider_out(row: AiProvider) -> AiProviderOut:
    """供应商响应 —— **不回吐密钥**（P0-19）。

    ``AiProviderOut`` 继承 ``AiProviderIn``，``secret_ref``（密文/明文）与
    ``config`` 里的 ``api_key`` 原本整块回吐。这里统一换成掩码：
    ``secret_ref`` 只保留 ``v1:`` 版本前缀（前端据此知道「已配置密钥」），
    密文本体与 ``config`` 里的密钥值一律遮成 ``***``。
    """
    return AiProviderOut.model_validate(row, from_attributes=True).model_copy(
        update={
            "secret_ref": mask_token_ref(row.secret_ref),
            "config": mask_secret_keys(row.config),
        }
    )


@router.get("/providers", response_model=list[AiProviderOut])
def list_providers(
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(AiProvider).where(
            AiProvider.tenant_id == auth.tenant_id,
            AiProvider.status != "deleted",
        )
    ).all()
    return [_provider_out(r) for r in rows]


@router.post("/providers", response_model=AiProviderOut)
def create_provider(
    body: AiProviderIn,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    data = body.model_dump()
    config = dict(data.pop("config") or {})
    raw_ref = data.pop("secret_ref", None)
    # P0-19：config 里带的 api_key 提升为 secret_ref（加密落库），
    # config 里不再留明文密钥。
    inline_key = config.pop("api_key", None)
    row = AiProvider(
        tenant_id=auth.tenant_id,
        status="active",
        name=data.get("name") or "",
        provider_type=data.get("provider_type") or "",
        base_url=data.get("base_url"),
        model_default=data.get("model_default"),
        secret_ref=_encrypt_secret(inline_key or raw_ref),
        config=encrypt_secret_keys(config),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _provider_out(row)


@router.patch("/providers/{provider_id}", response_model=AiProviderOut)
def update_provider(
    provider_id: UUID,
    body: AiProviderPatch,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    row = _get_provider(db, auth.tenant_id, provider_id)
    payload = body.model_dump(exclude_unset=True)
    api_key = payload.pop("api_key", None)
    raw_ref = payload.pop("secret_ref", None)
    incoming_cfg = payload.pop("config", None)

    old_cfg = dict(row.config or {})
    old_key = old_cfg.get("api_key") if isinstance(old_cfg.get("api_key"), str) else None

    new_cfg = dict(incoming_cfg) if incoming_cfg is not None else dict(old_cfg)
    inline_key = new_cfg.pop("api_key", None)
    # 密钥来源优先级：显式 api_key > 显式 secret_ref > 本次 config 里的 api_key
    # > 存量 config.api_key（顺带把历史明文迁进 secret_ref）
    secret = api_key or raw_ref or inline_key or old_key
    if secret is not None:
        payload["secret_ref"] = _encrypt_secret(secret, current=row.secret_ref)
    if incoming_cfg is not None or old_key:
        payload["config"] = encrypt_secret_keys(new_cfg)
    for k, v in payload.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _provider_out(row)


@router.delete("/providers/{provider_id}")
def delete_provider(
    provider_id: UUID,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """Soft delete — row kept for audit/binding history, status flips to deleted."""
    row = _get_provider(db, auth.tenant_id, provider_id)
    row.status = "deleted"
    db.commit()
    return {"deleted": True, "provider_id": str(row.id), "status": row.status}


@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: UUID,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """Live connectivity probe via llm_client (model list + latency)."""
    row = _get_provider(db, auth.tenant_id, provider_id)
    cfg = llm_client.config_from_provider_row(row)
    result = llm_client.test_provider(cfg)
    return {
        **result,
        "provider_id": str(row.id),
        "tested_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Models & usage ──


@router.get("/models", response_model=list[ProviderModelsOut])
def list_models(
    provider_id: UUID | None = Query(None),
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """Available models per provider: live /models probe, config-catalog fallback."""
    stmt = select(AiProvider).where(
        AiProvider.tenant_id == auth.tenant_id,
        AiProvider.status != "deleted",
    )
    if provider_id:
        stmt = stmt.where(AiProvider.id == provider_id)
    rows = db.scalars(stmt).all()
    if provider_id and not rows:
        raise HTTPException(404, "Provider not found")
    out: list[ProviderModelsOut] = []
    for row in rows:
        models: list[str] = []
        source = "catalog"
        try:
            cfg = llm_client.config_from_provider_row(row)
            models = llm_client.list_models(cfg)
            source = "live"
        except Exception:  # noqa: BLE001 — kill switch / 无凭证 / 端点失败 → 静态目录
            models = llm_client.model_catalog(row.provider_type or "anthropic")
        if row.model_default and row.model_default not in models:
            models = [row.model_default, *models]
        out.append(
            ProviderModelsOut(
                provider_id=str(row.id),
                provider_name=row.name,
                provider_type=row.provider_type,
                model_default=row.model_default,
                models=models[:50],
                source=source,
            )
        )
    return out


def _default_provider(db: Session, tenant_id: UUID) -> AiProvider | None:
    """Tenant's default provider — the row that carries global model defaults."""
    return db.scalar(
        select(AiProvider)
        .where(AiProvider.tenant_id == tenant_id, AiProvider.status != "deleted")
        .order_by(AiProvider.created_at)
        .limit(1)
    )


def _defaults_out(row: AiProvider | None) -> dict:
    if row is None:
        return {
            "model": None,
            "temperature": None,
            "max_tokens": None,
            "timeout_s": None,
            "provider_id": None,
            "provider_name": None,
        }
    cfg = row.config or {}
    return {
        "model": row.model_default,
        "temperature": cfg.get("temperature"),
        "max_tokens": cfg.get("max_tokens"),
        "timeout_s": cfg.get("timeout_s"),
        "provider_id": str(row.id),
        "provider_name": row.name,
    }


@router.get("/defaults")
def get_defaults(
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """Global LLM defaults (model / temperature / max_tokens / timeout)."""
    return _defaults_out(_default_provider(db, auth.tenant_id))


@router.put("/defaults")
def put_defaults(
    body: AiDefaultsIn,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """Persist global defaults on the tenant's default provider row."""
    row = _default_provider(db, auth.tenant_id)
    if row is None:
        raise HTTPException(
            400,
            detail={
                "code": "NO_PROVIDER",
                "message": "Create an AI provider first, then set global defaults.",
            },
        )
    if body.model is not None:
        row.model_default = body.model.strip() or None
    cfg = dict(row.config or {})
    for key in ("temperature", "max_tokens", "timeout_s"):
        value = getattr(body, key)
        if value is not None:
            cfg[key] = value
    row.config = encrypt_secret_keys(cfg)
    db.commit()
    db.refresh(row)
    return _defaults_out(row)


@router.get("/usage")
def usage_stats(
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """Token usage stats aggregated from AIMessage.

    Grouped by agent / conversation / day (ISO date). Aggregated in-process to
    stay portable across SQLite and Postgres.

    响应同时携带两套字段：
    - 前端用量页契约：``key/label/requests/tokens_in/tokens_out/tokens_total/
      avg_latency_ms`` + ``totals``（缺 cost 数据时 cost_usd=null → UI 显示 —）；
    - 旧字段（``total_tokens/message_count/by_* 的 agent_name/tokens/messages``）
      保留，兼容既有调用方与测试。
    """
    rows = db.execute(
        select(AIMessage, AIConversation)
        .join(AIConversation, AIMessage.conversation_id == AIConversation.id)
        .where(AIConversation.tenant_id == auth.tenant_id)
    ).all()

    # agent 显示名（全局 + 本租户；无定义时 key 即 label）
    disp: dict[str, str] = {}
    for a in db.scalars(
        select(AIAgentDefinition).where(
            (AIAgentDefinition.tenant_id.is_(None))
            | (AIAgentDefinition.tenant_id == auth.tenant_id)
        )
    ).all():
        disp[a.agent_name] = a.display_name

    total_tokens = 0
    counted = 0
    latency_sum = 0
    latency_n = 0
    total_requests = 0

    def _slot() -> dict[str, Any]:
        return {
            "tokens": 0,
            "messages": 0,
            "requests": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "has_in": False,
            "has_out": False,
            "lat_sum": 0,
            "lat_n": 0,
        }

    by_agent: dict[str, dict[str, Any]] = {}
    by_day: dict[str, dict[str, Any]] = {}
    by_conv: dict[str, dict[str, Any]] = {}
    conv_meta: dict[str, AIConversation] = {}

    for msg, conv in rows:
        tokens = int(msg.tokens_used or 0)
        if msg.tokens_used is not None:
            total_tokens += tokens
            counted += 1
        if msg.latency_ms is not None:
            latency_sum += int(msg.latency_ms)
            latency_n += 1
        # 「请求数」= 助手回复条数（用户提问条不重复计）
        is_reply = msg.role == "assistant"
        if is_reply:
            total_requests += 1
        day = (msg.created_at.date().isoformat() if msg.created_at else None) or "unknown"
        conv_key = str(conv.id)
        conv_meta[conv_key] = conv

        for group, key in (
            (by_agent, conv.agent_name or "unknown"),
            (by_day, day),
            (by_conv, conv_key),
        ):
            slot = group.setdefault(key, _slot())
            slot["tokens"] += tokens
            slot["messages"] += 1
            if is_reply:
                slot["requests"] += 1
            if msg.tokens_in is not None:
                slot["tokens_in"] += int(msg.tokens_in)
                slot["has_in"] = True
            if msg.tokens_out is not None:
                slot["tokens_out"] += int(msg.tokens_out)
                slot["has_out"] = True
            if msg.latency_ms is not None:
                slot["lat_sum"] += int(msg.latency_ms)
                slot["lat_n"] += 1

    def _out(key: str, slot: dict[str, Any], label: str, **legacy: Any) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "requests": slot["requests"],
            "tokens_total": slot["tokens"],
            "tokens_in": slot["tokens_in"] if slot["has_in"] else None,
            "tokens_out": slot["tokens_out"] if slot["has_out"] else None,
            "avg_latency_ms": round(slot["lat_sum"] / slot["lat_n"], 1) if slot["lat_n"] else None,
            # 旧字段（兼容）
            "tokens": slot["tokens"],
            "messages": slot["messages"],
            **legacy,
        }

    return {
        # 前端契约
        "totals": {
            "requests": total_requests,
            "tokens_total": total_tokens,
            "cost_usd": None,  # 无定价数据源 —— 前端显示 —，不编数字
        },
        "by_agent": [
            _out(k, v, disp.get(k, k), agent_name=k) for k, v in sorted(by_agent.items())
        ],
        "by_day": [_out(k, v, k, day=k) for k, v in sorted(by_day.items())],
        "by_conversation": [
            _out(
                k,
                v,
                (conv_meta[k].title or conv_meta[k].agent_name or "") if k in conv_meta else k,
                conversation_id=k,
                agent_name=conv_meta[k].agent_name if k in conv_meta else None,
            )
            for k, v in sorted(by_conv.items())
        ],
        # 旧字段（兼容既有调用方/测试）
        "total_tokens": total_tokens,
        "message_count": counted,
        "avg_latency_ms": round(latency_sum / latency_n, 1) if latency_n else 0,
    }


# ── Agents ──


@router.get("/agents", response_model=list[AIAgentOut])
def list_agents(
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(AIAgentDefinition).where(
            (AIAgentDefinition.tenant_id.is_(None))
            | (AIAgentDefinition.tenant_id == auth.tenant_id)
        ).order_by(AIAgentDefinition.agent_name)
    ).all()
    return [AIAgentOut.model_validate(r, from_attributes=True) for r in rows]


@router.patch("/agents/{agent_id}", response_model=AIAgentOut)
def update_agent(
    agent_id: UUID,
    body: AIAgentPatch,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    row = db.get(AIAgentDefinition, agent_id)
    if not row or (row.tenant_id is not None and row.tenant_id != auth.tenant_id):
        raise HTTPException(404, "Agent not found")
    payload = body.model_dump(exclude_unset=True)
    if "temperature" in payload and payload["temperature"] is not None:
        temp = float(payload["temperature"])
        if not (0.0 <= temp <= 2.0):
            raise HTTPException(422, "temperature must be between 0 and 2")
        payload["temperature"] = temp
    for k, v in payload.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return AIAgentOut.model_validate(row, from_attributes=True)
