"""业务自动化处理器：域事件 → 跟进任务 / 通知 / GL 自动过账 / 告警。

每个业务节点（``@on(kind)``）把「下一步该谁做什么」物化出来：

- 航次完成  → 日程收缩 + 收尾清单缺项分部门任务 + TCE 快照 + 规则任务
- lifting   → 固定/完成后 Ops 跟进、超短装告警
- 发票签发  → 财务过账/计提对账任务
- PDA 关闭  → 尝试自动过账 GL（失败降级为任务，不静默）
- 加油交付  → BDN 偏差告警 + 任务
- 索赔和解  → 财务转发票任务
- 租约修订  → 三部门通知 + 财务复核任务
- NOR/装卸时间邮件落位 → Ops 通知/复核任务

全部处理器与业务写入同事务；异常由 domain_events.run_handlers 捕获留痕。
在 ``main.py`` 导入本模块以保证注册（不依赖路由导入顺序）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import (
    Charter,
    Claim,
    Invoice,
    PortDisbursement,
    ScheduleBlock,
    TwinAlert,
    Voyage,
)
from app.services.domain_events import DomainEvent, ensure_task, materialize_task_rules, notify_task, on
from app.services.notifications import notify_roles_once
from app.services.voyage_close import closing_check, shrink_voyage_schedule_blocks

ZERO = Decimal("0")


def _dec(x) -> Decimal:
    return Decimal(str(x or 0))


def _uid(x) -> UUID | None:
    """payload 里的 id 可能是 str —— db.get(UUID 列) 需要真 UUID。"""
    if x is None:
        return None
    if isinstance(x, UUID):
        return x
    try:
        return UUID(str(x))
    except ValueError:
        return None


def _q2(x) -> float:
    return float(_dec(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ── 航次完成：收尾链总入口 ────────────────────────────────────────────────


@on("voyage.completed")
def on_voyage_completed(db: Session, ev: DomainEvent) -> None:
    voyage = db.get(Voyage, ev.entity_id)
    if voyage is None:
        return
    tenant_id = ev.tenant_id

    # 1) 船期日历收缩到实际完成时刻（释放多余占用）
    shrunk = shrink_voyage_schedule_blocks(db, tenant_id, voyage)

    # 2) 收尾清单缺项 → 分部门跟进任务 + 通知
    check = closing_check(db, tenant_id, voyage)
    ws = f"/operations/voyages/{voyage.id}/workspace"
    created_titles: list[str] = []
    for item in check["items"]:
        if item["ok"] or item["severity"] == "info" or not item.get("task_title"):
            continue
        task = ensure_task(
            db,
            tenant_id,
            title=f"{item['task_title']} — {voyage.voyage_no}",
            description=f"航次收尾清单缺项：{item['label']}。{item.get('detail') or ''}",
            entity_type="voyage",
            entity_id=voyage.id,
            priority="high",
            due_days=item.get("due_days") or 3,
            assign_role=item.get("assign_role"),
            created_by=ev.created_by,
        )
        notify_task(db, tenant_id, task, assign_role=item.get("assign_role"), href=ws)
        created_titles.append(task.title)

    # 3) Actual TCE 快照进 meta（复盘/报表可追溯）
    tce = check.get("tce") or {}
    meta = dict(voyage.meta or {})
    meta["tce_snapshot"] = {
        "estimate_tce": tce.get("estimate_tce"),
        "actual_tce": tce.get("actual_tce"),
        "variance": tce.get("variance"),
        "days": tce.get("days"),
        "actual_revenue": tce.get("actual_revenue"),
        "actual_cost": tce.get("actual_cost"),
    }
    meta["tce_snapshot_at"] = datetime.now(timezone.utc).isoformat()
    meta["closing_missing"] = check.get("missing") or []
    voyage.meta = meta

    # 4) 租户配置的 TaskRule 物化（规则 → 任务的最后一环）
    ctx = {
        "voyage": {
            "voyage_no": voyage.voyage_no,
            "status": voyage.status,
            "cargo": voyage.cargo,
            "vessel_id": str(voyage.vessel_id) if voyage.vessel_id else None,
            "charter_id": str(voyage.charter_id) if voyage.charter_id else None,
        }
    }
    materialize_task_rules(db, tenant_id, "voyage", ctx, entity_id=voyage.id, created_by=ev.created_by)

    # 5) 汇总通知（运营/管理）
    missing = check.get("missing") or []
    notify_roles_once(
        db,
        tenant_id,
        ("operations", "management"),
        title=f"航次 {voyage.voyage_no} 已完成",
        body=(
            f"收尾清单：{'全部齐备' if not missing else '缺 ' + '、'.join(missing)}"
            + (f"；已生成 {len(created_titles)} 项跟进任务" if created_titles else "")
            + (f"；船期块收缩 {shrunk} 段" if shrunk else "")
        ),
        href=ws,
        level="info" if not missing else "warn",
    )


# ── COA lifting：固定 / 完成 ─────────────────────────────────────────────


@on("lifting.fixed")
def on_lifting_fixed(db: Session, ev: DomainEvent) -> None:
    p = ev.payload or {}
    charter = db.get(Charter, _uid(p.get("charter_id"))) if p.get("charter_id") else None
    cno = charter.charter_no if charter is not None else "COA"
    voyage_no = p.get("voyage_no") or ""
    task = ensure_task(
        db,
        ev.tenant_id,
        title=f"执行提货航次 {voyage_no} — {cno}",
        description=f"COA 提货 {p.get('period_label') or ''} 已订租（fixed），请跟进航次执行与装期。",
        entity_type="charter",
        entity_id=charter.id if charter is not None else None,
        priority="normal",
        due_days=3,
        assign_role="operations",
        created_by=ev.created_by,
    )
    notify_task(
        db, ev.tenant_id, task, assign_role="operations",
        href=f"/charters/{charter.id}" if charter is not None else "/tasks",
    )


@on("lifting.completed")
def on_lifting_completed(db: Session, ev: DomainEvent) -> None:
    p = ev.payload or {}
    charter = db.get(Charter, _uid(p.get("charter_id"))) if p.get("charter_id") else None
    if charter is None:
        return
    total = _dec(p.get("total_qty"))
    lifted = _dec(p.get("lifted_total"))
    actual = _dec(p.get("actual_qty"))
    planned = _dec(p.get("planned_qty"))
    cno = charter.charter_no
    href = f"/charters/{charter.id}"

    if total > 0 and lifted > total * Decimal("1.02"):
        # 超装：需要变更单/补充协议 —— 告警 + 分派任务
        db.add(TwinAlert(
            tenant_id=ev.tenant_id,
            level="warn",
            title=f"COA 超装：{cno}",
            body=f"累计提货 {float(lifted):,.2f} 已超合同量 {float(total):,.2f}，请确认变更单/补充协议。",
            href=href,
            vessel_id=charter.vessel_id,
        ))
        task = ensure_task(
            db, ev.tenant_id,
            title=f"COA 超装复核 — {cno}",
            description=f"累计提货 {float(lifted):,.2f} > 合同量 {float(total):,.2f}。",
            entity_type="charter", entity_id=charter.id,
            priority="high", due_days=2, assign_role="chartering", created_by=ev.created_by,
        )
        notify_task(db, ev.tenant_id, task, assign_role="chartering", href=href, level="warn")
    elif total > 0 and lifted < total * Decimal("0.95") and not p.get("has_open_liftings", True):
        # 短装且无剩余开放 lifting：提醒商务跟进
        task = ensure_task(
            db, ev.tenant_id,
            title=f"COA 短装跟进 — {cno}",
            description=f"累计提货 {float(lifted):,.2f} 低于合同量 {float(total):,.2f}，请确认余量安排。",
            entity_type="charter", entity_id=charter.id,
            priority="normal", due_days=5, assign_role="chartering", created_by=ev.created_by,
        )
        notify_task(db, ev.tenant_id, task, assign_role="chartering", href=href)
    elif planned > 0 and abs(actual - planned) / planned > Decimal("0.05"):
        # 单笔实际量与计划偏差 >5%：提醒 ops
        db.add(TwinAlert(
            tenant_id=ev.tenant_id,
            level="info",
            title=f"提货量偏差：{cno} {p.get('period_label') or ''}",
            body=f"实际 {float(actual):,.2f} vs 计划 {float(planned):,.2f}。",
            href=href,
            vessel_id=charter.vessel_id,
        ))


# ── 租约修订批准 ─────────────────────────────────────────────────────────


_MONEY_CHANGE_KEYS = {"demurrage_rate", "freight_rate", "hire_per_day", "cargo_qty", "freight_basis"}


@on("charter.amendment_approved")
def on_amendment_approved(db: Session, ev: DomainEvent) -> None:
    p = ev.payload or {}
    charter = db.get(Charter, _uid(p.get("charter_id"))) if p.get("charter_id") else None
    if charter is None:
        return
    changes = p.get("changes") or {}
    cno = charter.charter_no
    href = f"/charters/{charter.id}"
    change_desc = "、".join(f"{k}→{changes[k]}" for k in list(changes)[:6])

    notify_roles_once(
        db, ev.tenant_id,
        ("chartering", "operations", "finance", "management"),
        title=f"租约修订已批准：{cno}",
        body=f"变更：{change_desc}。原因：{p.get('reason') or '—'}",
        href=href,
        level="info",
    )

    money_touched = _MONEY_CHANGE_KEYS.intersection(changes)
    if not money_touched:
        return
    # 有未结发票/计提 → 财务复核任务
    voyages = db.scalars(
        select(Voyage.id).where(Voyage.tenant_id == ev.tenant_id, Voyage.charter_id == charter.id)
    ).all()
    needs_review = False
    if voyages:
        open_inv = db.scalar(
            select(Invoice.id).where(
                Invoice.tenant_id == ev.tenant_id,
                Invoice.voyage_id.in_(voyages),
                Invoice.status.in_(("draft", "pending_approval", "issued", "partially_paid")),
            ).limit(1)
        )
        needs_review = open_inv is not None
    if needs_review:
        task = ensure_task(
            db, ev.tenant_id,
            title=f"按修订条款复核发票与计提 — {cno}",
            description=f"条款已变更（{ '、'.join(money_touched) }），请复核未结发票/计提是否需要重开或调整。",
            entity_type="charter", entity_id=charter.id,
            priority="high", due_days=3, assign_role="finance", created_by=ev.created_by,
        )
        notify_task(db, ev.tenant_id, task, assign_role="finance", href=href, level="warn")


# ── 发票签发 ─────────────────────────────────────────────────────────────


@on("invoice.issued")
def on_invoice_issued(db: Session, ev: DomainEvent) -> None:
    inv = db.get(Invoice, ev.entity_id)
    if inv is None:
        return
    inv_no = inv.invoice_no or str(inv.id)[:8]
    task = ensure_task(
        db, ev.tenant_id,
        title=f"过账总账：发票 {inv_no}",
        description=f"发票已签发（{_q2(inv.amount)} {inv.currency or 'USD'}），复核科目后过账 GL。",
        entity_type="invoice", entity_id=inv.id,
        priority="normal", due_days=3, assign_role="finance", created_by=ev.created_by,
    )
    notify_task(db, ev.tenant_id, task, assign_role="finance", href=f"/finance/invoices?id={inv.id}")

    if inv.voyage_id is not None:
        from app.models_domain import VoyageAccrual

        accruals = db.scalars(
            select(VoyageAccrual).where(
                VoyageAccrual.tenant_id == ev.tenant_id,
                VoyageAccrual.voyage_id == inv.voyage_id,
                VoyageAccrual.status == "posted",
            )
        ).all()
        if accruals:
            task2 = ensure_task(
                db, ev.tenant_id,
                title=f"计提对账：航次发票 {inv_no}",
                description="该航次存在已过账计提 —— 发票签发后请核对差异并冲回计提。",
                entity_type="voyage", entity_id=inv.voyage_id,
                priority="normal", due_days=5, assign_role="finance", created_by=ev.created_by,
            )
            notify_task(db, ev.tenant_id, task2, assign_role="finance", href=f"/operations/voyages/{inv.voyage_id}/workspace")


# ── PDA 关闭：尝试自动过账 GL（失败降级为任务） ───────────────────────────


def try_post_pda_journal(db: Session, tenant_id: UUID, pda: PortDisbursement, user_id=None):
    """PDA/FDA 关闭 → 自动过账一条港口使费凭证。幂等（source 键）。

    返回 (journal, created)；科目规则缺失或期间关闭 → (None, reason)，
    由调用方降级为财务任务（绝不静默丢账）。
    """
    from app.services.gl_engine import build_journal_entries, post_journal

    amount = _dec(pda.fda_amount or pda.pda_amount)
    if amount <= 0:
        return None, "no_amount"
    try:
        entries = build_journal_entries(db, tenant_id, [{
            "entity_type": "port_disbursement",
            "expense_category": "port_costs",
            "amount": float(amount),
            "reference": f"PDA-{str(pda.id)[:8]}",
            "description": f"Port disbursement {pda.status} {pda.currency or 'USD'}",
        }])
    except ValueError as exc:
        return None, f"no_gl_rule: {exc}"
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        journal = post_journal(
            db, tenant_id, period, "pda", entries,
            description=f"Port disbursement auto-post {pda.id}",
            user_id=user_id, currency=pda.currency or "USD",
            source_type="port_disbursement", source_id=pda.id,
        )
    except Exception as exc:  # noqa: BLE001 — 期间关闭等业务性失败 → 降级任务
        return None, f"post_failed: {exc}"
    return journal, "posted"


@on("pda.closed")
def on_pda_closed(db: Session, ev: DomainEvent) -> None:
    pda = db.get(PortDisbursement, ev.entity_id)
    if pda is None:
        return
    journal, outcome = try_post_pda_journal(db, ev.tenant_id, pda, user_id=ev.created_by)
    if journal is not None:
        notify_roles_once(
            db, ev.tenant_id, ("finance",),
            title=f"PDA 已自动过账：{_q2(pda.fda_amount or pda.pda_amount)} {pda.currency or 'USD'}",
            body=f"港口使费凭证已过账（period {datetime.now(timezone.utc):%Y-%m}）。",
            href=f"/operations/voyages/{pda.voyage_id}/workspace" if pda.voyage_id else "/finance/gl",
            level="info",
        )
        return
    # 降级：科目规则缺失 / 期间关闭 → 财务任务，不静默
    task = ensure_task(
        db, ev.tenant_id,
        title=f"PDA 待过账：{str(pda.id)[:8]}",
        description=f"PDA 已关闭但自动过账未完成（{outcome}），请补录凭证或调整科目规则。",
        entity_type="port_disbursement", entity_id=pda.id,
        priority="high", due_days=3, assign_role="finance", created_by=ev.created_by,
    )
    notify_task(db, ev.tenant_id, task, assign_role="finance", href="/finance/gl", level="warn")


# ── 加油交付 ─────────────────────────────────────────────────────────────


@on("bunker.delivered")
def on_bunker_delivered(db: Session, ev: DomainEvent) -> None:
    p = ev.payload or {}
    warnings = p.get("warnings") or []
    if not warnings:
        return
    codes = {w.get("code") for w in warnings}
    level = "warn" if "BDN_QTY_DEVIATION" in codes or "ROB_CONSERVATION" in codes else "info"
    voyage_id = p.get("voyage_id")
    db.add(TwinAlert(
        tenant_id=ev.tenant_id,
        level=level,
        title=f"加油交付异常：{p.get('order_no') or str(ev.entity_id)[:8]}",
        body="；".join(w.get("message", "") for w in warnings),
        href=f"/operations/voyages/{voyage_id}/workspace" if voyage_id else "/bunker",
        vessel_id=p.get("vessel_id"),
        voyage_id=voyage_id,
    ))
    task = ensure_task(
        db, ev.tenant_id,
        title=f"核对加油交付：{p.get('order_no') or str(ev.entity_id)[:8]}",
        description="；".join(w.get("message", "") for w in warnings),
        entity_type="bunker_order", entity_id=ev.entity_id,
        priority="high" if level == "warn" else "normal",
        due_days=2, assign_role="operations", created_by=ev.created_by,
    )
    notify_task(
        db, ev.tenant_id, task, assign_role="operations",
        href=f"/operations/voyages/{voyage_id}/workspace" if voyage_id else "/bunker",
        level=level,
    )


# ── 索赔和解 ─────────────────────────────────────────────────────────────


@on("claim.settled")
def on_claim_settled(db: Session, ev: DomainEvent) -> None:
    claim = db.get(Claim, ev.entity_id)
    if claim is None:
        return
    task = ensure_task(
        db, ev.tenant_id,
        title=f"索赔转结算：{claim.claim_no}",
        description=f"索赔已和解（{_q2(claim.settlement_amount or claim.amount)} {claim.currency or 'USD'}），请开具发票/登记收付款。",
        entity_type="claim", entity_id=claim.id,
        priority="high", due_days=5, assign_role="finance", created_by=ev.created_by,
    )
    notify_task(db, ev.tenant_id, task, assign_role="finance", href=f"/claims?id={claim.id}")


# ── 邮件落位（NOR / 装卸时间草稿） ───────────────────────────────────────


@on("portcall.nor_updated")
def on_nor_updated(db: Session, ev: DomainEvent) -> None:
    p = ev.payload or {}
    notify_roles_once(
        db, ev.tenant_id, ("operations",),
        title=f"NOR 已落位：{p.get('voyage_no') or ''}".strip(),
        body=f"邮件识别的 NOR 时间 {p.get('nor_at') or ''} 已写入挂靠港。",
        href=f"/operations/voyages/{p.get('voyage_id')}/workspace" if p.get("voyage_id") else "/email/review",
        level="info",
    )


@on("laytime.draft_created")
def on_laytime_draft_created(db: Session, ev: DomainEvent) -> None:
    p = ev.payload or {}
    voyage_id = p.get("voyage_id")
    task = ensure_task(
        db, ev.tenant_id,
        title=f"复核装卸时间草稿：{p.get('voyage_no') or ''}".strip(),
        description="邮件解析生成了装卸时间计算草稿，请核对事件与条款后定稿。",
        entity_type="laytime", entity_id=ev.entity_id,
        priority="normal", due_days=3, assign_role="operations", created_by=ev.created_by,
    )
    notify_task(
        db, ev.tenant_id, task, assign_role="operations",
        href=f"/finance/laytimes?id={ev.entity_id}",
    )
