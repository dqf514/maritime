"""Alert and task automation engine.

Evaluates alert rules and creates automated tasks based on conditions.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models_config import ConfigAlertRule, TaskRule
from app.services.rule_engine import evaluate_condition


def get_alert_rules(
    db: Session,
    tenant_id: UUID,
    entity_type: str | None = None,
) -> list[ConfigAlertRule]:
    """Get enabled alert rules."""
    stmt = select(ConfigAlertRule).where(
        and_(
            ConfigAlertRule.tenant_id == tenant_id,
            ConfigAlertRule.enabled.is_(True),
        )
    )
    if entity_type:
        stmt = stmt.where(ConfigAlertRule.entity_type == entity_type)
    return list(db.scalars(stmt).all())


def evaluate_alerts(
    db: Session,
    tenant_id: UUID,
    entity_type: str,
    context: dict,
) -> list[dict]:
    """Evaluate alert rules against context.

    Returns list of triggered alerts with messages.
    """
    rules = get_alert_rules(db, tenant_id, entity_type)
    triggered = []

    for rule in rules:
        condition = rule.condition_json or {}
        if evaluate_condition(condition, context):
            # Check if already triggered recently (frequency check)
            if rule.last_triggered_at and rule.frequency_days:
                next_trigger = rule.last_triggered_at + timedelta(days=rule.frequency_days)
                if datetime.now() < next_trigger:
                    continue

            triggered.append({
                "rule_id": str(rule.id),
                "rule_name": rule.rule_name,
                "message": rule.alert_message,
                "priority": rule.alert_priority,
                "entity_type": entity_type,
            })

            # Update last triggered
            rule.last_triggered_at = datetime.now()

    if triggered:
        db.commit()

    return triggered


def get_task_rules(
    db: Session,
    tenant_id: UUID,
    trigger_entity_type: str | None = None,
) -> list[TaskRule]:
    """Get enabled task rules."""
    stmt = select(TaskRule).where(
        and_(
            TaskRule.tenant_id == tenant_id,
            TaskRule.enabled.is_(True),
        )
    )
    if trigger_entity_type:
        stmt = stmt.where(TaskRule.trigger_entity_type == trigger_entity_type)
    return list(db.scalars(stmt).all())


def evaluate_task_rules(
    db: Session,
    tenant_id: UUID,
    trigger_entity_type: str,
    context: dict,
) -> list[dict]:
    """Evaluate task rules and return tasks to create.

    Returns list of task definitions to be created.
    """
    rules = get_task_rules(db, tenant_id, trigger_entity_type)
    tasks_to_create = []

    for rule in rules:
        condition = rule.trigger_condition or {}
        if evaluate_condition(condition, context):
            # Calculate due date
            due_date = None
            if rule.due_days_offset:
                due_date = datetime.now() + timedelta(days=rule.due_days_offset)

            tasks_to_create.append({
                "rule_id": str(rule.id),
                "rule_name": rule.rule_name,
                "title": rule.task_title,
                "description": rule.task_description,
                "assign_to_role": rule.assign_to_role,
                "due_date": due_date.isoformat() if due_date else None,
            })

    return tasks_to_create


def create_alert_rule(
    db: Session,
    tenant_id: UUID,
    rule_name: str,
    entity_type: str,
    condition: dict,
    alert_message: str,
    alert_priority: str = "normal",
    frequency_days: int | None = None,
    created_by: UUID | None = None,
) -> ConfigAlertRule:
    """Create a new alert rule."""
    rule = ConfigAlertRule(
        tenant_id=tenant_id,
        rule_name=rule_name,
        entity_type=entity_type,
        condition_json=condition,
        alert_message=alert_message,
        alert_priority=alert_priority,
        frequency_days=frequency_days,
        created_by=created_by,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def create_task_rule(
    db: Session,
    tenant_id: UUID,
    rule_name: str,
    trigger_entity_type: str,
    trigger_condition: dict,
    task_title: str,
    task_description: str | None = None,
    assign_to_role: str | None = None,
    due_days_offset: int | None = None,
    created_by: UUID | None = None,
) -> TaskRule:
    """Create a new task rule."""
    rule = TaskRule(
        tenant_id=tenant_id,
        rule_name=rule_name,
        trigger_entity_type=trigger_entity_type,
        trigger_condition=trigger_condition,
        task_title=task_title,
        task_description=task_description,
        assign_to_role=assign_to_role,
        due_days_offset=due_days_offset,
        created_by=created_by,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


# ── Preset alert templates ──


PRESET_ALERT_TEMPLATES = [
    {
        "name": "Overdue Invoice Reminder",
        "entity_type": "invoice",
        "condition": {"field": "invoice.status", "operator": "eq", "value": "overdue"},
        "message": "Invoice {invoice_no} is overdue",
        "priority": "high",
        "frequency_days": 7,
    },
    {
        "name": "Voyage Completion Alert",
        "entity_type": "voyage",
        "condition": {
            "field": "voyage.status",
            "operator": "eq",
            "value": "completed",
        },
        "message": "Voyage {voyage_no} completed 30 days ago, please close",
        "priority": "normal",
        "frequency_days": None,
    },
    {
        "name": "Certificate Expiry Warning (90 days)",
        "entity_type": "vessel",
        "condition": {
            "field": "certificate.days_to_expiry",
            "operator": "lte",
            "value": 90,
        },
        "message": "Certificate {cert_name} expires in {days} days",
        "priority": "normal",
        "frequency_days": 30,
    },
    {
        "name": "Low Bunker Stock Alert",
        "entity_type": "vessel",
        "condition": {
            "field": "bunker.rob_mt",
            "operator": "lt",
            "value": 500,
        },
        "message": "Vessel {vessel_name} bunker ROB below 500 MT",
        "priority": "high",
        "frequency_days": 1,
    },
    {
        "name": "Demurrage Threshold Alert",
        "entity_type": "voyage",
        "condition": {
            "field": "voyage.demurrage_amount",
            "operator": "gt",
            "value": 50000,
        },
        "message": "Voyage {voyage_no} demurrage exceeds $50,000",
        "priority": "urgent",
        "frequency_days": None,
    },
]


def seed_preset_alerts(db: Session, tenant_id: UUID, created_by: UUID | None = None):
    """Seed preset alert templates for a tenant."""
    for template in PRESET_ALERT_TEMPLATES:
        create_alert_rule(
            db,
            tenant_id=tenant_id,
            rule_name=template["name"],
            entity_type=template["entity_type"],
            condition=template["condition"],
            alert_message=template["message"],
            alert_priority=template["priority"],
            frequency_days=template["frequency_days"],
            created_by=created_by,
        )
