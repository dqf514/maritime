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
    return [AiProviderOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/providers", response_model=AiProviderOut)
def create_provider(
    body: AiProviderIn,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    row = AiProvider(tenant_id=auth.tenant_id, status="active", **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return AiProviderOut.model_validate(row, from_attributes=True)


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
    if api_key:
        try:
            from app.services.ops_crypto import encrypt_token

            payload["secret_ref"] = encrypt_token(api_key)
        except Exception:  # noqa: BLE001 — 加密不可用时回退明文 config（与解析侧一致）
            cfg = dict(row.config or {})
            cfg["api_key"] = api_key
            payload["config"] = cfg
    for k, v in payload.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return AiProviderOut.model_validate(row, from_attributes=True)


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


@router.get("/usage")
def usage_stats(
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """Token usage stats aggregated from AIMessage.tokens_used.

    Grouped by agent / conversation / day (ISO date). Aggregated in-process to
    stay portable across SQLite and Postgres.
    """
    rows = db.execute(
        select(AIMessage, AIConversation)
        .join(AIConversation, AIMessage.conversation_id == AIConversation.id)
        .where(AIConversation.tenant_id == auth.tenant_id)
    ).all()

    total_tokens = 0
    counted = 0
    latency_sum = 0
    latency_n = 0
    by_agent: dict[str, dict[str, Any]] = {}
    by_day: dict[str, dict[str, Any]] = {}
    by_conv: dict[str, dict[str, Any]] = {}

    for msg, conv in rows:
        tokens = int(msg.tokens_used or 0)
        if msg.tokens_used is not None:
            total_tokens += tokens
            counted += 1
        if msg.latency_ms is not None:
            latency_sum += int(msg.latency_ms)
            latency_n += 1
        day = (msg.created_at.date().isoformat() if msg.created_at else None) or "unknown"
        agent_slot = by_agent.setdefault(conv.agent_name or "unknown", {"tokens": 0, "messages": 0})
        agent_slot["tokens"] += tokens
        agent_slot["messages"] += 1
        day_slot = by_day.setdefault(day, {"tokens": 0, "messages": 0})
        day_slot["tokens"] += tokens
        day_slot["messages"] += 1
        conv_slot = by_conv.setdefault(
            str(conv.id),
            {"agent_name": conv.agent_name, "tokens": 0, "messages": 0},
        )
        conv_slot["tokens"] += tokens
        conv_slot["messages"] += 1

    return {
        "total_tokens": total_tokens,
        "message_count": counted,
        "avg_latency_ms": round(latency_sum / latency_n, 1) if latency_n else 0,
        "by_agent": [{"agent_name": k, **v} for k, v in sorted(by_agent.items())],
        "by_day": [{"day": k, **v} for k, v in sorted(by_day.items())],
        "by_conversation": [
            {"conversation_id": k, **v} for k, v in sorted(by_conv.items())
        ],
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
