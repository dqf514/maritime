"""Phase 3 — Configurable Intelligence Layer models.

ConfigFlag: System/tenant/user configuration flags with caching
BusinessRuleDefinition: Enhanced business rules engine
AlertRule + TaskRule: Alert and task automation
UdfDefinition + UdfValue: User-defined fields
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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ConfigFlag(Base):
    """System configuration flag with multi-scope support.

    Scope hierarchy: platform < tenant < user (user overrides tenant overrides platform)
    """

    __tablename__ = "config_flags"
    __table_args__ = (
        UniqueConstraint("scope_key", "flag_key", name="uq_config_flag_scope_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    scope_key: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # "platform" | tenant UUID | user UUID
    flag_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    flag_value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="string"
    )  # bool | number | string | json
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, default="general", index=True
    )  # financials | operations | bunkering | emissions | general
    description: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BusinessRuleDefinition(Base):
    """Enhanced business rule definition.

    Rule types:
    - pnl_mapping: Expense → GL account mapping
    - commission: Commission calculation rules
    - approval: Approval hierarchy rules
    - validation: Data validation rules
    - notification: Notification trigger rules
    - pricing: Pricing strategy rules
    """

    __tablename__ = "business_rule_definitions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )  # pnl_mapping | commission | approval | validation | notification | pricing
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # voyage | charter | invoice | vessel | estimate
    priority: Mapped[int] = mapped_column(Integer, default=100)
    condition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    action_json: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ConfigAlertRule(Base):
    """Alert/reminder rule definition.

    Triggers automated alerts based on conditions.
    """

    __tablename__ = "config_alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # invoice | voyage | vessel | certificate
    condition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    alert_message: Mapped[str] = mapped_column(Text, nullable=False)
    alert_priority: Mapped[str] = mapped_column(
        String(16), default="normal"
    )  # low | normal | high | urgent
    frequency_days: Mapped[int | None] = mapped_column(Integer)  # repeat every N days
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TaskRule(Base):
    """Task automation rule.

    Automatically creates tasks based on conditions.
    """

    __tablename__ = "task_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger_entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # voyage | charter | invoice
    trigger_condition: Mapped[dict] = mapped_column(JSON, default=dict)
    task_title: Mapped[str] = mapped_column(String(256), nullable=False)
    task_description: Mapped[str | None] = mapped_column(Text)
    assign_to_role: Mapped[str | None] = mapped_column(String(64))
    due_days_offset: Mapped[int | None] = mapped_column(Integer)  # days from trigger
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UdfDefinition(Base):
    """User-defined field definition.

    Allows tenants to add custom fields to standard entities.
    """

    __tablename__ = "udf_definitions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "entity_type", "field_key", name="uq_udf_def_entity_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # voyage | charter | invoice | vessel
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    field_label: Mapped[str] = mapped_column(String(128), nullable=False)
    field_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="string"
    )  # string | number | date | boolean | select
    options_json: Mapped[dict | None] = mapped_column(JSON)  # for select type
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    default_value: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UdfValue(Base):
    """User-defined field value.

    Stores actual values for UDF fields on entities.
    """

    __tablename__ = "udf_values"
    __table_args__ = (
        UniqueConstraint(
            "definition_id", "entity_id", name="uq_udf_value_def_entity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("udf_definitions.id"), nullable=False, index=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    field_value: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── 预置配置键目录（iMOS 风格功能开关 + 基础口径键）─────────────────────
# 每项: key / description / type（bool|number|string）/ default（Python 值，可省略）
# 种子写入 platform 域（scope_key="platform"），租户/用户域按需覆盖。

CONFIG_FLAG_PRESETS: dict[str, list[dict]] = {
    "financials": [
        {"key": "CFG_INVOICE_MIRROR", "description": "Enable mirror invoice generation", "type": "bool", "default": False},
        {"key": "CFG_USE_NATURAL_ROUNDING", "description": "Use natural rounding instead of banker's rounding", "type": "bool", "default": False},
        {"key": "CFG_COMMISSION_BASIS", "description": "Commission calculation basis (net/gross)", "type": "string", "default": "net"},
        {"key": "CFG_DEMURRAGE_INCLUDE_IN_PNL", "description": "Include demurrage in P&L calculation", "type": "bool", "default": False},
        {"key": "CFGEnableIntercompany", "description": "Enable intercompany invoicing and settlement", "type": "bool", "default": False},
        {"key": "CFGEnableAccruals", "description": "Enable accruals management in financials", "type": "bool", "default": False},
        {"key": "CFGEnableFinancialControl", "description": "Enable financial control workflows", "type": "bool", "default": False},
        {"key": "CFGEnableFinalFinancialsInvoice", "description": "Enable final financials invoice generation", "type": "bool", "default": False},
        {"key": "CFGEnableTaxIdentifierOnFinancialsInvoice", "description": "Show tax identifier on financials invoices", "type": "bool", "default": False},
        {"key": "CFGSelectBankDetailsFromBeneficiaryOnHireStatement", "description": "Select bank details from beneficiary on hire statement", "type": "bool", "default": False},
        {"key": "CFGEnablePaymentBatches", "description": "Enable payment batch processing", "type": "bool", "default": False},
        {"key": "CFGEnableAdvancePayments", "description": "Enable advance payments and allocations", "type": "bool", "default": False},
        {"key": "CFGEnableInvoiceRealization", "description": "Enable invoice realization tracking", "type": "bool", "default": False},
        {"key": "CFGEnableIFRS15", "description": "Enable IFRS 15 revenue recognition handling", "type": "bool", "default": False},
        {"key": "CFGEnableIFRS16", "description": "Enable IFRS 16 lease handling", "type": "bool", "default": False},
        {"key": "CFGEnableLeaseAccounting", "description": "Enable lease accounting", "type": "bool", "default": False},
    ],
    "operations": [
        {"key": "CFG_BILL_BY", "description": "Default billing basis (cp_qty/bl_qty)", "type": "string", "default": "cp_qty"},
        {"key": "CFG_LAYTIME_TERMS", "description": "Default laytime terms (SHINC/SHEX/SSHEX)", "type": "string", "default": "SHINC"},
        {"key": "CFG_CHARTERER_VIEW", "description": "Enable charterer view mode", "type": "bool", "default": False},
        {"key": "CFGEnableScheduling", "description": "Enable voyage scheduling", "type": "bool", "default": False},
        {"key": "CFGEnableBerthScheduling", "description": "Enable berth scheduling", "type": "bool", "default": False},
        {"key": "CFGEnableCargoBook", "description": "Enable cargo booking", "type": "bool", "default": False},
        {"key": "CFGEnableDistances", "description": "Enable distance tables and routing", "type": "bool", "default": False},
        {"key": "CFGEnablePiracy", "description": "Enable piracy risk zones and alerts", "type": "bool", "default": False},
        {"key": "CFGEnableLNG", "description": "Enable LNG-specific operations", "type": "bool", "default": False},
        {"key": "CFGEnableVesselVetting", "description": "Enable vessel vetting", "type": "bool", "default": False},
        {"key": "CFGEnableFleetMap", "description": "Enable fleet map view", "type": "bool", "default": False},
        {"key": "CFGEnableConsecutiveVoyages", "description": "Enable consecutive voyage handling", "type": "bool", "default": False},
        {"key": "CFGEnableVoyageETSRouting", "description": "Enable voyage ETS routing", "type": "bool", "default": False},
        {"key": "CFGEnableBarging", "description": "Enable barge operations", "type": "bool", "default": False},
        {"key": "CFGEnableLightering", "description": "Enable lightering operations", "type": "bool", "default": False},
        {"key": "CFGEnableCargoBooking", "description": "Enable cargo booking module", "type": "bool", "default": False},
        {"key": "CFGEnableCOA", "description": "Enable contract of affreightment", "type": "bool", "default": False},
        {"key": "CFGEnableSustainability", "description": "Enable sustainability reporting", "type": "bool", "default": False},
    ],
    "chartering": [
        {"key": "CFGEnableTrading", "description": "Enable trading module", "type": "bool", "default": False},
        {"key": "CFGEnableFFA", "description": "Enable forward freight agreements", "type": "bool", "default": False},
        {"key": "CFGEnableBunkerTrading", "description": "Enable bunker trading", "type": "bool", "default": False},
        {"key": "CFGEnableCommodityTrading", "description": "Enable commodity trading", "type": "bool", "default": False},
        {"key": "CFGEnableMirroring", "description": "Enable fixture mirroring", "type": "bool", "default": False},
        {"key": "CFGEnableRebilling", "description": "Enable expense rebilling to counterparties", "type": "bool", "default": False},
        {"key": "CFGEnableAdvancedPricing", "description": "Enable advanced pricing models", "type": "bool", "default": False},
        {"key": "CFGEnableScaleTables", "description": "Enable scale tables", "type": "bool", "default": False},
        {"key": "CFGEnableWorldScale", "description": "Enable Worldscale rate handling", "type": "bool", "default": False},
        {"key": "CFGEnableProfitShare", "description": "Enable profit share agreements", "type": "bool", "default": False},
    ],
    "compliance": [
        {"key": "CFGEnableMRV", "description": "Enable MRV emissions monitoring", "type": "bool", "default": False},
        {"key": "CFGEnableFuelEU", "description": "Enable FuelEU Maritime compliance", "type": "bool", "default": False},
        {"key": "CFGEnableECA", "description": "Enable ECA emission control area handling", "type": "bool", "default": False},
        {"key": "CFGEnableTCEmissionsAllocation", "description": "Enable TC emissions allocation", "type": "bool", "default": False},
        {"key": "CFGEnableCargoEmissionsAllocation", "description": "Enable cargo emissions allocation", "type": "bool", "default": False},
        {"key": "CFGAutoUpdateCarbonExposureOnVoyages", "description": "Auto-update carbon exposure on voyages", "type": "bool", "default": False},
        {"key": "CFGEnableTCEmissionsSettlement", "description": "Enable TC emissions settlement", "type": "bool", "default": False},
        {"key": "CFGEnableCarbonAllowanceTrading", "description": "Enable carbon allowance trading", "type": "bool", "default": False},
        {"key": "CFGEnableCarbonPricing", "description": "Enable carbon pricing", "type": "bool", "default": False},
        {"key": "CFGEnableUkEts", "description": "Enable UK ETS compliance", "type": "bool", "default": False},
        {"key": "CFGIncludeGibraltarInEts", "description": "Include Gibraltar in ETS scope", "type": "bool", "default": False},
        {"key": "CFGEnableFuelEUComplianceBalance", "description": "Enable FuelEU compliance balance tracking", "type": "bool", "default": False},
    ],
    "analytics": [
        {"key": "CFGEnableReportDesigner", "description": "Enable report designer", "type": "bool", "default": False},
        {"key": "CFGEnableAnalytics", "description": "Enable analytics dashboards", "type": "bool", "default": False},
        {"key": "CFGEnablePowerBI", "description": "Enable Power BI integration", "type": "bool", "default": False},
        {"key": "CFGEnableDataLake", "description": "Enable data lake export", "type": "bool", "default": False},
    ],
    "admin": [
        {"key": "CFGEnableSSO", "description": "Enable single sign-on", "type": "bool", "default": False},
        {"key": "CFGEnableUDF", "description": "Enable user-defined fields", "type": "bool", "default": False},
        {"key": "CFGEnableTaskAlerts", "description": "Enable task alerts", "type": "bool", "default": False},
        {"key": "CFGEnableBusinessRules", "description": "Enable business rules engine", "type": "bool", "default": False},
        {"key": "CFGEnableVeslink", "description": "Enable Veslink integration", "type": "bool", "default": False},
        {"key": "CFGEnableAgentPortal", "description": "Enable agent portal", "type": "bool", "default": False},
        {"key": "CFGEnableFormDesigner", "description": "Enable form designer", "type": "bool", "default": False},
        {"key": "CFGEnableAPI", "description": "Enable external API access", "type": "bool", "default": False},
        {"key": "CFGEnforceUniqueVesselImo", "description": "Enforce unique vessel IMO numbers", "type": "bool", "default": False},
        {"key": "CFGExcludeStatusFromVoyageTCDropdown", "description": "Exclude status from voyage TC dropdown", "type": "bool", "default": False},
    ],
    "bunkering": [
        {"key": "CFG_TCO_BUNKER_ADJ", "description": "TCO bunker adjustment factor", "type": "number", "default": 0.0},
    ],
    "emissions": [
        {"key": "CFG_EU_ETS_ENABLED", "description": "Enable EU ETS calculation", "type": "bool", "default": False},
        {"key": "CFG_FUELEU_ENABLED", "description": "Enable FuelEU Maritime calculation", "type": "bool", "default": False},
    ],
}
