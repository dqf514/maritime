"""实体 → 单据模板上下文。

每个单据类型的 builder 产出**同构**的纯 dict 结构，模板作者按固定形状取值即可：

    no            单据编号
    counterparty  收票方 / 对手方（Bill-To）
    vessel / voyage / charter  相关业务对象
    header        类型专属的头部字段（开票日、账期、装卸率…）
    lines         行项目（无行项目的单据给一条说明行，模板不必写 if 分支）
    totals        合计
    ports         港口作业（有则给）

约束：
- **只返回纯 dict/list/标量** —— 渲染走沙箱 Jinja2，不传 ORM 对象。
- **永不抛异常**：查不到就给空结构，出单不因缺一条外键而 500。
- **一律带 tenant_id 过滤**：本仓库无库级隔离，手写过滤是唯一防线。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

log = logging.getLogger("marios.doc_contexts")


# ── 通用工具 ──────────────────────────────────────────────────────────────


def _s(v: Any) -> Any:
    """Decimal/日期 → 模板可直接用的标量（Decimal 转 float 会丢精度展示，这里保留字符串）。"""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, UUID):
        return str(v)
    return v


def _money(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(Decimal(str(v)))
    except Exception:  # noqa: BLE001
        return None


def _date(v: Any) -> str | None:
    """日期字段 → 只印日期。

    开票日/到期日/交船日在正式单据上印成 "2026-09-14 22:10" 是不对的 ——
    时间戳是系统内部的东西，对外单据只看日期。时间敏感的字段（NOR、靠泊）
    仍走 :func:`_s` 保留时分。
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    text = str(v).strip()
    return text[:10] if len(text) >= 10 else text


def _counterparty_ctx(db: Session, tenant_id: UUID, cp_id: UUID | None) -> dict:
    out = {"name": None, "address": None, "tax_id": None, "registration_no": None,
           "swift_code": None, "email": None, "phone": None, "attention": None}
    if not cp_id:
        return out
    try:
        from app.models_wave1 import Counterparty, CounterpartyContact

        cp = db.scalar(select(Counterparty).where(
            Counterparty.tenant_id == tenant_id, Counterparty.id == cp_id))
        if cp is None:
            return out
        out.update({
            "name": cp.name, "address": cp.address, "tax_id": cp.tax_id,
            "registration_no": cp.registration_no, "swift_code": cp.swift_code,
            "email": cp.email, "phone": cp.phone,
        })
        contact = db.scalar(select(CounterpartyContact).where(
            CounterpartyContact.counterparty_id == cp.id)
            .order_by(CounterpartyContact.is_primary.desc()).limit(1))
        if contact is not None:
            out["attention"] = contact.name
    except Exception:  # noqa: BLE001
        log.exception("doc_contexts: counterparty lookup failed")
    return out


def _vessel_ctx(db: Session, tenant_id: UUID, vessel_id: UUID | None) -> dict:
    out = {"name": None, "imo": None, "flag": None, "dwt": None, "vessel_type": None}
    if not vessel_id:
        return out
    try:
        from app.models_wave1 import Vessel

        v = db.scalar(select(Vessel).where(
            Vessel.tenant_id == tenant_id, Vessel.id == vessel_id))
        if v is not None:
            out = {"name": v.name, "imo": v.imo, "flag": v.flag,
                   "dwt": _s(v.dwt), "vessel_type": v.vessel_type}
    except Exception:  # noqa: BLE001
        log.exception("doc_contexts: vessel lookup failed")
    return out


def _voyage_ctx(db: Session, tenant_id: UUID, voyage_id: UUID | None) -> dict:
    out = {"voyage_no": None, "status": None, "cargo": None, "cp_date": None, "id": None}
    if not voyage_id:
        return out
    try:
        from app.models_domain import Voyage

        v = db.scalar(select(Voyage).where(
            Voyage.tenant_id == tenant_id, Voyage.id == voyage_id))
        if v is not None:
            out = {"voyage_no": v.voyage_no, "status": v.status, "cargo": v.cargo,
                   "cp_date": _date(v.cp_date), "id": str(v.id)}
    except Exception:  # noqa: BLE001
        log.exception("doc_contexts: voyage lookup failed")
    return out


def _port_ctx(db: Session, tenant_id: UUID, port_id: UUID | None) -> dict:
    out = {"name": None, "unlocode": None, "country": None}
    if not port_id:
        return out
    try:
        from app.models_wave1 import Port

        p = db.get(Port, port_id)
        if p is not None and p.tenant_id == tenant_id:
            out = {"name": p.name, "unlocode": p.unlocode, "country": p.country}
    except Exception:  # noqa: BLE001
        log.exception("doc_contexts: port lookup failed")
    return out


def _port_calls(db: Session, tenant_id: UUID, voyage_id: UUID | None) -> list[dict]:
    """航次的港口作业序列 —— 计算书 / 事实记录 / 航次指令共用。"""
    if not voyage_id:
        return []
    try:
        from app.models_domain import PortCall

        rows = db.scalars(select(PortCall).where(
            PortCall.tenant_id == tenant_id, PortCall.voyage_id == voyage_id,
            PortCall.deleted_at.is_(None)).order_by(PortCall.seq)).all()
    except Exception:  # noqa: BLE001
        log.exception("doc_contexts: port calls lookup failed")
        return []
    out = []
    for pc in rows:
        port = _port_ctx(db, tenant_id, pc.port_id)
        out.append({
            "seq": pc.seq, "purpose": pc.purpose, "function_code": pc.function_code,
            "port": port["name"], "unlocode": port["unlocode"], "country": port["country"],
            "eta": _s(pc.eta), "etd": _s(pc.etd), "ata": _s(pc.ata), "atd": _s(pc.atd),
            "nor_at": _s(pc.nor_at), "bl_date": _date(pc.bl_date), "agent": pc.agent,
            "id": str(pc.id),
        })
    return out


def _line(description: str, *, qty=None, unit=None, rate=None, amount=None, note=None) -> dict:
    return {"description": description, "qty": _s(qty), "unit": unit,
            "rate": _s(rate), "amount": _money(amount), "note": note}


class _Blank:
    """缺字段占位 —— 打印为空串，参与逻辑/迭代时不炸。

    模板里 ``{{ totals.foo | money }}`` 在字段缺失时应当印空白栏，
    既不能 500，也不该印出 "None"。
    """

    def __str__(self) -> str:
        return ""

    def __repr__(self) -> str:
        return ""

    def __bool__(self) -> bool:
        return False

    def __iter__(self):
        return iter(())  # 让 | join / for 循环拿到空集合而不是异常

    def __eq__(self, other) -> bool:
        return other is None or other == ""

    def __hash__(self) -> int:
        return hash(None)


class _Section(dict):
    """模板友好的空分节 —— 缺键返回 :class:`_Blank` 而不是抛错。

    模板写 ``{{ header.foo }}`` 时，Jinja 先 ``getattr`` 再 ``obj['foo']``。
    普通 dict 两步都失败 → StrictUndefined → 出单失败；于是"这张发票还没填
    对手方"就变成了 500。缺字段应当印空白栏。
    """

    def __missing__(self, key):
        return _Blank()


def _base(no: str | None = None) -> dict:
    return {
        "no": no,
        # 与 _counterparty_ctx / _vessel_ctx / _voyage_ctx 的键集保持同步
        "counterparty": _Section({
            "name": None, "address": None, "tax_id": None, "registration_no": None,
            "swift_code": None, "email": None, "phone": None, "attention": None}),
        "vessel": _Section({"name": None, "imo": None, "flag": None,
                            "dwt": None, "vessel_type": None}),
        "voyage": _Section({"voyage_no": None, "status": None, "cargo": None,
                            "cp_date": None, "id": None}),
        # charter/header/totals 的键随单据类型不同 —— 缺键由 _Section 兜底
        "charter": _Section(),
        "header": _Section(),
        "lines": [],
        "totals": _Section(),
        "ports": [],
        # 引擎计算告警（如时区缺失、事件重叠）—— 计算书类模板会印在脚注
        "warnings": [],
    }


def as_sections(obj: Any) -> Any:
    """递归把普通 dict 换成 :class:`_Section` —— 渲染入口统一调用。

    各 builder 里 ``out["header"] = {...}`` 是直接赋值，会把 ``_base()``
    里已经包好的 ``_Section`` 换回普通 dict；逐处包裹容易漏。在渲染入口做一次
    深转换，既覆盖 builder 的直接赋值，也覆盖预览端点自行拼的 payload。
    """
    if isinstance(obj, dict):
        return _Section({k: as_sections(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return [as_sections(v) for v in obj]
    return obj


# ── 各单据类型的上下文 ────────────────────────────────────────────────────


def _ctx_invoice(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_domain import Invoice

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(Invoice).where(
        Invoice.tenant_id == tenant_id, Invoice.id == entity_id))
    if row is None:
        return out
    out["no"] = row.invoice_no
    out["counterparty"] = _counterparty_ctx(db, tenant_id, row.counterparty_id)
    out["vessel"] = _vessel_ctx(db, tenant_id, None)
    out["voyage"] = _voyage_ctx(db, tenant_id, row.voyage_id)
    if row.voyage_id:
        vid = _voyage_vessel_id(db, tenant_id, row.voyage_id)
        if vid:
            out["vessel"] = _vessel_ctx(db, tenant_id, vid)
    out["header"] = {
        "invoice_type": row.invoice_type, "status": row.status,
        "issue_date": _date(row.issued_at), "due_date": _date(row.due_date),
        "currency": row.currency, "tax_amount": _money(row.tax_amount),
        "amount_paid": _money(row.paid_amount), "bill_by": row.bill_by,
        "commission_basis": row.commission_basis,
    }
    # 系统内发票目前只有头金额、无行项目表 —— 合成一条说明行，模板不必写空表判断
    amount = _money(row.amount) or 0.0
    # 单据类型已在 Details 区显示，行备注不再重复印原始代码
    out["lines"] = [_line(_invoice_type_label(row.invoice_type), amount=amount)]
    if row.tax_amount:
        out["lines"].append(_line("Tax", amount=_money(row.tax_amount)))
    total = amount + (_money(row.tax_amount) or 0.0)
    out["totals"] = {
        "subtotal": amount, "tax": _money(row.tax_amount), "total": total,
        "amount_paid": _money(row.paid_amount),
        "balance": total - (_money(row.paid_amount) or 0.0),
        "currency": row.currency,
    }
    return out


def _voyage_vessel_id(db: Session, tenant_id: UUID, voyage_id: UUID) -> UUID | None:
    """航次上挂的船 —— 发票头没有 vessel_id，只能从 voyage 反查。"""
    try:
        from app.models_domain import Voyage

        v = db.scalar(select(Voyage.vessel_id).where(
            Voyage.tenant_id == tenant_id, Voyage.id == voyage_id))
        return v
    except Exception:  # noqa: BLE001
        return None


_INVOICE_TYPE_LABELS = {
    "FRT": "Freight", "DEM": "Demurrage", "TCIP": "Time charter hire",
    "TCOB": "Hire (owner's account)", "PDA": "Proforma disbursement account",
    "FDA": "Final disbursement account", "BKR": "Bunker",
    "XEXP": "Extra expense", "XREV": "Credit note", "XDIFF": "Rate difference",
    "freight": "Freight", "credit_note": "Credit note",
}


def _invoice_type_label(code: str | None) -> str:
    return _INVOICE_TYPE_LABELS.get(code or "", "Invoice")


def _ctx_credit_note(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_finance_ext import CreditNote
    from app.models_domain import Invoice

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(CreditNote).where(
        CreditNote.tenant_id == tenant_id, CreditNote.id == entity_id))
    if row is None:
        # 允许直接传原发票 id —— 出该发票对应的贷记单
        inv = db.scalar(select(Invoice).where(
            Invoice.tenant_id == tenant_id, Invoice.id == entity_id))
        if inv is None:
            return out
        cn = db.scalar(select(CreditNote).where(CreditNote.invoice_id == inv.id))
        if cn is None:
            return out
        row = cn
    out["no"] = row.credit_note_no
    inv = db.get(Invoice, row.invoice_id) if row.invoice_id else None
    if inv is not None:
        out["counterparty"] = _counterparty_ctx(db, tenant_id, inv.counterparty_id)
        out["voyage"] = _voyage_ctx(db, tenant_id, inv.voyage_id)
        out["header"]["original_invoice_no"] = inv.invoice_no
        out["header"]["currency"] = inv.currency
    out["header"].update({
        "status": row.status, "issue_date": _date(row.issued_at or row.created_at),
        "reason": row.reason, "currency": out["header"].get("currency") or "USD",
    })
    out["lines"] = [_line("Credit against invoice",
                          amount=_money(row.amount), note=row.reason)]
    out["totals"] = {"subtotal": _money(row.amount) or 0.0, "tax": 0.0,
                     "total": _money(row.amount) or 0.0,
                     "currency": out["header"].get("currency")}
    return out


def _ctx_laytime_statement(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_domain import LaytimeCalc

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(LaytimeCalc).where(
        LaytimeCalc.tenant_id == tenant_id, LaytimeCalc.id == entity_id))
    if row is None:
        return out
    out["no"] = row.booking_reference or f"LT-{str(row.id)[:8].upper()}"
    out["voyage"] = _voyage_ctx(db, tenant_id, row.voyage_id)
    if row.voyage_id:
        vid = _voyage_vessel_id(db, tenant_id, row.voyage_id)
        out["vessel"] = _vessel_ctx(db, tenant_id, vid)
    out["ports"] = _port_calls(db, tenant_id, row.voyage_id)
    if row.port_call_id:
        pc = out["ports"] or [{}]
        # 只算单港时，把该港提到上下文里
        found = [p for p in out["ports"] if p.get("id") == str(row.port_call_id)]
        if found:
            out["header"]["port"] = found[0].get("port")

    inputs = dict(row.inputs or {})
    results = dict(row.results or {})
    out["header"].update({
        "status": row.status, "booking_reference": row.booking_reference,
        "terms": results.get("terms") or inputs.get("terms"),
        "allowed_hours": _s(results.get("allowed_hours") or inputs.get("allowed_hours")),
        "demurrage_rate": _s(inputs.get("demurrage_rate_per_day")),
        "despatch_rate": _s(inputs.get("despatch_rate_per_day")),
        "currency": results.get("currency") or "USD",
    })
    # 事件表明细 —— 计算书的正文（时间账）
    events = results.get("events") or []
    out["lines"] = [
        {
            "description": (e.get("note") or e.get("kind") or "event"),
            "start": e.get("start"), "end": e.get("end"),
            "qty": _s(e.get("gross_hours")), "unit": "h",
            "rate": None, "amount": _s(e.get("counted_hours")),
            "excluded": bool(e.get("caller_excluded") or e.get("term_excluded_hours")),
            "cumulative": _s(e.get("cumulative_hours")),
        }
        for e in events
    ]
    if not out["lines"]:
        out["lines"] = [_line("Laytime time used", qty=results.get("used_hours"), unit="h",
                              amount=None, note="no event detail on this calculation")]
    result_type = results.get("result_type") or "on_time"
    out["totals"] = {
        "allowed_hours": _s(results.get("allowed_hours")),
        "used_hours": _s(results.get("used_hours")),
        "excluded_hours": _s(results.get("excluded_hours")),
        "balance_hours": _s(results.get("balance_hours")),
        "result_type": result_type,
        "result_label": {"demurrage": "Demurrage due", "despatch": "Despatch due",
                         "on_time": "Within laytime"}.get(result_type, result_type),
        "amount": _money(results.get("amount")) or 0.0,
        "currency": results.get("currency") or "USD",
    }
    out["warnings"] = results.get("warnings") or []
    return out


def _ctx_hire_statement(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_time_charter import HireStatement, TimeCharterContract

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(HireStatement).where(
        HireStatement.tenant_id == tenant_id, HireStatement.id == entity_id))
    if row is None:
        return out
    out["no"] = row.statement_number
    contract = db.scalar(select(TimeCharterContract).where(
        TimeCharterContract.tenant_id == tenant_id,
        TimeCharterContract.id == row.contract_id)) if row.contract_id else None
    if contract is not None:
        out["vessel"] = _vessel_ctx(db, tenant_id, contract.vessel_id)
        out["counterparty"] = _counterparty_ctx(db, tenant_id, contract.counterparty_id)
        out["charter"] = {
            "contract_type": contract.contract_type,
            "contract_style": contract.contract_style,
            "hire_rate": _s(contract.hire_rate),
            "hire_currency": contract.hire_currency,
            "payment_frequency": contract.payment_frequency,
            "delivery_port": contract.delivery_port,
            "redelivery_port": contract.redelivery_port,
            "delivery_date": _date(contract.delivery_date),
            "redelivery_date": _date(contract.redelivery_date),
        }
    out["header"] = {
        "status": row.status, "period_start": _date(row.period_start),
        "period_end": _date(row.period_end), "currency": row.currency,
        "payment_frequency": out["charter"].get("payment_frequency"),
    }
    breakdown = dict(row.breakdown or {})
    lines = breakdown.get("lines") or []
    out["lines"] = [
        _line(str(l.get("label") or "Adjustment"),
              qty=l.get("days"), unit="days" if l.get("days") is not None else None,
              rate=l.get("rate"), amount=l.get("amount"))
        for l in lines if isinstance(l, dict)
    ]
    if not out["lines"]:
        # 明细缺失时用汇总字段兜底，模板仍然印得出完整账单
        out["lines"] = [
            _line("Gross hire", amount=_money(row.gross_hire)),
            _line("Off-hire deduction", amount=-(_money(row.off_hire_deduction) or 0.0)),
        ]
        if row.other_adjustments:
            out["lines"].append(_line("Other adjustments", amount=_money(row.other_adjustments)))
        if row.bunker_adjustment:
            out["lines"].append(_line("Bunker adjustment", amount=_money(row.bunker_adjustment)))
    out["totals"] = {
        "hire_days": _s(row.hire_days), "off_hire_days": _s(row.off_hire_days),
        "gross_hire": _money(row.gross_hire) or 0.0,
        "off_hire_deduction": _money(row.off_hire_deduction) or 0.0,
        "bunker_adjustment": _money(row.bunker_adjustment) or 0.0,
        "other_adjustments": _money(row.other_adjustments) or 0.0,
        "total": _money(row.net_hire) or 0.0,
        "currency": row.currency,
    }
    return out


def _ctx_charter_recap(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_domain import Charter

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(Charter).where(
        Charter.tenant_id == tenant_id, Charter.id == entity_id))
    if row is None:
        return out
    out["no"] = row.charter_no
    out["vessel"] = _vessel_ctx(db, tenant_id, row.vessel_id)
    out["counterparty"] = _counterparty_ctx(db, tenant_id, row.counterparty_id)
    # Charter 表只有交船/还船港列 —— 航次租船语境下即装港/卸港
    lp = _port_ctx(db, tenant_id, row.delivery_port_id)
    dp = _port_ctx(db, tenant_id, row.redelivery_port_id)
    out["ports"] = [
        {"seq": 1, "purpose": "load", "port": lp["name"], "unlocode": lp["unlocode"],
         "rate": _s(row.load_rate_pd)},
        {"seq": 2, "purpose": "discharge", "port": dp["name"], "unlocode": dp["unlocode"],
         "rate": _s(row.disch_rate_pd)},
    ]
    out["header"] = {
        "status": row.status, "charter_type": row.charter_type, "cp_form": row.cp_form,
        "laycan_from": _date(row.laycan_from), "laycan_to": _date(row.laycan_to),
        "cargo_qty": _s(row.cargo_qty), "bill_by": row.bill_by,
        "tolerance_pct": _s(row.tolerance_pct), "overage_pct": _s(row.overage_pct),
        "laytime_terms": row.laytime_terms,
        "commission_pct": _s(row.commission_pct),
        "address_comm_pct": _s(row.address_comm_pct), "brokerage_pct": _s(row.brokerage_pct),
        "freight_rate": _s(row.freight_rate), "freight_basis": row.freight_basis,
        "demurrage_rate": _s(row.demurrage_rate), "despatch_rate": _s(row.despatch_rate),
        "currency": "USD",
    }
    fr = _money(row.freight_rate) or 0.0
    qty = _money(row.cargo_qty) or 0.0
    if (row.freight_basis or "per_mt") == "lumpsum":
        freight_total = fr
    else:
        freight_total = fr * qty
    out["lines"] = [
        _line("Freight", qty=qty, unit="MT" if row.bill_by != "measure" else None,
              rate=fr, amount=freight_total,
              note=row.freight_basis),
    ]
    out["totals"] = {
        "total": freight_total, "currency": out["header"]["currency"],
        "freight_basis": row.freight_basis,
    }
    return out


def _ctx_estimate(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_domain import Estimate

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(Estimate).where(
        Estimate.tenant_id == tenant_id, Estimate.id == entity_id))
    if row is None:
        return out
    out["no"] = f"EST-{str(row.id)[:8].upper()}"
    out["vessel"] = _vessel_ctx(db, tenant_id, row.vessel_id)
    out["counterparty"] = _counterparty_ctx(db, tenant_id, row.counterparty_id)
    inputs = dict(row.inputs or {})
    results = dict(row.results or {})
    out["header"] = {
        "title": row.title, "mode": row.mode, "status": row.status, "version": row.version,
        "currency": results.get("currency") or inputs.get("currency") or "USD",
        "freight_basis": results.get("freight_basis") or inputs.get("freight_basis"),
        "sea_days": _s(results.get("sea_days")), "port_days": _s(results.get("port_days")),
        "total_days": _s(results.get("total_days")),
        "cargo_qty": _s(inputs.get("cargo_qty")),
        "freight_rate": _s(inputs.get("freight_rate")),
        "bunker_price": _s(inputs.get("bunker_price")),
        "emissions_cost": _s(results.get("emissions_cost")),
    }
    rev = _money(results.get("total_revenue")) or 0.0
    out["lines"] = [
        _line("Gross freight / revenue", amount=_money(results.get("gross_freight")) or rev),
        _line("Commissions", amount=-abs(_money(results.get("commission")) or 0.0)),
        _line("Bunker cost", amount=-abs(_money(results.get("bunker_cost")) or 0.0)),
        _line("Port & canal & other costs", amount=-abs(_money(results.get("voyage_cost")) or 0.0)),
    ]
    if results.get("emissions_cost"):
        out["lines"].append(_line("Emissions cost (EU ETS / FuelEU)",
                                  amount=-abs(_money(results.get("emissions_cost")) or 0.0)))
    if results.get("hire_cost"):
        out["lines"].append(_line("Hire", amount=-abs(_money(results.get("hire_cost")) or 0.0)))
    out["totals"] = {
        "total_revenue": rev,
        "total_cost": (_money(results.get("bunker_cost")) or 0.0)
        + (_money(results.get("voyage_cost")) or 0.0)
        + (_money(results.get("emissions_cost")) or 0.0),
        "total": _money(results.get("net_result")) or 0.0,
        "tce": _money(results.get("tce")) or 0.0,
        "currency": out["header"]["currency"],
    }
    return out


def _ctx_pda(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_domain import PortDisbursement

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(PortDisbursement).where(
        PortDisbursement.tenant_id == tenant_id, PortDisbursement.id == entity_id))
    if row is None:
        return out
    out["no"] = f"PDA-{str(row.id)[:8].upper()}"
    out["voyage"] = _voyage_ctx(db, tenant_id, row.voyage_id)
    if row.voyage_id:
        vid = _voyage_vessel_id(db, tenant_id, row.voyage_id)
        out["vessel"] = _vessel_ctx(db, tenant_id, vid)
    pcs = _port_calls(db, tenant_id, row.voyage_id)
    if row.port_call_id:
        pcs = [p for p in pcs if p.get("id") == str(row.port_call_id)] or pcs
    out["ports"] = pcs
    if pcs:
        out["header"]["port"] = pcs[0].get("port")
        out["header"]["agent"] = pcs[0].get("agent")
    out["header"].update({
        "status": row.status, "currency": row.currency,
        "pda_amount": _money(row.pda_amount), "fda_amount": _money(row.fda_amount),
        "variance": _money(row.variance),
    })
    # lines 是无 schema 的自由 JSON —— 同时兼容 {label: amount} 与 [{label, amount}]
    raw = row.lines or {}
    lines: list[dict] = []
    if isinstance(raw, list):
        for l in raw:
            if isinstance(l, dict):
                lines.append(_line(str(l.get("label") or l.get("description") or "Charge"),
                                   amount=l.get("amount"), qty=l.get("qty"),
                                   unit=l.get("unit"), rate=l.get("rate"), note=l.get("note")))
    elif isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                lines.append(_line(str(v.get("label") or k), amount=v.get("amount"),
                                   qty=v.get("qty"), unit=v.get("unit"),
                                   rate=v.get("rate"), note=v.get("note")))
            else:
                lines.append(_line(str(k), amount=v))
    out["lines"] = lines or [_line("No disbursement lines recorded", note="add lines on the voyage workspace")]
    total = _money(row.fda_amount) if row.fda_amount is not None else _money(row.pda_amount)
    out["totals"] = {"total": total or 0.0, "currency": row.currency,
                     "pda_amount": _money(row.pda_amount), "fda_amount": _money(row.fda_amount)}
    return out


def _ctx_claim(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_domain import Claim

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(Claim).where(
        Claim.tenant_id == tenant_id, Claim.id == entity_id))
    if row is None:
        return out
    out["no"] = row.claim_no
    out["voyage"] = _voyage_ctx(db, tenant_id, row.voyage_id)
    if row.voyage_id:
        vid = _voyage_vessel_id(db, tenant_id, row.voyage_id)
        out["vessel"] = _vessel_ctx(db, tenant_id, vid)
    out["header"] = {
        "status": row.status, "claim_type": row.claim_type, "subtype": row.subtype,
        "time_bar": _date(row.time_bar), "currency": row.currency, "notes": row.notes,
        "settlement_amount": _money(row.settlement_amount),
    }
    deductions = row.deductions or []
    lines = [_line("Claim amount", amount=_money(row.amount))]
    for d in deductions if isinstance(deductions, list) else []:
        if isinstance(d, dict):
            lines.append(_line(str(d.get("reason") or "Deduction"),
                               amount=-abs(_money(d.get("amount")) or 0.0)))
    out["lines"] = lines
    total = _money(row.amount) or 0.0
    ded = sum(abs(_money(d.get("amount")) or 0.0)
              for d in deductions if isinstance(d, dict)) if isinstance(deductions, list) else 0.0
    out["totals"] = {"total": _money(row.settlement_amount) or (total - ded),
                     "gross": total, "deductions": ded, "currency": row.currency}
    return out


def _ctx_sof(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    """SOF 按 port_call 组织 —— 传 port_call_id（或 voyage id，取首个作业港）。"""
    from app.models_domain import PortCall, SofEvent

    out = _base()
    if not entity_id:
        return out
    pc = db.scalar(select(PortCall).where(
        PortCall.tenant_id == tenant_id, PortCall.id == entity_id))
    if pc is None:
        # 允许传 voyage id
        pcs = db.scalars(select(PortCall).where(
            PortCall.tenant_id == tenant_id, PortCall.voyage_id == entity_id)
            .order_by(PortCall.seq)).all()
        pc = pcs[0] if pcs else None
    if pc is None:
        return out
    out["no"] = f"SOF-{str(pc.id)[:8].upper()}"
    out["voyage"] = _voyage_ctx(db, tenant_id, pc.voyage_id)
    if pc.voyage_id:
        vid = _voyage_vessel_id(db, tenant_id, pc.voyage_id)
        out["vessel"] = _vessel_ctx(db, tenant_id, vid)
    port = _port_ctx(db, tenant_id, pc.port_id)
    out["header"] = {
        "port": port["name"], "unlocode": port["unlocode"],
        "eta": _s(pc.eta), "etd": _s(pc.etd), "ata": _s(pc.ata), "atd": _s(pc.atd),
        "nor_at": _s(pc.nor_at), "agent": pc.agent, "timezone": pc.timezone,
        "purpose": pc.purpose,
    }
    out["ports"] = [{"seq": pc.seq, "purpose": pc.purpose, "port": port["name"],
                     "unlocode": port["unlocode"], "eta": _s(pc.eta), "etd": _s(pc.etd),
                     "ata": _s(pc.ata), "atd": _s(pc.atd), "nor_at": _s(pc.nor_at)}]
    events = db.scalars(select(SofEvent).where(
        SofEvent.tenant_id == tenant_id, SofEvent.port_call_id == pc.id,
        SofEvent.deleted_at.is_(None))
        .order_by(SofEvent.event_at)).all()
    out["lines"] = [
        {"description": e.event_code, "start": _s(e.event_at), "end": None,
         "qty": None, "unit": None, "rate": None, "amount": None,
         "note": e.remarks, "excluded": False, "cumulative": None}
        for e in events
    ] or [_line("No events recorded", note="add SOF events on the voyage workspace")]
    return out


def _ctx_coa(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_coa import CoaContract, CoaItinerary

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(CoaContract).where(
        CoaContract.tenant_id == tenant_id, CoaContract.id == entity_id))
    if row is None:
        return out
    out["no"] = row.coa_no
    if row.charter_id:
        from app.models_domain import Charter

        ch = db.scalar(select(Charter).where(
            Charter.tenant_id == tenant_id, Charter.id == row.charter_id))
        if ch is not None:
            out["counterparty"] = _counterparty_ctx(db, tenant_id, ch.counterparty_id)
            out["vessel"] = _vessel_ctx(db, tenant_id, ch.vessel_id)
    out["header"] = {
        "status": row.status, "period_from": _date(row.period_from),
        "period_to": _date(row.period_to), "qty_unit": row.qty_unit,
        "total_qty": _s(row.total_qty), "rate_basis": row.rate_basis,
        "rate": _s(row.rate), "currency": row.currency, "cargo_spec": row.cargo_spec,
        "tolerance_pct": _s(row.tolerance_pct), "overage_pct": _s(row.overage_pct),
    }
    its = db.scalars(select(CoaItinerary).where(
        CoaItinerary.tenant_id == tenant_id, CoaItinerary.coa_contract_id == row.id)
        .order_by(CoaItinerary.seq)).all()
    lines = []
    for it in its:
        lp = _port_ctx(db, tenant_id, it.load_port_id)
        dp = _port_ctx(db, tenant_id, it.disch_port_id)
        lines.append(_line(f"{lp['name'] or '—'} → {dp['name'] or '—'}",
                           qty=it.qty, unit=row.qty_unit, note=it.notes))
    out["lines"] = lines or [_line("Liftings are allocated on the COA workspace")]
    out["totals"] = {"total_qty": _s(row.total_qty) or 0.0, "unit": row.qty_unit,
                     "currency": row.currency, "rate": _s(row.rate),
                     "total": (_money(row.rate) or 0.0) * (_money(row.total_qty) or 0.0)
                     if row.rate_basis == "per_mt" else (_money(row.rate) or 0.0)}
    return out


def _ctx_voyage_instruction(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    from app.models_domain import Voyage

    out = _base()
    if not entity_id:
        return out
    row = db.scalar(select(Voyage).where(
        Voyage.tenant_id == tenant_id, Voyage.id == entity_id))
    if row is None:
        return out
    out["no"] = f"VI-{row.voyage_no or str(row.id)[:8].upper()}"
    out["voyage"] = _voyage_ctx(db, tenant_id, row.id)
    out["vessel"] = _vessel_ctx(db, tenant_id, row.vessel_id)
    out["ports"] = _port_calls(db, tenant_id, row.id)
    meta = dict(row.meta or {})
    out["header"] = {
        "status": row.status, "cargo": row.cargo, "cp_date": _date(row.cp_date),
        "voyage_no": row.voyage_no, "notes": meta.get("instruction") or meta.get("notes"),
    }
    out["lines"] = [
        {"description": f"{p['seq']}. {p['purpose'] or ''} {p['port'] or ''}".strip(),
         "start": p.get("eta"), "end": p.get("etd"),
         "qty": None, "unit": None, "rate": None, "amount": None,
         "note": p.get("agent"), "excluded": False, "cumulative": None}
        for p in out["ports"]
    ] or [_line("No port calls planned yet")]
    return out


def _ctx_statement_of_account(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    """对账单 —— 传 counterparty_id，汇总该对手方的未结发票。"""
    from app.models_domain import Invoice

    out = _base()
    if not entity_id:
        return out
    out["counterparty"] = _counterparty_ctx(db, tenant_id, entity_id)
    out["no"] = f"SOA-{str(entity_id)[:8].upper()}"
    invs = db.scalars(select(Invoice).where(
        Invoice.tenant_id == tenant_id, Invoice.counterparty_id == entity_id)
        .order_by(Invoice.issued_at)).all()
    lines, total, paid = [], 0.0, 0.0
    for inv in invs:
        amt = _money(inv.amount) or 0.0
        tax = _money(inv.tax_amount) or 0.0
        p = _money(inv.paid_amount) or 0.0
        bal = amt + tax - p
        total += amt + tax
        paid += p
        lines.append({
            "description": f"{inv.invoice_no} · {_invoice_type_label(inv.invoice_type)}",
            "start": _s(inv.issued_at), "end": _s(inv.due_date),
            "qty": None, "unit": None, "rate": None, "amount": bal,
            "note": inv.status, "excluded": False, "cumulative": None,
        })
    out["lines"] = lines or [_line("No invoices on account")]
    out["totals"] = {"total": total - paid, "gross": total, "amount_paid": paid,
                     "currency": invs[0].currency if invs else "USD"}
    return out


def _ctx_remittance_advice(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    """汇款通知 —— 传 payment_batch_id。"""
    out = _base()
    if not entity_id:
        return out
    try:
        from app.models_finance_ext import PaymentBatch

        row = db.scalar(select(PaymentBatch).where(
            PaymentBatch.tenant_id == tenant_id, PaymentBatch.id == entity_id))
    except Exception:  # noqa: BLE001
        log.exception("doc_contexts: payment batch lookup failed")
        return out
    if row is None:
        return out
    out["no"] = getattr(row, "batch_number", None) or f"RA-{str(row.id)[:8].upper()}"
    out["header"] = {"status": getattr(row, "status", None),
                     "currency": getattr(row, "currency", None),
                     "value_date": _date(getattr(row, "batch_date", None)),
                     "total": _money(getattr(row, "total_amount", None))}
    out["lines"] = [_line("Remittance total", amount=_money(getattr(row, "total_amount", None)))]
    out["totals"] = {"total": _money(getattr(row, "total_amount", None)) or 0.0,
                     "currency": getattr(row, "currency", None)}
    return out


def _ctx_bdn(db: Session, tenant_id: UUID, entity_id: UUID | None) -> dict:
    """供油报告 —— 传 bunker_order_id。"""
    out = _base()
    if not entity_id:
        return out
    try:
        from app.models_domain import BunkerOrder

        row = db.scalar(select(BunkerOrder).where(
            BunkerOrder.tenant_id == tenant_id, BunkerOrder.id == entity_id))
    except Exception:  # noqa: BLE001
        log.exception("doc_contexts: bunker order lookup failed")
        return out
    if row is None:
        return out
    out["no"] = getattr(row, "order_no", None) or f"BDN-{str(row.id)[:8].upper()}"
    out["voyage"] = _voyage_ctx(db, tenant_id, getattr(row, "voyage_id", None))
    if getattr(row, "vessel_id", None):
        out["vessel"] = _vessel_ctx(db, tenant_id, row.vessel_id)
    elif out["voyage"].get("voyage_no"):
        vid = _voyage_vessel_id(db, tenant_id, row.voyage_id)
        out["vessel"] = _vessel_ctx(db, tenant_id, vid)
    qty = _s(getattr(row, "qty_delivered", None))
    price = _s(getattr(row, "unit_price", None))
    out["header"] = {
        "status": getattr(row, "status", None),
        "grade": getattr(row, "grade", None) or getattr(row, "fuel_grade", None),
        "quantity_mt": qty, "price_per_mt": price,
        "delivery_date": _date(getattr(row, "bdn_date", None)),
        "currency": getattr(row, "currency", None) or "USD",
    }
    out["lines"] = [_line(str(out["header"]["grade"] or "Bunker"), qty=qty, unit="MT",
                          rate=price, amount=(qty or 0) * (price or 0) if price else None)]
    out["totals"] = {"total": (qty or 0) * (price or 0) if price else 0.0,
                     "quantity_mt": qty, "currency": out["header"]["currency"]}
    return out


_BUILDERS = {
    "invoice": _ctx_invoice,
    "credit_note": _ctx_credit_note,
    "laytime_statement": _ctx_laytime_statement,
    "hire_statement": _ctx_hire_statement,
    "charter_recap": _ctx_charter_recap,
    "estimate": _ctx_estimate,
    "pda": _ctx_pda,
    "claim": _ctx_claim,
    "sof": _ctx_sof,
    "coa": _ctx_coa,
    "voyage_instruction": _ctx_voyage_instruction,
    "statement_of_account": _ctx_statement_of_account,
    "remittance_advice": _ctx_remittance_advice,
    "bdn": _ctx_bdn,
}


def build_context(db: Session, tenant_id: UUID, entity_type: str, entity_id: UUID | None) -> dict:
    """实体 → 模板上下文。永不抛异常：查不到给空骨架，出单不因缺外键而失败。"""
    fn = _BUILDERS.get(entity_type)
    if fn is None:
        return _base()
    try:
        return fn(db, tenant_id, entity_id)
    except Exception:  # noqa: BLE001 — 出单优先，结构缺失也印得出
        log.exception("doc_contexts: build failed for %s", entity_type)
        return _base()


# ── 示例数据（模板编辑器实时预览用） ──────────────────────────────────────

_SAMPLE_DATE = "2026-03-14"


def sample_context(entity_type: str) -> dict:
    """预览用示例数据 —— 管理员没建真实单据也能看到版式效果。"""
    out = _base(no="SAMPLE-0001")
    out["counterparty"] = {
        "name": "Pacific Bulk Carriers Pte. Ltd.", "address": "12 Marina Boulevard, #20-01, Singapore 018982",
        "tax_id": "201234567K", "registration_no": "201234567K", "swift_code": "DBSSSGSG",
        "email": "chartering@pacificbulk.example", "phone": "+65 6220 1188",
        "attention": "Mr. Tan Wei Ming",
    }
    out["vessel"] = {"name": "MV OCEAN PIONEER", "imo": "9784521", "flag": "SG",
                     "dwt": 82000, "vessel_type": "Bulk carrier"}
    out["voyage"] = {"voyage_no": "V2603", "status": "active", "cargo": "Iron ore",
                     "cp_date": _SAMPLE_DATE, "id": None}
    out["charter"] = {"contract_type": "tci", "contract_style": "time_charter",
                      "hire_rate": 18500, "hire_currency": "USD", "payment_frequency": "semi_monthly",
                      "delivery_port": "Singapore", "redelivery_port": "Qingdao",
                      "delivery_date": _SAMPLE_DATE, "redelivery_date": "2026-06-12"}
    out["ports"] = [
        {"seq": 1, "purpose": "load", "port": "Rio de Janeiro", "unlocode": "BRRIO",
         "country": "Brazil", "eta": "2026-03-18 08:00", "etd": "2026-03-21 18:00",
         "ata": "2026-03-18 09:20", "atd": "2026-03-21 17:40", "nor_at": "2026-03-18 06:00",
         "bl_date": "2026-03-21", "agent": "Rio Shipping Agency", "rate": None, "id": None},
        {"seq": 2, "purpose": "discharge", "port": "Qingdao", "unlocode": "CNTAO",
         "country": "China", "eta": "2026-04-09 07:00", "etd": "2026-04-12 12:00",
         "ata": "2026-04-09 08:10", "atd": "2026-04-12 11:30", "nor_at": "2026-04-09 05:30",
         "bl_date": "2026-03-21", "agent": "Qingdao Marine Services", "rate": None, "id": None},
    ]
    out["header"] = {
        "status": "issued", "currency": "USD",
        "issue_date": _SAMPLE_DATE, "due_date": "2026-04-13",
        "invoice_type": "FRT", "tax_amount": 0, "amount_paid": 0,
        "terms": "SHINC", "allowed_hours": 168, "used_hours": 191.5,
        "demurrage_rate": 22500, "despatch_rate": 11250,
        "period_start": "2026-03-01", "period_end": "2026-03-31",
        "hire_days": 31, "off_hire_days": 2, "gross_hire": 573500,
        "laycan_from": "2026-03-18", "laycan_to": "2026-03-23",
        "cargo_qty": 76000, "freight_rate": 21.4, "freight_basis": "per_mt",
        "commission_pct": 2.5, "demurrage_rate_pd": 22500, "despatch_rate_pd": 11250,
        "laytime_terms": "SHINC", "cp_form": "GENCON", "bill_by": "weight",
        "tolerance_pct": 0, "overage_pct": 0,
        "title": "V2603 Iron ore Rio → Qingdao", "mode": "voyage", "version": 1,
        "sea_days": 19.4, "port_days": 7.5, "total_days": 26.9,
        "bunker_price": 585, "emissions_cost": 18400,
        "port": "Rio de Janeiro", "agent": "Rio Shipping Agency",
        "unlocode": "BRRIO", "claim_type": "demurrage", "subtype": "charterer_delay",
        "time_bar": "2026-09-14", "notes": "Delay at load port awaiting berth.",
        "cargo": "Iron ore", "cp_date": _SAMPLE_DATE, "voyage_no": "V2603",
        "qty_unit": "mt", "total_qty": 480000, "rate_basis": "per_voyage",
        "rate": 1650000, "cargo_spec": "Fe 62%, Al2O3 max 2.0%",
        "period_from": "2026-04-01", "period_to": "2027-03-31",
        "grade": "VLSFO 0.5%", "quantity_mt": 1200, "price_per_mt": 612,
        "delivery_date": _SAMPLE_DATE, "grade_note": None,
        "value_date": _SAMPLE_DATE, "total": 573500,
        "pda_amount": 148600, "fda_amount": 151240, "variance": 2640,
        "payment_frequency": "semi_monthly", "settlement_amount": 186500,
        "reason": "Berth delay at load port",
    }
    out["totals"] = {
        # 与下方 lines 自洽：1,626,400 − 2% 地址佣金 − 2.5% 经纪费 = 1,553,212
        # （示例数字必须能被客户一眼核对，否则"模板预览"本身就成了错误示范）
        "subtotal": 1553212, "tax": 0, "total": 1553212, "amount_paid": 0,
        "balance": 1553212,
        "currency": "USD", "gross": 1553212, "deductions": 0,
        "allowed_hours": 168, "used_hours": 191.5, "excluded_hours": 12,
        "balance_hours": -23.5, "result_type": "demurrage", "result_label": "Demurrage due",
        "amount": 10812.5,
        "hire_days": 31, "off_hire_days": 2, "gross_hire": 573500,
        "off_hire_deduction": 122000, "bunker_adjustment": 0, "other_adjustments": -4800,
        "total_revenue": 1626400, "total_cost": 1464000, "tce": 4152,
        "freight_basis": "per_mt", "total_qty": 480000, "unit": "mt", "rate": 3.4375,
        "quantity_mt": 1200, "fda_amount": 151240, "pda_amount": 148600,
    }
    out["warnings"] = ["Event 3 overlaps event 4 — check NOR tender time"]
    out["lines"] = [
        {"description": "Freight — iron ore 76,000 MT @ USD 21.40", "qty": 76000, "unit": "MT",
         "rate": 21.4, "amount": 1626400, "note": "Freight basis: per MT, address commission & brokerage deducted",
         "start": None, "end": None, "excluded": False, "cumulative": None},
        {"description": "2% address commission", "qty": None, "unit": None, "rate": None,
         "amount": -32528, "note": None, "start": None, "end": None,
         "excluded": False, "cumulative": None},
        {"description": "2.5% brokerage", "qty": None, "unit": None, "rate": None,
         "amount": -40660, "note": None, "start": None, "end": None,
         "excluded": False, "cumulative": None},
    ]
    return out
