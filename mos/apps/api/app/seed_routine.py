"""例行任务中枢种子数据。

三类数据，性质不同：

* **平台技能模板**（``tenant_id IS NULL``）—— 属于平台目录（和 SaaS/i18n/参考数据
  同级），任何租户都能用，租户可复制后自改。启动时随 catalog 一起种下。
* **试点例行任务**（demo 租户）—— 属于演示数据，只在 ``SEED_DEMO=true`` 时种下。
* **试点入站邮件**（demo 租户）—— 三封，正好命中三条例行任务的触发规则；
  船名/航次号/对手方都指向 demo 租户里真实存在的实体，保证「人工确认 → 落库」
  有对象可落（不然只能演示到草稿这一步）。

技能模板里的字段契约是**数据不是代码**：新增一种抽取类型只要加一条模板，
不用改引擎。字段清单见 :mod:`app.services.skill_runtime`。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_routine import RoutineTask, SkillTemplate, TriggerRule

log = logging.getLogger("marios.seed_routine")


#: 平台技能模板（tenant_id = NULL）
PLATFORM_SKILLS: tuple[dict[str, Any], ...] = (
    {
        "code": "noon_report",
        "name": "Noon report intake",
        "purpose": "船长/代理午报邮件 → 午报草稿（船位、油耗、ETA、天气）",
        "prompt_template": (
            "从这封午报邮件中抽取字段。只输出 JSON，不要解释。"
            "字段：vessel, voyage_no, report_at, lat, lon, speed, rob_fo, rob_do, "
            "eta_next, sea_state, wind_bf, current_kn。原文没有的字段不要编造。"
        ),
        "output_schema": {
            "kind": "noon_report",
            "required": ["report_at"],
            "fields": {
                "vessel": {"type": "string"},
                "voyage_no": {"type": "string"},
                "report_at": {"type": "datetime", "required": True},
                "lat": {"type": "number"},
                "lon": {"type": "number"},
                "speed": {"type": "number"},
                "rob_fo": {"type": "number"},
                "rob_do": {"type": "number"},
                "eta_next": {"type": "datetime"},
                "sea_state": {"type": "string"},
                "wind_bf": {"type": "number"},
                "current_kn": {"type": "number"},
            },
        },
        "validator_rules": {
            "ranges": {
                "lat": [-90, 90],
                "lon": [-180, 180],
                "speed": [0, 60],
                "wind_bf": [0, 20],
                "current_kn": [0, 10],
            }
        },
        "deterministic_engine": None,
    },
    {
        "code": "laytime_statement",
        "name": "SOF / laytime statement intake",
        "purpose": "装卸时间事实（SOF）邮件 → 装卸时间计算草稿",
        "prompt_template": (
            "从这封 Statement of Facts 邮件中抽取字段。只输出 JSON，不要解释。"
            "字段：vessel, voyage_no, events[{time,event}], allowed_days。"
            "原文没有的字段不要编造。"
        ),
        "output_schema": {
            "kind": "laytime_statement",
            "required": ["events"],
            "fields": {
                "vessel": {"type": "string"},
                "voyage_no": {"type": "string"},
                "events": {"type": "array", "required": True},
                "allowed_days": {"type": "number"},
            },
        },
        "validator_rules": {"ranges": {"allowed_days": [0, 365]}},
        "deterministic_engine": None,
    },
    {
        "code": "fixture_recap",
        "name": "Fixture recap intake",
        "purpose": "租约意向书（recap）邮件 → 估价/租约草稿",
        "prompt_template": (
            "从这封租约意向书邮件中抽取字段。只输出 JSON，不要解释。"
            "字段：vessel, cargo, load_port, discharge_port, laycan, freight_rate, "
            "demurrage_rate, despatch_rate, commission, charterers, owners, laytime_load, "
            "laytime_discharge。原文没有的字段不要编造。"
        ),
        "output_schema": {
            "kind": "fixture_recap",
            "required": ["vessel"],
            "fields": {
                "vessel": {"type": "string", "required": True},
                "cargo": {"type": "string"},
                "load_port": {"type": "string"},
                "discharge_port": {"type": "string"},
                "laycan": {"type": "string"},
                "freight_rate": {"type": "number"},
                "demurrage_rate": {"type": "number"},
                "despatch_rate": {"type": "number"},
                "commission": {"type": "number"},
                "charterers": {"type": "string"},
                "owners": {"type": "string"},
                "laytime_load": {"type": "number"},
                "laytime_discharge": {"type": "number"},
            },
        },
        "validator_rules": {
            "ranges": {
                "freight_rate": [0, 1_000_000],
                "demurrage_rate": [0, 1_000_000],
                "despatch_rate": [0, 1_000_000],
                "commission": [0, 100],
            }
        },
        "deterministic_engine": None,
    },
)


def seed_platform_skills(db: Session) -> None:
    """种下平台技能模板（幂等 —— 按 code 去重，模板内容更新时覆盖）。"""
    for spec in PLATFORM_SKILLS:
        row = db.scalar(
            select(SkillTemplate).where(
                SkillTemplate.tenant_id.is_(None), SkillTemplate.code == spec["code"]
            )
        )
        if row is None:
            row = SkillTemplate(
                tenant_id=None,
                code=spec["code"],
                name=spec["name"],
                purpose=spec["purpose"],
                prompt_template=spec["prompt_template"],
                output_schema=spec["output_schema"],
                validator_rules=spec["validator_rules"],
                allowed_tools=[],
                deterministic_engine=spec["deterministic_engine"],
                version=1,
                enabled=True,
            )
            db.add(row)
        else:
            row.name = spec["name"]
            row.purpose = spec["purpose"]
            row.prompt_template = spec["prompt_template"]
            row.output_schema = spec["output_schema"]
            row.validator_rules = spec["validator_rules"]
            row.enabled = True
    db.flush()


#: 试点例行任务（demo 租户）—— 三条：午报 / 装卸时间 / 租约意向书
PILOT_TASKS: tuple[dict[str, Any], ...] = (
    {
        "code": "noon_report_intake",
        "name": "Noon report → noon report draft",
        "module_code": "operations",
        "skill_code": "noon_report",
        "output_target": "noon_report",
        "owner_role": "operations",
        "sla_minutes": 60,
        "trigger": {
            "subject_regex": r"noon\s*report|position\s*report|午报",
            "body_markers": ["lat"],
            "folder": "inbox",
            "direction": "inbound",
        },
    },
    {
        "code": "laytime_statement_intake",
        "name": "SOF → laytime calculation draft",
        "module_code": "laytime",
        "skill_code": "laytime_statement",
        "output_target": "laytime_calc",
        "owner_role": "operations",
        "sla_minutes": 120,
        "trigger": {
            "subject_regex": r"statement\s*of\s*facts|laytime|sof\b",
            "folder": "inbox",
            "direction": "inbound",
        },
    },
    {
        "code": "fixture_recap_intake",
        "name": "Fixture recap → estimate / chartering draft",
        "module_code": "chartering",
        "skill_code": "fixture_recap",
        "output_target": "estimate",
        "owner_role": "chartering",
        "sla_minutes": 240,
        "trigger": {
            "subject_regex": r"recap|fixture",
            "folder": "inbox",
            "direction": "inbound",
        },
    },
)


def seed_demo_routine_tasks(db: Session, tenant_id: Any) -> None:
    """给指定租户种下试点例行任务（幂等 —— 按 tenant_id + code 去重）。"""
    for spec in PILOT_TASKS:
        task = db.scalar(
            select(RoutineTask).where(
                RoutineTask.tenant_id == tenant_id, RoutineTask.code == spec["code"]
            )
        )
        if task is None:
            task = RoutineTask(
                tenant_id=tenant_id,
                code=spec["code"],
                name=spec["name"],
                direction="inbound",
                module_code=spec["module_code"],
                trigger_type="inbound_email",
                trigger_config={},
                skill_code=spec["skill_code"],
                output_target=spec["output_target"],
                owner_role=spec["owner_role"],
                sla_minutes=spec["sla_minutes"],
                dedupe_key_template="message:{message_id}",
                enabled=True,
            )
            db.add(task)
            db.flush()
        trigger = spec["trigger"]
        existing = db.scalar(
            select(TriggerRule).where(
                TriggerRule.tenant_id == tenant_id,
                TriggerRule.routine_task_id == task.id,
            )
        )
        if existing is None:
            db.add(
                TriggerRule(
                    tenant_id=tenant_id,
                    routine_task_id=task.id,
                    sender_emails=[],
                    sender_domains=[],
                    subject_regex=trigger.get("subject_regex"),
                    body_markers=trigger.get("body_markers") or [],
                    folder=trigger.get("folder"),
                    direction=trigger.get("direction"),
                    priority=100,
                    enabled=True,
                )
            )
        else:
            existing.subject_regex = trigger.get("subject_regex")
            existing.body_markers = trigger.get("body_markers") or []
            existing.folder = trigger.get("folder")
            existing.direction = trigger.get("direction")
            existing.enabled = True
    db.flush()


#: 试点入站邮件（demo 租户）—— 三封，一封对一条例行任务。
#: 船名 / 航次号 / 对手方都用 demo 租户里**真实存在**的实体：
#: MV PACIFIC STAR → VOY-2407（in_progress）、MV DEMO WAVE → VOY-2408（planned）、
#: MV ATLANTIC PEARL（IMO 9000003）+ 对手方 Nordic Grain Traders。
#: 这样「人工确认 → 落库」才有对象可落 —— 否则只能演示到草稿这一步。
PILOT_EMAILS: tuple[dict[str, Any], ...] = (
    {
        "message_id": "<pilot-noon-demo.marios>",
        "from_email": "master@oceanstar-agency.nl",
        "subject": "Noon Report — MV PACIFIC STAR / VOY-2407",
        "task_code": "noon_report_intake",
        "hours_ago": 2,
        "body": (
            "Noon Report - MV PACIFIC STAR\n"
            "Vessel: MV PACIFIC STAR\n"
            "Voyage: VOY-2407\n"
            "Report at: {today} 04:00\n"
            "Lat: 51.9\n"
            "Lon: 4.4\n"
            "Speed: 11.9\n"
            "ROB FO: 1520\n"
            "ROB DO: 980\n"
            "ETA next: {tomorrow} 08:00\n"
            "Sea state: slight\n"
            "Wind BF: 4\n"
            "Current: 0.6\n"
            "Remarks: Approaching Rotterdam, pilot booked for 08:00.\n"
        ),
    },
    {
        "message_id": "<pilot-sof-demo.marios>",
        "from_email": "sof@rotterdamagency.nl",
        "subject": "Statement of Facts — MV DEMO WAVE / VOY-2408",
        "task_code": "laytime_statement_intake",
        "hours_ago": 4,
        "body": (
            "Statement of Facts - MV DEMO WAVE\n"
            "Voyage: VOY-2408\n"
            "Port: Rotterdam (NLRTM)\n"
            "\n"
            "12-10 08:00 Vessel alongside berth 4\n"
            "12-10 12:00 Commencement of laytime\n"
            "12-12 10:30 Notice of readiness tendered\n"
            "12-14 16:00 Laytime terminated\n"
            "\n"
            "Total: 3.5 days\n"
            "Remarks: 1 day saved time.\n"
        ),
    },
    {
        "message_id": "<pilot-recap-demo.marios>",
        "from_email": "chartering@nordicgrain.no",
        "subject": "Fixture Recap — MV ATLANTIC PEARL / SGSIN-NLRTM Coal",
        "task_code": "fixture_recap_intake",
        "hours_ago": 6,
        "body": (
            "Fixture Recap - MV ATLANTIC PEARL\n"
            "Vessel: MV ATLANTIC PEARL\n"
            "Charterers: Nordic Grain Traders\n"
            "Owners: Demo Shipping Ltd\n"
            "Cargo: Coal\n"
            "Loading Port: SGSIN\n"
            "Discharge Port: NLRTM\n"
            "Laycan: {laycan_from} - {laycan_to}\n"
            "Freight Rate: USD 18.5 per MT\n"
            "Demurrage: USD 12000 per day\n"
            "Despatch: USD 6000 per day\n"
            "Laytime: 2 days\n"
            "Commission: 1.5%\n"
        ),
    },
)


def seed_routine_pilot_emails(db: Session, tenant_id: Any) -> None:
    """给 demo 租户种下三封试点入站邮件（幂等 upsert —— 按 message_id 定位）。

    这三封是**中枢的演示输入**：命中三条例行任务的触发规则 → 生成待确认草稿 →
    人工确认 → 落进午报 / 装卸时间 / 估算+租约三类业务表。

    upsert 而不是纯插入：试点邮件的正文会随演示需要调整（补一行 Vessel: 让船名
    变成有证据的字段），改了正文就应当同步到已存在的行，否则老草稿/新草稿的
    口径会不一致。
    """
    from app.models_wave1 import EmailMessage

    now = datetime.now(timezone.utc)
    ctx = {
        "today": now.strftime("%Y-%m-%d"),
        "tomorrow": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        "laycan_from": (now + timedelta(days=2)).strftime("%Y-%m-%d"),
        "laycan_to": (now + timedelta(days=12)).strftime("%Y-%m-%d"),
    }
    for spec in PILOT_EMAILS:
        body = str(spec["body"]).format(**ctx)
        row = db.scalar(
            select(EmailMessage).where(
                EmailMessage.tenant_id == tenant_id,
                EmailMessage.message_id == spec["message_id"],
            )
        )
        if row is None:
            db.add(
                EmailMessage(
                    tenant_id=tenant_id,
                    message_id=spec["message_id"],
                    direction="inbound",
                    folder="inbox",
                    from_email=spec["from_email"],
                    subject=spec["subject"],
                    body_text=body,
                    sent_at=now - timedelta(hours=spec.get("hours_ago", 1)),
                    parse_status="review",
                    parse_result={},
                )
            )
            continue
        # 已有行：正文/主题与模板不一致时同步（演示数据保持一致）
        if row.body_text != body:
            row.body_text = body
            row.subject = spec["subject"]
            row.from_email = spec["from_email"]
    db.flush()
