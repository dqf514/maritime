"""条款库服务（D1）：系统条款包 + 查询 + 计算参数物化。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models_clause import ClauseTemplate

# 系统内置条款包：code 唯一，params 直接对应计算引擎输入键
SYSTEM_CLAUSE_PACK: list[dict[str, Any]] = [
    {
        "code": "DEM_ALWAYS",
        "cp_form": "GENCON",
        "category": "demurrage",
        "title_en": "Once on demurrage, always on demurrage",
        "title_zh": "一旦滞期永远滞期",
        "params": {"once_on_demurrage": True},
        "text": "Once on demurrage always on demurrage, time used in loading/discharging beyond the laytime shall count as demurrage even if excepted periods intervene.",
    },
    {
        "code": "DESP_HALF",
        "cp_form": "GENCON",
        "category": "demurrage",
        "title_en": "Despatch half demurrage",
        "title_zh": "速遣费按滞期费半数",
        "params": {"despatch_half": True},
        "text": "Despatch money shall be paid at half the demurrage rate.",
    },
    {
        "code": "NOR_WIBON",
        "cp_form": "GENCON",
        "category": "nor",
        "title_en": "NOR whether in berth or not (WIBON)",
        "title_zh": "NOR 无论靠泊与否",
        "params": {"nor_terms": "WIBON"},
        "text": "Notice of Readiness to be tendered whether in berth or not.",
    },
    {
        "code": "NOR_WCCON",
        "cp_form": "GENCON",
        "category": "nor",
        "title_en": "NOR whether in free pratique or not (WCCON)",
        "title_zh": "NOR 无论清关与否",
        "params": {"nor_terms": "WCCON"},
        "text": "Notice of Readiness to be tendered whether in free pratique or not.",
    },
    {
        "code": "NOR_BERTH_ONLY",
        "cp_form": None,
        "category": "nor",
        "title_en": "NOR valid only in berth (waiting before berth excluded)",
        "title_zh": "NOR 靠泊方为有效（靠泊前等泊不计）",
        "params": {"nor_terms": "BERTH_ONLY"},
        "text": "Notice of Readiness shall be valid only when the vessel is in berth; waiting time before berthing shall not count as laytime.",
    },
    {
        "code": "LAY_SHINC",
        "cp_form": "GENCON",
        "category": "laytime",
        "title_en": "Laytime SHINC",
        "title_zh": "装卸时间星期日及假日包括",
        "params": {"laytime_terms": "SHINC"},
        "text": "Laytime shall not count Sundays and Holidays included.",
    },
    {
        "code": "LAY_SHEX_EIU",
        "cp_form": "NYPE",
        "category": "laytime",
        "title_en": "Laytime SHEX even if used",
        "title_zh": "装卸时间 SHEX 即使使用",
        "params": {"laytime_terms": "SHEX EIU"},
        "text": "Sundays and Holidays excepted, even if used.",
    },
    {
        "code": "TIME_BAR_90D",
        "cp_form": None,
        "category": "general",
        "title_en": "Demurrage claim time bar 90 days",
        "title_zh": "滞期费索赔时效 90 天",
        "params": {"time_bar_days": 90},
        "text": "Any demurrage claim must be submitted within 90 days of completion of discharge.",
    },
    {
        "code": "OFFHIRE_DEFICIENCY",
        "cp_form": "NYPE",
        "category": "off_hire",
        "title_en": "Off-hire: deficiency of men/master breakdown",
        "title_zh": "停租：缺员/故障/船长不履行",
        "params": {"off_hire_events": ["deficiency_of_men", "breakdown", "default_of_master"]},
        "text": "In the event of loss of time from deficiency and/or default of men/master, breakdown of machinery, the hire shall cease for the time thereby lost.",
    },
    {
        "code": "ETS_CHARTERER",
        "cp_form": None,
        "category": "general",
        "title_en": "EU ETS costs for charterer's account",
        "title_zh": "欧盟 ETS 成本由租家承担",
        "params": {"ets_responsibility": "charterer"},
        "text": "All EU ETS allowances for the charter period shall be for the Charterers' account.",
    },
]


def seed_clause_pack(db: Session) -> int:
    """系统条款包入库（幂等：已有任何系统条款即跳过）。"""
    exists = db.scalar(select(ClauseTemplate.id).where(ClauseTemplate.is_system.is_(True)).limit(1))
    if exists is not None:
        return 0
    for item in SYSTEM_CLAUSE_PACK:
        db.add(ClauseTemplate(tenant_id=None, is_system=True, **item))
    db.commit()
    return len(SYSTEM_CLAUSE_PACK)


def list_clauses(
    db: Session,
    tenant_id: UUID,
    *,
    cp_form: str | None = None,
    category: str | None = None,
) -> list[ClauseTemplate]:
    q = select(ClauseTemplate).where(or_(ClauseTemplate.tenant_id.is_(None), ClauseTemplate.tenant_id == tenant_id))
    if cp_form:
        q = q.where(or_(ClauseTemplate.cp_form.is_(None), ClauseTemplate.cp_form == cp_form))
    if category:
        q = q.where(ClauseTemplate.category == category)
    return list(db.scalars(q.order_by(ClauseTemplate.cp_form, ClauseTemplate.code)).all())


def materialize_params(db: Session, tenant_id: UUID, codes: list[str]) -> dict[str, Any]:
    """把条款 code 列表合并为计算参数（后出现的覆盖先出现的）。"""
    if not codes:
        return {}
    rows = db.scalars(
        select(ClauseTemplate).where(
            or_(ClauseTemplate.tenant_id.is_(None), ClauseTemplate.tenant_id == tenant_id),
            ClauseTemplate.code.in_(codes),
        )
    ).all()
    merged: dict[str, Any] = {}
    for row in rows:
        merged.update(row.params or {})
    return merged
