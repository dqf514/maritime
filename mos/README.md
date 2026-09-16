# MariOS（MOS）

面向船东、租家、Operator 与船舶管理公司的**航运商业操作系统**（Commercial Voyage Management）。

从航次估算、租约、航次执行、滞期/索赔、燃油到财务结算全链路闭环；邮件与多 AI 协同；船队数字孪生可视化；开放集成与完整 API；与 Microsoft 365（Teams、SharePoint、OneDrive、Outlook）生态互通。

## 仓库位置

本目录位于 GitHub 仓库：

**https://github.com/dqf514/maritime/tree/main/mos**

远程：`https://github.com/dqf514/maritime.git`（目录 `mos/`）

## 客户可见材料

| 资源 | 说明 |
| --- | --- |
| [index.html](./index.html) | 产品介绍页 |
| Web 门户 `/` | 在线介绍与模块 |
| 应用内 `/help`（需登录） | 知识中心（检索 + 问答） |
| [docs/user-guide.md](./docs/user-guide.md) | 用户指南 |
| [docs/product-capabilities.md](./docs/product-capabilities.md) | 能力一览 |
| [docs/office-ecosystem.md](./docs/office-ecosystem.md) | Microsoft 365 |
| [docs/platform-data-deploy.md](./docs/platform-data-deploy.md) | 数据面与部署 |
| [docs/README.md](./docs/README.md) | 文档导读 |

## 研发材料（内部）

| 资源 | 说明 |
| --- | --- |
| [MariOS 完整开发规格说明书（DDS）V2.1.md](./MariOS%20完整开发规格说明书（DDS）V2.1.md) | 开发 SSOT |
| [DEVELOPMENT.md](./DEVELOPMENT.md) | 本地开发与测试 |
| [docs/internal/](./docs/internal/) | 内部规划（不对客户展示） |

## 本地预览介绍页

用浏览器直接打开 `index.html` 即可。知识中心在登录产品后进入（`/help`）。

## 开始开发

见 [DEVELOPMENT.md](./DEVELOPMENT.md)。

Demo 登录：`admin@demo.marios` / `Demo1234!` / tenant `demo`

## 技术要点（摘要）

- 模块化单体，可单机 Docker Compose 部署，可扩展多机/多云  
- 默认界面语言 English，完整多语言 + 航运术语库  
- 模块许可证、多租户隔离、AI Hub、Integration Hub、API 管理、SelfCheck 自检  
- **DataOps**：从邮件/PST/O365/公共文件夹/Excel **AI 迁入**（勾选确认落库）；一键备份与恢复  
- **Office 生态**：Graph 连接、Teams 通知、SharePoint/OneDrive 资源链接、插件清单与 Webhook  
