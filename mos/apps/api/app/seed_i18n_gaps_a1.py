"""走查问题修复分片 i18n 种子 (a1) — 格式与 seed_i18n_extra.py 相同：
(key, "app", en, zh)。由 seed_i18n_extra.py 末尾自动加载。
"""
UI_MESSAGES_EXTRA: list[tuple[str, str, str, str]] = [
    # 船舶类型裸值（Tanker / Bulker …）中文化
    ("page.vessels.type_tanker", "app", "Tanker", "油轮"),
    ("page.vessels.type_bulker", "app", "Bulker", "散货船"),
    ("page.vessels.type_bulk", "app", "Bulk", "散货船"),
    ("page.vessels.type_container", "app", "Container", "集装箱船"),
    ("page.vessels.type_general_cargo", "app", "General cargo", "杂货船"),
    ("page.vessels.type_lng", "app", "LNG", "液化天然气船"),
    ("page.vessels.type_lpg", "app", "LPG", "液化石油气船"),
    ("page.vessels.type_chemical", "app", "Chemical", "化学品船"),
    ("page.vessels.type_product", "app", "Product", "成品油轮"),
    ("page.vessels.type_reefer", "app", "Reefer", "冷藏船"),
    ("page.vessels.type_roro", "app", "Ro-Ro", "滚装船"),
    ("page.vessels.type_offshore", "app", "Offshore", "海工船"),
    ("page.vessels.type_tug", "app", "Tug", "拖轮"),
    ("page.vessels.type_barge", "app", "Barge", "驳船"),
    ("page.vessels.type_other", "app", "Other", "其他"),
    # 回收站实体类型（a0 未覆盖）
    ("recycle.type.voyage_notes", "app", "Voyage notes", "航次备注"),
]
