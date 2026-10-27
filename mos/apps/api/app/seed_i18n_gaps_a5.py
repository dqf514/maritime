"""Request XVI/XVII — 登录页 SSO 优先（绑定 SSO 突出 SSO 按钮 / 密码收起备选 / 未激活提供商不显示）
+ 邮件复核同步状态芯片（同步中/已同步 N 封/失败/上次同步 x 前）。

独立分片，避免与 a0-a4 并行编辑冲突。
"""

UI_MESSAGES_EXTRA = [
    ("login.sso_hero_hint", "app", "This tenant uses {provider} sign-on — you'll continue there.", "该租户已绑定 {provider} 单点登录 — 将跳转完成登录。"),
    ("login.sso_hint_multi", "app", "This tenant uses single sign-on — pick your work account above.", "该租户已启用单点登录 — 请使用上方工作账号继续。"),
    ("login.use_password", "app", "Use password instead", "改用密码登录"),
    ("page.email.sync_btn_busy", "app", "Syncing…", "同步中…"),
    ("page.email.syncing_chip", "app", "Syncing {folders}… {s}s", "正在同步 {folders}… {s}s"),
    ("page.email.synced_chip", "app", "Synced — {n} new", "已同步 — {n} 封新邮件"),
    ("page.email.synced_none", "app", "Synced — no new mail", "同步完成 — 无新邮件"),
    ("page.email.sync_error_chip", "app", "Sync failed", "同步失败"),
    ("page.email.last_synced", "app", "Last sync {when}", "上次同步 {when}"),
    ("page.email.just_now", "app", "just now", "刚刚"),
    ("page.email.ago_min", "app", "{n} min ago", "{n} 分钟前"),
    ("page.email.ago_hour", "app", "{n}h ago", "{n} 小时前"),
]
