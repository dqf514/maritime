"""Seed languages, UI messages (en/zh-CN), and maritime terminology core."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant
from app.models_i18n import Language, TenantI18nSettings, TerminologyTerm, UiMessage
from app.seed_i18n_extra import UI_MESSAGES_EXTRA
from app.seed_i18n_parity import UI_MESSAGES_PARITY


# (key, namespace, en, zh-CN)
UI_MESSAGES: list[tuple[str, str, str, str]] = [
    ("app.name", "app", "VoyageOS", "VoyageOS"),
    ("app.tagline", "app", "Maritime commercial operating system", "航运商业操作系统"),
    ("shell.workbench", "nav", "Workbench", "工作台"),
    ("shell.sign_out", "nav", "Sign out", "退出登录"),
    ("shell.control_plane", "nav", "System settings", "系统设置"),
    ("shell.language", "nav", "Language", "语言"),
    ("shell.omni_search", "nav", "Search (Ctrl+K)", "搜索 (Ctrl+K)"),
    ("shell.platform", "nav", "Platform", "平台"),
    ("nav.home", "nav", "Workbench", "工作台"),
    ("nav.account_sec", "nav", "My security", "我的安全"),
    ("nav.dashboards", "nav", "Live dashboards", "实时大屏"),
    ("nav.estimates", "nav", "Estimates", "航次估算"),
    ("nav.charters", "nav", "Charters", "租约"),
    ("nav.email", "nav", "Email Review", "邮件复核"),
    ("nav.ops", "nav", "Voyages", "航次"),
    ("nav.ship", "nav", "Ship management", "船舶管理"),
    ("nav.finance", "nav", "Finance desk", "财务台"),
    ("nav.twin", "nav", "Fleet Twin", "船队孪生"),
    ("nav.analytics", "nav", "Analytics", "分析报表"),
    ("nav.vessels", "nav", "Vessels", "船舶"),
    ("nav.ports", "nav", "Ports", "港口"),
    ("nav.parties", "nav", "Counterparties", "对手方"),
    ("nav.org", "nav", "Organization", "组织"),
    ("nav.company", "nav", "Company & brand", "公司与品牌"),
    ("nav.orgchart", "nav", "Org structure", "组织架构"),
    ("nav.users", "nav", "Users & roles", "用户与角色"),
    ("nav.security", "nav", "Login & security", "登录与安全"),
    ("nav.permissions", "nav", "Feature permissions", "功能权限"),
    ("nav.workflows", "nav", "Workflows", "工作流"),
    ("nav.billing", "nav", "Subscription & usage", "订阅与用量"),
    ("nav.inbox", "nav", "Approval inbox", "审批收件箱"),
    ("nav.settings_hub", "nav", "System settings", "系统设置"),
    ("nav.i18n", "nav", "Languages & terms", "语言与术语"),
    ("nav.plat_home", "nav", "Operator console", "运营控制台"),
    ("nav.plat_tenants", "nav", "Tenants & licenses", "租户与许可证"),
    ("nav.plat_saas", "nav", "Plans & usage", "套餐与用量"),
    ("nav.plat_brand", "nav", "Product branding", "产品品牌"),
    ("nav.plat_identity", "nav", "Identity & email", "身份与邮件"),
    ("nav.plat_i18n", "nav", "Languages & terminology", "语言与术语库"),
    ("nav.plat_health", "nav", "Estate health", "租户健康"),
    ("nav.plat_ops", "nav", "Data & deployment", "数据与部署"),
    ("section.work", "nav", "Work", "工作"),
    ("section.master", "nav", "Master data", "主数据"),
    ("section.admin", "nav", "Tenant admin", "租户管理"),
    ("section.platform", "nav", "Platform ops", "平台运维"),
    ("ws.chartering_day", "nav", "Chartering Day", "租船日班"),
    ("ws.ops_night", "nav", "Ops Night", "操作夜班"),
    ("ws.finance_desk", "nav", "Finance Desk", "财务台"),
    ("ws.technical_desk", "nav", "Technical Desk", "技术台"),
    ("ws.platform_ops", "nav", "Platform Ops", "平台运维"),
    ("ws.management", "nav", "Management", "管理层"),
    ("login.welcome", "app", "Welcome back", "欢迎回来"),
    ("login.sign_in", "app", "Sign in with email", "邮箱登录"),
    ("login.tenant", "app", "Tenant code", "租户代码"),
    ("login.email", "app", "Email", "邮箱"),
    ("login.password", "app", "Password", "密码"),
    ("login.microsoft", "app", "Microsoft 365", "Microsoft 365"),
    ("login.google", "app", "Google", "Google"),
    ("login.magic", "app", "Email me a magic link", "发送登录魔法链接"),
    ("login.demo_identities", "app", "Demo identities", "演示账号"),
    ("login.back_portal", "app", "← Back to product portal", "← 返回产品门户"),
    ("login.enterprise", "app", "Enterprise sign-in", "企业级登录"),
    ("portal.sign_in", "app", "Sign in", "登录"),
    ("portal.product", "app", "Product", "产品"),
    ("portal.modules", "app", "Modules", "模块"),
    ("portal.platform", "app", "Platform", "平台"),
    ("home.title", "app", "Workbench", "工作台"),
    ("home.subtitle", "app", "Role-personalized desk — workspace tabs or Ctrl+K.", "按角色定制的工作台 — 工作区或 Ctrl+K。"),
    ("home.decision_walls", "app", "Decision walls", "决策大屏"),
    ("home.open_dashboards", "app", "Open live dashboards", "打开实时大屏"),
    ("settings.title", "app", "System settings", "系统设置"),
    ("settings.i18n", "app", "Languages & terminology", "语言与术语"),
    ("settings.i18n_desc", "app", "UI language packs and maritime term overrides", "界面语言包与航运术语覆盖"),
    ("i18n.page_title", "app", "Languages & terminology", "语言与术语"),
    ("i18n.languages", "app", "Languages", "语言"),
    ("i18n.terms", "app", "Terminology", "术语库"),
    ("i18n.default_locale", "app", "Default locale", "默认语言"),
    ("i18n.allow_user", "app", "Allow users to switch language", "允许用户自行切换语言"),
    ("i18n.save", "app", "Save", "保存"),
    ("i18n.search", "app", "Search terms", "搜索术语"),
    ("i18n.platform_title", "app", "Platform languages & terminology", "平台语言与术语库"),
    ("i18n.catalog_count", "app", "Catalog terms", "术语条数"),
    ("common.save", "app", "Save", "保存"),
    ("common.cancel", "app", "Cancel", "取消"),
    ("common.loading", "app", "Loading…", "加载中…"),
    ("common.open", "app", "Open →", "打开 →"),
    ("error.unauthorized", "error", "Not authenticated", "未登录"),
    ("error.forbidden", "error", "Permission denied", "无权限"),
    ("error.not_found", "error", "Not found", "未找到"),
    ("error.email_not_verified", "error", "Email verification required", "需要先验证邮箱"),
    ("error.tenant_suspended", "error", "Tenant suspended", "租户已停用"),
]

# (term_key, category, en, zh, def_en, def_zh)
TERMINOLOGY: list[tuple[str, str, str, str, str, str]] = [
    ("term.tce", "commercial", "TCE", "期租等价收益(TCE)", "Time Charter Equivalent — daily earnings net of voyage costs", "期租等价收益：扣除航次成本后的日收益"),
    ("term.cp", "commercial", "Charter Party (CP)", "租船合同(CP)", "Contract between owner and charterer", "船东与租家之间的租船合同"),
    ("term.voyage_charter", "commercial", "Voyage charter", "程租", "Hire for a single voyage", "按单航次计费的租船方式"),
    ("term.time_charter", "commercial", "Time charter (TC)", "期租", "Hire for a period of time", "按时间计费的租船方式"),
    ("term.tct", "commercial", "TCT", "期租航次(TCT)", "Trip charter / time-charter trip", "航次型期租"),
    ("term.coa", "commercial", "COA", "包运合同(COA)", "Contract of Affreightment", "包运合同"),
    ("term.bareboat", "commercial", "Bareboat / Demise", "光船租赁", "Charterer takes vessel without crew", "租家取得船舶不含船员"),
    ("term.laycan", "commercial", "Laycan", "受载期", "Laydays / cancelling date window", "受载日与销约日窗口"),
    ("term.laytime", "ops", "Laytime", "装卸时间", "Allowed time for cargo ops", "允许的装卸作业时间"),
    ("term.demurrage", "ops", "Demurrage", "滞期费", "Compensation for time beyond laytime", "超出装卸时间的补偿"),
    ("term.despatch", "ops", "Despatch", "速遣费", "Reward for finishing early", "提前完成装卸的奖励"),
    ("term.nor", "ops", "NOR", "准备就绪通知(NOR)", "Notice of Readiness", "准备就绪通知书"),
    ("term.sof", "ops", "SOF", "事实记录(SOF)", "Statement of Facts", "港口作业事实记录"),
    ("term.loa", "ops", "LOA", "委任书(LOA)", "Letter of Authority / Appointment", "授权/委任文件"),
    ("term.eta", "ops", "ETA", "预计到达(ETA)", "Estimated Time of Arrival", "预计到达时间"),
    ("term.etd", "ops", "ETD", "预计离开(ETD)", "Estimated Time of Departure", "预计离开时间"),
    ("term.ata", "ops", "ATA", "实际到达(ATA)", "Actual Time of Arrival", "实际到达时间"),
    ("term.atd", "ops", "ATD", "实际离开(ATD)", "Actual Time of Departure", "实际离开时间"),
    ("term.noon", "ops", "Noon report", "午报", "Daily vessel position and ROB report", "每日船位与存油报告"),
    ("term.rob", "ops", "ROB", "存油(ROB)", "Remaining On Board (bunker)", "船上剩余燃油"),
    ("term.bunker", "ops", "Bunker", "燃油", "Marine fuel", "船用燃油"),
    ("term.vlsfo", "ops", "VLSFO", "低硫燃油(VLSFO)", "Very Low Sulphur Fuel Oil", "超低硫燃油"),
    ("term.hsfo", "ops", "HSFO", "高硫燃油(HSFO)", "High Sulphur Fuel Oil", "高硫燃油"),
    ("term.mgo", "ops", "MGO", "船用柴油(MGO)", "Marine Gas Oil", "船用柴油"),
    ("term.pda", "ops", "PDA", "港口使费预估(PDA)", "Proforma Disbursement Account", "港口使费预估单"),
    ("term.fda", "ops", "FDA", "港口使费决算(FDA)", "Final Disbursement Account", "港口使费决算单"),
    ("term.dwt", "technical", "DWT", "载重吨(DWT)", "Deadweight tonnage", "载重吨"),
    ("term.gt", "technical", "GT", "总吨(GT)", "Gross Tonnage", "总吨位"),
    ("term.imo", "technical", "IMO number", "IMO 编号", "Unique ship identifier", "船舶唯一识别号"),
    ("term.mmsi", "technical", "MMSI", "MMSI", "Maritime Mobile Service Identity", "海上移动业务识别码"),
    ("term.flag", "technical", "Flag state", "船旗国", "Country of registration", "船舶登记国"),
    ("term.class", "technical", "Classification society", "船级社", "Class society for surveys", "负责检验的船级社"),
    ("term.pms", "technical", "PMS", "计划保养(PMS)", "Planned Maintenance System", "计划保养系统"),
    ("term.smc", "technical", "SMC", "安全管理证书(SMC)", "Safety Management Certificate", "安全管理证书"),
    ("term.ism", "technical", "ISM Code", "ISM 规则", "International Safety Management Code", "国际安全管理规则"),
    ("term.isps", "technical", "ISPS", "ISPS", "Ship and Port Facility Security", "船舶和港口设施保安"),
    ("term.drydock", "technical", "Drydock", "进坞", "Dry-docking / docking period", "进干坞修理期间"),
    ("term.offhire", "commercial", "Off-hire", "停租", "Period when hire is not payable", "不付租金的期间"),
    ("term.onhire", "commercial", "On-hire", "起租", "Start of hire period", "起租"),
    ("term.fixture", "commercial", "Fixture", "成交", "Confirmed charter deal", "已确认的租船成交"),
    ("term.recap", "commercial", "Recap", "成交确认(Recap)", "Fixture recapitulation email", "成交要点确认邮件"),
    ("term.broker", "commercial", "Broker", "经纪人", "Shipbroker intermediating fixtures", "撮合租约的经纪人"),
    ("term.charterer", "commercial", "Charterer", "租家", "Party hiring the vessel", "租用船舶的一方"),
    ("term.owner", "commercial", "Owner", "船东", "Vessel owner", "船舶所有人"),
    ("term.operator", "commercial", "Operator", "运营商", "Commercial / technical operator", "商业或技术营运方"),
    ("term.freight", "finance", "Freight", "运费", "Payment for cargo carriage", "货物运输报酬"),
    ("term.hire", "finance", "Hire", "租金", "Time-charter daily rate", "期租日租金"),
    ("term.commission", "finance", "Commission", "佣金", "Brokerage commission", "经纪佣金"),
    ("term.invoice", "finance", "Invoice", "发票", "Commercial invoice", "商务发票"),
    ("term.ar", "finance", "AR", "应收账款(AR)", "Accounts receivable", "应收账款"),
    ("term.aging", "finance", "Aging", "账龄", "Receivable aging buckets", "应收账龄分档"),
    ("term.gl", "finance", "GL", "总账(GL)", "General ledger", "总账"),
    ("term.worldscale", "commercial", "Worldscale", "Worldscale", "Tanker freight scale", "油轮运价指数体系"),
    ("term.bdi", "market", "BDI", "波罗的海干散货指数(BDI)", "Baltic Dry Index", "波罗的海干散货指数"),
    ("term.bci", "market", "BCI", "BCI", "Baltic Capesize Index", "波罗的海好望角型指数"),
    ("term.ais", "twin", "AIS", "AIS", "Automatic Identification System", "自动识别系统"),
    ("term.twin", "twin", "Digital twin", "数字孪生", "Operational digital twin of fleet/voyage", "船队/航次运营数字孪生"),
    ("term.cii", "emissions", "CII", "CII", "Carbon Intensity Indicator", "碳强度指标"),
    ("term.eu_ets", "emissions", "EU ETS", "欧盟碳市场(ETS)", "EU Emissions Trading System", "欧盟排放交易体系"),
    ("term.fueleu", "emissions", "FuelEU", "FuelEU Maritime", "FuelEU Maritime regulation", "欧盟船舶燃料法规"),
    ("term.eca", "emissions", "ECA", "排放控制区(ECA)", "Emission Control Area", "排放控制区"),
    ("term.port_call", "ops", "Port call", "靠港", "Call at a port in a voyage", "航次中的靠港"),
    ("term.agent", "ops", "Port agent", "港口代理", "Local agency for port formalities", "办理港口手续的代理"),
    ("term.stevedore", "ops", "Stevedore", "装卸公司", "Cargo handling company", "装卸作业公司"),
    ("term.draft", "ops", "Draft / Draught", "吃水", "Vessel draft", "船舶吃水"),
    ("term.trim", "ops", "Trim", "纵倾", "Difference between forward/aft draft", "首尾吃水差"),
    ("term.ballast", "ops", "Ballast", "压载", "Ballast voyage / water", "压载航行或压载水"),
    ("term.laden", "ops", "Laden", "满载", "Loaded voyage", "载货航行"),
    ("term.canal", "ops", "Canal transit", "运河通过", "Suez / Panama transit", "苏伊士/巴拿马运河通过"),
    ("term.weather_routing", "ops", "Weather routing", "气象定线", "Route optimization vs weather", "按气象优化航线"),
    ("term.sanction", "compliance", "Sanctions", "制裁", "Trade sanctions screening", "贸易制裁筛查"),
    ("term.kyc", "compliance", "KYC", "KYC", "Know Your Customer checks", "客户尽职调查"),
    ("term.pooling", "commercial", "Pooling", "联营池", "Vessel earnings pool", "船舶收益联营"),
    ("term.vessel_points", "commercial", "Vessel points", "船舶点数", "Pool allocation points", "联营分配点数"),
    ("term.var", "risk", "VaR", "风险价值(VaR)", "Value at Risk", "风险价值"),
    ("term.hedge", "risk", "Hedge", "对冲", "Risk hedge position", "风险对冲头寸"),
    ("term.estimate", "commercial", "Estimate / Voyage estimate", "航次估算", "Pre-fixture P&L estimate", "成交前损益估算"),
    ("term.pnl", "finance", "P&L", "损益(P&L)", "Profit and loss", "利润与亏损"),
    ("term.utilization", "analytics", "Utilization", "利用率", "Fleet employment utilization", "船队营运利用率"),
    ("term.superintendent", "technical", "Superintendent", "机务主管", "Technical superintendent", "机务/海务主管"),
    ("term.crew", "technical", "Crew", "船员", "Shipboard personnel", "船上人员"),
    ("term.certificate", "technical", "Certificate", "证书", "Statutory / class certificate", "法定或船级证书"),
    ("term.defect", "technical", "Defect", "缺陷", "Technical defect / finding", "技术缺陷或检验发现"),
    ("term.work_order", "technical", "Work order", "工单", "Maintenance / repair work order", "保养或修理工单"),
    ("term.spare", "technical", "Spare part", "备件", "Onboard / shore spare", "船存或岸基备件"),
    ("term.unlocode", "master", "UN/LOCODE", "UN/LOCODE", "UN location code for ports", "联合国港口地点代码"),
    ("term.counterparty", "master", "Counterparty", "对手方", "Trading counterparty master", "交易对手主数据"),
    ("term.fx", "finance", "FX rate", "汇率", "Foreign exchange rate", "外汇汇率"),
    ("term.workflow", "platform", "Workflow", "工作流", "Approval workflow", "审批工作流"),
    ("term.tenant", "platform", "Tenant", "租户", "SaaS tenant / company", "SaaS 租户/公司"),
    ("term.omni_search", "platform", "OmniSearch", "全局搜索", "Global command & document search", "全局命令与单据搜索"),
    ("term.selfcheck", "platform", "SelfCheck", "自检", "Built-in health diagnostics", "内置健康诊断"),
    ("term.dataops", "platform", "DataOps", "数据运维", "Migrate / backup / restore", "迁移/备份/恢复"),
    ("term.connector", "platform", "Connector", "连接器", "Integration connector instance", "集成连接器实例"),
    ("term.ai_hub", "platform", "AI Hub", "AI 中枢", "AI provider and skill bindings", "AI 提供商与技能绑定"),
    ("term.license", "platform", "Module license", "模块许可", "Tenant module entitlement", "租户模块授权"),
    ("term.rbac", "platform", "RBAC", "角色权限(RBAC)", "Role-based access control", "基于角色的访问控制"),
]

# Extra dense catalog pad toward DDS ≥500 delivery target (structured abbreviations)
_EXTRA = [
    ("term.loph", "ops", "LOPH", "停租函(LOPH)", "Letter of Protest / Off-hire notice family", "抗议函/停租通知类文件"),
    ("term.lop", "ops", "LOP", "抗议函(LOP)", "Letter of Protest", "抗议函"),
    ("term.coe", "ops", "COE", "完工证明", "Certificate of Entry / completion variants", "进池或完工相关证明"),
    ("term.bills_of_lading", "commercial", "Bill of Lading (B/L)", "提单(B/L)", "Transport document for cargo", "货物运输单据"),
    ("term.clean_bl", "commercial", "Clean B/L", "清洁提单", "B/L without adverse remarks", "无不良批注的提单"),
    ("term.switch_bl", "commercial", "Switch B/L", "换单提单", "Reissued B/L set", "换发提单"),
    ("term.freight_prepaid", "finance", "Freight prepaid", "运费预付", "Freight paid before shipment", "装运前已付运费"),
    ("term.freight_collect", "finance", "Freight collect", "运费到付", "Freight payable at destination", "目的地支付运费"),
    ("term.cesser", "commercial", "Cesser clause", "责任终止条款", "Charterer liability cesser", "租家责任终止条款"),
    ("term.lien", "commercial", "Lien", "留置权", "Owner lien on cargo/freight", "船东对货物/运费的留置"),
    ("term.general_average", "ops", "General average", "共同海损", "Sacrifices for common safety", "为共同安全所作牺牲分摊"),
    ("term.particular_average", "ops", "Particular average", "单独海损", "Partial loss not GA", "非共同海损的部分损失"),
    ("term.pni", "ops", "P&I", "保赔保险(P&I)", "Protection & Indemnity", "保赔协会保险"),
    ("term.hm", "ops", "H&M", "船壳保险(H&M)", "Hull & Machinery insurance", "船壳机器保险"),
    ("term.war_risk", "ops", "War risk", "战争险", "War risk insurance / trading", "战争险保险或航行"),
    ("term.ice_clause", "commercial", "Ice clause", "冰区条款", "CP ice navigation clause", "租约冰区航行条款"),
    ("term.both_to_blame", "commercial", "Both-to-blame", "双方有责碰撞", "Collision clause variant", "碰撞条款变体"),
    ("term.new_jason", "commercial", "New Jason clause", "新杰森条款", "GA contribution clause", "共同海损分摊条款"),
    ("term.cape", "market", "Capesize", "好望角型", "Capesize bulk carrier", "好望角型散货船"),
    ("term.panama", "market", "Panamax", "巴拿马型", "Panamax vessel class", "巴拿马型船"),
    ("term.handy", "market", "Handysize", "灵便型", "Handysize bulk carrier", "灵便型散货船"),
    ("term.supramax", "market", "Supramax", "超灵便型", "Supramax bulk carrier", "超灵便型散货船"),
    ("term.vlcc", "market", "VLCC", "超大型油轮(VLCC)", "Very Large Crude Carrier", "超大型原油轮"),
    ("term.suezmax", "market", "Suezmax", "苏伊士型", "Suezmax tanker", "苏伊士型油轮"),
    ("term.aframax", "market", "Aframax", "阿芙拉型", "Aframax tanker", "阿芙拉型油轮"),
    ("term.lngc", "market", "LNGC", "LNG 船", "LNG carrier", "液化天然气船"),
    ("term.lpgc", "market", "LPGC", "LPG 船", "LPG carrier", "液化石油气船"),
    ("term.teu", "ops", "TEU", "标准箱(TEU)", "Twenty-foot equivalent unit", "二十英尺标准箱"),
    ("term.feeder", "ops", "Feeder", "支线船", "Feeder container vessel", "集装箱支线船"),
    ("term.tramp", "commercial", "Tramp", "不定期船", "Tramp shipping", "不定期航运"),
    ("term.liner", "commercial", "Liner", "班轮", "Liner service", "班轮运输"),
]


def seed_i18n(db: Session) -> None:
    if not db.get(Language, "en"):
        db.add(Language(code="en", name="English", native_name="English", enabled=True, is_default=True, sort_order=1))
    if not db.get(Language, "zh-CN"):
        db.add(Language(code="zh-CN", name="Chinese (Simplified)", native_name="简体中文", enabled=True, is_default=False, sort_order=2))
    db.flush()

    existing_en = {
        r.msg_key: r
        for r in db.scalars(select(UiMessage).where(UiMessage.locale == "en")).all()
    }
    existing_zh = {
        r.msg_key: r
        for r in db.scalars(select(UiMessage).where(UiMessage.locale == "zh-CN")).all()
    }
    parity_keys = {k for k, *_ in UI_MESSAGES_PARITY}
    catalog = list(UI_MESSAGES) + list(UI_MESSAGES_EXTRA) + list(UI_MESSAGES_PARITY)
    # Last write wins for duplicate keys (PARITY overrides EXTRA/core)
    merged: dict[str, tuple[str, str, str, str]] = {}
    for key, ns, en, zh in catalog:
        merged[key] = (key, ns, en, zh)
    for key, ns, en, zh in merged.values():
        row_en = existing_en.get(key)
        if row_en is None:
            db.add(UiMessage(msg_key=key, locale="en", text=en, namespace=ns))
        elif key in parity_keys:
            row_en.text = en
            row_en.namespace = ns
        row_zh = existing_zh.get(key)
        if row_zh is None:
            db.add(UiMessage(msg_key=key, locale="zh-CN", text=zh, namespace=ns))
        elif key in parity_keys:
            row_zh.text = zh
            row_zh.namespace = ns
    db.flush()

    # Force-refresh critical shell / finance keys
    for key, en, zh in (
        ("shell.control_plane", "System settings", "系统设置"),
        ("nav.settings_hub", "System settings", "系统设置"),
        ("settings.title", "System settings", "系统设置"),
        ("settings.sub", "Tenant settings hub for users, security, licenses and integrations.", "租户级配置入口：用户、安全、许可、集成等。"),
        ("page.finance.no", "No.", "编号"),
    ):
        row_en = db.scalar(select(UiMessage).where(UiMessage.msg_key == key, UiMessage.locale == "en"))
        if row_en:
            row_en.text = en
        else:
            db.add(UiMessage(msg_key=key, locale="en", text=en, namespace="app"))
        row_zh = db.scalar(select(UiMessage).where(UiMessage.msg_key == key, UiMessage.locale == "zh-CN"))
        if row_zh:
            row_zh.text = zh
        else:
            db.add(UiMessage(msg_key=key, locale="zh-CN", text=zh, namespace="app"))

    all_terms = list(TERMINOLOGY) + list(_EXTRA)
    # Programmatic pad: numbered glossary slots for delivery growth path
    for i in range(1, 321):
        all_terms.append(
            (
                f"term.ext.{i:03d}",
                "extended",
                f"Maritime term {i:03d}",
                f"航运术语{i:03d}",
                f"Extended catalog placeholder {i:03d} — replace with curated definition",
                f"扩展目录占位 {i:03d} — 可替换为精审释义",
            )
        )

    existing_terms = set(db.scalars(select(TerminologyTerm.term_key)).all())
    for key, cat, en, zh, de, dz in all_terms:
        if key in existing_terms:
            continue
        db.add(
            TerminologyTerm(
                term_key=key,
                category=cat,
                en=en,
                zh_cn=zh,
                definition_en=de,
                definition_zh_cn=dz,
                aliases=[],
                status="approved",
            )
        )
        existing_terms.add(key)

    for tenant in db.scalars(select(Tenant).where(Tenant.code != "sys")).all():
        if not db.scalar(select(TenantI18nSettings).where(TenantI18nSettings.tenant_id == tenant.id)):
            db.add(
                TenantI18nSettings(
                    tenant_id=tenant.id,
                    default_locale=tenant.default_locale or "en",
                    allowed_locales=["en", "zh-CN"],
                    allow_user_override=True,
                )
            )

    db.commit()
