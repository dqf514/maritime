"""Request XIV — 邮件实体落单扩展 / 忽略记忆 / 存档与通用附件 的 i18n 补种。

邮件新类型（油/使费/发票/索赔）的类型名、逐类型落单按钮、「忽略并记住」、
邮件存档选择器、通用附件面板。独立分片，避免与 a0-a3 并行编辑冲突。
"""

UI_MESSAGES_EXTRA = [
    # —— 邮件分类新类型 ——
    # bunker_offer / invoice / claim 已在 a3 分片；这里只补 PDA
    ("email.type.port_disbursement", "app", "PDA / Disbursement", "使费账单"),
    # —— 逐类型落单按钮 ——
    ("page.email.apply_bunker_order", "app", "Create bunker order", "生成订油单"),
    ("page.email.apply_charter", "app", "Create charter draft", "生成租约草稿"),
    ("page.email.apply_claim", "app", "Create claim record", "生成索赔记录"),
    ("page.email.apply_estimate", "app", "Create estimate draft", "生成估算草稿"),
    ("page.email.apply_invoice", "app", "Create invoice draft", "生成发票草稿"),
    ("page.email.apply_laytime", "app", "Create laytime calc", "生成装卸时间计算"),
    ("page.email.apply_nor", "app", "Stamp NOR time", "盖 NOR 时间戳"),
    ("page.email.apply_pda", "app", "Create PDA draft", "生成使费草稿"),
    ("page.email.apply_recap", "app", "Create estimate & charter drafts", "生成估算与租约草稿"),
    ("page.email.created_more", "app", "+{n} more draft(s) created", "另有 {n} 份草稿已生成"),
    # —— 存档目标类型名（email.type.* 复用/补缺） ——
    ("email.type.bunker_order", "app", "Bunker order", "订油单"),
    ("email.type.charter", "app", "Charter", "租约"),
    ("email.type.estimate", "app", "Estimate", "估算"),
    ("email.type.laytime", "app", "Laytime calc", "装卸时间计算"),
    ("email.type.voyage", "app", "Voyage", "航次"),
    # —— 忽略并记住 ——
    ("page.email.filter_ignored", "app", "Ignored", "已忽略"),
    ("page.email.ignore_btn", "app", "Ignore", "忽略"),
    ("page.email.ignore_fail", "app", "Ignore failed", "忽略失败"),
    ("page.email.ignore_hint", "app", "Ignore this suggestion; with \"remember\" on, the same sender won't be classified as this type again.", "忽略本次建议；勾选记住后，同一发件人不会再被识别为此类型。"),
    ("page.email.ignore_ok", "app", "Ignored — rule saved for this sender", "已忽略 — 已记住该发件人"),
    ("page.email.ignore_remember", "app", "Remember this mistake", "记住这次误判"),
    ("page.email.ignore_title", "app", "Ignore suggestion", "忽略建议"),
    ("page.email.ignored", "app", "Ignored", "已忽略"),
    ("page.email.ignored_at", "app", "Ignored at {time}", "已于 {time} 忽略"),
    # —— 邮件存档 ——
    ("page.email.archive_btn", "app", "Archive", "存档"),
    ("page.email.archive_done", "app", "Archived to {title} (v{n})", "已存档到 {title}（第 {n} 版）"),
    ("page.email.archive_entity", "app", "Target entity", "目标项目"),
    ("page.email.archive_entity_hint", "app", "The email body is saved as a versioned attachment on the selected record.", "邮件正文将作为附件（带版本）挂到所选记录下。"),
    ("page.email.archive_fail", "app", "Archive failed", "存档失败"),
    ("page.email.archive_load_fail", "app", "Could not load the entity list", "项目清单加载失败"),
    ("page.email.archive_pick", "app", "Pick a record", "选择项目"),
    ("page.email.archive_placeholder", "app", "Select…", "请选择…"),
    ("page.email.archive_title", "app", "Archive email to a record", "存档邮件到项目"),
    # —— 通用附件面板 ——
    ("att.bad_type", "app", "Only PDF / PNG / JPG / WebP / XLSX / CSV files are allowed", "仅支持 PDF / PNG / JPG / WebP / XLSX / CSV"),
    ("att.col_version", "app", "Version", "版本"),
    ("att.current", "app", "Current", "当前版"),
    ("att.delete", "app", "Delete", "删除"),
    ("att.delete_confirm", "app", "Delete this file? A new version can be uploaded afterwards.", "确认删除该文件？之后可重新上传新版本。"),
    ("att.delete_ok", "app", "File deleted", "文件已删除"),
    ("att.empty", "app", "No attachments yet", "暂无附件"),
    ("att.load_fail", "app", "Could not load attachments", "附件加载失败"),
    ("att.next_version", "app", "Upload as new version", "上传为新版本"),
    ("att.note", "app", "Note", "备注"),
    ("att.set_current", "app", "Set current", "设为当前版"),
    ("att.set_current_ok", "app", "Current version updated", "已切换当前版本"),
    ("att.title", "app", "Attachments", "附件"),
    ("att.upload", "app", "Upload", "上传"),
    ("att.upload_ok", "app", "Uploaded", "上传成功"),
    ("att.version", "app", "v{n}", "第 {n} 版"),
    ("att.need_file", "app", "Choose a file first", "请先选择文件"),
    ("common.note", "app", "Note", "备注"),
    ("common.size", "app", "Size", "大小"),
]
