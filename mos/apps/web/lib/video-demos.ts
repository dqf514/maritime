// 由 _guide_work/video/gen-guide-data.mjs 生成 —— 勿手改；重录视频后重新生成。
// 讲解稿与时间轴来源：场景脚本 tts/sub + 各场景 mp4 实测时长（与成片一致）。
export type VideoCue = { t: number; sub: string; tts: string };
export type VideoChapter = {
  id: string;
  title: string;
  start: number;
  startLabel: string;
  cues: VideoCue[];
};
export type VideoDemo = {
  src: string;
  srt: string;
  duration: number;
  chapters: VideoChapter[];
};
export type VideoDemoId = "business-zh" | "business-en" | "admin-zh";

export const VIDEO_DEMOS: Record<VideoDemoId, VideoDemo> = {
  "business-zh": {
    "src": "/videos/MariOS_业务演示_明亮模式.mp4",
    "srt": "/videos/MariOS_业务演示_明亮模式.srt",
    "duration": 805,
    "chapters": [
      {
        "id": "d1-intro",
        "title": "MariOS 航运商业操作系统 · 新版全业务演示",
        "start": 0,
        "startLabel": "0:00",
        "cues": [
          {
            "t": 1.2,
            "sub": "MariOS 航运商业操作系统 · 新版全业务演示",
            "tts": "欢迎观看 MariOS 航运商业操作系统新版演示。本次将以明亮主题，从报价、成交、执行到财务核算，完整走一遍核心业务流程，并涵盖管理员的平台操作。"
          },
          {
            "t": 15.3,
            "sub": "多租户两步登录：先租户与账号，再口令",
            "tts": "登录采用两步安全设计：先输入租户标识与账号，系统解析该租户启用的认证方式，再进入口令验证。多租户数据彼此隔离，安全策略由平台统一下发。"
          },
          {
            "t": 28.2,
            "sub": "个人工作台：待办 · 告警 · 快捷入口 · 市场指数",
            "tts": "登录后进入个人工作台。待办事项、业务告警、快捷操作与市场指数汇聚一屏，每天从这里掌握全局，重要事项不遗漏。"
          },
          {
            "t": 39.1,
            "sub": "模块化导航：租船 · 运营 · 财务 · 技术 · 分析 · 平台",
            "tts": "左侧导航按业务域组织：租船、运营、财务、技术、分析智能、主数据与平台管理。导航由服务端按角色动态下发，不同岗位看到不同的功能组合。"
          },
          {
            "t": 52.9,
            "sub": "Ctrl+K 全局搜索 · 右上角主题与语言切换",
            "tts": "全局搜索快捷键 Control 加 K，可直达任意页面与记录；右上角支持主题、语言与租户切换，中英文界面一键切换。"
          },
          {
            "t": 63.2,
            "sub": "第一站：租船商务 — 航次估算与报价",
            "tts": "系统总览就介绍到这里。第一站，我们以租船商务的身份，从航次估算与报价开始。"
          }
        ]
      },
      {
        "id": "d2-estimate",
        "title": "租船商务 · 航次估算工作台",
        "start": 72.4,
        "startLabel": "1:12",
        "cues": [
          {
            "t": 74.7,
            "sub": "租船商务 · 航次估算工作台",
            "tts": "这是租船商务的估算工作台。左侧是估算清单，右侧是编辑与计算结果区，报价全流程在这里完成。"
          },
          {
            "t": 84.5,
            "sub": "干散货模板一键新建估算",
            "tts": "用干散货模板一键新建估算，船舶参数、燃油牌号等缺省值已经预置，省去大量重复录入。"
          },
          {
            "t": 93.3,
            "sub": "填写货量与运价 · 船舶档案自动关联",
            "tts": "填写估算标题、货量与运价。选择船舶后，档案中的设计航速与油耗会在计算时自动带入，主数据一处维护、全局生效。"
          },
          {
            "t": 104.6,
            "sub": "一船多票货：按吨 / 包干 / 指数 独立计价",
            "tts": "系统支持一船多票货混合计价。添加两票货，每票可按吨、包干或波罗的海指数独立定价，空白字段自动继承顶层输入。"
          },
          {
            "t": 166.3,
            "sub": "一键计算：TCE · 总运费 · 票货明细",
            "tts": "保存并点击计算，引擎立即给出 TCE、总运费与航次成本分解，两票货的运费明细逐票展示，报价依据清晰可查。"
          },
          {
            "t": 176.7,
            "sub": "档案 + 行情自动补全：航速油耗 · 欧盟碳价",
            "tts": "空缺的航速油耗已从船舶档案自动补全；挂靠欧盟港口的碳成本份额与最新欧盟碳价，也从行情数据自动推导，报价更接近真实。"
          },
          {
            "t": 237.5,
            "sub": "报价确认 · 一键转化为租约 CP",
            "tts": "报价确认后，一键转换为租约草稿，进入合同状态机，与后续的航次执行无缝衔接。"
          },
          {
            "t": 245,
            "sub": "下一站：货物台账与成交详情",
            "tts": "成交之后，我们打开货物台账与租约详情，看看每一票货的条款、航次选项与执行安排。"
          }
        ]
      },
      {
        "id": "d3-cargo-fixture",
        "title": "货物台账：在手货盘与 LAYCAN 一目了然",
        "start": 254,
        "startLabel": "4:14",
        "cues": [
          {
            "t": 256.5,
            "sub": "货物台账：在手货盘与 LAYCAN 一目了然",
            "tts": "货物台账集中管理在手货盘：货量、装卸港、运价基础与 LAYCAN 窗口一目了然，成交与执行状态实时同步。"
          },
          {
            "t": 266.2,
            "sub": "打开货盘详情：条款 · 航次选项 · 预算",
            "tts": "打开一票已成交的铁矿石货盘。详情页分为条款、航次选项与选择权三个页签，所有合同要素集中维护。"
          },
          {
            "t": 276.2,
            "sub": "条款页签：装卸率 · 运价 · 付款条件",
            "tts": "条款页签维护装卸率、运价类型、支付比例与付款条件等核心条款，与租约、发票保持同一数据源。"
          },
          {
            "t": 285.7,
            "sub": "航次选项页签：逐港明细与费用合计",
            "tts": "航次选项页签逐港列出货量、装卸费率、港口使费与杂费，底部自动合计，预算与实际逐项对照。"
          },
          {
            "t": 317,
            "sub": "选择权页签：货量选择权与比例",
            "tts": "选择权页签管理货量选择权与比例，选择权执行情况直接影响实际结算货量。"
          },
          {
            "t": 324.5,
            "sub": "关联租约：合同条款与状态机",
            "tts": "从货盘可以直达关联租约。租约详情集中展示合同条款、状态流转与关联航次，成交信息一路贯通。"
          },
          {
            "t": 334.2,
            "sub": "状态机守门：非法流转直接拦截",
            "tts": "租约按状态机流转，草稿、已提交、生效与关闭之间只能合法迁移；越权操作会被系统直接拦截，合同纪律有保障。"
          },
          {
            "t": 364.7,
            "sub": "下一站：期租合同与在租头寸",
            "tts": "接下来进入期租板块，查看期租合同的定价阶梯、账单计划，以及全船队的在租头寸。"
          }
        ]
      },
      {
        "id": "d4-tc-positions",
        "title": "租约台账：程租 · 期租 · 包运合同分类管理",
        "start": 373.9,
        "startLabel": "6:14",
        "cues": [
          {
            "t": 375.7,
            "sub": "租约台账：程租 · 期租 · 包运合同分类管理",
            "tts": "租约台账按类型管理程租、期租与包运合同，租入与租出分开维护，成交结构一目了然。"
          },
          {
            "t": 384.1,
            "sub": "打开期租合同：KPI 概览 + 十个业务页签",
            "tts": "打开一份生效中的期租合同。顶部 KPI 概览显示租期、租金与账单总额，下方十个页签覆盖合同的全部业务细节。"
          },
          {
            "t": 394.9,
            "sub": "定价阶梯：多段租金与计费周期",
            "tts": "定价阶梯支持多段租金：不同时间段适用不同费率，计费周期与账单计划自动联动。"
          },
          {
            "t": 402.9,
            "sub": "账单计划：应付租金与付款状态",
            "tts": "账单计划逐期列出应付租金、到期日与付款状态，收付进度清晰可查，资金安排心中有数。"
          },
          {
            "t": 411.5,
            "sub": "经纪佣金与其他费用项自动计算",
            "tts": "经纪佣金与其他费用项——熏舱、淡水、靠泊使费等——按规则自动计算并进入账单，无需手工逐项核对。"
          },
          {
            "t": 421,
            "sub": "在租头寸：全船队可租与到期窗口",
            "tts": "在租头寸视图汇总全船队的可租时间与到期窗口，配合货盘 LAYCAN，租入租出决策一屏完成。"
          },
          {
            "t": 430.2,
            "sub": "下一站：航次执行 — 工作台实战",
            "tts": "成交之后进入执行。下一站是运营的航次工作台，我们打开一条在航航次实操演练。"
          }
        ]
      },
      {
        "id": "d5-voyage-workspace",
        "title": "航次台账：在航 · 计划 · 完成 实时状态",
        "start": 439.1,
        "startLabel": "7:19",
        "cues": [
          {
            "t": 441.8,
            "sub": "航次台账：在航 · 计划 · 完成 实时状态",
            "tts": "航次台账实时展示在航、计划与完成各状态的船舶动态，点开任意航次进入工作台。"
          },
          {
            "t": 450.4,
            "sub": "航次工作台 VOY-2407：九大面板协同作业",
            "tts": "打开执行中的航次 VOY-2407。工作台把概览、损益、港口活动、财务、地图、备注、指令、邮件与动态九大面板集成在同一界面。"
          },
          {
            "t": 463.2,
            "sub": "概览页签：状态机双语 · 关键指标",
            "tts": "概览页签展示航次关键指标与执行进度。状态标签中英文对照，计划、执行、完成的每一次流转都由状态机守门。"
          },
          {
            "t": 473.9,
            "sub": "损益页签：收入成本与 TCE 实时试算",
            "tts": "损益页签把收入与成本按航次实时试算，租金、燃油、港口使费分项列示，盈亏随时心中有数。"
          },
          {
            "t": 483.5,
            "sub": "港口活动页签：挂靠 · SOF · 滞期速遣",
            "tts": "港口活动页签跟踪每一次挂靠与装卸事实记录，实际时间自动进入滞期计算，速遣延误一算便知。"
          },
          {
            "t": 492.5,
            "sub": "备注页签：随手记，团队共享",
            "tts": "备注页签支持随手记录现场要点，团队成员共享同一份上下文。我们现场添加一条备注。"
          },
          {
            "t": 501.3,
            "sub": "指令页签：船东与租家指令留痕",
            "tts": "指令页签向船端与代理下达作业指令，每条指令带确认机制，执行留痕、责任清晰。"
          },
          {
            "t": 509.2,
            "sub": "活动页签：全量审计轨迹",
            "tts": "活动页签记录航次的全量操作轨迹，谁在什么时间做了什么一目了然，审计追溯完整可靠。"
          },
          {
            "t": 517.4,
            "sub": "下一站：船期计划与滞期索赔",
            "tts": "执行环节的最后，我们看船期计划的冲突检测，以及滞期费与索赔的核算闭环。"
          }
        ]
      },
      {
        "id": "d6-schedule-claims",
        "title": "船期计划：靠泊窗口 · 拖拽排程 · 冲突检测",
        "start": 525.1,
        "startLabel": "8:45",
        "cues": [
          {
            "t": 527.1,
            "sub": "船期计划：靠泊窗口 · 拖拽排程 · 冲突检测",
            "tts": "船期计划统筹未来靠泊窗口，支持拖拽排程；运力与泊位冲突自动检测，让船队安排井井有条。"
          },
          {
            "t": 536.3,
            "sub": "财务工作台 · 滞期计算队列",
            "tts": "切换到财务工作台的滞期页签。每条装卸记录对应一份滞期计算，可计算、可终局、可直接生成索赔。"
          },
          {
            "t": 546,
            "sub": "滞期计算详情：事实时间 · 等待时间 · 速遣费率",
            "tts": "打开一份滞期计算详情：装卸事实时间、允许时间、等待与延误逐项列示，速遣费率与结果金额自动核算，全部有据可依。"
          },
          {
            "t": 556.8,
            "sub": "索赔台账：时效 · 金额阶梯 · 跟进行动",
            "tts": "索赔台账管理每一笔滞期索赔：时效期限预警、预估到最终金额阶梯，跟进动作全程留痕。"
          },
          {
            "t": 565.2,
            "sub": "打开索赔详情：行动日志与追收状态",
            "tts": "打开一笔在办索赔，行动日志记录每次沟通与让步，追收状态与目标日期一屏掌握。"
          },
          {
            "t": 572.9,
            "sub": "下一站：发票 · 总账 · 损益",
            "tts": "业务数据最终汇入财务。下一站，我们完成发票、收付款、总账与损益的核算闭环。"
          }
        ]
      },
      {
        "id": "d7-finance",
        "title": "发票中心：运费 · 使费 · 滞期 · 借贷项",
        "start": 581.8,
        "startLabel": "9:42",
        "cues": [
          {
            "t": 584.1,
            "sub": "发票中心：运费 · 使费 · 滞期 · 借贷项",
            "tts": "财务从发票中心开始。运费、港口使费、滞期费与借贷项红冲统一管理，单据状态一目了然。"
          },
          {
            "t": 593.3,
            "sub": "打开运费发票：行项目 · 税费 · 关联航次",
            "tts": "打开一张运费发票，行项目、金额、税费与关联航次完整呈现；业务财务同源，无需二次录入。"
          },
          {
            "t": 602.1,
            "sub": "收付款：账期与账龄跟踪",
            "tts": "收付款模块跟踪应收应付与实际收付，账期与账龄清晰可查，逾期自动进入提醒清单。"
          },
          {
            "t": 610.6,
            "sub": "总账：凭证自动生成 · 审计链完整",
            "tts": "发票审批后自动生成会计凭证进入总账。每一分钱都能追溯到源头单据，审计链完整可靠。"
          },
          {
            "t": 619.5,
            "sub": "航次损益：收入成本多维汇总",
            "tts": "损益报表按航次、船舶与租约多维汇总收入成本，航次真实盈利一屏看清，决策有据。"
          },
          {
            "t": 628,
            "sub": "下一站：船队技术与碳排放合规",
            "tts": "财务闭环之后，我们转向技术侧：船队档案、燃油管理与碳排放合规。"
          }
        ]
      },
      {
        "id": "d8-tech",
        "title": "技术管理 · 船队档案",
        "start": 635.6,
        "startLabel": "10:36",
        "cues": [
          {
            "t": 638.2,
            "sub": "技术管理 · 船队档案",
            "tts": "技术角色维护整支船队的档案：规范参数、结构数据与证书检验集中管理。"
          },
          {
            "t": 645.2,
            "sub": "航速油耗基准：直接反哺估算引擎",
            "tts": "档案中的航速与油耗基准直接反哺估算引擎，报价时自动带入；证书到期前自动预警，适航始终有保障。"
          },
          {
            "t": 654.8,
            "sub": "燃油管理：ROB 实时与加油计划",
            "tts": "燃油管理跟踪航次燃油储备与加油计划，航次油耗与估算自动对照，偏差及时暴露。"
          },
          {
            "t": 662.9,
            "sub": "碳排放合规：EU ETS · FuelEU · CII",
            "tts": "碳排放合规模块持续跟踪欧盟碳排放交易、FuelEU 燃油法规与能效评级，履约成本提前可见。"
          },
          {
            "t": 671.6,
            "sub": "下一站：行情与 AI 智能助手",
            "tts": "最后两站：市场行情，以及系统内置的 AI 智能助手。"
          }
        ]
      },
      {
        "id": "d9-ai-market",
        "title": "市场行情：指数走势与租船市场动态",
        "start": 678,
        "startLabel": "11:18",
        "cues": [
          {
            "t": 680.5,
            "sub": "市场行情：指数走势与租船市场动态",
            "tts": "行情模块汇聚波罗的海指数等市场指标与历史走势，报价与决策紧跟市场节奏。"
          },
          {
            "t": 688.4,
            "sub": "AI 智能助手：未配置模型时的友好提示",
            "tts": "打开 AI 智能助手。在平台尚未配置大模型时，系统不会报错或沉默，而是给出清晰友好的提示，说明当前可用与不可用的能力。"
          },
          {
            "t": 751,
            "sub": "照样能用：规则引擎给出确定性回复",
            "tts": "即使没有配置模型，助手依然可用——系统回落到规则引擎，给出确定性的引导回复，并明确告知原因。"
          },
          {
            "t": 760,
            "sub": "邮件识别同样遵循：只建议 · 人工确认执行",
            "tts": "邮件识别中的 AI 动作推荐也遵循同一原则：只给出建议，执行始终由人工确认，AI 不会越权操作。"
          },
          {
            "t": 769.4,
            "sub": "回到工作台：全流程回顾",
            "tts": "至此，从报价、成交、执行、滞期、财务到技术与智能助手的完整流程演示完毕。"
          }
        ]
      },
      {
        "id": "d10-outro",
        "title": "全角色贯通：一套数据 · 一个平台",
        "start": 778.8,
        "startLabel": "12:59",
        "cues": [
          {
            "t": 781.1,
            "sub": "全角色贯通：一套数据 · 一个平台",
            "tts": "租船、运营、财务、技术与平台管理，在同一套数据上协同工作——报价即执行的起点，执行即核算的依据。"
          },
          {
            "t": 790.9,
            "sub": "MariOS — 航运商业操作系统",
            "tts": "MariOS，航运商业操作系统，为船东、租家与运营商打造的一站式平台。"
          },
          {
            "t": 798,
            "sub": "演示到此结束 · 感谢观看",
            "tts": "演示到此结束，感谢观看。欢迎在系统中亲自体验完整流程。"
          }
        ]
      }
    ]
  },
  "business-en": {
    "src": "/videos/MariOS_Business_Demo_Light_EN.mp4",
    "srt": "/videos/MariOS_Business_Demo_EN.srt",
    "duration": 700,
    "chapters": [
      {
        "id": "d1-intro",
        "title": "MariOS Maritime Operating System · Full business",
        "start": 0,
        "startLabel": "0:00",
        "cues": [
          {
            "t": 0.9,
            "sub": "MariOS Maritime Operating System · Full business demo",
            "tts": "Welcome to the MariOS maritime operating system demonstration. In the light theme, we will walk the full core flow — from quotation and fixtures to voyage execution and financial settlement — and finish with the administrator's platform operations."
          },
          {
            "t": 15.8,
            "sub": "Secure two-step login: account first, then password",
            "tts": "Login follows a two-step design. You enter the tenant identifier and account first; the system resolves the authentication methods enabled for that tenant, then proceeds to password verification. Tenant data is fully isolated, and security policy is pushed down centrally by the platform."
          },
          {
            "t": 34,
            "sub": "Personal workbench: tasks · alerts · shortcuts · indices",
            "tts": "After login you land on your personal workbench. To-dos, business alerts, quick actions and market indices come together on one screen, so every day starts with a full view of the portfolio."
          },
          {
            "t": 46.3,
            "sub": "Modular navigation: Chartering · Operations · Finance · Tech",
            "tts": "The left navigation is organised by business domain: chartering, operations, finance, technical, analytics, master data and platform. It is served by the back end per role, so each role sees exactly its own set of functions."
          },
          {
            "t": 60.8,
            "sub": "Ctrl+K global search · theme and language switch",
            "tts": "Control plus K opens global search straight to any page or record. The top bar carries the theme, language and tenant switches — the UI flips between English and Chinese with one click."
          },
          {
            "t": 72.7,
            "sub": "First stop: Chartering — estimates and quotations",
            "tts": "That concludes the overview. Our first stop is the chartering desk, starting with voyage estimation and quotation."
          }
        ]
      },
      {
        "id": "d2-estimate",
        "title": "Chartering desk · Voyage estimate workspace",
        "start": 82.1,
        "startLabel": "1:22",
        "cues": [
          {
            "t": 84.4,
            "sub": "Chartering desk · Voyage estimate workspace",
            "tts": "This is the chartering workspace. The estimate list sits on the left; editing and results on the right — the whole quotation flow happens here."
          },
          {
            "t": 93.7,
            "sub": "One click: new estimate from dry-bulk template",
            "tts": "A dry-bulk template pre-fills vessel parameters and fuel grades, so a new estimate starts from sensible defaults instead of a blank form."
          },
          {
            "t": 102.2,
            "sub": "Enter quantity and rate · vessel profile pulls through",
            "tts": "Fill in the title, cargo quantity and freight rate. Once a vessel is selected, design speed and consumption come straight from the vessel profile — master data maintained once, effective everywhere."
          },
          {
            "t": 114.5,
            "sub": "Multi-cargo: per-ton · lump sum · index, priced separately",
            "tts": "One vessel, several parcels. Add two cargoes — each priced independently per tonne, lump sum or Baltic index — while blank fields inherit the top-level inputs."
          },
          {
            "t": 194,
            "sub": "One click: TCE · total freight · per-cargo breakdown",
            "tts": "Save and hit calculate — the engine returns TCE, total freight and a full cost breakdown instantly, with freight detail line by line for each parcel."
          },
          {
            "t": 203.4,
            "sub": "Profile + market enrich: speed/consumption · EU carbon",
            "tts": "Missing speed and consumption were filled from the vessel profile; the EU carbon share for calls into EU ports, priced off the latest market data, keeps the quotation close to reality."
          },
          {
            "t": 220.2,
            "sub": "Quotation confirmed · convert to CP in one click",
            "tts": "Once the quotation is agreed, one click converts it into a charter-party draft, entering the contract state machine and flowing straight into voyage execution."
          },
          {
            "t": 229.7,
            "sub": "Next: cargo book and fixture details",
            "tts": "With the fixture done, we open the cargo book and the contract details to review terms, voyage options and execution plans."
          }
        ]
      },
      {
        "id": "d3-cargo-fixture",
        "title": "Cargo book: open parcels and laycan at a glance",
        "start": 238.5,
        "startLabel": "3:59",
        "cues": [
          {
            "t": 241,
            "sub": "Cargo book: open parcels and laycan at a glance",
            "tts": "The cargo book manages every open parcel — quantity, ports, freight basis and laycan window — with execution status synced in real time."
          },
          {
            "t": 249.5,
            "sub": "Open a parcel: terms · itinerary · options",
            "tts": "We open a fixed iron-ore parcel. The detail page has three tabs — terms, itinerary and options — holding every contract element in one place."
          },
          {
            "t": 259.4,
            "sub": "Terms tab: laytime · freight · payment conditions",
            "tts": "The terms tab maintains laytime, freight basis, payment percentages and terms — the same data source as the charter-party and the invoice."
          },
          {
            "t": 267.7,
            "sub": "Itinerary tab: per-port detail with totals",
            "tts": "The itinerary tab lists quantity, loading/discharging rates, port expenses and liners' expenses per port, with totals aggregated at the bottom — budget against actual, line by line."
          },
          {
            "t": 279.5,
            "sub": "Options tab: quantity options and percentages",
            "tts": "The options tab manages quantity options and percentages — option declarations directly affect the settled quantity."
          },
          {
            "t": 286.8,
            "sub": "Linked charter: clauses and state machine",
            "tts": "From the parcel you jump straight to the linked charter-party, with clauses, status transitions and linked voyages in one place — fixture data flows end to end."
          },
          {
            "t": 296,
            "sub": "State machine guards every transition",
            "tts": "The charter moves through a state machine — draft, submitted, active, closed — and only legal transitions pass; anything else is rejected with a conflict."
          },
          {
            "t": 305.2,
            "sub": "Next: time charters and open positions",
            "tts": "Next we move to time charters — the pricing ladder and billing schedule of a live TC, plus open positions across the fleet."
          }
        ]
      },
      {
        "id": "d4-tc-positions",
        "title": "Charter list: voyage · time charter · COA",
        "start": 313.9,
        "startLabel": "5:14",
        "cues": [
          {
            "t": 316.2,
            "sub": "Charter list: voyage · time charter · COA",
            "tts": "The charter list separates voyage charters, time charters and contracts of affreightment, with TC-in and TC-out tracked apart."
          },
          {
            "t": 324,
            "sub": "Open a live TC: KPI header + ten business tabs",
            "tts": "We open a live time charter. The KPI header shows period, hire rate and billing total; ten tabs below cover every business detail of the contract."
          },
          {
            "t": 334.2,
            "sub": "Pricing ladder: multi-tier rates and periods",
            "tts": "The pricing ladder supports multiple tiers — different rates for different periods — with billing schedules linked automatically."
          },
          {
            "t": 341.9,
            "sub": "Billing schedule: payable hire and status",
            "tts": "The billing schedule lists payable hire per period with due dates and payment status — cash planning with full visibility."
          },
          {
            "t": 349.4,
            "sub": "Broker commission and other items computed automatically",
            "tts": "Broker commissions and other items — fumigation, water, attendance — are computed by rule and flow into the bills, no manual reconciliation needed."
          },
          {
            "t": 358.8,
            "sub": "Open positions: fleet availability windows",
            "tts": "Open positions aggregate availability and redelivery windows across the fleet — against cargo laycans, TC-in and TC-out decisions complete on one screen."
          },
          {
            "t": 368.7,
            "sub": "Next: voyage execution — the workspace in action",
            "tts": "With the fixture fixed, execution begins. Next stop: the voyage workspace with a live voyage."
          }
        ]
      },
      {
        "id": "d5-voyage-workspace",
        "title": "Voyage register: under way · planned · completed",
        "start": 377.4,
        "startLabel": "6:17",
        "cues": [
          {
            "t": 379.7,
            "sub": "Voyage register: under way · planned · completed",
            "tts": "The voyage register tracks vessels under way, planned and completed in real time — click any voyage to enter its workspace."
          },
          {
            "t": 387.5,
            "sub": "Voyage workspace VOY-2407: nine integrated panels",
            "tts": "We open voyage VOY-2407, currently under way. The workspace integrates nine panels — summary, P&L, port activity, finance, map, notes, instructions, mail and activity — into a single screen."
          },
          {
            "t": 401.8,
            "sub": "Summary tab: state machine, bilingual status, KPIs",
            "tts": "The summary tab shows key indicators and execution progress. Status labels are bilingual, and every transition — planned, under way, completed — is guarded by the state machine."
          },
          {
            "t": 413.4,
            "sub": "P&L tab: revenues and costs, live TCE",
            "tts": "The P&L tab trial-calculates revenues and costs per voyage — hire, bunkers and port costs itemised, profit visible at any moment."
          },
          {
            "t": 422.4,
            "sub": "Port activity: calls, SOF, laytime trigger",
            "tts": "Port activity tracks every call and statement of facts; actual times feed laytime directly, so despatch and demurrage are known as they accrue."
          },
          {
            "t": 430.9,
            "sub": "Notes tab: jot it down, share with the team",
            "tts": "The notes tab captures field observations for the whole team. Let's add one right now."
          },
          {
            "t": 437.7,
            "sub": "Instructions tab: owners and charterers, acknowledged",
            "tts": "The instructions tab issues operational orders to the vessel and agents, each with an acknowledgement — execution recorded, accountability clear."
          },
          {
            "t": 446.3,
            "sub": "Activity tab: the full audit trail",
            "tts": "The activity tab records every operation on the voyage — who did what and when — for a complete, reliable audit trail."
          },
          {
            "t": 453.7,
            "sub": "Next: schedule conflicts and demurrage claims",
            "tts": "To close execution, we look at schedule conflict detection and the demurrage-to-claims loop."
          }
        ]
      },
      {
        "id": "d6-schedule-claims",
        "title": "Schedule: berth windows · drag planning · confli",
        "start": 460.8,
        "startLabel": "7:41",
        "cues": [
          {
            "t": 463.1,
            "sub": "Schedule: berth windows · drag planning · conflicts",
            "tts": "The schedule pools future berth windows with drag-and-drop planning; vessel and berth conflicts are detected automatically."
          },
          {
            "t": 470.6,
            "sub": "Finance desk · laytime queue",
            "tts": "Switching to the finance desk, the laytime tab. Each statement of facts maps to a calculation — calculate, finalize, or raise a claim directly."
          },
          {
            "t": 480.7,
            "sub": "Laytime detail: facts · laytime used · despatch rate",
            "tts": "Open a calculation: fact times, laytime allowed, waiting and delay broken out — despatch rate and result computed automatically, every figure auditable."
          },
          {
            "t": 490.2,
            "sub": "Claims register: time bar · amount ladder · follow-up",
            "tts": "The claims register manages every demurrage claim — time-bar warnings, an estimate-to-final amount ladder, and follow-up actions on record."
          },
          {
            "t": 498.6,
            "sub": "Open a claim: action log and recovery status",
            "tts": "We open a live claim: the action log records every negotiation and concession, with recovery status and target date on one screen."
          },
          {
            "t": 506.9,
            "sub": "Next: invoices · GL · P&L",
            "tts": "Business data finally lands in finance. Next: invoices, payments, the general ledger and profit and loss."
          }
        ]
      },
      {
        "id": "d7-finance",
        "title": "Invoice centre: freight · demurrage · debit note",
        "start": 516.2,
        "startLabel": "8:36",
        "cues": [
          {
            "t": 518.5,
            "sub": "Invoice centre: freight · demurrage · debit notes",
            "tts": "Finance starts at the invoice centre — freight, port costs, demurrage and credit-note reversals managed together, every status visible."
          },
          {
            "t": 527,
            "sub": "Open a freight invoice: lines · tax · linked voyage",
            "tts": "Opening a freight invoice: line items, amounts, tax and the linked voyage in full view — operations and finance share one data source, no double entry."
          },
          {
            "t": 536.1,
            "sub": "Payments: terms and ageing tracking",
            "tts": "Payments track receivables, payables and actual settlements — terms and ageing clear at a glance, overdue items flow into the dunning list."
          },
          {
            "t": 544.4,
            "sub": "General ledger: vouchers generated · audit intact",
            "tts": "Invoice approval generates accounting vouchers into the ledger automatically. Every amount traces back to its source document — the audit chain stays intact."
          },
          {
            "t": 554.6,
            "sub": "Voyage P&L: revenues and costs, multi-dimensional",
            "tts": "The P&L aggregates revenues and costs by voyage, vessel and contract — true voyage profitability on a single screen."
          },
          {
            "t": 562.4,
            "sub": "Next: fleet technical and emissions compliance",
            "tts": "The finance loop closes. We now turn to the technical side: fleet profiles, bunkers and emissions compliance."
          }
        ]
      },
      {
        "id": "d8-tech",
        "title": "Technical management · Fleet profiles",
        "start": 571.6,
        "startLabel": "9:32",
        "cues": [
          {
            "t": 574,
            "sub": "Technical management · Fleet profiles",
            "tts": "The technical role maintains the fleet: particulars, structural data and certificates in one registry."
          },
          {
            "t": 581.1,
            "sub": "Speed/consumption baselines feed the estimate engine",
            "tts": "Speed and consumption baselines maintained here feed the estimate engine directly — pulled into quotations automatically — while certificate expiry warnings protect compliance."
          },
          {
            "t": 591.2,
            "sub": "Bunkers: ROB in real time and procurement plan",
            "tts": "Bunker management tracks remaining-on-board and procurement plans per voyage; consumption against estimate is compared automatically, deviations surface early."
          },
          {
            "t": 600.8,
            "sub": "Emissions: EU ETS · FuelEU · CII",
            "tts": "The emissions module tracks EU ETS exposure, FuelEU Maritime and CII ratings continuously — compliance cost visible before it lands."
          },
          {
            "t": 609.9,
            "sub": "Next: market data and the AI assistant",
            "tts": "Our last two stops: market intelligence, and the built-in AI assistant."
          }
        ]
      },
      {
        "id": "d9-ai-market",
        "title": "Market: indices and chartering trends",
        "start": 616.3,
        "startLabel": "10:16",
        "cues": [
          {
            "t": 618.6,
            "sub": "Market: indices and chartering trends",
            "tts": "The market module gathers the Baltic indices and their history, keeping quotations and decisions in step with the market."
          },
          {
            "t": 626.1,
            "sub": "AI assistant: a friendly notice when no model is set",
            "tts": "Now the AI assistant. While no large language model is configured on this platform, the system does not error out or go silent — it shows a clear, friendly notice explaining what is and isn't available yet."
          },
          {
            "t": 644.7,
            "sub": "Still useful: deterministic rule-based replies",
            "tts": "Even without a model the assistant remains useful — it falls back to the rules engine for deterministic guidance, and says so plainly."
          },
          {
            "t": 652.9,
            "sub": "Email review: AI advises, humans decide",
            "tts": "Email review follows the same principle: the AI only recommends — executing stays with a human confirmation, the model never acts on its own."
          },
          {
            "t": 662,
            "sub": "Back to the workbench: the loop complete",
            "tts": "And that completes the full loop — quotation, fixture, execution, laytime, finance, technical and the AI assistant."
          }
        ]
      },
      {
        "id": "d10-outro",
        "title": "One dataset, one platform, every role",
        "start": 671,
        "startLabel": "11:11",
        "cues": [
          {
            "t": 673.2,
            "sub": "One dataset, one platform, every role",
            "tts": "Chartering, operations, finance, technical and platform management all work on a single dataset — the quotation is where execution begins, and execution is what accounting is based on."
          },
          {
            "t": 684.4,
            "sub": "MariOS — Maritime Operating System",
            "tts": "MariOS, the maritime commercial operating system — one platform for owners, charterers and operators."
          },
          {
            "t": 691.6,
            "sub": "End of demonstration · Thank you for watching",
            "tts": "This concludes the demonstration — thank you for watching. We invite you to explore the full flow yourself."
          }
        ]
      }
    ]
  },
  "admin-zh": {
    "src": "/videos/MariOS_管理演示_明亮模式.mp4",
    "srt": "/videos/MariOS_管理演示_明亮模式.srt",
    "duration": 277,
    "chapters": [
      {
        "id": "m1-admin-users",
        "title": "管理员演示 · 租户管理员视角",
        "start": 0,
        "startLabel": "0:00",
        "cues": [
          {
            "t": 4.1,
            "sub": "管理员演示 · 租户管理员视角",
            "tts": "现在进入管理员操作演示。我们以租户管理员身份登录，演练用户与角色、功能权限、界面语言等日常管理工作。"
          },
          {
            "t": 14,
            "sub": "用户管理：一人多岗 · 部门归属 · 状态管理",
            "tts": "用户管理支持一人多岗：业务角色可多选，与租户管理员并存，并可归属到组织部门；状态支持启用、停用与待激活。"
          },
          {
            "t": 24.3,
            "sub": "创建用户：生成一次性初始密码",
            "tts": "填写邮箱与姓名、勾选角色即可创建；系统生成一次性初始密码，仅此一次显示，通过安全渠道传达给用户。"
          },
          {
            "t": 92.6,
            "sub": "功能权限矩阵：按角色精细授权",
            "tts": "功能权限矩阵按角色精细控制每一项能力。租户管理员始终放行，未配置的单元格继承角色默认，取消勾选即写入拒绝并在业务接口生效。"
          },
          {
            "t": 105.3,
            "sub": "字段级权限：读 / 写 / 隐藏 三种模式",
            "tts": "第二个页签是字段级权限：可按实体、字段与角色配置读、写、隐藏三种模式，敏感数据精确到字段。"
          },
          {
            "t": 115.3,
            "sub": "界面语言与航运术语本地化",
            "tts": "语言管理维护租户默认界面语言与航运术语的本地覆盖，公司惯用叫法可以全局替换，中英文界面同步生效。"
          },
          {
            "t": 125.2,
            "sub": "下一站：设置中心与 AI 配置",
            "tts": "接下来进入设置中心，重点看 AI 配置的友好提示、模块许可与系统自检。"
          }
        ]
      },
      {
        "id": "m2-admin-settings",
        "title": "设置中心：账户 · 组织 · 安全 · 平台 一站式",
        "start": 133.3,
        "startLabel": "2:13",
        "cues": [
          {
            "t": 135.8,
            "sub": "设置中心：账户 · 组织 · 安全 · 平台 一站式",
            "tts": "设置中心汇聚账户、组织、安全、许可与平台接入等全部管理入口，分类清晰。"
          },
          {
            "t": 143.3,
            "sub": "AI 配置：供应商 · 模型 · 技能绑定 · 用量",
            "tts": "AI 配置分四个页签：供应商、模型清单、技能绑定与用量计量。支持自带密钥，计量默认关闭——自备密钥不消耗平台额度。"
          },
          {
            "t": 154.6,
            "sub": "连接测试：失败也给出友好原因",
            "tts": "对供应商执行连接测试。在没有配置可用大模型的情况下，系统返回清晰的失败原因与技术细节，而不是含糊的报错。"
          },
          {
            "t": 165,
            "sub": "模块许可：按模块授权 · 开发全解锁",
            "tts": "模块许可页列出全部业务模块的授权状态与核心模块标识，按合同开通、即开即用。"
          },
          {
            "t": 173,
            "sub": "系统自检：黄金样例一键体检",
            "tts": "系统自检在打开时自动运行，覆盖计算黄金样例、租户隔离与数据一致性检查，得分与通过、警告、失败数量一屏呈现。"
          },
          {
            "t": 184,
            "sub": "连接器目录：邮件 · 市场 · ERP · PMS",
            "tts": "连接器目录覆盖邮件、市场数据、ERP 与船队系统等集成，每个连接器带本地化描述与健康状态指示。"
          },
          {
            "t": 193.3,
            "sub": "Webhook 与回收站",
            "tts": "Webhook 配置向外推送业务事件；回收站统一保管软删除的数据，可随时还原，误删无忧。"
          },
          {
            "t": 201.4,
            "sub": "下一站：平台管理员 · 多租户运营",
            "tts": "租户管理员的日常到此为止。下一站切换到平台管理员视角，看看多租户的运营与治理。"
          }
        ]
      },
      {
        "id": "m3-platform-admin",
        "title": "平台管理员登录 sys 租户",
        "start": 210.4,
        "startLabel": "3:30",
        "cues": [
          {
            "t": 213,
            "sub": "平台管理员登录 sys 租户",
            "tts": "以平台运营身份登录 sys 租户。平台管理员不进入业务流程，专注于租户、计费、品牌与身份的全局治理。"
          },
          {
            "t": 223.2,
            "sub": "平台总览：租户 · 运行 · 品牌",
            "tts": "平台总览聚合租户规模、运行状态与品牌配置，是平台运营的驾驶舱。"
          },
          {
            "t": 230.2,
            "sub": "租户管理：开通 · 状态 · 模块授权",
            "tts": "租户管理负责开通新租户、维护状态与模块授权，每个租户数据完全隔离。"
          },
          {
            "t": 237.6,
            "sub": "订阅计费：套餐 · MRR · 配额",
            "tts": "订阅计费管理套餐、商户经常性收入与用量配额，配额以紧凑可读的方式展示，经营状况一目了然。"
          },
          {
            "t": 246.7,
            "sub": "身份与邮件通道：OAuth · SMTP 统一配置",
            "tts": "身份与验证页统一管理全局 OAuth 应用与邮件通道。SMTP 密码加密存储、绝不下发浏览器，发送测试可即时验证连通性。"
          },
          {
            "t": 258,
            "sub": "平台健康：租户统计与运行版本",
            "tts": "平台健康页汇总租户总数、活跃与停用统计，以及 API 版本与最近检查时间。"
          },
          {
            "t": 265.7,
            "sub": "演示结束 · 平台与租户各司其职",
            "tts": "管理员演示到此结束。平台管理员治理租户与全局配置，租户管理员经营自己的业务域，职责清晰、数据隔离。感谢观看！"
          }
        ]
      }
    ]
  }
};
