"""Laytime 计算路由（U1 列表协议 + D12 对账）。"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.pagination import envelope, paginate
from app.security import AuthContext, require_module

from app.models_domain import (
    Charter,
    DemurrageOnAccount,
    DemurrageRootCause,
    Invoice,
    LaytimeCalc,
    LaytimeDelay,
    LaytimeType,
    PortCall,
    SofEvent,
    Voyage,
)
from app.models import User
from app.models_cargo import Cargo
from app.models_wave1 import Counterparty, Port
from app.models_task import Task
from app.services.laytime_engine import compute_laytime, compute_laytime_statement, settle_with_on_account
from app.services.clause_library import materialize_params
from app.services.doc_numbering import next_doc_number
from app.services.domain_events import emit
from app.services.money import FX_RATE_NOT_FOUND, FxRateUnavailable, money, require_fx_rate, to_base_amount
from app.services.recycle import soft_delete
from app.services.sanctions import assert_not_sanctioned
from app.services.state_machine import LAYTIME_TRANSITIONS, transition
from app.services.tenant_guard import scoped_get

from app.routers._finance_common import _alive, _base_currency, _resolve_fx_rate, TIMEBAR_DAYS_AFTER_BL
from app.services.data_scope import apply_module_scope

router = APIRouter()

log = logging.getLogger("marios.laytimes")


def _laytime_archive_bytes(db: Session, tenant_id, row) -> tuple[bytes, str, str, dict]:
    """定稿用的计算书文件 —— PDF 优先，缺引擎退回凭证 CSV。

    返回 ``(content, filename, content_type, meta)``。注意 entity_type 双轨：
    office_hub 归档路径沿用历史的 ``laytime``，模板体系用的是 ``laytime_statement``。
    """
    meta = {"status": row.status, "booking_reference": row.booking_reference}
    from app.services import doc_engine

    try:
        result = doc_engine.render_document(
            db, tenant_id,
            entity_type="laytime_statement", entity_id=row.id,
        )
        pdf = doc_engine.html_to_pdf(result.html)
        doc_engine.record_render(
            db, tenant_id,
            entity_type="laytime_statement", entity_id=row.id,
            result=result, content=pdf, fmt="pdf",
            content_type="application/pdf",
            snapshot=doc_engine.build_letterhead(db, tenant_id),
        )
        meta["template_version"] = result.template_version
        return pdf, result.filename, "application/pdf", meta
    except doc_engine.PDFEngineUnavailable:
        pass
    except Exception:  # noqa: BLE001
        log.exception("laytime PDF archive failed for %s, falling back to CSV", row.id)

    import csv
    import io
    import json as _json

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "key", "value"])
    for section, data in (("input", row.inputs or {}), ("result", row.results or {})):
        for k, v in sorted(data.items()):
            w.writerow([section, k, _json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v])
    return (buf.getvalue().encode("utf-8-sig"),
            f"laytime_statement_{row.id}.csv", "text/csv", meta)


def _office_escalate_laytime(db: Session, tenant_id, row) -> None:
    """装卸时间定稿 → 正式 PDF 归档 OneDrive + Teams 频道提醒（软失败，绝不影响定稿本身）。

    优先出租户模板渲染的 PDF（带公司抬头，对手方能直接收）；Chromium 未装时退回
    凭证 CSV —— 归档链路不能因为缺 PDF 引擎就断。
    """
    try:
        from app.services import office_hub

        content, filename, ctype, meta = _laytime_archive_bytes(db, tenant_id, row)
        doc = office_hub.push_entity_document(
            db,
            tenant_id,
            entity_type="laytime",
            entity_id=row.id,
            filename=filename,
            content=content,
            content_type=ctype,
            meta=meta,
        )
        lines = [f"Laytime finalized: {row.booking_reference or row.id}"]
        if doc:
            lines.append(f"Archived to OneDrive: {doc.get('web_url') or doc.get('name')}")
        office_hub.notify_workflow_event(
            db,
            tenant_id,
            title="Laytime statement finalized",
            lines=lines,
            href="/finance?tab=laytime",
        )
    except Exception:  # noqa: BLE001
        log.exception("office escalate failed for laytime %s", row.id)


# —— Laytime ——
class LaytimeIn(BaseModel):
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    booking_reference: str | None = None
    inputs: dict = Field(default_factory=dict)


@router.post("/laytimes")
def create_laytime(body: LaytimeIn, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    if body.voyage_id is not None and scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
        raise HTTPException(404, "Voyage not found")
    if body.port_call_id is not None and scoped_get(db, PortCall, body.port_call_id, auth.tenant_id) is None:
        raise HTTPException(404, "Port call not found")
    row = LaytimeCalc(
        tenant_id=auth.tenant_id,
     created_by=auth.user_id,
        voyage_id=body.voyage_id,
        port_call_id=body.port_call_id,
        booking_reference=body.booking_reference,
        inputs=body.inputs,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "status": row.status}


@router.post("/laytimes/{laytime_id}/calculate")
def calc_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Laytime not found")
    row.results = compute_laytime(row.inputs or {})
    row.status = transition("laytime", row.status, "calculated", LAYTIME_TRANSITIONS)
    db.commit()
    return {"id": str(row.id), "status": row.status, "results": row.results}


@router.post("/laytimes/{laytime_id}/finalize")
def finalize_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Laytime not found")
    row.status = transition("laytime", row.status, "finalized", LAYTIME_TRANSITIONS)
    row.finalized_at = datetime.now(timezone.utc)
    # 域事件：定稿才是"装卸时间这条动作做完了"的事实 —— 绑 laytime.finalize
    # 的任务靠它即时勾掉（以前只在"草稿刚建"时发事件，语义反了）。
    emit(
        db, auth.tenant_id, "laytime.finalized", "laytime", row.id,
        payload={
            "voyage_id": str(row.voyage_id) if row.voyage_id else None,
            "booking_reference": row.booking_reference,
        },
        user_id=auth.user_id,
    )
    db.commit()
    _office_escalate_laytime(db, auth.tenant_id, row)
    db.commit()
    return {"id": str(row.id), "status": row.status, "results": row.results}


def _laytime_out(r) -> dict:
    """滞期费计算书对外结构（列表与单条一致，前端可直接复用）。"""
    return {
        "id": str(r.id),
        "voyage_id": str(r.voyage_id) if r.voyage_id else None,
        "port_call_id": str(r.port_call_id) if r.port_call_id else None,
        "booking_reference": r.booking_reference,
        "status": r.status,
        "inputs": r.inputs or {},
        "results": r.results or {},
        "finalized_at": r.finalized_at.isoformat() if r.finalized_at else None,
    }


@router.get("/laytimes")
def list_laytimes(
    voyage_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    q = select(LaytimeCalc).where(LaytimeCalc.tenant_id == auth.tenant_id, LaytimeCalc.status != "deleted")
    if voyage_id is not None:
        q = q.where(LaytimeCalc.voyage_id == voyage_id)
    # 行级数据权限：scope 收窄到 "own" 时只看自己建的滞期费计算
    q = apply_module_scope(db, q, LaytimeCalc, auth, "laytime")
    rows, total = paginate(db, q.order_by(LaytimeCalc.id), limit, offset)
    return envelope([_laytime_out(r) for r in rows], total, limit, offset)


@router.put("/laytimes/{laytime_id}")
def update_laytime(
    laytime_id: UUID,
    body: LaytimeIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    if row.status == "finalized":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LAYTIME_FINALIZED",
                "message": "Laytime is finalized and locked; create a new revision instead of editing it",
                "status": row.status,
            },
        )
    if body.voyage_id is not None:
        if scoped_get(db, Voyage, body.voyage_id, auth.tenant_id) is None:
            raise HTTPException(404, "Voyage not found")
        row.voyage_id = body.voyage_id
    if body.port_call_id is not None:
        if scoped_get(db, PortCall, body.port_call_id, auth.tenant_id) is None:
            raise HTTPException(404, "Port call not found")
        row.port_call_id = body.port_call_id
    if body.booking_reference is not None:
        row.booking_reference = body.booking_reference
    row.inputs = body.inputs or row.inputs
    if row.status == "calculated":
        row.status = transition("laytime", "calculated", "draft", LAYTIME_TRANSITIONS)
        row.results = {}
    db.commit()
    return {"id": str(row.id), "status": row.status, "inputs": row.inputs or {}}


@router.delete("/laytimes/{laytime_id}")
def delete_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="laytime",
        row=row,
        title=f"Laytime {str(row.id)[:8]}",
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/laytimes/{laytime_id}/export")
def export_laytime(laytime_id: UUID, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    """Structured laytime statement (SOF 对照计算书): every event with gross /
    term-excluded / counted hours and the cumulative used time, against the
    allowed time and the settled demurrage/despatch amount."""
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    if not row.inputs:
        raise HTTPException(422, detail={"code": "NO_INPUTS", "message": "Laytime has no inputs to export"})
    statement = compute_laytime_statement(row.inputs)
    return {
        "id": str(row.id),
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "port_call_id": str(row.port_call_id) if row.port_call_id else None,
        "status": row.status,
        "format": "LAYTIME_STATEMENT_v1",
        "finalized_at": row.finalized_at.isoformat() if row.finalized_at else None,
        **statement,
    }


class LaytimeFromSofIn(BaseModel):
    port_call_id: UUID
    allowed_hours: float | None = None
    terms: str | None = None
    # D6 NOR 递交条件（WIBON/WCCON/WIPON）；不传则取租约勾选条款的 nor_terms
    nor_terms: str | None = None
    # 显式覆盖：是否计入等泊时间（None=按 nor_terms 规则判定）
    count_waiting: bool | None = None


def _allowed_from_charter(charter: Charter | None, purpose: str) -> Decimal | None:
    """Default allowed hours = charter cargo_qty / load|disch rate (mt/day) * 24."""
    if not charter or not charter.cargo_qty:
        return None
    rate = charter.load_rate_pd if purpose == "load" else charter.disch_rate_pd
    if not rate or Decimal(str(rate)) <= 0:
        return None
    return (Decimal(str(charter.cargo_qty)) / Decimal(str(rate)) * Decimal("24")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@router.post("/laytimes/from-sof")
def laytime_from_sof(body: LaytimeFromSofIn, auth: AuthContext = Depends(require_module("laytime")), db: Session = Depends(get_db)):
    """Build a LaytimeCalc from a port call's Statement of Facts events.

    NOR→COMMENCED becomes the waiting segment and COMMENCED→COMPLETED the
    working segment; both count subject to the charter-party terms (SHINC/SHEX
    weekend/holiday exclusions). Port holidays and timezone come from the Port
    master data. Allowed hours default to charter cargo_qty ÷ load/disch rate.
    """
    pc = db.get(PortCall, body.port_call_id)
    if not pc or pc.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Port call not found")
    sof = db.scalars(
        select(SofEvent).where(SofEvent.port_call_id == pc.id).order_by(SofEvent.event_at.asc())
    ).all()
    by_code: dict[str, list[SofEvent]] = {}
    for ev in sof:
        by_code.setdefault(ev.event_code.upper(), []).append(ev)
    if not by_code.get("COMMENCED") or not by_code.get("COMPLETED"):
        raise HTTPException(
            status_code=422,
            detail={"code": "INSUFFICIENT_SOF", "message": "SOF needs at least COMMENCED and COMPLETED events"},
        )
    commenced = by_code["COMMENCED"][0].event_at
    completed = by_code["COMPLETED"][-1].event_at

    voyage = db.get(Voyage, pc.voyage_id)
    charter = db.get(Charter, voyage.charter_id) if voyage and voyage.charter_id else None

    # D6 NOR 递交条件（条款驱动，向后兼容）：
    # - WIBON/WCCON/WIPON 或缺省：NOR 递交即起算，等泊时间计入（与历史行为一致）；
    # - BERTH_ONLY：NOR 须靠泊/备妥方为有效，靠泊前等泊时间不计（excluded）；
    # - count_waiting 显式覆盖一切规则。
    clause_codes = list((charter.clauses or {}).get("codes") or []) if charter else []
    clause_params = materialize_params(db, auth.tenant_id, clause_codes) if clause_codes else {}
    nor_terms = str(body.nor_terms or clause_params.get("nor_terms") or "").upper()

    events: list[dict] = []
    if by_code.get("NOR"):
        nor = by_code["NOR"][0].event_at
        if commenced > nor:
            if body.count_waiting is not None:
                waiting_counts = body.count_waiting
            else:
                waiting_counts = nor_terms != "BERTH_ONLY"
            events.append(
                {
                    "start": nor.isoformat(),
                    "end": commenced.isoformat(),
                    "kind": "waiting",
                    "excluded": not waiting_counts,
                }
            )
    events.append({"start": commenced.isoformat(), "end": completed.isoformat(), "kind": "working"})

    allowed = body.allowed_hours
    if allowed is None:
        derived = _allowed_from_charter(charter, pc.purpose or "load")
        if derived is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "ALLOWED_HOURS_REQUIRED",
                    "message": "Cannot derive allowed hours from charter (need cargo_qty and load/disch rate); pass allowed_hours",
                },
            )
        allowed = float(derived)

    port = db.get(Port, pc.port_id) if pc.port_id else None
    inputs: dict = {
        "allowed_hours": allowed,
        "terms": body.terms or (charter.laytime_terms if charter and charter.laytime_terms else "SHINC"),
        "events": events,
    }
    # 勾选条款的计算参数直通（once_on_demurrage 等；laytime_terms/nor_terms 已单独处理）
    inputs.update({k: v for k, v in clause_params.items() if k not in ("laytime_terms", "nor_terms")})
    if charter and charter.demurrage_rate:
        inputs["demurrage_rate_per_day"] = float(charter.demurrage_rate)
    if charter and charter.despatch_rate:
        inputs["despatch_rate_per_day"] = float(charter.despatch_rate)
    if port and port.holidays:
        inputs["port_holidays"] = port.holidays
    tz_name = (port.timezone if port else None) or pc.timezone
    if tz_name:
        inputs["port_timezone"] = tz_name

    row = LaytimeCalc(
        tenant_id=auth.tenant_id,
     created_by=auth.user_id,
        voyage_id=pc.voyage_id,
        port_call_id=pc.id,
        status="draft",
        inputs=inputs,
    )
    row.results = compute_laytime(inputs)
    row.status = transition("laytime", row.status, "calculated", LAYTIME_TRANSITIONS)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "status": row.status, "inputs": row.inputs, "results": row.results}


@router.post("/laytimes/compare")
def compare_laytime_statements(
    body: dict,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """D12 结算单对账：my（我方计算书）vs their（对手方）→ 差异清单。

    my 可直接给 statement JSON，或给 laytime_id 由服务端现算。
    """
    from app.services.laytime_engine import compute_laytime_statement
    from app.services.statement_diff import diff_statements

    my = body.get("my")
    if my is None and body.get("laytime_id"):
        try:
            lid = UUID(str(body["laytime_id"]))
        except ValueError:
            raise HTTPException(422, "invalid laytime_id")
        row = scoped_get(db, LaytimeCalc, lid, auth.tenant_id)
        if row is None:
            raise HTTPException(404, "Laytime not found")
        my = compute_laytime_statement(row.inputs or {})
    their = body.get("their")
    if not isinstance(my, dict) or not isinstance(their, dict):
        raise HTTPException(422, detail={"code": "STATEMENTS_REQUIRED", "message": "my (or laytime_id) and their are required"})
    return diff_statements(my, their)


# —— Laytime depth: demurrage on account / root causes / delays / time bar ——

ROOT_CAUSES = ("port_congestion", "weather", "cargo_delay", "documentation", "other")
RESPONSIBLE_PARTIES = ("owner", "charterer", "port", "agent", "other")
DELAY_TYPES = ("weather", "port_congestion", "cargo", "documentation", "breakdown", "other")


def _get_laytime(auth: AuthContext, db: Session, laytime_id: UUID) -> LaytimeCalc:
    row = db.get(LaytimeCalc, laytime_id)
    if not row or row.tenant_id != auth.tenant_id or not _alive(row.status):
        raise HTTPException(404, "Laytime not found")
    return row


def _convert_amounts_to_base(
    db: Session,
    tenant_id,
    base_ccy: str,
    items: list[tuple[Decimal, str]],
) -> tuple[Decimal, dict[str, Decimal]]:
    """把 (金额, 币种) 列表折成本位币并求和。

    P1-B4：不同币种的金额**不能直接相加**（EUR 1000 + USD 1000 ≠ 2000）。
    每一笔先按汇率折成本位币再求和。

    折不动的币种（没有汇率）**不进合计**，而是按币种列在第二个返回值里 ——
    宁可少算也不能拿没折的钱去冲抵（fail closed against false positives：
    没折成功的预付款绝不能把「未结」算成「已结清」）。
    """
    total = Decimal("0")
    unconverted: dict[str, Decimal] = {}
    for amt, ccy in items:
        cur = (ccy or base_ccy).upper()
        if cur == (base_ccy or "").upper():
            total += money(amt)
            continue
        rate = _resolve_fx_rate(db, tenant_id, cur, base_ccy)
        if rate is None:
            unconverted[cur] = unconverted.get(cur, Decimal("0")) + money(amt)
            continue
        total += to_base_amount(amt, rate)
    return money(total), unconverted


def _demurrage_amount(row: LaytimeCalc) -> Decimal:
    """Settled demurrage for a laytime (0 for despatch/on-time)."""
    results = row.results or {}
    if not results and row.inputs:
        results = compute_laytime(row.inputs or {})
    # dict 下标访问（不用 .get）：arch guard 把 .get() 误判为 ORM 查询点
    result_type = results["result_type"] if "result_type" in results else ""
    if str(result_type or "") != "demurrage":
        return Decimal("0.00")
    amount = results["amount"] if "amount" in results else 0
    return Decimal(str(amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class DemurrageOnAccountIn(BaseModel):
    amount: float
    currency: str = "USD"
    payment_date: date | None = None
    status: str = "pending"  # pending|paid|applied
    notes: str | None = None


@router.post("/laytimes/{laytime_id}/demurrage-on-account")
def create_demurrage_on_account(
    laytime_id: UUID,
    body: DemurrageOnAccountIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    if body.amount <= 0:
        raise HTTPException(422, detail={"code": "INVALID_AMOUNT", "message": "amount must be > 0"})
    if body.status not in ("pending", "paid", "applied"):
        raise HTTPException(422, detail={"code": "INVALID_STATUS", "message": "status must be pending|paid|applied"})
    rec = DemurrageOnAccount(
        tenant_id=auth.tenant_id,
        laytime_id=row.id,
        amount=Decimal(str(body.amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        currency=body.currency,
        payment_date=body.payment_date,
        status=body.status,
        applied_to_settlement=body.status == "applied",
        notes=body.notes,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _on_account_payload(rec)


@router.get("/laytimes/{laytime_id}/demurrage-on-account")
def list_demurrage_on_account(
    laytime_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    q = (
        select(DemurrageOnAccount)
        .where(DemurrageOnAccount.tenant_id == auth.tenant_id, DemurrageOnAccount.laytime_id == row.id)
        .order_by(DemurrageOnAccount.id)
    )
    rows, total = paginate(db, q, limit, offset)
    # 币种维度：不同币种的预付款不能直接相加成一个「已付」数（P1-B4）——
    # 每一笔先折本币再求和；折不动的币种单列，不混进合计。
    by_ccy_rows = db.execute(
        select(DemurrageOnAccount.currency, func.coalesce(func.sum(DemurrageOnAccount.amount), 0))
        .where(
            DemurrageOnAccount.tenant_id == auth.tenant_id,
            DemurrageOnAccount.laytime_id == row.id,
            DemurrageOnAccount.status.in_(("paid", "applied")),
        )
        .group_by(DemurrageOnAccount.currency)
    ).all()
    by_ccy = {str(ccy or "USD"): Decimal(str(amount or 0)) for ccy, amount in by_ccy_rows}
    base_ccy = _base_currency(db, auth.tenant_id)
    paid_base, unconverted = _convert_amounts_to_base(
        db,
        auth.tenant_id,
        base_ccy,
        [(amount, ccy) for ccy, amount in by_ccy.items()],
    )
    return {
        **envelope([_on_account_payload(r) for r in rows], total, limit, offset),
        # 本位币口径的「已付」总额（折算后的数）；折不动时给 null 而不是假数
        "on_account_paid": float(paid_base) if not unconverted else None,
        "on_account_paid_currency": base_ccy,
        "on_account_paid_status": "ok" if not unconverted else "cannot_evaluate",
        "on_account_paid_unconverted": {ccy: float(amount) for ccy, amount in unconverted.items()},
        "on_account_paid_by_currency": {
            ccy: float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) for ccy, amount in by_ccy.items()
        },
        **({"currencies": sorted(by_ccy)} if len(by_ccy) > 1 else {}),
    }


def _on_account_payload(r: DemurrageOnAccount) -> dict:
    return {
        "id": str(r.id),
        "laytime_id": str(r.laytime_id),
        "amount": float(r.amount or 0),
        "currency": r.currency,
        "payment_date": r.payment_date.isoformat() if r.payment_date else None,
        "status": r.status,
        "applied_to_settlement": bool(r.applied_to_settlement),
        "notes": r.notes,
    }


class DemurrageRootCauseIn(BaseModel):
    cause: str
    delay_hours: float
    responsible_party: str
    notes: str | None = None


@router.post("/laytimes/{laytime_id}/root-causes")
def create_root_cause(
    laytime_id: UUID,
    body: DemurrageRootCauseIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    if body.cause not in ROOT_CAUSES:
        raise HTTPException(422, detail={"code": "INVALID_CAUSE", "message": f"cause must be one of {list(ROOT_CAUSES)}"})
    if body.responsible_party not in RESPONSIBLE_PARTIES:
        raise HTTPException(
            422,
            detail={"code": "INVALID_RESPONSIBLE_PARTY", "message": f"responsible_party must be one of {list(RESPONSIBLE_PARTIES)}"},
        )
    if body.delay_hours < 0:
        raise HTTPException(422, detail={"code": "INVALID_HOURS", "message": "delay_hours must be >= 0"})
    rec = DemurrageRootCause(
        tenant_id=auth.tenant_id,
        laytime_id=row.id,
        cause=body.cause,
        delay_hours=Decimal(str(body.delay_hours)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        responsible_party=body.responsible_party,
        notes=body.notes,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _root_cause_payload(rec)


def _allocate_amount(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """按权重把 ``total`` 分摊到各行，**合计恒等于 total**（最大余数法）。

    逐行四舍五入再相加会差半分（滞期 100.00 分 3 个原因 → 报 100.00，
    Σ 实为 99.99）（P2-B2）。这里先按精确比例算，再把余下的分按最大余数
    补给余数最大的行。
    """
    if not weights:
        return []
    wsum = sum(weights, Decimal("0"))
    if wsum <= 0 or total == 0:
        return [Decimal("0.00") for _ in weights]
    raw = [total * w / wsum for w in weights]
    out = [r.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for r in raw]
    residual = total - sum(out, Decimal("0"))
    step = Decimal("0.01")
    pennies = int(abs(residual) / step)
    if pennies:
        order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=residual > 0)
        for j in range(pennies):
            out[order[j % len(order)]] += step if residual > 0 else -step
    return out


@router.get("/laytimes/{laytime_id}/root-causes")
def list_root_causes(
    laytime_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """Root causes with the demurrage amount allocated pro-rata by delay hours."""
    row = _get_laytime(auth, db, laytime_id)
    q = (
        select(DemurrageRootCause)
        .where(DemurrageRootCause.tenant_id == auth.tenant_id, DemurrageRootCause.laytime_id == row.id)
        .order_by(DemurrageRootCause.id)
    )
    rows, total = paginate(db, q, limit, offset)
    # 分摊基数覆盖全部分页（SQL sum，而非当前页）
    total_hours = Decimal(
        str(
            db.scalar(
                select(func.coalesce(func.sum(DemurrageRootCause.delay_hours), 0)).where(
                    DemurrageRootCause.tenant_id == auth.tenant_id,
                    DemurrageRootCause.laytime_id == row.id,
                )
            )
            or 0
        )
    )
    demurrage = _demurrage_amount(row)
    # 分摊按**全量**根因算（否则分页时合计对不上）
    all_rows = db.scalars(q).all()
    weights = [Decimal(str(r.delay_hours or 0)) for r in all_rows]
    allocations = _allocate_amount(demurrage, weights) if total_hours > 0 else [Decimal("0.00")] * len(all_rows)
    alloc_by_id = {str(r.id): a for r, a in zip(all_rows, allocations)}
    items = []
    for r in rows:
        share = (Decimal(str(r.delay_hours or 0)) / total_hours) if total_hours > 0 else Decimal("0")
        allocated = alloc_by_id.get(str(r.id), Decimal("0.00"))
        items.append({**_root_cause_payload(r), "share_pct": float((share * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)), "allocated_amount": float(allocated)})
    return {
        **envelope(items, total, limit, offset),
        "total_delay_hours": float(total_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "demurrage_amount": float(demurrage),
        # 全量根因按小时占比分摊滞期：Σ allocated_amount == allocated_total == 滞期额
        "allocated_total": float(sum(allocations, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if total_hours > 0 else 0.0,
    }


def _root_cause_payload(r: DemurrageRootCause) -> dict:
    return {
        "id": str(r.id),
        "laytime_id": str(r.laytime_id),
        "cause": r.cause,
        "delay_hours": float(r.delay_hours or 0),
        "responsible_party": r.responsible_party,
        "notes": r.notes,
    }


class LaytimeDelayIn(BaseModel):
    delay_type: str
    start_at: datetime
    end_at: datetime | None = None
    duration_hours: float | None = None
    excluded_from_laytime: bool = False
    cost_impact: float | None = None
    notes: str | None = None


@router.post("/laytimes/{laytime_id}/delays")
def create_laytime_delay(
    laytime_id: UUID,
    body: LaytimeDelayIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    if body.delay_type not in DELAY_TYPES:
        raise HTTPException(422, detail={"code": "INVALID_DELAY_TYPE", "message": f"delay_type must be one of {list(DELAY_TYPES)}"})
    duration = body.duration_hours
    if body.end_at is not None:
        if body.end_at < body.start_at:
            raise HTTPException(422, detail={"code": "INVALID_PERIOD", "message": "end_at must be >= start_at"})
        if duration is None:
            duration = (body.end_at - body.start_at).total_seconds() / 3600.0
    if duration is not None and duration < 0:
        raise HTTPException(422, detail={"code": "INVALID_DURATION", "message": "duration_hours must be >= 0"})
    rec = LaytimeDelay(
        tenant_id=auth.tenant_id,
        laytime_id=row.id,
        delay_type=body.delay_type,
        start_at=body.start_at,
        end_at=body.end_at,
        duration_hours=Decimal(str(duration)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if duration is not None else None,
        excluded_from_laytime=body.excluded_from_laytime,
        cost_impact=Decimal(str(body.cost_impact)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if body.cost_impact is not None else None,
        notes=body.notes,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _delay_payload(rec)


@router.get("/laytimes/{laytime_id}/delays")
def list_laytime_delays(
    laytime_id: UUID,
    delay_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    row = _get_laytime(auth, db, laytime_id)
    q = (
        select(LaytimeDelay)
        .where(LaytimeDelay.tenant_id == auth.tenant_id, LaytimeDelay.laytime_id == row.id)
        .order_by(LaytimeDelay.id)
    )
    if delay_type is not None:
        q = q.where(LaytimeDelay.delay_type == delay_type)
    rows, total = paginate(db, q, limit, offset)
    # 汇总口径覆盖全部分页（SQL sum，与筛选条件一致）
    agg_base = select(
        func.coalesce(func.sum(LaytimeDelay.duration_hours), 0),
        func.coalesce(
            func.sum(case((LaytimeDelay.excluded_from_laytime.is_(True), LaytimeDelay.duration_hours), else_=0)),
            0,
        ),
        func.coalesce(func.sum(LaytimeDelay.cost_impact), 0),
    ).where(LaytimeDelay.tenant_id == auth.tenant_id, LaytimeDelay.laytime_id == row.id)
    if delay_type is not None:
        agg_base = agg_base.where(LaytimeDelay.delay_type == delay_type)
    total_sum, excluded_sum, cost_sum = db.execute(agg_base).one()
    total_hours = Decimal(str(total_sum or 0))
    excluded_hours = Decimal(str(excluded_sum or 0))
    counted_hours = total_hours - excluded_hours
    cost = Decimal(str(cost_sum or 0))
    return {
        **envelope([_delay_payload(r) for r in rows], total, limit, offset),
        "summary": {
            "total_delay_hours": float(total_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "excluded_hours": float(excluded_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "counted_hours": float(counted_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_cost_impact": float(cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        },
    }


def _delay_payload(r: LaytimeDelay) -> dict:
    return {
        "id": str(r.id),
        "laytime_id": str(r.laytime_id),
        "delay_type": r.delay_type,
        "start_at": r.start_at.isoformat() if r.start_at else None,
        "end_at": r.end_at.isoformat() if r.end_at else None,
        "duration_hours": float(r.duration_hours) if r.duration_hours is not None else None,
        "excluded_from_laytime": bool(r.excluded_from_laytime),
        "cost_impact": float(r.cost_impact) if r.cost_impact is not None else None,
        "notes": r.notes,
    }


@router.get("/laytimes/{laytime_id}/estimated-demurrage")
def estimated_demurrage(
    laytime_id: UUID,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """Estimated demurrage settlement: computed demurrage less on-account payments.

    币种口径（P1-B4）：滞期费金额本身没有币种（计算书引擎只算数字），按**本位币**
    理解；预付款带币种，必须**先折本币再冲抵**。折不动的预付款不参与冲抵，
    并在 ``on_account_status`` 里说明 —— 宁可少冲抵也不能拿没折的钱把
    「未结」算成「已结清」。
    """
    row = _get_laytime(auth, db, laytime_id)
    results = row.results or (compute_laytime(row.inputs or {}) if row.inputs else {})
    demurrage = _demurrage_amount(row)
    on_account_rows = db.scalars(
        select(DemurrageOnAccount).where(
            DemurrageOnAccount.tenant_id == auth.tenant_id,
            DemurrageOnAccount.laytime_id == row.id,
        )
    ).all()
    base_ccy = _base_currency(db, auth.tenant_id)
    paid_base, paid_unconverted = _convert_amounts_to_base(
        db,
        auth.tenant_id,
        base_ccy,
        [
            (Decimal(str(r.amount or 0)), r.currency)
            for r in on_account_rows
            if r.status in ("paid", "applied")
        ],
    )
    pending_base, pending_unconverted = _convert_amounts_to_base(
        db,
        auth.tenant_id,
        base_ccy,
        [
            (Decimal(str(r.amount or 0)), r.currency)
            for r in on_account_rows
            if r.status == "pending"
        ],
    )
    unconverted = {**paid_unconverted, **pending_unconverted}
    settle = settle_with_on_account(demurrage, [paid_base])
    return {
        "laytime_id": str(row.id),
        "status": row.status,
        "result_type": results.get("result_type"),
        "used_hours": results.get("used_hours"),
        "allowed_hours": results.get("allowed_hours"),
        "balance_hours": results.get("balance_hours"),
        "demurrage_amount": settle["demurrage_amount"],
        "on_account_total": settle["on_account_total"],
        "on_account_pending": float(pending_base),
        "outstanding": settle["outstanding"],
        "overpaid": settle["overpaid"],
        "currency": base_ccy,
        "on_account_status": "ok" if not unconverted else "partial",
        "on_account_unconverted": {ccy: float(amount) for ccy, amount in unconverted.items()},
    }


class TimeBarTaskIn(BaseModel):
    time_bar: date | None = None
    days_before: int = 30
    priority: str = "high"
    assignee_user_id: UUID | None = None
    notes: str | None = None


@router.post("/laytimes/{laytime_id}/time-bar-task")
def create_time_bar_task(
    laytime_id: UUID,
    body: TimeBarTaskIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """Generate a follow-up task before the demurrage claim time bar expires.

    Time bar defaults to the latest B/L date on the voyage's port calls +
    TIMEBAR_DAYS_AFTER_BL (same rule as claim creation).
    """
    row = _get_laytime(auth, db, laytime_id)
    time_bar = body.time_bar
    if time_bar is None:
        bl_dates: list[date] = []
        if row.voyage_id:
            for pc in db.scalars(
                select(PortCall).where(PortCall.tenant_id == auth.tenant_id, PortCall.voyage_id == row.voyage_id)
            ).all():
                bl = getattr(pc, "bl_date", None)
                if isinstance(bl, datetime):
                    bl = bl.date()
                if bl:
                    bl_dates.append(bl)
        if not bl_dates:
            raise HTTPException(
                422,
                detail={
                    "code": "TIME_BAR_REQUIRED",
                    "message": "Cannot infer time bar (no B/L dates on the voyage); pass time_bar",
                },
            )
        time_bar = max(bl_dates) + timedelta(days=TIMEBAR_DAYS_AFTER_BL)
    if body.days_before < 0:
        raise HTTPException(422, detail={"code": "INVALID_DAYS", "message": "days_before must be >= 0"})
    if body.assignee_user_id is not None:
        user = db.get(User, body.assignee_user_id)
        if not user or user.tenant_id != auth.tenant_id:
            raise HTTPException(404, "Assignee not found")
    due_at = datetime(time_bar.year, time_bar.month, time_bar.day, tzinfo=timezone.utc) - timedelta(days=body.days_before)
    task = Task(
        tenant_id=auth.tenant_id,
        title=f"Demurrage time bar — laytime {str(row.id)[:8]}",
        description=(
            f"Time bar {time_bar.isoformat()} for laytime {str(row.id)} demurrage claim. "
            f"Submit claim / supporting documents before the bar date."
            + (f" {body.notes}" if body.notes else "")
        ),
        status="todo",
        priority=body.priority,
        due_at=due_at,
        assignee_user_id=body.assignee_user_id,
        created_by=auth.user_id,
        entity_type="laytime",
        entity_id=row.id,
        source="system",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "time_bar": time_bar.isoformat(),
        "entity_type": task.entity_type,
        "entity_id": str(task.entity_id),
    }


# —— Booking-based laytime / laytime types / include-in-freight ——


class LaytimeFromBookingIn(BaseModel):
    """从订舱（cargo booking）生成装卸时间计算。

    booking_reference 落到 LaytimeCalc.booking_reference；cargo_id 可选，给出时
    航次/租约条款（allowed_hours、terms、demurrage/despatch 费率）自动带入。
    """

    booking_reference: str
    cargo_id: UUID | None = None
    voyage_id: UUID | None = None
    port_call_id: UUID | None = None
    allowed_hours: float | None = None
    terms: str | None = None
    demurrage_rate_per_day: float | None = None
    despatch_rate_per_day: float | None = None
    events: list[dict] | None = None
    inputs: dict = Field(default_factory=dict)


@router.post("/laytimes/from-booking")
def laytime_from_booking(
    body: LaytimeFromBookingIn,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    if not body.booking_reference.strip():
        raise HTTPException(422, detail={"code": "BOOKING_REFERENCE_REQUIRED", "message": "booking_reference is required"})
    voyage_id = body.voyage_id
    port_call_id = body.port_call_id
    charter: Charter | None = None
    cargo = None
    if body.cargo_id is not None:
        cargo = scoped_get(db, Cargo, body.cargo_id, auth.tenant_id)
        if cargo is None:
            raise HTTPException(404, "Cargo not found")
        voyage_id = voyage_id or cargo.voyage_id
        if cargo.charter_id:
            charter = scoped_get(db, Charter, cargo.charter_id, auth.tenant_id)
    if voyage_id is not None:
        if scoped_get(db, Voyage, voyage_id, auth.tenant_id) is None:
            raise HTTPException(404, "Voyage not found")
        if charter is None:
            voyage = db.get(Voyage, voyage_id)
            if voyage and voyage.charter_id:
                charter = scoped_get(db, Charter, voyage.charter_id, auth.tenant_id)
    if port_call_id is not None and scoped_get(db, PortCall, port_call_id, auth.tenant_id) is None:
        raise HTTPException(404, "Port call not found")

    allowed = body.allowed_hours
    if allowed is None and cargo is not None:
        derived = _allowed_from_charter(charter, "load")
        if derived is not None:
            allowed = float(derived)
    if allowed is None and body.events:
        raise HTTPException(
            422,
            detail={
                "code": "ALLOWED_HOURS_REQUIRED",
                "message": "Cannot derive allowed hours from the booking (pass allowed_hours or link a cargo with charter rates)",
            },
        )

    inputs: dict = dict(body.inputs or {})
    if allowed is not None:
        inputs["allowed_hours"] = allowed
    inputs["terms"] = body.terms or (charter.laytime_terms if charter and charter.laytime_terms else "SHINC")
    if body.events is not None:
        inputs["events"] = body.events
    if body.demurrage_rate_per_day is not None:
        inputs["demurrage_rate_per_day"] = body.demurrage_rate_per_day
    elif charter and charter.demurrage_rate:
        inputs["demurrage_rate_per_day"] = float(charter.demurrage_rate)
    if body.despatch_rate_per_day is not None:
        inputs["despatch_rate_per_day"] = body.despatch_rate_per_day
    elif charter and charter.despatch_rate:
        inputs["despatch_rate_per_day"] = float(charter.despatch_rate)
    inputs["booking_reference"] = body.booking_reference.strip()

    row = LaytimeCalc(
        tenant_id=auth.tenant_id,
     created_by=auth.user_id,
        voyage_id=voyage_id,
        port_call_id=port_call_id,
        booking_reference=body.booking_reference.strip(),
        status="draft",
        inputs=inputs,
    )
    if inputs.get("events") is not None:
        row.results = compute_laytime(inputs)
        row.status = transition("laytime", row.status, "calculated", LAYTIME_TRANSITIONS)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": str(row.id),
        "status": row.status,
        "booking_reference": row.booking_reference,
        "voyage_id": str(row.voyage_id) if row.voyage_id else None,
        "inputs": row.inputs or {},
        "results": row.results or {},
    }


# 装卸时间条款类型字典（SHINC/SHEX/SHEXUU/WWDSHEX...）——首次读取时播种标准库
LAYTIME_TYPE_SEED = (
    ("SHINC", "Sundays and Holidays Included", "周日/节假日计入", "All calendar time counts against laytime."),
    ("SHEX", "Sundays and Holidays Excluded", "周日/节假日除外", "Sundays and holidays excluded from laytime unless used."),
    ("SHEXUU", "Sundays and Holidays Excluded Unless Used", "周日/节假日除外（除非已使用）", "Excluded periods count once actually used."),
    ("SSHINC", "Saturdays, Sundays and Holidays Included", "周六/周日/节假日计入", "All calendar time including weekends counts."),
    ("SSHEX", "Saturdays, Sundays and Holidays Excluded", "周六/周日/节假日除外", "Weekends and holidays excluded unless used."),
    ("WWDSHEX", "Weather Working Days SHEX", "天气适宜工作日 SHEX", "Weather working days, Sundays/holidays excluded."),
    ("WWDSHEXUU", "Weather Working Days SHEX Unless Used", "天气适宜工作日 SHEX（除非已使用）", "Weather working days SHEX; excluded periods count if used."),
    ("WWDSSHINC", "Weather Working Days SSHINC", "天气适宜工作日 SSHINC", "Weather working days with weekends/holidays counting."),
    ("FHEX", "Fridays and Holidays Excluded", "周五/节假日除外", "Fridays and holidays excluded (Middle East trade)."),
    ("CQD", "Customary Quick Despatch", "按港口习惯尽快装卸", "No fixed laytime; customary quick despatch applies."),
    ("ATUTC", "All Time Used Time Counts", "实际使用时间计入", "All time used counts as laytime."),
)


def _ensure_laytime_types(db: Session) -> list[LaytimeType]:
    rows = db.scalars(select(LaytimeType).order_by(LaytimeType.code)).all()
    if rows:
        return list(rows)
    for code, label_en, label_zh, description in LAYTIME_TYPE_SEED:
        db.add(LaytimeType(code=code, label_en=label_en, label_zh=label_zh, description=description))
    db.commit()
    return list(db.scalars(select(LaytimeType).order_by(LaytimeType.code)).all())


@router.get("/laytimes/types")
def list_laytime_types(
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """Laytime terms dictionary (SHINC/SHEX/SHEXUU/WWDSHEX...)."""
    rows = _ensure_laytime_types(db)
    return {
        "items": [
            {
                "id": str(r.id),
                "code": r.code,
                "label_en": r.label_en,
                "label_zh": r.label_zh,
                "description": r.description,
            }
            for r in rows
        ]
    }


# 注意：本路由必须排在所有 /laytimes/{id} 形态的参数路由之后 —— FastAPI 按声明顺序匹配，
# 参数路由在前会遮蔽字面量路径（历史缺陷：GET /laytimes/types 被 {laytime_id} 吞掉 → 422）。
@router.get("/laytimes/{laytime_id}")
def get_laytime(
    laytime_id: UUID,
    auth: AuthContext = Depends(require_module("laytime")),
    db: Session = Depends(get_db),
):
    """单条滞期费计算书 —— REST 语义的 GET（详情页/外部集成都要用）。"""
    row = scoped_get(db, LaytimeCalc, laytime_id, auth.tenant_id)
    if row is None or row.status == "deleted":
        raise HTTPException(404, "Laytime not found")
    return _laytime_out(row)


class IncludeInFreightIn(BaseModel):
    freight_amount: float = 0
    currency: str = "USD"
    counterparty_id: UUID | None = None
    invoice_no: str | None = None


@router.post("/laytimes/{laytime_id}/include-in-freight")
def include_in_freight(
    laytime_id: UUID,
    body: IncludeInFreightIn | None = None,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """Bill demurrage on the freight invoice: draft freight invoice = base freight
    + settled demurrage (despatch offsets), linked back to the laytime."""
    row = _get_laytime(auth, db, laytime_id)
    payload = body or IncludeInFreightIn()
    results = row.results or (compute_laytime(row.inputs or {}) if row.inputs else {})
    result_type = str(results.get("result_type") or "")
    # 结算额是**本币**金额（计算书引擎没有币种概念，费率按本币理解）
    settlement = Decimal(str(results.get("amount") or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if result_type == "despatch":
        settlement = -settlement
    else:
        settlement = settlement if result_type == "demurrage" else Decimal("0.00")
    freight = Decimal(str(payload.freight_amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # 外币发票必须带汇率（P1-B10）：没有汇率就按 1:1 入账是**错的钱**。
    # 取不到汇率 → fail closed（422），不许静默落库。
    currency = payload.currency or "USD"
    base_ccy = _base_currency(db, auth.tenant_id)
    try:
        fx_rate = require_fx_rate(
            db,
            auth.tenant_id,
            currency,
            base_ccy,
            invoice_type="freight",
            context_date=date.today(),
        )
    except FxRateUnavailable as exc:
        raise HTTPException(
            422,
            detail={
                "code": FX_RATE_NOT_FOUND,
                "message": str(exc),
                "currency": currency,
                "base_currency": base_ccy,
            },
        )
    # 结算额是本币金额、运费是发票币种金额 —— 混币不能直接相加（P1-B4）：
    # 结算额先折成发票币种（1/rate = 本币 → 发票币种），再与运费相加。
    settlement_in_ccy = (
        settlement
        if (currency or "").upper() == (base_ccy or "").upper()
        else money(settlement / fx_rate)
    )
    if freight + settlement_in_ccy <= 0:
        raise HTTPException(
            422,
            detail={"code": "NOTHING_TO_BILL", "message": "freight_amount + demurrage settlement must be > 0"},
        )
    counterparty_id = payload.counterparty_id
    if counterparty_id is not None:
        if scoped_get(db, Counterparty, counterparty_id, auth.tenant_id) is None:
            raise HTTPException(404, "Counterparty not found")
        assert_not_sanctioned(db, auth.tenant_id, counterparty_id)
    else:
        voyage = db.get(Voyage, row.voyage_id) if row.voyage_id else None
        charter = scoped_get(db, Charter, voyage.charter_id, auth.tenant_id) if voyage and voyage.charter_id else None
        counterparty_id = charter.counterparty_id if charter else None
        if counterparty_id:
            assert_not_sanctioned(db, auth.tenant_id, counterparty_id)
    inv = Invoice(
        tenant_id=auth.tenant_id,
        invoice_no=payload.invoice_no or next_doc_number(db, auth.tenant_id, Invoice, Invoice.invoice_no, "INV"),
        invoice_type="freight",
        counterparty_id=counterparty_id,
        voyage_id=row.voyage_id,
        amount=(freight + settlement_in_ccy),
        tax_amount=Decimal("0"),
        currency=currency,
        fx_rate=fx_rate,
        base_amount=to_base_amount(freight + settlement_in_ccy, fx_rate),
        meta={
            "laytime_id": str(row.id),
            "booking_reference": row.booking_reference,
            "freight_amount": float(freight),
            "settlement_amount": float(settlement_in_ccy),
            "settlement_amount_base": float(settlement),
            "result_type": result_type,
            "include_in_freight": True,
        },
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return {
        "id": str(inv.id),
        "invoice_no": inv.invoice_no,
        "invoice_type": inv.invoice_type,
        "status": inv.status,
        "amount": float(inv.amount),
        "freight_amount": float(freight),
        "settlement_amount": float(settlement_in_ccy),
        "settlement_amount_base": float(settlement),
        "laytime_id": str(row.id),
        "currency": inv.currency,
        "fx_rate": float(fx_rate),
        "base_amount": float(inv.base_amount),
    }


