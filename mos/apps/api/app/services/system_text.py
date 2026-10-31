"""系统自动生成的文案（任务标题 / 通知标题）—— 双语对照表。

系统生成的文案**随触发者 / 收件人的语言落库**：英文界面里不该挂着中文任务，
中文界面里也不该挂着英文任务。表里一条 = ``(en, zh)``，占位符用 ``{name}``。

与前端 ``t()`` 的分工：

* **前端能翻的**（按钮、列名、提示）→ 走 ``ui_messages`` 目录，前端自己翻；
* **后端生成的**（系统任务标题、通知、告警）→ 走本表，后端按用户语言取回再落库。

取不到对应语言时回落英文原文（``text()`` 永远不会返回空串）。
"""

from __future__ import annotations

# key → (en, zh)
TEXTS: dict[str, tuple[str, str]] = {
    # ── 航次完成 ────────────────────────────────────────────────────────
    "voyage.completed.notify.title": ("Voyage {voyage_no} completed", "航次 {voyage_no} 已完成"),
    "voyage.completed.notify.all_clear": (
        "Closeout checklist: all items complete",
        "收尾清单：全部齐备",
    ),
    "voyage.completed.notify.missing": (
        "Closeout checklist: missing {items}",
        "收尾清单：缺 {items}",
    ),
    "voyage.completed.notify.tasks": (
        "{count} follow-up task(s) created",
        "已生成 {count} 项跟进任务",
    ),
    "voyage.completed.notify.schedule": (
        "{count} schedule block(s) released",
        "船期块收缩 {count} 段",
    ),
    # ── COA 提货 ────────────────────────────────────────────────────────
    "lifting.fixed.task.title": (
        "Execute lifting voyage {voyage_no} — {charter_no}",
        "执行提货航次 {voyage_no} — {charter_no}",
    ),
    "lifting.fixed.task.desc": (
        "COA lifting {period} is fixed — track voyage execution and the lay date.",
        "COA 提货 {period} 已订租（fixed），请跟进航次执行与装期。",
    ),
    "lifting.over.alert.title": ("COA over-lift: {charter_no}", "COA 超装：{charter_no}"),
    "lifting.over.alert.body": (
        "Cumulative lift {lifted} exceeds the contract quantity {total} — confirm the variation or addendum.",
        "累计提货 {lifted} 已超合同量 {total}，请确认变更单/补充协议。",
    ),
    "lifting.over.task.title": ("Review COA over-lift — {charter_no}", "COA 超装复核 — {charter_no}"),
    "lifting.over.task.desc": (
        "Cumulative lift {lifted} is above the contract quantity {total}.",
        "累计提货 {lifted} > 合同量 {total}。",
    ),
    "lifting.short.task.title": ("Follow up COA short-lift — {charter_no}", "COA 短装跟进 — {charter_no}"),
    "lifting.short.task.desc": (
        "Cumulative lift {lifted} is below the contract quantity {total} — confirm the remaining volume.",
        "累计提货 {lifted} 低于合同量 {total}，请确认余量安排。",
    ),
    "lifting.deviation.alert.title": (
        "Lift quantity deviation: {charter_no} {period}",
        "提货量偏差：{charter_no} {period}",
    ),
    "lifting.deviation.alert.body": (
        "Actual {actual} vs planned {planned}.",
        "实际 {actual} vs 计划 {planned}。",
    ),
    # ── 租约修订 ────────────────────────────────────────────────────────
    "amendment.notify.title": ("Charter amendment approved: {charter_no}", "租约修订已批准：{charter_no}"),
    "amendment.notify.body": (
        "Changes: {changes}. Reason: {reason}",
        "变更：{changes}。原因：{reason}",
    ),
    "amendment.task.title": (
        "Review invoices and accruals against the amendment — {charter_no}",
        "按修订条款复核发票与计提 — {charter_no}",
    ),
    "amendment.task.desc": (
        "Terms changed ({fields}) — check open invoices and accruals for reissue or adjustment.",
        "条款已变更（{fields}），请复核未结发票/计提是否需要重开或调整。",
    ),
    # ── 发票 / 计提 ─────────────────────────────────────────────────────
    "invoice.issued.task.title": ("Post invoice to GL: {invoice_no}", "过账总账：发票 {invoice_no}"),
    "invoice.issued.task.desc": (
        "Invoice issued ({amount} {currency}) — check the accounts, then post it to the GL.",
        "发票已签发（{amount} {currency}），复核科目后过账 GL。",
    ),
    "invoice.accruals.task.title": (
        "Reconcile accruals: voyage invoice {invoice_no}",
        "计提对账：航次发票 {invoice_no}",
    ),
    "invoice.accruals.task.desc": (
        "This voyage has posted accruals — reconcile them against the invoice and reverse the difference.",
        "该航次存在已过账计提 —— 发票签发后请核对差异并冲回计提。",
    ),
    "invoice.credit_note.task.title": (
        "Review credit note {credit_note_no} (invoice {invoice_no})",
        "复核红冲单 {credit_note_no}（原单 {invoice_no}）",
    ),
    "invoice.credit_note.task.desc": (
        "Credit note issued for {amount} {currency} — check the reversal entry, and arrange a refund if the invoice was already paid.",
        "已红冲 {amount} {currency} —— 请核对反向分录；若原单已收款需安排退款。",
    ),
    "claim.to_invoice.task.title": (
        "Issue demurrage invoice {invoice_no}",
        "签发滞期费发票 {invoice_no}",
    ),
    "claim.to_invoice.task.desc": (
        "Claim {claim_no} was converted into a draft invoice — review it, then issue it.",
        "索赔 {claim_no} 已转为发票草稿，核对后请签发。",
    ),
    "invoice.refund.task.title": (
        "Arrange a refund for {invoice_no}",
        "为 {invoice_no} 安排退款",
    ),
    "invoice.refund.task.desc": (
        "A credit note of {amount} {currency} was issued against an invoice that was already paid — refund the difference.",
        "已对已收款的发票红冲 {amount} {currency} —— 请安排退还差额。",
    ),
    # ── 港口使费 ────────────────────────────────────────────────────────
    "pda.posted.notify.title": (
        "PDA auto-posted: {amount} {currency}",
        "PDA 已自动过账：{amount} {currency}",
    ),
    "pda.posted.notify.body": (
        "Port disbursement voucher posted (period {period}).",
        "港口使费凭证已过账（period {period}）。",
    ),
    "pda.pending.task.title": ("PDA pending posting: {ref}", "PDA 待过账：{ref}"),
    "pda.pending.task.desc": (
        "The PDA was closed but auto-posting did not complete ({outcome}) — enter the voucher or fix the account mapping.",
        "PDA 已关闭但自动过账未完成（{outcome}），请补录凭证或调整科目规则。",
    ),
    # ── 加油 ────────────────────────────────────────────────────────────
    "bunker.alert.title": ("Bunker delivery exception: {order_no}", "加油交付异常：{order_no}"),
    "bunker.task.title": ("Reconcile bunker delivery: {order_no}", "核对加油交付：{order_no}"),
    # ── 索赔 ────────────────────────────────────────────────────────────
    "claim.settled.task.title": ("Convert claim to settlement: {claim_no}", "索赔转结算：{claim_no}"),
    "claim.settled.task.desc": (
        "Claim settled ({amount} {currency}) — issue the invoice and record the payment.",
        "索赔已和解（{amount} {currency}），请开具发票/登记收付款。",
    ),
    # ── NOR / 装卸时间 ─────────────────────────────────────────────────
    "nor.notify.title": ("NOR recorded: {voyage_no}", "NOR 已落位：{voyage_no}"),
    "nor.notify.body": (
        "NOR time {nor_at} was written to the port call.",
        "NOR 时间 {nor_at} 已写入挂靠港。",
    ),
    "laytime.draft.task.title": ("Review laytime draft: {voyage_no}", "复核装卸时间草稿：{voyage_no}"),
    "laytime.draft.task.desc": (
        "Mail parsing created a laytime draft — check the events and terms, then finalise it.",
        "邮件解析生成了装卸时间计算草稿，请核对事件与条款后定稿。",
    ),
    # ── 任务中心自身的通知 ─────────────────────────────────────────────
    "task.auto_complete.body": (
        "The system action for this task is done — the task was completed automatically.",
        "该任务的系统动作已完成，任务已自动勾选完成。",
    ),
    "task.mention.title": ("You were mentioned: {title}", "你被提及：{title}"),
    # ── 证书到期预警（首页告警 → 通知中心）──────────────────────────────
    "cert.expiring.body": ("{code} expires on {date}", "{code} 于 {date} 到期"),
    "cert.expired.body": ("{code} expired on {date}", "{code} 已于 {date} 过期"),
    "crew.cert.expiring.body": (
        "{name} · {code} expires on {date}",
        "{name} · {code} 于 {date} 到期",
    ),
    "crew.cert.expired.body": (
        "{name} · {code} expired on {date}",
        "{name} · {code} 已于 {date} 过期",
    ),
}


def text(key: str, locale: str = "en", **vars) -> str:
    """按 locale 取一条系统文案并填空（未知键 → 返回键本身，不抛异常）。"""
    pair = TEXTS.get(key)
    if pair is None:
        raw = key
    else:
        raw = pair[1] if (locale or "en").startswith("zh") else pair[0]
    for name, value in vars.items():
        raw = raw.replace("{" + name + "}", str(value))
    return raw


def pair(key: str, **vars) -> tuple[str, str]:
    """取一条系统文案的双语变体（en, zh）—— 供通知按收件人语言再挑一次。"""
    en, zh = TEXTS.get(key, (key, key))
    if vars:
        en = text(key, "en", **vars)
        zh = text(key, "zh-CN", **vars)
    return en, zh
