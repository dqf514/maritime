"""Request XIX-B — 邮件详情「处理建议」区：可疑业务邮件打开即后台 AI 识别
（pending 芯片 → AI 结果动作 / 否则规则动作直接出）。

独立分片，避免与 a0-a5 并行编辑冲突。
"""

UI_MESSAGES_EXTRA = [
    ("page.email.sug_ai", "app", "AI-checked", "AI 识别"),
    ("page.email.sug_applied", "app", "Business draft already created — consider replying.", "已生成业务草稿 — 建议回复确认。"),
    ("page.email.sug_fail", "app", "AI check failed — rule-based actions below", "AI 识别失败 — 以下为规则建议"),
    ("page.email.sug_pending", "app", "AI is analyzing this email…", "AI 正在识别这封邮件…"),
    ("page.email.sug_pending_hint", "app", "Identifying type and next action — you can read the email meanwhile…", "正在识别类型与下一步动作 — 邮件内容可先阅读…"),
    ("page.email.sug_reason", "app", "Reason: {reason}", "推荐理由：{reason}"),
    ("page.email.sug_rule", "app", "Rule-based", "规则建议"),
    ("page.email.sug_retry", "app", "Retry", "重试"),
    ("page.email.sug_rerun", "app", "Re-check with AI", "重新识别"),
    ("page.email.sug_title", "app", "Suggested actions", "处理建议"),
    ("page.email.sug_type_diff", "app", "AI detected: {ai} (rules said: {rule})", "AI 识别为 {ai}（规则：{rule}）"),
]
