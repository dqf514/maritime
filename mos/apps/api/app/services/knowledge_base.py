"""MariOS customer knowledge base — articles, search, and guided Q&A.

Content is product-facing. Do not put internal roadmaps, competitor gap lists,
or engineering instructions here.
"""

from __future__ import annotations

import re
from typing import Any


CATEGORIES: list[dict[str, str]] = [
    {"id": "start", "en": "Getting started", "zh": "快速开始"},
    {"id": "commercial", "en": "Commercial desk", "zh": "商务台面"},
    {"id": "operations", "en": "Operations", "zh": "航次运营"},
    {"id": "finance", "en": "Finance & claims", "zh": "财务与索赔"},
    {"id": "office", "en": "Microsoft 365", "zh": "Microsoft 365"},
    {"id": "platform", "en": "Administration", "zh": "系统管理"},
    {"id": "integration", "en": "API & integrations", "zh": "API 与集成"},
]


# Each article: slug, category, tags, title/summary/body in en + zh (markdown-ish plain text)
ARTICLES: list[dict[str, Any]] = [
    {
        "slug": "welcome",
        "category": "start",
        "tags": ["overview", "product", "简介", "产品"],
        "title_en": "What is MariOS?",
        "title_zh": "MariOS 是什么？",
        "summary_en": "A maritime commercial operating system for owners, charterers, operators and ship managers.",
        "summary_zh": "面向船东、租家、Operator 与船舶管理公司的航运商业操作系统。",
        "body_en": """MariOS brings the commercial voyage chain into one workspace: estimate → fixture → voyage execution → laytime / claims → bunkers → settlement.

Teams work from role-based home screens and a global search (Ctrl+K). Master data, documents and Microsoft 365 resources stay linked to the same voyage or charter record.

Use this Knowledge Centre to learn workflows, configure Office connectivity, and find answers quickly.""",
        "body_zh": """MariOS 把航运商业主链路收进同一工作台：估算 → 租约 → 航次执行 → 装卸时间 / 索赔 → 燃油 → 结算。

各角色拥有专属首页，并通过全局搜索（Ctrl+K）快速到达任务。主数据、文档与 Microsoft 365 资源可挂接到同一航次或租约。

本知识中心帮助您了解业务流程、配置 Office 连接，并快速找到操作答案。""",
    },
    {
        "slug": "getting-started",
        "category": "start",
        "tags": ["login", "workspace", "demo", "登录", "工作区"],
        "title_en": "Sign in and first day",
        "title_zh": "登录与第一天上手",
        "summary_en": "How to sign in, pick a workspace, and find your desk.",
        "summary_zh": "如何登录、选择工作区并进入对应业务台面。",
        "body_en": """1. Open the web app and sign in with your company tenant code, email and password (or Microsoft / Google SSO if enabled).
2. After login you land on the Workbench. Use workspace tabs (e.g. Chartering Day, Ops Night) to switch focus.
3. Left navigation lists modules licensed for your role. Control plane (Settings) is for tenant administrators.
4. Press Ctrl+K anytime to search pages, vessels, and common actions.
5. Open Help → Knowledge Centre from the sidebar or top links when you need guidance.""",
        "body_zh": """1. 打开网站，使用公司租户代码、邮箱与密码登录（若已开通，也可使用 Microsoft / Google 单点登录）。
2. 登录后进入工作台。可用顶部工作区标签切换关注重点（如租船日班、操作夜班）。
3. 左侧导航按角色与许可证显示模块；「控制平面」供租户管理员使用。
4. 随时按 Ctrl+K 搜索页面、船舶与常用操作。
5. 需要指引时，从侧栏或顶部进入「帮助 → 知识中心」。""",
    },
    {
        "slug": "estimates",
        "category": "commercial",
        "tags": ["tce", "worldscale", "estimate", "估算", "运价"],
        "title_en": "Voyage estimates",
        "title_zh": "航次估算",
        "summary_en": "Build TCE cases, run Worldscale freight, sensitivity and convert to charter.",
        "summary_zh": "编制 TCE 方案、Worldscale 运费、敏感度分析并转租约。",
        "body_en": """Open Estimates from Work.

- Create an estimate with vessel, counterparty and voyage inputs (cargo, days, bunker, port costs, commission).
- Worldscale: enter flat and WS%; the engine derives gross freight and TCE.
- Save, Calculate, Clone, Compare scenarios, and run Sensitivity on key drivers.
- When ready, convert the case to a charter party draft for fixture workflow.

Tip: keep naming consistent (vessel + load/disch + laycan) so search and analytics stay clear.""",
        "body_zh": """在「工作」中打开「航次估算」。

- 创建估算时选择船舶、对手方并填写航次参数（货量、航程天数、燃油、港口费、佣金等）。
- Worldscale：填写 Flat 与 WS%；系统计算毛运费与 TCE。
- 支持保存、计算、克隆、方案对比，以及对关键驱动因子做敏感度分析。
- 成熟方案可一键转为租约草稿，进入成交与审批流程。

建议命名保持一致（船名 + 装卸港 + Laycan），便于检索与报表。""",
    },
    {
        "slug": "charters",
        "category": "commercial",
        "tags": ["cp", "fixture", "coa", "租约", "成交"],
        "title_en": "Charters and fixtures",
        "title_zh": "租约与成交",
        "summary_en": "Manage fixtures, approvals and activation into operations.",
        "summary_zh": "管理成交、审批，并激活进入运营。",
        "body_en": """The Charters desk tracks fixtures from draft through approval to activation.

- Capture commercial terms and link the originating estimate when applicable.
- Submit for workflow approval when your tenant policy requires it.
- On activation, cargo and schedule context become available to Operations for voyage creation.
- COA liftings can be recorded against contract of affreightment structures where enabled.

Always confirm counterparty KYC / compliance status before activation if your policy requires it.""",
        "body_zh": """「租约」台面覆盖从草稿、审批到激活的成交过程。

- 录入商务条款；可关联来源估算。
- 若租户启用了审批流，提交后进入工作流收件箱。
- 激活后，货载与船期上下文可供运营创建航次。
- 在启用场景下，可登记 COA 提货（lifting）。

若公司政策要求，激活前请确认对手方合规 / KYC 状态。""",
    },
    {
        "slug": "voyages",
        "category": "operations",
        "tags": ["voyage", "sof", "noon", "port call", "航次", "午报"],
        "title_en": "Voyages, port calls and SOF",
        "title_zh": "航次、靠港与 SOF",
        "summary_en": "Run the operational voyage: port calls, noon reports, SOF and schedule.",
        "summary_zh": "执行航次运营：靠港、午报、SOF 与船期。",
        "body_en": """Open Voyages under Operations.

- Create or open a voyage linked to an activated charter.
- Maintain port calls with ETA/ETB/ETD and local time zones.
- Record noon reports and SOF events that feed laytime calculations.
- Watch schedule blocks for conflicts; hard conflicts should be resolved before sailing.
- Fleet Twin shows positions and alerts for situational awareness.

Use consistent local times for port events — MariOS stores and displays local time, not UTC-only.""",
        "body_zh": """在「运营」中打开「航次」。

- 基于已激活租约创建或打开航次。
- 维护靠港的 ETA/ETB/ETD，并正确填写当地时区。
- 录入午报与 SOF 事件，供后续装卸时间计算使用。
- 关注船期块冲突；硬冲突应在开航前处理。
- 「船队孪生」提供船位与告警态势。

港口事件请使用当地时间；系统按本地时间存储与展示，而非仅用 UTC。""",
    },
    {
        "slug": "finance-laytime",
        "category": "finance",
        "tags": ["laytime", "demurrage", "invoice", "pnl", "滞期", "发票"],
        "title_en": "Laytime, claims and voyage P&L",
        "title_zh": "装卸时间、索赔与航次损益",
        "summary_en": "Calculate laytime, raise claims, invoice and review estimated vs actual P&L.",
        "summary_zh": "计算装卸时间、发起索赔、开票并查看估实损益。",
        "body_en": """Finance desk covers invoices, receipts, laytime and claims.

- Laytime: set CP terms, apply SOF facts, calculate, finalize, then open a claim if needed.
- Invoices: freight, demurrage and related types with payment tracking.
- Analytics → Voyage P&L compares estimated vs actual revenue, cost and variance.
- GL post helpers prepare entries for your accounting connector when configured.

Demurrage users typically work from the demurrage workspace and claim inbox.""",
        "body_zh": """「财务」台面覆盖发票、收付款、装卸时间与索赔。

- 装卸时间：录入租约条款与 SOF 事实 → 计算 → 定稿 → 必要时生成索赔。
- 发票：运费、滞期费等类型，并跟踪收款。
- 「分析 → 航次损益」对比估算与实际的收入、成本与差异。
- 配置会计连接后，可使用过账辅助生成分录。

滞期岗位通常使用滞期工作区与索赔相关收件箱。""",
    },
    {
        "slug": "microsoft-365",
        "category": "office",
        "tags": ["teams", "sharepoint", "onedrive", "outlook", "office", "邮件"],
        "title_en": "Microsoft 365 ecosystem",
        "title_zh": "Microsoft 365 生态",
        "summary_en": "Connect Mail, Teams, SharePoint and OneDrive; install Outlook / Teams / Excel add-ins.",
        "summary_zh": "连接邮件、Teams、SharePoint 与 OneDrive；安装 Outlook / Teams / Excel 插件。",
        "body_en": """MariOS integrates with Microsoft 365 so commercial records and collaboration stay in one ecosystem.

**Connect (tenant admin)**
1. Open Control plane → Office ecosystem.
2. Choose Connect Microsoft 365. Production uses Entra ID consent; development environments may use a safe demo connection.
3. Run Health check, then Sync for Mail, OneDrive / SharePoint or Teams.

**What you can do**
- Browse sample inbox context and send mail via Graph when enabled.
- List drives and provision voyage / charter folders linked back into MariOS.
- Post channel messages for approvals and ETA alerts.
- Register outbound webhooks for Power Automate or partner systems.
- Sideload add-in manifests for Outlook, Teams and Excel from the add-ins table.

**API keys**
Create keys under Control plane → API keys. Office add-ins and partners may call the API with header `X-API-Key`.

Linked files and folders appear as Office resource links on the related business entity.""",
        "body_zh": """MariOS 与 Microsoft 365 深度整合，使商务单据与日常协作处于同一生态。

**连接（租户管理员）**
1. 打开「控制平面 → Office 生态」。
2. 点击「连接 Microsoft 365」。生产环境走 Entra ID 授权；开发/演示环境可使用安全的演示连接。
3. 执行健康检查，再按需同步邮件、OneDrive / SharePoint 或 Teams。

**可做事项**
- 查看收件上下文，并在启用 Graph 时发送邮件。
- 列出驱动器，并为航次 / 租约创建文件夹并回写链接。
- 向 Teams 频道发送审批与 ETA 等通知。
- 注册出站 Webhook，对接 Power Automate 或合作伙伴系统。
- 从插件列表侧载 Outlook、Teams、Excel 清单。

**API 密钥**
在「控制平面 → API 密钥」创建。Office 插件与伙伴可通过请求头 `X-API-Key` 调用接口。

关联的文件与文件夹会作为 Office 资源链接挂在对应业务单据上。""",
    },
    {
        "slug": "ship-management",
        "category": "operations",
        "tags": ["pms", "certificate", "crew", "technical", "机务"],
        "title_en": "Ship management",
        "title_zh": "船舶管理",
        "summary_en": "Technical fleet desk: certificates, PMS work orders, defects and crew.",
        "summary_zh": "技术船队台面：证书、保养工单、缺陷与船员。",
        "body_en": """Ship management serves owners and technical managers.

- Select a vessel to review certificates, work orders, defects and crew snapshots.
- Connect external PMS systems from Integration Hub when your fleet already runs SpecTec, ABS NS, ShipNet or a webhook bridge.
- Technical live wall and dashboards highlight overdue certificates and open defects.

Commercial and technical views share the same vessel master data.""",
        "body_zh": """船舶管理面向船东与机务管理团队。

- 选择船舶查看证书、工单、缺陷与船员快照。
- 若船队已使用 SpecTec、ABS NS、ShipNet 或通用 Webhook，可在集成中枢配置对接。
- 技术大屏与仪表盘突出过期证书与未关闭缺陷。

商务与机务视图共用同一船舶主数据。""",
    },
    {
        "slug": "admin-security",
        "category": "platform",
        "tags": ["sso", "users", "roles", "i18n", "安全", "用户"],
        "title_en": "Users, security and languages",
        "title_zh": "用户、安全与语言",
        "summary_en": "Invite users, configure SSO, and manage locale terminology.",
        "summary_zh": "邀请用户、配置单点登录，并管理语言与术语。",
        "body_en": """Tenant administrators use:

- Users & roles — invite colleagues and assign chartering, ops, finance, etc.
- Login & security — password policy, email verification, Microsoft / Google SSO, allowed domains.
- Languages & terms — default locale and maritime terminology overrides.
- Feature permissions & workflows — fine-grained capabilities and approval definitions.
- Company & brand — logo and legal name for portals.

Platform operators (sys tenant) manage multi-tenant estate, plans and product branding.""",
        "body_zh": """租户管理员常用：

- 用户与角色 — 邀请同事并分配租船、运营、财务等角色。
- 登录与安全 — 密码策略、邮箱验证、Microsoft / Google SSO、允许域名。
- 语言与术语 — 默认语言与航运术语覆盖。
- 功能权限与工作流 — 细粒度能力与审批定义。
- 公司与品牌 — 门户 Logo 与法定名称。

平台运营方（sys 租户）管理多租户资产、套餐与产品品牌。""",
    },
    {
        "slug": "platform-data-deploy",
        "category": "platform",
        "tags": ["database", "postgres", "sqlite", "deploy", "monitor", "数据库", "部署", "监控", "初始化"],
        "title_en": "Platform data plane and deployment",
        "title_zh": "平台数据面与部署",
        "summary_en": "Default database, tenant datastore bindings, init wizard, deploy profiles and monitoring.",
        "summary_zh": "默认数据库、租户库绑定、初始化向导、部署档案与监控预警。",
        "body_en": """**Default database**

- Local development defaults to SQLite (`DATABASE_URL`, typically `sqlite+pysqlite:///./voyageos_wave0.db`).
- Docker Compose and production recommend PostgreSQL (`postgresql+psycopg://…`).

**Multi-tenant model**

MariOS uses a shared primary database with tenant isolation by `tenant_id`. Platform operators may register per-tenant datastore bindings (local file, database server, or managed cloud RDS). Connection strings are stored encrypted; the console shows masked previews and connectivity tests. Dedicated per-tenant engines are reserved in the architecture; business sessions currently continue on the primary database.

**Where to configure**

Sign in as a platform operator → **Platform ops → Data & deployment** (`/platform/ops`):

1. Runtime datastore — see dialect / masked URL / probe primary.
2. Tenant datastores — bind SQLite / Postgres / MySQL / cloud RDS per tenant.
3. Initialization — run schema ensure, catalog seed, optional demo data, readiness check.
4. Deploy profiles — Docker Compose, single-host, and common cloud VM templates (Aliyun / AWS / Azure).
5. Monitor & alerts — resource snapshot, latency probe, alert rules.

Also see product docs under `docs/platform-data-deploy.md`.""",
        "body_zh": """**默认数据库**

- 本地开发默认使用 SQLite（环境变量 `DATABASE_URL`，常见为 `sqlite+pysqlite:///./voyageos_wave0.db`）。
- Docker Compose 与生产环境推荐 PostgreSQL（`postgresql+psycopg://…`）。

**多租户模型**

MariOS 以共享主库 + `tenant_id` 隔离为主。平台运营方可按租户登记独立数据源绑定（本地文件、数据库服务器或主流云托管库）。连接串加密存储，控制台仅展示脱敏预览并支持连通性测试。架构上已预留按租户独立引擎路由；当前业务会话仍走平台主库，保证稳定。

**在哪里配置**

使用平台运营账号登录 → **平台运维 → 数据面与部署**（`/platform/ops`）：

1. 运行时数据源 — 查看方言 / 脱敏连接 / 探测主库。
2. 租户库绑定 — 为租户配置 SQLite / Postgres / MySQL / 云 RDS。
3. 系统初始化 — 建表校验、目录种子、可选演示数据、就绪检查。
4. 部署档案 — Docker Compose、单机进程，以及阿里云 / AWS / Azure 等常见云主机模板。
5. 监控与预警 — 资源快照、延迟探测、预警规则。

产品说明亦见 `docs/platform-data-deploy.md`。""",
    },
    {
        "slug": "api-integrations",
        "category": "integration",
        "tags": ["api", "webhook", "connector", "openapi", "集成"],
        "title_en": "API, connectors and webhooks",
        "title_zh": "API、连接器与 Webhook",
        "summary_en": "Open API, Integration Hub connectors, and event webhooks.",
        "summary_zh": "开放 API、集成中枢连接器与事件 Webhook。",
        "body_en": """MariOS exposes a versioned REST API (`/api/v1`, OpenAPI at `/docs` on the API host).

- API keys: Control plane → API keys; send `Authorization: Bearer` (user JWT) or `X-API-Key`.
- Integration Hub: FX, sanctions lists, AIS, bunker index, PMS, email and Microsoft 365 connectors with health tests.
- Office webhooks: subscribe to events such as charter.activated, voyage.started, invoice.issued, office.sync.done.
- DataOps: AI-assisted migration from mailbox / PST / Excel and one-click tenant backup.

Treat secrets as confidential; rotate keys if a device or partner is retired.""",
        "body_zh": """MariOS 提供版本化 REST API（`/api/v1`，API 主机上的 `/docs` 为 OpenAPI）。

- API 密钥：控制平面 → API 密钥；使用 `Authorization: Bearer`（用户 JWT）或 `X-API-Key`。
- 集成中枢：汇率、制裁名单、AIS、燃油指数、PMS、邮件与 Microsoft 365 等连接器，支持健康检测。
- Office Webhook：可订阅 charter.activated、voyage.started、invoice.issued、office.sync.done 等事件。
- DataOps：从邮箱 / PST / Excel 等 AI 辅助迁入，以及一键租户备份。

请妥善保管密钥；设备或合作伙伴停用后应及时轮换。""",
    },
    {
        "slug": "faq",
        "category": "start",
        "tags": ["faq", "常见问题", "help"],
        "title_en": "Frequently asked questions",
        "title_zh": "常见问题",
        "summary_en": "Short answers to common operational questions.",
        "summary_zh": "常见操作问题的简要说明。",
        "body_en": """**Where do I change language?** Use the language control in the top bar, or Languages & terms in admin.

**Why can I not see a module?** Your role or module license may not include it. Ask a tenant admin.

**How do I connect Outlook / Teams?** Control plane → Office ecosystem → Connect Microsoft 365, then mark add-ins installed after sideloading manifests.

**Does search find help articles?** Global search finds app pages; use Knowledge Centre search or Ask for documentation answers.

**Is time stored in UTC?** Business times are handled in local time for port and laytime facts.""",
        "body_zh": """**如何切换语言？** 使用顶栏语言切换，或管理员中的「语言与术语」。

**为什么看不到某个模块？** 可能是角色或模块许可证未包含，请联系租户管理员。

**如何连接 Outlook / Teams？** 控制平面 → Office 生态 → 连接 Microsoft 365，侧载清单后将插件标记为已安装。

**全局搜索能找到帮助文章吗？** 全局搜索以应用页面为主；文档请用知识中心的搜索或问答。

**时间是否只用 UTC？** 港口与装卸时间等业务时间按本地时间处理与展示。""",
    },
]


FAQS: list[dict[str, Any]] = [
    {
        "id": "q_login",
        "patterns": [r"登录", r"login", r"sign\s*in", r"密码", r"password", r"sso"],
        "answer_en": "Sign in with tenant code + email + password, or Microsoft / Google if your admin enabled SSO. See article “Sign in and first day”.",
        "answer_zh": "使用租户代码 + 邮箱 + 密码登录；若管理员已开通，也可使用 Microsoft / Google 单点登录。详见「登录与第一天上手」。",
        "article_slugs": ["getting-started", "admin-security"],
    },
    {
        "id": "q_estimate",
        "patterns": [r"估算", r"estimate", r"tce", r"worldscale", r"运价"],
        "answer_en": "Open Estimates to create a case, enter voyage economics (including Worldscale), Calculate, then convert to a charter when ready.",
        "answer_zh": "打开「航次估算」创建方案，填写航次经济参数（含 Worldscale），计算后再转为租约。",
        "article_slugs": ["estimates", "charters"],
    },
    {
        "id": "q_office",
        "patterns": [r"office", r"teams", r"sharepoint", r"onedrive", r"outlook", r"365", r"邮件", r"graph"],
        "answer_en": "Tenant admins connect Microsoft 365 under Control plane → Office ecosystem. You can sync mail/files/Teams, post channel alerts, and sideload add-ins.",
        "answer_zh": "租户管理员在「控制平面 → Office 生态」连接 Microsoft 365，可同步邮件/文件/Teams、发送频道通知并侧载插件。",
        "article_slugs": ["microsoft-365", "api-integrations"],
    },
    {
        "id": "q_laytime",
        "patterns": [r"laytime", r"demurrage", r"滞期", r"装卸时间", r"sof", r"索赔", r"claim"],
        "answer_en": "Use Finance desk: apply SOF facts to laytime terms, calculate and finalize, then raise a claim and invoice if needed. Voyage P&L shows estimate vs actual.",
        "answer_zh": "在财务台面：将 SOF 事实代入装卸时间条款，计算并定稿，必要时发起索赔与开票。航次损益可看估与实对比。",
        "article_slugs": ["finance-laytime", "voyages"],
    },
    {
        "id": "q_api",
        "patterns": [r"api", r"webhook", r"集成", r"connector", r"密钥", r"api.?key"],
        "answer_en": "Use REST `/api/v1` with JWT or X-API-Key. Configure connectors in Integration Hub and Office webhooks for outbound events. OpenAPI is at `/docs` on the API host.",
        "answer_zh": "通过 REST `/api/v1`，使用 JWT 或 X-API-Key。在集成中枢配置连接器，在 Office 生态配置出站 Webhook。OpenAPI 见 API 主机 `/docs`。",
        "article_slugs": ["api-integrations", "microsoft-365"],
    },
    {
        "id": "q_database",
        "patterns": [r"database", r"postgres", r"sqlite", r"数据库", r"部署", r"deploy", r"监控", r"monitor", r"rds"],
        "answer_en": "Default local DB is SQLite; Compose/production use PostgreSQL. Platform operators configure datastore bindings, init wizard, deploy profiles and alerts under Platform ops → Data & deployment (`/platform/ops`). Business traffic still uses the shared primary DB; per-tenant engines are reserved.",
        "answer_zh": "本地默认 SQLite，Compose/生产推荐 PostgreSQL。平台运营可在「平台运维 → 数据面与部署」（`/platform/ops`）配置租户库绑定、初始化向导、部署档案与监控预警。业务会话当前仍走共享主库，独立引擎已预留。",
        "article_slugs": ["platform-data-deploy", "admin-security"],
    },
    {
        "id": "q_voyage",
        "patterns": [r"航次", r"voyage", r"靠港", r"port\s*call", r"午报", r"noon"],
        "answer_en": "Operations → Voyages: maintain port calls in local time, noon reports and SOF. Fleet Twin shows positions and alerts.",
        "answer_zh": "运营 → 航次：用当地时间维护靠港、午报与 SOF。船队孪生可看船位与告警。",
        "article_slugs": ["voyages", "ship-management"],
    },
]


def _locale(lang: str | None) -> str:
    if not lang:
        return "en"
    l = lang.lower()
    if l.startswith("zh"):
        return "zh"
    return "en"


def _pick(article: dict[str, Any], field: str, lang: str) -> str:
    key = f"{field}_{'zh' if lang == 'zh' else 'en'}"
    return str(article.get(key) or article.get(f"{field}_en") or "")


def list_categories(lang: str | None = None) -> list[dict[str, str]]:
    loc = _locale(lang)
    return [{"id": c["id"], "label": c["zh"] if loc == "zh" else c["en"]} for c in CATEGORIES]


def serialize_article(article: dict[str, Any], lang: str | None = None, *, full: bool = False) -> dict[str, Any]:
    loc = _locale(lang)
    out = {
        "slug": article["slug"],
        "category": article["category"],
        "tags": article.get("tags") or [],
        "title": _pick(article, "title", loc),
        "summary": _pick(article, "summary", loc),
    }
    if full:
        out["body"] = _pick(article, "body", loc)
    return out


def get_article(slug: str, lang: str | None = None) -> dict[str, Any] | None:
    for a in ARTICLES:
        if a["slug"] == slug:
            return serialize_article(a, lang, full=True)
    return None


def catalog(lang: str | None = None) -> dict[str, Any]:
    loc = _locale(lang)
    return {
        "locale": loc,
        "categories": list_categories(lang),
        "articles": [serialize_article(a, lang, full=False) for a in ARTICLES],
    }


def search(query: str, lang: str | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    loc = _locale(lang)
    if not q:
        return [serialize_article(a, lang) for a in ARTICLES[:limit]]
    tokens = [t for t in re.split(r"\s+", q) if t]
    scored: list[tuple[int, dict[str, Any]]] = []
    for a in ARTICLES:
        blob = " ".join(
            [
                a["slug"],
                a["category"],
                " ".join(a.get("tags") or []),
                _pick(a, "title", "en"),
                _pick(a, "title", "zh"),
                _pick(a, "summary", "en"),
                _pick(a, "summary", "zh"),
                _pick(a, "body", "en"),
                _pick(a, "body", "zh"),
            ]
        ).lower()
        score = 0
        for t in tokens:
            if t in blob:
                score += 3 if t in (a["slug"] + " " + " ".join(a.get("tags") or [])).lower() else 1
                if t in _pick(a, "title", loc).lower():
                    score += 4
        if score:
            scored.append((score, serialize_article(a, lang)))
    scored.sort(key=lambda x: (-x[0], x[1]["title"]))
    return [s[1] for s in scored[:limit]]


def ask(question: str, lang: str | None = None) -> dict[str, Any]:
    loc = _locale(lang)
    q = (question or "").strip()
    if not q:
        return {
            "answer": "请输入问题。" if loc == "zh" else "Please enter a question.",
            "confidence": 0,
            "related": [],
            "source": "empty",
        }
    best = None
    best_score = 0
    for faq in FAQS:
        score = 0
        for pat in faq["patterns"]:
            if re.search(pat, q, flags=re.IGNORECASE):
                score += 2
        if score > best_score:
            best_score = score
            best = faq
    related = search(q, lang, limit=5)
    if best and best_score > 0:
        answer = best["answer_zh"] if loc == "zh" else best["answer_en"]
        slugs = best.get("article_slugs") or []
        related_forced = []
        for slug in slugs:
            art = get_article(slug, lang)
            if art:
                related_forced.append({k: art[k] for k in ("slug", "category", "tags", "title", "summary") if k in art})
        # merge unique
        seen = {r["slug"] for r in related_forced}
        for r in related:
            if r["slug"] not in seen:
                related_forced.append(r)
                seen.add(r["slug"])
        return {
            "answer": answer,
            "confidence": min(0.95, 0.55 + 0.1 * best_score),
            "related": related_forced[:6],
            "source": "faq",
            "faq_id": best["id"],
        }
    if related:
        top = related[0]
        full = get_article(top["slug"], lang)
        snippet = (full or {}).get("body", "")[:280]
        if loc == "zh":
            answer = f"未匹配到标准问答，已为您找到相关说明《{top['title']}》。摘要：{top['summary']}\n\n{snippet}…"
        else:
            answer = f"No exact FAQ match. Closest article: “{top['title']}”. {top['summary']}\n\n{snippet}…"
        return {"answer": answer, "confidence": 0.45, "related": related, "source": "search"}
    return {
        "answer": "暂未找到相关说明，请换个关键词，或浏览知识中心目录。"
        if loc == "zh"
        else "No matching guidance found. Try different keywords or browse the Knowledge Centre catalogue.",
        "confidence": 0.1,
        "related": [],
        "source": "none",
    }
