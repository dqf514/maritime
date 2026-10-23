"""全局 AI 助手端点 — 弹出问答 / 表单填充 / 总结汇报 / 邮件动作推荐。

与 ``/ai/conversations/{id}/chat``（整页 MariAI，会话制）互补：这里面向
「用户正对着某个表单/记录问一句」的轻量场景，自动带上当前上下文，
不要求用户先建会话。所有端点只产出建议，落库动作仍由用户在既有业务
端点确认后触发。
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module
from app.services import ai_assist, ai_context

router = APIRouter(prefix="/ai/assist", tags=["MariAI Assist"])


class ContextIn(BaseModel):
    page: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    form_fields: dict | None = None
    selected_text: str | None = None
    extra: dict | None = None


class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    context: ContextIn | None = None


class FillIn(BaseModel):
    task: Literal["fill_form", "summarize", "daily_report", "draft_note", "explain", "compare"] = "fill_form"
    context: ContextIn | None = None
    form_fields: dict | None = None
    instruction: str | None = Field(default=None, max_length=2000)


def _build_ctx(db: Session, tenant_id: UUID, c: ContextIn | None) -> dict:
    if c is None:
        return {}
    return ai_context.build_context(
        db,
        tenant_id,
        entity_type=c.entity_type,
        entity_id=c.entity_id,
        page=c.page,
        form_fields=c.form_fields,
        selected_text=c.selected_text,
        extra=c.extra,
    )


@router.get("/status")
def assist_status(
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """助手可用性 + provider + 计费余额（前端据此渲染禁用态/提示）。"""
    return ai_assist.status(db, auth.tenant_id)


@router.post("/ask")
def assist_ask(
    body: AskIn,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """上下文感知问答。402 QUOTA_EXCEEDED 在计费开启且余额不足时由引擎抛出。"""
    ctx = _build_ctx(db, auth.tenant_id, body.context)
    try:
        return ai_assist.ask(db, auth.tenant_id, auth.user_id, body.message, context=ctx)
    except HTTPException:
        raise
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/fill")
def assist_fill(
    body: FillIn,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """表单填充 / 总结 / 日报建议 —— 返回建议值 + 叙述，人工确认后应用。"""
    ctx = _build_ctx(db, auth.tenant_id, body.context)
    try:
        return ai_assist.fill(
            db,
            auth.tenant_id,
            auth.user_id,
            task=body.task,
            context=ctx,
            form_fields=body.form_fields,
            instruction=body.instruction,
        )
    except HTTPException:
        raise
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/recommend/email/{message_id}")
def recommend_email(
    message_id: UUID,
    auth: AuthContext = Depends(require_module("ai")),
    db: Session = Depends(get_db),
):
    """邮件下一步动作推荐（apply / reply / review），不落库。"""
    try:
        return ai_assist.recommend_email(db, auth.tenant_id, auth.user_id, message_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
