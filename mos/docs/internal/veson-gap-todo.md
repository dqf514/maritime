# 【内部文档 · 不对客户展示】MariOS 能力差距跟踪

> **机密 / 内部**：本文仅供产品与研发规划，禁止链接到产品介绍页、知识中心或对外材料。  
> 对标来源仅作内部能力清单参考，勿写入客户文案。

> 状态：`solid` = 可商用深度 · `thin` = 有入口但演示级 · `gap` = 缺失

---

## 0. 结论一句话

Veson = **IMOS 业务主干 + CoCaptain AI + Mail + Insights** 一体化。  
我们 = **SaaS/壳层完整**；商业主干已从「列表架子」推进到 **可操作 Desk**（估算/租约/航次/财务·滞期·动态P&L），引擎+台面开始对齐；Mail/AI/Insights/Risk 仍待做厚。

### 本轮已落地（生产力台面，2026-09）

- [x] **估算台**：完整输入、Worldscale/ECA、Save/Calculate/Clone/Sensitivity/Compare/To CP
- [x] **租约台**：创建表单、审批流转、COA lifting
- [x] **航次操作台**：挂靠港 / SOF / 午报 / Twin 轨迹
- [x] **Laytime 台**：条款参数 → 计算 → 定稿 → 索赔
- [x] **动态航次 P&L**：估 vs 实 vs 差异（发票/PDA/燃油驱动）
- [x] **收付款 / GL post** 台面入口
- [x] **Office 生态 Hub**：M365 连接（Graph stub/live）、Mail/Files/Teams/SharePoint 同步、Webhook、Outlook/Teams/Excel 插件清单、API Key 伙伴鉴权

---

## 1. Veson 有、我们明显缺或偏弱（必须补齐）

### P0 — 商业主干深度（否则“不能比人家差”不成立）

- [ ] **估算台（Estimate Desk）**：模板、分段航程、Worldscale、ECA/运河、多方案并排对比 UI、敏感度图、从邮件/货盘一键生成
- [ ] **合同类型完备**：程租 VC / 期租 TC / 光租 BB / **COA liftings 全生命周期** / TCT；条款库与修订变更单
- [ ] **货盘 Cargo Book**：货种主数据、tolerance、laycan、船货匹配（pre-fixture）
- [ ] **船期 Scheduling**：甘特/占用视图、冲突硬拦、从 CP→占船→开航次一键链路
- [ ] **航次操作台**：挂靠港时间线、任务/指令、午报录入与校验、异常告警（非仅 API）
- [ ] **NOR/SOF 台**：时区正确的时间事实表、可审计、驱动 Laytime
- [ ] **港口使费 PDA/FDA**：编制→审批→归集航次→对账闭环 UI
- [ ] **燃油 Bunker**：计划/询比价/BDN/ROB 守恒/航次分摊（全生命周期）
- [ ] **Laytime/Demurrage 业务台**：条款参数化 UI + 定稿导出（引擎已有，缺台面）
- [ ] **Claims**：立案→谈判→时效→和解，与 Laytime/发票联动
- [ ] **动态航次 P&L**：估→实差异、费用驱动因子、实时滚动（对标 Dynamic P&L）
- [ ] **财务结算**：运费/租金/滞期/燃油发票全类型、收付款台、红冲、账龄钻取
- [ ] **GL/ERP 过账**：科目映射 + 导出/连接器（SAP/Oracle/Dynamics 至少一种可跑通）

### P1 — Veson Platform 四大层面对齐

- [ ] **情境式 AI（对标 CoCaptain）**：嵌入航次/租约/估算上下文的对话助手；非演示 stub
- [x] **Office Hub 骨架**：Graph 连接、同步、Teams 通知、SharePoint/OneDrive 链接、出站 Webhook、插件清单（见 `/settings/office`、`docs/office-ecosystem.md`）
- [ ] **原生邮件（对标 Veson Mail / Connect）**：航次/合同旁侧邮箱；真实 IMAP/Graph 深度业务抽取；AI 标记与抽取落单据
- [ ] **市场数据 Insights**：船队筛查、燃油预测/港口价、指数与成交带；进入估算/风险工作流
- [ ] **开放 API & 伙伴集成**：稳定 OpenAPI、Webhook、双向同步；文档与沙箱租户

### P2 — 风险 / 合规 / 专项（IMOS 公开卖点）

- [ ] **Trading & Risk**：运费/燃油/碳敞口、FFA/纸货、限额、头寸 vs 实货对冲视图
- [ ] **排放合规**：CII、EU ETS、FuelEU 进入估算与航次成本
- [ ] **Pooling**：入退池、池点、分配、现金结算
- [ ] **Berth / Lightering / LNG 专项**：可许可证模块但须达到 DoD
- [ ] **对手方门户**：发票确认、有限协同

---

## 2. 已有模块 — 必须“做厚”到不低于对标（禁止停在演示）

| 模块 | 现状 | Todo（达标定义） |
| --- | --- | --- |
| Estimate | 引擎 solid，UI thin | 完整估算台 + 对比 + 模板 + WS/运河/ECA |
| Chartering | 状态机 + 制裁 thin | 多合同类型表单 + COA + 审批修订闭环 |
| Scheduling | 冲突标记 thin | 可视化船期 + 硬冲突策略 |
| Operations | CRUD thin | 操作台时间线 + 午报 + 任务 |
| PortCall/SOF | API thin | NOR/SOF 业务页 + 驱动 Laytime |
| Laytime | 引擎 solid | 条款 UI + 定稿/导出/索赔入口 |
| Finance | 发票列表 thin | 全票种 + 收付款 + 动态 P&L |
| Email | 假同步 thin | 真同步 + 旁侧上下文 + 抽取得确认 |
| AI Hub | stub | 情境助手 + 真实模型调用与计量 |
| Twin | L1/L4 demo | 船队态势与航次回放达到决策可用 |
| Analytics | 三张表 thin | 标准报表包 + 订阅 + 钻取 |
| Connectors | 健康检查 stub | 至少 2 个实连接（制裁/汇率或 AIS/燃油） |
| Ship Mgmt | 卡片 demo | 证书/缺陷/工单闭环或稳定外接 PMS |

---

## 3. 我们相对 Veson 的差异化（保持并宣传）

- [x] 多租户 SaaS 控制平面（套餐 / AI 计量 / 钱包）
- [x] 平台品牌 / 身份策略 / 租户安全策略分层
- [x] i18n + 航运术语覆盖（en / zh-CN）
- [x] SelfCheck / DataOps 迁入备份（产品化运维）
- [ ] 把上述能力写进门户叙事：**中国市场可部署的 IMOS 级商业 OS + 完整 SaaS**

---

## 4. 建议施工序（对齐 DDS Wave，但每波必须到 DoD）

1. **Wave A — Pre-fixture 做厚**：估算台、货盘、COA、对比、转 CP  
2. **Wave B — Ops 做厚**：船期甘特、航次台、NOR/SOF、午报  
3. **Wave C — Money 做厚**：Bunker、PDA/FDA、Laytime 台、Claims、动态 P&L、收付款、GL  
4. **Wave D — Platform 体验**：Mail 旁侧、CoCaptain 式助手、Insights 接入  
5. **Wave E — Risk & Compliance**：敞口、ETS/FuelEU、Pooling  

每波验收：**同一角色在 Veson 宣传页上能做的主路径，在 MariOS 可端到端演示且数据可审计。**

---

## 5. Logo / 品牌（本轮已做）

- [x] 去掉“小船+单据”插画风，改为海军蓝底 + 青绿航向/地平线极简 mark
- [x] 更新 `public/branding/mark.svg`、`logo.svg`，并同步 `icon.png` / `logo.png`
