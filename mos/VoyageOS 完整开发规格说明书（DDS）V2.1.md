# VoyageOS 完整开发规格说明书（DDS）V2.1

> **文档性质**：产品需求 + 架构约束 + 模块规格 + UX 操作系统 + 自检体系 + 数字孪生，**单一事实源（SSOT）**。  
> **读者**：架构师、后端/前端/QA、运维、业务专家。读完应可**脱手完整开发**，无需再猜范围。  
> **废止关系**：本文为 VoyageOS **唯一开工 SSOT**；此前 V1.x PRD / 增补文档已移除。业务口径、控制平面、计算规则、模块闭环均以本文为准。  
> **对标**：公开能力上对标并超越 Veson IMOS 类商业航次管理系统（Commercial VMS/ERP）；**唯一承认短期落后于历史数据积累**。  
> **默认语言**：English（en）；完整多语言 + 航运术语库。  
> **版本**：V2.1 | 2026-09-13 | 状态：可完整开工  
> **GitHub**：https://github.com/dqf514/maritime/tree/main/mos（仓库 `dqf514/maritime`，目录 `mos/`）  
> **V2.1**：新增 **DataOps（迁移 / 备份 / 恢复）** 与 **AI 迁入向导**——从邮件/PST/O365/公共文件夹/Excel 一键分析、勾选确认落库。

---

## 0. 如何使用本文开发（给架构师/程序员）

### 0.1 开工顺序

1. 搭建 Stage A 单机 Compose（见第 12 章）+ 平台内核（租户/许可证/i18n/控制平面骨架）  
2. 实现 **VoyageOS Shell（Windows 级壳层）**（第 3 章）——所有业务模块挂载于此  
3. 按 **业务闭环依赖序**（第 5.2 节）实现模块；每个模块必须达到「闭环 DoD」（第 0.3）才算完成  
4. 同步实现 **自检系统 SelfCheck**、**DataOps（迁入/备份/恢复）** 与 **数字孪生 Fleet Twin**（第 7A、9、10 章），不可事后补丁  
5. OpenAPI / 连接器 / AI Hub 与业务同步，禁止业务直连第三方 SDK  

### 0.2 强制原则

| # | 原则 |
| --- | --- |
| P1 | **功能齐全**：许可证可关闭模块，但**产品必须开发齐全**；不是「以后再说」 |
| P2 | **业务闭环**：每个模块有入口、处理、出站、财务/审计落点、异常路径 |
| P3 | **操作像 Windows**：全局搜索、快捷启动、个性化工作台、键盘优先、可撤销 |
| P4 | **控制平面化**：AI/集成/术语/API/通知全部后台可配 |
| P5 | **自检内建**：安装后与持续运行均可一键体检 |
| P6 | **孪生可视前列**：船队/航次/港口三维或高级 2.5D + 实时图层为标配能力 |
| P7 | **规模自适应**：一人公司与跨国船东同一产品，体验按规模/角色裁剪密度而非砍功能 |
| P8 | **迁入/备份极简**：迁移、备份、恢复操作简单；能自动化/AI 化的一律自动化；人只做勾选与总把关 |

### 0.3 模块完成定义（Module DoD）— 全部模块适用

- [ ] 功能清单 100% 实现（本章该模块节）  
- [ ] 状态机合法迁移 + 非法迁移测试  
- [ ] 主路径 + ≥5 条异常路径 UAT  
- [ ] 租户隔离 / 许可证门禁 / RBAC 测试通过  
- [ ] OpenAPI 路由注册 + 契约测试  
- [ ] 若有外部依赖：连接器实例可配置、可 Test  
- [ ] 若有 AI：Skill 注册并走 AI Hub  
- [ ] 术语键覆盖用户可见标签  
- [ ] 自检项注册到 SelfCheck  
- [ ] 审计日志覆盖关键写操作  
- [ ] 空/错/载/离线/权限不足五态齐全  
- [ ] 性能：列表虚拟滚动；关键计算有预算  

### 0.4 工程交付节奏说明（不是功能裁剪）

允许 **按依赖分波次合入主干**，但每一波交付的是**完整模块闭环**，禁止「半截估算」「只读发票」。路线图是施工序，不是产品缩水。

---

## 1. 产品愿景与竞争策略

**VoyageOS** = 航运商业操作系统：从市场机会 → 估算 → 租约 → 航次执行 → 滞期/索赔 → 燃油 → 财务结算 → 联营池/风险 → 合规排放 → 孪生决策，全链路数字化。

| 维度 | 目标 |
| --- | --- |
| 能力广度 | IMOS 级商业模块全集 + 邮件原生 + 多 AI + 自助集成 + 数字孪生 |
| 易用性 | Windows 级：搜索即达、工作台个性化、少培训上手 |
| 集成 | Integration Hub 自助，少依赖 PS |
| API | 完整 API 管理框架 |
| 可视化 | 行业前列的 Fleet/Voyage Digital Twin |
| 质量 | 内建自检 + 自动化回归金样例 |
| 数据 | 短期承认积累落后；用开放灌数与连接器追赶 |

---

## 2. 用户规模 × 角色：极致便捷模型

### 2.1 组织规模档位（Tenant Profile）

| 档位 | 画像 | 体验策略 |
| --- | --- | --- |
| **S** Solo / 微型企业 | 1–5 人，一人多角 | 默认「精简导航」；工作台预置「今日待办+邮件+估算」；向导强引导；隐藏企业级复杂度入口到「高级」 |
| **M** 中型 Operator | 6–50 人，角色分工 | 标准导航；角色工作台模板；审批流开启 |
| **L** 大型船东/管理公司 | 50+，多公司多船队 | 全密度；字段级权限；多公司切换；大屏孪生；API/Webhook 重度 |
| **E** 企业集团 | 多租户/多区域 | 平台超管；区域部署；数据驻留；连接器市场 |

租户档位可配置，影响：**默认工作台模板、导航密度、是否显示高级字段、报表默认可视化级别**。不删除功能，只改变「默认可见与路径长度」。

### 2.2 角色与日常「三键到达」

每个角色必须满足：**≤3 次点击或 1 次全局搜索**到达今日主任务。

| 角色 | 今日主任务 | 默认工作台小组件 | 全局关键字示例 |
| --- | --- | --- | --- |
| Chartering | 估算/谈判/定约 | 机会管道、估算草稿、邮件 Recap | `est` `recap` `CP` |
| Operations | 航次异常与港口任务 | 在航列表、ETA 风险、任务 | `voy` `NOR` `SOF` |
| Demurrage | 滞期计算与时效 | Laytime 待定稿、time-bar | `laytime` `SOF` |
| Finance | 开票收款对账 | 应收账龄、待审批发票 | `inv` `AR` |
| Bunker | 加油与 ROB | 计划、报价、ROB 预警 | `bunker` `ROB` |
| Pool Manager | 池分配 | 池点、月结 | `pool` |
| Risk | 敞口 | FFA、限额 | `FFA` `VaR` |
| Compliance | 制裁命中 | 待审命中 | `sanction` |
| Management | 决策 | TCE、利用率、孪生大屏 | `TCE` `fleet` |
| Tenant Admin | 健康与集成 | SelfCheck、连接器、**迁入/备份** | `health` `migrate` `backup` |
| Platform Admin | 租户与许可 | 租户列表、许可证 | `tenant` `license` |

### 2.3 跨环节「用户旅程」必须写清的触点

每个闭环在 UI 上必须有：

1. **发现**（工作台/搜索/邮件建议）  
2. **办理**（主表单/计算器）  
3. **协同**（评论/@、邮件外发、审批）  
4. **确认**（定稿/过账）  
5. **回看**（时间线/审计/报表/孪生）  

禁止只有「菜单里有个列表」而无发现与回看。

---

## 3. VoyageOS Shell — Windows 级操作体验（P0，最先做）

### 3.1 设计隐喻

| Windows 概念 | VoyageOS |
| --- | --- |
| 开始菜单 | **App Launcher**（模块/页面/操作/最近） |
| 任务栏 | **收藏钉选 + 运行中上下文**（打开的航次/估算） |
| 搜索（Win+S） | **Command Palette / OmniSearch**（`Ctrl+K` / `Ctrl+Space`） |
| 桌面 | **个性化工作台 Home** |
| 设置 | **Settings 控制平面** |
| 文件资源管理器 | **全局实体搜索 + 最近文件/附件** |
| 通知中心 | **Notification Center** |
| 多桌面 | **已保存视图 / 工作区 Workspace**（按角色） |

### 3.2 OmniSearch / 快捷入口（强制）

**触发**：`Ctrl+K`（Mac：`Cmd+K`）。  
**可搜类型**：

- 导航页面与动作（新建估算、定稿 Laytime…）  
- 业务实体（Voyage No、IMO、Invoice No、对方名称）  
- 邮件线程  
- 术语与帮助  
- 系统命令（Run SelfCheck、Switch Company、Switch Language）  
- AI 提问入口（前缀 `?` 或 `ask:`）  

**行为**：拼音/缩写/别名；最近优先；权限过滤；键盘上下选择；Enter 跳转；`Ctrl+Enter` 后台打开。  
**配置**：租户可维护「关键字别名表」；用户可自定义缩写。

### 3.3 个性化工作台（Home）

- 拖拽网格布局；密度随租户档位默认不同  
- 小组件目录：KPI、任务、邮件待复核、地图孪生缩略、审批、连接器健康、AI 用量、自定义报表卡  
- 每角色系统模板 + 用户覆盖；可「重置为角色默认」  
- 支持多工作区：`Chartering Day` / `Ops Night` 一键切换  

### 3.4 全局交互公约

- 一致反馈 ≤100ms；危险操作可撤销（5s）或明确不可逆  
- 键盘：列表 `j/k`、详情 `e` 编辑、`Esc` 关闭  
- 就地编辑 + 自动保存草稿  
- 右键上下文菜单（实体级动作）  
- 深浅色、密度、语言、时区在壳层一处设置  

### 3.5 响应式与大屏

- 桌面 Shell 完整；平板折叠导航；手机底部 Tab（角色可配）  
- **Situation Room** 大屏模式：孪生 + KPI，自动刷新，退出需确认  

---

## 4. 完整模块清单（对标 IMOS+，必须全部开发）

> 许可证可关闭销售，**研发不得省略**。括号内为模块代码。

### 4.1 平台与壳层

| 模块 | 代码 | 闭环要点 |
| --- | --- | --- |
| Shell / UX OS | `shell` | 搜索、工作台、通知、工作区 |
| 认证与安全 | `identity` | 登录、SSO、MFA、会话 |
| 租户与公司 | `tenancy` | 租户生命周期、多公司 |
| 许可证 | `license` | 模块激活门禁 |
| 用户权限 | `rbac` | 角色、字段级权限 |
| AI Hub | `ai` | 多模型场景 |
| Integration Hub | `integration` | 连接器 |
| API Management | `apim` | 密钥/Webhook/OpenAPI |
| i18n & 术语 | `i18n` | 语言包+术语库 |
| 通知 | `notify` | 多通道 |
| 审计 | `audit` | 全量审计查询 |
| 自检 | `selfcheck` | 安装/定时/一键体检 |
| **数据运维** | **`dataops`** | **迁入向导、备份、恢复、演练** |
| 附件与文档 | `docs` | 版本、预览、权限 |
| 工作流引擎 | `workflow` | 审批可配 |

### 4.2 主数据与数据中心

| 模块 | 代码 | 闭环要点 |
| --- | --- | --- |
| 船舶 | `vessel` | 档案、油耗曲线、证书摘要（商业相关） |
| 港口/运河/航线 | `geo` | UN/LOCODE、时区、距离 |
| 对手方 | `party` | KYC 字段、制裁状态 |
| 货物 | `cargo` | 货种、危险品标记 |
| 市场数据 | `market` | 油价、汇率、指数入库 |
| 数据质量 | `dq` | 规则、异常工单 |

### 4.3 商业核心（IMOS 对标主干）

| 模块 | 代码 | 闭环要点 |
| --- | --- | --- |
| 航次估算 | `estimate` | 多方案、敏感度、转租约 |
| 租船/合同 | `chartering` | 程租/期租/光租/COA/TCT、审批、制裁阻断 |
| 船队调度 | `scheduling` | 船期占用、冲突检测 |
| 航次操作 | `operations` | 挂靠港、任务、指令、午报 |
| NOR/SOF | `portcall` | 时间事实、时区 |
| 港口使费 DA | `portcost` | PDA/FDA、审批、归集航次 |
| 燃油 | `bunker` | 计划、询比价、BDN、ROB、分摊 |
| Laytime/滞期 | `laytime` | 全条款计算、定稿、导出 |
| 索赔 | `claims` | 立案、谈判、和解、时效 |
| 财务业务 | `finance` | 运费/租金/滞期/燃油发票、收付款、账龄、红冲 |
| 总账接口 | `gl` | 科目映射、过账连接器 |
| 联营池 | `pooling` | 入退池、池点、分配、结算 |
| 交易与风险 | `risk` | FFA/头寸、敞口、VaR、限额 |
| 排放合规 | `emissions` | CII、EU ETS、FuelEU 数据与报告 |
| 轻载/过驳等专项 | `specialops` | lightering 等可配置专项流程 |
| 泊位计划 | `berth` | 泊位窗口（可许可证） |
| 报表与分析 | `analytics` | 标准+自定义+订阅 |
| 邮件 | `email` | 入站出站、抽取、归档 |
| 数字孪生 | `twin` | 船队/航次/港口可视与回放 |
| 对手方门户 | `portal` | 发票确认、有限协同（完整开发） |

### 4.4 模块完备性核对（相对公开 IMOS/同类能力）

| 能力域 | 必须具备 |
| --- | --- |
| Pre-fixture | 估算、what-if、船货匹配、模板 |
| Contracting | 多租约类型、COA liftings、条款库 |
| Operations | 航次执行、调度、午报、异常管理 |
| Bunker | 全生命周期 ROB 守恒 |
| Port costs | PDA/FDA 闭环 |
| Laytime/Claims | 复杂条款 + 索赔时效 |
| Accounting | 航次 P&L、结算、GL 过账 |
| Pooling | 贡献、分配、现金结算 |
| Risk | 敞口与限额 |
| Compliance | 制裁 + 排放 |
| Ecosystem | API、邮件、AI、孪生、门户 |

缺一即视为规格未完成。

---

## 5. 端到端业务闭环（完整逻辑，必须实现）

### 5.1 主闭环（商业主链）

```
机会/询盘(邮件AI)
  → Estimate(多方案/TCE) → 审批可选
  → Charter Party(制裁筛查→审批→生效)
  → Schedule 占船 → Voyage 生成
  → Operations(任务/指令) + Twin 跟踪
  → Port Call(NOR/SOF) + Port Cost(PDA/FDA)
  → Bunker(补给/消耗/ROB)
  → Laytime 定稿 → Claims(如需要)
  → Finance 开票/收款/付款 → GL 过账
  → Voyage P&L 锁定 → Analytics / Twin 回放
  → (可选) Pooling 贡献分配 → 结算
```

任一箭头断裂 = 缺陷。每个节点有：状态、责任角色、单据号、审计、可从 OmniSearch 打开。

### 5.2 开发依赖序（施工序，非砍功能）

```
Wave 0  Shell + Identity + Tenancy + License + RBAC + i18n + SelfCheck骨架 + APIM骨架 + **DataOps备份/恢复骨架**
Wave 1  Masterdata + Workflow + Docs + Notify + Email基础 + AI Hub骨架 + Integration骨架 + **AI迁入向导骨架（连接源+分析队列）**
Wave 2  Estimate + Chartering + Scheduling
Wave 3  Operations + PortCall + Twin基础地图
Wave 4  Laytime + Claims + PortCost
Wave 5  Bunker + Finance + GL接口
Wave 6  Market/DQ + Emissions + Analytics
Wave 7  Pooling + Risk + Berth + SpecialOps + Portal
Wave 8  Twin高级(回放/3D/大屏) + SelfCheck完备 + **DataOps迁入全源适配完备** + 性能加固
```

每波结束必须跑该波 SelfCheck 套件 + 回归金样例。

### 5.3 关键子闭环（规格级要求）

**估算闭环**：输入校验 → 计算引擎 → 版本 → 对比 → 导出 → 一键生成 CP 草稿 → 反写关联。  
**租约闭环**：草稿 → 制裁 → 审批 → 生效 → 生成航次/调度占用 → 修订用变更单 → 完成/取消。  
**操作闭环**：计划 → 在航 → 港口事件 → 午报偏差告警 → 完航。  
**滞期闭环**：SOF/NOR → 条款包 → 计算 → 争议标记 → 定稿 → 生成发票/索赔。  
**燃油闭环**：需求 → 询价(邮件) → 订单 → BDN → ROB 滚动 → 成本入航次。  
**财务闭环**：应计 → 发票 → 审批 → 发送 → 收款匹配 → 账龄 → 红冲 → GL。  
**联营池闭环**：入池规则 → 航次贡献 → 月分配 → 结算单 → 伙伴共享。  
**风险闭环**：头寸录入 → 行情连接器 → 敞口 → 限额预警 → 对冲建议(AI 可选)。  
**邮件闭环**：同步 → 解析 → 复核 → 落库 → 外发模板 → 归档。  
**孪生闭环**：AIS/午报/航次计划 → 场景融合 → 告警 → 用户处置回写业务。

### 5.4 状态机（实现必须编码强制）

状态机（实现必须编码强制）至少覆盖：`charter`、`voyage`、`invoice`、`claim`、`email.parse`、`license`、`connector`、`laytime`、`bunker_order`、`pda/fda`、`pool_period`。  
非法迁移 API 返回 `409 INVALID_STATE`；UI 禁用非法按钮。

---

## 6. 各模块功能规格（开发清单级）

> 下列为**必须实现**的功能点；细节公式见第 11 章与既有 calc 口径。UI 均挂 Shell，支持搜索与工作台组件。

### 6.1 Estimate

- 程租/期租机会成本模式；多腿港口；包干运费/单价；多燃油牌号  
- 模板、克隆、版本、敏感度（运价/油价/航速）、≥10 方案对比  
- AI：假设建议、TCE 解读（Hub）  
- 连接器：距离、油价、指数  
- 输出：PDF/Excel；转 CP  

### 6.2 Chartering

- 类型：voyage / time / bareboat / coa / tct  
- 条款库、laycan、佣金、支付计划、仲裁/法律  
- COA：liftings 计划与实际  
- 审批流、附件、邮件归档、续租/laycan 提醒  
- 制裁阻断激活  

### 6.3 Scheduling

- 船期甘特；硬/软冲突；维修/Off-hire 占档  
- 与航次双向同步；拖拽改期（权限+审计）  

### 6.4 Operations & PortCall

- 航次挂靠港顺序、代理、指令、任务 SLA  
- NOR/SOF 时区；午报；ETA 偏差；文件柜  
- 邮件解析落库；AI 午报/SOF  

### 6.5 Port Cost

- PDA 预估 → 审批 → FDA 实际 → 差异分析 → 进入航次成本  
- 连接器：DA 网络类；无连接器时可手工  

### 6.6 Bunker

- 计划、询比价、订单、BDN/BDR、质量、ROB 守恒、航次分摊  
- 价格指数连接器；AI 解析 BDR  

### 6.7 Laytime & Claims

- 允许时间（固定/定额）、turn time、SHEX/SHINC、除外、可逆/合并（全支持）  
- 定稿锁定 details；导出计算书  
- 索赔：立案、函稿 AI、时效、和解、与发票联动  

### 6.8 Finance & GL

- 多类型发票、多币种、税、审批、发送、收付款、部分核销、账龄、红冲  
- 航次 P&L；应计；科目/成本中心映射；会计连接器过账  
- AI：水单匹配、供应商发票抽取  

### 6.9 Pooling

- 池定义、船舶入退、Vessel Points、Off-hire、月分配、现金结算、伙伴报表  

### 6.10 Risk

- 交易、头寸、行情、敞口、VaR（可插拔模型）、限额、预警、对冲工作流  

### 6.11 Emissions

- 航次油耗归集；CII 指标；EU ETS / FuelEU 数据导出与连接器；审计轨迹  

### 6.12 Email / AI / Integration / APIM / i18n

- 见第 7 章控制平面；本 DDS 要求**全部场景与连接器目录进入产品**，按 Wave 接入但规格预留齐全  

### 6.13 Analytics

- 标准报表：TCE、航次利润、利用率、账龄、滞期、燃油、排放、池、风险  
- 自定义报表构建器；订阅；下钻；导出  
- 叙事 AI 可选  

### 6.14 Portal

- 对手方只读/确认发票、上传文档、有限消息；强租户隔离  

---

## 7. 平台控制平面（内嵌摘要）

后台 Settings 必须包含：Organization、Security/SSO、Licenses、**AI Hub**、**Integration Hub**、**API Management**、**Languages & Terminology**、Notifications、Retention、Feature Flags、**SelfCheck**、**DataOps（Migrate / Backup / Restore）**。  

铁律：无硬编码第三方；密钥 KMS；Test/健康/审计齐全。  
AI Skill 与连接器目录在 Settings 中建完整注册表（类型码全集入库）；未实现适配器显示 `adapter_pending`，避免遗漏。

---

## 7A. DataOps：迁移 / 备份 / 恢复 / AI 迁入（必须完整开发）

> **产品承诺**：从「邮件 + 公共文件夹 + Excel」转到 VoyageOS，用户主要做**连接 → 等待分析 → 勾选确认 → 少量总览性输入**；不做逐行手工建档。  
> **人机分工**：AI/规则负责发现、分类、抽取、去重、建议建档；**建档生效与总把关以人为主**（批量勾选即可）。

### 7A.1 设计原则

| # | 原则 |
| --- | --- |
| D1 | **一股脑连接**：一次向导可挂接多种源（O365/IMAP、PST、SharePoint/文件库、本地/网络文件夹、Excel/CSV 包） |
| D2 | **先分析后落库**：默认只生成「建议草案」，确认后才写入业务表 |
| D3 | **勾选式确认**：按实体类型批量 Accept / Reject / Merge；支持「全部接受高置信度」 |
| D4 | **可追溯**：每条生成数据保留 `source_uri`、抽取片段、模型/规则版本、操作者 |
| D5 | **可重跑**：增量再扫描；已确认项不重复骚扰（指纹去重） |
| D6 | **备份恢复同样简单**：一键备份、一键恢复、定期策略、演练模式；能自动的自动 |
| D7 | **失败友善**：单文件失败不阻断整批；报告可下载；可仅重试失败项 |

### 7A.2 用户体验（极简剧本）

```
1. Settings → DataOps → Migrate →「开始迁入」
2. 勾选数据源并授权/上传：
   - Microsoft 365（邮件 + OneDrive/SharePoint）
   - PST / OST 存档文件
   - IMAP/Exchange 邮箱
   - 公共/共享文件夹、文档库
   - Excel/CSV 工作簿包（船舶、对方、航次台账等）
3. 可选：填 3～5 个总览项（公司本位币、默认船队、主要贸易区域、时区、起始业务年）
4. 系统自动：扫描 → 分类 → 抽取 → 聚类成「建议实体」
5. 复核台：按船舶/对方/租约/航次/发票… 分组列表
   - 置信度色标；AI 给出推荐动作（新建 / 合并到已有 / 忽略）
   - 用户主要：☑ 勾选 + 偶尔改下拉合并目标
6. 「应用已选」→ 写入系统；生成迁入报告；SelfCheck 跑迁入后探针
```

**禁止**：要求用户先学完数据模型再填几十张导入模板才能开工（模板导入仅作高级附加，不是主路径）。

### 7A.3 迁入源适配器（Connection Sources）

| source_type | 说明 | 能力 |
| --- | --- | --- |
| `m365_mail` | Microsoft Graph 邮箱 | 文件夹选择、历史区间、附件 |
| `m365_files` | OneDrive / SharePoint 库 | 站点/库/路径、文件类型过滤 |
| `pst` | Outlook PST 上传或路径挂载 | 解析邮件/文件夹/附件（服务端解析组件） |
| `imap` | 通用 IMAP | 与邮件模块账号复用或只读迁入专用 |
| `smb_folder` / `local_folder` | 公共盘/本地目录 | 递归扫描 xlsx/csv/pdf/msg/eml |
| `excel_pack` | 多表工作簿 | 表头 AI 映射到实体字段 |
| `zip_bundle` | 打包迁入 | 内含上述混合 |

均走 Integration Hub 凭证与健康检查；PST 大文件支持分片上传 + 断点续传。

### 7A.4 AI / 规则分析流水线

```
Ingest(原始对象)
  → Fingerprint(去重)
  → Classify(邮件类型/文件类型/台账表类型)          [Skill: migrate.classify]
  → Extract(结构化候选字段)                        [Skill: migrate.extract.*]
  → EntityResolve(与已有主数据模糊匹配)            [规则 + embedding]
  → Cluster(同一航次/同一 CP 的证据归并)
  → Propose(建议：create/merge/skip + 置信度)
  → HumanReview(勾选台)
  → Commit(事务写入 + 审计 + 源链接)
```

**Skill 注册（必须）**：`migrate.classify`、`migrate.extract.recap`、`migrate.extract.nor_sof`、`migrate.extract.invoice`、`migrate.extract.bunker`、`migrate.map.excel_headers`、`migrate.suggest.merge`、`migrate.summarize.batch`（整批总览叙事，辅助总把关）。

### 7A.5 可建议生成的实体（完整产品范围）

主数据：船舶、港口（匹配 UN/LOCODE）、对手方、货物、公司抬头。  
商业：估算草稿（若有足够证据）、租约/Recap、航次、挂靠港、NOR/SOF 事件、Laytime 草稿、索赔线索、加油记录、发票/付款线索、DA/使费单据、邮件线程归档与实体链接。  

低置信度默认**不自动勾选**；≥ 配置阈值（默认 0.9）可一键「全选高置信」。

### 7A.6 复核台 UX（人只做勾勾选选）

- 左侧：实体类型与数量、置信度分布  
- 中间：建议列表（复选框、推荐动作、关键字段预览、证据条数）  
- 右侧：证据抽屉（原邮件/Excel 行/文件预览、高亮抽取）  
- 顶部批量：接受推荐 / 全部跳过低置信 / 按对方过滤  
- 冲突：同名船舶 IMO 不同 → 强制人选集；不得静默覆盖  
- 总把关页：迁入前后数量对比、风险提示（制裁命中候选、币种缺失）、一键生成「待补全清单」

### 7A.7 备份（Backup）

| 能力 | 要求 |
| --- | --- |
| 一键备份 | UI + CLI/脚本同一引擎；OmniSearch：`backup` |
| 内容 | Postgres 逻辑备份 + 对象存储桶（附件/邮件原文）+ 配置快照（无明文密钥，仅 secret_ref） |
| 策略 | 手动；定时（日/周）；保留份数；异地目标（第二 S3）可选 |
| 自动 | 大版本升级前自动备份；迁入 Commit 前可选自动快照 |
| 状态 | 进度、大小、校验和、成功/失败通知 |
| AI（可选） | `dataops.explain.backup_diff`：两份备份差异摘要（表级/桶级） |

### 7A.8 恢复（Restore）

| 能力 | 要求 |
| --- | --- |
| 一键恢复 | 选择备份点 → 确认 → 恢复；生产需二次确认码 |
| 模式 | **整租户恢复**；**演练恢复**到隔离沙箱租户（推荐先演练） |
| 粒度 | 须支持按模块/时间范围部分恢复（完整产品能力） |
| 校验 | 恢复后自动跑 SelfCheck + 行数探针 + 抽样打开单据 |
| 回滚 | 恢复前自动再打一份「恢复前快照」 |

### 7A.9 与传统工具的对照承诺

| 传统方式 | VoyageOS DataOps |
| --- | --- |
| 手工整理 Excel 再导入 | Excel 包丢进向导，AI 映射表头，勾选建档 |
| 多年 PST / 邮箱人工翻找 | 连接 O365/PST，自动分类抽取，证据可点开 |
| 公共盘无人认领文件 | 扫描文档库，归并到航次/对方建议 |
| 备份靠 IT 脚本 | 租户管理员可自助备份/恢复/演练 |
| 迁系统靠顾问驻场数月 | 自助为主，顾问只处理例外冲突 |

### 7A.10 数据模型（纲要）

```text
migration_jobs
migration_sources
migration_artifacts
migration_proposals
migration_proposal_evidence
migration_commits
backup_jobs / backup_objects
restore_jobs
```

### 7A.11 API（节选）

- `POST /settings/dataops/migrations` 创建作业  
- `POST /settings/dataops/migrations/:id/sources` 添加源  
- `POST /settings/dataops/migrations/:id/run-analyze` 开始分析  
- `GET /settings/dataops/migrations/:id/proposals` 建议列表  
- `POST /settings/dataops/migrations/:id/commit` 提交勾选  
- `POST /settings/dataops/backups` / `POST .../restore`  
- OmniSearch 命令：`migrate`、`backup`、`restore`

### 7A.12 安全与合规

- 迁入源只读优先；写回外部系统默认关闭  
- PST/邮箱内容加密存储；权限仅 Admin + 被授权迁入员  
- 制裁：对手方建议在 Commit 前跑筛查，命中则默认不勾选并标红  
- 审计：谁接受了哪条建议、何时  

### 7A.13 验收

- [ ] O365 或 IMAP + 一份 PST + 一个 Excel 包 + 一个文件夹，单次向导可完成分析  
- [ ] 用户在不手建主数据的情况下，仅靠勾选生成船舶/对方/至少一类业务单据草案并成功 Commit  
- [ ] 高置信一键全选；低置信默认不选  
- [ ] 一键备份与演练恢复成功；恢复后 SelfCheck 绿  
- [ ] 大文件分片上传可断点续传；单票失败可重试  
- [ ] 全程可从 OmniSearch 唤起  

---

## 8. 多语言与术语库

- 默认 `en`；至少 `en` + `zh-CN` 完整；架构支持续加语言  
- UI / Email / PDF / API error / Notification 全走 i18n  
- **Terminology** 一等公民：≥500 条核心航运术语（交付标准），租户可覆盖，审批流，AI 辅助翻译须人工确认  
- PDF 计算书/发票标签必须引用术语键  

---

## 9. 数字孪生与可视化（行业前列目标）

### 9.1 能力分层

| 层级 | 能力 | 要求 |
| --- | --- | --- |
| L1 态势 | 全球/区域船队地图、航次轨迹、港口聚合 | 实时 AIS + 计划航线叠加 |
| L2 航次孪生 | 单船时间轴：计划 vs 实际、港口事件、燃油、气象层 | 可回放 |
| L3 运营孪生 | 船期甘特与地图联动；冲突高亮 | 与 Scheduling 一体 |
| L4 决策孪生 | what-if：改航速/港口对 TCE/排放影响预览 | 调用 Estimate 引擎 |
| L5 沉浸 | 3D/2.5D 港口或船舶模型（渐进增强） | 性能可降级到 L1–L4 |

### 9.2 体验与性能

- Home 可嵌「孪生微件」；Situation Room 全屏  
- 图层：AIS、天气、制裁风险区、运河、排放控制区  
- 告警点击跳转业务单据（三键内）  
- 大数据量：聚合、LOD、轨迹抽稀；弱网降级  
- 视觉规范纳入设计令牌；无障碍提供表格式替代视图  

### 9.3 数据融合

优先级：AIS 连接器 > 午报 > 用户手工。冲突显示置信度并记 DQ。  

---

## 10. 自测试 / 自检系统（SelfCheck）— 必须具备

### 10.1 形态

1. **安装后向导体检**：DB/Redis/存储/邮件/AI/关键连接器  
2. **一键 Run SelfCheck**（OmniSearch 可调）  
3. **定时巡检** + 失败通知 Admin  
4. **CI 同源规则**：尽可能同一检查库  

### 10.2 检查类别

| 类别 | 示例 |
| --- | --- |
| Infra | 迁移版本、磁盘、备份新鲜度、证书过期 |
| Security | 默认密码、DEV_UNLOCK 关闭、TLS |
| Tenancy | 隔离抽样探针 |
| License | 核心模块许可状态 |
| Data | ROB 守恒抽样、孤儿单据、汇率缺口 |
| Calc | 金样例 TCE/Laytime 回归 |
| Integration | 连接器 health、Webhook 失败率 |
| AI | Provider 可达、Skill 绑定完整 |
| UX | 关键页面 TTI 探针（可选合成监控） |
| Twin | AIS 延迟、轨迹空洞 |

### 10.3 输出

- 分数 + 红黄绿；一键导出报告；修复深链到 Settings  
- 所有检查项代码化：`checks/*.py` 注册制  

### 10.4 自动化测试金字塔（研发强制）

- 单元：计算引擎 100% 金样例  
- 契约：OpenAPI  
- 集成：租户隔离套件  
- E2E：主闭环 Playwright/等价  
- 视觉：Chromatic 核心壳层  
- 性能：列表 1 万行、孪生 500 船压力基线  

---

## 11. 计算与业务规则（摘要）

- **TCE / voyage_cost**：`voyage_cost` 不含日租金；`TCE = (总收入 - voyage_cost) / 总航次天数`  
- **Laytime**：全条款；时间 UTC 存、港口时区显  
- **ROB**：期初+加油-消耗=期末，差异超阈告警  
- **P&L**：收入−直接成本；锁定策略可配  
- 规则变更必须：用例 + 版本号 + 业务签字字段  

金样例库存放 `fixtures/calc/**`，SelfCheck 与 CI 共用。

---

## 12. 技术架构（完整系统，仍保持可单机运行）

### 12.1 形态

**模块化单体 + 清晰模块边界**（默认）。规模化后再拆 worker/只读副本。  
禁止一上来微服务拆分。

### 12.2 栈

- Web：Next.js + TS + Tailwind + Radix + 地图/WebGL（孪生）  
- API：Python FastAPI  
- DB：PostgreSQL；Cache/Queue：Redis；Object：S3/MinIO  
- 搜索：初期 PG FTS + OmniSearch；可上 OpenSearch  
- 监控：OTel + Sentry；单机先日志+SelfCheck  

### 12.3 部署 Stage A/B/C

部署拓扑：单机 Compose（Stage A）→ 多机（Stage B）→ 多云（Stage C）。完整功能必须在 Stage A 可跑（孪生可降级图层）。

### 12.4 仓库结构

```
voyageos/
  apps/web          # Shell + 各模块前端包
  apps/api          # FastAPI 宿主
  modules/*         # 业务与平台模块
  packages/core     # 租户/许可/AI/连接器端口
  packages/calc
  packages/ui
  packages/twin     # 孪生渲染与数据融合
  checks/           # SelfCheck 注册
  fixtures/         # 金样例
  deploy/compose
  docs/             # 本 DDS 与 OpenAPI
```

### 12.5 编码约束

- 禁止业务 `httpx` 直连外网  
- 所有路由声明 `module` + `scopes`  
- 用户可见字符串禁止硬编码（i18n/术语）  
- 本地时间展示、UTC 存储  

---

## 13. 数据模型纲要

核心业务表之外，必须补齐：

- 调度：`vessel_schedule_blocks`  
- 港口使费：`port_disbursements`、`port_disbursement_lines`  
- 燃油订单：`bunker_orders`、`bunker_order_lines`  
- COA：`coa_liftings`  
- 池：`pools`、`pool_vessels`、`pool_distributions`  
- 风险：`risk_trades`、`risk_positions`、`risk_limits`  
- 排放：`emission_records`、`emission_reports`  
- 孪生：`twin_snapshots`、`twin_alerts`  
- 工作台：`user_home_layouts`、`user_shortcuts`、`search_aliases`  
- 自检：`selfcheck_runs`、`selfcheck_results`  
- 控制平面表：`ai_*`、`connector_*`、`terminology_*`、`api_keys`、`webhooks`、`selfcheck_*`、`user_home_layouts`、`search_aliases`、`migration_*`、`backup_*`、`restore_*` 等  

`docs/ddl.sql` 为唯一执行源；本文为纲要。

---

## 14. API 与事件

- 全部业务 REST 进 `/api/v1`，OpenAPI 强制  
- 管理面：`/settings/*`、`/platform/*`  
- 事件出站：`estimate.finalized`、`charter.activated`、`voyage.completed`、`laytime.finalized`、`invoice.approved`、`payment.reconciled`、`bunker.delivered`、`pool.distributed`、`sanctions.hit`、`twin.alert.raised`…  
- Webhook HMAC + 重试 + 投递日志  
- 幂等键写操作强制  

---

## 15. 安全与合规

- SSO/MFA、RBAC、字段级权限、租户隔离 CI  
- 制裁筛查触发点：对手方保存、租约激活、付款前  
- 审计不可篡改存储策略  
- GDPR 等：导出/删除请求工作流  

---

## 16. 非功能

| 项 | 指标 |
| --- | --- |
| OmniSearch | P95 < 300ms（本地索引热数据） |
| 首屏 Shell | TTI < 2s |
| 估算 | < 5s |
| 孪生 200 船 | 交互 60fps 目标，可降级 |
| 可用性 | 多机 99.9%；单机尽力 |
| 可访问 | WCAG 2.2 AA 核心路径 |
| 浏览器 | 近两年版本 |

---

## 17. UX 文案与帮助

- 默认 English；角色首次进入 3 步引导可跳过  
- 上下文 `?` 帮助绑定术语定义  
- 空状态提供「用示例数据体验闭环」开关（仅非生产或显式确认）  

---

## 18. 质量门禁（合并前）

- SelfCheck 套件绿  
- 租户隔离绿  
- 计算金样例绿  
- OpenAPI diff 无未声明路由  
- 模块 DoD 勾选  
- 无高危安全扫描  

---

## 19. 团队建议（完整产品）

架构 1、后端 4–6、前端 3–5、孪生/可视化 1–2、QA 2、设计 1–2、业务专家兼职、平台/集成 1–2。  
并行 Wave，但 Shell 与平台内核不可跳过。

---

## 20. 风险

| 风险 | 应对 |
| --- | --- |
| 迁入质量差/幻觉 | 先分析后落库；低置信默认不勾选；证据抽屉强制可追溯 |
| 庞大导致难用 | Shell+OmniSearch+角色工作台优先于深功能堆砌 |
| 范围失控 | 模块 DoD + 目录制；许可证销售裁剪不等于研发裁剪 |
| 孪生性能 | LOD/降级；L5 增强可选 |
| 数据积累 | 开放灌数；不假装拥有 IMOS 级历史网络 |
| 闭环断裂 | 主链 E2E 每日构建 |

---

## 21. 附录 A — OmniSearch 命令注册表示例

```yaml
- id: nav.estimate.new
  title: New Estimate
  keywords: [est, estimate, tce]
  module: estimate
  action: route:/estimates/new
- id: cmd.selfcheck.run
  title: Run SelfCheck
  keywords: [health, selfcheck, diagnose]
  module: selfcheck
  action: command:selfcheck.run
- id: cmd.migrate
  title: Start Migration
  keywords: [migrate, import, pst, o365, excel]
  module: dataops
  action: route:/settings/dataops/migrate
- id: cmd.backup
  title: Backup Now
  keywords: [backup, snapshot]
  module: dataops
  action: command:dataops.backup
- id: ent.voyage
  title: Open Voyage
  type: entity
  module: operations
  resolver: voyage_no_or_id
```

## 22. 附录 B — 工作台小组件目录（节选）

`kpi.tce_mtd`、`tasks.my_open`、`email.review_queue`、`twin.fleet_mini`、`finance.ar_aging`、`integration.health`、`ai.budget`、`laytime.due_finalize`、`approvals.pending`

## 23. 附录 C — SelfCheck 注册示例

```python
@check(id="calc.tce_gold", severity="blocker")
def check_tce_gold():
    assert run_gold_suite("fixtures/calc/tce") == 0

@check(id="sec.dev_unlock_off", severity="blocker", env="prod")
def check_dev_unlock():
    assert os.getenv("LICENSE_DEV_UNLOCK") in (None, "", "0")
```

## 24. 附录 D — 设计令牌与 i18n

- 字体：Ubuntu + IBM Plex Sans + Noto CJK（按 locale）  
- `defaultLocale: en`  
- 详细色板/间距沿用既有 design-tokens  

## 25. 附录 E — 关联文档

| 文档 | 用途 |
| --- | --- |
| 本 DDS V2.1 | **开发唯一 SSOT** |
| `docs/openapi.yaml` | 生成自代码，CI 校验 |
| `docs/ddl.sql` | 唯一库结构（由本规格落地） |
| `docs/deploy.md` | 安装备份恢复（由本规格落地） |
| `docs/modules.md` | 模块许可证与依赖（由本规格落地） |

---

## 26. 验收总册（产品完整交付）

- [ ] 第 4 章模块清单全部达到 Module DoD  
- [ ] 第 5.1 主闭环 E2E 演示通过（含邮件进、财务出、孪生可视）  
- [ ] S/M/L 三档租户体验走查：主任务三键到达  
- [ ] OmniSearch 覆盖导航/实体/命令  
- [ ] 个性化工作台角色模板 + 用户自定义  
- [ ] SelfCheck 安装时+一键+定时  
- [ ] **DataOps**：多源 AI 迁入勾选落库 + 一键备份/演练恢复  
- [ ] Twin L1–L4 达标，L5 可降级  
- [ ] AI Hub ≥2 Provider；控制平面无硬编码密钥  
- [ ] API Management 完整可用  
- [ ] 术语库 ≥500 并驱动 PDF/UI  
- [ ] 计算金样例与隔离套件 CI 绿  
- [ ] 单机 Compose 可完整演示（图层可降级）  

---

## 27. 架构师开工包（Wave 0–2 史诗分解）

> 可直接导入项目管理工具；验收标准 = 对应 Module DoD + SelfCheck。

### Wave 0 — 平台内核与 Shell

| Epic | 交付物 |
| --- | --- |
| W0.1 Compose | `docker-compose.yml`：web/api/postgres/redis/minio；install/backup/restore 脚本 |
| W0.2 Tenancy/Auth | 登录、JWT、租户上下文中间件、RBAC、许可证门禁 |
| W0.3 Shell | 顶栏、侧栏、Home 网格、OmniSearch、通知抽屉、主题/语言 |
| W0.4 i18n | en 默认、zh-CN、术语表 CRUD 骨架 |
| W0.5 APIM | OpenAPI 生成、API Key、Webhook 框架 |
| W0.6 SelfCheck | 注册器 + 安装向导 + 一键运行 UI |
| W0.7 AI/Integration 骨架 | Provider/Connector 表结构 + Test 动作空实现 |
| W0.8 DataOps 骨架 | 备份/恢复引擎 + 迁入作业表结构 + OmniSearch 命令 |

### Wave 1 — 主数据与邮件

| Epic | 交付物 |
| --- | --- |
| W1.1 Masterdata | 船舶/港口/对手方/公司/汇率；制裁字段 |
| W1.2 Workflow/Docs/Notify | 审批引擎、附件、站内+邮件通知 |
| W1.3 Email | 账号同步、线程、规则、复核队列；Skills 接 AI Hub |
| W1.4 工作台模板 | S/M/L 档位 × 角色默认布局 |
| W1.5 AI 迁入向导 | 多源连接 + 分析队列 + 勾选复核台（先通 Excel+IMAP，再 PST/O365） |

### Wave 2 — 估算与租船调度

| Epic | 交付物 |
| --- | --- |
| W2.1 Estimate 引擎+UI | 计算金样例、多方案、导出、转 CP |
| W2.2 Chartering | 五类租约、条款、审批、制裁阻断 |
| W2.3 Scheduling | 甘特、冲突、与航次同步 |
| W2.4 主闭环 E2E | 邮件 Recap→估算→CP→占船 自动化 |

其后 Wave 3–8 按第 5.2 节拆 Epic，规则相同：**一模块一闭环，不做半截功能。**

---

## 28. 角色日常操作剧本（开发验收用）

### 28.1 Chartering（M 档）

1. 登录后工作台见「邮件 Recap 待复核」  
2. `Ctrl+K` 输入对方船名打开线程 → 确认抽取 → 生成 Estimate  
3. 对比三方案 → 送审 → 激活 CP → 自动占船期  
4. 钉选该 CP 到任务栏式「运行中上下文」  

### 28.2 Operations

1. 工作台「ETA 风险」进入航次  
2. 孪生微件查看轨迹偏差 → 创建任务给代理  
3. 录入 NOR/SOF（时区自动）→ 推送 Laytime  

### 28.3 Finance

1. `Ctrl+K` → `AR` 打开账龄  
2. 从滞期定稿一键生成发票 → 审批 → 发送  
3. 付款匹配 AI 建议 → 确认 → GL 过账连接器  

### 28.4 Tenant Admin

1. OmniSearch `health` → Run SelfCheck  
2. 红项深链到连接器轮换密钥  
3. OmniSearch `migrate` → 连接 O365/PST/Excel → 分析完成后勾选高置信建议 → Commit  
4. OmniSearch `backup` → 一键备份；定期策略设为每日  
5. 查看 API 用量与 Webhook 失败重放  

以上剧本必须写入 E2E 测试。

---

**文档结束（DDS V2.1）**

此份说明书已按「完整产品、脱手开发」编写：功能不按 MVP 裁剪；易用性按 Windows 级操作系统设计；质量靠 SelfCheck；可视化靠 Digital Twin；迁入/备份靠 DataOps（AI 分析 + 人勾选把关）；规模与角色靠工作台与搜索适配。  

架构师下一步：基于 Wave 0 建仓与 Compose；导出 `ddl.sql` / OpenAPI 骨架；冻结 Module DoD 检查表为项目管理看板。
