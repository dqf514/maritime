"""Meta endpoints — 状态机转移表 + 实体修订史（审计）+ 港口挂靠功能码目录。

- GET /api/v1/meta/transitions  全量 {entity: {status: [allowed targets]}}
  前端 DetailHeader 用它决定渲染哪些状态机动作（非法动作直接不出现，而非点击 409）。
- GET /api/v1/meta/revisions?entity_type=&entity_id=&limit=
  实体级审计流水（用户 + 动作 + 明细 + 时间），详情页 Revisions 侧栏数据源。
- GET /api/v1/meta/port-functions
  港口挂靠功能码目录（L/D/P/I/W）：{code, label_en, label_zh, tone}，
  tone 对齐全站状态色语言，供排程/甘特图例着色。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, get_current_auth
from app.services import state_machine as sm

router = APIRouter(prefix="/meta", tags=["meta"])

# 模块级懒加载：state_machine 的 20 张转移表统一收口
_TRANSITION_TABLES = {
    "charter": sm.CHARTER_TRANSITIONS,
    "voyage": sm.VOYAGE_TRANSITIONS,
    "invoice": sm.INVOICE_TRANSITIONS,
    "claim": sm.CLAIM_TRANSITIONS,
    "laytime": sm.LAYTIME_TRANSITIONS,
    "bunker": sm.BUNKER_TRANSITIONS,
    "bunker_requirement": sm.BUNKER_REQUIREMENT_TRANSITIONS,
    "offhire": sm.OFFHIRE_TRANSITIONS,
    "coa_lifting": sm.COA_LIFTING_TRANSITIONS,
    "cargo": sm.CARGO_TRANSITIONS,
    "charter_amendment": sm.CHARTER_AMENDMENT_TRANSITIONS,
    "coa_contract": sm.COA_CONTRACT_TRANSITIONS,
    "trade": sm.TRADE_TRANSITIONS,
    "time_charter": sm.TIME_CHARTER_TRANSITIONS,
    "hire_statement": sm.HIRE_STATEMENT_TRANSITIONS,
    "pda": sm.PDA_TRANSITIONS,
    "journal": sm.JOURNAL_TRANSITIONS,
    "accrual": sm.ACCRUAL_TRANSITIONS,
    "pool_period": sm.POOL_PERIOD_TRANSITIONS,
    "email_parse": sm.EMAIL_PARSE_TRANSITIONS,
    "license": sm.LICENSE_TRANSITIONS,
    "connector": sm.CONNECTOR_TRANSITIONS,
}


@router.get("/transitions")
def list_transitions(auth: AuthContext = Depends(get_current_auth)):
    """全站状态机转移表（只读元数据，任意登录用户可见）。"""
    return {
        entity: {status: sorted(targets) for status, targets in table.items()}
        for entity, table in _TRANSITION_TABLES.items()
    }


@router.get("/revisions")
def list_revisions(
    entity_type: str = Query(..., description="e.g. voyage / invoice / charter"),
    entity_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """实体修订史（tenant 内审计流水，最新在前）。无记录返回空列表。"""
    from app.models_audit import AuditLog

    stmt = (
        select(AuditLog)
        .where(
            AuditLog.tenant_id == auth.tenant_id,
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == str(entity_id),
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    rows = db.scalars(stmt).all()
    return {
        "items": [
            {
                "id": str(r.id),
                "action": r.action,
                "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
                "detail": r.detail or {},
                "ip": r.ip,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/port-functions")
def list_port_functions(auth: AuthContext = Depends(get_current_auth)):
    """港口挂靠功能码目录（只读元数据，任意登录用户可见）。

    返回 [{code, label_en, label_zh, tone}]；tone ∈ ok|info|muted|warn|default，
    对齐 StatusBadge 的状态色语言，甘特/排程图例直接按 tone 上色。
    """
    from app.services.port_functions import port_functions_payload

    return {"items": port_functions_payload()}
