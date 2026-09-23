"""Business rule engine for automated decision-making.

Supports rule types:
- pnl_mapping: Expense → GL account mapping
- commission: Commission calculation rules
- approval: Approval hierarchy rules
- validation: Data validation rules
- notification: Notification trigger rules
- pricing: Pricing strategy rules
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models_config import BusinessRuleDefinition


def evaluate_condition(condition: dict, context: dict) -> bool:
    """Evaluate a rule condition against context.

    Condition format:
    {
        "field": "voyage.cargo_qty",
        "operator": "gt",
        "value": 50000
    }

    Operators: eq, ne, gt, gte, lt, lte, in, contains, starts_with
    """
    field = condition.get("field")
    operator = condition.get("operator", "eq")
    expected = condition.get("value")

    # Resolve field path (e.g., "voyage.cargo_qty")
    actual = _resolve_field(context, field)
    if actual is None:
        return False

    # Evaluate operator
    if operator == "eq":
        return actual == expected
    elif operator == "ne":
        return actual != expected
    elif operator == "gt":
        return actual > expected
    elif operator == "gte":
        return actual >= expected
    elif operator == "lt":
        return actual < expected
    elif operator == "lte":
        return actual <= expected
    elif operator == "in":
        return actual in expected
    elif operator == "contains":
        return expected in actual
    elif operator == "starts_with":
        return str(actual).startswith(str(expected))
    else:
        return False


def _resolve_field(context: dict, field_path: str) -> Any:
    """Resolve nested field path (e.g., 'voyage.cargo_qty')."""
    parts = field_path.split(".")
    value = context
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def get_applicable_rules(
    db: Session,
    tenant_id: UUID,
    rule_type: str,
    entity_type: str,
) -> list[BusinessRuleDefinition]:
    """Get enabled rules matching type and entity.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        rule_type: Rule type (pnl_mapping, commission, etc.)
        entity_type: Entity type (voyage, charter, invoice, etc.)

    Returns:
        List of matching rules ordered by priority
    """
    return list(
        db.scalars(
            select(BusinessRuleDefinition).where(
                and_(
                    BusinessRuleDefinition.tenant_id == tenant_id,
                    BusinessRuleDefinition.rule_type == rule_type,
                    BusinessRuleDefinition.entity_type == entity_type,
                    BusinessRuleDefinition.enabled.is_(True),
                )
            ).order_by(BusinessRuleDefinition.priority)
        ).all()
    )


def evaluate_rules(
    db: Session,
    tenant_id: UUID,
    rule_type: str,
    entity_type: str,
    context: dict,
) -> list[dict]:
    """Evaluate all applicable rules against context.

    Args:
        db: Database session
        tenant_id: Tenant UUID
        rule_type: Rule type
        entity_type: Entity type
        context: Context dict with entity data

    Returns:
        List of matching rule actions
    """
    rules = get_applicable_rules(db, tenant_id, rule_type, entity_type)
    matched = []

    for rule in rules:
        conditions = rule.condition_json or {}
        # Support single condition or list of conditions (AND logic)
        if isinstance(conditions, dict):
            conditions = [conditions]

        all_match = all(evaluate_condition(cond, context) for cond in conditions)
        if all_match:
            matched.append({
                "rule_id": str(rule.id),
                "rule_name": rule.rule_name,
                "action": rule.action_json,
            })

    return matched


# ── Rule type-specific helpers ──


def get_pnl_mapping(
    db: Session,
    tenant_id: UUID,
    expense_type: str,
) -> dict | None:
    """Get GL account mapping for expense type.

    Returns action_json with gl_account_id, cost_center, etc.
    """
    rules = get_applicable_rules(db, tenant_id, "pnl_mapping", "voyage")
    for rule in rules:
        cond = rule.condition_json or {}
        if cond.get("field") == "expense_type" and cond.get("value") == expense_type:
            return rule.action_json
    return None


def get_commission_rule(
    db: Session,
    tenant_id: UUID,
    charter_type: str,
) -> dict | None:
    """Get commission calculation rule for charter type."""
    rules = get_applicable_rules(db, tenant_id, "commission", "charter")
    for rule in rules:
        cond = rule.condition_json or {}
        if cond.get("field") == "charter_type" and cond.get("value") == charter_type:
            return rule.action_json
    return None


def get_approval_rule(
    db: Session,
    tenant_id: UUID,
    amount: Decimal,
) -> dict | None:
    """Get approval rule based on amount threshold."""
    rules = get_applicable_rules(db, tenant_id, "approval", "invoice")
    context = {"amount": float(amount)}
    for rule in rules:
        if evaluate_condition(rule.condition_json or {}, context):
            return rule.action_json
    return None


def validate_entity(
    db: Session,
    tenant_id: UUID,
    entity_type: str,
    context: dict,
) -> list[str]:
    """Validate entity against validation rules.

    Returns list of error messages (empty if valid).
    """
    rules = get_applicable_rules(db, tenant_id, "validation", entity_type)
    errors = []

    for rule in rules:
        cond = rule.condition_json or {}
        # Validation rules: if condition matches, it's an error
        if evaluate_condition(cond, context):
            action = rule.action_json or {}
            errors.append(action.get("message", f"Validation failed: {rule.rule_name}"))

    return errors


def create_rule(
    db: Session,
    tenant_id: UUID,
    rule_name: str,
    rule_type: str,
    entity_type: str,
    condition: dict,
    action: dict,
    priority: int = 100,
    description: str | None = None,
    created_by: UUID | None = None,
) -> BusinessRuleDefinition:
    """Create a new business rule."""
    rule = BusinessRuleDefinition(
        tenant_id=tenant_id,
        rule_name=rule_name,
        rule_type=rule_type,
        entity_type=entity_type,
        condition_json=condition,
        action_json=action,
        priority=priority,
        description=description,
        created_by=created_by,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
