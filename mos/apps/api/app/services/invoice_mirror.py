"""Mirror invoice generation — creates counterparty invoice with reversed direction.

When company A issues a freight invoice to company B, a mirror invoice is
auto-generated for company B's books with the same amount/currency/fx_rate
but opposite debit/credit direction. The mirror follows an independent
approval workflow.

End-to-end contract (Track C3):
- 源改镜像跟 (pull-sync): while the mirror is ``draft``, source commercial
  fields flow into it via :func:`sync_mirrors`, tracked by
  ``Invoice.mirror_synced_source_at``.
- 不可独立编辑: a mirror must not be patched on its own — call
  :func:`assert_mirror_writable` at the top of any invoice-update path.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import Invoice
from app.services.config_service import ConfigService
from app.services.doc_numbering import next_doc_number
from app.services.invoice_types import normalize_invoice_type

#: 可镜像的发票类型（**规范码**）—— P0-B7。
#:
#: 旧实现用的是"历史别名"字面量集合（``"freight"`` / ``"port_da"`` …），
#: 于是**用规范码存的发票**（``"FRT"`` / ``"FDA"`` / ``"BKR"`` …）一律被
#: 判定为"不可镜像"而抛错 —— 同一张发票，只是类型写法不同，一个能镜像
#: 一个不能。现在统一走 :func:`app.services.invoice_types.normalize_invoice_type`
#: 解析成规范码再判定，别名与规范码一视同仁。
#:
#: 不可镜像的类型：
#:   * ``PDA`` —— 港口使费账单是**航次成本**（向代理付款），不是对外开票；
#:   * ``TCOB`` —— 期租**开出**账单，方向与镜像（对方入账）相反；
#:   * ``XREV`` —— 红冲单，镜像没有意义（源单自己冲销即可）；
#:   * ``XDIFF`` —— 汇兑重估，不是真实收付。
MIRROR_TYPES: frozenset[str] = frozenset({"FRT", "DEM", "BKR", "FDA", "TCIP", "XEXP"})

#: 旧的历史别名集合 —— 保留常量供外部引用（不再用于判定）。
LEGACY_MIRROR_TYPES: frozenset[str] = frozenset(
    {
        "freight",
        "demurrage",
        "despatch",
        "bunker",
        "port_da",
        "tc_hire",
        "broker_commission",
        "carbon_allowance",
        "eu_ets",
    }
)


def is_mirrorable_type(invoice_type: str | None) -> bool:
    """该发票类型能否被镜像 —— 别名与规范码一视同仁（P0-B7）。

    ``invoice_type`` 可以是历史别名（``"freight"``）也可以是规范码
    （``"FRT"``）；都先解析成规范码再判断。无法识别的类型一律判为
    不可镜像（宁可不镜像，也不要镜像出错的账）。
    """
    raw = str(invoice_type or "").strip()
    if not raw:
        return False
    try:
        code = normalize_invoice_type(raw)
    except ValueError:
        return False
    return code in MIRROR_TYPES

# Fields pulled from source → mirror while the mirror is still draft.
# P1-B6：``base_amount`` 必须在同步列表里 —— 源单改了金额，镜像的金额跟着变，
# 但本币金额不跟着变 → 镜像的 P&L / 账龄按旧汇率折算，对不上。
SYNCED_FIELDS = (
    "amount",
    "base_amount",
    "currency",
    "fx_rate",
    "tax_amount",
    "due_date",
    "bill_by",
    "commission_basis",
)

# 商务字段：源单改了就照抄。
# ``fx_rate`` / ``base_amount`` 不在这里 —— 它们的口径取决于**镜像租户**的本位币，
# 跨本位币时必须按镜像租户重算（见 :func:`_target_base_amount`）。
SYNCED_BUSINESS_FIELDS = (
    "amount",
    "currency",
    "tax_amount",
    "due_date",
    "bill_by",
    "commission_basis",
)


def intercompany_enabled(db: Session, tenant_id: UUID, user_id: UUID | None = None) -> bool:
    """CFGEnableIntercompany — gate for cross-tenant (intercompany) mirrors.

    Thin wrapper over ConfigService so tests can monkeypatch this helper.
    """
    return bool(
        ConfigService.get(db, "CFGEnableIntercompany", tenant_id=tenant_id, user_id=user_id, default=False)
    )


def create_mirror_invoice(
    db: Session,
    source: Invoice,
    counterparty_tenant_id: UUID,
) -> Invoice:
    """Generate a mirror invoice for the counterparty.

    The mirror copies amount, currency, voyage and invoice_type from the source.
    The mirror's ``mirror_of_id`` points back to the source. The mirror starts in
    ``draft`` status with its own invoice_no.

    P1-B10：**本币金额必须按镜像租户的本位币算**。旧实现直接把源租户算出来的
    ``base_amount`` / ``fx_rate`` 抄过去 —— 两边本位币不同时（源 USD、镜像 EUR）
    镜像的 P&L / 账龄就是用错的汇率折算的，数字看着有但口径是错的。
    """
    if not is_mirrorable_type(source.invoice_type):
        raise ValueError(f"Invoice type '{source.invoice_type}' is not mirrorable")
    if source.mirror_of_id is not None:
        raise ValueError("Cannot mirror a mirror invoice")

    existing = db.scalar(select(Invoice.id).where(Invoice.mirror_of_id == source.id))
    if existing is not None:
        raise ValueError("Source invoice already has a mirror")

    mirror_no = next_doc_number(db, counterparty_tenant_id, Invoice, Invoice.invoice_no, "INV")
    synced_at = _now()
    fx_rate, base_amount = _target_base_amount(db, source, counterparty_tenant_id)

    mirror = Invoice(
        id=uuid.uuid4(),
        tenant_id=counterparty_tenant_id,
        invoice_no=mirror_no,
        invoice_type=source.invoice_type,
        status="draft",
        counterparty_id=source.counterparty_id,
        voyage_id=source.voyage_id,
        currency=source.currency,
        amount=source.amount,
        base_amount=base_amount,
        fx_rate=fx_rate,
        tax_amount=source.tax_amount,
        due_date=source.due_date,
        mirror_of_id=source.id,
        mirror_synced_source_at=synced_at,
        bill_by=source.bill_by,
        commission_basis=source.commission_basis,
    )
    db.add(mirror)
    return mirror


def _tenant_base_currency(db: Session, tenant_id: UUID) -> str:
    """租户本位币（没有 Company 行时退回 USD）。"""
    from app.models_wave1 import Company

    comp = db.scalar(select(Company).where(Company.tenant_id == tenant_id).limit(1))
    return (comp.base_currency if comp and comp.base_currency else "USD")


def _source_invoice_date(source: Invoice):
    """源发票的**单据日期**（取价日用）—— created_at，没有就用 due_date。"""
    created = getattr(source, "created_at", None)
    if isinstance(created, datetime):
        return created.date()
    if isinstance(created, date):
        return created
    due = getattr(source, "due_date", None)
    if isinstance(due, date):
        return due
    return None


def _target_base_amount(
    db: Session, source: Invoice, target_tenant_id: UUID
) -> tuple[Decimal | None, Decimal | None]:
    """镜像单的 (fx_rate, base_amount) —— 按**镜像租户**的本位币算。

    两边本位币相同 → 直接沿用源单的汇率/本币金额（同口径，零误差）。
    不同 → 用镜像租户自己的汇率重算；没有汇率就留空（镜像还是草稿，签发前
    必须补齐汇率 —— 与 P0-B5「缺汇率不落库」同口径）。
    """
    from decimal import Decimal

    from app.services.fx_date_rules import resolve_fx_rate, resolve_rate_date

    src_base = _tenant_base_currency(db, source.tenant_id).upper()
    tgt_base = _tenant_base_currency(db, target_tenant_id).upper()
    ccy = (source.currency or "USD").upper()
    if src_base == tgt_base:
        return source.fx_rate, source.base_amount
    if ccy == tgt_base:
        return Decimal("1"), source.amount
    # P1-B9：取价日 = **源发票日期**（不是"绝对最新汇率"）—— 否则租户改了
    # 汇率，历史镜像单的金额就跟着变，报表不可复现。
    doc_date = _source_invoice_date(source)
    rate_date = (
        resolve_rate_date(
            db,
            target_tenant_id,
            source.invoice_type,
            {"invoice": doc_date, "invoice_date": doc_date},
            fallback=doc_date,
        )
        if doc_date
        else None
    )
    rate = resolve_fx_rate(
        db, target_tenant_id, ccy, tgt_base, context_date=rate_date
    )
    if rate is None:
        return None, None
    return rate, (source.amount or Decimal("0")) * rate


def assert_mirror_writable(invoice: Invoice) -> None:
    """不可独立编辑 — mirror invoices follow their source and cannot be edited.

    Call this at the top of any invoice update/patch path. Raises 409
    ``MIRROR_READONLY`` when the invoice is a mirror.

    NOTE: ``routers/invoices.py::update_invoice`` must call this (see report);
    the call is intentionally not added here to avoid touching that file while
    a concurrent agent owns it.
    """
    if invoice.mirror_of_id is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "MIRROR_READONLY",
                "message": "Mirror invoice follows its source and cannot be edited independently",
                "mirror_of_id": str(invoice.mirror_of_id),
            },
        )


def sync_mirrors(db: Session, source: Invoice, *, user_id: UUID | None = None) -> list[Invoice]:
    """Pull-sync (源改镜像跟): draft mirrors follow source commercial fields.

    Copies amount/currency/fx_rate/tax_amount/due_date/bill_by/commission_basis
    into every draft mirror of ``source`` when the source has moved on since the
    mirror's stored sync marker (``mirror_synced_source_at``), then stamps the
    marker. Commits are left to the caller.

    P1-17：跨租户的那条腿（镜像在别的租户）**只在源租户启用了
    ``CFGEnableIntercompany`` 时才同步**。否则本租户的一个普通写操作就能
    改到外租户的发票行上 —— 那是实打实的跨租户写入。
    """
    if source.mirror_of_id is not None:
        # Called on a mirror — nothing to pull; the chain resolves its source.
        return []

    mirrors = db.scalars(select(Invoice).where(Invoice.mirror_of_id == source.id)).all()
    synced: list[Invoice] = []
    for mirror in mirrors:
        if mirror.status != "draft":
            continue
        if mirror.tenant_id != source.tenant_id:
            # 跨租户镜像 —— 需公司间镜像开关打开，否则不碰对方的行
            if not intercompany_enabled(db, source.tenant_id, user_id):
                continue
        if not _needs_sync(source, mirror):
            continue
        for field in SYNCED_BUSINESS_FIELDS:
            setattr(mirror, field, getattr(source, field))
        # 本币金额按镜像租户口径重算（跨本位币时不能照抄源单的 fx/base）
        fx_rate, base_amount = _target_base_amount(db, source, mirror.tenant_id)
        mirror.fx_rate = fx_rate
        mirror.base_amount = base_amount
        mirror.mirror_synced_source_at = _now()
        db.add(mirror)
        synced.append(mirror)
    return synced


def get_mirror_chain(
    db: Session, invoice_id: UUID, tenant_id: UUID, *, user_id: UUID | None = None
) -> list[dict]:
    """Return the source + its mirror (if any) for display.

    Tenant-scoped: only the invoice row that matches ``tenant_id`` is used as
    the entry point.

    P1-17：**跨租户的那条腿只有在本租户启用了 ``CFGEnableIntercompany`` 时
    才返回**。否则一个镜像开关没开的租户，只要库里存在一条指向它的镜像
    （历史脏数据 / 手工造的数据），就能读到外租户的单据号与金额。
    """
    inv = db.get(Invoice, invoice_id)
    if not inv or inv.tenant_id != tenant_id:
        return []

    chain = [_chain_row(inv)]
    cross_tenant_allowed = intercompany_enabled(db, tenant_id, user_id)

    if inv.mirror_of_id:
        source = db.get(Invoice, inv.mirror_of_id)
        if source and (source.tenant_id == tenant_id or cross_tenant_allowed):
            chain.insert(0, _chain_row(source))
    else:
        mirror_stmt = select(Invoice).where(Invoice.mirror_of_id == inv.id)
        mirror = db.scalars(mirror_stmt).first()
        if mirror and (mirror.tenant_id == tenant_id or cross_tenant_allowed):
            chain.append(_chain_row(mirror))

    return chain


def find_mirror(db: Session, source_id: UUID) -> Invoice | None:
    """Return the mirror of a source invoice (any tenant), if one exists."""
    return db.scalars(select(Invoice).where(Invoice.mirror_of_id == source_id)).first()


def invoice_payload(row: Invoice) -> dict:
    """Invoice-list-shaped dict for API responses (includes mirror flags)."""
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "invoice_no": row.invoice_no,
        "invoice_type": row.invoice_type,
        "status": row.status,
        "amount": float(row.amount or 0),
        "tax_amount": float(row.tax_amount or 0),
        "paid_amount": float(row.paid_amount or 0),
        "currency": row.currency,
        "fx_rate": float(row.fx_rate) if row.fx_rate is not None else None,
        "base_amount": float(row.base_amount) if row.base_amount is not None else None,
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "counterparty_id": str(row.counterparty_id) if row.counterparty_id else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "gl_posted": bool(row.gl_posted),
        "mirror_of_id": str(row.mirror_of_id) if row.mirror_of_id else None,
        "is_mirror": row.mirror_of_id is not None,
        "mirror_synced_source_at": row.mirror_synced_source_at.isoformat() if row.mirror_synced_source_at else None,
        "bill_by": row.bill_by,
        "commission_basis": row.commission_basis,
    }


def _chain_row(row: Invoice) -> dict:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "invoice_no": row.invoice_no,
        "status": row.status,
        "amount": str(row.amount),
        "currency": row.currency,
        "is_mirror": row.mirror_of_id is not None,
        "mirror_of_id": str(row.mirror_of_id) if row.mirror_of_id else None,
        "mirror_synced_source_at": row.mirror_synced_source_at.isoformat() if row.mirror_synced_source_at else None,
    }


def _needs_sync(source: Invoice, mirror: Invoice) -> bool:
    """True when the source has moved on since the mirror's last pull-sync.

    Invoice has no ``updated_at`` column, so drift is detected by comparing the
    synced fields themselves. If a source timestamp is ever present it is used
    as an additional trigger (marker older than source).
    """
    if mirror.mirror_synced_source_at is None:
        return True
    if any(getattr(source, f) != getattr(mirror, f) for f in SYNCED_FIELDS):
        return True
    source_ts = getattr(source, "updated_at", None)
    if source_ts is not None:
        return _as_utc(source_ts) > _as_utc(mirror.mirror_synced_source_at)
    return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Re-exported for callers that need the synced-field list (e.g. tests).
__all__ = [
    "LEGACY_MIRROR_TYPES",
    "MIRROR_TYPES",
    "SYNCED_FIELDS",
    "assert_mirror_writable",
    "create_mirror_invoice",
    "find_mirror",
    "get_mirror_chain",
    "intercompany_enabled",
    "invoice_payload",
    "is_mirrorable_type",
    "sync_mirrors",
]
