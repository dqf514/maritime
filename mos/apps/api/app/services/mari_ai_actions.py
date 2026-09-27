"""MariAI 业务 Agent（Phase 2 / D26）：从"问答"到"能办业务"。

三类动作全部**复用既有确定性引擎**（laytime/exceptions/主数据），LLM 只负责
叙述润色（可选，失败不影响草稿生成）——计算永远以引擎为准：

- ``laytime_statement``：laytime 计算书草稿（compute_laytime_statement）；
- ``voyage_instruction``：航次指令草稿（租约/航次/船舶主数据拼装）；
- ``exception_explanation``：异常解释 + 建议动作（exceptions 引擎数据）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

class Narrative(BaseModel):
    narrative: str


def _narrative(prompt: str) -> str | None:
    """LLM 叙述（可选）：失败/无凭证返回 None，草稿照出。"""
    try:
        from app.services.llm_extract import call_claude, llm_available

        if not llm_available():
            return None
        parsed = call_claude(Narrative, "Business draft narrative", prompt)
        return parsed.narrative if parsed else None
    except Exception:  # noqa: BLE001
        return None


def laytime_statement_draft(db, tenant_id, laytime_id) -> dict[str, Any]:
    """laytime 计算书草稿：引擎现算 +（可选）叙述。"""
    from uuid import UUID

    from app.services.laytime_engine import compute_laytime_statement
    from app.services.tenant_guard import scoped_get
    from app.models_domain import LaytimeCalc

    row = scoped_get(db, LaytimeCalc, UUID(str(laytime_id)), tenant_id)
    if row is None:
        return {"error": "not_found"}
    statement = compute_laytime_statement(row.inputs or {})
    return {
        "action": "laytime_statement",
        "laytime_id": str(row.id),
        "statement": statement,
        "narrative": _narrative(
            "Draft a one-paragraph cover note for this laytime statement to a counterparty: "
            f"allowed {statement.get('allowed_hours')}h, used {statement.get('used_hours')}h, "
            f"result {statement.get('result_type')} amount {statement.get('amount')} {statement.get('currency')}."
        ),
    }


def voyage_instruction_draft(db, tenant_id, voyage_id) -> dict[str, Any]:
    """航次指令草稿：租约条款 + 航次/船舶主数据拼装（确定性）。"""
    from uuid import UUID

    from app.models_domain import Charter, Voyage
    from app.models_wave1 import Vessel
    from app.services.tenant_guard import scoped_get

    voy = scoped_get(db, Voyage, UUID(str(voyage_id)), tenant_id)
    if voy is None:
        return {"error": "not_found"}
    charter = scoped_get(db, Charter, voy.charter_id, tenant_id) if voy.charter_id else None
    vessel = scoped_get(db, Vessel, voy.vessel_id, tenant_id) if getattr(voy, "vessel_id", None) else None
    fields = {
        "voyage_no": voy.voyage_no,
        "vessel": vessel.name if vessel else None,
        "cargo": (charter.freight_terms or {}).get("cargo") if charter else None,
        "cargo_qty": float(charter.cargo_qty) if charter and charter.cargo_qty else None,
        "laycan_from": charter.laycan_from.isoformat() if charter and charter.laycan_from else None,
        "laycan_to": charter.laycan_to.isoformat() if charter and charter.laycan_to else None,
        "demurrage_rate": float(charter.demurrage_rate) if charter and charter.demurrage_rate else None,
        "laytime_terms": charter.laytime_terms if charter else None,
        "cp_form": charter.cp_form if charter else None,
        "ets_responsibility": charter.ets_responsibility if charter else None,
    }
    instructions = [
        "Report ETA daily at 1200 LT.",
        "Tender NOR on arrival in accordance with CP terms.",
        "Follow charterer's berthing instructions; confirm holds/gears readiness before loading.",
    ]
    return {
        "action": "voyage_instruction",
        "voyage_id": str(voy.id),
        "fields": fields,
        "instructions": instructions,
        "narrative": _narrative(
            "Draft a voyage instruction email to the master for: "
            + ", ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
        ),
    }


def exception_explanation(db, tenant_id, entity_id: str | None = None, kind: str | None = None) -> dict[str, Any]:
    """异常解释：exceptions 引擎扫描 + 建议动作映射 +（可选）叙述。"""
    from app.services.exceptions import scan_exceptions

    scan = scan_exceptions(db, tenant_id, notify=False)
    items = scan.get("items", [])
    if entity_id:
        items = [i for i in items if str(i.get("entity_id")) == entity_id]
    if kind:
        items = [i for i in items if i.get("kind") == kind]
    if not items:
        return {"action": "exception_explanation", "items": [], "narrative": None}

    suggestion = {
        "claim_timebar": "立即整理 laytime statement 并在时效内递交索赔",
        "invoice_overdue": "联系对手方催收，超信用限额则暂停新单",
        "eta_delay": "核实午报与气象，必要时通知租家重排 laycan",
        "demurrage_open": "核对 SOF 事件，推进滞期费计算与确认",
        "cert_expired": "安排检验换证，船舶相关作业暂停直至恢复",
        "pnl_deterioration": "复盘估算与实际差异，标记异常成本",
        "off_hire_open": "确认 off-hire 事由与证据，纳入 hire statement",
        "tc_redelivery_due": "准备还船检验与存油确认",
        "sanctions_blocked": "停止交易，启动合规复核",
        "dq_issue": "修正主数据/单据数据质量问题",
    }
    out_items = []
    for it in items[:5]:
        out_items.append({**it, "suggested_action": suggestion.get(it.get("kind"), "人工复核")})
    return {
        "action": "exception_explanation",
        "items": out_items,
        "narrative": _narrative(
            "Explain these operational exceptions to a fleet manager and suggest priorities: "
            + "; ".join(f"[{i.get('severity')}] {i.get('title')}: {i.get('detail')}" for i in out_items)
        ),
    }
