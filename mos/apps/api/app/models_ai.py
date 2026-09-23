"""Phase 5 — MariAI multi-agent framework models.

AIConversation + AIMessage: Conversation history with agents
AIToolCall: Tool invocation log for audit/debugging
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AIConversation(Base):
    """AI conversation session with an agent."""

    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # voyage_advisor | compliance_assistant | email_intelligence | market_analyst
    title: Mapped[str | None] = mapped_column(String(256))
    context_json: Mapped[dict] = mapped_column(
        JSON, default=dict
    )  # voyage_id, charter_id, etc.
    status: Mapped[str] = mapped_column(
        String(16), default="active"
    )  # active | archived
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIMessage(Base):
    """Individual message in an AI conversation."""

    __tablename__ = "ai_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_conversations.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls_json: Mapped[dict | None] = mapped_column(
        JSON
    )  # [{tool_name, parameters, result}]
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIAgentDefinition(Base):
    """Registered AI agent with its tool set and configuration."""

    __tablename__ = "ai_agent_definitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_name: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    tools_json: Mapped[dict] = mapped_column(
        JSON, default=list
    )  # list of tool names this agent can use
    model_name: Mapped[str] = mapped_column(
        String(64), default="default"
    )  # which LLM to use
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id"), index=True
    )  # NULL = system-wide agent
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
