# 文档导读

## 面向客户 / 用户

| 资源 | 说明 |
|------|------|
| [产品介绍页](../index.html) | 对外产品介绍 |
| 产品门户（Web `/`） | 在线介绍与模块一览 |
| 产品内 **帮助 / 知识中心**（`/help`，需登录） | 可检索、可问答的操作与产品说明 |
| [用户指南](./user-guide.md) | 登录、主链路、Office、API 总览 |
| [能力一览](./product-capabilities.md) | 对外可陈述的能力清单 |
| [Microsoft 365 说明](./office-ecosystem.md) | Office 生态连接与能力概览 |
| [平台数据面与部署](./platform-data-deploy.md) | 默认数据库、租户库绑定、初始化与部署档案 |
| [部署指南](./deployment.md) | Docker Compose 部署、发布、反代、备份、安全清单 |

请勿将内部研发清单或施工指令放入客户可见渠道。

## 面向研发 / 实施（内部）

| 资源 | 说明 |
|------|------|
| [DEVELOPMENT.md](../DEVELOPMENT.md) | 本地开发与测试 |
| [CLAUDE.md](../CLAUDE.md) | 架构约定与开发规约（代码库根，AI 协作用） |
| [internal/](./internal/) | 内部规划与差距跟踪、QA 摘要（不对客户展示） |
| [deploy/compose/README.md](../deploy/compose/README.md) | 部署编排说明（compose 服务、卷、迁移、备份） |
| [apps/api/alembic/README.md](../apps/api/alembic/README.md) | 数据库迁移说明（空库自举、迁移约定、常用命令） |

> 旧版本文档里指向「DDS V2.1 完整开发规格说明书」的链接已移除 —— 该文件不在仓库中
> （且被 `.gitignore` 忽略），链接必然失效。请以上表为准。
