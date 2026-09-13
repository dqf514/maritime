from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_wave1 import AiProvider, AiSkillBinding
from app.schemas_wave1 import (
    AiProviderIn,
    AiProviderOut,
    AiSkillBindingIn,
    AiSkillBindingOut,
    SkillCatalogItem,
)
from app.security import AuthContext, require_module

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


@router.get("/skills/catalog", response_model=list[SkillCatalogItem])
def skill_catalog(auth: AuthContext = Depends(require_module("ai"))):
    _ = auth
    return SKILL_CATALOG


@router.get("/providers", response_model=list[AiProviderOut])
def list_providers(
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(AiProvider).where(AiProvider.tenant_id == auth.tenant_id)).all()
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


@router.post("/providers/{provider_id}/test")
def test_provider(
    provider_id: UUID,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    row = db.get(AiProvider, provider_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Provider not found")
    # Wave 1: connectivity stub — real HTTP probe in later wave
    return {
        "ok": True,
        "provider_id": str(row.id),
        "provider_type": row.provider_type,
        "model": row.model_default,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "message": "Stub OK — configure base_url/secret_ref for live calls",
    }


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
