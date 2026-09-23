"""Configuration management API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.security import AuthContext, require_module
from app.db import get_db
from app.models_config import ConfigFlag, BusinessRuleDefinition, ConfigAlertRule, TaskRule, UdfDefinition, UdfValue
from app.services.config_service import ConfigService
from app.services import rule_engine
from app.services import alert_engine

router = APIRouter(prefix="/api/v1/config", tags=["config"])


class ConfigFlagOut(BaseModel):
    id: str
    flag_key: str
    flag_value: str
    value_type: str
    category: str
    scope_key: str
    description: str | None
    tenant_id: str | None
    user_id: str | None


class ConfigFlagIn(BaseModel):
    key: str
    value: str
    value_type: str = "string"
    category: str = "general"
    description: str | None = None


@router.get("/flags", response_model=list[ConfigFlagOut])
def list_config_flags(
    category: str | None = Query(None),
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """List configuration flags for current tenant + platform defaults."""
    flags = ConfigService.list_flags(db, auth.tenant_id, category)
    return [
        ConfigFlagOut(
            id=str(f.id),
            flag_key=f.flag_key,
            flag_value=f.flag_value,
            value_type=f.value_type,
            category=f.category,
            scope_key=f.scope_key,
            description=f.description,
            tenant_id=str(f.tenant_id) if f.tenant_id else None,
            user_id=str(f.user_id) if f.user_id else None,
        )
        for f in flags
    ]


@router.get("/flags/{key}")
def get_config_flag(
    key: str,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Get configuration value with scope fallback."""
    value = ConfigService.get(db, key, auth.tenant_id, auth.user_id)
    return {"key": key, "value": value}


@router.post("/flags", response_model=ConfigFlagOut, status_code=201)
def set_config_flag(
    body: ConfigFlagIn,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Set configuration flag at tenant scope."""
    # Parse value according to type
    if body.value_type == "bool":
        parsed = body.value.lower() in ("true", "1", "yes", "on")
    elif body.value_type == "number":
        parsed = float(body.value)
    elif body.value_type == "json":
        import json
        parsed = json.loads(body.value)
    else:
        parsed = body.value

    flag = ConfigService.set(
        db,
        key=body.key,
        value=parsed,
        tenant_id=auth.tenant_id,
        category=body.category,
        description=body.description,
        updated_by=auth.user_id,
    )
    return ConfigFlagOut(
        id=str(flag.id),
        flag_key=flag.flag_key,
        flag_value=flag.flag_value,
        value_type=flag.value_type,
        category=flag.category,
        scope_key=flag.scope_key,
        description=flag.description,
        tenant_id=str(flag.tenant_id) if flag.tenant_id else None,
        user_id=str(flag.user_id) if flag.user_id else None,
    )


@router.delete("/flags/{flag_id}")
def delete_config_flag(
    flag_id: UUID,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Delete configuration flag."""
    flag = db.get(ConfigFlag, flag_id)
    if not flag:
        raise HTTPException(404, "Flag not found")
    if flag.tenant_id != auth.tenant_id and flag.scope_key != "platform":
        raise HTTPException(403, "Cannot delete platform flags")
    db.delete(flag)
    db.commit()
    return {"ok": True}


# ── Common configuration keys ──


@router.get("/presets")
def list_config_presets():
    """List common configuration keys and their descriptions."""
    return {
        "financials": [
            {"key": "CFG_INVOICE_MIRROR", "description": "Enable mirror invoice generation", "type": "bool"},
            {"key": "CFG_USE_NATURAL_ROUNDING", "description": "Use natural rounding instead of banker's rounding", "type": "bool"},
            {"key": "CFG_COMMISSION_BASIS", "description": "Commission calculation basis (net/gross)", "type": "string"},
            {"key": "CFG_DEMURRAGE_INCLUDE_IN_PNL", "description": "Include demurrage in P&L calculation", "type": "bool"},
        ],
        "operations": [
            {"key": "CFG_BILL_BY", "description": "Default billing basis (cp_qty/bl_qty)", "type": "string"},
            {"key": "CFG_LAYTIME_TERMS", "description": "Default laytime terms (SHINC/SHEX/SSHEX)", "type": "string"},
            {"key": "CFG_CHARTERER_VIEW", "description": "Enable charterer view mode", "type": "bool"},
        ],
        "bunkering": [
            {"key": "CFG_TCO_BUNKER_ADJ", "description": "TCO bunker adjustment factor", "type": "number"},
        ],
        "emissions": [
            {"key": "CFG_EU_ETS_ENABLED", "description": "Enable EU ETS calculation", "type": "bool"},
            {"key": "CFG_FUELEU_ENABLED", "description": "Enable FuelEU Maritime calculation", "type": "bool"},
        ],
    }


# ── Business Rules ──


class BusinessRuleOut(BaseModel):
    id: str
    rule_name: str
    rule_type: str
    entity_type: str
    priority: int
    condition_json: dict
    action_json: dict
    enabled: bool
    description: str | None


class BusinessRuleIn(BaseModel):
    rule_name: str
    rule_type: str
    entity_type: str
    condition: dict
    action: dict
    priority: int = 100
    description: str | None = None


@router.get("/rules", response_model=list[BusinessRuleOut])
def list_business_rules(
    rule_type: str | None = Query(None),
    entity_type: str | None = Query(None),
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """List business rules for current tenant."""
    from sqlalchemy import select, and_

    stmt = select(BusinessRuleDefinition).where(
        BusinessRuleDefinition.tenant_id == auth.tenant_id
    )
    if rule_type:
        stmt = stmt.where(BusinessRuleDefinition.rule_type == rule_type)
    if entity_type:
        stmt = stmt.where(BusinessRuleDefinition.entity_type == entity_type)
    stmt = stmt.order_by(BusinessRuleDefinition.priority)

    rules = db.scalars(stmt).all()
    return [
        BusinessRuleOut(
            id=str(r.id),
            rule_name=r.rule_name,
            rule_type=r.rule_type,
            entity_type=r.entity_type,
            priority=r.priority,
            condition_json=r.condition_json or {},
            action_json=r.action_json or {},
            enabled=r.enabled,
            description=r.description,
        )
        for r in rules
    ]


@router.post("/rules", response_model=BusinessRuleOut, status_code=201)
def create_business_rule(
    body: BusinessRuleIn,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Create a new business rule."""
    rule = rule_engine.create_rule(
        db,
        tenant_id=auth.tenant_id,
        rule_name=body.rule_name,
        rule_type=body.rule_type,
        entity_type=body.entity_type,
        condition=body.condition,
        action=body.action,
        priority=body.priority,
        description=body.description,
        created_by=auth.user_id,
    )
    return BusinessRuleOut(
        id=str(rule.id),
        rule_name=rule.rule_name,
        rule_type=rule.rule_type,
        entity_type=rule.entity_type,
        priority=rule.priority,
        condition_json=rule.condition_json or {},
        action_json=rule.action_json or {},
        enabled=rule.enabled,
        description=rule.description,
    )


@router.post("/rules/evaluate")
def evaluate_business_rules(
    rule_type: str = Query(...),
    entity_type: str = Query(...),
    context: dict = {},
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Evaluate business rules against context."""
    return rule_engine.evaluate_rules(db, auth.tenant_id, rule_type, entity_type, context)


# ── Alert Rules ──


class AlertRuleOut(BaseModel):
    id: str
    rule_name: str
    entity_type: str
    condition_json: dict
    alert_message: str
    alert_priority: str
    frequency_days: int | None
    enabled: bool
    last_triggered_at: str | None


class AlertRuleIn(BaseModel):
    rule_name: str
    entity_type: str
    condition: dict
    alert_message: str
    alert_priority: str = "normal"
    frequency_days: int | None = None


@router.get("/alert-rules", response_model=list[AlertRuleOut])
def list_alert_rules(
    entity_type: str | None = Query(None),
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """List alert rules for current tenant."""
    rules = alert_engine.get_alert_rules(db, auth.tenant_id, entity_type)
    return [
        AlertRuleOut(
            id=str(r.id),
            rule_name=r.rule_name,
            entity_type=r.entity_type,
            condition_json=r.condition_json or {},
            alert_message=r.alert_message,
            alert_priority=r.alert_priority,
            frequency_days=r.frequency_days,
            enabled=r.enabled,
            last_triggered_at=r.last_triggered_at.isoformat() if r.last_triggered_at else None,
        )
        for r in rules
    ]


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=201)
def create_alert_rule(
    body: AlertRuleIn,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Create a new alert rule."""
    rule = alert_engine.create_alert_rule(
        db,
        tenant_id=auth.tenant_id,
        rule_name=body.rule_name,
        entity_type=body.entity_type,
        condition=body.condition,
        alert_message=body.alert_message,
        alert_priority=body.alert_priority,
        frequency_days=body.frequency_days,
        created_by=auth.user_id,
    )
    return AlertRuleOut(
        id=str(rule.id),
        rule_name=rule.rule_name,
        entity_type=rule.entity_type,
        condition_json=rule.condition_json or {},
        alert_message=rule.alert_message,
        alert_priority=rule.alert_priority,
        frequency_days=rule.frequency_days,
        enabled=rule.enabled,
        last_triggered_at=rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
    )


@router.post("/alert-rules/evaluate")
def evaluate_alert_rules(
    entity_type: str = Query(...),
    context: dict = {},
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Evaluate alert rules and return triggered alerts."""
    return alert_engine.evaluate_alerts(db, auth.tenant_id, entity_type, context)


@router.post("/alert-rules/seed-presets", status_code=201)
def seed_preset_alert_rules(
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Seed preset alert templates for current tenant."""
    alert_engine.seed_preset_alerts(db, auth.tenant_id, auth.user_id)
    return {"ok": True, "message": "Preset alert rules seeded"}


# ── Task Rules ──


class TaskRuleOut(BaseModel):
    id: str
    rule_name: str
    trigger_entity_type: str
    trigger_condition: dict
    task_title: str
    task_description: str | None
    assign_to_role: str | None
    due_days_offset: int | None
    enabled: bool


class TaskRuleIn(BaseModel):
    rule_name: str
    trigger_entity_type: str
    trigger_condition: dict
    task_title: str
    task_description: str | None = None
    assign_to_role: str | None = None
    due_days_offset: int | None = None


@router.get("/task-rules", response_model=list[TaskRuleOut])
def list_task_rules(
    trigger_entity_type: str | None = Query(None),
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """List task automation rules for current tenant."""
    rules = alert_engine.get_task_rules(db, auth.tenant_id, trigger_entity_type)
    return [
        TaskRuleOut(
            id=str(r.id),
            rule_name=r.rule_name,
            trigger_entity_type=r.trigger_entity_type,
            trigger_condition=r.trigger_condition or {},
            task_title=r.task_title,
            task_description=r.task_description,
            assign_to_role=r.assign_to_role,
            due_days_offset=r.due_days_offset,
            enabled=r.enabled,
        )
        for r in rules
    ]


@router.post("/task-rules", response_model=TaskRuleOut, status_code=201)
def create_task_rule(
    body: TaskRuleIn,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Create a new task automation rule."""
    rule = alert_engine.create_task_rule(
        db,
        tenant_id=auth.tenant_id,
        rule_name=body.rule_name,
        trigger_entity_type=body.trigger_entity_type,
        trigger_condition=body.trigger_condition,
        task_title=body.task_title,
        task_description=body.task_description,
        assign_to_role=body.assign_to_role,
        due_days_offset=body.due_days_offset,
        created_by=auth.user_id,
    )
    return TaskRuleOut(
        id=str(rule.id),
        rule_name=rule.rule_name,
        trigger_entity_type=rule.trigger_entity_type,
        trigger_condition=rule.trigger_condition or {},
        task_title=rule.task_title,
        task_description=rule.task_description,
        assign_to_role=rule.assign_to_role,
        due_days_offset=rule.due_days_offset,
        enabled=rule.enabled,
    )


@router.post("/task-rules/evaluate")
def evaluate_task_rules(
    trigger_entity_type: str = Query(...),
    context: dict = {},
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Evaluate task rules and return tasks to create."""
    return alert_engine.evaluate_task_rules(db, auth.tenant_id, trigger_entity_type, context)


# ── User-Defined Fields (UDF) ──


class UdfDefinitionOut(BaseModel):
    id: str
    entity_type: str
    field_key: str
    field_label: str
    field_type: str
    options: dict | None
    required: bool
    default_value: str | None
    sort_order: int


class UdfDefinitionIn(BaseModel):
    entity_type: str
    field_key: str
    field_label: str
    field_type: str = "string"
    options: dict | None = None
    required: bool = False
    default_value: str | None = None
    sort_order: int = 0


class UdfValueIn(BaseModel):
    field_value: str | None = None


@router.get("/udf/{entity_type}", response_model=list[UdfDefinitionOut])
def list_udf_definitions(
    entity_type: str,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """List UDF definitions for an entity type."""
    from sqlalchemy import select

    stmt = (
        select(UdfDefinition)
        .where(
            UdfDefinition.tenant_id == auth.tenant_id,
            UdfDefinition.entity_type == entity_type,
        )
        .order_by(UdfDefinition.sort_order)
    )
    defs = db.scalars(stmt).all()
    return [
        UdfDefinitionOut(
            id=str(d.id),
            entity_type=d.entity_type,
            field_key=d.field_key,
            field_label=d.field_label,
            field_type=d.field_type,
            options=d.options_json,
            required=d.required,
            default_value=d.default_value,
            sort_order=d.sort_order,
        )
        for d in defs
    ]


@router.post("/udf/{entity_type}", response_model=UdfDefinitionOut, status_code=201)
def create_udf_definition(
    entity_type: str,
    body: UdfDefinitionIn,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Create a new UDF definition."""
    defn = UdfDefinition(
        tenant_id=auth.tenant_id,
        entity_type=entity_type,
        field_key=body.field_key,
        field_label=body.field_label,
        field_type=body.field_type,
        options_json=body.options,
        required=body.required,
        default_value=body.default_value,
        sort_order=body.sort_order,
        created_by=auth.user_id,
    )
    db.add(defn)
    db.commit()
    db.refresh(defn)
    return UdfDefinitionOut(
        id=str(defn.id),
        entity_type=defn.entity_type,
        field_key=defn.field_key,
        field_label=defn.field_label,
        field_type=defn.field_type,
        options=defn.options_json,
        required=defn.required,
        default_value=defn.default_value,
        sort_order=defn.sort_order,
    )


@router.get("/udf/{entity_type}/{entity_id}")
def get_udf_values(
    entity_type: str,
    entity_id: UUID,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Get UDF values for a specific entity."""
    from sqlalchemy import select

    stmt = select(UdfDefinition).where(
        UdfDefinition.tenant_id == auth.tenant_id,
        UdfDefinition.entity_type == entity_type,
    )
    defs = db.scalars(stmt).all()

    result = {}
    for defn in defs:
        val = db.scalars(
            select(UdfValue).where(
                UdfValue.definition_id == defn.id,
                UdfValue.entity_id == entity_id,
            )
        ).first()
        result[defn.field_key] = {
            "label": defn.field_label,
            "type": defn.field_type,
            "value": val.field_value if val else defn.default_value,
        }
    return result


@router.put("/udf/{entity_type}/{entity_id}/{field_key}")
def set_udf_value(
    entity_type: str,
    entity_id: UUID,
    field_key: str,
    body: UdfValueIn,
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    """Set a UDF value for a specific entity."""
    from sqlalchemy import select

    defn = db.scalars(
        select(UdfDefinition).where(
            UdfDefinition.tenant_id == auth.tenant_id,
            UdfDefinition.entity_type == entity_type,
            UdfDefinition.field_key == field_key,
        )
    ).first()
    if not defn:
        raise HTTPException(404, f"UDF definition '{field_key}' not found")

    val = db.scalars(
        select(UdfValue).where(
            UdfValue.definition_id == defn.id,
            UdfValue.entity_id == entity_id,
        )
    ).first()

    if val:
        val.field_value = body.field_value
        val.updated_by = auth.user_id
    else:
        val = UdfValue(
            definition_id=defn.id,
            entity_id=entity_id,
            field_value=body.field_value,
            updated_by=auth.user_id,
        )
        db.add(val)

    db.commit()
    return {"ok": True}
