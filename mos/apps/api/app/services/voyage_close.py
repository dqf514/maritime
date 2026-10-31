"""航次收尾链：收尾清单 / Actual TCE vs Estimate / 日程收缩。

系统不仅记录航次，更要「驱动收尾」——完成一张航次要像关账一样有清单、
有负责人、有 Actual vs Estimate 复盘。本模块只做查询与计算（无副作用），
副作用集中在 ``services/automation.py`` 的事件处理器里。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import (
    BunkerOrder,
    Charter,
    Claim,
    EmissionRecord,
    Estimate,
    Invoice,
    LaytimeCalc,
    NoonReport,
    PortCall,
    ScheduleBlock,
    SofEvent,
    Voyage,
    VoyageAccrual,
)
from app.services.pnl_engine import voyage_pnl_4col
from app.services.ui_text import fill, messages_for

ZERO = Decimal("0")

# 跟进任务标题/描述的目录键（任务落库时用同一份文案，不会因语言切换留下中文）
TASK_DESC_KEY = "voyage.closeout.task_desc"


def _localize_items(db: Session, items: list[dict], locale: str) -> None:
    """把清单条目的 label / detail / 任务标题按 locale 取回（就地改写）。"""
    keys: list[str] = [TASK_DESC_KEY]
    for it in items:
        if it.get("label_key"):
            keys.append(it["label_key"])
        if it.get("detail_key"):
            keys.append(it["detail_key"])
        if it.get("task_title_key"):
            keys.append(it["task_title_key"])
    cat = messages_for(db, keys, locale)
    for it in items:
        vars_ = it.get("detail_vars") or {}
        if it.get("label_key"):
            it["label"] = fill(cat.get(it["label_key"], it["label"]), vars_)
        if it.get("detail_key"):
            it["detail"] = fill(cat.get(it["detail_key"], it["detail"]), vars_)
        if it.get("task_title_key"):
            it["task_title"] = fill(
                cat.get(it["task_title_key"], it.get("task_title") or ""), vars_
            )
        if it.get("task_title"):
            it["task_description"] = fill(
                cat.get(TASK_DESC_KEY, "Voyage closeout checklist gap: {label}. {detail}"),
                {"label": it["label"], "detail": it["detail"]},
            )


def _q2(x) -> float | None:
    if x is None:
        return None
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _as_utc_naive(dt: datetime | None) -> datetime | None:
    """SQLite 返回 naive UTC；内存里刚 set 的可能是 aware —— 统一成 naive UTC 再比较。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def tce_variance(db: Session, tenant_id: UUID, voyage: Voyage) -> dict:
    """Actual TCE vs Estimate TCE。

    - 估算侧：charter.estimate_id → Estimate.results（tce / total_revenue）；
    - 实际侧：已签发发票收入（freight+demurrage）− 航次成本（港口/运河/加油/
      佣金/排放/其他，来自 voyage_pnl_4col 的 actual 列）；
    - 天数：started_at → completed_at（未完成用当前时刻），下限 0.25 天。
    """
    charter = db.get(Charter, voyage.charter_id) if voyage.charter_id else None
    est_tce = None
    est_revenue = None
    if charter is not None and charter.estimate_id:
        est = db.get(Estimate, charter.estimate_id)
        if est is not None and est.results:
            est_tce = est.results.get("tce")
            est_revenue = est.results.get("total_revenue")

    actual_revenue = actual_cost = None
    row_tce = est_tce
    rows = voyage_pnl_4col(db, tenant_id, voyage.id)
    if rows:
        totals = rows[0].get("totals") or {}
        act = totals.get("actual") or {}
        est_col = totals.get("estimate") or {}
        if row_tce is None:
            row_tce = est_col.get("tce")
        actual_revenue = Decimal(str(act.get("revenue") or 0)) + Decimal(str(act.get("demurrage") or 0))
        actual_cost = sum(
            Decimal(str(act.get(k) or 0))
            for k in ("port_costs", "canal", "bunker", "commission", "emissions", "other")
        )

    days = None
    actual_tce = None
    start = _as_utc_naive(voyage.started_at)
    if start is not None and actual_revenue is not None:
        end = _as_utc_naive(voyage.completed_at) or datetime.now(timezone.utc).replace(tzinfo=None)
        days = max((end - start).total_seconds() / 86400.0, 0.25)
        actual_tce = float((actual_revenue - actual_cost) / Decimal(str(days)))

    variance = None
    if actual_tce is not None and row_tce is not None:
        variance = actual_tce - float(row_tce)

    return {
        "estimate_tce": _q2(row_tce),
        "estimate_revenue": _q2(est_revenue),
        "actual_tce": _q2(actual_tce),
        "actual_revenue": _q2(actual_revenue),
        "actual_cost": _q2(actual_cost),
        "days": round(days, 2) if days is not None else None,
        "variance": _q2(variance),
    }


def shrink_voyage_schedule_blocks(db: Session, tenant_id: UUID, voyage: Voyage) -> int:
    """航次完成后把关联 ScheduleBlock 收缩到实际完成时刻，释放多余船期占用。"""
    if voyage.completed_at is None:
        return 0
    done = _as_utc_naive(voyage.completed_at)
    blocks = db.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.tenant_id == tenant_id,
            ScheduleBlock.voyage_id == voyage.id,
        )
    ).all()
    n = 0
    for b in blocks:
        end = _as_utc_naive(b.end_at)
        if end is not None and end > done:
            b.end_at = done
            n += 1
    return n


def closing_check(db: Session, tenant_id: UUID, voyage: Voyage, locale: str = "en") -> dict:
    """航次收尾清单：逐项 ok/缺失 + 缺项的跟进任务定义（角色/时限）+ TCE 对比。

    severity：``warn`` = 缺失则完成航次时自动生成跟进任务；``info`` = 仅展示。

    文案按 ``locale`` 取（键见 ``app/seed_i18n.py`` 的 ``voyage.closeout.*``）：
    清单与自动生成的跟进任务都由后端产出，不经过前端 i18n 目录，若直接返回
    中文原文，英文界面里会整片漏出中文。目录缺键时回退到中文原文。
    """
    vid = voyage.id
    ws = f"/operations/voyages/{vid}/workspace"
    items: list[dict] = []

    def add(key, ok, label, detail, severity="warn", href=ws, task_title=None,
            assign_role=None, due_days=3, label_key="", detail_key="",
            detail_vars=None, task_title_key=""):
        items.append({
            "key": key,
            "ok": bool(ok),
            "label": label,
            "label_key": label_key,
            "detail": detail,
            "detail_key": detail_key,
            "detail_vars": detail_vars or {},
            "severity": severity,
            "href": href,
            "task_title": task_title,
            "task_title_key": task_title_key,
            "assign_role": assign_role,
            "due_days": due_days,
        })

    # 1) 挂靠港事实（ATA/ATD）
    calls = list(db.scalars(
        select(PortCall).where(
            PortCall.tenant_id == tenant_id,
            PortCall.voyage_id == vid,
            PortCall.deleted_at.is_(None),
        )
    ).all())
    if not calls:
        add("port_calls", False, "挂靠港已录入", "尚无挂靠港记录",
            label_key="voyage.closeout.port_calls.label",
            detail_key="voyage.closeout.port_calls.none",
            task_title="补录挂靠港", task_title_key="voyage.closeout.task.port_calls",
            assign_role="operations", due_days=1)
    else:
        missing = [c for c in calls if not (c.ata and c.atd)]
        done = len(calls) - len(missing)
        add(
            "port_calls", not missing, "挂靠港事实齐备 (ATA/ATD)",
            f"{done}/{len(calls)} 个挂靠港已录实际抵离港"
            + (f"，缺 {len(missing)} 个" if missing else ""),
            label_key="voyage.closeout.port_calls.full",
            detail_key=("voyage.closeout.port_calls.detail_missing" if missing
                        else "voyage.closeout.port_calls.detail"),
            detail_vars={"done": done, "total": len(calls), "missing": len(missing)},
            task_title="补录挂靠港 ATA/ATD",
            task_title_key="voyage.closeout.task.port_calls_ata",
            assign_role="operations", due_days=1,
        )

    # 2) SOF 装卸事实（laytime 可算性）
    pc_ids = [c.id for c in calls]
    codes: set[str] = set()
    if pc_ids:
        evs = db.scalars(
            select(SofEvent).where(
                SofEvent.tenant_id == tenant_id,
                SofEvent.port_call_id.in_(pc_ids),
                SofEvent.deleted_at.is_(None),
            )
        ).all()
        codes = {e.event_code for e in evs}
    sof_ok = "COMMENCED" in codes and "COMPLETED" in codes
    code_list = ", ".join(sorted(codes))
    add(
        "sof", sof_ok, "SOF 装卸事实已记录",
        f"已有事件码：{code_list if codes else '无'}"
        + ("" if sof_ok else "（需 COMMENCED + COMPLETED）"),
        label_key="voyage.closeout.sof.label",
        detail_key=("voyage.closeout.sof.detail_need" if not sof_ok
                    else ("voyage.closeout.sof.detail_ok" if codes
                          else "voyage.closeout.sof.detail_none")),
        detail_vars={"codes": code_list},
        task_title="补录 SOF 装卸事实", task_title_key="voyage.closeout.task.sof",
        assign_role="operations", due_days=1,
    )

    # 3) 装卸时间计算已定稿
    lts = list(db.scalars(
        select(LaytimeCalc).where(LaytimeCalc.tenant_id == tenant_id, LaytimeCalc.voyage_id == vid)
    ).all())
    finalized = [l for l in lts if l.status == "finalized" or l.finalized_at]
    add(
        "laytime", bool(finalized), "装卸时间计算已定稿",
        f"{len(finalized)}/{len(lts)} 份计算已定稿" if lts else "尚无装卸时间计算",
        label_key="voyage.closeout.laytime.label",
        detail_key=("voyage.closeout.laytime.detail" if lts
                    else "voyage.closeout.laytime.none"),
        detail_vars={"done": len(finalized), "total": len(lts)},
        task_title="完成装卸时间计算并定稿",
        task_title_key="voyage.closeout.task.laytime",
        assign_role="operations", due_days=3,
    )

    # 4) 索赔已了结
    open_claims = list(db.scalars(
        select(Claim).where(
            Claim.tenant_id == tenant_id,
            Claim.voyage_id == vid,
            Claim.status.in_(("open", "negotiating")),
        )
    ).all())
    add(
        "claims", not open_claims, "索赔已了结",
        f"{len(open_claims)} 笔索赔未了结" if open_claims else "无未决索赔",
        label_key="voyage.closeout.claims.label",
        detail_key=("voyage.closeout.claims.detail" if open_claims
                    else "voyage.closeout.claims.none"),
        detail_vars={"n": len(open_claims)},
        task_title="了结未决索赔", task_title_key="voyage.closeout.task.claims",
        assign_role="claims", due_days=5,
    )

    # 5) 发票已签发（有待开草稿 → 提醒财务）
    invs = list(db.scalars(
        select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.voyage_id == vid)
    ).all())
    issued = [i for i in invs if i.status in ("issued", "partially_paid", "paid")]
    drafts = [i for i in invs if i.status in ("draft", "pending_approval")]
    add(
        "invoices", bool(issued) or not invs, "发票已签发",
        f"{len(issued)} 张已签发" + (f"，{len(drafts)} 张待签发" if drafts else "")
        if invs else "尚无发票记录",
        label_key="voyage.closeout.invoices.label",
        detail_key=("voyage.closeout.invoices.none" if not invs
                    else ("voyage.closeout.invoices.detail_pending" if drafts
                          else "voyage.closeout.invoices.detail")),
        detail_vars={"issued": len(issued), "pending": len(drafts)},
        task_title="签发待开航次发票",
        task_title_key="voyage.closeout.task.invoices",
        assign_role="finance", due_days=3,
    )

    # 6) 加油订单已交付
    orders = list(db.scalars(
        select(BunkerOrder).where(BunkerOrder.tenant_id == tenant_id, BunkerOrder.voyage_id == vid)
    ).all())
    undelivered = [o for o in orders if o.status not in ("delivered", "cancelled")]
    add(
        "bunker", not undelivered, "加油订单已交付",
        f"{len(orders) - len(undelivered)}/{len(orders)} 单已交付" if orders else "无加油订单",
        label_key="voyage.closeout.bunker.label",
        detail_key=("voyage.closeout.bunker.detail" if orders
                    else "voyage.closeout.bunker.none"),
        detail_vars={"done": len(orders) - len(undelivered), "total": len(orders)},
        task_title="交付未完成的加油订单",
        task_title_key="voyage.closeout.task.bunker",
        assign_role="operations", due_days=2,
    )

    # 7) 排放已记录（info：由排放引擎/手工补录）
    emissions = db.scalar(
        select(EmissionRecord.id).where(
            EmissionRecord.tenant_id == tenant_id, EmissionRecord.voyage_id == vid
        ).limit(1)
    )
    noons = db.scalar(
        select(NoonReport.id).where(
            NoonReport.tenant_id == tenant_id, NoonReport.voyage_id == vid
        ).limit(1)
    )
    add(
        "emissions", bool(emissions or noons), "排放数据已记录",
        "有排放记录" if emissions else ("有午报（可推算排放）" if noons else "无排放/午报记录"),
        label_key="voyage.closeout.emissions.label",
        detail_key=("voyage.closeout.emissions.detail" if emissions
                    else ("voyage.closeout.emissions.detail_noon" if noons
                          else "voyage.closeout.emissions.none")),
        severity="info",
    )

    # 8) 计提 vs 实际发票差异（posted accrual 合计 vs 已签发发票合计）
    accruals = list(db.scalars(
        select(VoyageAccrual).where(
            VoyageAccrual.tenant_id == tenant_id,
            VoyageAccrual.voyage_id == vid,
            VoyageAccrual.status == "posted",
        )
    ).all())
    if accruals:
        accr_total = sum(Decimal(str(a.amount or 0)) for a in accruals)
        inv_total = sum(
            Decimal(str(i.base_amount if i.base_amount is not None else i.amount or 0)) for i in issued
        )
        diff = abs(accr_total - inv_total)
        threshold = abs(accr_total) * Decimal("0.05")
        accr_ok = diff <= max(threshold, Decimal("1"))
        add(
            "accruals", accr_ok, "计提与实际发票已对平",
            f"计提合计 {float(accr_total):.2f} vs 发票合计 {float(inv_total):.2f}，差异 {float(diff):.2f}",
            label_key="voyage.closeout.accruals.label",
            detail_key="voyage.closeout.accruals.detail",
            detail_vars={
                "accrual": f"{float(accr_total):.2f}",
                "invoice": f"{float(inv_total):.2f}",
                "diff": f"{float(diff):.2f}",
            },
            task_title="核对计提与实际发票差异",
            task_title_key="voyage.closeout.task.accruals",
            assign_role="finance", due_days=5,
        )
    else:
        add("accruals", True, "计提与实际发票已对平", "无已过账计提",
            label_key="voyage.closeout.accruals.label",
            detail_key="voyage.closeout.accruals.none",
            severity="info")

    # 按 locale 取文案（目录缺键 → 回退上面写的中文原文）
    _localize_items(db, items, locale)

    ready = all(i["ok"] for i in items if i["severity"] == "warn")
    return {
        "ready": ready,
        "items": items,
        "tce": tce_variance(db, tenant_id, voyage),
        "missing": [i["key"] for i in items if not i["ok"] and i["severity"] == "warn"],
    }
