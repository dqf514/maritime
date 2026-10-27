"""MariAI multi-agent framework.

Provides agent registry, tool system, and conversation management.

Chat runs a real LLM tool-use loop via :mod:`app.services.llm_client`
(Anthropic ``tool_use`` / OpenAI ``function_call`` are normalized to the same
``ToolCall`` shape). When no LLM is configured (``MARIOS_LLM_OFF=1`` / missing
credentials) or the provider raises :class:`LLMNotConfigured` / :class:`LLMError`,
chat degrades to the deterministic keyword rules in :func:`_fallback_chat`
(零网络、优雅降级).
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models_ai import AIConversation, AIMessage, AIAgentDefinition
from app.security import tenant_has_module
from app.services import llm_client
from app.services.llm_client import LLMError, LLMNotConfigured
from app.services.money import round_half_up

# Agentic loop bound: assistant may call tools this many rounds before we take
# the last text as final (prevents unbounded tool spirals).
MAX_TOOL_ROUNDS = 4
# Conversation history window sent to the model (last N messages).
HISTORY_LIMIT = 20


# ── Tool System ──


def _jsonable(obj: Any) -> Any:
    """Coerce ORM/Decimal/datetime values into JSON-friendly shapes."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    return obj


class AITool:
    """Base class for agent-callable tools."""

    name: str = ""
    description: str = ""
    parameters: dict = {}
    #: 该工具读写的业务域对应的**模块码**（P0-20）。
    #: 空 = 不需要模块许可（纯计算 / 公共数据）。
    module: str = ""

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        raise NotImplementedError

    def definition(self) -> dict:
        """Provider-agnostic tool definition (llm_client maps it per provider)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def _row_dict(row: Any, fields: tuple[str, ...]) -> dict:
    return _jsonable({f: getattr(row, f, None) for f in fields})


def _limit(kwargs: dict, default: int = 20) -> int:
    try:
        val = int(kwargs.get("limit") or default)
    except (TypeError, ValueError):
        val = default
    return max(1, min(val, 100))


# ── Calculation tools ──


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
        revenue = Decimal(str(kwargs.get("freight_revenue", 0)))
        bunker = Decimal(str(kwargs.get("bunker_cost", 0)))
        ports = Decimal(str(kwargs.get("port_costs", 0)))
        days = Decimal(str(kwargs.get("voyage_days", 1)))
        if days <= 0:
            return {"error": "voyage_days must be positive"}
        voyage_cost = bunker + ports
        # 金额口径：Decimal + 显式 ROUND_HALF_UP（内建 round() 是银行家舍入）
        tce = round_half_up((revenue - voyage_cost) / days, 2)
        return {
            "freight_revenue": float(revenue),
            "voyage_cost": float(voyage_cost),
            "net_revenue": float(revenue - voyage_cost),
            "tce_per_day": float(tce),
            "voyage_days": float(days),
        }


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
        allowed = Decimal(str(kwargs.get("allowed_days", 0)))
        actual = Decimal(str(kwargs.get("actual_days", 0)))
        dem_rate = Decimal(str(kwargs.get("demurrage_rate", 0)))
        des_rate = Decimal(str(kwargs.get("despatch_rate", 0)))
        diff = allowed - actual
        if diff < 0:
            amount = abs(diff) * dem_rate
            result_type = "demurrage"
        else:
            amount = diff * des_rate
            result_type = "despatch"
        return {
            "allowed_days": float(allowed),
            "actual_days": float(actual),
            "time_saved_days": float(round_half_up(diff, 2)),
            "result": result_type,
            "amount_usd": float(round_half_up(amount, 2)),
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

        from_p = str(kwargs.get("from_port", "")).upper()
        to_p = str(kwargs.get("to_port", "")).upper()
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
    module = "emissions"
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


# ── Operations tools ──


class ListVesselsTool(AITool):
    """List fleet vessels."""

    name = "list_vessels"
    module = "masterdata"
    description = "List vessels in the fleet with name/IMO/DWT/speed/consumption"
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Filter by vessel status (active/inactive)"},
            "name": {"type": "string", "description": "Substring filter on vessel name"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_wave1 import Vessel

        stmt = select(Vessel).where(Vessel.tenant_id == tenant_id, Vessel.deleted_at.is_(None))
        if kwargs.get("status"):
            stmt = stmt.where(Vessel.status == str(kwargs["status"]))
        if kwargs.get("name"):
            stmt = stmt.where(Vessel.name.ilike(f"%{kwargs['name']}%"))
        rows = db.scalars(stmt.order_by(Vessel.name).limit(_limit(kwargs))).all()
        fields = (
            "id", "name", "imo", "mmsi", "flag", "vessel_type", "dwt",
            "speed_knots", "consumption_sea", "consumption_port", "status",
        )
        return {"count": len(rows), "vessels": [_row_dict(r, fields) for r in rows]}


class GetVesselTool(AITool):
    """Vessel detail by name or IMO."""

    name = "get_vessel"
    module = "masterdata"
    description = "Get vessel detail (name/IMO/DWT/speed/consumption) by vessel name or IMO number"
    parameters = {
        "type": "object",
        "properties": {
            "vessel": {"type": "string", "description": "Vessel name (partial) or IMO number"},
        },
        "required": ["vessel"],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_wave1 import Vessel

        q = str(kwargs.get("vessel", "")).strip()
        if not q:
            return {"error": "vessel is required"}
        stmt = select(Vessel).where(Vessel.tenant_id == tenant_id, Vessel.deleted_at.is_(None))
        row = db.scalars(stmt.where(Vessel.imo == q)).first()
        if not row:
            row = db.scalars(stmt.where(Vessel.name.ilike(f"%{q}%"))).first()
        if not row:
            return {"error": f"Vessel not found: {q}"}
        fields = (
            "id", "name", "imo", "mmsi", "flag", "vessel_type", "dwt",
            "speed_knots", "consumption_sea", "consumption_port", "status",
        )
        return _row_dict(row, fields)


class ListVoyagesTool(AITool):
    """List voyages with optional status filter."""

    name = "list_voyages"
    module = "operations"
    description = "List voyages with optional status filter (planned/in_progress/completed)"
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Voyage status filter"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Voyage

        stmt = select(Voyage).where(Voyage.tenant_id == tenant_id)
        if kwargs.get("status"):
            stmt = stmt.where(Voyage.status == str(kwargs["status"]))
        rows = db.scalars(stmt.order_by(desc(Voyage.created_at)).limit(_limit(kwargs))).all()
        fields = (
            "id", "voyage_no", "status", "vessel_id", "charter_id",
            "cargo", "started_at", "completed_at",
        )
        return {"count": len(rows), "voyages": [_row_dict(r, fields) for r in rows]}


class GetVoyageTool(AITool):
    """Voyage detail including port calls."""

    name = "get_voyage"
    module = "operations"
    description = "Get voyage detail (status, cargo, dates) with its port calls by voyage ID or voyage number"
    parameters = {
        "type": "object",
        "properties": {
            "voyage_id": {"type": "string", "description": "Voyage UUID"},
            "voyage_no": {"type": "string", "description": "Voyage number, e.g. VOY-2407"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import PortCall, Voyage

        stmt = select(Voyage).where(Voyage.tenant_id == tenant_id)
        row = None
        if kwargs.get("voyage_id"):
            try:
                row = db.scalars(stmt.where(Voyage.id == UUID(str(kwargs["voyage_id"])))).first()
            except ValueError:
                row = None
        if not row and kwargs.get("voyage_no"):
            row = db.scalars(stmt.where(Voyage.voyage_no == str(kwargs["voyage_no"]))).first()
        if not row:
            return {"error": "Voyage not found (provide voyage_id or voyage_no)"}
        pcs = db.scalars(
            select(PortCall)
            .where(PortCall.tenant_id == tenant_id, PortCall.voyage_id == row.id)
            .order_by(PortCall.seq)
        ).all()
        out = _row_dict(
            row,
            ("id", "voyage_no", "status", "vessel_id", "charter_id", "cargo",
             "cp_date", "started_at", "completed_at", "meta"),
        )
        out["port_calls"] = [
            _row_dict(p, ("id", "seq", "purpose", "eta", "etd", "ata", "atd", "nor_at"))
            for p in pcs
        ]
        return out


class ListPortCallsTool(AITool):
    """Port calls for a voyage."""

    name = "list_port_calls"
    module = "operations"
    description = "List port calls (seq, purpose, ETA/ETD/ATA/ATD, NOR) for a voyage"
    parameters = {
        "type": "object",
        "properties": {
            "voyage_id": {"type": "string", "description": "Voyage UUID"},
            "voyage_no": {"type": "string", "description": "Voyage number (alternative to voyage_id)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import PortCall, Voyage

        voyage_id = kwargs.get("voyage_id")
        if not voyage_id and kwargs.get("voyage_no"):
            voy = db.scalars(
                select(Voyage).where(
                    Voyage.tenant_id == tenant_id,
                    Voyage.voyage_no == str(kwargs["voyage_no"]),
                )
            ).first()
            voyage_id = str(voy.id) if voy else None
        if not voyage_id:
            return {"error": "voyage_id or voyage_no is required"}
        try:
            vid = UUID(str(voyage_id))
        except ValueError:
            return {"error": f"Invalid voyage_id: {voyage_id}"}
        rows = db.scalars(
            select(PortCall)
            .where(PortCall.tenant_id == tenant_id, PortCall.voyage_id == vid)
            .order_by(PortCall.seq)
        ).all()
        fields = ("id", "voyage_id", "port_id", "seq", "purpose", "eta", "etd", "ata", "atd", "nor_at", "agent")
        return {"count": len(rows), "port_calls": [_row_dict(r, fields) for r in rows]}


class GetNoonReportsTool(AITool):
    """Noon reports for a voyage."""

    name = "get_noon_reports"
    module = "operations"
    description = "Get noon reports (position, speed, ROB, ETA deviation) for a voyage"
    parameters = {
        "type": "object",
        "properties": {
            "voyage_id": {"type": "string", "description": "Voyage UUID"},
            "voyage_no": {"type": "string", "description": "Voyage number (alternative to voyage_id)"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import NoonReport, Voyage

        voyage_id = kwargs.get("voyage_id")
        if not voyage_id and kwargs.get("voyage_no"):
            voy = db.scalars(
                select(Voyage).where(
                    Voyage.tenant_id == tenant_id,
                    Voyage.voyage_no == str(kwargs["voyage_no"]),
                )
            ).first()
            voyage_id = str(voy.id) if voy else None
        if not voyage_id:
            return {"error": "voyage_id or voyage_no is required"}
        try:
            vid = UUID(str(voyage_id))
        except ValueError:
            return {"error": f"Invalid voyage_id: {voyage_id}"}
        rows = db.scalars(
            select(NoonReport)
            .where(NoonReport.tenant_id == tenant_id, NoonReport.voyage_id == vid)
            .order_by(desc(NoonReport.report_at))
            .limit(_limit(kwargs))
        ).all()
        fields = (
            "id", "voyage_id", "report_at", "lat", "lon", "speed",
            "rob_fo", "rob_do", "eta_next", "eta_deviation_hours", "remarks",
        )
        return {"count": len(rows), "noon_reports": [_row_dict(r, fields) for r in rows]}


# ── Commercial tools ──


class ListChartersTool(AITool):
    """List charters with optional status filter."""

    name = "list_charters"
    module = "chartering"
    description = "List charters/CPs with optional status filter (draft/submitted/active/completed)"
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Charter status filter"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Charter

        stmt = select(Charter).where(Charter.tenant_id == tenant_id)
        if kwargs.get("status"):
            stmt = stmt.where(Charter.status == str(kwargs["status"]))
        rows = db.scalars(stmt.order_by(desc(Charter.created_at)).limit(_limit(kwargs))).all()
        fields = (
            "id", "charter_no", "charter_type", "status", "vessel_id",
            "laycan_from", "laycan_to", "freight_rate", "hire_per_day", "demurrage_rate",
        )
        return {"count": len(rows), "charters": [_row_dict(r, fields) for r in rows]}


class GetCharterTool(AITool):
    """Charter detail with CP terms."""

    name = "get_charter"
    module = "chartering"
    description = "Get a charter with its CP terms (freight, laytime, demurrage, commission, clauses) by charter ID or number"
    parameters = {
        "type": "object",
        "properties": {
            "charter_id": {"type": "string", "description": "Charter UUID"},
            "charter_no": {"type": "string", "description": "Charter number, e.g. CP-2407"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Charter

        stmt = select(Charter).where(Charter.tenant_id == tenant_id)
        row = None
        if kwargs.get("charter_id"):
            try:
                row = db.scalars(stmt.where(Charter.id == UUID(str(kwargs["charter_id"])))).first()
            except ValueError:
                row = None
        if not row and kwargs.get("charter_no"):
            row = db.scalars(stmt.where(Charter.charter_no == str(kwargs["charter_no"]))).first()
        if not row:
            return {"error": "Charter not found (provide charter_id or charter_no)"}
        fields = (
            "id", "charter_no", "charter_type", "status", "vessel_id", "counterparty_id",
            "laycan_from", "laycan_to", "commission_pct", "freight_terms", "clauses",
            "demurrage_rate", "despatch_rate", "laytime_terms", "cp_form",
            "freight_rate", "freight_basis", "cargo_qty", "hire_per_day", "hire_cycle_days",
            "ets_responsibility", "sanctions_blocked",
        )
        return _row_dict(row, fields)


class ListEstimatesTool(AITool):
    """List estimates with TCE results."""

    name = "list_estimates"
    module = "estimate"
    description = "List cargo/voyage estimates with their TCE results and status"
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Estimate status filter (draft/approved/...)"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Estimate

        stmt = select(Estimate).where(Estimate.tenant_id == tenant_id)
        if kwargs.get("status"):
            stmt = stmt.where(Estimate.status == str(kwargs["status"]))
        rows = db.scalars(stmt.order_by(desc(Estimate.created_at)).limit(_limit(kwargs))).all()
        out = []
        for r in rows:
            results = r.results or {}
            out.append({
                "id": str(r.id),
                "title": r.title,
                "mode": r.mode,
                "status": r.status,
                "tce_usd_day": results.get("tce_usd_day") or results.get("tce"),
                "voyage_days": results.get("voyage_days"),
                "pnl_usd": results.get("pnl_usd"),
            })
        return {"count": len(out), "estimates": out}


class ListCargoTool(AITool):
    """Cargo book."""

    name = "list_cargo"
    module = "operations"
    description = "List the cargo book (commodity, qty, laycan, load/discharge, status)"
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Cargo status filter (open/booked/nominated/fixed/completed)"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_cargo import Cargo

        stmt = select(Cargo).where(Cargo.tenant_id == tenant_id, Cargo.deleted_at.is_(None))
        if kwargs.get("status"):
            stmt = stmt.where(Cargo.status == str(kwargs["status"]))
        rows = db.scalars(stmt.order_by(desc(Cargo.created_at)).limit(_limit(kwargs))).all()
        fields = (
            "id", "cargo_no", "cargo_type", "commodity", "qty", "qty_unit",
            "laycan_from", "laycan_to", "freight_basis", "freight_rate", "status",
        )
        return {"count": len(rows), "cargoes": [_row_dict(r, fields) for r in rows]}


# ── Finance tools ──


class ListInvoicesTool(AITool):
    """List invoices with optional status filter."""

    name = "list_invoices"
    module = "finance"
    description = "List invoices with optional status filter (draft/issued/paid/overdue) including amounts"
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Invoice status filter"},
            "invoice_type": {"type": "string", "description": "Invoice type filter (freight/hire/bunker/...)"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Invoice

        stmt = select(Invoice).where(Invoice.tenant_id == tenant_id)
        if kwargs.get("status"):
            stmt = stmt.where(Invoice.status == str(kwargs["status"]))
        if kwargs.get("invoice_type"):
            stmt = stmt.where(Invoice.invoice_type == str(kwargs["invoice_type"]))
        rows = db.scalars(stmt.order_by(desc(Invoice.issued_at)).limit(_limit(kwargs))).all()
        fields = (
            "id", "invoice_no", "invoice_type", "status", "currency", "amount",
            "tax_amount", "paid_amount", "due_date", "voyage_id",
        )
        return {"count": len(rows), "invoices": [_row_dict(r, fields) for r in rows]}


class GetInvoiceTool(AITool):
    """Invoice detail with payments."""

    name = "get_invoice"
    module = "finance"
    description = "Get an invoice with its payment history by invoice ID or invoice number"
    parameters = {
        "type": "object",
        "properties": {
            "invoice_id": {"type": "string", "description": "Invoice UUID"},
            "invoice_no": {"type": "string", "description": "Invoice number"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Invoice, Payment

        stmt = select(Invoice).where(Invoice.tenant_id == tenant_id)
        row = None
        if kwargs.get("invoice_id"):
            try:
                row = db.scalars(stmt.where(Invoice.id == UUID(str(kwargs["invoice_id"])))).first()
            except ValueError:
                row = None
        if not row and kwargs.get("invoice_no"):
            row = db.scalars(stmt.where(Invoice.invoice_no == str(kwargs["invoice_no"]))).first()
        if not row:
            return {"error": "Invoice not found (provide invoice_id or invoice_no)"}
        pays = db.scalars(
            select(Payment)
            .where(Payment.tenant_id == tenant_id, Payment.invoice_id == row.id)
            .order_by(Payment.paid_at)
        ).all()
        out = _row_dict(
            row,
            ("id", "invoice_no", "invoice_type", "status", "counterparty_id", "voyage_id",
             "currency", "amount", "tax_amount", "paid_amount", "issued_at", "due_date", "gl_posted"),
        )
        out["payments"] = [
            _row_dict(p, ("id", "amount", "currency", "paid_at", "reference")) for p in pays
        ]
        return out


class ListClaimsTool(AITool):
    """List claims with time bar."""

    name = "list_claims"
    module = "claims"
    description = "List claims (demurrage/cargo/etc.) with amounts and time-bar dates"
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Claim status filter (open/negotiating/settled/closed)"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Claim

        stmt = select(Claim).where(Claim.tenant_id == tenant_id)
        if kwargs.get("status"):
            stmt = stmt.where(Claim.status == str(kwargs["status"]))
        rows = db.scalars(stmt.limit(_limit(kwargs))).all()
        today = date.today()
        items = []
        for r in rows:
            item = _row_dict(
                r,
                ("id", "claim_no", "claim_type", "status", "voyage_id", "laytime_id",
                 "amount", "currency", "time_bar", "settlement_amount"),
            )
            if r.time_bar:
                item["days_to_time_bar"] = (r.time_bar - today).days
            else:
                item["days_to_time_bar"] = None
            items.append(item)
        return {"count": len(items), "claims": items}


class GetLaytimeTool(AITool):
    """Laytime calculation detail."""

    name = "get_laytime"
    module = "laytime"
    description = "Get a laytime calculation (inputs, results: laytime used, demurrage/despatch) by laytime ID or voyage ID"
    parameters = {
        "type": "object",
        "properties": {
            "laytime_id": {"type": "string", "description": "Laytime calculation UUID"},
            "voyage_id": {"type": "string", "description": "Voyage UUID (returns its laytime calculation)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import LaytimeCalc

        stmt = select(LaytimeCalc).where(LaytimeCalc.tenant_id == tenant_id)
        row = None
        if kwargs.get("laytime_id"):
            try:
                row = db.scalars(stmt.where(LaytimeCalc.id == UUID(str(kwargs["laytime_id"])))).first()
            except ValueError:
                row = None
        if not row and kwargs.get("voyage_id"):
            try:
                row = db.scalars(
                    stmt.where(LaytimeCalc.voyage_id == UUID(str(kwargs["voyage_id"])))
                ).first()
            except ValueError:
                row = None
        if not row:
            return {"error": "Laytime calculation not found (provide laytime_id or voyage_id)"}
        return _row_dict(
            row,
            ("id", "voyage_id", "port_call_id", "status", "inputs", "results", "finalized_at"),
        )


class ListPaymentsTool(AITool):
    """Payment history."""

    name = "list_payments"
    module = "finance"
    description = "List payment history, optionally filtered by invoice"
    parameters = {
        "type": "object",
        "properties": {
            "invoice_id": {"type": "string", "description": "Filter by invoice UUID"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Payment

        stmt = select(Payment).where(Payment.tenant_id == tenant_id)
        if kwargs.get("invoice_id"):
            try:
                stmt = stmt.where(Payment.invoice_id == UUID(str(kwargs["invoice_id"])))
            except ValueError:
                return {"error": f"Invalid invoice_id: {kwargs['invoice_id']}"}
        rows = db.scalars(stmt.order_by(desc(Payment.paid_at)).limit(_limit(kwargs))).all()
        fields = ("id", "invoice_id", "amount", "currency", "paid_at", "reference", "batch_id")
        total = sum((Decimal(str(r.amount or 0)) for r in rows), Decimal("0"))
        return {
            "count": len(rows),
            "total_amount": float(round_half_up(total, 2)),
            "payments": [_row_dict(r, fields) for r in rows],
        }


# ── Risk & Market tools ──


class ListExceptionsTool(AITool):
    """Active operational exceptions."""

    name = "list_exceptions"
    description = "List active operational exceptions (ETA delay, overdue invoice, claim time bar, sanctions, DQ, ...)"
    parameters = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.services.exceptions import scan_exceptions

        out = scan_exceptions(db, tenant_id, notify=False)
        items = out.get("items", [])[: _limit(kwargs)]
        return {"summary": out.get("summary"), "count": len(items), "items": items}


class GetExposureTool(AITool):
    """Risk exposure summary."""

    name = "get_exposure"
    module = "risk"
    description = "Get the fleet hire risk exposure summary (locked hire by horizon window, sensitivity)"
    parameters = {
        "type": "object",
        "properties": {
            "horizon_days": {"type": "integer", "description": "Horizon in days (default 90)"},
            "market_hire_rate": {"type": "number", "description": "Market hire rate/day for vs-market comparison"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.services.exposure import fleet_exposure

        horizon = int(kwargs.get("horizon_days") or 90)
        market = kwargs.get("market_hire_rate")
        return fleet_exposure(
            db,
            tenant_id,
            horizon_days=horizon,
            market_hire_rate=float(market) if market is not None else None,
        )


class GetMarketQuotesTool(AITool):
    """Freight/bunker price quotes."""

    name = "get_market_quotes"
    module = "analytics"
    description = "Get latest freight index / bunker price quotes (by symbol or all)"
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Quote symbol filter, e.g. BDI, VLSFO_SG"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import MarketQuote

        stmt = select(MarketQuote).where(MarketQuote.tenant_id == tenant_id)
        if kwargs.get("symbol"):
            stmt = stmt.where(MarketQuote.symbol == str(kwargs["symbol"]).upper())
        rows = db.scalars(stmt.order_by(desc(MarketQuote.quote_date)).limit(_limit(kwargs))).all()
        fields = ("id", "symbol", "quote_date", "value", "source")
        return {"count": len(rows), "quotes": [_row_dict(r, fields) for r in rows]}


class ListTasksTool(AITool):
    """Open tasks."""

    name = "list_tasks"
    description = "List open tasks (todo/in_progress) with priority and due dates"
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "Task status filter; default open (todo + in_progress)"},
            "limit": {"type": "integer", "description": "Max rows to return (default 20)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_task import Task

        stmt = select(Task).where(Task.tenant_id == tenant_id)
        if kwargs.get("status"):
            stmt = stmt.where(Task.status == str(kwargs["status"]))
        else:
            stmt = stmt.where(Task.status.in_(["todo", "in_progress"]))
        rows = db.scalars(stmt.order_by(Task.due_at).limit(_limit(kwargs))).all()
        fields = ("id", "title", "status", "priority", "due_at", "entity_type", "entity_id", "source")
        return {"count": len(rows), "tasks": [_row_dict(r, fields) for r in rows]}


# ── Voyage tools (P&L) ──


class QueryVoyagePnLTool(AITool):
    """Query voyage P&L summary."""

    name = "query_voyage_pnl"
    module = "finance"
    description = "Get P&L summary for a voyage including revenue, costs, and profit"
    parameters = {
        "type": "object",
        "properties": {
            "voyage_id": {"type": "string", "description": "Voyage ID"},
            "voyage_no": {"type": "string", "description": "Voyage number (alternative to voyage_id)"},
        },
        "required": [],
    }

    def execute(self, db: Session, tenant_id: UUID, **kwargs) -> dict:
        from app.models_domain import Voyage
        from app.services.pnl import voyage_pnl_rows

        voyage_id = kwargs.get("voyage_id")
        voyage_no = kwargs.get("voyage_no")
        voyage = None
        if voyage_id:
            try:
                voyage = db.get(Voyage, UUID(str(voyage_id)))
            except ValueError:
                voyage = None
            if voyage and voyage.tenant_id != tenant_id:
                voyage = None
        if not voyage and voyage_no:
            voyage = db.scalars(
                select(Voyage).where(
                    Voyage.tenant_id == tenant_id,
                    Voyage.voyage_no == str(voyage_no),
                )
            ).first()
        if not voyage:
            return {"error": "Voyage not found (provide voyage_id or voyage_no)"}
        for row in voyage_pnl_rows(db, tenant_id):
            if row.get("voyage_id") == str(voyage.id):
                return {
                    "voyage_id": str(voyage.id),
                    "voyage_ref": voyage.voyage_no,
                    "status": voyage.status,
                    "revenue": row.get("actual_revenue", 0),
                    "cost": row.get("actual_cost", 0),
                    "pnl": row.get("actual_pnl", 0),
                    "estimated_pnl": row.get("estimated_pnl", 0),
                    "variance_pnl": row.get("variance_pnl", 0),
                    "expenses_by_category": row.get("lines") or {},
                    "expense_count": sum(1 for v in (row.get("lines") or {}).values() if v),
                }
        return {
            "voyage_id": str(voyage.id),
            "voyage_ref": voyage.voyage_no,
            "status": voyage.status,
            "revenue": 0,
            "cost": 0,
            "pnl": 0,
            "expenses_by_category": {},
            "expense_count": 0,
        }


TOOL_REGISTRY: dict[str, AITool] = {
    # calculations
    "calculate_tce": CalculateTCETool(),
    "calculate_laytime": CalculateLaytimeTool(),
    "search_port_distance": SearchPortDistanceTool(),
    "check_compliance": CheckComplianceTool(),
    "query_voyage_pnl": QueryVoyagePnLTool(),
    # operations
    "list_vessels": ListVesselsTool(),
    "get_vessel": GetVesselTool(),
    "list_voyages": ListVoyagesTool(),
    "get_voyage": GetVoyageTool(),
    "list_port_calls": ListPortCallsTool(),
    "get_noon_reports": GetNoonReportsTool(),
    # commercial
    "list_charters": ListChartersTool(),
    "get_charter": GetCharterTool(),
    "list_estimates": ListEstimatesTool(),
    "list_cargo": ListCargoTool(),
    # finance
    "list_invoices": ListInvoicesTool(),
    "get_invoice": GetInvoiceTool(),
    "list_claims": ListClaimsTool(),
    "get_laytime": GetLaytimeTool(),
    "list_payments": ListPaymentsTool(),
    # risk & market
    "list_exceptions": ListExceptionsTool(),
    "get_exposure": GetExposureTool(),
    "get_market_quotes": GetMarketQuotesTool(),
    "list_tasks": ListTasksTool(),
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
        "tools_json": [
            "calculate_tce", "query_voyage_pnl", "search_port_distance", "calculate_laytime",
            "list_vessels", "get_vessel", "list_voyages", "get_voyage", "list_port_calls",
            "get_noon_reports", "get_laytime", "list_exceptions",
        ],
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
        "tools_json": ["check_compliance", "search_port_distance", "get_noon_reports", "list_voyages", "get_vessel"],
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
        "tools_json": [
            "calculate_tce", "search_port_distance", "get_market_quotes",
            "list_estimates", "list_charters", "list_voyages", "get_exposure",
        ],
        "model_name": "default",
    },
    {
        "agent_name": "copilot",
        "display_name": "Mari Copilot",
        "description": "Context-aware assistant available on every screen — asks about the record you are viewing, fills routine fields, summarizes and drafts",
        "system_prompt": """You are Mari Copilot, the always-available AI assistant embedded across the MariOS shipping platform.

You appear as a popup assistant next to whatever screen the user is on — a form being filled, a comparison table, an email under review, a voyage, an invoice. You see the CONTEXT block describing the current record; use it to answer about *this* record rather than asking the user to re-explain.

You help with:
- Explaining the record on screen (what it is, why a value looks odd, what to check next)
- Filling routine form fields — return crisp values, not prose
- Summarizing (voyage status, email threads, P&L variance, laytime exposure)
- Drafting daily reports, follow-up notes and email replies
- Comparing options (routes, rates, suppliers) with specific numbers

Rules:
- Use the CONTEXT block when present. Cite real figures from it or from tools — never invent numbers.
- When asked to fill fields, return ONLY the requested values in the exact form asked (e.g. JSON), so the UI can apply them for human confirmation. Never claim you already saved anything.
- Keep answers tight and actionable. Match the user's language (Chinese↔English).
- You suggest; the human confirms and submits. Do not imply an action was already taken.""",
        "tools_json": [
            "calculate_tce", "calculate_laytime", "search_port_distance", "check_compliance",
            "query_voyage_pnl", "list_vessels", "get_vessel", "list_voyages", "get_voyage",
            "list_port_calls", "list_charters", "get_charter", "list_estimates", "list_cargo",
            "list_invoices", "get_invoice", "list_claims", "get_laytime", "list_exceptions",
            "get_exposure", "get_market_quotes", "list_tasks",
        ],
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
    # limit 必须加在 select 上：ScalarResult 没有 .limit()（旧写法直接 500）
    return list(db.scalars(stmt.limit(50)).all())


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
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> AIMessage:
    """Add a message to a conversation."""
    msg = AIMessage(
        conversation_id=conv_id,
        role=role,
        content=content,
        tool_calls_json=tool_calls,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
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
    """Execute a tool by name with given parameters.

    **模块授权前置**（P0-20）：审计发现 ``POST /api/v1/ai/tools/execute`` 只挂
    ``require_module("operations")``，而 ``TOOL_REGISTRY`` 里有
    ``list_invoices`` / ``get_invoice`` / ``list_claims`` / ``get_exposure`` …

    —— 于是**没买 finance 模块**的租户依然能通过 AI 工具读财务数据
    （模块许可被绕开）。现在每个工具声明自己需要的模块码
    （``AITool.module``），执行前先查该租户的模块许可证，不通过就拒。
    """
    tool = TOOL_REGISTRY.get(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}
    required = getattr(tool, "module", "") or ""
    if required and not tenant_has_module(db, tenant_id, required):
        return {
            "error": f"Module '{required}' is not licensed for this tenant",
            "code": "MODULE_NOT_LICENSED",
            "module": required,
        }
    try:
        start = time.time()
        result = tool.execute(db, tenant_id, **(parameters or {}))
        elapsed = int((time.time() - start) * 1000)
        if isinstance(result, dict):
            result["_latency_ms"] = elapsed
        return result
    except Exception as e:  # noqa: BLE001 — tool failures surface to the model as data
        return {"error": str(e)}


# ── Chat: LLM tool-use loop with rule fallback ──


def _agent_tool_defs(agent_def: AIAgentDefinition) -> list[dict]:
    """JSON tool definitions for the tools this agent may call."""
    defs = []
    for name in agent_def.tools_json or []:
        tool = TOOL_REGISTRY.get(name)
        if tool:
            defs.append(tool.definition())
    return defs


def _history_messages(db: Session, conv_id: UUID) -> list[dict]:
    """Normalized conversation history from AIMessage rows (oldest → newest).

    Assistant tool calls are reconstructed with their stored results so the
    provider sees a consistent tool_use / tool_result sequence.
    """
    msgs = get_messages(db, conv_id)[-HISTORY_LIMIT:]
    out: list[dict] = []
    for m in msgs:
        if m.role == "user":
            out.append({"role": "user", "content": m.content or ""})
        elif m.role == "assistant":
            entry: dict = {"role": "assistant", "content": m.content or ""}
            stored_entries = [
                t for t in (m.tool_calls_json or [])
                if isinstance(t, dict) and t.get("id")
            ]
            if stored_entries:
                entry["tool_calls"] = [
                    {
                        "id": t["id"],
                        "name": t.get("tool") or t.get("name") or "",
                        "arguments": t.get("parameters") or t.get("arguments") or {},
                    }
                    for t in stored_entries
                ]
                out.append(entry)
                for t in stored_entries:
                    out.append({
                        "role": "tool",
                        "tool_call_id": t["id"],
                        "name": t.get("tool") or t.get("name") or "",
                        "content": json.dumps(t.get("result") or {}, ensure_ascii=False, default=str),
                    })
            else:
                out.append(entry)
    return out


def chat(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    conv_id: UUID,
    user_message: str,
) -> dict:
    """Process a user message and generate an AI response.

    LLM path: system prompt (AIAgentDefinition) + conversation history
    (AIMessage) + user message → llm_client.chat_completion with tool
    definitions → tool_use loop → final text. Records tokens_used and
    latency_ms on the assistant AIMessage.

    Fallback: LLMNotConfigured / LLMError (kill switch, missing creds,
    provider error) → deterministic keyword rules (:func:`_fallback_chat`).
    """
    conv = get_conversation(db, conv_id, tenant_id)
    if not conv:
        return {"error": "Conversation not found"}

    agent_def = get_agent(db, conv.agent_name)
    if not agent_def:
        return {"error": f"Agent {conv.agent_name} not found"}

    # Save user message first — history build includes it.
    add_message(db, conv_id, "user", user_message)

    try:
        return _llm_chat(db, tenant_id, conv, conv_id, agent_def)
    except (LLMNotConfigured, LLMError):
        return _fallback_chat(db, tenant_id, conv, conv_id, agent_def, user_message)


def _llm_chat(
    db: Session,
    tenant_id: UUID,
    conv: AIConversation,
    conv_id: UUID,
    agent_def: AIAgentDefinition,
) -> dict:
    """One agentic LLM turn. Raises LLMNotConfigured / LLMError upward."""
    messages = _history_messages(db, conv_id)
    tools = _agent_tool_defs(agent_def)
    provider = llm_client.resolve_provider_config(
        db, tenant_id, agent_name=conv.agent_name
    )
    model = agent_def.model_name or "default"
    if model in ("", "default"):
        model = None  # provider default
    temperature = getattr(agent_def, "temperature", None)
    # 上下文注入：conv.context_json 存了页面/实体快照（此前从未进过 prompt）。
    system_prompt = agent_def.system_prompt or ""
    ctx_block = _context_block(conv.context_json)
    if ctx_block:
        system_prompt = f"{system_prompt}\n\n{ctx_block}"

    tool_log: list[dict] = []
    total_tokens = 0
    total_in = 0
    total_out = 0
    total_latency = 0
    text = ""
    last_resp = None

    for _ in range(MAX_TOOL_ROUNDS):
        resp = llm_client.chat_completion(
            messages,
            model=model,
            temperature=temperature,
            system=system_prompt,
            tools=tools or None,
            provider=provider,
        )
        last_resp = resp
        total_tokens += int(resp.usage.total_tokens or 0)
        # getattr：测试 double 可能只带 total_tokens / 不带 latency
        total_in += int(getattr(resp.usage, "input_tokens", 0) or 0)
        total_out += int(getattr(resp.usage, "output_tokens", 0) or 0)
        total_latency += int(getattr(resp, "latency_ms", 0) or 0)

        if not resp.tool_calls:
            text = (resp.text or "").strip()
            break

        # Feed tool calls back into the conversation and run another round.
        messages.append({
            "role": "assistant",
            "content": resp.text or "",
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments or {}}
                for tc in resp.tool_calls
            ],
        })
        for tc in resp.tool_calls:
            result = execute_tool(db, tenant_id, tc.name, tc.arguments or {})
            tool_log.append({
                "id": tc.id,
                "tool": tc.name,
                "parameters": tc.arguments or {},
                "result": result,
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.name,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

    if not text and last_resp is not None:
        text = (last_resp.text or "").strip()
    if not text:
        text = _default_response(conv.agent_name, "")

    msg = add_message(
        db,
        conv_id,
        "assistant",
        text,
        tool_calls=tool_log or None,
        tokens_used=total_tokens,
        latency_ms=total_latency,
        tokens_in=total_in or None,
        tokens_out=total_out or None,
    )
    billing = _bill_chat_usage(
        db, tenant_id, conv.user_id, total_tokens, msg.id,
        billable=bool(provider is not None and provider.billable_by_platform),
    )
    return {
        "conversation_id": str(conv_id),
        "agent": conv.agent_name,
        "response": text,
        "tool_calls": tool_log,
        "message_id": str(msg.id),
        "tokens_used": total_tokens,
        "latency_ms": total_latency,
        "source": "llm",
        "billing": billing,
    }


def _context_block(context_json: dict | None) -> str:
    """conv.context_json → 注入 system prompt 的 CONTEXT 文本块（无内容返回 ""）。"""
    if not isinstance(context_json, dict) or not context_json:
        return ""
    lines: list[str] = ["## CONTEXT (current screen / record — answer about THIS)"]
    page = context_json.get("page")
    if page:
        lines.append(f"- Screen: {page}")
    etype = context_json.get("entity_type")
    eid = context_json.get("entity_id")
    if etype:
        lines.append(f"- Record type: {etype}" + (f" (id {eid})" if eid else ""))
    summary = context_json.get("summary")
    if isinstance(summary, dict):
        for k, v in list(summary.items())[:20]:
            if v is not None and v != "":
                lines.append(f"- {k}: {v}")
    elif isinstance(summary, str) and summary.strip():
        lines.append(summary.strip()[:4000])
    raw = context_json.get("text")
    if isinstance(raw, str) and raw.strip():
        lines.append(raw.strip()[:4000])
    return "\n".join(lines) if len(lines) > 1 else ""


def _bill_chat_usage(db, tenant_id, user_id, tokens: int, message_id, *, billable: bool = True) -> dict:
    """真实 LLM 调用按 tokens 记账。计量开启且余额不足时 402 向上传播。

    ``billable=False`` 表示本次用的是租户自备 key / 主机 env 凭证 —— 不扣平台钱包。
    """
    from fastapi import HTTPException

    from app.services.saas_engine import bill_ai_tokens

    try:
        return bill_ai_tokens(
            db,
            tenant_id=tenant_id,
            tokens=tokens,
            user_id=user_id,
            ref_type="ai_message",
            ref_id=str(message_id),
            note="mari_ai.chat",
            billable=billable,
        )
    except HTTPException:
        raise  # 计费开启且余额不足 —— 明确告知调用方
    except Exception:  # noqa: BLE001 — 记账失败不阻断已生成的答复
        log.exception("mari_ai: usage billing failed (tokens=%s)", tokens)
        return {"billed": 0, "meter": "ai.tokens", "mode": "error"}


def _fallback_chat(
    db: Session,
    tenant_id: UUID,
    conv: AIConversation,
    conv_id: UUID,
    agent_def: AIAgentDefinition,
    user_message: str,
) -> dict:
    """Deterministic keyword-rule response when no LLM is available.

    Zero network — this is the degradation path for MARIOS_LLM_OFF, missing
    credentials, and provider errors.
    """
    tool_results = []
    available_tools = agent_def.tools_json or []
    response_parts = []

    if any(kw in user_message.lower() for kw in ["tce", "time charter"]):
        if "calculate_tce" in available_tools:
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
                    response_parts.append(f"Voyage {result['voyage_ref']}: P&L ${result['pnl']:,.2f} (revenue ${result['revenue']:,.2f} − cost ${result['cost']:,.2f})")
                    if result['expenses_by_category']:
                        cats = ", ".join(f"{k}: ${v:,.2f}" for k, v in result['expenses_by_category'].items() if v)
                        if cats:
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

    if response_parts:
        ai_content = "\n".join(response_parts)
    else:
        ai_content = _default_response(conv.agent_name, user_message)

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
        "source": "fallback",
    }


def _default_response(agent_name: str, message: str) -> str:
    """Generate a contextual default response when no tools match."""
    responses = {
        "voyage_advisor": "I can help with voyage optimization. Try asking about:\n- TCE calculation (provide freight revenue, bunker cost, port costs, voyage days)\n- Voyage P&L (provide a voyage ID)\n- Port distances (provide two UNLOCODEs like CNSHA JPtyO)\n- Laytime/demurrage calculations\n- Fleet/voyage listings",
        "compliance_assistant": "I can help with emissions compliance. Try asking about:\n- Fuel compliance at a position (provide lat/lon and fuel type)\n- ECA requirements\n- EU ETS zone checking",
        "market_analyst": "I can help with market analysis. Try asking about:\n- TCE calculations for route comparison\n- Port distance lookups for voyage planning\n- Market quotes (freight/bunker)",
    }
    return responses.get(agent_name, "I'm here to help. Please describe what you need assistance with.")
