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
            {"en": "5. Use Ctrl+K to jump directly to any document or page.", "zh": "5. 用 Ctrl+K 直接跳转到任何单据或页面。"},
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
        "help_slugs": ["welcome", "getting-started"],
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
        ],
        "upstream": {
            "en": "Manual entries and system events (approvals, expiry alerts, exception scans).",
            "zh": "手工录入与系统事件（审批、到期提醒、异常扫描）。",
        },
        "downstream": {
            "en": "Completed tasks close the loop; assignees receive notifications.",
            "zh": "任务办结形成闭环；被指派人会收到通知。",
        },
        "roles": {"en": "All roles; tenant admin and management see the tenant-wide list.", "zh": "所有角色；租户管理员与管理层可查看全租户清单。"},
        "help_slugs": ["getting-started"],
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
        "help_slugs": ["estimates"],
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
        ],
        "upstream": {"en": "Converted estimates and counterparty masterdata.", "zh": "由估算转换而来，并引用对手方主数据。"},
        "downstream": {
            "en": "Approved charters activate voyages; terms drive laytime, demurrage and freight invoicing.",
            "zh": "批准的租约激活航次；条款驱动滞期费计算与运费开票。",
        },
        "roles": {"en": "Chartering desk creates; management approves.", "zh": "租船台面录入；管理层审批。"},
        "help_slugs": ["charters"],
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
        ],
        "upstream": {"en": "Approved charters from the chartering desk.", "zh": "租船台面批准的租约。"},
        "downstream": {
            "en": "Completed voyages feed laytime/demurrage, freight invoices, claims and voyage P&L.",
            "zh": "完成的航次流向滞期/索赔、运费发票与航次盈亏。",
        },
        "roles": {"en": "Operations desk runs it; demurrage and finance consume the output.", "zh": "操作岗位主导；滞期与财务岗位使用其产出。"},
        "help_slugs": ["voyages"],
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
        "help_slugs": ["finance-laytime"],
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
        ],
        "upstream": {
            "en": "System scans (data quality, schedule, certificates) plus manual reports.",
            "zh": "系统扫描（数据质量、船期、证书）与人工上报。",
        },
        "downstream": {
            "en": "Resolved exceptions unblock laytime, invoicing and reporting downstream.",
            "zh": "异常清除后，下游的滞期、开票与报表才能顺利进行。",
        },
        "roles": {"en": "Operations, finance and management by exception type.", "zh": "按异常类型分给操作、财务与管理层。"},
        "help_slugs": ["voyages", "faq"],
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
        ],
        "upstream": {"en": "Charter and invoice submissions from the desks.", "zh": "各台面提交的租约与发票。"},
        "downstream": {
            "en": "Approvals release charters to operations and invoices to issuance.", "zh": "批准后租约放行到运营、发票放行到开具。"},
        "roles": {"en": "Management and tenant admin approve; desks watch status.", "zh": "管理层与租户管理员审批；业务台面关注状态。"},
        "help_slugs": ["getting-started", "admin-security"],
    },
}


def get_guide(page_key: str) -> dict[str, Any] | None:
    guide = GUIDES.get(page_key)
    if guide is None:
        return None
    return {"page_key": page_key, **guide}
