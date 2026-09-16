**`Mari OS要做的事情设定`**
  **IMOS 是 Veson Nautical 的 Integrated Maritime Operating System**，我认为它的核心竞争力其实不是“ERP功能多”，而是它把**航运最核心的商业闭环——合同、船舶、航次、运费、成本、风险、结算和利润**连接起来了。

现在进入 AI 时代以后，IMOS 最值得做的也不是简单加一个 ChatGPT，而是把它从“**记录和管理业务的系统**”升级成“**理解业务、预测结果、主动决策、执行动作的航运 Operating System**”。

Veson 当前对 IMOS 的定位本身已经很接近这个方向：IMOS覆盖从 pre-fixture、合同管理、航次执行到 post-voyage settlement，并把 AI、邮件、市场数据和 Analytics 纳入统一平台。官方目前披露 IMOS 已有超过 21,000 名用户、年处理约 165,000 个商业航次。 Veson Nautical+1

## 一、IMOS真正的核心竞争力是什么？

我会把它总结成 **5个“护城河”**。

### 1. 最核心的不是ERP，而是“航次商业逻辑”

传统 ERP 的基本逻辑是：

> 客户 → 订单 → 采购 → 库存 → 财务 → 结算

但航运不是这么简单。

航运的核心逻辑实际上是：

> **Cargo → Contract → Vessel → Voyage → Port → Bunker → Freight → Cost → Risk → P&L → Settlement**

而且这些变量是实时变化的。

比如：

- 船晚到一天

- 燃油价格上涨

- 港口拥堵

- laycan变化

- cargo数量变化

- weather变化

- canal transit变化

- freight rate变化

- demurrage发生

- ETS/FuelEU成本变化

最终都会反映到：

> **这条船、这个航次，到底赚多少钱？**

IMOS最强的地方，就是它把这些商业变量放在了一个连续的航次生命周期里。

现在 IMOS Operations 仍然把 voyage planning、cargo、vessel performance、bunker、P&L、tasks & alerts 放在统一工作流里，并通过 Dynamic P&L 实时观察估算与实际之间的差异。 Veson Nautical+1

所以我认为：

> **IMOS的第一护城河 = 航运业务模型，而不是软件界面。**

---

# 二、第二个护城河：它积累的是“航运决策数据”

这是 AI 时代非常重要的一点。

普通 ERP 积累的是：

> 谁买了什么、什么时候付款、库存多少。

而 IMOS 积累的是：

> **为什么这个航次赚钱/亏钱。**

例如：

某条船：

| 项目         | 预算    | 实际     |
| ---------- | ----- | ------ |
| Freight    | $1.8M | $1.8M  |
| Bunker     | $420K | $510K  |
| Port Cost  | $180K | $220K  |
| Demurrage  | $0    | $150K  |
| Revenue    | $1.8M | $1.95M |
| Voyage P&L | $620K | $470K  |

普通 ERP 最后告诉你：

> Actual P&L = $470K

但优秀的 IMOS 应该能够进一步告诉你：

> **为什么少赚了 $150K？**

甚至：

> 其中 $90K 来自 bunker consumption，$45K 来自港口延误，$30K 来自 demurrage，$15K来自其他异常。

这就是非常宝贵的 **decision data**。

而且这种数据是跨：

- 船

- 航次

- Charterer

- Broker

- Cargo

- Port

- Counterparty

- Route

- Bunker

- Captain

- Vessel class

- Trade lane

不断积累的。

**AI真正有价值的燃料，就是这种结构化的历史业务数据。**

---

# 三、第三个护城河：复杂航运业务的“规则引擎”

航运业有一个很特殊的特点：

> **业务不是简单的CRUD，而是大量例外、规则和合同解释。**

例如：

- demurrage

- despatch

- laytime

- NOR

- weather working day

- reversible laytime

- SHINC / SHEX

- WIBON / WIPON

- freight escalation

- bunker adjustment

- deviation

- deadfreight

- off-hire

- performance claim

- deviation clause

这也是为什么普通 ERP 很难直接替代专业航运系统。

IMOS 的价值之一，就是把这些复杂规则变成系统里的：

> **business rules + workflow + calculation engine**

所以它真正的壁垒不是“代码”，而是：

> **几十年航运行业经验被固化成软件逻辑。**

这一点非常重要。

---

# 四、AI时代最大的机会：把IMOS从“System of Record”变成“System of Intelligence”

这是我认为最关键的战略转型。

过去：

> **IMOS = System of Record**

记录发生了什么。

未来：

> **IMOS = System of Intelligence**

告诉你：

> **接下来会发生什么、为什么发生、应该怎么办。**

再进一步：

> **System of Action**

直接帮你执行。

可以形成一个非常清晰的演进：

**ERP → Analytics → AI Copilot → AI Agent → Autonomous Operations**

---

# 五、我认为IMOS最值得做的6个AI方向

## 1. AI Chartering Copilot

这是非常大的机会。

现在 Charterer 可能要处理：

- broker email

- charter party

- fixture recap

- market data

- vessel position

- freight indication

- bunker price

- historical voyage

- customer requirements

AI可以把这些信息自动理解。

例如收到：

> “We can offer MV XXX basis 5/10 Feb delivery Rotterdam, redelivery Skaw-Gibraltar…”

AI直接识别：

- Vessel

- Laycan

- Delivery

- Redelivery

- Cargo

- Freight

- Demurrage

- Commission

- Bunker terms

- Special clauses

然后：

> **自动生成 fixture**

甚至自动和历史交易比较：

> “这个 offer 比过去90天同航线成交价低 $1.8/ton。”

这就不是 Chatbot 了。

而是：

> **AI Chartering Analyst**

---

# 六、AI Voyage Manager

这个我认为甚至比聊天机器人重要。

未来 Operations 页面不应该只是：

> Voyage 123  
> ETA: 15 Sep  
> P&L: $480K

而应该主动告诉你：

> **Voyage 123：预计最终P&L下降 $72K。**

然后：

> 主要原因：
> 
> - Rotterdam congestion：预计 +18 hrs
> 
> - Bunker consumption：+6%
> 
> - Weather delay：+9 hrs
> 
> - Demurrage probability：63%

再进一步：

> **建议：调整航速至 12.5 knots，可减少预计成本 $28K。**

这时候 IMOS 才真正成为：

> **AI Operations Manager**

---

# 七、AI Demurrage / Claims Agent

这个领域特别适合 AI。

因为它本质上是：

> **合同 + 文件 + 时间线 + 规则 + 计算**

非常适合 AI。

例如：

系统自动读取：

- Charter Party

- NOR

- SOF

- Statement of Facts

- Emails

- Port log

- Weather

- AIS

- Agent documents

然后建立：

> **完整事件时间线**

AI判断：

> Laytime commenced at 08:32  
> Laytime allowed: 72h  
> Actual used: 91h  
> Demurrage: 19h  
> Rate: $25,000/day  
> Estimated claim: $19,791

然后：

> 自动生成 claim。

甚至：

> 自动找出对方可能反驳的合同条款。

这会直接产生 ROI。

---

# 八、AI应该进入邮件，而不是要求用户再打开一个AI窗口

这是一个非常关键的产品判断。

航运公司的大量业务其实发生在：

> **Email**

而不是 ERP。

所以未来最好的 IMOS 不是：

> “这里有一个AI Chat按钮。”

而是：

> **AI就在你的工作流里面。**

例如 Charterer 收到：

> “Please confirm revised ETA…”

AI自动理解：

> 这是 Voyage 2387 的 ETA request。

然后：

> 从 AIS / voyage plan / port information 中获取最新数据。

最后生成：

> “Current ETA Rotterdam is 18 Sep 14:00 LT…”

用户点击：

> **Send**

这才是真正的 AI-native ERP。

Veson目前也已经在往这个方向走，把 IMOS 与集成邮件、AI和市场数据放进同一平台，而不是让用户不断切换应用。 Veson Nautical

---

# 九、第三个方向：从“数据查询”升级到“预测”

现在 ERP：

> What happened?

BI：

> What is happening?

AI：

> **What will happen?**

真正有价值的模型应该预测：

### Voyage P&L Prediction

> 预计最终P&L：$487K  
> Confidence：87%

### ETA Prediction

> ETA Rotterdam：18 Sep 13:40  
> Confidence：91%

### Demurrage Prediction

> Demurrage probability：67%

### Bunker Prediction

> Expected consumption：+4.8%

### Counterparty Risk

> Counterparty payment risk：medium/high

### Freight Prediction

> Expected TC equivalent：$18,500/day

这样 IMOS 就从：

> **ERP**

变成：

> **航运预测平台。**

---

# 十、第四个方向：建立“Shipping Knowledge Graph”

我甚至认为这可能是未来IMOS最大的技术壁垒之一。

把所有数据关联起来：

```
Vessel
  ↓
Voyage
  ↓
Cargo
  ↓
Charter Party
  ↓
Counterparty
  ↓
Port
  ↓
Bunker
  ↓
Weather
  ↓
AIS
  ↓
Operations
  ↓
P&L
  ↓
Claims
```

然后再加入：

```
Email
Documents
Contracts
Market Data
News
Regulations
Historical Voyages
```

形成一个：

> **Maritime Knowledge Graph**

这样用户问：

> “为什么这条船今年表现比去年差？”

AI不是去“搜索数据库”，而是在知识图谱上做推理。

它可以回答：

> 主要原因有三个：
> 
> 1. Rotterdam waiting time增加22%
> 
> 2. bunker consumption增加5.7%
> 
> 3. average freight收入下降3.2%

这才是真正意义上的：

> **AI + ERP**

---

# 十一、但有一个问题比AI更重要：数据质量

这一点我反而认为是很多企业最容易犯的错误。

很多公司会说：

> “我们要上AI。”

但实际上：

> Master Data 不统一  
> Vessel data 不完整  
> Port data 不一致  
> Charter Party 没结构化  
> Email 没关联  
> Voyage data 有大量人工修改  
> P&L口径不统一

这种情况下，AI越强，可能只是：

> **Garbage in → Intelligent Garbage out**

所以 AI 时代，IMOS 第一优先级其实应该是：

### Data Foundation

包括：

- Master Data

- Vessel

- Port

- Cargo

- Customer

- Counterparty

- Contract

- Voyage

- Rate

- Cost

- P&L

- Event

- Document

全部建立统一的数据模型。

这也是为什么 Master Data Management 本身在海事 ERP 中非常重要——例如 smartPAL 的 MDM 就强调把 master data 作为统一中心，供交易和分析模块共享。 MariApps Marine Solutions

---

# 十二、如果我是IMOS产品负责人，我会重新定义产品架构

我会把未来的 IMOS 设计成：

```
                    ┌────────────────────┐
                    │   AI Decision Layer │
                    │ Prediction / Agent  │
                    └─────────┬──────────┘
                              │
             ┌────────────────┴────────────────┐
             │      Maritime Intelligence     │
             │ Knowledge Graph + Data Lake    │
             └────────────────┬────────────────┘
                              │
       ┌──────────────────────┼─────────────────────┐
       │                      │                     │
   Chartering             Operations             Finance
       │                      │                     │
   Contracts                Voyage                 P&L
   Fixtures                 Port                   Claims
   Freight                  Bunker                 Settlement
       │                      │                     │
       └──────────────────────┼─────────────────────┘
                              │
                    Core Maritime Data
                              │
              Vessel / Cargo / Port / Party
```

也就是说：

> **AI不能漂浮在ERP上面。**

它必须深入到：

> **数据层 → 业务规则 → 工作流 → 决策 → 执行**

---

# 十三、那么作为“航运业ERP”，最重要的到底是什么？

如果让我只选 **5件事情**，我会按照这个优先级排：

### 第一：业务正确性

> **系统算得对。**

比漂亮 UI、AI、Dashboard 都重要。

航运公司一天可能处理几百万美元甚至更高价值的交易。

一个错误的：

- laytime

- freight

- bunker

- demurrage

- P&L

都可能直接造成真实的财务损失。

所以：

> **Trust > Intelligence**

---

### 第二：Single Source of Truth

整个公司必须知道：

> **到底哪个数字是真的？**

例如：

Chartering认为：

> Voyage P&L = $520K

Operations认为：

> $490K

Finance认为：

> $460K

Management看到：

> $530K

这时候 AI 没意义。

所以未来最重要的基础设施之一是：

> **Single Maritime Truth**

---

### 第三：Workflow，而不是功能

好的 ERP 不是：

> 有1000个功能。

而是：

> **让一件事情从开始到结束自动流动。**

例如：

```
Fixture
 ↓
Contract
 ↓
Voyage
 ↓
Operations
 ↓
Bunker
 ↓
Port
 ↓
Invoice
 ↓
Demurrage
 ↓
Settlement
 ↓
P&L
```

不能中间靠：

> Excel + Email + WhatsApp + 人脑

连接起来。

---

### 第四：Exception Management

未来 ERP 不应该要求人：

> 每天打开100个页面检查1000条数据。

而应该：

> **AI帮你过滤，只把真正重要的问题推给人。**

例如：

> 🔴 3个Voyage存在重大P&L风险  
> 🟠 5个Voyage存在ETA风险  
> 🟠 2个Counterparty存在付款风险  
> 🟢 187个Voyage正常

这叫：

> **Management by Exception**

我认为这是 AI 对 ERP 最重要的改变之一。

---

### 第五：Decision Support

最终 ERP 的价值不是：

> “记录业务。”

而是：

> **帮助公司赚更多钱、少亏钱、降低风险。**

所以未来 IMOS 的核心 KPI 不应该只是：

- DAU

- 用户数

- 登录次数

- 页面访问

而应该是：

> **每年通过系统帮助客户创造/保护了多少利润。**

例如：

> AI发现 $3.2M demurrage leakage  
> AI减少 $5.7M bunker cost  
> AI减少 $2.1M claims leakage  
> AI减少 $1.8M manual operation cost

这才是真正的商业价值。

---

# 十四、我对IMOS未来的一个核心判断

我会把它浓缩成一句话：

> **IMOS过去的核心价值，是把复杂的航运业务数字化；未来的核心价值，是把航运公司的“经验”数字化，并最终让AI能够代替人执行大量重复性的商业决策。**

也就是：

**过去**

> 人 → IMOS → 数据

**现在**

> 人 → IMOS → 数据 → Analytics

**AI时代**

> 人 → AI → IMOS → 数据 → Decision → Action

**最终形态**

> **Human sets strategy  
> AI manages exceptions  
> System executes operations**

这其实比“给IMOS加一个Copilot”高一个数量级。

而且从行业竞争来看，竞争也已经不是单纯的“谁的ERP功能更多”。像 Veson/IMOS、MariApps smartPAL、Shipnet ONE 等都在强调一体化、数据、云、运营和决策能力；MariApps目前也已经把 OceanAI 等AI能力纳入其海事数字化产品体系。 MariApps Marine Solutions+2

所以我认为未来真正的竞争会变成：

> **谁拥有最好的 Maritime Data Model + Maritime Workflow + Maritime Knowledge + AI Decision Engine。**

如果你是在做**航运软件产品/IMOS产品规划/ERP升级**，我建议下一步不要泛泛谈“AI能做什么”，而是直接做一张 **《IMOS AI时代产品战略地图》**，把 **Chartering、Operations、Voyage、P&L、Demurrage、Bunker、Claims、Finance、AI Agent** 逐个拆开，按 **“现状 → AI改造点 → 用户价值 → 技术实现 → 商业价值 → 优先级”** 排出未来 1～3 年 roadmap。这样会非常适合拿去做产品战略或管理层汇报。
