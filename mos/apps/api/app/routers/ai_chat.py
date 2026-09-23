"""Phase 5 — MariAI agent chat endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module
from app.services import mari_ai

router = APIRouter(prefix="/ai", tags=["MariAI"])


class AgentOut(BaseModel):
    agent_name: str
    display_name: str
    description: str | None
    tools: list
    model_name: str

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: str
    agent_name: str
    title: str | None
    status: str
    message_count: int
    created_at: str
    updated_at: str | None


class ConversationIn(BaseModel):
    agent_name: str
    title: str | None = None
    context: dict | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    tool_calls_json: dict | None
    tokens_used: int | None
    latency_ms: int | None
    created_at: str


class ChatIn(BaseModel):
    message: str


class ToolCallIn(BaseModel):
    tool_name: str
    parameters: dict


@router.get("/agents", response_model=list[AgentOut])
def list_agents(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    agents = mari_ai.list_agents(db)
    return [
        AgentOut(
            agent_name=a.agent_name,
            display_name=a.display_name,
            description=a.description,
            tools=a.tools_json or [],
            model_name=a.model_name,
        )
        for a in agents
    ]


@router.post("/agents/seed", status_code=201)
def seed_agents(
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    created = mari_ai.seed_preset_agents(db)
    return {"seeded": len(created), "agents": [a.agent_name for a in created]}


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    agent_name: str | None = Query(None),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    convs = mari_ai.list_conversations(db, auth.tenant_id, auth.user_id, agent_name)
    return [
        ConversationOut(
            id=str(c.id),
            agent_name=c.agent_name,
            title=c.title,
            status=c.status,
            message_count=c.message_count or 0,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat() if c.updated_at else None,
        )
        for c in convs
    ]


@router.post("/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(
    body: ConversationIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    agent = mari_ai.get_agent(db, body.agent_name)
    if not agent:
        raise HTTPException(404, f"Agent '{body.agent_name}' not found or disabled")
    conv = mari_ai.create_conversation(
        db, auth.tenant_id, auth.user_id, body.agent_name, body.title, body.context
    )
    return ConversationOut(
        id=str(conv.id),
        agent_name=conv.agent_name,
        title=conv.title,
        status=conv.status,
        message_count=conv.message_count or 0,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat() if conv.updated_at else None,
    )


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
def get_messages(
    conv_id: UUID,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    conv = mari_ai.get_conversation(db, conv_id, auth.tenant_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    msgs = mari_ai.get_messages(db, conv_id)
    return [
        MessageOut(
            id=str(m.id),
            role=m.role,
            content=m.content,
            tool_calls_json=m.tool_calls_json,
            tokens_used=m.tokens_used,
            latency_ms=m.latency_ms,
            created_at=m.created_at.isoformat(),
        )
        for m in msgs
    ]


@router.post("/conversations/{conv_id}/chat")
def chat(
    conv_id: UUID,
    body: ChatIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    conv = mari_ai.get_conversation(db, conv_id, auth.tenant_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    result = mari_ai.chat(db, auth.tenant_id, auth.user_id, conv_id, body.message)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@router.post("/tools/execute")
def execute_tool(
    body: ToolCallIn,
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    result = mari_ai.execute_tool(db, auth.tenant_id, body.tool_name, body.parameters)
    return result
