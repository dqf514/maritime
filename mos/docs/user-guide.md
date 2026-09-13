# VoyageOS 用户指南

面向业务用户与租户管理员的操作说明。更细的条目可在产品内 **知识中心**（`/help`）检索或问答。完整图文步骤见 **全流程操作手册**：开发环境打开 [`/manual/`](/manual/)（文件 `apps/web/public/manual/index.html`）。

## 1. 产品是什么

VoyageOS 是航运商业操作系统：把估算 → 租约 → 航次执行 → 装卸时间 / 索赔 → 燃油 → 财务结算收进同一工作台，并与 Microsoft 365、开放 API、多语言术语库协同。

## 2. 登录与角色

| 角色示例 | 典型入口 |
|----------|----------|
| 租船 | 工作台 · 估算 · 租约 · 邮件复核 |
| 运营 | 航次 · 船队孪生 · 挂靠港 / 午报 / SOF |
| 财务 / 滞期 | 财务台 · 装卸时间 · 发票 · 航次损益 |
| 机务 | 船舶管理 · 证书 / PMS |
| 租户管理员 | 控制平面 · 用户 · 安全 · Office 生态 · 集成 |
| 平台运营 | `/platform` · 数据面与部署 `/platform/ops` |

演示租户码 `demo`；平台运营租户码 `sys`。

全局搜索：**Ctrl+K**。帮助：**顶栏 / 侧栏 → 知识中心**。

## 3. 商务主链路

1. **估算**：录入船、货、航程与 Worldscale 等参数 → 计算 TCE → 敏感度 / 对比 → 转租约。  
2. **租约**：审批（若启用）→ 激活。  
3. **航次**：靠港时间线（本地时区）→ 午报 / SOF。  
4. **装卸时间与索赔**：条款 + SOF → 计算定稿 → 索赔 / 开票。  
5. **分析**：航次损益（估算 vs 实际 vs 差异）。

## 4. Microsoft 365

控制平面 → **Office 生态**：连接组织、同步邮件 / 文件 / Teams、出站 Webhook、侧载 Outlook / Teams / Excel 插件。详见 [office-ecosystem.md](./office-ecosystem.md)。

## 5. 集成与 API

- OpenAPI：API 主机 `/docs`  
- API 密钥：控制平面 → API 密钥（`X-API-Key`）  
- 连接器：控制平面 → 集成中枢  
- 说明：[api-integrations] 知识中心文章

## 6. 数据与部署（平台运营）

默认本地开发 SQLite；Compose / 生产推荐 PostgreSQL。共享主库 + 租户隔离；可按租户登记独立数据源（切库路由预留）。详见 [platform-data-deploy.md](./platform-data-deploy.md)。

## 7. 多语言

顶栏切换语言；管理员可维护航运术语。默认界面语言为 English，完整支持简体中文等。

## 8. 相关链接

| 资源 | 路径 |
|------|------|
| 产品介绍（静态） | `index.html` |
| 产品门户（Web） | `/` |
| 知识中心 | `/help`（登录后） |
| 登录 | `/login` |
| 文档导读 | [README.md](./README.md) |
