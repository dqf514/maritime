"""索赔分类体系（Phase 1 / D10）：受控字典 + GL 科目映射 + 默认时效天数。

claim_type 历史上是自由字符串（默认 demurrage）。本模块把它升级为受控
字典：创建/更新时校验（未知类型 → 422 INVALID_CLAIM_TYPE），读取保持
宽容（存量自由值不报错，逐步收敛）。GL 科目映射供过账引擎按类型取科目；
time_bar_days 用于按类型给默认索赔时效（可被显式 time_bar 覆盖）。

子类（CLAIM_SUBTYPES）把大类拆成可统计的细类：demurrage →
loading_delay / discharge_delay / weather / port_congestion / documentation。
动作（CLAIM_ACTIONS）跟踪索赔处置：negotiate / litigate / arbitrate /
settle / write_off，落库到 claim_actions（见 ClaimAction 模型）。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

CLAIM_TYPES: dict[str, dict[str, Any]] = {
    "demurrage": {
        "label": {"en": "Demurrage", "zh": "滞期费"},
        "gl_account": "5101",
        "time_bar_days": 90,
    },
    "despatch": {
        "label": {"en": "Despatch", "zh": "速遣费"},
        "gl_account": "5102",
        "time_bar_days": 90,
    },
    "off_hire": {
        "label": {"en": "Off-hire", "zh": "停租扣款"},
        "gl_account": "5110",
        "time_bar_days": 60,
    },
    "performance": {
        "label": {"en": "Speed / consumption claim", "zh": "航速油耗索赔"},
        "gl_account": "5120",
        "time_bar_days": 90,
    },
    "cargo_damage": {
        "label": {"en": "Cargo damage / shortage", "zh": "货损货差"},
        "gl_account": "5130",
        "time_bar_days": 365,
    },
    "pda_difference": {
        "label": {"en": "PDA/FDA difference", "zh": "港口使费差异"},
        "gl_account": "5140",
        "time_bar_days": 60,
    },
    "insurance": {
        "label": {"en": "Insurance recovery", "zh": "保险追偿"},
        "gl_account": "5150",
        "time_bar_days": 365,
    },
    "other": {
        "label": {"en": "Other", "zh": "其他"},
        "gl_account": "5199",
        "time_bar_days": 90,
    },
}

# 大类 → 子类字典（子类按大类校验归属；未知组合 → 422 INVALID_CLAIM_SUBTYPE）
CLAIM_SUBTYPES: dict[str, dict[str, dict[str, Any]]] = {
    "demurrage": {
        "loading_delay": {"label": {"en": "Loading delay", "zh": "装货延误"}},
        "discharge_delay": {"label": {"en": "Discharge delay", "zh": "卸货延误"}},
        "weather": {"label": {"en": "Weather", "zh": "天气"}},
        "port_congestion": {"label": {"en": "Port congestion", "zh": "港口拥堵"}},
        "documentation": {"label": {"en": "Documentation", "zh": "单证"}},
    },
    "despatch": {
        "quick_loading": {"label": {"en": "Quick loading", "zh": "快装"}},
        "quick_discharge": {"label": {"en": "Quick discharge", "zh": "快卸"}},
    },
    "off_hire": {
        "breakdown": {"label": {"en": "Breakdown", "zh": "机械故障"}},
        "dry_dock": {"label": {"en": "Dry dock", "zh": "坞修"}},
        "detention": {"label": {"en": "Detention", "zh": "滞留"}},
        "strike": {"label": {"en": "Strike", "zh": "罢工"}},
        "deficiency": {"label": {"en": "Deficiency", "zh": "缺陷"}},
    },
    "cargo_damage": {
        "shortage": {"label": {"en": "Shortage", "zh": "短量"}},
        "wetting": {"label": {"en": "Wetting", "zh": "水湿"}},
        "contamination": {"label": {"en": "Contamination", "zh": "污染"}},
        "breakage": {"label": {"en": "Breakage", "zh": "破损"}},
    },
    "performance": {
        "speed_shortfall": {"label": {"en": "Speed shortfall", "zh": "航速不足"}},
        "over_consumption": {"label": {"en": "Over consumption", "zh": "超耗"}},
    },
}

# 索赔处置动作（ClaimAction.action_type 受控字典）
CLAIM_ACTIONS: dict[str, dict[str, Any]] = {
    "negotiate": {"label": {"en": "Negotiate", "zh": "谈判"}},
    "litigate": {"label": {"en": "Litigate", "zh": "诉讼"}},
    "arbitrate": {"label": {"en": "Arbitrate", "zh": "仲裁"}},
    "settle": {"label": {"en": "Settle", "zh": "和解结清"}},
    "write_off": {"label": {"en": "Write off", "zh": "核销"}},
}


def is_valid_claim_type(claim_type: str) -> bool:
    return claim_type in CLAIM_TYPES


def assert_claim_type(claim_type: str) -> str:
    if not is_valid_claim_type(claim_type):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CLAIM_TYPE",
                "message": f"Unknown claim_type '{claim_type}'",
                "allowed": sorted(CLAIM_TYPES),
            },
        )
    return claim_type


def subtypes_for(claim_type: str) -> dict[str, dict[str, Any]]:
    return CLAIM_SUBTYPES.get(claim_type) or {}


def is_valid_claim_subtype(claim_type: str, subtype: str) -> bool:
    return subtype in subtypes_for(claim_type)


def assert_claim_subtype(claim_type: str, subtype: str) -> str:
    if not is_valid_claim_subtype(claim_type, subtype):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CLAIM_SUBTYPE",
                "message": f"Unknown subtype '{subtype}' for claim_type '{claim_type}'",
                "allowed": sorted(subtypes_for(claim_type)),
            },
        )
    return subtype


def is_valid_claim_action(action_type: str) -> bool:
    return action_type in CLAIM_ACTIONS


def assert_claim_action(action_type: str) -> str:
    if not is_valid_claim_action(action_type):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CLAIM_ACTION",
                "message": f"Unknown action_type '{action_type}'",
                "allowed": sorted(CLAIM_ACTIONS),
            },
        )
    return action_type


def claim_types_payload() -> dict[str, Any]:
    """/claims/types 响应：大类字典 + 各自子类 + 处置动作字典。"""
    items = []
    for code, meta in CLAIM_TYPES.items():
        subtypes = [
            {"code": scode, **smeta} for scode, smeta in subtypes_for(code).items()
        ]
        items.append({"code": code, **meta, "subtypes": subtypes})
    actions = [{"code": code, **meta} for code, meta in CLAIM_ACTIONS.items()]
    return {"items": items, "actions": actions}


def gl_account_for(claim_type: str) -> str:
    return (CLAIM_TYPES.get(claim_type) or CLAIM_TYPES["other"])["gl_account"]


def default_time_bar_days(claim_type: str) -> int:
    return int((CLAIM_TYPES.get(claim_type) or CLAIM_TYPES["other"])["time_bar_days"])
