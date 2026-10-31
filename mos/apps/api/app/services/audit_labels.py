"""操作日志的动作文案 —— 把审计里的技术码翻成人话。

审计表里存的是 ``{entity}.{verb}`` 与 ``api.{method}`` 这样的**技术码**
（``task.auto_complete``、``api.post`` …）。直接甩给用户看等于让人读日志：
"Demo Admin post"、"某人 auto_complete task" —— 谁也看不懂发生了什么。

本模块负责把它们翻成「动词 + 实体」的可读文案，并按请求人的语言出
（英文界面给英文，中文界面给中文）。前端只管显示，不再自己猜。

口径：
* ``api.<method>`` → 从 ``detail.path`` 里认出资源（``/api/v1/invoices`` → 发票），
  动词取方法（POST→创建 / PUT·PATCH→更新 / DELETE→删除）；
* ``<实体>.<动词>`` → 实体名 + 动词名（``task.transfer`` → 任务已转派）；
* 认不出来的 → 原样返回技术码（宁可显示码，也不要瞎猜）。

动词表每条三个值：``(英文, 中文动词前缀, 中文整句模板)``。
中文模板为 ``None`` 时用「动词前缀 + 实体名」（创建任务）；
不为 ``None`` 时把实体名填进模板（航次状态变更）—— 中文语序与英文相反，
两种语序都要能用，才不会拼出"变更了航次"这种别扭话。
"""

from __future__ import annotations

import re

# 实体 → (英文, 中文)
ENTITY_LABELS: dict[str, tuple[str, str]] = {
    "task": ("task", "任务"),
    "voyage": ("voyage", "航次"),
    "invoice": ("invoice", "发票"),
    "credit_note": ("credit note", "红冲单"),
    "claim": ("claim", "索赔"),
    "charter": ("charter", "租约"),
    "charter_amendment": ("amendment", "租约修订"),
    "coa_lifting": ("lifting", "提货"),
    "estimate": ("estimate", "估算"),
    "counterparty": ("counterparty", "交易对手"),
    "vessel": ("vessel", "船舶"),
    "ship": ("vessel", "船舶"),
    "ship_certificate": ("certificate", "证书"),
    "crew": ("crew member", "船员"),
    "port_call": ("port call", "挂靠"),
    "port_disbursement": ("PDA", "港口使费"),
    "bunker_order": ("bunker order", "加油订单"),
    "laytime": ("laytime calculation", "装卸时间计算"),
    "accrual": ("accrual", "计提"),
    "voyage_accrual": ("accrual", "计提"),
    "journal": ("journal entry", "分录"),
    "period_journal": ("journal entry", "分录"),
    "payment": ("payment", "收付款"),
    "cargo": ("cargo", "货物"),
    "user": ("user", "用户"),
    "tenant": ("tenant", "租户"),
    "role": ("role", "角色"),
    "email_message": ("email", "邮件"),
    "email": ("email", "邮件"),
    "workflow_instance": ("workflow", "工作流"),
    "work_package": ("work package", "工作包"),
    "objective": ("OKR objective", "OKR 目标"),
    "key_result": ("key result", "关键结果"),
    "routine_draft": ("routine draft", "例行草稿"),
    "flag": ("feature flag", "功能开关"),
    "config": ("configuration", "配置"),
    "template": ("template", "模板"),
    "notification": ("notification", "通知"),
    "document": ("document", "单据"),
    "approval": ("approval", "审批"),
    "report": ("report", "报表"),
    "dashboard": ("dashboard", "看板"),
    "market_data": ("market data", "市场数据"),
    "reference": ("reference data", "基础数据"),
    "office": ("office document", "单证"),
    "rate": ("rate", "费率"),
    "master_data": ("master data", "主数据"),
    "import": ("import job", "导入作业"),
    "compliance": ("compliance record", "合规记录"),
}

# 动词 → (英文, 中文动词前缀, 中文整句模板或 None)
VERB_LABELS: dict[str, tuple[str, str, str | None]] = {
    "post": ("Created", "创建", None),
    "put": ("Updated", "更新", None),
    "patch": ("Updated", "更新", None),
    "delete": ("Deleted", "删除", None),
    "create": ("Created", "创建", None),
    "update": ("Updated", "更新", None),
    "import": ("Imported", "导入", None),
    "export": ("Exported", "导出", None),
    "transition": ("changed status of", "变更", "{entity}状态变更"),
    "auto_complete": ("auto-completed", "自动完成", "{entity}已自动完成"),
    "complete": ("completed", "完成", "{entity}已完成"),
    "reopen": ("reopened", "重开", "{entity}已重开"),
    "transfer": ("reassigned", "转派", "{entity}已转派"),
    "comment": ("commented on", "评论", "{entity}收到评论"),
    "system": ("System created", "系统生成", None),
    "login_success": ("signed in", "登录", None),
    "login": ("signed in", "登录", None),
    "issue": ("issued", "签发", "{entity}已签发"),
    "issued": ("issued", "签发", "{entity}已签发"),
    "settle": ("settled", "结算", "{entity}已结算"),
    "settled": ("settled", "结算", "{entity}已结算"),
    "reverse": ("reversed", "冲回", "{entity}已冲回"),
    "reversed": ("reversed", "冲回", "{entity}已冲回"),
    "record": ("recorded", "登记", "{entity}已登记"),
    "approve": ("approved", "批准", "{entity}已批准"),
    "approved": ("approved", "批准", "{entity}已批准"),
    "reject": ("rejected", "驳回", "{entity}已驳回"),
    "rejected": ("rejected", "驳回", "{entity}已驳回"),
    "close": ("closed", "关闭", "{entity}已关闭"),
    "closed": ("closed", "关闭", "{entity}已关闭"),
    "cancel": ("cancelled", "取消", "{entity}已取消"),
    "cancelled": ("cancelled", "取消", "{entity}已取消"),
    "notify": ("notified", "通知", "{entity}已通知"),
    "assign": ("assigned", "指派", "{entity}已指派"),
    "reply": ("replied to", "回复", "{entity}收到回复"),
    "sync": ("synced", "同步", "{entity}已同步"),
}

# 资源路径段 → 实体键（``api.post`` 那条路要用）
PATH_ENTITY: dict[str, str] = {
    "voyages": "voyage",
    "invoices": "invoice",
    "credit-notes": "credit_note",
    "claims": "claim",
    "charters": "charter",
    "charter-amendments": "charter_amendment",
    "coa-liftings": "coa_lifting",
    "estimates": "estimate",
    "counterparties": "counterparty",
    "vessels": "vessel",
    "ship-certificates": "ship_certificate",
    "crew": "crew",
    "port-calls": "port_call",
    "port-disbursements": "port_disbursement",
    "bunker-orders": "bunker_order",
    "laytimes": "laytime",
    "accruals": "accrual",
    "payments": "payment",
    "cargo-book": "cargo",
    "tasks": "task",
    "work-packages": "work_package",
    "objectives": "objective",
    "key-results": "key_result",
    "emails": "email_message",
    "workflows": "workflow_instance",
    "users": "user",
    "roles": "role",
    "flags": "flag",
    "templates": "template",
    "documents": "document",
    "reports": "report",
    "approvals": "approval",
    "dashboards": "dashboard",
    "market-data": "market_data",
    "reference": "reference",
    "office": "office",
    "rates": "rate",
    "masterdata": "master_data",
    "imports": "import",
    "compliance": "compliance",
    "settings": "config",
    "config": "config",
}

_PATH_RE = re.compile(r"/api/v1/([a-z0-9\-]+)")

# 路径里表示「动作」的尾段 —— 认实体时跳过它们
# （/tasks/{id}/comments 是给任务加评论，不是「创建评论」）
_ACTION_SEGMENTS = frozenset(
    {
        "transition",
        "comments",
        "comment",
        "transfer",
        "complete",
        "reopen",
        "clone",
        "compare",
        "preview",
        "run",
        "dismiss",
        "locale",
        "to-charter",
        "to-invoice",
        "credit-note",
        "issue",
        "settle",
        "finalize",
        "post-gl",
    }
)

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")


def _is_zh(locale: str | None) -> bool:
    return bool(locale) and str(locale).lower().startswith("zh")


def entity_label(entity_type: str | None, locale: str = "en") -> str | None:
    """实体键 → 可读名（认不出返回 None，让前端回落原始值）。"""
    if not entity_type:
        return None
    pair_ = ENTITY_LABELS.get(entity_type)
    if pair_ is None:
        return None
    return pair_[1] if _is_zh(locale) else pair_[0]


def _entity_from_path(path: str | None) -> str | None:
    """从资源路径认出实体。

    路径有多层（``/documents/templates/{id}/preview``、``/tasks/{id}/comments``），
    所以**逐段扫**，取第一个认得的资源段 —— 只看第一段的话，
    "创建模板" 会因为首段是 ``documents`` 而认不出来。
    """
    if not path:
        return None
    m = _PATH_RE.search(path)
    if not m:
        return None
    tail = path[m.end() :]
    for seg in tail.split("/"):
        if not seg:
            continue
        if seg in _ACTION_SEGMENTS or _UUID_RE.match(seg):
            continue
        hit = PATH_ENTITY.get(seg)
        if hit:
            return hit
    # 一段都没认出来 —— 至少把首段当实体（/api/v1/settings → settings）
    first = m.group(1)
    return PATH_ENTITY.get(first)


def entity_key_from_path(path: str | None) -> str | None:
    """资源路径 → 实体键（``/api/v1/invoices`` → ``invoice``）。"""
    return _entity_from_path(path)


def action_label(
    action: str | None,
    *,
    detail: dict | None = None,
    entity_type: str | None = None,
    locale: str = "en",
) -> str:
    """把审计动作码翻成可读文案。

    ``api.post`` 这类通用动作会从 ``detail["path"]`` 认出资源；
    认不出资源时退化成「动词 + 原实体名」，再认不出就原样返回动作码。
    """
    action = (action or "").strip()
    if not action:
        return ""
    detail = detail or {}
    zh = _is_zh(locale)

    parts = action.split(".")
    if parts[0] == "api":
        method = parts[1] if len(parts) > 1 else ""
        verb = VERB_LABELS.get(method)
        res = _entity_from_path(detail.get("path"))
        ent = entity_label(res, locale) if res else None
        if ent is None:
            ent = entity_label(entity_type, locale)
        if verb is None:
            return action
        return _compose(verb, ent, zh)

    ent_key = parts[0]
    verb_key = parts[1] if len(parts) > 1 else ""
    # ``task.create.system`` —— 第三段是 system：系统干的，不是人干的
    if len(parts) > 2 and parts[2] == "system":
        verb_key = "system"
    ent = entity_label(ent_key, locale)
    verb = VERB_LABELS.get(verb_key)
    if verb is None:
        if ent:
            return f"{ent} · {action}"
        return action
    return _compose(verb, ent, zh)


def _compose(verb: tuple[str, str, str | None], ent: str | None, zh: bool) -> str:
    en, zh_prefix, zh_tpl = verb
    if zh:
        if zh_tpl:
            return zh_tpl.format(entity=ent) if ent else zh_prefix
        return f"{zh_prefix}{ent}" if ent else zh_prefix
    if ent:
        return f"{en} {ent}"
    return en
