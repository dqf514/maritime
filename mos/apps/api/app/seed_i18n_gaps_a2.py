"""走查问题修复分片 i18n 种子 (a2) — 格式与 seed_i18n_extra.py 相同：
(key, "app", en, zh)。由 seed_i18n_extra.py 末尾自动加载。
"""
UI_MESSAGES_EXTRA: list[tuple[str, str, str, str]] = [
    # ── 总账科目表展示名（gl.png：数据仅英文 account_name，展示层走 coa.<code>）──
    ("coa.1000", "app", "Cash & banks", "现金及银行"),
    ("coa.1200", "app", "Accounts receivable", "应收账款"),
    ("coa.2000", "app", "Accounts payable", "应付账款"),
    ("coa.4000", "app", "Freight revenue", "运费收入"),
    ("coa.4010", "app", "Demurrage revenue", "滞期费收入"),
    ("coa.4100", "app", "Time charter hire revenue", "期租租金收入"),
    ("coa.5000", "app", "Bunker cost", "燃油成本"),
    ("coa.5100", "app", "Port & disbursement cost", "港口使费"),
    ("coa.5200", "app", "Commission", "佣金"),
    ("coa.5900", "app", "Other voyage cost", "其他航次成本"),
    # ── 科目类型枚举 ──
    ("coa.type.asset", "app", "Asset", "资产"),
    ("coa.type.liability", "app", "Liability", "负债"),
    ("coa.type.revenue", "app", "Revenue", "收入"),
    ("coa.type.expense", "app", "Expense", "费用"),
    ("coa.type.equity", "app", "Equity", "权益"),
    # ── Laytime 根因 / 延误类型 / 责任方（laytime-detail.png：port_congestion 等裸枚举）──
    ("laytime.cause.port_congestion", "app", "Port congestion", "港口拥堵"),
    ("laytime.cause.weather", "app", "Weather", "天气"),
    ("laytime.cause.cargo_delay", "app", "Cargo delay", "货物延误"),
    ("laytime.cause.documentation", "app", "Documentation", "单证"),
    ("laytime.cause.other", "app", "Other", "其他"),
    ("laytime.delay.weather", "app", "Weather", "天气"),
    ("laytime.delay.port_congestion", "app", "Port congestion", "港口拥堵"),
    ("laytime.delay.cargo", "app", "Cargo", "货物"),
    ("laytime.delay.documentation", "app", "Documentation", "单证"),
    ("laytime.delay.breakdown", "app", "Breakdown", "机械故障"),
    ("laytime.delay.other", "app", "Other", "其他"),
    ("laytime.party.owner", "app", "Owner", "船东"),
    ("laytime.party.charterer", "app", "Charterer", "租家"),
    ("laytime.party.port", "app", "Port", "港口"),
    ("laytime.party.agent", "app", "Agent", "代理"),
    ("laytime.party.other", "app", "Other", "其他"),
    # ── GL 日记账类型（gl 页 type 下拉裸枚举）──
    ("gl.journal_type.voyage", "app", "Voyage", "航次"),
    ("gl.journal_type.accrual", "app", "Accrual", "计提"),
    ("gl.journal_type.non_voyage", "app", "Non-voyage", "非航次"),
    ("gl.journal_type.ic", "app", "IC", "内部往来"),
    # ── 发票类型枚举（finance.png：类型下拉裸 freight/hire/…）──
    ("invoice.type.freight", "app", "Freight", "运费"),
    ("invoice.type.hire", "app", "Hire", "租金"),
    ("invoice.type.demurrage", "app", "Demurrage", "滞期费"),
    ("invoice.type.bunker", "app", "Bunker", "燃油"),
    ("invoice.type.port_disbursement", "app", "Port disbursement", "港口使费"),
    ("invoice.type.credit_note", "app", "Credit note", "红字发票"),
    ("invoice.type.other", "app", "Other", "其他"),
    # ── finance 按钮：原 page.finance.hs_generate 的 zh 为中英混写“生成 hire 发票”，
    #    不能改 seed_i18n_extra.py，改用干净 key ──
    ("page.finance.hs_action", "app", "Generate hire invoice", "生成租金发票"),
    # ── status.* 词表缺项（on-account 状态、laytime 结果）──
    ("status.applied", "app", "Applied", "已冲抵"),
    ("status.none", "app", "None", "无"),
    # ── 通用列头（emissions ID 列等）──
    ("common.id", "app", "ID", "ID"),
]
