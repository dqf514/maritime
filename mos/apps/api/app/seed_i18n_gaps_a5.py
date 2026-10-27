"""Request XVI — 登录页 SSO 优先（绑定 SSO 突出 SSO 按钮 / 密码收起备选 / 未激活提供商不显示）。

独立分片，避免与 a0-a4 并行编辑冲突。
"""

UI_MESSAGES_EXTRA = [
    ("login.sso_hero_hint", "app", "This tenant uses {provider} sign-on — you'll continue there.", "该租户已绑定 {provider} 单点登录 — 将跳转完成登录。"),
    ("login.sso_hint_multi", "app", "This tenant uses single sign-on — pick your work account above.", "该租户已启用单点登录 — 请使用上方工作账号继续。"),
    ("login.use_password", "app", "Use password instead", "改用密码登录"),
]
