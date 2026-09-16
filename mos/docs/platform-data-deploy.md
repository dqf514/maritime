# 平台数据面与部署

面向实施与平台运营的产品说明（客户可见语气）。内部对标或研发清单请放在 `docs/internal/`。

## 当前默认数据库

| 场景 | 数据库 | 配置 |
|------|--------|------|
| 本地开发（默认） | **SQLite** | `DATABASE_URL=sqlite+pysqlite:///./voyageos_wave0.db`（见 `apps/api/app/config.py`） |
| Compose / 生产推荐 | **PostgreSQL 16** | `postgresql+psycopg://…@postgres:5432/marios`（见 `deploy/compose`） |

多租户以**共享主库 + `tenant_id` 行级隔离**运行。平台运维台支持按租户登记独立数据源（本地 / 数据库服务器 / 主流云托管库），连接串加密存储；**业务会话当前仍使用主库**，独立引擎路由已预留。

## 后台能力入口

1. 使用平台运营账号登录（演示：`ops@marios.platform` / 租户码 `sys`）。
2. 打开 **平台运维 → 数据面与部署**，路径：`/platform/ops`。
3. 或知识中心检索「数据面」「部署」「数据库」。

页内分区：

- **运行时数据源** — 方言、脱敏连接、主库探测  
- **租户库绑定** — CRUD、连通性测试、路由策略（绑定登记 / 预留切库）  
- **系统初始化** — 建表、目录种子、演示数据、就绪检查  
- **部署档案** — Compose、单机、阿里云 / AWS / Azure 等模板与可视化指引  
- **监控与预警** — 延迟 / 磁盘等快照与规则启停  

API 前缀：`/api/v1/platform/ops/`（需 `platform_admin`）。

## 相关资源

- Compose：`deploy/compose/docker-compose.yml`
- 知识中心文章：`platform-data-deploy`
- OpenAPI：API 主机 `/docs`
