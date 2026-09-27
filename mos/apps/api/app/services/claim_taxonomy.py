"""索赔分类体系（Phase 1 / D10）：受控字典 + GL 科目映射 + 默认时效天数。

claim_type 历史上是自由字符串（默认 demurrage）。本模块把它升级为受控
字典：创建/更新时校验（未知类型 → 422 INVALID_CLAIM_TYPE），读取保持
宽容（存量自由值不报错，逐步收敛）。GL 科目映射供过账引擎按类型取科目；
time_bar_days 用于按类型给默认索赔时效（可被显式 time_bar 覆盖）。
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


def gl_account_for(claim_type: str) -> str:
    return (CLAIM_TYPES.get(claim_type) or CLAIM_TYPES["other"])["gl_account"]


def default_time_bar_days(claim_type: str) -> int:
    return int((CLAIM_TYPES.get(claim_type) or CLAIM_TYPES["other"])["time_bar_days"])
