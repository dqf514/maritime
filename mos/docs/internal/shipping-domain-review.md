# 【内部文档】MariOS 航运业务域审查报告 + 计算引擎修复清单

> 审查人视角：干散货/油轮租船、航次估算、滞期费计算、航次执行（对标 Veson IMOS / DA-Desk / Marsoft）。
> 基线代码：`mos/apps/api`（FastAPI + SQLAlchemy）。本报告行号以审查时点代码为准，并行开发可能导致漂移。
> 关联文档：`veson-gap-todo.md`（能力差距跟踪）、DDS V2.1 §5.4/§6/§11。

---

## 第一部分：计算引擎修复清单（本轮已实施）

### 1.1 laytime_engine.py（滞期/速遣引擎）

| 问题 | 修复 | 位置 |
| --- | --- | --- |
| `terms` 仅 `.upper()` 回显，SHINC/SHEX 无语义 | 实现条款策略表 `_TERM_RULES`：SHINC/SSHINC/FHINC 全计入；SHEX/SSHEX 自动剔除周六/周日/节假日；FHEX 剔除周五/节假日；支持 `EIU`（even if used）后缀与事件级 `even_if_used` 标记；未知条款（如 WWD）不再静默忽略，返回 `warnings` 且全部时间计入 | `app/services/laytime_engine.py:25,67` |
| 无节假日支持 | 新增输入 `port_holidays: ["YYYY-MM-DD"]`，SHEX 类条款下节假日整日剔除，SHINC 类计入 | `laytime_engine.py:60(_parse_holidays),83` |
| 无港口时区（DDS §11 要求"UTC 存、港口时区显"） | 新增输入 `port_timezone`（IANA 名，标准库 `zoneinfo`）：naive 事件时间按港口本地时间解释，aware 时间转换到港口时区后判定日界；naive/aware 混用抛带明确信息的 `ValueError`（不再 TypeError 崩溃）；非法时区名抛 `ValueError` | `laytime_engine.py:56(_parse_dt),130-143` |
| `_hours` 先 float 除法再转 Decimal 精度损耗 | 全程 Decimal：`timedelta.days/seconds/microseconds`（均为 int）→ 微秒级 Decimal ÷ 3_600_000_000；aware 时间先归一到 UTC 求真实流逝 | `laytime_engine.py:37(_delta_hours)` |
| 输出缺少审计信息 | 输出新增 `excluded_hours`、`warnings`、`port_timezone`；原 key 全部保留（`terms/allowed_hours/used_hours/balance_hours/result_type/amount/currency` 不变） | `compute_laytime` 返回体 |

行为兼容：调用方已标 `excluded: true` 的事件仍然整条跳过；缺省 `terms` 仍为 SHINC；金样例 `laytime_gold_01`（滞期费 6000.0）与 `test_full_chain.py` 断言不变、全绿。

### 1.2 estimate_engine.py（估算/TCE 引擎）

| 问题 | 修复 | 位置 |
| --- | --- | --- |
| `total_days <= 0` 静默置 1 | 改为抛 `ValueError`，信息含 sea/port/eca/waiting 各项值。**路由层注意**：`routers/commercial.py:204`（calculate）、`routers/commercial.py:267`（to-charter 隐式计算）、`routers/operations.py:362`（twin what-if）目前未捕获 `ValueError`，会冒泡成 500；路由层属其他 agent 范围，需 `try/except ValueError → HTTPException(422)` 包一层（本引擎侧已按约定只抛 `ValueError`） | `app/services/estimate_engine.py:60-68` |
| 敏感度仅支持乘法扰动 | `sensitivity()` 新增 `mode: str = "pct"` 参数：`"pct"` 保持原行为（行内含 `delta_pct` key，向后兼容），`"abs"` 做加减扰动（如 bunker_price ±50 USD/MT，行内含 `delta_abs` key）；非法 mode 抛 `ValueError` | `estimate_engine.py:107-132` |

### 1.3 state_machine.py（DDS §5.4 状态机补齐）

- 新增 `EMAIL_PARSE_TRANSITIONS`（pending/review/parsed/failed/archived，状态值对齐 `routers/email_notify.py` 现用法）— `state_machine.py:99`
- 新增 `LICENSE_TRANSITIONS`（inactive/active/suspended/expired，对齐 `admin_platform.py:540`、`saas.py:391`）— `state_machine.py:107`
- 新增 `CONNECTOR_TRANSITIONS`（draft/active/error/deleted，对齐 `connectors.py`、`models_wave1.py:140`）— `state_machine.py:114`
- `INVOICE_TRANSITIONS` 的 `partially_paid → void` 增加注释：仅在配套红冲/退款（credit note）时合法；红冲工作流在路由层实现（不在本轮范围），`finance_ext.py` 需实现 void 时生成红字发票并退回已收款 — `state_machine.py:47-50`

**路由层绕过状态机的直写点（需路由 agent 改为走 `transition()`）：**

| 位置 | 实体 | 现状 |
| --- | --- | --- |
| `routers/email_notify.py:153` | email.parse | `row.parse_status = "parsed"` 直写 |
| `routers/connectors.py:138,157`、`routers/ship_mgmt.py:572` | connector | `status = "active"/"error"` 直写 |
| `routers/admin_platform.py:554`、`routers/saas.py:391` | license | `status` 直写 |
| `routers/commercial.py:174,204,283` | estimate | draft/calculated/converted 直写（estimate 不在 DDS 11 实体清单内，但建议加 ESTIMATE_TRANSITIONS） |
| `routers/finance_ext.py:759` | accrual | draft→posted 直写（accrual 不在 DDS 清单内，可接受） |

### 1.4 金样例与测试

新增 `mos/fixtures/calc/laytime/`（registry 的 `calc.laytime_gold` 按目录 glob 自动注册，无需改 registry.py）：

- `gold_02.json` — SHEX 跨周末：Fri 08:00 → Tue 08:00，剔除 Sat+Sun 48h，used=48h，滞期 8000.0
- `gold_03.json` — SHINC 含节假日：port_holidays=[2026-09-08] 仍计入，used=48h，滞期 24000.0
- `gold_04.json` — 港口时区跨日界：UTC aware 事件转 Asia/Shanghai 后落在周六 01:00→周日 01:00，SSHEX 全剔除，used=0，速遣 12000.0
- `gold_05.json` — SHEX 节假日 `even_if_used: true`：节假日作业计入，used=24h，on_time

新增 `mos/apps/api/tests/test_shipping_domain.py`（22 个用例）：SHEX/SHINC/FHEX 语义、节假日、`EIU` 后缀、未知条款警告、naive 本地化、aware 跨日界、naive/aware 混用报错、非法时区报错、Decimal 精确小时、`total_days<=0` 报错、敏感度 pct/abs 双模式、email.parse/license/connector 状态机合法与非法迁移、invoice partially_paid→void 注释行为。

---

## 第二部分：航运业务域全面审查

> 每项：现状（文件:行号证据）→ 与行业标准差距 → 字段级/接口级建议 → 优先级（P0 阻断商用 / P1 对标必需 / P2 增强）。

### 2.1 航次估算（Estimate）

**现状**：`services/estimate_engine.py` 支持包干/单价/Worldscale（`ws_flat×ws_pct`）三种运费、单一 `commission_pct`、燃油（sea/port/ECA 三档 tpd × 单一 `bunker_price`）、port/canal/other 成本、hire 单列不进 voyage_cost（口径正确，TCE=9953.13 金样例背书）。`routers/commercial.py` 提供 calculate/clone/sensitivity/compare/to-charter。

**差距与建议**：

1. **佣金结构过简**（P0）：行业区分 address commission（租家佣金，通常从运费扣）与 brokerage（经纪人佣金，通常 1.25%×n，船东费用）。建议：`estimate_engine` 输入拆 `address_comm_pct`（扣运费收入）与 `brokerage_pct`（计入 voyage_cost），`Estimate.inputs` 同步；金样例补充含 brokerage 用例。
2. **无碳排成本**（P1，EU 航线实为 P0）：EU ETS 配额成本、FuelEU 罚没未进估算。建议：inputs 增加 `eu_ets_share`（EU 航段比例）、`ets_price`、`co2_factor`（默认 3.114），引擎加 `emissions_cost = bunker_mt × co2_factor × eu_ets_share × ets_price` 入 voyage_cost；与 `routers/finance_ext.py:854` fueleu-calc 共用因子常量。
3. **燃油价格机制单一**（P1）：多燃油牌号（VLSFO/HSFO/MGO/LNG）不同价、ECA 区烧 MGO 高价。建议：inputs 支持 `bunker_prices: {"VLSFO": 450, "MGO": 620}` + `bunker_eca_grade`，引擎按牌号取价。
4. **多腿航线缺失**（P1）：DDS §6.1 要求多腿港口；当前 sea_days/port_days 是拍平的单值，无 leg 结构、无距离/航速驱动天数。建议：`Estimate.inputs` 增加 `legs: [{from_port, to_port, distance_nm, speed_kn, cargo_qty}]`，引擎由 distance/speed 推 sea_days；港口费按 leg 挂 port_id。
5. **货种/积载**（P2）：无 cargo stowage factor、deadweight vs cubic 校验、10% MOL 选项（tolerance）。建议 inputs 加 `cargo_tolerance_pct`、`stowage_factor`。
6. **等待/绕道**（P2）：waiting_days 已有；缺 deviating（绕航加油）天数与成本项。

### 2.2 租约（Charter）

**现状**：`models_domain.py:46` Charter 有 charter_type、laycan_from/to、`commission_pct`、`freight_terms`(JSON)、`clauses`(JSON)、`sanctions_blocked`；状态机 draft→pending_approval→active→completed；`routers/commercial.py:439` 制裁阻断激活；`:445` 工作流审批；COA liftings（`:514`）仅 planned_qty 录入。

**差距与建议**：

1. **关键条款字段缺失**（P0）：demurrage/despatch rate、freight rate basis（per MT / lump sum / WS）、laytime terms（SHINC/SHEX）、C/P form（GENCON/NYPE/SHELLTIME）、load/discharge rate 全部埋在 JSON 里，无法查询/校验/驱动 laytime。建议：Charter 加列 `demurrage_rate Numeric(12,2)`、`despatch_rate`、`laytime_terms Text`、`cp_form Text`、`freight_rate Numeric(12,4)`、`freight_basis String(16)`、`cargo_qty Numeric(18,3)`、`load_rate_pd`、`disch_rate_pd`；`/laytimes` 创建时从 charter 自动带入（`finance_ext.py:64` 目前 inputs 全靠手工）。
2. **期租（TC）字段空白**（P0）：无 hire rate、hire payment cycle（15 天/30 天预付）、delivery/redelivery 港与时间、off-hire 条款。建议：Charter 加 `hire_per_day`、`hire_cycle_days`、`delivery_port_id/redelivery_port_id`、`delivery_at/redelivery_at`；新增 `off_hire_events` 表（voyage_id, start_at, end_at, reason, deduct_hire bool）。
3. **COA liftings 生命周期**（P1）：`CoaLifting` 有 planned/actual qty 但无 nomination→voyage 挂接、无 laycan per lifting、无状态机（status 直写）。建议 lifting 加 `voyage_id`、`laycan_from/to`，状态 planned→nominated→fixed→completed。
4. **修订变更单**（P1）：DDS §5.3 要求修订用变更单；现 `PATCH /charters/{id}` 直接改、无版本/审计。建议加 `charter_amendments` 表（charter_id, seq, changes JSON, approved_by, created_at），active 后禁止 PATCH 关键字段。

### 2.3 航次执行（Voyage / Operations）

**现状**：`models_domain.py:112` PortCall 有 seq/purpose/eta/etd/ata/atd/agent/timezone；SofEvent 有 event_code/event_at/local_tz；NoonReport 有 lat/lon/speed/rob_fo/rob_do/eta_next，`routers/operations.py:215` 算 ETA 偏差、≥6h 发 TwinAlert；`:264` NOR→ata、COMPLETED/SAILED→atd 回写。

**差距与建议**：

1. **Port call 事件序列不规范**（P0）：event_code 自由文本，无标准码表（NOR/EOSP/ANCHOR/POB/COMMENCED/COMPLETED/HOSES_OFF/B/L_DATE/SAILED）；B/L date 是提单、滞期时效（timebar 起算点）和运费开票触发点，必须为一等字段。建议：`SofEvent.event_code` 加枚举校验 + `PortCall` 加派生列 `nor_at/eosp_at/bl_date`；`POST /sof-events` 校验同一 port_call 内事件时序单调。
2. **SOF 不驱动 Laytime**（P0）：`LaytimeCalc.inputs.events` 全靠手工 JSON（`finance_ext.py:64`），IMOS 是 SOF 一键生成 laytime 工作表。建议新增 `POST /laytimes/from-sof`：按 port_call 的 SofEvent 序列生成 events（含 excluded 标记、港口 timezone/holidays 从 Port 主数据带）。Port 主数据（`models_wave1.py:64`）有 timezone 列但无 holidays——建议加 `Port.holidays JSON` 或 `port_holidays(port_id, date)` 表。
3. **Off-hire 缺失**（P1）：无 off-hire 事件模型；期租执行的核心。建议新表 `off_hire_events`（见 2.2-2），午报/事件驱动，进 hire 发票扣减。
4. **Bunker stem/ROB 追踪**（P1）：NoonReport 有 rob_fo/rob_do 但无校验（DDS §11 ROB 守恒：期初+加油-消耗=期末，差异超阈告警——`finance_ext.py:341` 的守恒检查是自算的恒等式，永远通过，形同虚设）。建议：ROB 校验改为比对"上一天报 ROB + 期间加油 - 期间消耗"与当日报 ROB，超阈值（如 0.5%）写 `dq_issues`。
5. **Weather routing 输入**（P2）：无天气/海流字段；建议 NoonReport 加 `wind_bf`、`sea_state`、`current_kn`，为 weather routing 连接器预留。

### 2.4 滞期 / 索赔（Demurrage / Claims）

**现状**：引擎见第一部分（本轮已修）；`LaytimeCalc` status draft→calculated→finalized；`Claim` 有 claim_type/amount/time_bar/settlement_amount，状态 open→negotiating→settled/withdrawn；`finance_ext.py:163` 索赔可从 laytime 结果带金额。

**差距与建议**：

1. **timebar 管理弱**（P0）：`Claim.time_bar` 只是日期字段，无预警、无默认推算（通常 B/L date + 90 天/按 CP 条款）。建议：创建 claim 时若未传 time_bar，从 port_call B/L date + CP 条款天数推算；`GET /claims` 增加 `days_to_timebar`；dashboard `_demurrage`（`dashboards.py:424` 硬编码 "Time-bar <14d: 1"）改查真实数据。
2. **deduction / 部分赔付缺失**（P0）：索赔实务大量部分和解（settle at 70%）、扣减（装卸工时中断扣减）。`claim_transition` settled 时 `settlement_amount = row.amount`（`finance_ext.py:193`）写死全额。建议：transition 加 `settlement_amount` 参数；Claim 加 `deductions JSON`（[{reason, hours/amount}]）。
3. **Laytime 可逆/合并未支持**（P1）：DDS §6.7 要求"可逆/合并（全支持）"——reversible laytime（装卸两港时间合并计算）与 averaging。引擎现按单港 events 算。建议：inputs 加 `reversible: true` + 多 port events（带 port 标记），引擎合并 allowed/used 后统一结算（两港一滞一速互抵）。
4. **定稿锁定**（P1）：DDS §6.7 要求定稿锁定 details；`PUT /laytimes/{id}`（`finance_ext.py:113`）在 finalized 后仍可改 inputs。建议 finalized 状态拒改（409），并加"导出计算书"端点（PDF/SOF 对照表）。
5. **索赔-发票联动**（P1）：无 `POST /claims/{id}/to-invoice`；定稿滞期费应一键生成 demurrage 类型发票。

### 2.5 财务（Finance）

**现状**：Invoice 全状态机 + 工作流审批 + GL post 标记 + 部分付款/超额拦截（`finance_ext.py:609-648`，OVERPAYMENT/AMOUNT_BELOW_PAID 校验良好）；aging 报表；VoyageAccrual 应计；动态 P&L（`:923`）按 voyage 聚合发票/PDA/燃油，估 vs 实差异。

**差距与建议**：

1. **红冲缺失**（P0）：DDS §5.3 财务闭环含红冲；`partially_paid→void` 已在状态机放行但无 credit note。建议：新增 `credit_notes` 表（invoice_id, amount, reason, status）+ `POST /invoices/{id}/credit-note`，void 前置校验已收款已红冲。
2. **汇率机制空转**（P0）：`ExchangeRate` 表存在（`models_wave1.py:92`）但发票/付款/P&L 全程单币种，多币种发票与本位币折算未实现。建议：Invoice 加 `base_amount`（本位币）+ `fx_rate_id`，P&L 端点按 rate_date 折算汇总。
3. **期租 hire 发票**（P0）：invoice_type 自由文本，无 hire 类型周期性开票（15 天预付、off-hire 扣减、address commission 扣除）。建议：`invoice_type` 枚举化（freight/hire/demurrage/bunker/port_disbursement/other），新增 `POST /invoices/hire-schedule`（charter_id → 按期生成 hire 发票草稿）。
4. **P&L 结构不全**（P1）：现 P&L 只有 revenue/port/bunker；缺 canal、commission、hire、emissions、other 行项；应加 accrual 行并入（VoyageAccrual 已建模但未进 P&L 查询）。建议 `report_pnl` 增加按 line_type 分列与应计/实际两套口径。
5. **付款无撤销**（P1）：无 `DELETE /payments/{id}` 或冲正；付错只能改库。建议 payment 加 `voided_at` + 冲正端点，回写 invoice.paid_amount 与状态。

### 2.6 燃油（Bunker）

**现状**：BunkerOrder 有 grade/qty/price/rob_before/after/consumption；状态机 planned→inquiry→ordered→delivered→closed；ROB 滚动在 delivered 时计算（`finance_ext.py:341`）。

**差距与建议**：

1. **BDN/BDR 缺失**（P0）：无 Bunker Delivery Note（实际交付量、密度、硫含量）与质量争议。建议：BunkerOrder 加 `bdn_qty`、`density_kg_m3`、`sulphur_pct`、`bdn_date`、`supplier`、`barge`，交付校验 bdn_qty vs qty_ordered 偏差>2% 告警。
2. **询比价**（P1）：DDS §6.6 询比价流程；状态机有 inquiry 但无多供应商报价比价结构。建议 `bunker_inquiries` 子表（order_id, supplier, quoted_price, quoted_at）。
3. **价格曲线**（P1）：MarketQuote 可存燃油指数但 bunker 定价未挂钩；建议 unit_price 支持 `index_symbol + differential`（如 SIN380 + 12）。
4. **航次分摊**（P1）：燃油成本按 voyage 归属 = P&L 里 qty×price 粗算（`finance_ext.py:953`），未按实际消耗段分摊。建议按午报消耗 × 加权平均 ROB 成本分摊到航次段。
5. **排放因子**（P2）：排放因子 3.114/3.206 硬编码在 `finance_ext.py:815,859`；建议抽常量表（fuel_grade → co2_factor、LHV），供引擎/FuelEU 复用。

### 2.7 排放（Emissions）

**现状**：`finance_ext.py:806` 简单 CO2 估算 + 拍脑袋 CII（`co2>1000→C`）；`:854` fueleu-calc 有 GHG 强度、ETS 配额成本、FuelEU 罚没的简化公式与导出（格式版本标记良好）。

**差距与建议**：

1. **CII 评级公式错误**（P0）：真 CII = 年度 CO2 / (DWT × 距离） 对照 IMO 评级带（A–E 按船型/年份折减），不是绝对吨数阈值。建议：EmissionRecord 加 `distance_nm`、`year`，CII 计算服务化（输入 dwt/船型/年），阈值表入库。
2. **EU ETS 分摊**（P1）：现 `eu_share` 手工输入；应按航线 EU 港进出比例自动（EU 港↔EU 港 100%、EU↔非 EU 50%）。Port 主数据加 `is_eu bool`，fueleu-calc 按 port_calls 自动推 eu_share；ETS 成本需分摊到租家（TC 下租家承担）——Charter 加 `ets_responsibility: owner|charterer`。
3. **EEOI 缺失**（P2）：EEOI = CO2 /（载货吨 × 海里）；建议 EmissionRecord 加 `cargo_mt`、`eeoi` 派生列，进 analytics 报表。
4. **排放进估算**（P1）：见 2.1-2，估算引擎需纳入 ETS 成本才闭环。

### 2.8 船舶管理（Ship mgmt）

**现状**：`models_ship.py` 覆盖技术档案、证书（valid/expiring/expired）、PMS 工单（open/in_progress/done/deferred/cancelled）、船员、缺陷、备件（min_qty 预警），外部 PMS 同步 stub + 适配器目录（spectec/abs_ns/shipnet，DDS 要求的 adapter_pending 模式到位）。

**差距与建议**：

1. **证书到期无自动状态迁移**（P1）：status 靠手工/同步写入。建议加定时/惰性校验：`GET /ship/fleet` 时按 `expires_on - today < 30d → expiring`、`< 0 → expired` 重算并落库。
2. **工单无工时/备件消耗关联**（P2）：ShipWorkOrder 与 ShipSparePart 无 M2M 消耗记录；建议 `ship_wo_spares(wo_id, part_id, qty)`，完工扣 qty_on_hand。
3. **船员证书**（P2）：船员只有 contract_end；建议 ShipCrewMember.meta 规范化 `certificates: [{code, expires_on}]`，STCW 到期预警。
4. **dock/停租联动**（P2）：next_drydock 不生成 ScheduleBlock（block_type 已支持 repair/offhire）；建议 drydock 日期变更时自动占船期。

### 2.9 风控（Risk / 制裁 / 信用）

**现状**：Counterparty.sanctions_status 驱动 charter 激活阻断（`commercial.py:439`，E2E 有测试）；RiskPosition 有 var_1d/limit_breach。

**差距与建议**：

1. **信用限额硬编码**（P0）：`finance_ext.py:1199` `limit = 100000` 硬编码、VaR 按 `qty×price×2%` 拍算。建议：新增 `risk_limits` 表（tenant_id, scope: symbol/counterparty/global, limit_type: var/notional, amount, currency），创建头寸按 scope 链匹配限额；VaR 模型可插拔（DDS §6.10）。
2. **制裁筛查单点**（P0）：只在 charter 激活时查一次 sanctions_status，发票/付款/加油不查，无定期重筛与命中审计（DDS 事件 `sanctions.hit`）。建议：统一 `assert_not_sanctioned(db, counterparty_id)` 服务，invoice create/payment、bunker、portal 全挂；加 `sanctions_screenings` 审计表（screened_at, provider, result）。
3. **敞口 vs 实货**（P1）：FFA/纸货头寸与实货（open cargo/voyage）无对冲视图；建议 risk 报表按 symbol 聚合约期头寸 vs 在手货盘。

### 2.10 仪表盘（Dashboards）

**现状**：`dashboards.py` 七面角色墙，KPI 大量 `_pulse` 假数据与硬编码（如 `:247` "Laycan this week: 3"、`:424` "Time-bar <14d: 1"、`:318` "Port calls today: 4"）。

**建议**（P1）：KPI 逐项接真数据（本报告 2.3/2.4/2.5 的查询可直接供给）；假数据保留为"无数据时演示回退"并打 `synthetic: true` 标记，避免客户误读为真实业务数据——这直接关系"数据可审计"的 DoD。

---

## 第三部分：优先级汇总（建议施工序）

| 优先级 | 事项 |
| --- | --- |
| P0 | 佣金拆分（address/brokerage）；Charter 关键条款字段化（demurrage rate/laytime terms/freight basis/CP form）+ laytime 自动带入；TC hire/off-hire 模型；SOF 标准码表 + B/L date 字段化 + 一键生成 laytime；claim timebar 推算/预警 + 部分和解；红冲 credit note；多币种折算落地；hire 周期发票；BDN；真 CII 公式；risk_limits 表替硬编码 limit=100000；制裁统一断言+审计；路由层捕获 estimate ValueError→422 |
| P1 | 估算碳成本/多牌号油价/多腿航线；COA lifting 生命周期；charter 变更单；off-hire 驱动 hire 扣减；ROB 真实校验；laytime 可逆/合并 + 定稿锁定/导出；索赔一键发票；P&L 全行项+应计口径；燃油询比价/指数定价/航次分摊；ETS 自动 eu_share + 租家分摊；证书到期自动迁移；dashboard KPI 接真数据 |
| P2 | 积载/tolerance 校验；weather routing 输入；EEOI；工单-备件消耗；船员证书；drydock 占船期；敞口对冲视图 |
