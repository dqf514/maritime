"""MariAI 业务 Agent 路由（Phase 2 / D26）：草稿生成动作。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module

router = APIRouter(prefix="/ai", tags=["MariAI Actions"])


class DraftIn(BaseModel):
    action: str  # laytime_statement | voyage_instruction | exception_explanation
    laytime_id: str | None = None
    voyage_id: str | None = None
    entity_id: str | None = None
    kind: str | None = None


@router.post("/actions/draft")
def action_draft(
    body: DraftIn,
    auth: AuthContext = Depends(require_module("analytics")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """生成业务草稿：确定性引擎 + 可选 LLM 叙述（AI 建议，人工确认后使用）。"""
    from app.services import mari_ai_actions as actions

    if body.action == "laytime_statement":
        if not body.laytime_id:
            raise HTTPException(422, "laytime_id required")
        return actions.laytime_statement_draft(db, auth.tenant_id, body.laytime_id)
    if body.action == "voyage_instruction":
        if not body.voyage_id:
            raise HTTPException(422, "voyage_id required")
        return actions.voyage_instruction_draft(db, auth.tenant_id, body.voyage_id)
    if body.action == "exception_explanation":
        return actions.exception_explanation(db, auth.tenant_id, entity_id=body.entity_id, kind=body.kind)
    raise HTTPException(422, detail={"code": "UNKNOWN_ACTION", "message": body.action})
