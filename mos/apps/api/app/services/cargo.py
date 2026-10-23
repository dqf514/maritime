"""Cargo services — 货盘 CRUD、航次分派与货盘簿汇总 (Phase 3).

All functions are tenant-scoped (via ``app.services.tenant_guard``) and commit
their own transaction; routers stay thin.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models_cargo import Cargo
from app.models_domain import Charter, Voyage
from app.models_wave1 import Counterparty, Port, Vessel
from app.pagination import paginate
from app.services.doc_numbering import next_doc_number
from app.services.tenant_guard import scoped_get, scoped_query

# 货盘簿 (cargo book) 关注的在场状态 — 未终态且仍可用于排程
OPEN_STATUSES = ("open", "booked", "nominated")
CARGO_STATUSES = ("open", "booked", "nominated", "fixed", "completed", "cancelled")
CARGO_TYPES = ("bulk", "liquid", "dry")
QTY_UNITS = ("mt", "bbl")
FREIGHT_BASES = ("per_mt", "lumpsum", "worldscale")


def _assert_port(db: Session, port_id: UUID | None, field: str) -> None:
    """Ports are global reference data (no tenant column) — existence + soft-delete only."""
    if port_id is None:
        return
    port = db.get(Port, port_id)
    if port is None or port.deleted_at is not None:
        raise HTTPException(404, f"{field} not found")


def _assert_refs(
    db: Session,
    tenant_id: UUID,
    *,
    charterer_id: UUID | None = None,
    voyage_id: UUID | None = None,
    charter_id: UUID | None = None,
    nominated_vessel_id: UUID | None = None,
    cargo_name_id: UUID | None = None,
) -> None:
    if charterer_id is not None and scoped_get(db, Counterparty, charterer_id, tenant_id) is None:
        raise HTTPException(404, "Charterer not found")
    if voyage_id is not None and scoped_get(db, Voyage, voyage_id, tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    if charter_id is not None and scoped_get(db, Charter, charter_id, tenant_id) is None:
        raise HTTPException(404, "Charter not found")
    if nominated_vessel_id is not None and scoped_get(db, Vessel, nominated_vessel_id, tenant_id) is None:
        raise HTTPException(404, "Nominated vessel not found")
    if cargo_name_id is not None:
        from app.models_cargo import CargoName

        if scoped_get(db, CargoName, cargo_name_id, tenant_id) is None:
            raise HTTPException(404, "Cargo name not found")


def _validate_window(laycan_from: date | None, laycan_to: date | None) -> None:
    if laycan_from and laycan_to and laycan_to < laycan_from:
        raise HTTPException(400, "laycan_to must be on or after laycan_from")


def cargo_public(row: Cargo) -> dict:
    return {
        "id": str(row.id),
        "cargo_no": row.cargo_no,
        "cargo_type": row.cargo_type,
        "commodity": row.commodity,
        "qty": float(row.qty) if row.qty is not None else None,
        "qty_unit": row.qty_unit,
        "load_port_id": str(row.load_port_id) if row.load_port_id else None,
        "disch_port_id": str(row.disch_port_id) if row.disch_port_id else None,
        "laycan_from": row.laycan_from.isoformat() if row.laycan_from else None,
        "laycan_to": row.laycan_to.isoformat() if row.laycan_to else None,
        "charterer_id": str(row.charterer_id) if row.charterer_id else None,
        "freight_basis": row.freight_basis,
        "freight_rate": float(row.freight_rate) if row.freight_rate is not None else None,
        "status": row.status,
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "charter_id": str(row.charter_id) if row.charter_id else None,
        "coa_id": str(row.coa_id) if row.coa_id else None,
        "notes": row.notes,
        # ── P11 IMOS Cargo detail 对齐 ──
        "cargo_name_id": str(row.cargo_name_id) if row.cargo_name_id else None,
        "api_gravity": float(row.api_gravity) if row.api_gravity is not None else None,
        "specific_gravity": float(row.specific_gravity) if row.specific_gravity is not None else None,
        "cp_date": row.cp_date.isoformat() if row.cp_date else None,
        "cp_form": row.cp_form,
        "option_pct": float(row.option_pct) if row.option_pct is not None else None,
        "option_type": row.option_type,
        "min_qty": float(row.min_qty) if row.min_qty is not None else None,
        "max_qty": float(row.max_qty) if row.max_qty is not None else None,
        "freight_type": row.freight_type,
        "currency": row.currency,
        "exchange_rate": float(row.exchange_rate) if row.exchange_rate is not None else None,
        "min_inv_qty": float(row.min_inv_qty) if row.min_inv_qty is not None else None,
        "freight_via": row.freight_via,
        "demurrage_via": row.demurrage_via,
        "cp_draft_m": float(row.cp_draft_m) if row.cp_draft_m is not None else None,
        "coordinator": row.coordinator,
        "reference_no": row.reference_no,
        "booking_no": row.booking_no,
        "vc_in_id": row.vc_in_id,
        "nominated_vessel_id": str(row.nominated_vessel_id) if row.nominated_vessel_id else None,
        "voyage_no": row.voyage_no,
        "contract_link": row.contract_link,
        "company_code": row.company_code,
        "department": row.department,
        "trade_area": row.trade_area,
        "laycan_from_override": row.laycan_from_override.isoformat() if row.laycan_from_override else None,
        "laycan_to_override": row.laycan_to_override.isoformat() if row.laycan_to_override else None,
        "laycan_confirmed": bool(row.laycan_confirmed),
        "remittance_bank": row.remittance_bank,
        "invoice_pct": float(row.invoice_pct) if row.invoice_pct is not None else None,
        "balance_pct": float(row.balance_pct) if row.balance_pct is not None else None,
        "payment_terms_code": row.payment_terms_code,
        "payment_terms_desc": row.payment_terms_desc,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def create_cargo(db: Session, tenant_id: UUID, **fields) -> Cargo:
    """Create a cargo row; ``cargo_no`` is allocated via doc numbering (CGO-YYYY-NNNNN)."""
    _validate_window(fields.get("laycan_from"), fields.get("laycan_to"))
    _assert_refs(
        db,
        tenant_id,
        charterer_id=fields.get("charterer_id"),
        voyage_id=fields.get("voyage_id"),
        charter_id=fields.get("charter_id"),
        nominated_vessel_id=fields.get("nominated_vessel_id"),
        cargo_name_id=fields.get("cargo_name_id"),
    )
    _assert_port(db, fields.get("load_port_id"), "Load port")
    _assert_port(db, fields.get("disch_port_id"), "Discharge port")
    row = Cargo(
        tenant_id=tenant_id,
        cargo_no=next_doc_number(db, tenant_id, Cargo, Cargo.cargo_no, "CGO"),
        status=fields.get("status") or "open",
        **{k: v for k, v in fields.items() if v is not None and k != "status"},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_cargo(db: Session, cargo: Cargo, **fields) -> Cargo:
    """Patch mutable fields on a cargo row (``None`` values are ignored)."""
    merged_from = fields.get("laycan_from", cargo.laycan_from)
    merged_to = fields.get("laycan_to", cargo.laycan_to)
    if "laycan_from" in fields or "laycan_to" in fields:
        _validate_window(merged_from, merged_to)
    _assert_refs(
        db,
        cargo.tenant_id,
        charterer_id=fields.get("charterer_id"),
        voyage_id=fields.get("voyage_id"),
        charter_id=fields.get("charter_id"),
        nominated_vessel_id=fields.get("nominated_vessel_id"),
        cargo_name_id=fields.get("cargo_name_id"),
    )
    _assert_port(db, fields.get("load_port_id"), "Load port")
    _assert_port(db, fields.get("disch_port_id"), "Discharge port")
    for key, value in fields.items():
        # 显式 null = 清空（调用方已用 exclude_unset 过滤未提交字段）
        if hasattr(cargo, key):
            setattr(cargo, key, value)
    db.commit()
    db.refresh(cargo)
    return cargo


def list_cargo(
    db: Session,
    tenant_id: UUID,
    *,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    charterer_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Cargo], int]:
    """Tenant-scoped cargo list.

    ``date_from``/``date_to`` filter on the laycan window with **overlap**
    semantics (a cargo matches when its laycan intersects the range).
    """
    stmt = scoped_query(db, Cargo, tenant_id).order_by(Cargo.cargo_no)
    if status is not None:
        stmt = stmt.where(Cargo.status == status)
    if charterer_id is not None:
        stmt = stmt.where(Cargo.charterer_id == charterer_id)
    if date_from is not None:
        stmt = stmt.where(Cargo.laycan_to.is_(None) | (Cargo.laycan_to >= date_from))
    if date_to is not None:
        stmt = stmt.where(Cargo.laycan_from.is_(None) | (Cargo.laycan_from <= date_to))
    return paginate(db, stmt, limit, offset)


def allocate_to_voyage(db: Session, cargo_id: UUID, voyage_id: UUID) -> Cargo:
    """Link a cargo to a voyage of the same tenant (IDOR-safe: foreign voyage → 404)."""
    cargo = db.get(Cargo, cargo_id)
    if cargo is None or cargo.deleted_at is not None or cargo.status == "deleted":
        raise HTTPException(404, "Cargo not found")
    if scoped_get(db, Voyage, voyage_id, cargo.tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    cargo.voyage_id = voyage_id
    db.commit()
    db.refresh(cargo)
    return cargo


def cargo_book_summary(db: Session, tenant_id: UUID) -> dict:
    """Open cargo grouped by laycan month (cargo book / 货盘簿视图).

    Cargoes without a laycan window fall into an ``unknown`` bucket.
    """
    rows = db.scalars(
        scoped_query(db, Cargo, tenant_id)
        .where(Cargo.status.in_(OPEN_STATUSES))
        .order_by(Cargo.laycan_from, Cargo.cargo_no)
    ).all()
    buckets: dict[str, list[Cargo]] = defaultdict(list)
    for row in rows:
        anchor = row.laycan_from or row.laycan_to
        key = anchor.strftime("%Y-%m") if anchor else "unknown"
        buckets[key].append(row)
    months = []
    for month in sorted(buckets):
        group = buckets[month]
        qty = sum((r.qty or Decimal("0") for r in group), Decimal("0"))
        months.append(
            {
                "month": month,
                "cargo_count": len(group),
                "total_qty": float(qty),
                "cargoes": [cargo_public(r) for r in group],
            }
        )
    return {
        "months": months,
        "total_open": len(rows),
        "statuses": list(OPEN_STATUSES),
    }
