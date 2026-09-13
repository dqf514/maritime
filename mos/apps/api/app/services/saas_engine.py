"""Usage wallet + workflow engine helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_saas import TenantWallet, UsageLedger, WorkflowDefinition, WorkflowInstance


FEATURE_CATALOG = [
    {"code": "estimate.create", "name": "Create estimates", "module": "estimate"},
    {"code": "estimate.convert_cp", "name": "Convert estimate to CP", "module": "chartering"},
    {"code": "charter.activate", "name": "Activate charter", "module": "chartering"},
    {"code": "voyage.operate", "name": "Operate voyages", "module": "operations"},
    {"code": "invoice.issue", "name": "Issue invoices", "module": "finance"},
    {"code": "invoice.collect", "name": "Record payments", "module": "finance"},
    {"code": "laytime.finalize", "name": "Finalize laytime", "module": "laytime"},
    {"code": "ai.invoke", "name": "Invoke AI skills", "module": "ai"},
    {"code": "admin.users", "name": "Manage users", "module": "rbac"},
    {"code": "admin.billing", "name": "Manage subscription & top-up", "module": "license"},
    {"code": "workflow.approve", "name": "Approve workflow steps", "module": "workflow"},
]


def get_or_create_wallet(db: Session, tenant_id: UUID, meter_code: str) -> TenantWallet:
    row = db.scalar(
        select(TenantWallet).where(TenantWallet.tenant_id == tenant_id, TenantWallet.meter_code == meter_code)
    )
    if not row:
        row = TenantWallet(tenant_id=tenant_id, meter_code=meter_code, balance=Decimal("0"), reserved=Decimal("0"))
        db.add(row)
        db.flush()
    return row


def credit_usage(
    db: Session,
    *,
    tenant_id: UUID,
    meter_code: str,
    quantity: Decimal,
    ref_type: str | None = None,
    ref_id: str | None = None,
    note: str | None = None,
    user_id: UUID | None = None,
) -> TenantWallet:
    wallet = get_or_create_wallet(db, tenant_id, meter_code)
    wallet.balance = Decimal(str(wallet.balance)) + Decimal(str(quantity))
    wallet.updated_at = datetime.now(timezone.utc)
    db.add(
        UsageLedger(
            tenant_id=tenant_id,
            meter_code=meter_code,
            quantity=quantity,
            direction="credit",
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
            created_by=user_id,
        )
    )
    return wallet


def consume_usage(
    db: Session,
    *,
    tenant_id: UUID,
    meter_code: str,
    quantity: Decimal,
    ref_type: str | None = None,
    ref_id: str | None = None,
    note: str | None = None,
    user_id: UUID | None = None,
    allow_negative: bool = False,
) -> TenantWallet:
    wallet = get_or_create_wallet(db, tenant_id, meter_code)
    qty = Decimal(str(quantity))
    bal = Decimal(str(wallet.balance))
    if not allow_negative and bal < qty:
        raise HTTPException(
            status_code=402,
            detail={
                "code": "QUOTA_EXCEEDED",
                "meter": meter_code,
                "balance": float(bal),
                "needed": float(qty),
                "message": "Insufficient usage balance — top up or upgrade plan",
            },
        )
    wallet.balance = bal - qty
    wallet.updated_at = datetime.now(timezone.utc)
    db.add(
        UsageLedger(
            tenant_id=tenant_id,
            meter_code=meter_code,
            quantity=qty,
            direction="consume",
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
            created_by=user_id,
        )
    )
    return wallet


def start_workflow(
    db: Session,
    *,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
    started_by: UUID | None,
) -> WorkflowInstance | None:
    definition = db.scalar(
        select(WorkflowDefinition).where(
            WorkflowDefinition.tenant_id == tenant_id,
            WorkflowDefinition.entity_type == entity_type,
            WorkflowDefinition.enabled.is_(True),
        )
    )
    if not definition:
        return None
    inst = WorkflowInstance(
        tenant_id=tenant_id,
        definition_id=definition.id,
        entity_type=entity_type,
        entity_id=entity_id,
        status="running",
        current_step=0,
        history={"events": [{"at": datetime.now(timezone.utc).isoformat(), "action": "started", "by": str(started_by)}]},
        started_by=started_by,
    )
    db.add(inst)
    db.flush()
    return inst


def advance_workflow(
    db: Session,
    *,
    instance_id: UUID,
    tenant_id: UUID,
    actor_roles: list[str],
    actor_user_id: UUID,
    decision: str,
    comment: str | None = None,
) -> WorkflowInstance:
    inst = db.get(WorkflowInstance, instance_id)
    if not inst or inst.tenant_id != tenant_id:
        raise HTTPException(404, "Workflow not found")
    if inst.status != "running":
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": f"Workflow is {inst.status}"})
    definition = db.get(WorkflowDefinition, inst.definition_id)
    assert definition
    steps = definition.steps.get("steps") if isinstance(definition.steps, dict) else definition.steps
    if not isinstance(steps, list):
        steps = []
    if inst.current_step >= len(steps):
        raise HTTPException(409, detail={"code": "INVALID_STATE", "message": "No pending step"})
    step = steps[inst.current_step]
    required_role = step.get("role_code")
    if required_role and required_role not in actor_roles and "tenant_admin" not in actor_roles:
        raise HTTPException(403, detail={"code": "ROLE_REQUIRED", "role": required_role})
    events = list((inst.history or {}).get("events") or [])
    events.append(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "action": decision,
            "step": inst.current_step,
            "by": str(actor_user_id),
            "comment": comment,
        }
    )
    if decision == "reject":
        inst.status = "rejected"
        inst.finished_at = datetime.now(timezone.utc)
    else:
        inst.current_step += 1
        if inst.current_step >= len(steps):
            inst.status = "approved"
            inst.finished_at = datetime.now(timezone.utc)
    inst.history = {"events": events}
    db.flush()
    return inst
