"""Phase 6/8 — Report engine service.

Preset reports query existing domain tables and return structured data.
Custom reports support SQL-based data sources with parameter substitution.

Phase 8 (Report Designer): declarative specs (``query_spec`` v2) run through
``app.services.report_builder`` — no raw user SQL. ``SYSTEM_REPORT_SPECS``
adapters express the system reports as declarative specs over the seeded
datasets; preset executors remain the execution path for system reports and
derive their display rows from real domain tables.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models_domain import (
    BunkerOrder,
    Charter,
    EmissionRecord,
    Estimate,
    Invoice,
    LaytimeCalc,
    NoonReport,
    Payment,
    PortCall,
    PortDisbursement,
    SofEvent,
    Voyage,
)
from app.models_gl import ChartOfAccount, PeriodJournal
from app.models_report import (
    ReportDefinition,
    ReportDataset,
    ReportField,
    ReportJoin,
    ReportSchedule,
)
from app.models_time_charter import HireStatement, TimeCharterContract
from app.models_wave1 import Counterparty, Port, Vessel
from app.services.report_builder import (
    ReportSpecError,
    execute_query as builder_execute_query,
)


SYSTEM_REPORTS: list[dict[str, Any]] = [
    {
        "report_type": "voyage_pnl",
        "report_name": "Voyage P&L Report",
        "description": "Voyage profit & loss with estimate vs actual comparison",
        "data_source": "preset",
        "query": "voyage_pnl",
        "columns": [
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "charterer", "label": "Charterer", "width": 140},
            {"key": "load_port", "label": "Load Port", "width": 120},
            {"key": "disch_port", "label": "Disch Port", "width": 120},
            {"key": "cargo_qty", "label": "Cargo (MT)", "width": 100, "format": "number"},
            {"key": "freight_revenue", "label": "Freight Revenue", "width": 130, "format": "currency"},
            {"key": "total_costs", "label": "Total Costs", "width": 130, "format": "currency"},
            {"key": "net_pnl", "label": "Net P&L", "width": 130, "format": "currency"},
            {"key": "status", "label": "Status", "width": 100},
        ],
    },
    {
        "report_type": "bunker",
        "report_name": "Bunker Consumption Report",
        "description": "Fuel consumption by vessel, voyage, and fuel type",
        "data_source": "preset",
        "query": "bunker_consumption",
        "columns": [
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "fuel_type", "label": "Fuel Type", "width": 100},
            {"key": "quantity_mt", "label": "Quantity (MT)", "width": 120, "format": "number"},
            {"key": "unit_cost", "label": "Unit Cost ($/MT)", "width": 120, "format": "currency"},
            {"key": "total_cost", "label": "Total Cost", "width": 130, "format": "currency"},
            {"key": "order_date", "label": "Order Date", "width": 110, "format": "date"},
        ],
    },
    {
        "report_type": "tce_analysis",
        "report_name": "TCE Analysis Report",
        "description": "Time Charter Equivalent earnings comparison",
        "data_source": "preset",
        "query": "tce_analysis",
        "columns": [
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "voyage_days", "label": "Voyage Days", "width": 100, "format": "number"},
            {"key": "freight_revenue", "label": "Freight Revenue", "width": 130, "format": "currency"},
            {"key": "bunker_cost", "label": "Bunker Cost", "width": 130, "format": "currency"},
            {"key": "port_cost", "label": "Port Cost", "width": 130, "format": "currency"},
            {"key": "tce", "label": "TCE ($/day)", "width": 120, "format": "currency"},
        ],
    },
    {
        "report_type": "fleet_performance",
        "report_name": "Fleet Performance Report",
        "description": "Fleet-wide operational performance summary",
        "data_source": "preset",
        "query": "fleet_performance",
        "columns": [
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "voyage_count", "label": "Voyages", "width": 80, "format": "number"},
            {"key": "total_revenue", "label": "Total Revenue", "width": 130, "format": "currency"},
            {"key": "total_bunker_cost", "label": "Bunker Cost", "width": 130, "format": "currency"},
            {"key": "avg_tce", "label": "Avg TCE ($/day)", "width": 120, "format": "currency"},
            {"key": "total_co2", "label": "CO2 (tonnes)", "width": 120, "format": "number"},
        ],
    },
    {
        "report_type": "counterparty",
        "report_name": "Counterparty Summary",
        "description": "Business volume and outstanding balances by counterparty",
        "data_source": "preset",
        "query": "counterparty_summary",
        "columns": [
            {"key": "party_name", "label": "Counterparty", "width": 180},
            {"key": "voyage_count", "label": "Voyages", "width": 80, "format": "number"},
            {"key": "total_revenue", "label": "Total Revenue", "width": 130, "format": "currency"},
            {"key": "outstanding", "label": "Outstanding", "width": 130, "format": "currency"},
            {"key": "last_activity", "label": "Last Activity", "width": 110, "format": "date"},
        ],
    },
    {
        "report_type": "age_days",
        "report_name": "Age Days Report",
        "description": "Receivable/payable aging analysis",
        "data_source": "preset",
        "query": "age_days",
        "columns": [
            {"key": "invoice_no", "label": "Invoice #", "width": 120},
            {"key": "party_name", "label": "Counterparty", "width": 160},
            {"key": "invoice_type", "label": "Type", "width": 100},
            {"key": "amount", "label": "Amount", "width": 120, "format": "currency"},
            {"key": "outstanding", "label": "Outstanding", "width": 120, "format": "currency"},
            {"key": "days_overdue", "label": "Days Overdue", "width": 100, "format": "number"},
            {"key": "aging_bucket", "label": "Aging Bucket", "width": 100},
        ],
    },
    {
        "report_type": "port_details",
        "report_name": "Port Details Report",
        "description": "Port call statistics and costs",
        "data_source": "preset",
        "query": "port_details",
        "columns": [
            {"key": "port_name", "label": "Port", "width": 160},
            {"key": "call_count", "label": "Calls", "width": 80, "format": "number"},
            {"key": "avg_stay_hours", "label": "Avg Stay (hrs)", "width": 110, "format": "number"},
            {"key": "total_port_cost", "label": "Total Port Cost", "width": 130, "format": "currency"},
            {"key": "last_call", "label": "Last Call", "width": 110, "format": "date"},
        ],
    },
    {
        "report_type": "emissions",
        "report_name": "Cargo Emissions Report",
        "description": "CO2 emissions per cargo unit for compliance reporting",
        "data_source": "preset",
        "query": "cargo_emissions",
        "columns": [
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "cargo_qty", "label": "Cargo (MT)", "width": 100, "format": "number"},
            {"key": "co2_total", "label": "CO2 Total (t)", "width": 120, "format": "number"},
            {"key": "co2_per_cargo", "label": "CO2/Cargo (t/MT)", "width": 130, "format": "number"},
            {"key": "eu_ets_cost", "label": "EU ETS Cost", "width": 120, "format": "currency"},
        ],
    },
    {
        "report_type": "speed",
        "report_name": "Speed Comparison",
        "description": "Observed vs design speed and consumption by vessel (noon reports + bunker data)",
        "data_source": "preset",
        "query": "speed_comparison",
        "columns": [
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "voyage_count", "label": "Voyages", "width": 80, "format": "number"},
            {"key": "avg_noon_speed", "label": "Avg Observed Speed (kn)", "width": 150, "format": "number"},
            {"key": "design_speed", "label": "Design Speed (kn)", "width": 130, "format": "number"},
            {"key": "avg_consumption", "label": "Avg Consumption (MT/day)", "width": 150, "format": "number"},
        ],
    },
    # ---- Chartering / Commercial ----
    {
        "report_type": "sof_statement",
        "report_name": "Statement of Facts",
        "description": "SOF events by port call with inter-event durations",
        "data_source": "preset",
        "query": "sof_statement",
        "columns": [
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "port_name", "label": "Port", "width": 130},
            {"key": "event_code", "label": "Event", "width": 120},
            {"key": "event_at", "label": "Event Time", "width": 150, "format": "datetime"},
            {"key": "duration_hours", "label": "Duration (hrs)", "width": 110, "format": "number"},
            {"key": "remarks", "label": "Remarks", "width": 180},
        ],
    },
    {
        "report_type": "laytime_statement",
        "report_name": "Laytime / Demurrage Statement",
        "description": "Allowed vs used laytime, demurrage and despatch amounts",
        "data_source": "preset",
        "query": "laytime_statement",
        "columns": [
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "port_name", "label": "Port", "width": 130},
            {"key": "allowed_days", "label": "Allowed Days", "width": 110, "format": "number"},
            {"key": "used_days", "label": "Used Days", "width": 100, "format": "number"},
            {"key": "demurrage_rate", "label": "Demurrage Rate", "width": 120, "format": "currency"},
            {"key": "despatch_rate", "label": "Despatch Rate", "width": 120, "format": "currency"},
            {"key": "demurrage_amount", "label": "Demurrage Amount", "width": 130, "format": "currency"},
            {"key": "despatch_amount", "label": "Despatch Amount", "width": 130, "format": "currency"},
            {"key": "status", "label": "Status", "width": 90},
        ],
    },
    {
        "report_type": "hire_statement",
        "report_name": "TC Hire Statement",
        "description": "Time-charter hire statements: period, rate, off-hire, net hire",
        "data_source": "preset",
        "query": "hire_statement",
        "columns": [
            {"key": "statement_no", "label": "Statement #", "width": 120},
            {"key": "contract_no", "label": "Contract", "width": 110},
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "period_start", "label": "Period From", "width": 105, "format": "date"},
            {"key": "period_end", "label": "Period To", "width": 105, "format": "date"},
            {"key": "hire_rate", "label": "Hire Rate ($/day)", "width": 125, "format": "currency"},
            {"key": "hire_days", "label": "Hire Days", "width": 95, "format": "number"},
            {"key": "off_hire_days", "label": "Off-Hire Days", "width": 105, "format": "number"},
            {"key": "net_hire", "label": "Net Hire", "width": 125, "format": "currency"},
            {"key": "status", "label": "Status", "width": 90},
        ],
    },
    {
        "report_type": "estimate_vs_actual",
        "report_name": "Estimate vs Actual P&L",
        "description": "Estimated revenue/cost against realised voyage results with variance",
        "data_source": "preset",
        "query": "estimate_vs_actual",
        "columns": [
            {"key": "estimate_title", "label": "Estimate", "width": 180},
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "est_revenue", "label": "Est Revenue", "width": 120, "format": "currency"},
            {"key": "act_revenue", "label": "Actual Revenue", "width": 125, "format": "currency"},
            {"key": "est_cost", "label": "Est Cost", "width": 120, "format": "currency"},
            {"key": "act_cost", "label": "Actual Cost", "width": 120, "format": "currency"},
            {"key": "revenue_variance", "label": "Revenue Variance", "width": 130, "format": "currency"},
            {"key": "cost_variance", "label": "Cost Variance", "width": 120, "format": "currency"},
            {"key": "net_variance", "label": "Net Variance", "width": 120, "format": "currency"},
        ],
    },
    {
        "report_type": "fixture_recap",
        "report_name": "Fixture Recap",
        "description": "Fixture recap: vessel, cargo, route, freight rate, laycan, CP form",
        "data_source": "preset",
        "query": "fixture_recap",
        "columns": [
            {"key": "fixture_date", "label": "Fixture Date", "width": 105, "format": "date"},
            {"key": "charter_no", "label": "CP #", "width": 100},
            {"key": "vessel_name", "label": "Vessel", "width": 140},
            {"key": "charterer", "label": "Charterer", "width": 150},
            {"key": "cargo", "label": "Cargo", "width": 150},
            {"key": "load_port", "label": "Load Port", "width": 120},
            {"key": "disch_port", "label": "Disch Port", "width": 120},
            {"key": "freight_rate", "label": "Freight Rate", "width": 110, "format": "currency"},
            {"key": "laycan_from", "label": "Laycan From", "width": 105, "format": "date"},
            {"key": "laycan_to", "label": "Laycan To", "width": 105, "format": "date"},
            {"key": "cp_form", "label": "CP Form", "width": 90},
        ],
    },
    # ---- Finance ----
    {
        "report_type": "trial_balance",
        "report_name": "GL Trial Balance",
        "description": "Posted GL totals by account (debit, credit, balance)",
        "data_source": "preset",
        "query": "trial_balance",
        "columns": [
            {"key": "account_code", "label": "Account Code", "width": 110},
            {"key": "account_name", "label": "Account Name", "width": 180},
            {"key": "account_type", "label": "Type", "width": 100},
            {"key": "debit_total", "label": "Debit Total", "width": 125, "format": "currency"},
            {"key": "credit_total", "label": "Credit Total", "width": 125, "format": "currency"},
            {"key": "balance", "label": "Balance", "width": 125, "format": "currency"},
        ],
    },
    {
        "report_type": "commission_report",
        "report_name": "Commission Report",
        "description": "Brokerage / address commission breakdown by invoice",
        "data_source": "preset",
        "query": "commission_report",
        "columns": [
            {"key": "invoice_no", "label": "Invoice #", "width": 120},
            {"key": "broker", "label": "Broker", "width": 150},
            {"key": "commission_type", "label": "Commission Type", "width": 130},
            {"key": "rate_pct", "label": "Rate (%)", "width": 90, "format": "number"},
            {"key": "base_amount", "label": "Base Amount", "width": 125, "format": "currency"},
            {"key": "amount", "label": "Commission Amount", "width": 140, "format": "currency"},
            {"key": "currency", "label": "Currency", "width": 80},
        ],
    },
    {
        "report_type": "statement_of_account",
        "report_name": "Statement of Account",
        "description": "Counterparty statement: invoices, payments and outstanding balances",
        "data_source": "preset",
        "query": "statement_of_account",
        "columns": [
            {"key": "party_name", "label": "Counterparty", "width": 170},
            {"key": "invoice_no", "label": "Invoice #", "width": 120},
            {"key": "invoice_date", "label": "Date", "width": 105, "format": "date"},
            {"key": "invoice_type", "label": "Type", "width": 100},
            {"key": "amount", "label": "Amount", "width": 125, "format": "currency"},
            {"key": "paid", "label": "Paid", "width": 125, "format": "currency"},
            {"key": "outstanding", "label": "Outstanding", "width": 125, "format": "currency"},
            {"key": "status", "label": "Status", "width": 90},
        ],
    },
    {
        "report_type": "port_cost_breakdown",
        "report_name": "Port Cost Breakdown (PDA vs FDA)",
        "description": "Proforma vs final disbursement account with variance",
        "data_source": "preset",
        "query": "port_cost_breakdown",
        "columns": [
            {"key": "port_name", "label": "Port", "width": 150},
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "pda_amount", "label": "PDA Amount", "width": 125, "format": "currency"},
            {"key": "fda_amount", "label": "FDA Amount", "width": 125, "format": "currency"},
            {"key": "variance", "label": "Variance", "width": 120, "format": "currency"},
            {"key": "variance_pct", "label": "Variance %", "width": 100, "format": "number"},
            {"key": "status", "label": "Status", "width": 90},
        ],
    },
    {
        "report_type": "credit_exposure",
        "report_name": "Credit Exposure",
        "description": "Open receivable exposure vs credit limit by counterparty",
        "data_source": "preset",
        "query": "credit_exposure",
        "columns": [
            {"key": "party_name", "label": "Counterparty", "width": 180},
            {"key": "open_invoices", "label": "Open Invoices", "width": 105, "format": "number"},
            {"key": "total_exposure", "label": "Total Exposure", "width": 130, "format": "currency"},
            {"key": "credit_limit", "label": "Credit Limit", "width": 125, "format": "currency"},
            {"key": "utilization_pct", "label": "Utilization %", "width": 110, "format": "number"},
            {"key": "breach", "label": "Breach", "width": 80},
        ],
    },
    # ---- Emissions / Regulatory ----
    {
        "report_type": "cii_annual",
        "report_name": "CII Annual Report",
        "description": "Annual operational CII: AER, required CII and A-E rating per vessel",
        "data_source": "preset",
        "query": "cii_annual",
        "columns": [
            {"key": "vessel_name", "label": "Vessel", "width": 150},
            {"key": "period", "label": "Period", "width": 90},
            {"key": "distance_nm", "label": "Distance (nm)", "width": 115, "format": "number"},
            {"key": "co2_mt", "label": "CO2 (t)", "width": 100, "format": "number"},
            {"key": "aer", "label": "AER (gCO2/dwt·nm)", "width": 150, "format": "number"},
            {"key": "required_cii", "label": "Required CII", "width": 110, "format": "number"},
            {"key": "cii_rating", "label": "CII Rating", "width": 95},
        ],
    },
    {
        "report_type": "mrv_voyage",
        "report_name": "MRV Voyage Report",
        "description": "EU MRV per-voyage: fuel, CO2, transport work and AER",
        "data_source": "preset",
        "query": "mrv_voyage",
        "columns": [
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "vessel_name", "label": "Vessel", "width": 145},
            {"key": "fuel_type", "label": "Fuel Type", "width": 110},
            {"key": "fo_mt", "label": "FO (t)", "width": 90, "format": "number"},
            {"key": "do_mt", "label": "DO (t)", "width": 90, "format": "number"},
            {"key": "co2_mt", "label": "CO2 (t)", "width": 100, "format": "number"},
            {"key": "transport_work", "label": "Transport Work (t·nm)", "width": 155, "format": "number"},
            {"key": "aer", "label": "AER (gCO2/dwt·nm)", "width": 150, "format": "number"},
        ],
    },
    {
        "report_type": "eu_ets_cost",
        "report_name": "EU ETS Cost Report",
        "description": "EU ETS allowance cost per voyage (phase-in applied)",
        "data_source": "preset",
        "query": "eu_ets_cost",
        "columns": [
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "vessel_name", "label": "Vessel", "width": 145},
            {"key": "co2_mt", "label": "CO2 (t)", "width": 100, "format": "number"},
            {"key": "eu_share_pct", "label": "EU Share %", "width": 100, "format": "number"},
            {"key": "applicable_pct", "label": "Applicable %", "width": 110, "format": "number"},
            {"key": "ets_price_eur", "label": "EUA Price (EUR)", "width": 120, "format": "currency"},
            {"key": "allowance_cost_eur", "label": "Allowance Cost (EUR)", "width": 150, "format": "currency"},
        ],
    },
    # ---- Operations ----
    {
        "report_type": "noon_report_summary",
        "report_name": "Noon Report Summary",
        "description": "Noon positions: speed, consumption, ROB and ETA deviation",
        "data_source": "preset",
        "query": "noon_report_summary",
        "columns": [
            {"key": "vessel_name", "label": "Vessel", "width": 145},
            {"key": "voyage_no", "label": "Voyage #", "width": 100},
            {"key": "report_at", "label": "Date", "width": 120, "format": "datetime"},
            {"key": "position", "label": "Position", "width": 140},
            {"key": "speed", "label": "Speed (kn)", "width": 95, "format": "number"},
            {"key": "consumption_mt", "label": "Consumption (t)", "width": 120, "format": "number"},
            {"key": "rob_fo", "label": "ROB FO (t)", "width": 100, "format": "number"},
            {"key": "rob_do", "label": "ROB DO (t)", "width": 100, "format": "number"},
            {"key": "eta_deviation_hours", "label": "ETA Dev (hrs)", "width": 110, "format": "number"},
        ],
    },
    {
        "report_type": "bunker_reconciliation",
        "report_name": "Bunker Reconciliation",
        "description": "BDN quantity vs ROB movement and consumption variance",
        "data_source": "preset",
        "query": "bunker_reconciliation",
        "columns": [
            {"key": "vessel_name", "label": "Vessel", "width": 145},
            {"key": "order_no", "label": "Order #", "width": 110},
            {"key": "grade", "label": "Grade", "width": 90},
            {"key": "bdn_qty", "label": "BDN Qty (t)", "width": 105, "format": "number"},
            {"key": "rob_before", "label": "ROB Start (t)", "width": 110, "format": "number"},
            {"key": "rob_after", "label": "ROB End (t)", "width": 105, "format": "number"},
            {"key": "consumption", "label": "Consumption (t)", "width": 120, "format": "number"},
            {"key": "computed_consumption", "label": "Computed (t)", "width": 110, "format": "number"},
            {"key": "variance", "label": "Variance (t)", "width": 105, "format": "number"},
        ],
    },
    {
        "report_type": "vessel_utilization",
        "report_name": "Vessel Utilization",
        "description": "Voyage / sea / port days and utilization by vessel",
        "data_source": "preset",
        "query": "vessel_utilization",
        "columns": [
            {"key": "vessel_name", "label": "Vessel", "width": 150},
            {"key": "voyage_days", "label": "Voyage Days", "width": 105, "format": "number"},
            {"key": "sea_days", "label": "Sea Days", "width": 95, "format": "number"},
            {"key": "port_days", "label": "Port Days", "width": 95, "format": "number"},
            {"key": "utilization_pct", "label": "Utilization %", "width": 110, "format": "number"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Phase 8 — declarative adapters for the system reports
# ---------------------------------------------------------------------------
# Each system report can also be expressed as a declarative spec over the
# seeded datasets (report_builder). Derived display metrics (net P&L, aging
# buckets, ...) stay in the preset executors; the specs cover the base
# columns and safe arithmetic expressions.

def _spec_voyage_pnl() -> dict:
    return {
        "datasets": [
            {"dataset": "voyages", "alias": "v"},
            {"dataset": "vessels", "alias": "vs"},
            {"dataset": "charters", "alias": "c"},
            {"dataset": "counterparties", "alias": "cp"},
        ],
        "joins": [
            {"left": "v", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
            {"left": "v", "right": "c", "join_type": "left", "left_field": "charter_id", "right_field": "id"},
            {"left": "c", "right": "cp", "join_type": "left", "left_field": "counterparty_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "cp", "field": "name", "label": "Charterer"},
            {"dataset": "c", "field": "cargo_qty", "label": "Cargo (MT)", "format": "number"},
            {"dataset": "v", "field": "status", "label": "Status"},
        ],
        "order_by": [{"dataset": "v", "field": "created_at", "direction": "desc"}],
    }


def _spec_bunker() -> dict:
    return {
        "datasets": [
            {"dataset": "bunker_orders", "alias": "b"},
            {"dataset": "vessels", "alias": "vs"},
            {"dataset": "voyages", "alias": "v"},
        ],
        "joins": [
            {"left": "b", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
            {"left": "b", "right": "v", "join_type": "left", "left_field": "voyage_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "b", "field": "grade", "label": "Fuel Type"},
            {
                "dataset": "b",
                "expression": "coalesce(qty_delivered, qty_ordered)",
                "label": "Quantity (MT)",
                "format": "number",
            },
            {"dataset": "b", "field": "unit_price", "label": "Unit Cost ($/MT)", "format": "currency"},
            {
                "dataset": "b",
                "expression": "coalesce(qty_delivered, qty_ordered) * unit_price",
                "label": "Total Cost",
                "format": "currency",
            },
        ],
        "order_by": [{"dataset": "b", "field": "bdn_date", "direction": "desc"}],
    }


def _spec_tce() -> dict:
    return {
        "datasets": [
            {"dataset": "voyages", "alias": "v"},
            {"dataset": "vessels", "alias": "vs"},
        ],
        "joins": [
            {"left": "v", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "v", "field": "started_at", "label": "Started", "format": "date"},
            {"dataset": "v", "field": "completed_at", "label": "Completed", "format": "date"},
        ],
        "order_by": [{"dataset": "v", "field": "created_at", "direction": "desc"}],
    }


def _spec_fleet() -> dict:
    return {
        "datasets": [
            {"dataset": "voyages", "alias": "v"},
            {"dataset": "vessels", "alias": "vs"},
        ],
        "joins": [
            {"left": "v", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "v", "field": "id", "label": "Voyages", "agg": "count"},
        ],
        "group_by": [{"dataset": "vs", "field": "name"}],
        "order_by": [{"label": "Voyages", "direction": "desc"}],
    }


def _spec_counterparty() -> dict:
    return {
        "datasets": [
            {"dataset": "counterparties", "alias": "cp"},
            {"dataset": "charters", "alias": "c"},
            {"dataset": "voyages", "alias": "v"},
        ],
        "joins": [
            {"left": "cp", "right": "c", "join_type": "left", "left_field": "id", "right_field": "counterparty_id"},
            {"left": "c", "right": "v", "join_type": "left", "left_field": "id", "right_field": "charter_id"},
        ],
        "fields": [
            {"dataset": "cp", "field": "name", "label": "Counterparty"},
            {"dataset": "v", "field": "id", "label": "Voyages", "agg": "count"},
        ],
        "group_by": [{"dataset": "cp", "field": "name"}],
    }


def _spec_age_days() -> dict:
    return {
        "datasets": [
            {"dataset": "invoices", "alias": "i"},
            {"dataset": "counterparties", "alias": "cp"},
        ],
        "joins": [
            {"left": "i", "right": "cp", "join_type": "left", "left_field": "counterparty_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "i", "field": "invoice_no", "label": "Invoice #"},
            {"dataset": "cp", "field": "name", "label": "Counterparty"},
            {"dataset": "i", "field": "invoice_type", "label": "Type"},
            {"dataset": "i", "field": "amount", "label": "Amount", "format": "currency"},
            {
                "dataset": "i",
                "expression": "amount - paid_amount",
                "label": "Outstanding",
                "format": "currency",
            },
            {"dataset": "i", "field": "due_date", "label": "Due Date", "format": "date"},
        ],
        "order_by": [{"dataset": "i", "field": "due_date", "direction": "asc"}],
    }


def _spec_port_details() -> dict:
    return {
        "datasets": [{"dataset": "port_calls", "alias": "pc"}],
        "fields": [
            {"dataset": "pc", "field": "purpose", "label": "Purpose"},
            {"dataset": "pc", "field": "port_id", "label": "Port ID"},
            {"dataset": "pc", "field": "id", "label": "Calls", "agg": "count"},
        ],
        "group_by": [
            {"dataset": "pc", "field": "purpose"},
            {"dataset": "pc", "field": "port_id"},
        ],
    }


def _spec_emissions() -> dict:
    return {
        "datasets": [
            {"dataset": "voyages", "alias": "v"},
            {"dataset": "vessels", "alias": "vs"},
            {"dataset": "charters", "alias": "c"},
        ],
        "joins": [
            {"left": "v", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
            {"left": "v", "right": "c", "join_type": "left", "left_field": "charter_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "c", "field": "cargo_qty", "label": "Cargo (MT)", "format": "number"},
        ],
        "order_by": [{"dataset": "v", "field": "created_at", "direction": "desc"}],
    }


def _spec_speed() -> dict:
    return {
        "datasets": [
            {"dataset": "vessels", "alias": "vs"},
            {"dataset": "voyages", "alias": "v"},
        ],
        "joins": [
            {"left": "vs", "right": "v", "join_type": "left", "left_field": "id", "right_field": "vessel_id"},
        ],
        "fields": [
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "vs", "field": "speed_knots", "label": "Speed (kn)", "format": "number"},
            {"dataset": "vs", "field": "consumption_sea", "label": "Consumption (MT/day)", "format": "number"},
            {"dataset": "v", "field": "id", "label": "Voyages", "agg": "count"},
        ],
        "group_by": [
            {"dataset": "vs", "field": "name"},
            {"dataset": "vs", "field": "speed_knots"},
            {"dataset": "vs", "field": "consumption_sea"},
        ],
    }


def _spec_sof_statement() -> dict:
    return {
        "datasets": [
            {"dataset": "sof_events", "alias": "se"},
            {"dataset": "port_calls", "alias": "pc"},
            {"dataset": "voyages", "alias": "v"},
        ],
        "joins": [
            {"left": "se", "right": "pc", "join_type": "left", "left_field": "port_call_id", "right_field": "id"},
            {"left": "pc", "right": "v", "join_type": "left", "left_field": "voyage_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "pc", "field": "port_id", "label": "Port ID"},
            {"dataset": "pc", "field": "purpose", "label": "Purpose"},
            {"dataset": "se", "field": "event_code", "label": "Event"},
            {"dataset": "se", "field": "event_at", "label": "Event Time", "format": "datetime"},
            {"dataset": "se", "field": "remarks", "label": "Remarks"},
        ],
        "order_by": [{"dataset": "se", "field": "event_at", "direction": "asc"}],
    }


def _spec_laytime_statement() -> dict:
    return {
        "datasets": [
            {"dataset": "laytime", "alias": "lc"},
            {"dataset": "voyages", "alias": "v"},
        ],
        "joins": [
            {"left": "lc", "right": "v", "join_type": "left", "left_field": "voyage_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "lc", "field": "status", "label": "Status"},
            {"dataset": "lc", "field": "finalized_at", "label": "Finalized", "format": "datetime"},
        ],
        "order_by": [{"dataset": "lc", "field": "finalized_at", "direction": "desc"}],
    }


def _spec_hire_statement() -> dict:
    return {
        "datasets": [
            {"dataset": "hire_statements", "alias": "hs"},
            {"dataset": "time_charter_contracts", "alias": "tc"},
        ],
        "joins": [
            {"left": "hs", "right": "tc", "join_type": "left", "left_field": "contract_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "hs", "field": "statement_number", "label": "Statement #"},
            {"dataset": "tc", "field": "contract_type", "label": "Contract Type"},
            {"dataset": "hs", "field": "period_start", "label": "Period From", "format": "date"},
            {"dataset": "hs", "field": "period_end", "label": "Period To", "format": "date"},
            {"dataset": "hs", "field": "hire_days", "label": "Hire Days", "format": "number"},
            {"dataset": "hs", "field": "off_hire_days", "label": "Off-Hire Days", "format": "number"},
            {"dataset": "hs", "field": "net_hire", "label": "Net Hire", "format": "currency"},
        ],
        "order_by": [{"dataset": "hs", "field": "period_start", "direction": "desc"}],
    }


def _spec_estimate_vs_actual() -> dict:
    return {
        "datasets": [
            {"dataset": "estimates", "alias": "e"},
            {"dataset": "vessels", "alias": "vs"},
        ],
        "joins": [
            {"left": "e", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "e", "field": "title", "label": "Estimate"},
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "e", "field": "mode", "label": "Mode"},
            {"dataset": "e", "field": "status", "label": "Status"},
            {"dataset": "e", "field": "version", "label": "Version", "format": "number"},
        ],
        "order_by": [{"dataset": "e", "field": "created_at", "direction": "desc"}],
    }


def _spec_fixture_recap() -> dict:
    return {
        "datasets": [
            {"dataset": "charters", "alias": "c"},
            {"dataset": "vessels", "alias": "vs"},
            {"dataset": "counterparties", "alias": "cp"},
        ],
        "joins": [
            {"left": "c", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
            {"left": "c", "right": "cp", "join_type": "left", "left_field": "counterparty_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "c", "field": "charter_no", "label": "CP #"},
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "cp", "field": "name", "label": "Charterer"},
            {"dataset": "c", "field": "cargo_qty", "label": "Cargo (MT)", "format": "number"},
            {"dataset": "c", "field": "freight_rate", "label": "Freight Rate", "format": "currency"},
            {"dataset": "c", "field": "laycan_from", "label": "Laycan From", "format": "date"},
            {"dataset": "c", "field": "laycan_to", "label": "Laycan To", "format": "date"},
            {"dataset": "c", "field": "cp_form", "label": "CP Form"},
        ],
        "order_by": [{"dataset": "c", "field": "laycan_from", "direction": "desc"}],
    }


def _spec_trial_balance() -> dict:
    return {
        "datasets": [{"dataset": "chart_of_accounts", "alias": "a"}],
        "fields": [
            {"dataset": "a", "field": "account_code", "label": "Account Code"},
            {"dataset": "a", "field": "account_name", "label": "Account Name"},
            {"dataset": "a", "field": "account_type", "label": "Type"},
            {"dataset": "a", "field": "is_active", "label": "Active"},
        ],
        "order_by": [{"dataset": "a", "field": "account_code", "direction": "asc"}],
    }


def _spec_commission_report() -> dict:
    return {
        "datasets": [
            {"dataset": "invoices", "alias": "i"},
            {"dataset": "counterparties", "alias": "cp"},
        ],
        "joins": [
            {"left": "i", "right": "cp", "join_type": "left", "left_field": "counterparty_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "i", "field": "invoice_no", "label": "Invoice #"},
            {"dataset": "cp", "field": "name", "label": "Counterparty"},
            {"dataset": "i", "field": "invoice_type", "label": "Type"},
            {"dataset": "i", "field": "commission_basis", "label": "Basis"},
            {"dataset": "i", "field": "amount", "label": "Amount", "format": "currency"},
        ],
        "order_by": [{"dataset": "i", "field": "issued_at", "direction": "desc"}],
    }


def _spec_statement_of_account() -> dict:
    return {
        "datasets": [
            {"dataset": "invoices", "alias": "i"},
            {"dataset": "counterparties", "alias": "cp"},
        ],
        "joins": [
            {"left": "i", "right": "cp", "join_type": "left", "left_field": "counterparty_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "cp", "field": "name", "label": "Counterparty"},
            {"dataset": "i", "field": "invoice_no", "label": "Invoice #"},
            {"dataset": "i", "field": "issued_at", "label": "Date", "format": "date"},
            {"dataset": "i", "field": "amount", "label": "Amount", "format": "currency"},
            {"dataset": "i", "field": "paid_amount", "label": "Paid", "format": "currency"},
            {
                "dataset": "i",
                "expression": "amount - paid_amount",
                "label": "Outstanding",
                "format": "currency",
            },
        ],
        "order_by": [{"dataset": "cp", "field": "name", "direction": "asc"}],
    }


def _spec_port_cost_breakdown() -> dict:
    return {
        "datasets": [
            {"dataset": "port_disbursements", "alias": "pd"},
            {"dataset": "port_calls", "alias": "pc"},
        ],
        "joins": [
            {"left": "pd", "right": "pc", "join_type": "left", "left_field": "port_call_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "pc", "field": "port_id", "label": "Port ID"},
            {"dataset": "pd", "field": "pda_amount", "label": "PDA Amount", "format": "currency"},
            {"dataset": "pd", "field": "fda_amount", "label": "FDA Amount", "format": "currency"},
            {
                "dataset": "pd",
                "expression": "fda_amount - pda_amount",
                "label": "Variance",
                "format": "currency",
            },
            {"dataset": "pd", "field": "status", "label": "Status"},
        ],
        "order_by": [{"dataset": "pd", "field": "voyage_id", "direction": "asc"}],
    }


def _spec_credit_exposure() -> dict:
    return {
        "datasets": [
            {"dataset": "counterparties", "alias": "cp"},
            {"dataset": "invoices", "alias": "i"},
        ],
        "joins": [
            {"left": "cp", "right": "i", "join_type": "left", "left_field": "id", "right_field": "counterparty_id"},
        ],
        "fields": [
            {"dataset": "cp", "field": "name", "label": "Counterparty"},
            {"dataset": "cp", "field": "credit_rating", "label": "Rating"},
            {"dataset": "i", "field": "id", "label": "Invoices", "agg": "count"},
            {"dataset": "i", "field": "amount", "label": "Total Amount", "agg": "sum", "format": "currency"},
        ],
        "group_by": [
            {"dataset": "cp", "field": "name"},
            {"dataset": "cp", "field": "credit_rating"},
        ],
        "order_by": [{"label": "Total Amount", "direction": "desc"}],
    }


def _spec_cii_annual() -> dict:
    return {
        "datasets": [
            {"dataset": "emissions", "alias": "e"},
            {"dataset": "vessels", "alias": "vs"},
        ],
        "joins": [
            {"left": "e", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "e", "field": "period", "label": "Period"},
            {"dataset": "e", "field": "co2_mt", "label": "CO2 (t)", "agg": "sum", "format": "number"},
            {"dataset": "e", "field": "cii_rating", "label": "CII Rating"},
        ],
        "group_by": [
            {"dataset": "vs", "field": "name"},
            {"dataset": "e", "field": "period"},
            {"dataset": "e", "field": "cii_rating"},
        ],
    }


def _spec_mrv_voyage() -> dict:
    return {
        "datasets": [
            {"dataset": "emissions", "alias": "e"},
            {"dataset": "voyages", "alias": "v"},
            {"dataset": "vessels", "alias": "vs"},
        ],
        "joins": [
            {"left": "e", "right": "v", "join_type": "left", "left_field": "voyage_id", "right_field": "id"},
            {"left": "v", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "e", "field": "fo_mt", "label": "FO (t)", "agg": "sum", "format": "number"},
            {"dataset": "e", "field": "do_mt", "label": "DO (t)", "agg": "sum", "format": "number"},
            {"dataset": "e", "field": "co2_mt", "label": "CO2 (t)", "agg": "sum", "format": "number"},
        ],
        "group_by": [
            {"dataset": "v", "field": "voyage_no"},
            {"dataset": "vs", "field": "name"},
        ],
    }


def _spec_eu_ets_cost() -> dict:
    return {
        "datasets": [
            {"dataset": "emissions", "alias": "e"},
            {"dataset": "voyages", "alias": "v"},
        ],
        "joins": [
            {"left": "e", "right": "v", "join_type": "left", "left_field": "voyage_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "e", "field": "co2_mt", "label": "CO2 (t)", "agg": "sum", "format": "number"},
            {"dataset": "e", "field": "period", "label": "Period"},
        ],
        "group_by": [
            {"dataset": "v", "field": "voyage_no"},
            {"dataset": "e", "field": "period"},
        ],
    }


def _spec_noon_report_summary() -> dict:
    return {
        "datasets": [
            {"dataset": "noon_reports", "alias": "n"},
            {"dataset": "voyages", "alias": "v"},
            {"dataset": "vessels", "alias": "vs"},
        ],
        "joins": [
            {"left": "n", "right": "v", "join_type": "left", "left_field": "voyage_id", "right_field": "id"},
            {"left": "v", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "v", "field": "voyage_no", "label": "Voyage #"},
            {"dataset": "n", "field": "report_at", "label": "Date", "format": "datetime"},
            {"dataset": "n", "field": "speed", "label": "Speed (kn)", "format": "number"},
            {"dataset": "n", "field": "rob_fo", "label": "ROB FO (t)", "format": "number"},
            {"dataset": "n", "field": "rob_do", "label": "ROB DO (t)", "format": "number"},
            {"dataset": "n", "field": "eta_deviation_hours", "label": "ETA Dev (hrs)", "format": "number"},
        ],
        "order_by": [{"dataset": "n", "field": "report_at", "direction": "desc"}],
    }


def _spec_bunker_reconciliation() -> dict:
    return {
        "datasets": [
            {"dataset": "bunker_orders", "alias": "b"},
            {"dataset": "vessels", "alias": "vs"},
        ],
        "joins": [
            {"left": "b", "right": "vs", "join_type": "left", "left_field": "vessel_id", "right_field": "id"},
        ],
        "fields": [
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "b", "field": "order_no", "label": "Order #"},
            {"dataset": "b", "field": "grade", "label": "Grade"},
            {"dataset": "b", "field": "bdn_qty", "label": "BDN Qty (t)", "format": "number"},
            {"dataset": "b", "field": "rob_before", "label": "ROB Start (t)", "format": "number"},
            {"dataset": "b", "field": "rob_after", "label": "ROB End (t)", "format": "number"},
            {"dataset": "b", "field": "consumption", "label": "Consumption (t)", "format": "number"},
        ],
        "order_by": [{"dataset": "b", "field": "bdn_date", "direction": "desc"}],
    }


def _spec_vessel_utilization() -> dict:
    return {
        "datasets": [
            {"dataset": "vessels", "alias": "vs"},
            {"dataset": "voyages", "alias": "v"},
        ],
        "joins": [
            {"left": "vs", "right": "v", "join_type": "left", "left_field": "id", "right_field": "vessel_id"},
        ],
        "fields": [
            {"dataset": "vs", "field": "name", "label": "Vessel"},
            {"dataset": "v", "field": "id", "label": "Voyages", "agg": "count"},
        ],
        "group_by": [{"dataset": "vs", "field": "name"}],
        "order_by": [{"label": "Voyages", "direction": "desc"}],
    }


SYSTEM_REPORT_SPECS: dict[str, Any] = {
    "voyage_pnl": _spec_voyage_pnl,
    "bunker_consumption": _spec_bunker,
    "tce_analysis": _spec_tce,
    "fleet_performance": _spec_fleet,
    "counterparty_summary": _spec_counterparty,
    "age_days": _spec_age_days,
    "port_details": _spec_port_details,
    "cargo_emissions": _spec_emissions,
    "speed_comparison": _spec_speed,
    "sof_statement": _spec_sof_statement,
    "laytime_statement": _spec_laytime_statement,
    "hire_statement": _spec_hire_statement,
    "estimate_vs_actual": _spec_estimate_vs_actual,
    "fixture_recap": _spec_fixture_recap,
    "trial_balance": _spec_trial_balance,
    "commission_report": _spec_commission_report,
    "statement_of_account": _spec_statement_of_account,
    "port_cost_breakdown": _spec_port_cost_breakdown,
    "credit_exposure": _spec_credit_exposure,
    "cii_annual": _spec_cii_annual,
    "mrv_voyage": _spec_mrv_voyage,
    "eu_ets_cost": _spec_eu_ets_cost,
    "noon_report_summary": _spec_noon_report_summary,
    "bunker_reconciliation": _spec_bunker_reconciliation,
    "vessel_utilization": _spec_vessel_utilization,
}


def system_report_spec(report_type: str) -> dict | None:
    """Declarative-spec adapter for a system report (None if unknown)."""
    factory = SYSTEM_REPORT_SPECS.get(report_type)
    return factory() if factory else None


def spec_for_report(report: ReportDefinition) -> dict | None:
    """Best declarative spec for a report definition (v2 spec or preset adapter)."""
    if report.query_spec:
        return report.query_spec
    if report.data_source == "preset" and report.query:
        return system_report_spec(report.query)
    return None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def seed_system_reports(db: Session, tenant_id: uuid.UUID) -> list[ReportDefinition]:
    """Create system preset reports for a tenant (idempotent)."""
    existing = db.execute(
        select(ReportDefinition).where(
            ReportDefinition.tenant_id == tenant_id,
            ReportDefinition.is_system == True,
        )
    ).scalars().all()
    existing_types = {r.report_type for r in existing}

    created = []
    for spec in SYSTEM_REPORTS:
        if spec["report_type"] in existing_types:
            continue
        rd = ReportDefinition(
            tenant_id=tenant_id,
            is_system=True,
            created_by=None,
            **spec,
        )
        db.add(rd)
        created.append(rd)
    if created:
        db.flush()
    return created


def list_reports(db: Session, tenant_id: uuid.UUID) -> list[ReportDefinition]:
    return db.execute(
        select(ReportDefinition)
        .where(ReportDefinition.tenant_id == tenant_id)
        .order_by(ReportDefinition.report_name)
    ).scalars().all()


def get_report(db: Session, tenant_id: uuid.UUID, report_id: uuid.UUID) -> ReportDefinition | None:
    return db.execute(
        select(ReportDefinition).where(
            ReportDefinition.id == report_id,
            ReportDefinition.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()


def sync_spec_children(db: Session, report: ReportDefinition, spec: dict | None) -> None:
    """Mirror query_spec joins/fields into report_joins/report_fields rows."""
    db.execute(delete(ReportJoin).where(ReportJoin.report_definition_id == report.id))
    db.execute(delete(ReportField).where(ReportField.report_definition_id == report.id))
    if not spec:
        return

    # alias → ReportDataset row id
    ds_ids: dict[str, uuid.UUID] = {}
    for entry in spec.get("datasets") or []:
        if isinstance(entry, str):
            key, alias = entry, entry
        elif isinstance(entry, dict):
            key = entry.get("dataset") or entry.get("entity") or entry.get("name")
            alias = entry.get("alias") or key
        else:
            continue
        if not key:
            continue
        row = db.query(ReportDataset).filter(ReportDataset.entity == key).first()
        if row is None:
            row = db.query(ReportDataset).filter(ReportDataset.name == key).first()
        if row is not None:
            ds_ids[str(alias)] = row.id

    for j in spec.get("joins") or []:
        if not isinstance(j, dict):
            continue
        left = str(j.get("left") or j.get("left_dataset") or "")
        right = str(j.get("right") or j.get("right_dataset") or "")
        if left not in ds_ids or right not in ds_ids:
            continue
        db.add(
            ReportJoin(
                report_definition_id=report.id,
                left_dataset_id=ds_ids[left],
                right_dataset_id=ds_ids[right],
                join_type=j.get("join_type") or j.get("type") or "left",
                left_field=str(j.get("left_field") or ""),
                right_field=str(j.get("right_field") or ""),
            )
        )

    for i, f in enumerate(spec.get("fields") or []):
        if not isinstance(f, dict):
            continue
        ds_key = str(f.get("dataset") or f.get("entity") or "")
        if ds_key not in ds_ids:
            continue
        field_name = f.get("field") or f.get("field_name") or f.get("name") or ""
        label = f.get("label") or field_name or f"col_{i + 1}"
        db.add(
            ReportField(
                report_definition_id=report.id,
                dataset_id=ds_ids[ds_key],
                field_name=str(field_name or f"expr_{i + 1}"),
                label=str(label),
                expression=f.get("expression"),
                agg=f.get("agg"),
                format=f.get("format"),
                sort_order=int(f.get("sort_order") or 0),
                visible=bool(f.get("visible", True)),
            )
        )
    db.flush()


def create_report(db: Session, tenant_id: uuid.UUID, data: dict) -> ReportDefinition:
    query_spec = data.get("query_spec")
    if query_spec:
        data.setdefault("data_source", "spec")
        data["spec_version"] = "v2"
    rd = ReportDefinition(tenant_id=tenant_id, **data)
    db.add(rd)
    db.flush()
    if query_spec:
        sync_spec_children(db, rd, query_spec)
    return rd


def update_report(db: Session, report: ReportDefinition, data: dict) -> ReportDefinition:
    query_spec = data.get("query_spec")
    if query_spec:
        data.setdefault("data_source", "spec")
        data["spec_version"] = "v2"
    for k, v in data.items():
        setattr(report, k, v)
    report.updated_at = datetime.now(timezone.utc)
    db.flush()
    if "query_spec" in data:
        sync_spec_children(db, report, query_spec)
    return report


def delete_report(db: Session, report: ReportDefinition) -> None:
    if report.is_system:
        raise ValueError("Cannot delete system report")
    db.execute(delete(ReportJoin).where(ReportJoin.report_definition_id == report.id))
    db.execute(delete(ReportField).where(ReportField.report_definition_id == report.id))
    db.delete(report)
    db.flush()


# ---------------------------------------------------------------------------
# Preset executors (real domain tables; output keys match SYSTEM_REPORTS)
# ---------------------------------------------------------------------------


def _safe_decimal(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _fmt_date(val: Any) -> str:
    return str(val)[:10] if val else ""


def _naive(dt: Any) -> Any:
    """Drop tzinfo so SQLite (naive) and aware datetimes can be compared."""
    if not isinstance(dt, datetime):
        return dt
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _columns_for(query: str) -> list[dict[str, Any]]:
    """Display columns registered for a preset query key."""
    for spec in SYSTEM_REPORTS:
        if spec["query"] == query:
            return spec["columns"]
    return []


def _ets_price(db: Session, tenant_id: uuid.UUID) -> float:
    """EU allowance price: latest tenant/platform quote, else carbon_calculator default."""
    from app.models_domain import MarketQuote
    from app.services.carbon_calculator import EU_ETS_CO2_PRICE

    for symbol in ("EUA", "EU_ETS_PRICE", "EU_ETS", "ETS"):
        val = db.execute(
            select(MarketQuote.value)
            .where(
                MarketQuote.symbol == symbol,
                (MarketQuote.tenant_id == tenant_id) | (MarketQuote.tenant_id.is_(None)),
            )
            .order_by(MarketQuote.quote_date.desc())
            .limit(1)
        ).scalar()
        if val is not None:
            return _safe_decimal(val)
    return float(EU_ETS_CO2_PRICE)


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlmb / 2) ** 2
    return 2 * asin(sqrt(min(1.0, a))) * 3440.065  # earth radius in nm


def _voyage_distances(db: Session, tenant_id: uuid.UUID) -> dict[Any, float]:
    """Distance sailed per voyage: explicit meta value, else noon-report haversine sum."""
    out: dict[Any, float] = {}
    voyages = (
        db.execute(
            select(Voyage.id, Voyage.meta).where(Voyage.tenant_id == tenant_id, Voyage.status != "deleted")
        )
        .mappings()
        .all()
    )
    for v in voyages:
        meta = v["meta"] if isinstance(v["meta"], dict) else {}
        dist = meta.get("distance_nm") or meta.get("distance")
        if dist is not None:
            out[v["id"]] = _safe_decimal(dist)

    noon_rows = (
        db.execute(
            select(
                NoonReport.voyage_id,
                NoonReport.lat,
                NoonReport.lon,
                NoonReport.report_at,
            )
            .where(NoonReport.tenant_id == tenant_id)
            .order_by(NoonReport.voyage_id, NoonReport.report_at)
        )
        .mappings()
        .all()
    )
    legs: dict[Any, float] = {}
    prev: dict[Any, tuple[float, float]] = {}
    for r in noon_rows:
        if r["lat"] is None or r["lon"] is None:
            continue
        lat, lon = _safe_decimal(r["lat"]), _safe_decimal(r["lon"])
        vid = r["voyage_id"]
        if vid in prev:
            legs[vid] = legs.get(vid, 0.0) + _haversine_nm(prev[vid][0], prev[vid][1], lat, lon)
        prev[vid] = (lat, lon)
    for vid, nm in legs.items():
        out.setdefault(vid, round(nm, 1))
    return out


def _voyage_dwt_map(db: Session, tenant_id: uuid.UUID) -> dict[Any, float]:
    out: dict[Any, float] = {}
    for vid, dwt in db.execute(
        select(Voyage.id, Vessel.dwt)
        .outerjoin(Vessel, Voyage.vessel_id == Vessel.id)
        .where(Voyage.tenant_id == tenant_id, Voyage.status != "deleted")
    ).all():
        out[vid] = _safe_decimal(dwt)
    return out


def _revenue_costs(db: Session, tenant_id: uuid.UUID) -> tuple[dict, dict, dict]:
    """Per-voyage (freight_revenue, bunker_cost, port_cost) from real documents."""
    revenue: dict[Any, float] = {}
    for vid, amount in db.execute(
        select(Invoice.voyage_id, func.coalesce(func.sum(Invoice.amount), 0))
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.voyage_id.is_not(None),
            Invoice.invoice_type == "freight",
            Invoice.status != "deleted",
        )
        .group_by(Invoice.voyage_id)
    ).all():
        revenue[vid] = _safe_decimal(amount)

    bunker: dict[Any, float] = {}
    for vid, amount in db.execute(
        select(
            BunkerOrder.voyage_id,
            func.coalesce(
                func.sum(
                    func.coalesce(BunkerOrder.qty_delivered, BunkerOrder.qty_ordered)
                    * func.coalesce(BunkerOrder.unit_price, 0)
                ),
                0,
            ),
        )
        .where(
            BunkerOrder.tenant_id == tenant_id,
            BunkerOrder.voyage_id.is_not(None),
            BunkerOrder.status != "deleted",
        )
        .group_by(BunkerOrder.voyage_id)
    ).all():
        bunker[vid] = _safe_decimal(amount)

    port: dict[Any, float] = {}
    for vid, amount in db.execute(
        select(PortDisbursement.voyage_id, func.coalesce(func.sum(PortDisbursement.pda_amount), 0))
        .where(PortDisbursement.tenant_id == tenant_id, PortDisbursement.voyage_id.is_not(None))
        .group_by(PortDisbursement.voyage_id)
    ).all():
        port[vid] = _safe_decimal(amount)
    return revenue, bunker, port


def _voyage_ports(db: Session, tenant_id: uuid.UUID) -> dict[Any, dict[str, str]]:
    """Per-voyage first load / discharge port names."""
    out: dict[Any, dict[str, str]] = {}
    rows = (
        db.execute(
            select(PortCall.voyage_id, PortCall.purpose, Port.name, PortCall.seq)
            .outerjoin(Port, PortCall.port_id == Port.id)
            .where(PortCall.tenant_id == tenant_id)
            .order_by(PortCall.seq)
        )
        .mappings()
        .all()
    )
    for r in rows:
        if r["purpose"] not in ("load", "discharge"):
            continue
        slot = out.setdefault(r["voyage_id"], {})
        slot.setdefault(r["purpose"], r["name"] or "")
    return out


def _voyage_rows(db: Session, tenant_id: uuid.UUID, params: dict) -> list[dict[str, Any]]:
    """Shared voyage master rows (names via real joins)."""
    q = (
        select(
            Voyage.id,
            Voyage.voyage_no,
            Voyage.status,
            Voyage.started_at,
            Voyage.completed_at,
            Voyage.created_at,
            Vessel.name.label("vessel_name"),
            Charter.cargo_qty.label("cargo_qty"),
            Charter.freight_terms.label("freight_terms"),
            Counterparty.name.label("charterer"),
        )
        .outerjoin(Vessel, Voyage.vessel_id == Vessel.id)
        .outerjoin(Charter, Voyage.charter_id == Charter.id)
        .outerjoin(Counterparty, Charter.counterparty_id == Counterparty.id)
        .where(Voyage.tenant_id == tenant_id, Voyage.status != "deleted")
    )
    if params.get("date_from"):
        q = q.where(Voyage.created_at >= params["date_from"])
    if params.get("date_to"):
        q = q.where(Voyage.created_at <= params["date_to"])
    q = q.order_by(Voyage.created_at.desc()).limit(500)
    return [dict(r) for r in db.execute(q).mappings().all()]


def execute_voyage_pnl(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Voyage P&L: freight revenue - (bunker + port costs) per voyage."""
    revenue, bunker, port = _revenue_costs(db, tenant_id)
    ports = _voyage_ports(db, tenant_id)
    data = []
    for r in _voyage_rows(db, tenant_id, params):
        rev = revenue.get(r["id"], 0.0)
        if not rev and isinstance(r["freight_terms"], dict):
            rev = _safe_decimal(r["freight_terms"].get("freight_usd"))
        cost = bunker.get(r["id"], 0.0) + port.get(r["id"], 0.0)
        slot = ports.get(r["id"], {})
        data.append({
            "voyage_no": r["voyage_no"] or "",
            "vessel_name": r["vessel_name"] or "",
            "charterer": r["charterer"] or "",
            "load_port": slot.get("load", ""),
            "disch_port": slot.get("discharge", ""),
            "cargo_qty": _safe_decimal(r["cargo_qty"]),
            "freight_revenue": rev,
            "total_costs": cost,
            "net_pnl": rev - cost,
            "status": r["status"] or "",
        })
    return {"columns": _columns_for("voyage_pnl"), "rows": data, "total_rows": len(data)}


def execute_bunker_consumption(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    q = (
        select(
            BunkerOrder.grade,
            BunkerOrder.qty_ordered,
            BunkerOrder.qty_delivered,
            BunkerOrder.unit_price,
            BunkerOrder.bdn_date,
            Vessel.name.label("vessel_name"),
            Voyage.voyage_no.label("voyage_no"),
        )
        .outerjoin(Vessel, BunkerOrder.vessel_id == Vessel.id)
        .outerjoin(Voyage, BunkerOrder.voyage_id == Voyage.id)
        .where(BunkerOrder.tenant_id == tenant_id, BunkerOrder.status != "deleted")
        .order_by(BunkerOrder.bdn_date.desc().nullslast())
        .limit(500)
    )
    data = []
    for r in db.execute(q).mappings().all():
        qty = _safe_decimal(r["qty_delivered"] if r["qty_delivered"] is not None else r["qty_ordered"])
        price = _safe_decimal(r["unit_price"])
        data.append({
            "vessel_name": r["vessel_name"] or "",
            "voyage_no": r["voyage_no"] or "",
            "fuel_type": r["grade"] or "",
            "quantity_mt": qty,
            "unit_cost": price,
            "total_cost": qty * price,
            "order_date": _fmt_date(r["bdn_date"]),
        })
    return {"columns": _columns_for("bunker_consumption"), "rows": data, "total_rows": len(data)}


def execute_tce_analysis(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    revenue, bunker, port = _revenue_costs(db, tenant_id)
    now = _now_naive()
    data = []
    for r in _voyage_rows(db, tenant_id, params):
        rev = revenue.get(r["id"], 0.0)
        cost = bunker.get(r["id"], 0.0) + port.get(r["id"], 0.0)
        days = 0
        if r["started_at"]:
            end = _naive(r["completed_at"]) or now
            days = max(0, (end - _naive(r["started_at"])).days)
        data.append({
            "voyage_no": r["voyage_no"] or "",
            "vessel_name": r["vessel_name"] or "",
            "voyage_days": days,
            "freight_revenue": rev,
            "bunker_cost": bunker.get(r["id"], 0.0),
            "port_cost": port.get(r["id"], 0.0),
            "tce": (rev - cost) / max(1, days),
        })
    return {"columns": _columns_for("tce_analysis"), "rows": data, "total_rows": len(data)}


def execute_fleet_performance(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    revenue, bunker, port = _revenue_costs(db, tenant_id)
    voyages = _voyage_rows(db, tenant_id, {})
    co2: dict[Any, float] = {}
    for vid, total in db.execute(
        select(EmissionRecord.voyage_id, func.coalesce(func.sum(EmissionRecord.co2_mt), 0))
        .where(EmissionRecord.tenant_id == tenant_id, EmissionRecord.voyage_id.is_not(None))
        .group_by(EmissionRecord.voyage_id)
    ).all():
        co2[vid] = _safe_decimal(total)

    per_vessel: dict[str, dict[str, Any]] = {}
    for r in voyages:
        slot = per_vessel.setdefault(
            r["vessel_name"] or "Unknown",
            {"voyage_count": 0, "total_revenue": 0.0, "total_bunker_cost": 0.0, "total_co2": 0.0},
        )
        slot["voyage_count"] += 1
        slot["total_revenue"] += revenue.get(r["id"], 0.0)
        slot["total_bunker_cost"] += bunker.get(r["id"], 0.0)
        slot["total_co2"] += co2.get(r["id"], 0.0)
    data = []
    for name, slot in per_vessel.items():
        rev = slot["total_revenue"]
        cost = slot["total_bunker_cost"] + 0.0
        data.append({
            "vessel_name": name,
            "voyage_count": slot["voyage_count"],
            "total_revenue": rev,
            "total_bunker_cost": slot["total_bunker_cost"],
            "avg_tce": (rev - cost) / max(1, slot["voyage_count"] * 30),
            "total_co2": slot["total_co2"],
        })
    data.sort(key=lambda d: -d["total_revenue"])
    return {"columns": _columns_for("fleet_performance"), "rows": data, "total_rows": len(data)}


def execute_counterparty_summary(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    inv_stats: dict[Any, dict[str, Any]] = {}
    for cid, total, outstanding, last in db.execute(
        select(
            Invoice.counterparty_id,
            func.coalesce(func.sum(Invoice.amount), 0),
            func.coalesce(func.sum(Invoice.amount - func.coalesce(Invoice.paid_amount, 0)), 0),
            func.max(Invoice.issued_at),
        )
        .where(Invoice.tenant_id == tenant_id, Invoice.counterparty_id.is_not(None))
        .group_by(Invoice.counterparty_id)
    ).all():
        inv_stats[cid] = {
            "total_revenue": _safe_decimal(total),
            "outstanding": _safe_decimal(outstanding),
            "last_activity": _fmt_date(last),
        }

    voyage_counts: dict[Any, int] = {}
    for cid, cnt in db.execute(
        select(Charter.counterparty_id, func.count(func.distinct(Voyage.id)))
        .outerjoin(Voyage, Voyage.charter_id == Charter.id)
        .where(Charter.tenant_id == tenant_id, Charter.counterparty_id.is_not(None))
        .group_by(Charter.counterparty_id)
    ).all():
        voyage_counts[cid] = int(cnt or 0)

    rows = (
        db.execute(
            select(Counterparty)
            .where(
                Counterparty.tenant_id == tenant_id,
                Counterparty.deleted_at.is_(None),
            )
            .order_by(Counterparty.name)
            .limit(200)
        )
        .scalars()
        .all()
    )
    data = []
    for cp in rows:
        st = inv_stats.get(cp.id, {})
        data.append({
            "party_name": cp.name or "Unknown",
            "voyage_count": voyage_counts.get(cp.id, 0),
            "total_revenue": st.get("total_revenue", 0.0),
            "outstanding": st.get("outstanding", 0.0),
            "last_activity": st.get("last_activity", ""),
        })
    return {"columns": _columns_for("counterparty_summary"), "rows": data, "total_rows": len(data)}


def execute_age_days(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    q = (
        select(Invoice, Counterparty.name.label("party_name"))
        .outerjoin(Counterparty, Invoice.counterparty_id == Counterparty.id)
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.status != "paid",
            Invoice.status != "deleted",
        )
        .order_by(Invoice.issued_at.asc().nullslast())
        .limit(500)
    )
    now = _now_naive()
    data = []
    for row in db.execute(q):
        inv = row[0]
        party_name = row[1]
        amount = _safe_decimal(inv.base_amount if inv.base_amount is not None else inv.amount)
        outstanding = amount - _safe_decimal(inv.paid_amount)
        ref = _naive(inv.issued_at) or _naive(inv.due_date)
        days = 0
        if ref is not None:
            ref_dt = datetime(ref.year, ref.month, ref.day) if not isinstance(ref, datetime) else ref
            days = max(0, (now - ref_dt).days)
        if days <= 30:
            bucket = "0-30"
        elif days <= 60:
            bucket = "31-60"
        elif days <= 90:
            bucket = "61-90"
        else:
            bucket = "90+"
        overdue = 0
        if inv.due_date is not None:
            d = inv.due_date
            due_dt = datetime(d.year, d.month, d.day) if not isinstance(d, datetime) else _naive(d)
            overdue = max(0, (now - due_dt).days)
        data.append({
            "invoice_no": inv.invoice_no or "",
            "party_name": party_name or "",
            "invoice_type": inv.invoice_type or "",
            "amount": amount,
            "outstanding": outstanding,
            "days_overdue": overdue,
            "aging_bucket": bucket,
        })
    return {"columns": _columns_for("age_days"), "rows": data, "total_rows": len(data)}


def execute_port_details(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    cost_by_port: dict[Any, float] = {}
    for port_id, total in db.execute(
        select(PortCall.port_id, func.coalesce(func.sum(PortDisbursement.pda_amount), 0))
        .join(PortDisbursement, PortDisbursement.port_call_id == PortCall.id)
        .where(PortCall.tenant_id == tenant_id, PortCall.port_id.is_not(None))
        .group_by(PortCall.port_id)
    ).all():
        cost_by_port[port_id] = _safe_decimal(total)

    rows = (
        db.execute(
            select(Port.name.label("port_name"), PortCall.eta, PortCall.etd, PortCall.ata, PortCall.atd, PortCall.port_id)
            .outerjoin(Port, PortCall.port_id == Port.id)
            .where(PortCall.tenant_id == tenant_id)
            .order_by(PortCall.eta.desc().nullslast())
            .limit(1000)
        )
        .mappings()
        .all()
    )
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        name = r["port_name"] or "Unknown"
        slot = agg.setdefault(
            name,
            {"call_count": 0, "stay_hours": [], "last_call": None, "port_id": r["port_id"]},
        )
        slot["call_count"] += 1
        arr = r["ata"] or r["eta"]
        dep = r["atd"] or r["etd"]
        if arr is not None and dep is not None:
            slot["stay_hours"].append((dep - arr).total_seconds() / 3600.0)
        stamp = arr or dep
        if stamp is not None and (slot["last_call"] is None or stamp > slot["last_call"]):
            slot["last_call"] = stamp
    data = []
    for name, slot in agg.items():
        hours = slot["stay_hours"]
        data.append({
            "port_name": name,
            "call_count": slot["call_count"],
            "avg_stay_hours": round(sum(hours) / len(hours), 1) if hours else 0.0,
            "total_port_cost": cost_by_port.get(slot["port_id"], 0.0),
            "last_call": _fmt_date(slot["last_call"]),
        })
    data.sort(key=lambda d: -d["call_count"])
    return {"columns": _columns_for("port_details"), "rows": data, "total_rows": len(data)}


def execute_cargo_emissions(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    co2_by_voyage: dict[Any, float] = {}
    for vid, total in db.execute(
        select(EmissionRecord.voyage_id, func.coalesce(func.sum(EmissionRecord.co2_mt), 0))
        .where(EmissionRecord.tenant_id == tenant_id, EmissionRecord.voyage_id.is_not(None))
        .group_by(EmissionRecord.voyage_id)
    ).all():
        co2_by_voyage[vid] = _safe_decimal(total)

    bunker_mt: dict[Any, float] = {}
    for vid, total in db.execute(
        select(
            BunkerOrder.voyage_id,
            func.coalesce(
                func.sum(func.coalesce(BunkerOrder.qty_delivered, BunkerOrder.qty_ordered)), 0
            ),
        )
        .where(
            BunkerOrder.tenant_id == tenant_id,
            BunkerOrder.voyage_id.is_not(None),
            BunkerOrder.status != "deleted",
        )
        .group_by(BunkerOrder.voyage_id)
    ).all():
        bunker_mt[vid] = _safe_decimal(total)

    ets_price = _ets_price(db, tenant_id)
    data = []
    for r in _voyage_rows(db, tenant_id, params):
        cargo = _safe_decimal(r["cargo_qty"]) or 1.0
        co2 = co2_by_voyage.get(r["id"], 0.0) or bunker_mt.get(r["id"], 0.0) * 3.114
        data.append({
            "voyage_no": r["voyage_no"] or "",
            "vessel_name": r["vessel_name"] or "",
            "cargo_qty": cargo,
            "co2_total": co2,
            "co2_per_cargo": co2 / cargo,
            "eu_ets_cost": co2 * ets_price,
        })
    return {"columns": _columns_for("cargo_emissions"), "rows": data, "total_rows": len(data)}


def execute_speed_comparison(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Observed vs design speed per vessel.

    Observed speed and consumption come from real noon reports and bunker
    deliveries; design values come from vessel master data. Nothing is
    synthesised — missing observations show as 0 / master-data fallbacks.
    """
    counts: dict[Any, int] = {}
    for vid, cnt in db.execute(
        select(Voyage.vessel_id, func.count(Voyage.id))
        .where(Voyage.tenant_id == tenant_id, Voyage.vessel_id.is_not(None), Voyage.status != "deleted")
        .group_by(Voyage.vessel_id)
    ).all():
        counts[vid] = int(cnt or 0)

    # observed speeds: average of noon speeds > 0 per vessel
    speed_sums: dict[Any, list[float]] = {}
    for vessel_id, speed in db.execute(
        select(Voyage.vessel_id, NoonReport.speed)
        .join(NoonReport, NoonReport.voyage_id == Voyage.id)
        .where(
            Voyage.tenant_id == tenant_id,
            Voyage.vessel_id.is_not(None),
            NoonReport.speed.is_not(None),
            NoonReport.speed > 0,
        )
    ).all():
        speed_sums.setdefault(vessel_id, []).append(_safe_decimal(speed))

    # observed consumption: bunker MT delivered per voyage-day per vessel
    bunker_by_vessel: dict[Any, float] = {}
    for vessel_id, qty in db.execute(
        select(
            BunkerOrder.vessel_id,
            func.coalesce(func.sum(func.coalesce(BunkerOrder.qty_delivered, BunkerOrder.qty_ordered)), 0),
        )
        .where(
            BunkerOrder.tenant_id == tenant_id,
            BunkerOrder.vessel_id.is_not(None),
            BunkerOrder.status != "deleted",
        )
        .group_by(BunkerOrder.vessel_id)
    ).all():
        bunker_by_vessel[vessel_id] = _safe_decimal(qty)

    voyage_days_by_vessel: dict[Any, float] = {}
    now = _now_naive()
    for vessel_id, started, completed in db.execute(
        select(Voyage.vessel_id, Voyage.started_at, Voyage.completed_at).where(
            Voyage.tenant_id == tenant_id,
            Voyage.vessel_id.is_not(None),
            Voyage.status != "deleted",
            Voyage.started_at.is_not(None),
        )
    ).all():
        if completed is not None:  # completed voyages use actual duration
            days = (_naive(completed) - _naive(started)).total_seconds() / 86400.0
        else:
            days = max(0.0, (now - _naive(started)).total_seconds() / 86400.0)
        voyage_days_by_vessel[vessel_id] = voyage_days_by_vessel.get(vessel_id, 0.0) + max(days, 0.0)

    vessels = (
        db.execute(
            select(Vessel).where(Vessel.tenant_id == tenant_id, Vessel.deleted_at.is_(None))
            .order_by(Vessel.name)
            .limit(200)
        )
        .scalars()
        .all()
    )
    data = []
    for v in vessels:
        speeds = speed_sums.get(v.id, [])
        days = voyage_days_by_vessel.get(v.id, 0.0)
        observed_cons = bunker_by_vessel.get(v.id, 0.0) / days if days > 0 else 0.0
        data.append({
            "vessel_name": v.name or "Unknown",
            "voyage_count": counts.get(v.id, 0),
            "avg_noon_speed": round(sum(speeds) / len(speeds), 2) if speeds else 0.0,
            "design_speed": _safe_decimal(v.speed_knots),
            "avg_consumption": round(observed_cons, 2) if observed_cons else _safe_decimal(v.consumption_sea),
        })
    return {"columns": _columns_for("speed_comparison"), "rows": data, "total_rows": len(data)}


# ---------------------------------------------------------------------------
# Phase 9 — industry-standard preset reports
# ---------------------------------------------------------------------------


def execute_sof_statement(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Statement of Facts: events per port call with duration to previous event."""
    rows = (
        db.execute(
            select(
                SofEvent.id,
                SofEvent.port_call_id,
                SofEvent.event_code,
                SofEvent.event_at,
                SofEvent.remarks,
                PortCall.port_id,
                Voyage.voyage_no.label("voyage_no"),
                Vessel.name.label("vessel_name"),
                Port.name.label("port_name"),
            )
            .outerjoin(PortCall, SofEvent.port_call_id == PortCall.id)
            .outerjoin(Voyage, PortCall.voyage_id == Voyage.id)
            .outerjoin(Vessel, Voyage.vessel_id == Vessel.id)
            .outerjoin(Port, PortCall.port_id == Port.id)
            .where(SofEvent.tenant_id == tenant_id)
            .order_by(SofEvent.port_call_id, SofEvent.event_at)
            .limit(1000)
        )
        .mappings()
        .all()
    )
    prev_at: dict[Any, Any] = {}
    data = []
    for r in rows:
        event_at = r["event_at"]
        duration = 0.0
        if r["port_call_id"] in prev_at and event_at is not None and prev_at[r["port_call_id"]] is not None:
            delta = _naive(event_at) - _naive(prev_at[r["port_call_id"]])
            duration = round(delta.total_seconds() / 3600.0, 2)
        prev_at[r["port_call_id"]] = event_at
        data.append({
            "vessel_name": r["vessel_name"] or "",
            "voyage_no": r["voyage_no"] or "",
            "port_name": r["port_name"] or "",
            "event_code": r["event_code"] or "",
            "event_at": _fmt_date(event_at),
            "duration_hours": duration,
            "remarks": r["remarks"] or "",
        })
    return {"columns": _columns_for("sof_statement"), "rows": data, "total_rows": len(data)}


def execute_laytime_statement(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Laytime / demurrage statement from laytime calculation inputs & results."""
    rows = (
        db.execute(
            select(
                LaytimeCalc.inputs,
                LaytimeCalc.results,
                LaytimeCalc.status,
                Voyage.voyage_no.label("voyage_no"),
                Port.name.label("port_name"),
            )
            .outerjoin(Voyage, LaytimeCalc.voyage_id == Voyage.id)
            .outerjoin(PortCall, LaytimeCalc.port_call_id == PortCall.id)
            .outerjoin(Port, PortCall.port_id == Port.id)
            .where(LaytimeCalc.tenant_id == tenant_id)
            .order_by(LaytimeCalc.finalized_at.desc().nullslast())
            .limit(500)
        )
        .mappings()
        .all()
    )
    data = []
    for r in rows:
        inputs = r["inputs"] if isinstance(r["inputs"], dict) else {}
        results = r["results"] if isinstance(r["results"], dict) else {}
        allowed_h = _safe_decimal(inputs.get("allowed_hours"))
        used_h = _safe_decimal(results.get("used_hours"))
        dem_rate = _safe_decimal(inputs.get("demurrage_rate"))
        despatch_rate = _safe_decimal(inputs.get("despatch_rate"))
        data.append({
            "voyage_no": r["voyage_no"] or "",
            "port_name": r["port_name"] or "",
            "allowed_days": round(allowed_h / 24.0, 3),
            "used_days": round(used_h / 24.0, 3),
            "demurrage_rate": dem_rate,
            "despatch_rate": despatch_rate,
            "demurrage_amount": _safe_decimal(results.get("demurrage_usd")),
            "despatch_amount": _safe_decimal(results.get("despatch_usd")),
            "status": r["status"] or "",
        })
    return {"columns": _columns_for("laytime_statement"), "rows": data, "total_rows": len(data)}


def execute_hire_statement(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """TC hire statements: contract, period, hire rate, off-hire days, net hire."""
    rows = (
        db.execute(
            select(
                HireStatement,
                TimeCharterContract.hire_rate.label("hire_rate"),
                Charter.charter_no.label("contract_no"),
                Vessel.name.label("vessel_name"),
            )
            .outerjoin(TimeCharterContract, HireStatement.contract_id == TimeCharterContract.id)
            .outerjoin(Charter, TimeCharterContract.charter_id == Charter.id)
            .outerjoin(Vessel, TimeCharterContract.vessel_id == Vessel.id)
            .where(HireStatement.tenant_id == tenant_id)
            .order_by(HireStatement.period_start.desc())
            .limit(500)
        )
        .all()
    )
    data = []
    for row in rows:
        hs, hire_rate, contract_no, vessel_name = row
        data.append({
            "statement_no": hs.statement_number or "",
            "contract_no": contract_no or "",
            "vessel_name": vessel_name or "",
            "period_start": _fmt_date(hs.period_start),
            "period_end": _fmt_date(hs.period_end),
            "hire_rate": _safe_decimal(hire_rate),
            "hire_days": _safe_decimal(hs.hire_days),
            "off_hire_days": _safe_decimal(hs.off_hire_days),
            "net_hire": _safe_decimal(hs.net_hire),
            "status": hs.status or "",
        })
    return {"columns": _columns_for("hire_statement"), "rows": data, "total_rows": len(data)}


def execute_estimate_vs_actual(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Estimate revenue/cost vs realised voyage P&L with variance."""
    revenue, bunker, port = _revenue_costs(db, tenant_id)
    # voyage → estimate via charter.estimate_id
    voy_rows = _voyage_rows(db, tenant_id, params)
    est_by_id: dict[Any, dict] = {}
    for e in (
        db.execute(select(Estimate).where(Estimate.tenant_id == tenant_id)).scalars().all()
    ):
        results = e.results if isinstance(e.results, dict) else {}
        est_by_id[e.id] = {
            "title": e.title or "",
            "est_revenue": _safe_decimal(results.get("total_revenue") or results.get("net_freight")),
            "est_cost": _safe_decimal(results.get("voyage_cost")),
        }

    charter_est: dict[Any, Any] = {}
    for cid, eid in db.execute(
        select(Charter.id, Charter.estimate_id).where(
            Charter.tenant_id == tenant_id, Charter.estimate_id.is_not(None)
        )
    ).all():
        charter_est[cid] = eid

    # voyage → charter mapping (from _voyage_rows we only have names; re-query ids)
    voy_charter: dict[Any, Any] = {}
    for vid, cid in db.execute(
        select(Voyage.id, Voyage.charter_id).where(Voyage.tenant_id == tenant_id)
    ).all():
        voy_charter[vid] = cid

    per_est: dict[Any, dict] = {}
    for r in voy_rows:
        eid = charter_est.get(voy_charter.get(r["id"]))
        if eid is None or eid not in est_by_id:
            continue
        slot = per_est.setdefault(
            eid,
            {
                "voyage_nos": [],
                "vessel_name": r["vessel_name"] or "",
                "act_revenue": 0.0,
                "act_cost": 0.0,
            },
        )
        slot["voyage_nos"].append(r["voyage_no"] or "")
        slot["act_revenue"] += revenue.get(r["id"], 0.0)
        slot["act_cost"] += bunker.get(r["id"], 0.0) + port.get(r["id"], 0.0)

    data = []
    for eid, est in est_by_id.items():
        slot = per_est.get(eid)
        act_rev = slot["act_revenue"] if slot else 0.0
        act_cost = slot["act_cost"] if slot else 0.0
        est_rev, est_cost = est["est_revenue"], est["est_cost"]
        data.append({
            "estimate_title": est["title"],
            "voyage_no": ", ".join(slot["voyage_nos"]) if slot else "",
            "vessel_name": slot["vessel_name"] if slot else "",
            "est_revenue": est_rev,
            "act_revenue": act_rev,
            "est_cost": est_cost,
            "act_cost": act_cost,
            "revenue_variance": act_rev - est_rev,
            "cost_variance": act_cost - est_cost,
            "net_variance": (act_rev - act_cost) - (est_rev - est_cost),
        })
    data.sort(key=lambda d: d["estimate_title"])
    return {"columns": _columns_for("estimate_vs_actual"), "rows": data, "total_rows": len(data)}


def execute_fixture_recap(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Fixture recap: vessel, cargo, route, freight rate, laycan, CP form."""
    # first load / discharge port per charter (via its voyages' port calls)
    charter_ports: dict[Any, dict[str, str]] = {}
    port_rows = (
        db.execute(
            select(Voyage.charter_id, PortCall.purpose, Port.name)
            .join(PortCall, PortCall.voyage_id == Voyage.id)
            .outerjoin(Port, PortCall.port_id == Port.id)
            .where(Voyage.tenant_id == tenant_id, Voyage.charter_id.is_not(None))
            .order_by(PortCall.seq)
        )
        .all()
    )
    for charter_id, purpose, name in port_rows:
        if purpose not in ("load", "discharge"):
            continue
        slot = charter_ports.setdefault(charter_id, {})
        slot.setdefault(purpose, name or "")

    # first voyage cargo text per charter
    charter_cargo: dict[Any, str] = {}
    for cid, cargo in db.execute(
        select(Voyage.charter_id, Voyage.cargo)
        .where(Voyage.tenant_id == tenant_id, Voyage.charter_id.is_not(None), Voyage.cargo.is_not(None))
        .order_by(Voyage.created_at)
    ).all():
        charter_cargo.setdefault(cid, cargo or "")

    rows = (
        db.execute(
            select(Charter, Vessel.name.label("vessel_name"), Counterparty.name.label("charterer"))
            .outerjoin(Vessel, Charter.vessel_id == Vessel.id)
            .outerjoin(Counterparty, Charter.counterparty_id == Counterparty.id)
            .where(Charter.tenant_id == tenant_id, Charter.status != "deleted")
            .order_by(Charter.created_at.desc())
            .limit(500)
        )
        .all()
    )
    data = []
    for ch, vessel_name, charterer in rows:
        slot = charter_ports.get(ch.id, {})
        cargo = charter_cargo.get(ch.id) or ""
        if not cargo and ch.cargo_qty:
            cargo = f"{_safe_decimal(ch.cargo_qty):g} MT"
        data.append({
            "fixture_date": _fmt_date(ch.created_at),
            "charter_no": ch.charter_no or "",
            "vessel_name": vessel_name or "",
            "charterer": charterer or "",
            "cargo": cargo,
            "load_port": slot.get("load", ""),
            "disch_port": slot.get("discharge", ""),
            "freight_rate": _safe_decimal(ch.freight_rate),
            "laycan_from": _fmt_date(ch.laycan_from),
            "laycan_to": _fmt_date(ch.laycan_to),
            "cp_form": ch.cp_form or "",
        })
    return {"columns": _columns_for("fixture_recap"), "rows": data, "total_rows": len(data)}


def execute_trial_balance(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """GL trial balance: posted journal entries aggregated per account."""
    totals: dict[str, dict[str, float]] = {}
    for period, entries, status in db.execute(
        select(PeriodJournal.period, PeriodJournal.entries, PeriodJournal.status).where(
            PeriodJournal.tenant_id == tenant_id, PeriodJournal.status == "posted"
        )
    ).all():
        for e in entries or []:
            if not isinstance(e, dict):
                continue
            acct = str(e.get("account") or e.get("account_code") or "").strip()
            if not acct:
                continue
            slot = totals.setdefault(acct, {"debit": 0.0, "credit": 0.0})
            slot["debit"] += _safe_decimal(e.get("debit"))
            slot["credit"] += _safe_decimal(e.get("credit"))

    accounts = {
        a.account_code: a
        for a in db.execute(
            select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id)
        ).scalars().all()
    }
    codes = sorted(set(totals) | set(accounts))
    data = []
    for code in codes:
        acct = accounts.get(code)
        slot = totals.get(code, {"debit": 0.0, "credit": 0.0})
        if slot["debit"] == 0 and slot["credit"] == 0 and acct is None:
            continue
        data.append({
            "account_code": code,
            "account_name": (acct.account_name if acct else "") or "",
            "account_type": (acct.account_type if acct else "") or "",
            "debit_total": round(slot["debit"], 2),
            "credit_total": round(slot["credit"], 2),
            "balance": round(slot["debit"] - slot["credit"], 2),
        })
    return {"columns": _columns_for("trial_balance"), "rows": data, "total_rows": len(data)}


def execute_commission_report(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Brokerage / address commission breakdown per invoice."""
    from app.services.commission import commission_plan

    q = (
        select(Invoice, Counterparty.name.label("party_name"))
        .outerjoin(Counterparty, Invoice.counterparty_id == Counterparty.id)
        .where(Invoice.tenant_id == tenant_id, Invoice.status != "deleted")
        .order_by(Invoice.issued_at.desc().nullslast())
        .limit(500)
    )
    data = []
    for inv, party_name in db.execute(q).all():
        if inv.invoice_type == "broker_commission":
            data.append({
                "invoice_no": inv.invoice_no or "",
                "broker": party_name or "",
                "commission_type": "brokerage",
                "rate_pct": 0.0,
                "base_amount": 0.0,
                "amount": _safe_decimal(inv.amount),
                "currency": inv.currency or "USD",
            })
            continue
        plan = commission_plan(db, inv)
        if plan["brokerage_amount"] > 0:
            data.append({
                "invoice_no": inv.invoice_no or "",
                "broker": party_name or "",
                "commission_type": "brokerage",
                "rate_pct": plan["brokerage_pct"],
                "base_amount": plan["base_amount"],
                "amount": plan["brokerage_amount"],
                "currency": inv.currency or "USD",
            })
        if plan["address_commission_amount"] > 0:
            data.append({
                "invoice_no": inv.invoice_no or "",
                "broker": party_name or "",
                "commission_type": "address",
                "rate_pct": plan["address_comm_pct"],
                "base_amount": plan["base_amount"],
                "amount": plan["address_commission_amount"],
                "currency": inv.currency or "USD",
            })
    return {"columns": _columns_for("commission_report"), "rows": data, "total_rows": len(data)}


def execute_statement_of_account(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Counterparty statement: invoice, date, amount, paid, outstanding."""
    paid_by_inv: dict[Any, float] = {}
    for iid, total in db.execute(
        select(Payment.invoice_id, func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.tenant_id == tenant_id)
        .group_by(Payment.invoice_id)
    ).all():
        paid_by_inv[iid] = _safe_decimal(total)

    rows = (
        db.execute(
            select(Invoice, Counterparty.name.label("party_name"))
            .outerjoin(Counterparty, Invoice.counterparty_id == Counterparty.id)
            .where(Invoice.tenant_id == tenant_id, Invoice.status != "deleted")
            .order_by(Counterparty.name, Invoice.issued_at.asc().nullslast())
            .limit(1000)
        )
        .all()
    )
    data = []
    for inv, party_name in rows:
        amount = _safe_decimal(inv.base_amount if inv.base_amount is not None else inv.amount)
        paid = paid_by_inv.get(inv.id, _safe_decimal(inv.paid_amount))
        data.append({
            "party_name": party_name or "",
            "invoice_no": inv.invoice_no or "",
            "invoice_date": _fmt_date(inv.issued_at),
            "invoice_type": inv.invoice_type or "",
            "amount": amount,
            "paid": paid,
            "outstanding": round(amount - paid, 2),
            "status": inv.status or "",
        })
    return {"columns": _columns_for("statement_of_account"), "rows": data, "total_rows": len(data)}


def execute_port_cost_breakdown(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """PDA vs FDA per port call with variance."""
    rows = (
        db.execute(
            select(
                PortDisbursement,
                Port.name.label("port_name"),
                Voyage.voyage_no.label("voyage_no"),
            )
            .outerjoin(PortCall, PortDisbursement.port_call_id == PortCall.id)
            .outerjoin(Port, PortCall.port_id == Port.id)
            .outerjoin(Voyage, PortDisbursement.voyage_id == Voyage.id)
            .where(PortDisbursement.tenant_id == tenant_id)
            .limit(500)
        )
        .all()
    )
    data = []
    for pd, port_name, voyage_no in rows:
        pda = _safe_decimal(pd.pda_amount)
        fda = _safe_decimal(pd.fda_amount)
        variance = _safe_decimal(pd.variance) if pd.variance is not None else fda - pda
        data.append({
            "port_name": port_name or "",
            "voyage_no": voyage_no or "",
            "pda_amount": pda,
            "fda_amount": fda,
            "variance": variance,
            "variance_pct": round(variance / pda * 100, 2) if pda else 0.0,
            "status": pd.status or "",
        })
    return {"columns": _columns_for("port_cost_breakdown"), "rows": data, "total_rows": len(data)}


def execute_credit_exposure(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Open receivable exposure vs credit limit per counterparty."""
    from app.models_finance_ext import RiskLimit

    open_statuses = ("issued", "partially_paid", "overdue")
    stats: dict[Any, dict[str, Any]] = {}
    for cid, cnt, exposure in db.execute(
        select(
            Invoice.counterparty_id,
            func.count(Invoice.id),
            func.coalesce(
                func.sum(
                    Invoice.amount
                    + func.coalesce(Invoice.tax_amount, 0)
                    - func.coalesce(Invoice.paid_amount, 0)
                ),
                0,
            ),
        )
        .where(
            Invoice.tenant_id == tenant_id,
            Invoice.counterparty_id.is_not(None),
            Invoice.status.in_(open_statuses),
        )
        .group_by(Invoice.counterparty_id)
    ).all():
        stats[cid] = {"open_invoices": int(cnt or 0), "total_exposure": _safe_decimal(exposure)}

    limits: dict[str, float] = {}
    for scope, amount in db.execute(
        select(RiskLimit.scope, RiskLimit.amount).where(
            RiskLimit.tenant_id == tenant_id,
            RiskLimit.limit_type == "credit",
            RiskLimit.active.is_(True),
        )
    ).all():
        limits[str(scope)] = _safe_decimal(amount)

    rows = (
        db.execute(
            select(Counterparty)
            .where(Counterparty.tenant_id == tenant_id, Counterparty.deleted_at.is_(None))
            .order_by(Counterparty.name)
            .limit(200)
        )
        .scalars()
        .all()
    )
    data = []
    for cp in rows:
        slot = stats.get(cp.id, {"open_invoices": 0, "total_exposure": 0.0})
        limit = limits.get(f"counterparty:{cp.id}")
        exposure = slot["total_exposure"]
        data.append({
            "party_name": cp.name or "Unknown",
            "open_invoices": slot["open_invoices"],
            "total_exposure": round(exposure, 2),
            "credit_limit": limit,
            "utilization_pct": round(exposure / limit * 100, 1) if limit else 0.0,
            "breach": bool(limit is not None and exposure > limit),
        })
    return {"columns": _columns_for("credit_exposure"), "rows": data, "total_rows": len(data)}


def _period_year(period: str | None, default: int | None = None) -> int:
    if period:
        digits = "".join(ch for ch in str(period)[:4] if ch.isdigit())
        if len(digits) == 4:
            return int(digits)
    return default or datetime.now(timezone.utc).year


def execute_cii_annual(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Annual operational CII per vessel: AER, required CII, A-E rating."""
    from app.services.cii import required_cii

    distances = _voyage_distances(db, tenant_id)
    # per vessel: rows of (period, co2, voyage_id)
    agg: dict[tuple[Any, str], dict[str, float]] = {}
    for rec in (
        db.execute(
            select(EmissionRecord).where(EmissionRecord.tenant_id == tenant_id)
        ).scalars().all()
    ):
        period = rec.period or ""
        key = (rec.vessel_id, period)
        slot = agg.setdefault(key, {"co2": 0.0, "distance": 0.0})
        slot["co2"] += _safe_decimal(rec.co2_mt)
        if rec.voyage_id is not None:
            slot["distance"] += distances.get(rec.voyage_id, 0.0)

    vessel_map = {
        v.id: v
        for v in db.execute(
            select(Vessel).where(Vessel.tenant_id == tenant_id, Vessel.deleted_at.is_(None))
        ).scalars().all()
    }
    data = []
    for (vessel_id, period), slot in sorted(agg.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        v = vessel_map.get(vessel_id)
        dwt = _safe_decimal(v.dwt) if v else 0.0
        co2 = slot["co2"]
        dist = slot["distance"]
        aer = co2 * 1_000_000 / (dwt * dist) if dwt > 0 and dist > 0 else 0.0
        req = required_cii(dwt, _period_year(period), v.vessel_type if v else None) if dwt > 0 else 0.0
        rating = ""
        if aer > 0 and req > 0:
            # rating bands relative to required CII (MEPC.338(76) vectors, generic)
            ratio = aer / req
            rating = "A" if ratio <= 0.6 else "B" if ratio <= 0.8 else "C" if ratio <= 1.0 else "D" if ratio <= 1.2 else "E"
        data.append({
            "vessel_name": (v.name if v else "") or "Unknown",
            "period": period,
            "distance_nm": round(dist, 1),
            "co2_mt": round(co2, 3),
            "aer": round(aer, 4),
            "required_cii": round(req, 4),
            "cii_rating": rating,
        })
    return {"columns": _columns_for("cii_annual"), "rows": data, "total_rows": len(data)}


def execute_mrv_voyage(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """EU MRV per-voyage: fuel, CO2, transport work, AER."""
    distances = _voyage_distances(db, tenant_id)
    dwt_by_voyage = _voyage_dwt_map(db, tenant_id)

    agg: dict[Any, dict[str, float]] = {}
    for rec in (
        db.execute(
            select(EmissionRecord).where(
                EmissionRecord.tenant_id == tenant_id, EmissionRecord.voyage_id.is_not(None)
            )
        ).scalars().all()
    ):
        slot = agg.setdefault(rec.voyage_id, {"fo": 0.0, "do": 0.0, "co2": 0.0})
        slot["fo"] += _safe_decimal(rec.fo_mt)
        slot["do"] += _safe_decimal(rec.do_mt)
        slot["co2"] += _safe_decimal(rec.co2_mt)

    grades_by_voyage: dict[Any, set[str]] = {}
    for vid, grade in db.execute(
        select(BunkerOrder.voyage_id, BunkerOrder.grade).where(
            BunkerOrder.tenant_id == tenant_id,
            BunkerOrder.voyage_id.is_not(None),
            BunkerOrder.status != "deleted",
        )
    ).all():
        if grade:
            grades_by_voyage.setdefault(vid, set()).add(grade)

    data = []
    for r in _voyage_rows(db, tenant_id, params):
        vid = r["id"]
        slot = agg.get(vid)
        if slot is None:
            continue
        dist = distances.get(vid, 0.0)
        cargo = _safe_decimal(r["cargo_qty"])
        dwt = dwt_by_voyage.get(vid, 0.0)
        aer = slot["co2"] * 1_000_000 / (dwt * dist) if dwt > 0 and dist > 0 else 0.0
        data.append({
            "voyage_no": r["voyage_no"] or "",
            "vessel_name": r["vessel_name"] or "",
            "fuel_type": ", ".join(sorted(grades_by_voyage.get(vid, ()))) or "FO/DO",
            "fo_mt": round(slot["fo"], 3),
            "do_mt": round(slot["do"], 3),
            "co2_mt": round(slot["co2"], 3),
            "transport_work": round(cargo * dist, 1),
            "aer": round(aer, 4),
        })
    return {"columns": _columns_for("mrv_voyage"), "rows": data, "total_rows": len(data)}


def execute_eu_ets_cost(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """EU ETS allowance cost per voyage (phase-in + EU share applied)."""
    price = _ets_price(db, tenant_id)
    # phase-in schedule (EU ETS maritime): 2024 40%, 2025 70%, 2026+ 100%
    phase_in = {2024: 0.40, 2025: 0.70}

    eu_ports: dict[Any, bool] = {}
    for pc_id, is_eu in db.execute(
        select(PortCall.voyage_id, Port.is_eu)
        .outerjoin(Port, PortCall.port_id == Port.id)
        .where(PortCall.tenant_id == tenant_id)
    ).all():
        if pc_id is not None:
            eu_ports[pc_id] = eu_ports.get(pc_id, False) or bool(is_eu)

    co2_by_voyage: dict[Any, float] = {}
    for vid, total in db.execute(
        select(EmissionRecord.voyage_id, func.coalesce(func.sum(EmissionRecord.co2_mt), 0))
        .where(EmissionRecord.tenant_id == tenant_id, EmissionRecord.voyage_id.is_not(None))
        .group_by(EmissionRecord.voyage_id)
    ).all():
        co2_by_voyage[vid] = _safe_decimal(total)

    # ETS responsibility: owner/None → owner pays 100%, "charterer" → 0% owner share
    owner_share: dict[Any, float] = {}
    for vid, resp in db.execute(
        select(Voyage.id, Charter.ets_responsibility)
        .outerjoin(Charter, Voyage.charter_id == Charter.id)
        .where(Voyage.tenant_id == tenant_id, Voyage.status != "deleted")
    ).all():
        owner_share[vid] = 0.0 if (resp or "").lower() == "charterer" else 100.0

    data = []
    for r in _voyage_rows(db, tenant_id, params):
        vid = r["id"]
        co2 = co2_by_voyage.get(vid, 0.0)
        is_eu = eu_ports.get(vid, False)
        year = _period_year(None, _naive(r["completed_at"]).year if r["completed_at"] else None)
        coverage = phase_in.get(year, 1.0) if is_eu else 0.0
        share = owner_share.get(vid, 100.0)
        data.append({
            "voyage_no": r["voyage_no"] or "",
            "vessel_name": r["vessel_name"] or "",
            "co2_mt": round(co2, 3),
            "eu_share_pct": 100.0 if is_eu else 0.0,
            "applicable_pct": round(coverage * share, 1),
            "ets_price_eur": price,
            "allowance_cost_eur": round(co2 * coverage * share / 100 * price, 2),
        })
    return {"columns": _columns_for("eu_ets_cost"), "rows": data, "total_rows": len(data)}


def execute_noon_report_summary(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Noon report summary: position, speed, consumption, ROB, ETA deviation."""
    rows = (
        db.execute(
            select(
                NoonReport,
                Voyage.voyage_no.label("voyage_no"),
                Vessel.name.label("vessel_name"),
            )
            .outerjoin(Voyage, NoonReport.voyage_id == Voyage.id)
            .outerjoin(Vessel, Voyage.vessel_id == Vessel.id)
            .where(NoonReport.tenant_id == tenant_id)
            .order_by(NoonReport.voyage_id, NoonReport.report_at)
            .limit(1000)
        )
        .all()
    )
    prev_rob: dict[Any, float] = {}
    data = []
    for n, voyage_no, vessel_name in rows:
        rob = _safe_decimal(n.rob_fo) + _safe_decimal(n.rob_do)
        consumption = max(0.0, prev_rob.get(n.voyage_id, rob) - rob) if n.voyage_id in prev_rob else 0.0
        prev_rob[n.voyage_id] = rob
        lat, lon = _safe_decimal(n.lat), _safe_decimal(n.lon)
        data.append({
            "vessel_name": vessel_name or "",
            "voyage_no": voyage_no or "",
            "report_at": _fmt_date(n.report_at),
            "position": f"{lat:.2f}, {lon:.2f}" if n.lat is not None and n.lon is not None else "",
            "speed": _safe_decimal(n.speed),
            "consumption_mt": round(consumption, 3),
            "rob_fo": _safe_decimal(n.rob_fo),
            "rob_do": _safe_decimal(n.rob_do),
            "eta_deviation_hours": _safe_decimal(n.eta_deviation_hours),
        })
    return {"columns": _columns_for("noon_report_summary"), "rows": data, "total_rows": len(data)}


def execute_bunker_reconciliation(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """ROB / BDN reconciliation: delivered qty vs ROB movement vs consumption."""
    rows = (
        db.execute(
            select(BunkerOrder, Vessel.name.label("vessel_name"))
            .outerjoin(Vessel, BunkerOrder.vessel_id == Vessel.id)
            .where(BunkerOrder.tenant_id == tenant_id, BunkerOrder.status != "deleted")
            .order_by(BunkerOrder.bdn_date.desc().nullslast())
            .limit(500)
        )
        .all()
    )
    data = []
    for b, vessel_name in rows:
        delivered = _safe_decimal(b.qty_delivered if b.qty_delivered is not None else b.bdn_qty)
        rob_before = _safe_decimal(b.rob_before)
        rob_after = _safe_decimal(b.rob_after)
        consumption = _safe_decimal(b.consumption)
        computed = rob_before + delivered - rob_after
        data.append({
            "vessel_name": vessel_name or "",
            "order_no": b.order_no or "",
            "grade": b.grade or "",
            "bdn_qty": _safe_decimal(b.bdn_qty if b.bdn_qty is not None else b.qty_delivered),
            "rob_before": rob_before,
            "rob_after": rob_after,
            "consumption": consumption,
            "computed_consumption": round(computed, 3),
            "variance": round(consumption - computed, 3),
        })
    return {"columns": _columns_for("bunker_reconciliation"), "rows": data, "total_rows": len(data)}


def execute_vessel_utilization(db: Session, tenant_id: uuid.UUID, params: dict) -> dict:
    """Voyage / sea / port days and utilization per vessel."""
    now = _now_naive()
    per_vessel: dict[str, dict[str, Any]] = {}
    for r in _voyage_rows(db, tenant_id, {}):
        name = r["vessel_name"] or "Unknown"
        slot = per_vessel.setdefault(
            name,
            {"voyage_days": 0.0, "port_days": 0.0, "start": None, "end": None},
        )
        started = _naive(r["started_at"]) if r["started_at"] else None
        completed = _naive(r["completed_at"]) if r["completed_at"] else (now if started else None)
        if started and completed:
            days = max(0.0, (completed - started).total_seconds() / 86400.0)
            slot["voyage_days"] += days
            slot["start"] = started if slot["start"] is None else min(slot["start"], started)
            slot["end"] = completed if slot["end"] is None else max(slot["end"], completed)

    # port days from port call stays
    port_days_by_vessel: dict[Any, float] = {}
    for vessel_id, arr, dep in db.execute(
        select(Vessel.id, PortCall.ata, PortCall.atd)
        .select_from(PortCall)
        .join(Voyage, PortCall.voyage_id == Voyage.id)
        .outerjoin(Vessel, Voyage.vessel_id == Vessel.id)
        .where(PortCall.tenant_id == tenant_id)
    ).all():
        a = arr or None
        d = dep or None
        # fall back to ETAs when actuals missing
        if a is None or d is None:
            continue
        port_days_by_vessel[vessel_id] = port_days_by_vessel.get(vessel_id, 0.0) + max(
            0.0, (_naive(d) - _naive(a)).total_seconds() / 86400.0
        )

    # map vessel display name → vessel id for port-day attribution
    name_to_id = {
        v.name: v.id
        for v in db.execute(
            select(Vessel).where(Vessel.tenant_id == tenant_id, Vessel.deleted_at.is_(None))
        ).scalars().all()
    }

    data = []
    for name, slot in per_vessel.items():
        window = 0.0
        if slot["start"] and slot["end"]:
            window = max(0.0, (slot["end"] - slot["start"]).total_seconds() / 86400.0)
        port_days = port_days_by_vessel.get(name_to_id.get(name), 0.0)
        voyage_days = slot["voyage_days"]
        sea_days = max(0.0, voyage_days - port_days)
        data.append({
            "vessel_name": name,
            "voyage_days": round(voyage_days, 2),
            "sea_days": round(sea_days, 2),
            "port_days": round(port_days, 2),
            "utilization_pct": round(voyage_days / window * 100, 1) if window > 0 else 0.0,
        })
    data.sort(key=lambda d: -d["utilization_pct"])
    return {"columns": _columns_for("vessel_utilization"), "rows": data, "total_rows": len(data)}


PRESET_EXECUTORS = {
    "voyage_pnl": execute_voyage_pnl,
    "bunker_consumption": execute_bunker_consumption,
    "tce_analysis": execute_tce_analysis,
    "fleet_performance": execute_fleet_performance,
    "counterparty_summary": execute_counterparty_summary,
    "age_days": execute_age_days,
    "port_details": execute_port_details,
    "cargo_emissions": execute_cargo_emissions,
    "speed_comparison": execute_speed_comparison,
    "sof_statement": execute_sof_statement,
    "laytime_statement": execute_laytime_statement,
    "hire_statement": execute_hire_statement,
    "estimate_vs_actual": execute_estimate_vs_actual,
    "fixture_recap": execute_fixture_recap,
    "trial_balance": execute_trial_balance,
    "commission_report": execute_commission_report,
    "statement_of_account": execute_statement_of_account,
    "port_cost_breakdown": execute_port_cost_breakdown,
    "credit_exposure": execute_credit_exposure,
    "cii_annual": execute_cii_annual,
    "mrv_voyage": execute_mrv_voyage,
    "eu_ets_cost": execute_eu_ets_cost,
    "noon_report_summary": execute_noon_report_summary,
    "bunker_reconciliation": execute_bunker_reconciliation,
    "vessel_utilization": execute_vessel_utilization,
}


# ---------------------------------------------------------------------------
# Execution dispatch
# ---------------------------------------------------------------------------


def run_declarative_report(
    db: Session,
    report_id: uuid.UUID,
    params: dict | None = None,
    tenant_id: uuid.UUID | None = None,
) -> dict:
    """Run a spec-v2 report through the declarative builder.

    Tenant scoping: the query always filters ``tenant_id``; when ``tenant_id``
    is given it must own the report (route layer already 404s cross-tenant).
    """
    report = db.get(ReportDefinition, report_id)
    if report is None:
        raise LookupError("Report not found")
    if tenant_id is not None and report.tenant_id != tenant_id:
        raise LookupError("Report not found")
    if not report.query_spec:
        raise ValueError("Report has no declarative query_spec")
    return builder_execute_query(db, report.query_spec, report.tenant_id, params or {})


def execute_report(
    db: Session,
    tenant_id: uuid.UUID,
    report: ReportDefinition,
    params: dict | None = None,
) -> dict:
    """Execute a report and return {columns, rows, total_rows}."""
    params = params or {}
    if report.query_spec:
        try:
            return builder_execute_query(db, report.query_spec, tenant_id, params)
        except ReportSpecError as e:
            return {"columns": [], "rows": [], "total_rows": 0, "error": "; ".join(e.errors)}
    if report.data_source == "preset" and report.query in PRESET_EXECUTORS:
        return PRESET_EXECUTORS[report.query](db, tenant_id, params)
    if report.data_source == "sql" and report.query:
        return _execute_sql_report(db, tenant_id, report.query, params)
    return {"columns": report.columns or [], "rows": [], "total_rows": 0, "error": "Unsupported data source"}


def _execute_sql_report(db: Session, tenant_id: uuid.UUID, sql_text: str, params: dict) -> dict:
    """Execute a custom SQL report with tenant isolation."""
    from sqlalchemy import text

    safe_params = {"tid": str(tenant_id), **params}
    if ":tid" not in sql_text:
        return {"columns": [], "rows": [], "total_rows": 0, "error": "SQL must include WHERE tenant_id = :tid"}
    try:
        result = db.execute(text(sql_text), safe_params)
        columns = [{"key": c, "label": c.replace("_", " ").title()} for c in result.keys()]
        rows = [dict(zip(result.keys(), r)) for r in result.fetchmany(1000)]
        for row in rows:
            for k, v in row.items():
                if isinstance(v, Decimal):
                    row[k] = float(v)
                elif hasattr(v, "isoformat"):
                    row[k] = str(v)
        return {"columns": columns, "rows": rows, "total_rows": len(rows)}
    except Exception as e:
        return {"columns": [], "rows": [], "total_rows": 0, "error": str(e)}


def export_report_csv(result: dict) -> str:
    """Export report result to CSV string."""
    output = io.StringIO()
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    writer = csv.writer(output)
    writer.writerow([c.get("label", c.get("key", "")) for c in columns])
    for row in rows:
        writer.writerow([row.get(c.get("key", ""), "") for c in columns])
    return output.getvalue()


def export_report_xlsx(result: dict) -> bytes:
    """Export report result to an .xlsx workbook (openpyxl).

    Auto-sized columns, styled header row, frozen first row; currency/number
    columns get basic Excel number formats.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"

    columns = result.get("columns", []) or []
    rows = result.get("rows", []) or []

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")
    widths: list[int] = []

    for idx, col in enumerate(columns, start=1):
        label = str(col.get("label", col.get("key", "")))
        cell = ws.cell(row=1, column=idx, value=label)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        widths.append(len(label))

    for r_idx, row in enumerate(rows, start=2):
        for c_idx, col in enumerate(columns, start=1):
            key = col.get("key", "")
            raw = row.get(key, "") if isinstance(row, dict) else ""
            if isinstance(raw, Decimal):
                raw = float(raw)
            if hasattr(raw, "isoformat"):
                raw = str(raw)
            cell = ws.cell(row=r_idx, column=c_idx, value=raw)
            fmt = col.get("format")
            if fmt == "currency":
                cell.number_format = '#,##0.00'
            elif fmt == "number" and isinstance(raw, (int, float)):
                cell.number_format = '#,##0.00'
            widths[c_idx - 1] = max(widths[c_idx - 1], len(str(raw)) if raw is not None else 0)

    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 10), 60)
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


def list_schedules(db: Session, tenant_id: uuid.UUID) -> list[ReportSchedule]:
    return db.execute(
        select(ReportSchedule)
        .where(ReportSchedule.tenant_id == tenant_id)
        .order_by(ReportSchedule.created_at.desc())
    ).scalars().all()


def get_schedule(db: Session, tenant_id: uuid.UUID, schedule_id: uuid.UUID) -> ReportSchedule | None:
    return db.execute(
        select(ReportSchedule).where(
            ReportSchedule.id == schedule_id,
            ReportSchedule.tenant_id == tenant_id,
        )
    ).scalar_one_or_none()


def create_schedule(db: Session, tenant_id: uuid.UUID, data: dict) -> ReportSchedule:
    rs = ReportSchedule(tenant_id=tenant_id, **data)
    db.add(rs)
    db.flush()
    return rs


def update_schedule(db: Session, schedule: ReportSchedule, data: dict) -> ReportSchedule:
    for k, v in data.items():
        setattr(schedule, k, v)
    schedule.updated_at = datetime.now(timezone.utc)
    db.flush()
    return schedule


def delete_schedule(db: Session, schedule: ReportSchedule) -> None:
    db.delete(schedule)
    db.flush()
