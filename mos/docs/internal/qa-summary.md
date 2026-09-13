# 测试与验收摘要（内部）

> 内部记录，不对客户展示。

## 最近全量结果

- **pytest**：`apps/api/tests` **47 passed**（含 `test_full_chain`、`test_smoke_surface`、office、help、platform_ops 等）
- **操作手册（HTML）**：`apps/web/public/manual/index.html` → 开发环境访问 `/manual/`
- **API 冒烟**：healthz、me、estimates、charters、voyages、laytimes、invoices、office、help、platform/ops/*
- **浏览器**：建议按手册第 8 节人工走查清单核对 UI

## 客户文档核对

- `index.html`、Web 门户 `/`、`/help`、`docs/user-guide.md`、`docs/product-capabilities.md`、Office / 数据面说明、**全流程操作手册 `/manual/`**

## 已知边界（产品诚实表述）

- **定位**：商业主干可试点演练；大型航运公司生产级「全流程唯一核心」仍需加深邮件/ERP/船期/AI 等模块
- 租户独立数据库：可绑定登记，业务会话仍走主库
- 云厂商部署 API：模板与指引，非真实云控制台代管
- 知识中心问答：FAQ + 检索增强（非大模型实时生成）
