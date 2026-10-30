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
    {"id": "automation", "en": "AI & automation", "zh": "AI 与自动化"},
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
        "body_en": """1. Open the web app and sign in with your company tenant code, email and password — or, when your tenant has Microsoft / Google SSO enabled, the identity provider button on the sign-in screen comes first.
2. After login you land on the Workbench. Use workspace tabs (e.g. Chartering Day, Ops Night) to switch focus.
3. Left navigation lists modules licensed for your role. Control plane (Settings) is for tenant administrators.
4. Press Ctrl+K anytime to search pages, vessels, and common actions; press Ctrl+J to open the AI assistant on the current page.
5. Open Help → Knowledge Centre from the sidebar or top links when you need guidance.""",
        "body_zh": """1. 打开网站，使用公司租户代码、邮箱与密码登录 —— 若租户已开通 Microsoft / Google SSO，登录页会优先展示身份提供方按钮。
2. 登录后进入工作台。可用顶部工作区标签切换关注重点（如租船日班、操作夜班）。
3. 左侧导航按角色与许可证显示模块；「控制平面」供租户管理员使用。
4. 随时按 Ctrl+K 搜索页面、船舶与常用操作；按 Ctrl+J 打开当前页面的 AI 助手。
5. 需要指引时，从侧栏或顶部进入「帮助 → 知识中心」。""",
    },
    {
        "slug": "video-demos",
        "category": "start",
        "tags": ["video", "demo", "walkthrough", "screencast", "narration", "视频", "演示", "讲解", "录屏"],
        "title_en": "Video walkthrough",
        "title_zh": "视频演示讲解",
        "summary_en": "Narrated product videos — full business flow (Chinese & English) and administrator operations — with click-to-seek transcripts.",
        "summary_zh": "带讲解的产品视频——全业务流程（中文与英文）与管理员操作，附可点击跳转的完整讲解稿。",
        "body_en": """Watch MariOS end to end without leaving the app. This page embeds three narrated videos:

- Business demo (Chinese) — estimate → fixture → voyage execution → laytime/claims → finance → technical → market & AI, about 13 minutes, 10 chapters.
- Business demo (English) — the same flow with English narration, about 12 minutes.
- Admin operations (Chinese) — tenant administrator (users, permissions, languages, settings, module licences, self-check) and platform operations (tenants, subscriptions, identity, health), about 5 minutes, 3 chapters.

Each video ships with a full transcript: click any chapter or transcript line and the player jumps to that exact moment. Subtitle files (.srt) can be downloaded next to the player for offline use or re-use in training.

Tip: first-time users should watch the opening chapter (sign-in and workbench) before exploring their own modules.""",
        "body_zh": """无需离开系统即可完整了解 MariOS。本页内嵌三段带讲解的视频：

- 业务演示（中文）——估算 → 成交 → 航次执行 → 滞期与索赔 → 财务 → 技术 → 行情与 AI，约 13 分钟，10 个章节。
- 业务演示（英文）——同一流程的英文讲解版，约 12 分钟。
- 管理演示（中文）——租户管理员（用户、权限、语言、设置、模块许可、系统自检）与平台运营（租户、订阅、身份、健康）约 5 分钟，3 个章节。

每段视频均附完整讲解稿：点击任意章节或讲解段落，播放器即跳转到对应画面；播放器旁可下载字幕文件（.srt），便于离线观看或用于内部培训。

建议：初次使用者先观看开篇章节（登录与工作台），再进入自己负责的模块。""",
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
- An approved charter can be created directly from an email draft in Email Review, and an estimate can be converted into a charter draft with one click.

Always confirm counterparty KYC / compliance status before activation if your policy requires it.""",
        "body_zh": """「租约」台面覆盖从草稿、审批到激活的成交过程。

- 录入商务条款；可关联来源估算。
- 若租户启用了审批流，提交后进入审批收件箱。
- 激活后，货载与船期上下文可供运营创建航次。
- 在启用场景下，可登记 COA 提货（lifting）。
- 邮件复核中可由一封邮件直接生成估算与租约草稿；估算也可一键转成租约草稿。

若公司政策要求，激活前请确认对手方合规 / KYC 状态。""",
    },
    {
        "slug": "voyages",
        "category": "operations",
        "tags": ["voyage", "sof", "noon", "port call", "closeout", "航次", "午报", "收尾"],
        "title_en": "Voyages, port calls, SOF and closeout",
        "title_zh": "航次、靠港、SOF 与收尾",
        "summary_en": "Run the operational voyage: port calls, noon reports, SOF, schedule and the closeout checklist.",
        "summary_zh": "执行航次运营：靠港、午报、SOF、船期与收尾清单。",
        "body_en": """Open Voyages under Operations.

- Create or open a voyage linked to an activated charter.
- Maintain port calls with ETA/ETB/ETD and local time zones.
- Record noon reports and SOF events that feed laytime calculations.
- Watch schedule blocks for conflicts; hard conflicts should be resolved before sailing.
- Fleet Twin shows positions and alerts for situational awareness.
- The Closeout tab lists the pre-close items (port calls, SOF facts, laytime finalisation, claims, invoices, bunker delivery, emissions, accrual reconciliation). Completing a voyage turns every missing item into a task for the owning role, and the panel shows actual versus estimate TCE side by side.

Use consistent local times for port events — MariOS stores and displays local time, not UTC-only.""",
        "body_zh": """在「运营」中打开「航次」。

- 基于已激活租约创建或打开航次。
- 维护靠港的 ETA/ETB/ETD，并正确填写当地时区。
- 录入午报与 SOF 事件，供后续装卸时间计算使用。
- 关注船期块冲突；硬冲突应在开航前处理。
- 「船队孪生」提供船位与告警态势。
- 「收尾」页签列出关航前的检查项（挂港、SOF 事实、装卸时间定稿、索赔、账单、加油交付、排放、计提对账）。航次完成时，每一项未完成内容都会变成对应角色的任务，同页并排显示实际 TCE 与估算 TCE。

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
- Invoices and laytime calculations carry an Export PDF button; the layout comes from System settings → Document templates.

Demurrage users typically work from the demurrage workspace and claim inbox.""",
        "body_zh": """「财务」台面覆盖发票、收付款、装卸时间与索赔。

- 装卸时间：录入租约条款与 SOF 事实 → 计算 → 定稿 → 必要时生成索赔。
- 发票：运费、滞期费等类型，并跟踪收款。
- 「分析 → 航次损益」对比估算与实际的收入、成本与差异。
- 配置会计连接后，可使用过账辅助生成分录。
- 账单与装卸时间计算详情带「导出 PDF」按钮，版式取自「系统设置 → 单据模板」。

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
- Sync mail into the Email Review desk, where each message is classified and turned into a reviewed business draft.
- List drives and provision voyage / charter folders linked back into MariOS.
- Post channel messages for approvals and ETA alerts.
- Register outbound webhooks for Power Automate or partner systems.
- Sideload add-in manifests for Outlook, Teams and Excel from the add-ins table.

**Email Review**
Office mail feeds Email Review (`/email/review`): inbound mail is classified, given a suggested action, and can create a business draft — with the mail reviewable side by side. See "Email review and AI-assisted paperwork".

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
- 把邮件同步进邮件复核台面：每封邮件被分类、给出处理建议，并可生成待复核的业务草稿。
- 列出驱动器，并为航次 / 租约创建文件夹并回写链接。
- 向 Teams 频道发送审批与 ETA 等通知。
- 注册出站 Webhook，对接 Power Automate 或合作伙伴系统。
- 从插件列表侧载 Outlook、Teams、Excel 清单。

**邮件复核**
Office 邮件汇入邮件复核台面（`/email/review`）：来件被分类、给出建议动作，并可生成业务草稿，邮件原文与草稿并排复核。详见「邮件复核与 AI 辅助落单」。

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
- 技术数据看板与仪表盘突出过期证书与未关闭缺陷。

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
- AI Hub — providers, default models, skill bindings and usage for the tenant.
- Document templates — fourteen editable single-document layouts.

On the sign-in screen, an enabled identity provider is offered first: if Microsoft or Google SSO is configured for the tenant, that button is shown ahead of the password form, so colleagues reach their desk through one click. Password sign-in remains available as a fallback.

Platform operators (sys tenant) manage multi-tenant estate, plans and product branding.""",
        "body_zh": """租户管理员常用：

- 用户与角色 — 邀请同事并分配租船、运营、财务等角色。
- 登录与安全 — 密码策略、邮箱验证、Microsoft / Google SSO、允许域名。
- 语言与术语 — 默认语言与航运术语覆盖。
- 功能权限与工作流 — 细粒度能力与审批定义。
- 公司与品牌 — 门户 Logo 与法定名称。
- AI Hub — 租户级的提供商、默认模型、技能绑定与用量。
- 单据模板 — 十四类可编辑的单据版式。

在登录页，已启用的身份提供方优先展示：若租户配置了 Microsoft 或 Google SSO，该按钮会排在密码表单之前，同事一键即可进入工作台；密码登录作为兜底仍然保留。

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
- Business events: the same events drive in-app automation — tasks, desk notifications, the voyage closeout checklist and automatic GL posting for a closed disbursement. See "Event automation, closeout checklists and approvals".
- Task rules: `/api/v1/config/task-rules` creates a task when a condition on an entity is met.
- DataOps: AI-assisted migration from mailbox / PST / Excel and one-click tenant backup.

Treat secrets as confidential; rotate keys if a device or partner is retired.""",
        "body_zh": """MariOS 提供版本化 REST API（`/api/v1`，API 主机上的 `/docs` 为 OpenAPI）。

- API 密钥：控制平面 → API 密钥；使用 `Authorization: Bearer`（用户 JWT）或 `X-API-Key`。
- 集成中枢：汇率、制裁名单、AIS、燃油指数、PMS、邮件与 Microsoft 365 等连接器，支持健康检测。
- Office Webhook：可订阅 charter.activated、voyage.started、invoice.issued、office.sync.done 等事件。
- 业务事件：同一批事件驱动应用内自动化 —— 任务、台面通知、航次收尾清单，以及使费关闭时自动记账总账凭证。详见「事件自动化、收尾清单与审批」。
- 任务规则：`/api/v1/config/task-rules` 可在满足实体条件时创建任务。
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

**Is time stored in UTC?** Business times are handled in local time for port and laytime facts.

**Does the AI write into my records?** No. Every AI feature proposes values, drafts or suggestions; a person confirms before anything is stored.

**Something was created without me asking.** Check the Routine task hub and the voyage Closeout tab — the system creates follow-up tasks when business events fire.

**Can I export a document as PDF?** Invoice and laytime calculation details have an Export PDF button; the other document types are reachable from their render URL under System settings → Document templates.""",
        "body_zh": """**如何切换语言？** 使用顶栏语言切换，或管理员中的「语言与术语」。

**为什么看不到某个模块？** 可能是角色或模块许可证未包含，请联系租户管理员。

**如何连接 Outlook / Teams？** 控制平面 → Office 生态 → 连接 Microsoft 365，侧载清单后将插件标记为已安装。

**全局搜索能找到帮助文章吗？** 全局搜索以应用页面为主；文档请用知识中心的搜索或问答。

**时间是否只用 UTC？** 港口与装卸时间等业务时间按本地时间处理与展示。

**AI 会直接写入我的记录吗？** 不会。所有 AI 功能只产出建议值、草稿或提示，落地前一律由人确认。

**我没操作却生成了东西？** 请看例行任务中枢与航次「收尾」页签 —— 业务事件触发时系统会自动创建跟进任务。

**单据能导出 PDF 吗？** 账单与装卸时间计算详情带「导出 PDF」按钮，其余类型可在「系统设置 → 单据模板」的渲染地址打开。""",
    },
    {
        "slug": "ai-assistant",
        "category": "automation",
        "tags": ["ai", "assistant", "copilot", "人工智能", "助手", "大模型", "chat"],
        "title_en": "AI assistant, MariAI chat and AI Hub",
        "title_zh": "AI 助手、MariAI 对话与 AI Hub",
        "summary_en": "Where AI lives in MariOS — the in-app assistant, the MariAI desk, and the tenant AI Hub.",
        "summary_zh": "MariOS 中 AI 的三个位置：应用内助手、MariAI 对话台，以及租户级 AI Hub。",
        "body_en": """AI in MariOS always suggests. It never writes business data on its own.

**In-app assistant** — click "AI assistant" in the bottom status bar (or press Ctrl+J). The panel shows whether a model is configured, binds the page you are on and the estimate you are editing, and offers Summarize / Daily report / Explain values. Every answer carries a source badge: "AI" means a model answered, "rules" means the built-in deterministic engine answered because no model was reachable.

**MariAI chat** (`/ai/chat`, nav: Analytics & AI → MariAI) — a full-page desk with preset agents: Voyage Advisor, Compliance Assistant, Market Analyst and Mari Copilot. Seed the agents from the empty-state button, start a conversation and ask about TCE, voyage P&L, port distances or compliance. Tool calls are listed under "Tool calls", so you can see which figures an answer used.

**AI Hub** (`/settings/ai`, tenant admins) — four tabs. Providers: add your own Anthropic / OpenAI / Azure / Ollama endpoint, test connectivity; keys are stored encrypted and never returned in clear. Model settings: a global default model plus a per-agent override. Skill bindings: route a skill to a primary provider with an optional fallback. Usage: requests, tokens in and out, average latency by agent, conversation and by day.

**Cost and quota** — a tenant's own provider key is not billed by the platform. Platform-shared endpoints are metered against the tenant allowance; when it runs out the assistant says so and you can switch to your own key. Metering is off by default.

**Limits** — the assistant answers from the page context it was given, so open the record first. Without a configured model every AI feature degrades to the rules engine. That is intended, not an error.

**Your own key, your own data** — keys are encrypted at rest, scoped to one tenant and never leave it. See AI Hub → Providers.""",
        "body_zh": """MariOS 里的 AI 始终是「建议」，它不会自行写入业务数据。

**应用内助手** —— 点击底栏的「AI 助手」（或按 Ctrl+J）。面板会显示是否已配置模型，绑定当前页面与正在编辑的估算，并提供「总结 / 生成日报 / 解释数值」等动作。每条回答都带来源徽标：「AI」表示由模型作答，「规则」表示没有可用模型时由内置确定性引擎作答。

**MariAI 对话**（`/ai/chat`，导航：分析与 AI → MariAI）—— 独立对话台，预置四类智能体：航次顾问、合规助手、市场分析师与 Mari Copilot。可从空状态按钮一键创建智能体，开始对话后即可询问 TCE、航次损益、港口距离或合规问题。回答下方「工具调用」会列出用到的取数，便于核对口径。

**AI Hub**（`/settings/ai`，租户管理员）—— 四个页签。提供商：接入自有 Anthropic / OpenAI / Azure / Ollama 端点并测试连通性，密钥加密存储且不再明文返回。模型设置：全局默认模型，并可为单个智能体指定覆盖模型。技能绑定：为技能指定主用提供商与可选的备用提供商。用量：请求数、输入/输出 token、按智能体的平均延迟、按会话与按日分布。

**成本与额度** —— 租户自有密钥不计费平台额度；平台共享端点按租户额度计量，额度用尽时助手会明确告知，可切换为自有密钥。计量默认关闭。

**边界** —— 助手基于当前页面的上下文作答，请先打开对应单据。未配置模型时所有 AI 功能退化为规则引擎，这是设计如此而非故障。

**自有密钥与自有数据** —— 密钥静态加密、限定在单个租户内，不出租户。见 AI Hub → 提供商。""",
    },
    {
        "slug": "email-ai",
        "category": "commercial",
        "tags": ["email", "mail", "m365", "ai", "邮件", "复核", "落单"],
        "title_en": "Email review and AI-assisted paperwork",
        "title_zh": "邮件复核与 AI 辅助落单",
        "summary_en": "How inbound mail becomes quotes, charters, laytime, bunker and invoice drafts — always confirmed by a person.",
        "summary_zh": "来件邮件如何变成询价、租约、装卸时间、加油与账单草稿 —— 每一步都由人工确认。",
        "body_en": """Email Review (`/email/review`) classifies inbound and outbound mail and offers the action that fits the mail type. Nothing is created until you confirm it.

**Suggested actions** — open a message and the panel parses it with rules first; business mail that is unclear or incomplete is additionally sent to the model. The badge tells you which happened: "AI identified", "Rule suggestion", or "AI identification failed — rule suggestion below". The reason line says why the action was suggested, and when the model re-classified the mail both types are shown.

**Create a business draft** — depending on the mail type this creates an estimate and charter draft, stamps the NOR time, or creates a laytime calculation, bunker order, port disbursement, invoice or claim draft. A confirmation dialog precedes it, and applying the same mail twice does nothing.

**Fill voyage estimate** — parse a recap into estimate fields. Review every value, tick the ones to use, then apply: only ticked fields are written, the rest stay untouched.

**Ignore** — mark a mail as irrelevant. With "remember this mistake" the sender and mail type are remembered so similar mail stops reaching the review queue. Ignore rules can be revoked.

**Archive** — attach a mail to a voyage, invoice, claim, bunker order or other record. The body is stored as a versioned attachment and the original mail appears in the record's linked resources.

**Mailbox tabs** — inbox, sent and custom folders are browsable in tabs. Switching folder triggers a sync with a five-minute cooldown, and the header shows how many mails were synced and when. The sync window and per-folder cap are adjustable.""",
        "body_zh": """邮件复核（`/email/review`）对收发邮件分类并给出匹配的动作建议；在你确认之前不会创建任何单据。

**处理建议** —— 打开邮件后，面板先用规则解析；对业务含义不明或字段不全的邮件，会再送模型识别。徽标说明走了哪条路：「AI 已识别」「规则建议」或「AI 识别失败 —— 以下为规则建议」。理由行说明为何给出该建议；若模型改判了邮件类型，两种类型都会并列显示。

**生成业务草稿** —— 按邮件类型创建「估算 + 租约草稿」、填报 NOR 时间，或创建装卸时间计算、加油订单、港口使费、账单或索赔草稿。创建前有确认弹窗；同一封邮件重复处理不会重复创建。

**填入航次计算** —— 把 recap 解析为估算字段。逐项核对数值，勾选需要采用的字段后再应用：只有勾选的字段会写入，其余保持原样。

**忽略** —— 标记为与业务无关。勾选「记住这个错误」后，发件人与邮件类型会被记住，同类邮件不再进入复核队列。忽略规则可撤销。

**存档** —— 把邮件挂到航次、账单、索赔、加油订单等记录上。正文以版本化附件形式保存，原邮件出现在该记录的资源链接中。

**邮箱分页** —— 收件箱、已发送与自定义文件夹以页签切换。切换文件夹会触发同步（五分钟冷却），页头显示本次同步数量与时间；同步时间窗与每文件夹条数上限可调。""",
    },
    {
        "slug": "routine-hub",
        "category": "automation",
        "tags": ["routine", "draft", "automation", "例行", "中枢", "草稿", "四眼"],
        "title_en": "Routine task hub — drafts, tasks, skills",
        "title_zh": "例行任务中枢 —— 草稿、任务与技能",
        "summary_en": "The pipeline that turns matching mail into reviewed drafts, with evidence, a four-eyes rule and write-back.",
        "summary_zh": "把命中的邮件变成待复核草稿的流水线：逐字段溯源、四眼闸门与回写落库。",
        "body_en": """The Routine task hub (`/routine`, nav: Operations → Routine tasks) turns inbound mail into reviewed drafts. Nothing reaches the books until a person confirms it.

**Three tabs** — Drafts (what to review), Routine tasks (what to automate) and Skill templates (what each extractor guarantees).

**How a draft is produced** — a trigger rule matches the mail (sender, domain, subject pattern, body markers, folder), a skill extracts the fields with a quote of the source line behind every value, and a pending draft appears. Fields with no traceable source line are dropped and listed as "Dropped for lack of evidence" rather than guessed.

**Reviewing a draft** — every field shows its value, the evidence quote and whether the model or the rules produced it. Tick the fields to keep; unticked fields are neither stored nor used in any calculation. "Adopt selected fields" writes them; "Reject" asks for a reason and is recorded in the audit trail.

**Four-eyes rule** — whoever triggered a draft cannot confirm it; a second person has to. The button is disabled and the reason is shown.

**Writing back** — an adopted draft can create a noon report, a laytime calculation or an estimate / charter draft. Values are re-validated against the skill contract before they are stored, so a bad extraction cannot silently corrupt a calculation.

**Limits** — today only inbound mail triggers a task; scheduled and event triggers are not implemented. A task is scanned every five minutes over the last seven days of synced mail, so only mail already synced into MariOS is visible.""",
        "body_zh": """例行任务中枢（`/routine`，导航：运营 → 例行任务）把来件邮件变成待复核草稿。在人工确认之前，不会进入账务。

**三个页签** —— 草稿（待复核）、例行任务（要自动化的规则）、技能模板（每个抽取器保证产出什么）。

**草稿如何产生** —— 触发规则命中邮件（发件人、域名、主题模式、正文标记、文件夹），技能抽取字段，并为每个数值附上来源行的原文引用，于是生成一条待处理草稿。找不到可追溯来源行的字段会被丢弃并列入「因缺乏依据被舍弃」，而不是猜测补齐。

**复核草稿** —— 每个字段显示取值、依据引用，以及由模型还是规则产出。勾选要采用的字段，未勾选的字段既不落库也不参与任何计算。「采用所选字段」执行写入；「驳回」需填写理由并记入审计轨迹。

**四眼原则** —— 触发草稿的人不能确认自己的草稿，须由第二人确认。按钮置灰并显示原因。

**回写落库** —— 被采用的草稿可生成船位报告、装卸时间计算或估算 / 租约草稿。落库前会按技能契约重新校验，因此错误的抽取不会悄悄污染计算结果。

**边界** —— 目前只有来件邮件能触发任务，定时触发与事件触发尚未实现。任务每五分钟扫描一次近七天已同步的邮件，因此只有已同步进 MariOS 的邮件才可见。""",
    },
    {
        "slug": "event-automation",
        "category": "automation",
        "tags": ["automation", "event", "workflow", "approval", "自动化", "事件", "工作流", "审批", "收尾清单"],
        "title_en": "Event automation, closeout checklists and approvals",
        "title_zh": "事件自动化、收尾清单与审批",
        "summary_en": "What the system creates on its own: follow-up tasks, closeout checklists, approval chains and scheduled jobs.",
        "summary_zh": "系统自动做的事：自动派生的待办、航次收尾清单、审批链与定时作业。",
        "body_en": """Most routine follow-up in MariOS is created by the system rather than typed by hand.

**What triggers work** — completing a voyage, fixing or completing a lifting, approving a charter amendment, issuing an invoice, closing a port disbursement, delivering a bunker order, settling a claim, stamping a NOR from mail, or creating a laytime draft. Each of these raises a business event; handlers then create tasks for the right role, notify the desk, and — for a closed disbursement — post the general-ledger voucher automatically.

**Closure checklist** — the voyage workspace has a Closeout tab listing the pre-close items (port calls, SOF facts, laytime finalisation, claims, invoices, bunker delivery, emissions, accrual reconciliation). When a voyage completes, every missing item becomes a task for the owning role, and the panel shows actual versus estimate TCE at the same time.

**Approval workflows** — tenant admins define a chain of approval steps under System settings → Workflows, one role per step. Submissions land in the Approval inbox, where you Approve or Reject with a comment; the initiator cannot approve their own submission. Approving a charter activates it and creates the voyage with its schedule block; approving an invoice issues it.

**Task rules** — an API-level rule can create a task when a condition on an entity is met (for example, when a voyage completes). Rules are managed through `/api/v1/config/task-rules`; only voyage completion materialises them today.

**Scheduled work** — scheduled reports (daily, weekly or monthly; Excel, PDF or CSV; delivered by e-mail) and tenant backups run on their own schedules from the background job queue.

**What is still manual** — the events raise tasks and notifications; they do not by themselves move a business state. Approvals and confirmations stay with a person.""",
        "body_zh": """MariOS 里大部分例行跟进由系统自动产生，而不是人工一条条建。

**什么会触发工作** —— 完成航次、修正或完成一个 lifting、批准租约修订、开具账单、关闭港口使费、交付加油订单、了结索赔、从邮件填报 NOR、生成装卸时间草稿。这些动作各自产生业务事件；处理器随后为对应角色创建任务、通知相关台面，并在关闭使费时自动记账总账凭证。

**收尾清单** —— 航次工作台的「收尾」页签列出关航前的检查项（挂港、SOF 事实、装卸时间定稿、索赔、账单、加油交付、排放、计提对账）。航次完成时，每一项未完成的内容都会变成对应角色的任务，同一页面并排显示实际 TCE 与估算 TCE。

**审批工作流** —— 租户管理员在「系统设置 → 工作流」中定义审批链，每个环节一个角色。提交进入审批收件箱，可通过或驳回并附意见；提交人不能审批自己的提交。批准租约即激活租约并创建航次与船期块；批准账单即开具账单。

**任务规则** —— 可通过 API 级的规则在满足条件时创建任务（例如航次完成时）。规则通过 `/api/v1/config/task-rules` 管理；目前只有「航次完成」会实际派发。

**定时作业** —— 定时报表（按日/周/月，输出 Excel / PDF / CSV，按邮件投递）与租户备份由后台作业队列按各自计划运行。

**仍然需要人的环节** —— 事件负责产生任务与通知，本身不会推进业务状态；审批与确认仍由人完成。""",
    },
    {
        "slug": "documents",
        "category": "finance",
        "tags": ["document", "pdf", "template", "单据", "PDF", "模板", "抬头"],
        "title_en": "Documents, PDF export and templates",
        "title_zh": "单据、PDF 导出与模板",
        "summary_en": "Fourteen document types rendered from editable templates, with letterhead, PDF export and e-mail sending.",
        "summary_zh": "十四类单据由可编辑模板渲染，含抬头、PDF 导出与邮件发送。",
        "body_en": """Documents are rendered from templates you can edit, then printed, exported as PDF or sent by e-mail.

**Single document templates** — System settings → Document templates lists fourteen document types: invoice, credit note, laytime statement, hire statement, charter recap, estimate, PDA, claim, SOF, COA, voyage instruction, statement of account, remittance advice and BDN. Pick a type, edit its HTML and CSS, watch the live preview and save. Chinese and English layouts are separate.

**Letterhead** — the company name, address, contacts, tax number and logo printed on every document come from the tenant company profile, so a change there updates every document.

**Exporting** — invoice and laytime calculation details carry an "Export PDF" button; other document types are reachable through their render URL. Every render can be archived so you can download a copy later.

**Sending** — a document can be sent as an e-mail attachment. If delivery fails the document is still produced and the delivery status is reported rather than swallowed.

**Limits** — PDF output needs a rendering engine on the server; without it the document falls back to an HTML view. Only invoice and laytime carry the button today.""",
        "body_zh": """单据由可编辑的模板渲染，随后可打印、导出 PDF 或按邮件发送。

**单据模板** —— 「系统设置 → 单据模板」列出十四类单据：账单、贷记单、装卸时间证明、租金结算单、租约摘要、估算、港口使费、索赔、装卸事实单、代理指令、航次指示、对账单、汇款通知与提单。选中类型后可直接编辑 HTML 与 CSS，实时预览后保存。中英文版式相互独立。

**抬头** —— 每份单据上的公司名称、地址、联系人、税号与标识来自租户公司档案，改一处即全局生效。

**导出** —— 账单与装卸时间计算详情带「导出 PDF」按钮，其余类型可通过其渲染地址打开。每次渲染都可以归档，之后可再次下载。

**发送** —— 单据可作为邮件附件发送。发送失败时单据仍然生成，失败状态会被如实反馈而不是被吞掉。

**边界** —— PDF 输出依赖服务端的渲染引擎，缺失时降级为 HTML 视图。目前只有账单与装卸时间带该按钮。""",
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
    {
        "id": "q_ai",
        "patterns": [r"\bai\b", r"人工智能", r"智能", r"助手", r"大模型", r"copilot", r"聊天", r"chat", r"模型", r"model"],
        "answer_en": "AI in MariOS always suggests and never writes on its own: use the assistant (Ctrl+J), the MariAI chat desk (/ai/chat) and the AI Hub (/settings/ai) for providers, models, skills and usage. Without a configured model everything falls back to the deterministic rules engine.",
        "answer_zh": "MariOS 的 AI 始终只给建议，不会自行写入数据：应用内助手（Ctrl+J）、MariAI 对话台（/ai/chat），以及 AI Hub（/settings/ai，管理提供商、模型、技能与用量）。未配置模型时全部退化为确定性规则引擎。",
        "article_slugs": ["ai-assistant", "email-ai"],
    },
    {
        "id": "q_routine",
        "patterns": [r"例行", r"routine", r"中枢", r"草稿", r"draft", r"自动化", r"automati", r"自动", r"四眼", r"four.?eyes"],
        "answer_en": "Operations → Routine tasks turns matching mail into reviewed drafts with per-field evidence. Whoever triggered a draft cannot confirm it — a second person approves (four-eyes rule). Adopted drafts can write back a noon report, laytime calculation or estimate / charter draft.",
        "answer_zh": "运营 → 例行任务把命中的邮件变成带逐字段依据的待复核草稿。触发者不能确认自己的草稿，须第二人批准（四眼原则）。被采用的草稿可回写船位报告、装卸时间计算或估算 / 租约草稿。",
        "article_slugs": ["routine-hub", "event-automation"],
    },
    {
        "id": "q_workflow",
        "patterns": [r"审批", r"approval", r"approve", r"工作流", r"workflow", r"收件箱", r"inbox", r"自动创建", r"事件", r"event"],
        "answer_en": "Voyage completion, invoice issue, disbursement closure and similar actions raise business events that create follow-up tasks, desk notifications and the voyage closeout checklist. Approval chains are defined in System settings → Workflows; submissions wait in the Approval inbox.",
        "answer_zh": "航次完成、账单开具、使费关闭等动作会产生业务事件，自动派生跟进任务、台面通知与航次收尾清单。审批链在「系统设置 → 工作流」定义，提交后在审批收件箱等待处理。",
        "article_slugs": ["event-automation", "admin-security"],
    },
    {
        "id": "q_document",
        "patterns": [r"单据", r"document", r"pdf", r"模板", r"template", r"打印", r"print", r"抬头", r"letterhead"],
        "answer_en": "System settings → Document templates holds fourteen editable document types (invoice, laytime statement, PDA, SOF, COA, …). Invoice and laytime carry an Export PDF button; the company letterhead comes from the tenant company profile.",
        "answer_zh": "「系统设置 → 单据模板」内置十四类可编辑单据（账单、装卸时间证明、港口使费、SOF、代理指令……）。账单与装卸时间带「导出 PDF」按钮，公司抬头取自租户公司档案。",
        "article_slugs": ["documents", "finance-laytime"],
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
