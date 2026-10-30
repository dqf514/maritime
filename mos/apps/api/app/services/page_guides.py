"""Page-level SOP guides — bilingual static content served by /guides/{page_key}.

Content is defined in code for now; tenant-level overrides can be layered on
later without changing the API contract.
"""

from __future__ import annotations

from typing import Any

GUIDES: dict[str, dict[str, Any]] = {
    "home": {
        "title": {"en": "Workbench", "zh": "工作台"},
        "purpose": {
            "en": "Daily landing page: your tasks, alerts, voyage exceptions and key numbers in one glance, so you know what needs action today.",
            "zh": "每日落地页：汇总你的任务、提醒、航次异常与关键数字，让你一眼看清今天要处理什么。",
        },
        "steps": [
            {"en": "1. Sign in and scan the alert strip for overdue tasks and expiring certificates.", "zh": "1. 登录后先扫一遍提醒条：逾期任务与临期证书。"},
            {"en": "2. Review open voyage exceptions and click through to the voyage that needs attention.", "zh": "2. 查看未处理的航次异常，点进需要处理的航次。"},
            {"en": "3. Work your task list top-down; complete or reassign what you finish.", "zh": "3. 自上而下处理任务清单，完成的及时办结或转派。"},
            {"en": "4. Check the KPI cards (active voyages, receivables, claims) for anything unusual.", "zh": "4. 看关键指标卡（在航航次、应收、索赔）有无异常波动。"},
            {"en": "5. Use Ctrl+K to jump directly to any document or page; Ctrl+J opens the AI assistant on whatever you are looking at.", "zh": "5. 用 Ctrl+K 直接跳转到任何单据或页面；按 Ctrl+J 打开当前页面的 AI 助手。"},
            {"en": "6. Check pending routine drafts and system-generated tasks — automation only raises them, a person still confirms.", "zh": "6. 查看待复核的例行草稿与系统生成的任务——自动化只负责产生，确认仍由人完成。"},
        ],
        "upstream": {
            "en": "Aggregates data produced by every desk: tasks, voyages, invoices, claims and certificates.",
            "zh": "汇总各台面产生的数据：任务、航次、发票、索赔与证书。",
        },
        "downstream": {
            "en": "Entry point — every card links into the owning desk page where the actual work happens.",
            "zh": "入口页——每张卡片都跳转到对应业务页面，实际工作在那些页面完成。",
        },
        "roles": {"en": "Every signed-in role; the layout adapts to your role.", "zh": "所有登录角色；版面随角色自适应。"},
        "help_slugs": ["welcome", "getting-started", "ai-assistant"],
    },
    "tasks": {
        "title": {"en": "Tasks", "zh": "任务"},
        "purpose": {
            "en": "Personal and team work list: manual to-dos plus system-generated follow-ups (approvals, alerts) tracked to completion.",
            "zh": "个人与团队工作清单：手工待办加系统生成的跟进事项（审批、提醒），跟踪到办结。",
        },
        "steps": [
            {"en": "1. Open My tasks and sort by due date; overdue items surface first.", "zh": "1. 打开我的任务，按截止时间排序，逾期事项排在最前。"},
            {"en": "2. Pick a task, follow its link to the related document (voyage, invoice, certificate).", "zh": "2. 选择任务，顺着链接打开关联单据（航次、发票、证书）。"},
            {"en": "3. Do the work in the owning page, then return and mark the task done.", "zh": "3. 在对应业务页面完成工作，回到任务页标记办结。"},
            {"en": "4. Reassign with a comment when someone else should pick it up.", "zh": "4. 需要他人接手时改派并留言说明。"},
            {"en": "5. Create manual tasks for anything you don't want to lose track of.", "zh": "5. 任何怕漏掉的事都随手建任务跟踪。"},
            {"en": "6. Expect system tasks to arrive on their own: voyage completion, invoice issue and disbursement closure each raise follow-ups for the owning role.", "zh": "6. 系统任务会自行到来：航次完成、账单开具、使费关闭都会为对应角色派发跟进事项。"},
        ],
        "upstream": {
            "en": "Manual entries and system events (approvals, expiry alerts, exception scans, closeout checklist).",
            "zh": "手工录入与系统事件（审批、到期提醒、异常扫描、收尾清单）。",
        },
        "downstream": {
            "en": "Completed tasks close the loop; assignees receive notifications.",
            "zh": "任务办结形成闭环；被指派人会收到通知。",
        },
        "roles": {"en": "All roles; tenant admin and management see the tenant-wide list.", "zh": "所有角色；租户管理员与管理层可查看全租户清单。"},
        "help_slugs": ["getting-started", "event-automation"],
    },
    "estimates": {
        "title": {"en": "Voyage Estimates", "zh": "航次估算"},
        "purpose": {
            "en": "Pre-fixture profitability calculation: simulate freight, bunker, port costs and hire to get TCE and margin before committing to a cargo.",
            "zh": "成交前盈利测算：模拟运费、燃油、港使费与租金，在揽货前算出租金当量（TCE）与毛利。",
        },
        "steps": [
            {"en": "1. Create an estimate, pick the vessel and cargo quantity.", "zh": "1. 新建估算，选择船舶与货量。"},
            {"en": "2. Enter the voyage legs: load/discharge ports, distances and port stays.", "zh": "2. 录入航段：装卸港、航程距离与在港天数。"},
            {"en": "3. Input freight rate, bunker prices and port costs.", "zh": "3. 输入运费率、油价与港口费用。"},
            {"en": "4. Run the calculation and review TCE, daily result and margin.", "zh": "4. 执行计算，查看 TCE、日收益与毛利。"},
            {"en": "5. Clone versions to compare alternatives before negotiating.", "zh": "5. 复制版本对比不同方案，用于谈判。"},
            {"en": "6. Convert the winning estimate into a charter once fixed.", "zh": "6. 成交后把最终估算转为租约。"},
            {"en": "7. Shortcut: paste a recap, mail or chat log and let the assistant extract the fields, then tick only what you want applied.", "zh": "7. 快捷做法：粘贴 recap、邮件或聊天记录，由助手抽取字段，再只勾选要采用的字段填入。"},
        ],
        "upstream": {
            "en": "Vessel masterdata (speed/consumption), port distances, market bunker prices.",
            "zh": "船舶主数据（航速/油耗）、港口距离、市场油价。",
        },
        "downstream": {
            "en": "A fixed estimate converts into a charter; the charter later activates a voyage.",
            "zh": "成交的估算转为租约；租约随后激活为航次。",
        },
        "roles": {"en": "Chartering desk; management reviews results.", "zh": "租船台面；管理层查看测算结果。"},
        "help_slugs": ["estimates", "ai-assistant", "email-ai"],
    },
    "charters": {
        "title": {"en": "Charters & Fixtures", "zh": "租约与成交"},
        "purpose": {
            "en": "Fixture management: CP terms (freight, laycan, demurrage/despatch, commissions) captured, approved and kept as the contract baseline.",
            "zh": "成交管理：录入并审批租约条款（运费、受载期、滞期/速遣、佣金），作为合同基准保存。",
        },
        "steps": [
            {"en": "1. Create a charter from an estimate or from scratch, filling CP form and laycan.", "zh": "1. 从估算或空白新建租约，填写 CP 格式与受载期。"},
            {"en": "2. Record commercial terms: freight rate/basis, cargo qty, load/discharge rates.", "zh": "2. 录入商务条款：运费率/计价方式、货量、装卸率。"},
            {"en": "3. Set demurrage/despatch rates and laytime terms (SHINC/SHEX).", "zh": "3. 设置滞期/速遣费率与装卸时间条款（SHINC/SHEX）。"},
            {"en": "4. Capture address commission and brokerage percentages.", "zh": "4. 录入回佣与经纪佣金比例。"},
            {"en": "5. Submit for approval; the fixture locks once approved.", "zh": "5. 提交审批；审批通过后成交锁定。"},
            {"en": "6. Activate a voyage from the approved charter.", "zh": "6. 从已批准的租约激活航次。"},
            {"en": "7. Fast track: a recap mail in Email Review can create the estimate and charter draft for you — then confirm the terms here.", "zh": "7. 快车道：邮件复核中的一封 recap 邮件即可生成估算与租约草稿，条款仍需在此确认。"},
        ],
        "upstream": {"en": "Converted estimates, counterparty masterdata, and drafts raised from email.", "zh": "由估算转换而来，引用对手方主数据，也可由邮件直接生成草稿。"},
        "downstream": {
            "en": "Approved charters activate voyages; terms drive laytime, demurrage and freight invoicing.",
            "zh": "批准的租约激活航次；条款驱动滞期费计算与运费开票。",
        },
        "roles": {"en": "Chartering desk creates; management approves.", "zh": "租船台面录入；管理层审批。"},
        "help_slugs": ["charters", "email-ai"],
    },
    "voyages": {
        "title": {"en": "Voyage Operations", "zh": "航次运营"},
        "purpose": {
            "en": "Execution of the fixture: the live voyage list where ops tracks every voyage from activation to completion and hand-over to laytime/finance.",
            "zh": "成交的执行：在航航次总表，操作岗位在这里跟踪每个航次从激活到完成，并移交滞期/财务。",
        },
        "steps": [
            {"en": "1. Activate the voyage from the approved charter.", "zh": "1. 从已批准的租约激活航次。"},
            {"en": "2. Maintain port calls: keep ETA/ETD current for every call.", "zh": "2. 维护挂靠港：及时更新每港 ETA/ETD。"},
            {"en": "3. Enter the noon report every day while at sea.", "zh": "3. 海上航行期间每日录入午报。"},
            {"en": "4. On arrival, record SOF events (NOR, commenced, completed).", "zh": "4. 到港后录入 SOF 事件（NOR、开工、完工）。"},
            {"en": "5. Watch the exception feed and clear alerts as they arise.", "zh": "5. 盯异常清单，出现异常及时处理销号。"},
            {"en": "6. Complete the voyage and hand over to laytime calculation and invoicing.", "zh": "6. 航次完成后移交滞期计算与开票。"},
            {"en": "7. Work the Closeout tab before you close: every missing item becomes a task for the owning role automatically.", "zh": "7. 关航前过一遍「收尾」页签：每一项未完成的内容都会自动变成对应角色的任务。"},
        ],
        "upstream": {"en": "Approved charters from the chartering desk.", "zh": "租船台面批准的租约。"},
        "downstream": {
            "en": "Completed voyages feed laytime/demurrage, freight invoices, claims and voyage P&L.",
            "zh": "完成的航次流向滞期/索赔、运费发票与航次盈亏。",
        },
        "roles": {"en": "Operations desk runs it; demurrage and finance consume the output.", "zh": "操作岗位主导；滞期与财务岗位使用其产出。"},
        "help_slugs": ["voyages", "event-automation"],
    },
    "voyage_detail": {
        "title": {"en": "Voyage 360", "zh": "航次 360"},
        "purpose": {
            "en": "Single-voyage command view: itinerary, noon reports, SOF events, bunker, costs and P&L for one voyage in one place.",
            "zh": "单航次指挥视图：一个页面看全某航次的航线、午报、SOF 事件、燃油、费用与盈亏。",
        },
        "steps": [
            {"en": "1. Check the itinerary strip: port sequence, ETA vs ATA for each call.", "zh": "1. 看航线条：港口顺序、每港 ETA 与 ATA 对比。"},
            {"en": "2. Review noon reports for speed/consumption deviation.", "zh": "2. 查看午报，关注航速/油耗偏差。"},
            {"en": "3. Verify SOF events are complete before laytime starts.", "zh": "3. 滞期起算前确认 SOF 事件完整。"},
            {"en": "4. Track costs accruing: port disbursements, bunker, hire.", "zh": "4. 跟踪累计成本：港使费、燃油、租金。"},
            {"en": "5. Read the live P&L and TCE to judge the voyage result.", "zh": "5. 看实时盈亏与 TCE，判断航次效益。"},
            {"en": "6. Raise or clear exceptions linked to this voyage.", "zh": "6. 处理或登记与本航次相关的异常。"},
            {"en": "7. Use the Route map tab to see the world basemap with the planned great-circle route, the noon track and every port call.", "zh": "7. 「航线图」页签提供世界底图：计划大圆航线、午报航迹与每个挂靠港都在其上。"},
        ],
        "upstream": {"en": "Everything the ops desk records on the voyage: port calls, reports, events, costs.", "zh": "操作岗位在该航次上记录的一切：挂靠港、午报、事件、费用。"},
        "downstream": {
            "en": "Source of truth for laytime calc, claims and voyage accounting.",
            "zh": "滞期计算、索赔与航次核算的数据源头。",
        },
        "roles": {"en": "Operations, demurrage and management.", "zh": "操作、滞期与管理层。"},
        "help_slugs": ["voyages", "finance-laytime"],
    },
    "finance": {
        "title": {"en": "Finance Desk", "zh": "财务台面"},
        "purpose": {
            "en": "Receivables and payables: freight and demurrage invoicing, payment matching, credit notes, aging and GL posting.",
            "zh": "应收应付：运费与滞期费开票、收款核销、红冲、账龄与过账。",
        },
        "steps": [
            {"en": "1. Create the invoice from the charter, laytime or claim.", "zh": "1. 依据租约、滞期单或索赔创建发票。"},
            {"en": "2. Submit the draft through approval before issuing.", "zh": "2. 草稿提交审批后再开具。"},
            {"en": "3. Issue the invoice and watch the due date.", "zh": "3. 开具发票并盯紧到期日。"},
            {"en": "4. Register payments and match them against open invoices.", "zh": "4. 登记收款并核销未结发票。"},
            {"en": "5. Issue credit notes for corrections (red-flush the original).", "zh": "5. 需要更正时开红冲贷记单。"},
            {"en": "6. Review aging weekly and escalate long-overdue balances.", "zh": "6. 每周看账龄表，长期逾期的升级催收。"},
            {"en": "7. Export the document when you need to send it: invoices and laytime statements have an Export PDF button, laid out from the tenant's document templates.", "zh": "7. 需要对外出具时导出：账单与装卸时间证明带「导出 PDF」按钮，版式取自租户的单据模板。"},
        ],
        "upstream": {
            "en": "Completed voyages, finalized laytime calcs and settled claims.",
            "zh": "完成的航次、定稿的滞期计算与结案的索赔。",
        },
        "downstream": {
            "en": "Paid invoices close the cash cycle; balances feed aging, accruals and voyage P&L.",
            "zh": "收款后现金闭环；余额进入账龄、计提与航次盈亏。",
        },
        "roles": {"en": "Finance desk; management reviews aging.", "zh": "财务岗位；管理层查看账龄。"},
        "help_slugs": ["finance-laytime", "documents"],
    },
    "ship": {
        "title": {"en": "Ship Management", "zh": "船舶管理"},
        "purpose": {
            "en": "Technical fleet file: technical profiles, statutory certificates, work orders, defects, crew and spares for managed vessels.",
            "zh": "船舶技术档案：技术资料、法定证书、工单、缺陷、船员与备件。",
        },
        "steps": [
            {"en": "1. Maintain the technical profile: class society, drydock and survey dates.", "zh": "1. 维护技术资料：船级社、坞修与特检日期。"},
            {"en": "2. Register every statutory certificate with issue and expiry dates.", "zh": "2. 登记每份法定证书的签发与到期日。"},
            {"en": "3. Upload the current certificate file so the latest scan is always attached.", "zh": "3. 上传证书当前版文件，保证随时可取最新扫描件。"},
            {"en": "4. Watch expiring/expired bands and renew before expiry.", "zh": "4. 盯临期/过期状态，到期前完成换证。"},
            {"en": "5. Plan work orders and track defects to closure.", "zh": "5. 安排工单并跟踪缺陷关闭。"},
            {"en": "6. Keep crew and spare-parts data aligned with the PMS.", "zh": "6. 保持船员与备件数据同 PMS 同步。"},
        ],
        "upstream": {"en": "Vessel masterdata; PMS connector sync where connected.", "zh": "船舶主数据；已接入的 PMS 连接器同步。"},
        "downstream": {
            "en": "Certificate alerts feed the workbench; drydock blocks appear on the schedule.",
            "zh": "证书提醒推送工作台；坞修时段自动出现在船期表。",
        },
        "roles": {"en": "Technical / superintendent; management monitors.", "zh": "机务/船长级主管；管理层监督。"},
        "help_slugs": ["ship-management"],
    },
    "exceptions": {
        "title": {"en": "Exception Centre", "zh": "异常中心"},
        "purpose": {
            "en": "Cross-desk problem queue: data-quality issues, schedule conflicts, certificate expiries and finance anomalies triaged in one list.",
            "zh": "跨台面问题队列：数据质量、船期冲突、证书到期与财务异常集中分诊处理。",
        },
        "steps": [
            {"en": "1. Scan the open list by severity, most severe first.", "zh": "1. 按严重度扫未处理清单，先重后轻。"},
            {"en": "2. Open the exception to see the owning entity (voyage, invoice, certificate).", "zh": "2. 打开异常，定位所属单据（航次、发票、证书）。"},
            {"en": "3. Fix the root cause in the owning page.", "zh": "3. 到对应业务页面修复根因。"},
            {"en": "4. Re-run the data-quality scan to confirm the issue clears.", "zh": "4. 重新跑数据质量扫描，确认问题消除。"},
            {"en": "5. Resolve or dismiss with a reason so the queue stays honest.", "zh": "5. 办结或注明原因驳回，保持队列真实可信。"},
            {"en": "6. Exceptions raised by system events land here too — check whether the fix belongs to a task rather than to you.", "zh": "6. 系统事件引发的异常也会落到这里 —— 先判断该由任务闭环，而不是你个人扛下。"},
        ],
        "upstream": {
            "en": "System scans (data quality, schedule, certificates), business events and manual reports.",
            "zh": "系统扫描（数据质量、船期、证书）、业务事件与人工上报。",
        },
        "downstream": {
            "en": "Resolved exceptions unblock laytime, invoicing and reporting downstream.",
            "zh": "异常清除后，下游的滞期、开票与报表才能顺利进行。",
        },
        "roles": {"en": "Operations, finance and management by exception type.", "zh": "按异常类型分给操作、财务与管理层。"},
        "help_slugs": ["voyages", "faq", "event-automation"],
    },
    "masterdata_vessels": {
        "title": {"en": "Vessel Masterdata", "zh": "船舶主数据"},
        "purpose": {
            "en": "The commercial fleet register: names, IMO/MMSI, flags, types and tonnage that every estimate, charter and voyage references.",
            "zh": "商业船队登记册：船名、IMO/MMSI、船旗、船型与吨位，供估算、租约与航次引用。",
        },
        "steps": [
            {"en": "1. Register each vessel once with its IMO number (unique per tenant).", "zh": "1. 每艘船按 IMO 号登记一次（租户内唯一）。"},
            {"en": "2. Fill type, DWT, speed and consumption — estimates depend on them.", "zh": "2. 填全船型、载重吨、航速与油耗——估算测算依赖这些值。"},
            {"en": "3. Keep flag and class-relevant data current after registry changes.", "zh": "3. 注册变更后及时更新船旗等信息。"},
            {"en": "4. Retire vessels with status changes instead of deleting history.", "zh": "4. 退役船用状态标记，不要删除历史。"},
        ],
        "upstream": {"en": "Manual registration or fleet import during onboarding.", "zh": "手工登记或上线时的船队导入。"},
        "downstream": {
            "en": "Referenced by estimates, charters, voyages, ship management and emissions.",
            "zh": "被估算、租约、航次、船舶管理与排放模块引用。",
        },
        "roles": {"en": "Tenant admin maintains; every desk reads.", "zh": "租户管理员维护；各台面引用。"},
        "help_slugs": ["getting-started", "ship-management"],
    },
    "workflows_inbox": {
        "title": {"en": "Approval Inbox", "zh": "审批收件箱"},
        "purpose": {
            "en": "Your pending approvals: charters and invoices waiting for your decision, with full context attached.",
            "zh": "待你审批的事项：等待决策的租约与发票，附完整上下文。",
        },
        "steps": [
            {"en": "1. Open the inbox and work the pending list oldest-first.", "zh": "1. 打开收件箱，按提交时间从旧到新处理。"},
            {"en": "2. Open an item and review the attached terms and amounts.", "zh": "2. 打开事项，核对所附条款与金额。"},
            {"en": "3. Approve when everything checks out; the document moves to its next state.", "zh": "3. 核对无误后批准，单据进入下一状态。"},
            {"en": "4. Reject with a written reason when terms must change.", "zh": "4. 条款需修改时驳回并写明原因。"},
            {"en": "5. Keep the inbox empty daily — approvals block invoicing and activation.", "zh": "5. 每日清空收件箱——审批卡住会阻塞开票与航次激活。"},
            {"en": "6. The chain itself is configured in System settings → Workflows: one role per step, and the initiator cannot approve their own submission.", "zh": "6. 审批链本身在「系统设置 → 工作流」配置：每个环节一个角色，且提交人不能审批自己的提交。"},
        ],
        "upstream": {"en": "Charter and invoice submissions from the desks.", "zh": "各台面提交的租约与发票。"},
        "downstream": {
            "en": "Approvals release charters to operations and invoices to issuance.", "zh": "批准后租约放行到运营、发票放行到开具。"},
        "roles": {"en": "Management and tenant admin approve; desks watch status.", "zh": "管理层与租户管理员审批；业务台面关注状态。"},
        "help_slugs": ["getting-started", "admin-security", "event-automation"],
    },
    "routine_hub": {
        "title": {"en": "Routine Task Hub", "zh": "例行任务中枢"},
        "purpose": {
            "en": "The inbox where automation stops: matching mail becomes a reviewed draft with per-field evidence, and only a second pair of eyes can confirm it.",
            "zh": "自动化停下来的地方：命中的邮件变成逐字段带依据的待复核草稿，且必须第二个人确认才能落库。",
        },
        "steps": [
            {"en": "1. Open Drafts and sort by age — the oldest waiting draft is the most urgent.", "zh": "1. 打开「草稿」按等待时长排序，越久等越急。"},
            {"en": "2. Read the evidence quote under each field: it shows the source line the value came from.", "zh": "2. 读每个字段下方的依据引用 —— 它显示该取值的来源原文行。"},
            {"en": "3. Tick the fields you accept; unticked fields are neither stored nor used in calculations.", "zh": "3. 勾选你认可的字段；未勾选的既不落库也不参与计算。"},
            {"en": "4. Adopt the selected fields to write them, or reject with a reason — rejects are recorded in the audit trail.", "zh": "4. 「采用所选字段」执行写入，或驳回并写明原因 —— 驳回记入审计轨迹。"},
            {"en": "5. Note the four-eyes rule: the person who triggered a draft cannot confirm it, so hand it to a colleague.", "zh": "5. 注意四眼原则：触发草稿的人不能确认，需转交同事。"},
            {"en": "6. Use Routine tasks to tune which mail triggers a task, and Skill templates to see what each extractor guarantees.", "zh": "6. 用「例行任务」调整哪些邮件触发任务，用「技能模板」查看每个抽取器保证产出什么。"},
        ],
        "upstream": {
            "en": "Inbound mail already synced from Microsoft 365, matched by trigger rules.",
            "zh": "已从 Microsoft 365 同步进来的来件邮件，由触发规则匹配。",
        },
        "downstream": {
            "en": "Adopted drafts write back a noon report, laytime calculation or estimate / charter draft — re-validated before storage.",
            "zh": "被采用的草稿回写船位报告、装卸时间计算或估算 / 租约草稿，落库前会重新校验。",
        },
        "roles": {"en": "Operations and chartering desks; the confirming colleague is usually another role holder.", "zh": "运营与租船台面；确认人通常是另一位同岗位同事。"},
        "help_slugs": ["routine-hub", "email-ai", "event-automation"],
    },
    "email_review": {
        "title": {"en": "Email Review", "zh": "邮件复核"},
        "purpose": {
            "en": "Turn inbound and outbound mail into reviewed business drafts: classify the mail, propose the action, and let a person confirm.",
            "zh": "把收发邮件变成待复核的业务草稿：先分类，再给出建议动作，最后由人确认。",
        },
        "steps": [
            {"en": "1. Sync your mailbox first — only mail already synced into MariOS is visible here.", "zh": "1. 先同步邮箱 —— 只有已同步进 MariOS 的邮件才在这里可见。"},
            {"en": "2. Work the review queue; the badge tells you whether rules or the model produced the suggestion.", "zh": "2. 处理复核队列；徽标说明建议来自规则还是模型。"},
            {"en": "3. Open a message to read the body, the parsed fields and the reason behind the suggested action.", "zh": "3. 打开邮件查看正文、解析字段以及给出该建议的理由。"},
            {"en": "4. Create the business draft (estimate + charter, NOR stamp, laytime, bunker, PDA, invoice, claim) and confirm in the dialog.", "zh": "4. 生成业务草稿（估算 + 租约、NOR 填报、装卸时间、加油、港口使费、账单、索赔）并在弹窗中确认。"},
            {"en": "5. Use Fill voyage estimate to push a recap into the estimate form — only ticked fields are written.", "zh": "5. 用「填入航次计算」把 recap 推入估算表单 —— 只有勾选的字段会写入。"},
            {"en": "6. Ignore irrelevant mail (with the remember option) or archive it onto the related voyage, invoice or claim.", "zh": "6. 忽略无关邮件（可勾选记住），或把它存档到关联的航次、账单或索赔上。"},
        ],
        "upstream": {
            "en": "Microsoft 365 mail folders: inbox, sent and custom folders, with a configurable sync window.",
            "zh": "Microsoft 365 邮箱文件夹：收件箱、已发送与自定义文件夹，同步时间窗可配置。",
        },
        "downstream": {
            "en": "Drafts feed the estimating, chartering, operations and finance desks once confirmed.",
            "zh": "确认后的草稿流向估算、租船、运营与财务台面。",
        },
        "roles": {"en": "Chartering and operations desks; tenant admin connects the mailbox.", "zh": "租船与运营台面；租户管理员负责连接邮箱。"},
        "help_slugs": ["email-ai", "microsoft-365", "routine-hub"],
    },
    "ai_chat": {
        "title": {"en": "MariAI Chat", "zh": "MariAI 对话"},
        "purpose": {
            "en": "A question-and-answer desk over your own data: preset agents answer about TCE, voyage P&L, port distances and compliance, and show which tools they used.",
            "zh": "基于自有数据的问答台：预置智能体回答 TCE、航次盈亏、港口距离与合规问题，并展示用到的取数工具。",
        },
        "steps": [
            {"en": "1. Seed the agents from the empty-state button if none exist yet.", "zh": "1. 若还没有智能体，先从空状态按钮一键创建。"},
            {"en": "2. Pick the agent that matches your question — Voyage Advisor, Compliance, Market Analyst or Mari Copilot.", "zh": "2. 选择与问题匹配的智能体 —— 航次顾问、合规、市场分析师或 Mari Copilot。"},
            {"en": "3. Ask in plain language; the assistant uses the tenant's own data, not generic answers.", "zh": "3. 用自然语言提问；助手调用租户自己的数据，而不是泛泛而谈。"},
            {"en": "4. Check the Tool calls panel to see which figures the answer was built on.", "zh": "4. 查看「工具调用」面板，确认答案依据的是哪些数据。"},
            {"en": "5. Open any record the answer links to and finish the work there — the chat never writes for you.", "zh": "5. 打开回答中链接的单据去完成工作 —— 对话不会替你写入数据。"},
        ],
        "upstream": {
            "en": "Tenant data accessed through the AI Hub's configured providers and skills.",
            "zh": "租户数据，经 AI Hub 配置的提供商与技能访问。",
        },
        "downstream": {
            "en": "Answers point back to the owning desk page, where the actual record is changed.",
            "zh": "回答会指回对应的业务页面，真正的单据修改在那里完成。",
        },
        "roles": {"en": "All roles; tenant admins govern providers, models and usage in AI Hub.", "zh": "所有角色；租户管理员在 AI Hub 管理提供商、模型与用量。"},
        "help_slugs": ["ai-assistant", "admin-security"],
    },
    "ai_settings": {
        "title": {"en": "AI Hub", "zh": "AI Hub"},
        "purpose": {
            "en": "Tenant-level control of the AI layer: which providers may be called, which model answers which skill, and how much has been used.",
            "zh": "租户级的 AI 控制面：允许调用哪些提供商、哪个技能用哪个模型、用了多少。",
        },
        "steps": [
            {"en": "1. Add a provider in Providers tab and test connectivity before saving.", "zh": "1. 在「提供商」页签添加提供商并测试连通性后再保存。"},
            {"en": "2. Keys are encrypted at rest and never returned in clear; a tenant's own key is not billed by the platform.", "zh": "2. 密钥静态加密且不再明文返回；租户自有密钥不计平台费用。"},
            {"en": "3. Set the default model in Model settings and override it per agent where needed.", "zh": "3. 在「模型设置」设默认模型，必要时按智能体覆盖。"},
            {"en": "4. Bind a skill to a primary provider with an optional fallback in Skill bindings.", "zh": "4. 在「技能绑定」把技能绑定到主用提供商，并可设备用提供商。"},
            {"en": "5. Watch the Usage tab: requests, tokens, latency by agent, conversation and by day.", "zh": "5. 关注「用量」页签：请求数、token、按智能体的延迟、按会话与按日分布。"},
        ],
        "upstream": {
            "en": "Provider endpoints and credentials owned by the tenant.",
            "zh": "租户自有的提供商端点与凭据。",
        },
        "downstream": {
            "en": "Determines how the assistant, MariAI chat and the mail review features behave for this tenant.",
            "zh": "决定本租户的助手、MariAI 对话与邮件复核功能的表现。",
        },
        "roles": {"en": "Tenant administrators only.", "zh": "仅租户管理员。"},
        "help_slugs": ["ai-assistant", "admin-security"],
    },
}


def get_guide(page_key: str) -> dict[str, Any] | None:
    guide = GUIDES.get(page_key)
    if guide is None:
        return None
    return {"page_key": page_key, **guide}
