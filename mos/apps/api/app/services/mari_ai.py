"""MariAI multi-agent framework.

Provides agent registry, tool system, and conversation management.
Agents use a ReAct-style loop: think → act → observe → respond.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models_ai import AIConversation, AIMessage, AIAgentDefinition


# ── Tool System ──


class AITool:
    """Base class for agent-callable tools."""

    name: str = ""
    description: str = ""
    parameters: dict = {}

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        raise NotImplementedError


class CalculateTCETool(AITool):
    """Calculate TCE (Time Charter Equivalent) for a voyage."""

    name = "calculate_tce"
    description = "Calculate Time Charter Equivalent revenue for a voyage given freight revenue, bunker costs, port costs, and voyage days"
    parameters = {
        "type": "object",
        "properties": {
            "freight_revenue": {"type": "number", "description": "Total freight revenue in USD"},
            "bunker_cost": {"type": "number", "description": "Total bunker cost in USD"},
            "port_costs": {"type": "number", "description": "Total port costs in USD"},
            "voyage_days": {"type": "number", "description": "Total voyage duration in days"},
        },
        "required": ["freight_revenue", "bunker_cost", "port_costs", "voyage_days"],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        revenue = float(kwargs.get("freight_revenue", 0))
        bunker = float(kwargs.get("bunker_cost", 0))
        ports = float(kwargs.get("port_costs", 0))
        days = float(kwargs.get("voyage_days", 1))
        if days <= 0:
            return {"error": "voyage_days must be positive"}
        voyage_cost = bunker + ports
        tce = (revenue - voyage_cost) / days
        return {
            "freight_revenue": revenue,
            "voyage_cost": voyage_cost,
            "net_revenue": revenue - voyage_cost,
            "tce_per_day": round(tce, 2),
            "voyage_days": days,
        }


class QueryVoyagePnLTool(AITool):
    """Query voyage P&L summary."""

    name = "query_voyage_pnl"
    description = "Get P&L summary for a voyage including revenue, costs, and profit"
    parameters = {
        "type": "object",
        "properties": {
            "voyage_id": {"type": "string", "description": "Voyage ID"},
        },
        "required": ["voyage_id"],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Voyage, VoyageExpense
        voyage_id = kwargs.get("voyage_id")
        voyage = db.get(Voyage, voyage_id)
        if not voyage or voyage.tenant_id != tenant_id:
            return {"error": "Voyage not found"}
        expenses = db.scalars(
            select(VoyageExpense).where(
                VoyageExpense.voyage_id == voyage.id,
                VoyageExpense.tenant_id == tenant_id,
            )
        ).all()
        total_expenses = sum(float(e.amount or 0) for e in expenses)
        by_category = {}
        for e in expenses:
            cat = e.category or "other"
            by_category[cat] = by_category.get(cat, 0) + float(e.amount or 0)
        return {
            "voyage_id": str(voyage.id),
            "voyage_ref": voyage.voyage_ref,
            "status": voyage.status,
            "total_expenses": round(total_expenses, 2),
            "expenses_by_category": {k: round(v, 2) for k, v in by_category.items()},
            "expense_count": len(expenses),
        }


class SearchPortDistanceTool(AITool):
    """Query port-to-port distance."""

    name = "search_port_distance"
    description = "Look up the distance in nautical miles between two ports by UNLOCODE"
    parameters = {
        "type": "object",
        "properties": {
            "from_port": {"type": "string", "description": "From port UNLOCODE (5 chars)"},
            "to_port": {"type": "string", "description": "To port UNLOCODE (5 chars)"},
        },
        "required": ["from_port", "to_port"],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_reference import PortDistance
        from_p = kwargs.get("from_port", "").upper()
        to_p = kwargs.get("to_port", "").upper()
        row = db.scalars(
            select(PortDistance).where(
                PortDistance.from_port_unlocode == from_p,
                PortDistance.to_port_unlocode == to_p,
            )
        ).first()
        if not row:
            row = db.scalars(
                select(PortDistance).where(
                    PortDistance.from_port_unlocode == to_p,
                    PortDistance.to_port_unlocode == from_p,
                )
            ).first()
        if not row:
            return {"error": f"No distance data for {from_p} ↔ {to_p}"}
        return {
            "from_port": row.from_port_unlocode,
            "to_port": row.to_port_unlocode,
            "distance_nm": float(row.distance_nm),
            "route_type": row.route_type,
            "canal_transit": row.canal_transit,
            "transit_days": float(row.transit_days) if row.transit_days else None,
        }


class CheckComplianceTool(AITool):
    """Check emissions compliance at a position."""

    name = "check_compliance"
    description = "Check fuel/emissions compliance at a given position (lat/lon)"
    parameters = {
        "type": "object",
        "properties": {
            "lat": {"type": "number", "description": "Latitude"},
            "lon": {"type": "number", "description": "Longitude"},
            "fuel_type": {"type": "string", "description": "Current fuel type (HFO/MGO/MDO/LNG)"},
            "sulfur_pct": {"type": "number", "description": "Fuel sulfur content %"},
        },
        "required": ["lat", "lon", "fuel_type"],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.services import fuel_zone_service as fz_svc
        lat = float(kwargs.get("lat", 0))
        lon = float(kwargs.get("lon", 0))
        fuel_type = kwargs.get("fuel_type", "MGO")
        sulfur_pct = kwargs.get("sulfur_pct")
        return fz_svc.check_fuel_compliance(db, lat, lon, fuel_type, sulfur_pct)


class CalculateLaytimeTool(AITool):
    """Quick laytime calculation."""

    name = "calculate_laytime"
    description = "Calculate laytime usage given allowed days and actual events"
    parameters = {
        "type": "object",
        "properties": {
            "allowed_days": {"type": "number", "description": "Allowed laytime days"},
            "actual_days": {"type": "number", "description": "Actual days used"},
            "demurrage_rate": {"type": "number", "description": "Demurrage rate per day (USD)"},
            "despatch_rate": {"type": "number", "description": "Despatch rate per day (USD)"},
        },
        "required": ["allowed_days", "actual_days"],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        allowed = float(kwargs.get("allowed_days", 0))
        actual = float(kwargs.get("actual_days", 0))
        dem_rate = float(kwargs.get("demurrage_rate", 0))
        des_rate = float(kwargs.get("despatch_rate", 0))
        diff = allowed - actual
        if diff < 0:
            amount = abs(diff) * dem_rate
            result_type = "demurrage"
        else:
            amount = diff * des_rate
            result_type = "despatch"
        return {
            "allowed_days": allowed,
            "actual_days": actual,
            "time_saved_days": round(diff, 2),
            "result": result_type,
            "amount_usd": round(amount, 2),
        }


TOOL_REGISTRY: dict[str, AITool] = {
    "calculate_tce": CalculateTCETool(),
    "query_voyage_pnl": QueryVoyagePnLTool(),
    "search_port_distance": SearchPortDistanceTool(),
    "check_compliance": CheckComplianceTool(),
    "calculate_laytime": CalculateLaytimeTool(),
}


# ── Agent Definitions ──

PRESET_AGENTS = [
    {
        "agent_name": "voyage_advisor",
        "display_name": "Voyage Advisor",
        "description": "Provides voyage optimization suggestions, P&L analysis, and operational recommendations",
        "system_prompt": """You are MariOS Voyage Advisor, an AI assistant for voyage optimization.

You help shipping operators with:
- Voyage P&L analysis and variance explanation
- Route optimization and port cost comparisons
- Bunker planning and fuel efficiency recommendations
- Demurrage/despatch analysis
- Weather routing suggestions

Always provide actionable recommendations with specific numbers. Use available tools to query real data.
Respond in the same language as the user's query.""",
        "tools_json": ["calculate_tce", "query_voyage_pnl", "search_port_distance", "calculate_laytime"],
        "model_name": "default",
    },
    {
        "agent_name": "compliance_assistant",
        "display_name": "Compliance Assistant",
        "description": "EU ETS, FuelEU Maritime, and emissions compliance checking",
        "system_prompt": """You are MariOS Compliance Assistant, specialized in maritime emissions regulations.

You help with:
- EU ETS compliance checking and allowance cost estimation
- FuelEU Maritime intensity calculations
- ECA fuel switching requirements
- CII rating analysis
- Emissions reporting guidance

Always cite the specific regulation and provide clear compliance status. Use the compliance check tool for position-based queries.
Respond in the same language as the user's query.""",
        "tools_json": ["check_compliance", "search_port_distance"],
        "model_name": "default",
    },
    {
        "agent_name": "market_analyst",
        "display_name": "Market Analyst",
        "description": "Freight market analysis, bunker price trends, and route economics",
        "system_prompt": """You are MariOS Market Analyst, providing market intelligence for shipping decisions.

You help with:
- Freight rate trend analysis
- Bunker price comparisons across ports
- Route economics and TCE calculations
- Market positioning recommendations
- Supply/demand indicators

Provide data-driven insights with specific numbers. Use tools for distance and cost calculations.
Respond in the same language as the user's query.""",
        "tools_json": ["calculate_tce", "search_port_distance"],
        "model_name": "default",
    },
]


# ── Service Functions ──


def seed_preset_agents(db: Session) -> list[AIAgentDefinition]:
    """Seed preset AI agent definitions."""
    created = []
    for preset in PRESET_AGENTS:
        existing = db.scalars(
            select(AIAgentDefinition).where(
                AIAgentDefinition.agent_name == preset["agent_name"]
            )
        ).first()
        if not existing:
            agent = AIAgentDefinition(**preset)
            db.add(agent)
            created.append(agent)
    db.commit()
    return created


def list_agents(db: Session) -> list[AIAgentDefinition]:
    """List all enabled AI agents."""
    return list(db.scalars(
        select(AIAgentDefinition).where(AIAgentDefinition.enabled.is_(True))
    ).all())


def get_agent(db: Session, agent_name: str) -> AIAgentDefinition | None:
    """Get agent definition by name."""
    return db.scalars(
        select(AIAgentDefinition).where(
            AIAgentDefinition.agent_name == agent_name,
            AIAgentDefinition.enabled.is_(True),
        )
    ).first()


def create_conversation(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    agent_name: str,
    title: str | None = None,
    context: dict | None = None,
) -> AIConversation:
    """Create a new AI conversation."""
    conv = AIConversation(
        tenant_id=tenant_id,
        user_id=user_id,
        agent_name=agent_name,
        title=title or f"{agent_name} conversation",
        context_json=context or {},
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def list_conversations(
    db: Session, tenant_id: UUID, user_id: UUID, agent_name: str | None = None
) -> list[AIConversation]:
    """List conversations for a user."""
    stmt = (
        select(AIConversation)
        .where(
            AIConversation.tenant_id == tenant_id,
            AIConversation.user_id == user_id,
        )
        .order_by(desc(AIConversation.updated_at))
    )
    if agent_name:
        stmt = stmt.where(AIConversation.agent_name == agent_name)
    return list(db.scalars(stmt).limit(50).all())


def get_conversation(db: Session, conv_id: UUID, tenant_id: UUID) -> AIConversation | None:
    """Get a conversation by ID."""
    return db.scalars(
        select(AIConversation).where(
            AIConversation.id == conv_id,
            AIConversation.tenant_id == tenant_id,
        )
    ).first()


def get_messages(db: Session, conv_id: UUID) -> list[AIMessage]:
    """Get all messages in a conversation, ordered by creation time."""
    return list(db.scalars(
        select(AIMessage)
        .where(AIMessage.conversation_id == conv_id)
        .order_by(AIMessage.created_at)
    ).all())


def add_message(
    db: Session,
    conv_id: UUID,
    role: str,
    content: str,
    tool_calls: list[dict] | None = None,
    tokens_used: int | None = None,
    latency_ms: int | None = None,
) -> AIMessage:
    """Add a message to a conversation."""
    msg = AIMessage(
        conversation_id=conv_id,
        role=role,
        content=content,
        tool_calls_json=tool_calls,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
    )
    db.add(msg)
    # Update conversation message count and timestamp
    conv = db.get(AIConversation, conv_id)
    if conv:
        conv.message_count = (conv.message_count or 0) + 1
        conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)
    return msg


def execute_tool(
    db: Session, tenant_id: UUID, tool_name: str, parameters: dict
) -> dict:
    """Execute a tool by name with given parameters."""
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        start = time.time()
        result = tool.execute(db, tenant_id, **parameters)
        elapsed = int((time.time() - start) * 1000)
        result["_latency_ms"] = elapsed
        return result
    except Exception as e:
        return {"error": str(e)}


def chat(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    conv_id: UUID,
    user_message: str,
) -> dict:
    """Process a user message and generate an AI response.

    Since we don't have an actual LLM backend, this implements a rule-based
    response system that demonstrates the tool-calling architecture.
    In production, this would call an LLM API (OpenAI, Anthropic, etc.).
    """
    conv = get_conversation(db, conv_id, tenant_id)
    if not conv:
        return {"error": "Conversation not found"}

    agent_def = get_agent(db, conv.agent_name)
    if not agent_def:
        return {"error": f"Agent {conv.agent_name} not found"}

    # Save user message
    add_message(db, conv_id, "user", user_message)

    # Parse intent and call tools
    tool_results = []
    available_tools = agent_def.tools_json or []

    # Simple intent matching for demo purposes
    response_parts = []

    if any(kw in user_message.lower() for kw in ["tce", "time charter"]):
        if "calculate_tce" in available_tools:
            # Try to extract numbers from the message
            import re
            numbers = re.findall(r'[\d,]+\.?\d*', user_message.replace(',', ''))
            if len(numbers) >= 4:
                result = execute_tool(db, tenant_id, "calculate_tce", {
                    "freight_revenue": float(numbers[0]),
                    "bunker_cost": float(numbers[1]),
                    "port_costs": float(numbers[2]),
                    "voyage_days": float(numbers[3]),
                })
                tool_results.append({"tool": "calculate_tce", "parameters": {"auto_extracted": True}, "result": result})
                if "error" not in result:
                    response_parts.append(f"TCE Calculation: ${result['tce_per_day']:,.2f}/day (Net revenue: ${result['net_revenue']:,.2f} over {result['voyage_days']} days)")

    if any(kw in user_message.lower() for kw in ["pnl", "profit", "loss", "expense"]):
        if "query_voyage_pnl" in available_tools:
            import re
            uuid_match = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', user_message)
            if uuid_match:
                result = execute_tool(db, tenant_id, "query_voyage_pnl", {"voyage_id": uuid_match.group()})
                tool_results.append({"tool": "query_voyage_pnl", "parameters": {"voyage_id": uuid_match.group()}, "result": result})
                if "error" not in result:
                    response_parts.append(f"Voyage {result['voyage_ref']}: {result['expense_count']} expenses totaling ${result['total_expenses']:,.2f}")
                    if result['expenses_by_category']:
                        cats = ", ".join(f"{k}: ${v:,.2f}" for k, v in result['expenses_by_category'].items())
                        response_parts.append(f"By category: {cats}")

    if any(kw in user_message.lower() for kw in ["distance", "how far", "nautical miles"]):
        if "search_port_distance" in available_tools:
            import re
            ports = re.findall(r'[A-Z]{5}', user_message.upper())
            if len(ports) >= 2:
                result = execute_tool(db, tenant_id, "search_port_distance", {
                    "from_port": ports[0],
                    "to_port": ports[1],
                })
                tool_results.append({"tool": "search_port_distance", "parameters": {"from": ports[0], "to": ports[1]}, "result": result})
                if "error" not in result:
                    response_parts.append(f"Distance {result['from_port']} → {result['to_port']}: {result['distance_nm']:,.1f} nm ({result['route_type']} route)")
                    if result.get('transit_days'):
                        response_parts.append(f"Estimated transit: {result['transit_days']} days")

    if any(kw in user_message.lower() for kw in ["compliance", "emissions", "eca", "fuel"]):
        if "check_compliance" in available_tools:
            import re
            coords = re.findall(r'-?\d+\.?\d*', user_message)
            if len(coords) >= 2:
                fuel_match = re.search(r'(HFO|MGO|MDO|LNG)', user_message, re.I)
                result = execute_tool(db, tenant_id, "check_compliance", {
                    "lat": float(coords[0]),
                    "lon": float(coords[1]),
                    "fuel_type": fuel_match.group(1).upper() if fuel_match else "MGO",
                })
                tool_results.append({"tool": "check_compliance", "parameters": {"lat": coords[0], "lon": coords[1]}, "result": result})
                if "error" not in result:
                    status = "COMPLIANT" if result.get("compliant") else "NON-COMPLIANT"
                    response_parts.append(f"Compliance status: {status}")
                    if result.get("violations"):
                        for v in result["violations"]:
                            response_parts.append(f"  ⚠ {v}")

    if any(kw in user_message.lower() for kw in ["laytime", "demurrage", "despatch"]):
        if "calculate_laytime" in available_tools:
            import re
            numbers = re.findall(r'[\d,]+\.?\d*', user_message.replace(',', ''))
            if len(numbers) >= 2:
                params = {"allowed_days": float(numbers[0]), "actual_days": float(numbers[1])}
                if len(numbers) >= 3:
                    params["demurrage_rate"] = float(numbers[2])
                if len(numbers) >= 4:
                    params["despatch_rate"] = float(numbers[3])
                result = execute_tool(db, tenant_id, "calculate_laytime", params)
                tool_results.append({"tool": "calculate_laytime", "parameters": params, "result": result})
                if "error" not in result:
                    response_parts.append(f"Laytime: {result['time_saved_days']} days {result['result']} → ${result['amount_usd']:,.2f}")

    # Build response
    if response_parts:
        ai_content = "\n".join(response_parts)
    else:
        ai_content = _default_response(conv.agent_name, user_message)

    # Save assistant message
    msg = add_message(
        db, conv_id, "assistant", ai_content,
        tool_calls=tool_results if tool_results else None,
    )

    return {
        "conversation_id": str(conv_id),
        "agent": conv.agent_name,
        "response": ai_content,
        "tool_calls": tool_results,
        "message_id": str(msg.id),
    }


def _default_response(agent_name: str, message: str) -> str:
    """Generate a contextual default response when no tools match."""
    responses = {
        "voyage_advisor": "I can help with voyage optimization. Try asking about:\n- TCE calculation (provide freight revenue, bunker cost, port costs, voyage days)\n- Voyage P&L (provide a voyage ID)\n- Port distances (provide two UNLOCODEs like CNSHA JPtyO)\n- Laytime/demurrage calculations",
        "compliance_assistant": "I can help with emissions compliance. Try asking about:\n- Fuel compliance at a position (provide lat/lon and fuel type)\n- ECA requirements\n- EU ETS zone checking",
        "market_analyst": "I can help with market analysis. Try asking about:\n- TCE calculations for route comparison\n- Port distance lookups for voyage planning",
    }
    return responses.get(agent_name, "I'm here to help. Please describe what you need assistance with.")
