# AGENTS.md

本文件面向 AI 编码代理，假设读者对本项目一无所知。修改代码前请先通读。

## 项目概览

**MariOS（MOS）** —— 面向船东、租家、Operator 与船舶管理公司的**航运商业操作系统**（Commercial Voyage Management）。业务链路：航次估算/TCE → 租船（CP）→ 航次执行（午报/SOF）→ Laytime/滞期索赔 → 燃油 → 财务结算/GL；另有 AI Hub、Microsoft 365 集成（Teams/Outlook/Excel/SharePoint）、船队数字孪生（Twin）、多租户 SaaS 与模块许可证体系。

- 架构形态：**模块化单体**（modular monolith），多租户、按模块授权；可单机 Docker Compose 部署。
- 本目录 `mos/` 是 GitHub 仓库 `github.com/dqf514/maritime` 的子目录，git 命令作用于父仓库。
- 文档与代码注释为**中英混排**，沿用周围文件风格；界面默认语言 English，带完整 i18n 与航运术语库。
- Demo 登录：`admin@demo.marios` / `Demo1234!` / tenant `demo`（需 `SEED_DEMO=true`）。
- 开发 SSOT 为《MariOS 完整开发规格说明书（DDS）V2.1.md》（在文档中被引用）；`DEVELOPMENT.md` 记录本地开发流程；`docs/` 为客户可见文档，**内部规划（`docs/internal/`）不得放入客户可见渠道**。

## 仓库布局

```
mos/
├── apps/
│   ├── api/        # FastAPI 后端（系统主体）
│   └── web/        # Next.js 前端
├── fixtures/calc/  # 计算金样（tce/、laytime/），pytest 与 SelfCheck 同源
├── deploy/compose/ # Docker Compose 部署（Postgres + Redis + MinIO + API + Web）
├── office/         # M365 插件清单（excel/outlook manifest.xml、teams manifest.json）
├── docs/           # 客户可见文档；docs/internal/ 为内部规划
├── index.html      # 产品介绍页（浏览器直接打开）
└── imos.txt        # iMOS 参考资料
```

## 技术栈

- **后端**（`apps/api`）：Python + FastAPI 0.141、SQLAlchemy 2.0（ORM）、Pydantic 2、Alembic（迁移）、python-jose（JWT）、bcrypt、redis、httpx、openpyxl、anthropic SDK。数据库默认 SQLite（`voyageos_wave0.db`），生产用 Postgres 16（psycopg 3）。依赖固定在 `apps/api/requirements.txt`（无 pyproject.toml）。
- **前端**（`apps/web`）：Next.js 16.3 + React 19 + TypeScript 6，ESLint 9（`eslint-config-next`）。**注意：此版本 Next.js 与训练数据中的旧版有破坏性差异**——写 Next 相关代码前先读 `node_modules/next/dist/docs/` 中对应指南（见 `apps/web/AGENTS.md`，该文件由 `next dev` 自动重写，勿删除其中标记块）。
- **部署**：Docker Compose（`deploy/compose/docker-compose.yml`）：Postgres + Redis + MinIO（S3）+ API + Web。

## 构建与运行命令

命令示例为 Windows PowerShell（出自 DEVELOPMENT.md）；其他 shell 自行调整。

### API

```powershell
cd apps/api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r requirements.txt
$env:LICENSE_DEV_UNLOCK="all"   # 开发/测试必需：解锁全部模块
uvicorn app.main:app --reload --port 8000
```

### Web

```powershell
cd apps/web
npm install
$env:NEXT_PUBLIC_API_BASE="http://localhost:8000"
npm run dev     # 另有：npm run build / npm run start / npm run lint
```

## 测试（必跑）

任何改动在完成前必须跑全量后端测试：

```powershell
cd apps/api
$env:LICENSE_DEV_UNLOCK="all"
.\.venv\Scripts\python.exe -m pytest -q
```

- 单测选择：标准 pytest node-id，如 `python -m pytest tests/test_full_chain.py::test_calc_engines_unit -q`。
- 套件是端到端全链路：登录 → 估算/TCE 金样 → CP 状态机 → 航次/午报/SOF → Laytime/索赔/PDA → 燃油 ROB → 发票收款/GL → 市场/排放/报表 → 联营池/风险/泊位/门户 → Twin L4 → SelfCheck 金样，另含制裁阻断与租户隔离用例（`tests/test_tenant_isolation.py` 等）。
- **金样例**位于 `fixtures/calc/tce` 与 `fixtures/calc/laytime`，是 pytest 与应用内 SelfCheck（`apps/api/checks/registry.py`）的共同事实源——两侧必须保持同步、保持全绿。
- 测试环境由 `tests/conftest.py` 设置：默认使用**临时文件 SQLite**（非内存库，避免 TestClient 跨线程连接竞态）；设置 `TEST_DATABASE_URL` 可切换为一次性 Postgres 集成模式（每测试 drop/create 全 schema，CI 的 api-pg 作业用此方式，CI 配置在父仓库）。测试中 `MARIOS_LLM_OFF=1` 熔断 LLM（零网络）。
- 前端无测试套件，用 `npm run lint` 与 `npm run build` 验证。

## 部署

- `deploy/compose/docker-compose.yml`，API 构建上下文**必须是 `mos/` 根**（fixtures 在 `mos/fixtures`，SelfCheck 依赖此布局）。
- **不要**挂载 `docs/ddl.sql` 做数据库初始化——该文件已与模型漂移；空库由 API 启动时 `create_all` 建表，再 `alembic stamp head` 登记基线。

## 后端架构（`apps/api/app`）

分层：**routers**（`routers/*.py`，全部挂载于 `/api/v1`）→ **services**（`services/*.py`，领域引擎与平台基础设施）→ **models**（`models*.py`，按域拆分：`models_domain`、`models_ops`、`models_gl`、`models_identity`、`models_saas`、`models_office` 等）+ Pydantic schemas（`schemas*.py`）。

新增 `models_*.py` 模块时，必须同时在 **`app/main.py` 和 `tests/conftest.py`** 中 import（元数据注册由 import 驱动）。

关键横切机制：

- **多租户**：无数据库级隔离，每条路由手写 `tenant_id ==` 过滤。新代码使用约定封装 `services/tenant_guard.py`（`scoped_get` / `scoped_query`，同时处理软删除过滤）。软删除有两种约定（见 `services/recycle.py`）：`deleted_at` 时间戳列，或 `status = "deleted"`。`services/tenant_datastore.py` 是每租户独立引擎的预留钩子（当前恒为主库）。
- **状态机**：`services/state_machine.py` —— `transition()` 对非法迁移抛 409 `INVALID_STATE`；各实体有独立迁移表（`CHARTER_TRANSITIONS`、`VOYAGE_TRANSITIONS`、`INVOICE_TRANSITIONS` 等）。财务工作流（如红冲 credit-note）在 router 层与这些迁移配合实现。
- **计算引擎**：`services/estimate_engine.py`（TCE）、`laytime_engine.py`、`gl_engine.py`、`pnl_engine.py`、`hire_engine.py`、`carbon_calculator.py`、`cii.py` 等。基于 Decimal、确定性，须用 `fixtures/calc` 金样校验。
- **认证与安全**（`app/security.py`）：双轨会话——JWT 既在响应体返回，又写入 HttpOnly Cookie `marios_token`（旧名 `voyageos_token` 仍兼容）；也支持 Bearer / API Key。CSRF 姿态为 SameSite=Lax + 严格 CORS allow_credentials（理由记录在 `security.py` 注释中，改动 Cookie/CORS 时保留该推理）。模块许可证经 `require_module()` 校验，未授权返回 403 `MODULE_NOT_LICENSED`；开发用 `LICENSE_DEV_UNLOCK=all` 绕过。
- **启动种子**（`main.py` lifespan）：目录类数据总是播种（SaaS catalog、i18n、ops catalog、reference catalog）；demo 租户/用户仅当 `SEED_DEMO=true` 时播种。
- **Schema 管理**：启动时执行 `Base.metadata.create_all`，另在 `main.py` 保留针对旧 SQLite dev 库的存量 `ALTER TABLE` 补丁。**新的 schema 变更一律走 Alembic**（`alembic revision --autogenerate`），不要再往 ALTER 补丁列表加列。存量库先 `alembic stamp head` 再 `alembic upgrade head`，详见 `apps/api/alembic/README.md`（SQLite 下启用 `render_as_batch`）。
- **导航**：角色驱动的服务端导航，定义在 `services/shell_nav.py`（iMOS 风格分区：Workbench → Chartering → Operations → Finance → Technical → Analytics → Master data → Administration → Platform），被搜索 ACL 与 Web AppShell 消费——导航改动放在服务端，不要在前端硬编码。
- **SelfCheck**（`apps/api/checks/registry.py`）：应用内健康/计算金样检查，须与 pytest 同步保持全绿。
- **LLM**：平台默认配置在 `app/config.py`（Anthropic/OpenAI），租户级 `AiProvider` 行可覆盖；`MARIOS_LLM_OFF=1` 为运行时熔断开关（`llm_client` 抛 `LLMNotConfigured`，调用方回退规则引擎）。

## 前端架构（`apps/web`）

- `app/` 下路由目录与后端模块对应（`estimates/`、`charters/`、`operations/`、`finance/`、`twin/`、`platform/` 等）。
- `lib/api.ts` —— fetch 封装（`apiGet`/`apiPost`，读 `NEXT_PUBLIC_API_BASE`）；token 存 localStorage（`marios_token`，含从旧 `voyageos_*` 键的一次性迁移）。
- `lib/i18n.tsx` —— 客户端 i18n；UI 默认 English，术语感知。
- `components/` —— 共享 UI 组件库（DataTable、RecordModal、StateView、Toast、Skeleton、ErrorBoundary、ThemeProvider/暗色模式、LookupSelect、AppShell 等）。

## 代码风格与约定

- 注释与文档中英混排，与所在文件现有风格保持一致；UI 文案默认英文。
- 修改遵循最小侵入原则：新路由挂在 `/api/v1` 下并按域放入对应 router 文件；新领域逻辑放 `services/`；数据库访问走 `tenant_guard` 封装。
- 计算代码用 Decimal，保持确定性，并以金样验证。
- 改完代码后，顺带核对受影响的注释/文档字符串是否仍描述旧行为。

## 安全注意事项

- 生产环境必须显式设置 `JWT_SECRET`（无默认值；未设时生成进程级随机密钥，重启后全部 token 失效）。
- `ENV=production` 会关闭 `/docs` 与 `/openapi.json`；生产必须 `COOKIE_SECURE=true`（HTTPS）。
- 平台 OAuth 密钥（Microsoft/Google client secret）绝不暴露给租户或前端。
- `OPS_DATA_KEY` 用于 ops/office 静态数据加密，缺省回退 `jwt_secret`。
- 租户隔离完全依赖代码层的 `tenant_id` 过滤——新增查询路径必须走 `tenant_guard` 或显式过滤，并有租户隔离测试覆盖。
- 认证端点有进程内滑动窗口限流（`RATE_LIMIT_ENABLED`，测试中关闭）。

## 重要环境变量

均定义于 `apps/api/app/config.py`（pydantic-settings，支持 `.env`）：

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | 默认 SQLite `sqlite+pysqlite:///./voyageos_wave0.db`；生产用 Postgres |
| `JWT_SECRET` | 生产必填，无默认值 |
| `LICENSE_DEV_UNLOCK` | `all` 解锁全部模块（仅开发/测试） |
| `SEED_DEMO` | `true` 时启动播种 demo 租户/用户 |
| `NEXT_PUBLIC_API_BASE` | 前端指向 API 的地址 |
| `RATE_LIMIT_ENABLED` | 认证端点限流开关 |
| `COOKIE_SECURE` | 会话 Cookie 的 Secure 标记，生产必须 `true` |
| `ENV` | `production` 关闭 OpenAPI 文档端点 |
| `MARIOS_LLM_OFF` | 运行时 LLM 熔断（非 Settings，直接读 env） |
| `TEST_DATABASE_URL` | 测试切换到一次性 Postgres 集成模式 |
