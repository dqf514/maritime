"""走查问题修复分片 i18n 种子 (a3) — 格式与 seed_i18n_extra.py 相同：
(key, "app", en, zh)。由 seed_i18n_extra.py 末尾自动加载。
"""
UI_MESSAGES_EXTRA: list[tuple[str, str, str, str]] = [
    # ── 邮件解析字段标签（email review 解析字段 kv 展示）──
    ("email.parse.vessel", "app", "Vessel", "船舶"),
    ("email.parse.vessel_name", "app", "Vessel", "船舶"),
    ("email.parse.cargo", "app", "Cargo", "货物"),
    ("email.parse.laycan", "app", "Laycan", "受载期"),
    ("email.parse.load_port", "app", "Load port", "装货港"),
    ("email.parse.discharge_port", "app", "Discharge port", "卸货港"),
    ("email.parse.freight_rate", "app", "Freight rate", "运价"),
    ("email.parse.demurrage_rate", "app", "Demurrage rate", "滞期费率"),
    ("email.parse.despatch_rate", "app", "Despatch rate", "速遣费率"),
    ("email.parse.laytime_load", "app", "Load laytime", "装货装卸时间"),
    ("email.parse.laytime_discharge", "app", "Discharge laytime", "卸货装卸时间"),
    ("email.parse.commission", "app", "Commission", "佣金"),
    ("email.parse.charterers", "app", "Charterers", "租家"),
    ("email.parse.owners", "app", "Owners", "船东"),
    ("email.parse.port", "app", "Port", "港口"),
    ("email.parse.date_time", "app", "Date / time", "日期时间"),
    ("email.parse.position", "app", "Position", "船位"),
    ("email.parse.draft", "app", "Draft", "吃水"),
    ("email.parse.events", "app", "Events", "事件数"),
    ("email.parse.event_count", "app", "Event count", "事件条数"),
    ("email.parse.allowed_days", "app", "Allowed days", "允许天数"),
    ("email.parse.counterparty", "app", "Counterparty", "对手方"),
    # ── 邮件识别类型徽章 ──
    ("email.type.fixture_recap", "app", "Fixture recap", "成交确认"),
    ("email.type.recap", "app", "Recap", "成交确认"),
    ("email.type.nor", "app", "NOR", "装卸准备就绪通知"),
    ("email.type.laytime_statement", "app", "Laytime statement", "装卸时间计算"),
    ("email.type.bunker_offer", "app", "Bunker offer", "加油报价"),
    ("email.type.invoice", "app", "Invoice", "发票"),
    ("email.type.claim", "app", "Claim", "索赔"),
    ("email.type.general", "app", "General", "一般邮件"),
    # ── 航次挂靠用途 ──
    ("page.voyages.purpose_load", "app", "Load", "装货"),
    ("page.voyages.purpose_discharge", "app", "Discharge", "卸货"),
    ("page.voyages.purpose_bunker", "app", "Bunker", "加油"),
    ("page.voyages.purpose_transit", "app", "Transit", "过境"),
    # ── 船期块类型 ──
    ("page.voyages.block_voyage", "app", "Voyage", "航次"),
    ("page.voyages.block_offhire", "app", "Off-hire", "停租"),
    ("page.voyages.block_repair", "app", "Repair", "修理"),
    # ── 付款批次银行费用承担方 ──
    ("page.payments.charge_shared", "app", "Shared", "共担"),
    ("page.payments.charge_sender", "app", "Sender", "付款方承担"),
    ("page.payments.charge_receiver", "app", "Receiver", "收款方承担"),
    # ── 租约状态机动作按钮（go_<status>）──
    ("page.charters.go_draft", "app", "Back to draft", "退回草稿"),
    ("page.charters.go_pending_approval", "app", "Submit for approval", "提交审批"),
    ("page.charters.go_active", "app", "Activate", "生效"),
    ("page.charters.go_completed", "app", "Complete", "完成"),
    ("page.charters.go_cancelled", "app", "Cancel", "取消"),
    # ── 孪生告警级别（StatusBadge status.* 词表补缺）──
    ("status.warn", "app", "Warning", "警告"),
    ("status.info", "app", "Info", "提示"),
    ("status.critical", "app", "Critical", "严重"),
    # ── 孪生页经纬度列 ──
    ("page.twin.lat", "app", "LAT", "纬度"),
    ("page.twin.lon", "app", "LON", "经度"),
]
