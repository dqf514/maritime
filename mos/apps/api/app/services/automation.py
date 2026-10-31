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
from app.services.action_catalog import ACTION_BY_CODE, ACTIONS
from app.services.notifications import notify_roles_once
from app.services.system_text import text
from app.services.voyage_close import closing_check, shrink_voyage_schedule_blocks
from app.services.ui_text import user_locale

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


def _voyage_completed_body(locale: str, missing: list, task_count: int, shrunk: int) -> str:
    """航次完成汇总正文（按 locale 拼装，可选片段用分隔符连起来）。"""
    zh = locale.startswith("zh")
    sep = "；" if zh else "; "
    parts: list[str] = []
    if missing:
        parts.append(
            text(
                "voyage.completed.notify.missing",
                locale,
                items=("、".join(missing) if zh else ", ".join(missing)),
            )
        )
    else:
        parts.append(text("voyage.completed.notify.all_clear", locale))
    if task_count:
        parts.append(text("voyage.completed.notify.tasks", locale, count=task_count))
    if shrunk:
        parts.append(text("voyage.completed.notify.schedule", locale, count=shrunk))
    return sep.join(parts)


def create_closeout_tasks(
    db: Session,
    tenant_id: UUID,
    voyage: Voyage,
    *,
    locale: str = "en",
    created_by: UUID | None = None,
    notify: bool = True,
    check: dict | None = None,
) -> list:
    """按收尾清单缺项建跟进任务（每项绑定动作目录里的对应动作码）。

    收尾清单项 ↔ 动作目录一一对应（同一份判定，见 ``services/closeout_checks``）：
    任务带上 ``action_code`` 后，业务侧把缺项补齐 → 任务自动勾完成。

    幂等键带上本轮完成时间 —— 航次重开后再次完成要重新生成一批任务，
    但同一轮里重复触发不会重复建。

    独立成函数是为了让演示种子能复用**同一条路径**造数据：
    演示里那个"已完成航次"的收尾任务与真实收尾时生成的完全同源。
    """
    check = check or closing_check(db, tenant_id, voyage, locale=locale)
    ws = f"/operations/voyages/{voyage.id}/workspace"
    created: list = []
    for item in check["items"]:
        if item["ok"] or item["severity"] == "info" or not item.get("task_title"):
            continue
        action_code = f"voyage.closeout.{item['key']}"
        if action_code not in ACTION_BY_CODE:
            action_code = None
        round_key = voyage.completed_at.isoformat() if voyage.completed_at else "na"
        task = ensure_task(
            db,
            tenant_id,
            title=f"{item['task_title']} — {voyage.voyage_no}",
            description=item.get("task_description")
            or f"{item['label']}. {item.get('detail') or ''}",
            entity_type="voyage",
            entity_id=voyage.id,
            priority="high",
            due_days=item.get("due_days") or 3,
            assign_role=item.get("assign_role"),
            created_by=created_by,
            action_code=action_code,
            dedupe_key=f"voyage.closeout:{item['key']}:{voyage.id}:{round_key}",
        )
        if notify:
            notify_task(db, tenant_id, task, assign_role=item.get("assign_role"), href=ws)
        created.append(task)
    return created


@on("voyage.completed")
def on_voyage_completed(db: Session, ev: DomainEvent) -> None:
    voyage = db.get(Voyage, ev.entity_id)
    if voyage is None:
        return
    tenant_id = ev.tenant_id

    # 1) 船期日历收缩到实际完成时刻（释放多余占用）
    shrunk = shrink_voyage_schedule_blocks(db, tenant_id, voyage)

    # 2) 收尾清单缺项 → 分部门跟进任务 + 通知
    #    任务文案随「完成航次的人」的语言落库（英文界面不该留中文任务）
    locale = user_locale(db, ev.created_by)
    check = closing_check(db, tenant_id, voyage, locale=locale)
    ws = f"/operations/voyages/{voyage.id}/workspace"
    created_titles: list[str] = [
        t.title
        for t in create_closeout_tasks(
            db, tenant_id, voyage, locale=locale, created_by=ev.created_by, check=check
        )
    ]

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

    # 5) 汇总通知（运营/管理）—— 收件人各按自己的语言收（notify_once 逐人挑）
    missing = check.get("missing") or []
    notify_roles_once(
        db,
        tenant_id,
        ("operations", "management"),
        title=text("voyage.completed.notify.title", "en", voyage_no=voyage.voyage_no),
        body=_voyage_completed_body("en", missing, len(created_titles), shrunk),
        title_i18n={"zh": text("voyage.completed.notify.title", "zh-CN", voyage_no=voyage.voyage_no)},
        body_i18n={"zh": _voyage_completed_body("zh-CN", missing, len(created_titles), shrunk)},
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
    locale = user_locale(db, ev.created_by)
    task = ensure_task(
        db,
        ev.tenant_id,
        title=text("lifting.fixed.task.title", locale, voyage_no=voyage_no, charter_no=cno),
        description=text(
            "lifting.fixed.task.desc", locale, period=p.get("period_label") or ""
        ),
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
        locale = user_locale(db, ev.created_by)
        db.add(TwinAlert(
            tenant_id=ev.tenant_id,
            level="warn",
            title=text("lifting.over.alert.title", "en", charter_no=cno),
            body=text(
                "lifting.over.alert.body", "en",
                lifted=f"{float(lifted):,.2f}", total=f"{float(total):,.2f}",
            ),
            href=href,
            vessel_id=charter.vessel_id,
        ))
        task = ensure_task(
            db, ev.tenant_id,
            title=text("lifting.over.task.title", locale, charter_no=cno),
            description=text(
                "lifting.over.task.desc", locale,
                lifted=f"{float(lifted):,.2f}", total=f"{float(total):,.2f}",
            ),
            entity_type="charter", entity_id=charter.id,
            priority="high", due_days=2, assign_role="chartering", created_by=ev.created_by,
        )
        notify_task(db, ev.tenant_id, task, assign_role="chartering", href=href, level="warn")
    elif total > 0 and lifted < total * Decimal("0.95") and not p.get("has_open_liftings", True):
        # 短装且无剩余开放 lifting：提醒商务跟进
        locale = user_locale(db, ev.created_by)
        task = ensure_task(
            db, ev.tenant_id,
            title=text("lifting.short.task.title", locale, charter_no=cno),
            description=text(
                "lifting.short.task.desc", locale,
                lifted=f"{float(lifted):,.2f}", total=f"{float(total):,.2f}",
            ),
            entity_type="charter", entity_id=charter.id,
            priority="normal", due_days=5, assign_role="chartering", created_by=ev.created_by,
        )
        notify_task(db, ev.tenant_id, task, assign_role="chartering", href=href)
    elif planned > 0 and abs(actual - planned) / planned > Decimal("0.05"):
        # 单笔实际量与计划偏差 >5%：提醒 ops
        db.add(TwinAlert(
            tenant_id=ev.tenant_id,
            level="info",
            title=text(
                "lifting.deviation.alert.title", "en",
                charter_no=cno, period=p.get("period_label") or "",
            ),
            body=text(
                "lifting.deviation.alert.body", "en",
                actual=f"{float(actual):,.2f}", planned=f"{float(planned):,.2f}",
            ),
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
    change_desc_en = ", ".join(f"{k}→{changes[k]}" for k in list(changes)[:6])
    locale = user_locale(db, ev.created_by)

    notify_roles_once(
        db, ev.tenant_id,
        ("chartering", "operations", "finance", "management"),
        title=text("amendment.notify.title", "en", charter_no=cno),
        body=text("amendment.notify.body", "en", changes=change_desc_en, reason=p.get("reason") or "—"),
        title_i18n={"zh": text("amendment.notify.title", "zh-CN", charter_no=cno)},
        body_i18n={"zh": text("amendment.notify.body", "zh-CN", changes=change_desc, reason=p.get("reason") or "—")},
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
            title=text("amendment.task.title", locale, charter_no=cno),
            description=text(
                "amendment.task.desc", locale,
                fields=("、".join(money_touched) if locale.startswith("zh") else ", ".join(sorted(money_touched))),
            ),
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
    locale = user_locale(db, ev.created_by)
    task = ensure_task(
        db, ev.tenant_id,
        title=text("invoice.issued.task.title", locale, invoice_no=inv_no),
        description=text(
            "invoice.issued.task.desc", locale,
            amount=_q2(inv.amount), currency=inv.currency or "USD",
        ),
        entity_type="invoice", entity_id=inv.id,
        priority="normal", due_days=3, assign_role="finance", created_by=ev.created_by,
        # 发票已签发但 GL 未过账 → 绑 invoice.post_gl：过账后任务自动勾完成。
        action_code="invoice.post_gl",
        dedupe_key=f"invoice.post_gl:{inv.id}:{inv.issued_at.isoformat() if inv.issued_at else 'na'}",
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
                title=text("invoice.accruals.task.title", locale, invoice_no=inv_no),
                description=text("invoice.accruals.task.desc", locale),
                entity_type="voyage", entity_id=inv.voyage_id,
                priority="normal", due_days=5, assign_role="finance", created_by=ev.created_by,
                # 计提与发票对齐后自动勾完成（voyage.closeout.accruals 与收尾清单同一判定）。
                action_code="voyage.closeout.accruals",
                dedupe_key=f"voyage.closeout.accruals:{inv.voyage_id}:{inv_no}",
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
    locale = user_locale(db, ev.created_by)
    if journal is not None:
        amount = _q2(pda.fda_amount or pda.pda_amount)
        currency = pda.currency or "USD"
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        notify_roles_once(
            db, ev.tenant_id, ("finance",),
            title=text("pda.posted.notify.title", "en", amount=amount, currency=currency),
            body=text("pda.posted.notify.body", "en", period=period),
            title_i18n={"zh": text("pda.posted.notify.title", "zh-CN", amount=amount, currency=currency)},
            body_i18n={"zh": text("pda.posted.notify.body", "zh-CN", period=period)},
            href=f"/operations/voyages/{pda.voyage_id}/workspace" if pda.voyage_id else "/finance/gl",
            level="info",
        )
        return
    # 降级：科目规则缺失 / 期间关闭 → 财务任务，不静默
    task = ensure_task(
        db, ev.tenant_id,
        title=text("pda.pending.task.title", locale, ref=str(pda.id)[:8]),
        description=text("pda.pending.task.desc", locale, outcome=outcome),
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
    order_no = p.get("order_no") or str(ev.entity_id)[:8]
    locale = user_locale(db, ev.created_by)
    db.add(TwinAlert(
        tenant_id=ev.tenant_id,
        level=level,
        title=text("bunker.alert.title", "en", order_no=order_no),
        body="; ".join(w.get("message", "") for w in warnings),
        href=f"/operations/voyages/{voyage_id}/workspace" if voyage_id else "/bunker",
        vessel_id=p.get("vessel_id"),
        voyage_id=voyage_id,
    ))
    task = ensure_task(
        db, ev.tenant_id,
        title=text("bunker.task.title", locale, order_no=order_no),
        description="；".join(w.get("message", "") for w in warnings)
        if locale.startswith("zh") else "; ".join(w.get("message", "") for w in warnings),
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
        title=text("claim.settled.task.title", user_locale(db, ev.created_by), claim_no=claim.claim_no),
        description=text(
            "claim.settled.task.desc", user_locale(db, ev.created_by),
            amount=_q2(claim.settlement_amount or claim.amount), currency=claim.currency or "USD",
        ),
        entity_type="claim", entity_id=claim.id,
        priority="high", due_days=5, assign_role="finance", created_by=ev.created_by,
    )
    notify_task(db, ev.tenant_id, task, assign_role="finance", href=f"/claims?id={claim.id}")


# ── 撤销通道：动作被撤销 → 自动勾完的任务回退 ──────────────────────────


@on("voyage.reopened")
def on_voyage_reopened(db: Session, ev: DomainEvent) -> None:
    """航次被重开 → 上一轮被系统勾掉的收尾任务回退成待办。

    没有这条通道，航次重新开跑时清单上却还挂着 7 条绿的"已收尾"任务。
    """
    from app.services.task_completion import reopen_tasks_for

    codes = tuple(a.code for a in ACTIONS if a.code.startswith("voyage.closeout.")) + ("voyage.complete",)
    reopen_tasks_for(db, ev.tenant_id, codes, ev.entity_id, reason="voyage.reopened")


@on("invoice.payment_voided")
def on_invoice_payment_voided(db: Session, ev: DomainEvent) -> None:
    """收款被冲正 → "已收款"不再成立，任务回退。"""
    from app.services.task_completion import reopen_tasks_for

    reopen_tasks_for(db, ev.tenant_id, ("invoice.payment.record",), ev.entity_id, reason="payment_voided")


@on("accrual.reversed")
def on_accrual_reversed(db: Session, ev: DomainEvent) -> None:
    """计提被冲销 → 航次的「计提对账」任务回退（计提与发票又对不上了）。"""
    from app.services.task_completion import reopen_tasks_for

    voyage_id = (ev.payload or {}).get("voyage_id")
    if not voyage_id:
        return
    vid = _uid(voyage_id)
    if vid is None:
        return
    reopen_tasks_for(
        db, ev.tenant_id, ("voyage.closeout.accruals",), vid,
        reason="accrual_reversed",
    )


# ── 邮件落位（NOR / 装卸时间草稿） ───────────────────────────────────────

@on("portcall.nor_updated")
def on_nor_updated(db: Session, ev: DomainEvent) -> None:
    p = ev.payload or {}
    voyage_no = (p.get("voyage_no") or "").strip()
    notify_roles_once(
        db, ev.tenant_id, ("operations",),
        title=text("nor.notify.title", "en", voyage_no=voyage_no),
        body=text("nor.notify.body", "en", nor_at=p.get("nor_at") or ""),
        title_i18n={"zh": text("nor.notify.title", "zh-CN", voyage_no=voyage_no)},
        body_i18n={"zh": text("nor.notify.body", "zh-CN", nor_at=p.get("nor_at") or "")},
        href=f"/operations/voyages/{p.get('voyage_id')}/workspace" if p.get("voyage_id") else "/email/review",
        level="info",
    )


@on("laytime.draft_created")
def on_laytime_draft_created(db: Session, ev: DomainEvent) -> None:
    p = ev.payload or {}
    voyage_id = p.get("voyage_id")
    locale = user_locale(db, ev.created_by)
    task = ensure_task(
        db, ev.tenant_id,
        title=text("laytime.draft.task.title", locale, voyage_no=(p.get("voyage_no") or "").strip()),
        description=text("laytime.draft.task.desc", locale),
        entity_type="laytime", entity_id=ev.entity_id,
        priority="normal", due_days=3, assign_role="operations", created_by=ev.created_by,
    )
    notify_task(
        db, ev.tenant_id, task, assign_role="operations",
        href="/finance?tab=laytime",
    )


# ── TaskRule 通用物化（任何域事件 → 匹配的租户规则 → 任务） ──────────────

#: 域事件的实体类型 → TaskRule.trigger_entity_type 的取值
#: 租户在「任务规则」里按 trigger_entity_type 配规则；这里把业务事件
#: 的实体类型翻译成规则侧认识的类型。
_ENTITY_TYPE_ALIASES = {
    "voyage": "voyage",
    "invoice": "invoice",
    "claim": "claim",
    "bunker_order": "bunker_order",
    "port_disbursement": "port_disbursement",
    "coa_lifting": "charter",
    "charter_amendment": "charter",
    "charter": "charter",
}

#: 这些 kind 已由专用处理器用更完整的上下文物化过 —— 通用处理器跳过，
#: 避免同一规则被用两套 context 各判一次。
_SPECIALIZED_KINDS = {"voyage.completed"}


@on("*")
def on_any_event_materialize_task_rules(db: Session, ev: DomainEvent) -> None:
    """通配处理器：把命中的 TaskRule 物化成任务。

    以前只有 ``voyage.completed`` 一条路径能物化规则任务，其余 trigger
    只有 dry-run 端点（看得见却落不下）—— 这里补齐最后一环。
    幂等靠 ``dedupe_key``（``rule:<id>:<实体类型>:<实体ID>``），重复事件
    不会重复建任务。
    """
    if ev.kind in _SPECIALIZED_KINDS:
        return
    trigger = _ENTITY_TYPE_ALIASES.get(ev.entity_type or "")
    if not trigger:
        return
    payload = dict(ev.payload or {})
    payload.setdefault("id", str(ev.entity_id) if ev.entity_id else None)
    ctx = {trigger: payload}
    materialize_task_rules(
        db, ev.tenant_id, trigger, ctx, entity_id=ev.entity_id, created_by=ev.created_by,
        round_key=_round_token(db, ev, trigger),
    )


def _round_token(db: Session, ev: DomainEvent, trigger: str) -> str | None:
    """实体的"轮次"标记 —— 同一实体重新走一轮时用它区分幂等键。

    没有轮次标记时，同一实体一生只出一条规则任务：航次重开后再次完成，
    规则配的跟进任务就再也不出现了。
    """
    if ev.entity_id is None:
        return None
    try:
        if trigger == "voyage":
            from app.models_domain import Voyage

            row = db.get(Voyage, ev.entity_id)
            return row.completed_at.isoformat() if row is not None and row.completed_at else None
        if trigger == "invoice":
            from app.models_domain import Invoice

            row = db.get(Invoice, ev.entity_id)
            return row.issued_at.isoformat() if row is not None and row.issued_at else None
    except Exception:  # noqa: BLE001 —— 取不到轮次就退回旧口径
        return None
    return None
