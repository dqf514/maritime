"""登录页最近使用身份回填（租户+邮箱芯片行）。

独立分片，避免与 a0-a6 并行编辑冲突。
"""

UI_MESSAGES_EXTRA = [
    ("login.recent", "app", "Recent sign-ins", "最近登录"),
]
