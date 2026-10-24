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


def _is_uuid(val: str) -> bool:
    try:
        import uuid as _uuid

        _uuid.UUID(str(val))
        return True
    except Exception:  # noqa: BLE001
        return False

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


@router.get("/attribution")
def record_attribution(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """创建人/修改人（时间）—— derived from the append-only audit ledger.

    Works for every entity that writes audit rows on create/update. Returns
    {created_by, created_by_name, created_at, updated_by, updated_by_name, updated_at}.
    Creator = the earliest create-ish action (falls back to earliest row);
    modifier = the latest action. Null fields when no audit history exists.
    """
    from app.models_audit import AuditLog
    from app.models import User

    # Durable attribution columns (authoritative) for entities that carry them.
    _ATTR_MODELS = {}
    try:
        from app.models_domain import Estimate, Invoice, Voyage

        _ATTR_MODELS = {"voyage": Voyage, "invoice": Invoice, "estimate": Estimate}
    except Exception:  # noqa: BLE001
        pass

    model = _ATTR_MODELS.get(entity_type)
    if model is not None:
        import uuid as _uuid_mod

        row = db.get(model, _uuid_mod.UUID(str(entity_id))) if _is_uuid(entity_id) else None
        if row is not None and getattr(row, "tenant_id", None) == auth.tenant_id:
            created_by = getattr(row, "created_by", None)
            updated_by = getattr(row, "updated_by", None)
            created_at = getattr(row, "created_at", None)
            updated_at = getattr(row, "updated_at", None) or created_at
            # 持久列缺失时回退到审计账本：存量行（种子数据）与只有 created_by 的实体
            # （如 Estimate）也要能显示「创建人 / 修改人」，否则归属条永远空白。
            if created_by is None or updated_by is None or created_at is None:
                ledger = db.scalars(
                    select(AuditLog)
                    .where(
                        AuditLog.tenant_id == auth.tenant_id,
                        AuditLog.entity_type == entity_type,
                        AuditLog.entity_id == str(entity_id),
                    )
                    .order_by(AuditLog.created_at.asc())
                ).all()
                if ledger:
                    def _is_create(action: str) -> bool:
                        a = (action or "").lower()
                        return a == "create" or a.endswith(".create") or a.endswith(".created")

                    first = next((r for r in ledger if _is_create(r.action)), ledger[0])
                    last = ledger[-1]
                    if created_by is None and first.actor_user_id:
                        created_by = first.actor_user_id
                    if updated_by is None and last.actor_user_id:
                        updated_by = last.actor_user_id
                    if created_at is None:
                        created_at = first.created_at
                    if updated_at is None:
                        updated_at = last.created_at
            actor_ids = {created_by, updated_by} - {None}
            users = (
                {u.id: u for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()}
                if actor_ids
                else {}
            )
            cu = users.get(created_by)
            uu = users.get(updated_by)
            return {
                "created_by": str(created_by) if created_by else None,
                "created_by_name": (cu.full_name or cu.email) if cu else None,
                "created_at": created_at.isoformat() if created_at else None,
                "updated_by": str(updated_by) if updated_by else None,
                "updated_by_name": (uu.full_name or uu.email) if uu else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
            }

    rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.tenant_id == auth.tenant_id,
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == str(entity_id),
        )
        .order_by(AuditLog.created_at.asc())
    ).all()
    if not rows:
        return {"created_by": None, "created_by_name": None, "created_at": None,
                "updated_by": None, "updated_by_name": None, "updated_at": None}

    def _is_create(action: str) -> bool:
        a = (action or "").lower()
        return a == "create" or a.endswith(".create") or a.endswith(".transition") or a.endswith(".created")

    create_row = next((r for r in rows if _is_create(r.action)), rows[0])
    update_row = rows[-1]

    actor_ids = {r.actor_user_id for r in (create_row, update_row) if r.actor_user_id}
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()}
        if actor_ids
        else {}
    )
    cu = users.get(create_row.actor_user_id)
    uu = users.get(update_row.actor_user_id)
    return {
        "created_by": str(create_row.actor_user_id) if create_row.actor_user_id else None,
        "created_by_name": (cu.full_name or cu.email) if cu else None,
        "created_at": create_row.created_at.isoformat() if create_row.created_at else None,
        "updated_by": str(update_row.actor_user_id) if update_row.actor_user_id else None,
        "updated_by_name": (uu.full_name or uu.email) if uu else None,
        "updated_at": update_row.created_at.isoformat() if update_row.created_at else None,
    }


@router.get("/port-functions")
def list_port_functions(auth: AuthContext = Depends(get_current_auth)):
    """港口挂靠功能码目录（只读元数据，任意登录用户可见）。

    返回 [{code, label_en, label_zh, tone}]；tone ∈ ok|info|muted|warn|default，
    对齐 StatusBadge 的状态色语言，甘特/排程图例直接按 tone 上色。
    """
    from app.services.port_functions import port_functions_payload

    return {"items": port_functions_payload()}
