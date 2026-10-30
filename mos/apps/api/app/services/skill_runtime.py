"""技能运行时 —— 受限技能的固定四腿。

一个技能 = **一个抽取类型 + 一份字段契约 + 一组校验规则 + 可选的确定性引擎**。
执行顺序固定（顺序本身就是风控）：

1. **规则腿** —— 正则/关键字规则解析（便宜、确定、可离线）
2. **LLM 腿** —— 结构化抽取（长邮件、非标格式、多语种）；失败自动回落规则
3. **确定性引擎腿** —— 算账一律走现有引擎（laytime/estimate/carbon）；
   **AI 不碰金额与天数**
4. **校验腿** —— 字段级必填/范围/枚举；不通过就不生成草稿

产出（:class:`SkillResult`）里的 **evidence** 是硬约束：
每个字段都必须能在原文里指回一行出处，指不回的字段直接丢弃 ——
「无证据不落库」是中枢的第一条红线。

字段契约放在 ``SkillTemplate.output_schema``（数据，不是代码）::

    {
      "kind": "noon_report",
      "fields": {"report_at": {"type": "datetime", "required": true}},
      "required": ["report_at"]
    }

校验规则放在 ``SkillTemplate.validator_rules``::

    {"ranges": {"lat": [-90, 90]}, "one_of": {"currency": ["USD", "EUR"]}}
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

log = logging.getLogger("marios.skill_runtime")

#: 抽取类型 → 规则解析器（规则腿）。缺规则解析器的类型只有 LLM 腿。
RULE_PARSERS: dict[str, Any] = {}


def _register_rule_parsers() -> None:
    """规则解析器注册（延迟导入，避免模块级循环依赖）。"""
    if RULE_PARSERS:
        return
    from app.services.email_intelligence import (
        parse_bunker_offer,
        parse_fixture_recap,
        parse_laytime_statement,
        parse_nor,
        parse_port_disbursement,
    )

    RULE_PARSERS.update(
        {
            "fixture_recap": parse_fixture_recap,
            "nor": parse_nor,
            "laytime_statement": parse_laytime_statement,
            "bunker_offer": parse_bunker_offer,
            "port_disbursement": parse_port_disbursement,
            "noon_report": parse_noon_report,
        }
    )


# ── 午报规则解析（例行任务中枢新增；邮件复核分类器不动，避免影响既有队列语义）──

_NOON_PATTERNS: dict[str, re.Pattern] = {
    "lat": re.compile(r"lat(?:itude)?\s*[:\-]?\s*(-?\d{1,3}(?:\.\d+)?)", re.I),
    "lon": re.compile(r"lon(?:g|gitude)?\s*[:\-]?\s*(-?\d{1,3}(?:\.\d+)?)", re.I),
    "speed": re.compile(r"(?:speed|spd)\s*[:\-]?\s*(\d{1,2}(?:\.\d+)?)", re.I),
    "rob_fo": re.compile(r"rob\s*[-_ ]?fo\s*[:\-]?\s*(\d{1,6}(?:\.\d+)?)", re.I),
    "rob_do": re.compile(r"rob\s*[-_ ]?do\s*[:\-]?\s*(\d{1,6}(?:\.\d+)?)", re.I),
    "wind_bf": re.compile(r"(?:wind|wind\s*bf)\s*[:\-]?\s*(\d{1,2}(?:\.\d+)?)", re.I),
    "current_kn": re.compile(r"(?:current|curr)\s*[:\-]?\s*(\d{1,2}(?:\.\d+)?)", re.I),
}


def _num(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_noon_report(body: str) -> dict:
    """午报 → 午报字段（船位/油耗/ETA/天气）。

    规则腿只认**明确写出来的字段**；没写的字段留空由人工补 —— 不猜。
    """
    result: dict[str, Any] = {}
    text = body or ""
    for field_name, pattern in _NOON_PATTERNS.items():
        m = pattern.search(text)
        if m:
            val = _num(m.group(1))
            if val is not None:
                result[field_name] = val
    m = re.search(r"report(?:ed)?\s*(?:at|time)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)", text, re.I)
    if m:
        result["report_at"] = m.group(1).strip()
    m = re.search(r"eta\s*(?:next)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)", text, re.I)
    if m:
        result["eta_next"] = m.group(1).strip()
    m = re.search(r"sea\s*state\s*[:\-]?\s*([A-Za-z ]{2,16})", text, re.I)
    if m:
        result["sea_state"] = m.group(1).strip()
    m = re.search(r"vessel\s*[:\-]?\s*(.+)", text, re.I)
    if m:
        result["vessel"] = m.group(1).strip()
    m = re.search(r"voyage\s*(?:no\.?|#)?\s*[:\-]?\s*([A-Z]{2,4}-?\d{2,5})", text, re.I)
    if m:
        result["voyage_no"] = m.group(1).strip()
    return result


# ── 确定性引擎腿 ────────────────────────────────────────────────────────────

def _run_engine(name: str | None, fields: dict[str, Any], db: Any = None, tenant_id: Any = None) -> dict[str, Any]:
    """跑确定性引擎（算账）。引擎名来自技能模板，**不让模型选**。"""
    if not name:
        return {}
    try:
        if name == "laytime_engine":
            from app.services.laytime_engine import compute_laytime_statement

            return {"laytime_statement": compute_laytime_statement(fields)}
        if name == "estimate_engine":
            from app.services.estimate_engine import compute_estimate

            return {"estimate": compute_estimate(fields, db=db, tenant_id=tenant_id)}
        if name == "carbon_calculator":
            from app.services.carbon_calculator import calculate_voyage_emissions

            return {"emissions": calculate_voyage_emissions(fields)}
    except Exception as exc:  # noqa: BLE001 — 引擎失败必须显性，不静默
        log.warning("skill_runtime: deterministic engine %s failed: %s", name, exc)
        return {"_engine_error": f"{name}: {exc}"}
    log.warning("skill_runtime: unknown deterministic engine %s", name)
    return {"_engine_error": f"unknown deterministic engine: {name}"}


# ── 证据腿 ────────────────────────────────────────────────────────────────

def _as_number(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    """空值判定 —— LLM 腿返回空容器/空串时**不算抽到值**。

    模型常把「没找到」表达成 ``[]`` / ``{}`` / ``""``；若把它当成有效值，
    就会顶掉规则腿明明抽到的结果（试点走查踩到：SOF 的 4 条事件被空数组顶掉，
    装卸时间草稿成了空壳）。
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _value_candidates(value: Any) -> list[str]:
    """把字段值拆成可在原文里检索的标量候选（列表/字典取其元素）。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_value_candidates(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_value_candidates(item))
        return out
    text = str(value).strip()
    return [text] if text else []


#: 纯数字形态的字符串（判「按数字 token 匹配」而不是子串匹配）
_NUMERIC_STR_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def _numeric_candidates(value: Any) -> list[str]:
    """把一个数值展开成正文里可能的写法（1520 / 1520.0 / 1,520）。"""
    num = _as_number(value)
    if num is None:
        return []
    raw = format(num, "f")
    out: list[str] = [raw]
    if "." in raw:
        trimmed = raw.rstrip("0").rstrip(".")
        if trimmed and trimmed not in out:
            out.append(trimmed)
    else:
        if f"{raw}.0" not in out:
            out.append(f"{raw}.0")
        if len(raw.lstrip("-")) > 3:
            grouped = f"{int(raw):,}"
            if grouped not in out:
                out.append(grouped)
    return out


def _has_standalone_number(line: str, candidates: list[str]) -> bool:
    """行里是否**独立**出现了该数字。

    必须按「独立 token」判，不能用子串包含 —— 否则 4 会命中 "04:00"、
    4 会命中 "2408"，出处行会指到不相干的行上（试点走查踩到：
    wind_bf=4 的出处指向 "Report at: ... 04:00"）。左右两侧都不许挨着
    字母/数字/小数点，才算「这一行里写的就是这个数」。
    """
    for cand in candidates:
        if re.search(rf"(?<![\w.]){re.escape(cand)}(?![\w.])", line):
            return True
    return False


def _line_quote(body: str, value: Any) -> str | None:
    """在原文里找一行能佐证该字段值的出处（找不到 → 该字段没有证据）。"""
    if value is None:
        return None
    candidates = _value_candidates(value)
    if not candidates:
        return None
    lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]

    # 数值型字段：只认「独立出现的数字」，绝不按子串找
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        numeric = _numeric_candidates(value)
        for raw_line in lines:
            if _has_standalone_number(raw_line, numeric):
                return raw_line[:280]
        return None

    # 文本候选：任一候选出现在某行即算证据（容器字段靠元素命中）
    for raw_line in lines:
        low = raw_line.lower()
        for cand in candidates:
            text = cand.strip()
            if not text:
                continue
            if _NUMERIC_STR_RE.match(text):
                # 字符串形态的纯数字 —— 同样按独立 token 判
                if _has_standalone_number(raw_line, _numeric_candidates(text)):
                    return raw_line[:280]
            elif text.lower() in low:
                return raw_line[:280]
    return None


def build_evidence(
    fields: dict[str, Any],
    body: str,
    *,
    source: str,
    origins: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """逐字段找原文出处；找不到出处的字段不产出证据（调用方据此丢字段）。

    ``origins`` 给的是**逐字段**来源（llm / rules）；缺省才回落到整体 ``source``。
    规则腿兜底的字段不能挂「llm」标签 —— 复核人看到的标签必须等于真正的抽取腿。
    """
    evidence: list[dict[str, Any]] = []
    for name, value in fields.items():
        if name.startswith("_") or value is None:
            continue
        quote = _line_quote(body, value)
        if quote is None:
            continue
        evidence.append(
            {
                "source": "email",
                "field": name,
                "quote": quote,
                "value": value,
                "extracted_by": (origins or {}).get(name, source),
            }
        )
    return evidence


# ── 校验腿 ────────────────────────────────────────────────────────────────

def validate_payload(
    payload: dict[str, Any], validator_rules: dict[str, Any], required: list[str]
) -> list[str]:
    """字段级校验 —— 返回错误清单（空 = 通过）。"""
    errors: list[str] = []
    for name in required or []:
        value = payload.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"missing_required:{name}")
        elif isinstance(value, (list, tuple, dict, set)) and not value:
            errors.append(f"missing_required:{name}")  # 空列表/空字典同样算缺
    ranges = (validator_rules or {}).get("ranges") or {}
    for name, bounds in ranges.items():
        value = payload.get(name)
        if value is None:
            continue
        num = _as_number(value)
        if num is None:
            errors.append(f"not_numeric:{name}")
            continue
        try:
            low, high = bounds[0], bounds[1]
        except (TypeError, IndexError):
            continue
        if low is not None and num < Decimal(str(low)):
            errors.append(f"out_of_range:{name}")
        if high is not None and num > Decimal(str(high)):
            errors.append(f"out_of_range:{name}")
    one_of = (validator_rules or {}).get("one_of") or {}
    for name, allowed in one_of.items():
        value = payload.get(name)
        if value is None:
            continue
        if str(value).upper() not in {str(a).upper() for a in allowed}:
            errors.append(f"not_allowed:{name}")
    return errors


# ── 主入口 ────────────────────────────────────────────────────────────────

@dataclass
class SkillResult:
    """技能执行结果。"""

    payload: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    source: str = "rules"  # llm | rules
    field_diff: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error: str | None = None  # 整体失败原因（显性，不静默）


def run_skill(
    *,
    skill: Any,
    subject: str,
    body: str,
    db: Any = None,
    tenant_id: Any = None,
    provider: Any = None,
    rule_fields: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> SkillResult:
    """执行一个技能模板。

    ``skill`` 是 :class:`app.models_routine.SkillTemplate` 行（或等价对象）。
    失败不抛异常 —— 错误写进 :class:`SkillResult`，由调用方落成
    ``status="failed"`` 的草稿并通知人（**不静默降级**）。
    """
    _register_rule_parsers()
    schema = dict(getattr(skill, "output_schema", None) or {})
    validator_rules = dict(getattr(skill, "validator_rules", None) or {})
    kind = str(schema.get("kind") or "")
    required = list(schema.get("required") or [])

    if not kind:
        return SkillResult(error="skill_template_missing_kind")

    # 1) 规则腿
    rules: dict[str, Any] = {}
    parser = RULE_PARSERS.get(kind)
    if parser is not None:
        try:
            rules = {k: v for k, v in (parser(body) or {}).items() if v is not None}
        except Exception as exc:  # noqa: BLE001
            log.warning("skill_runtime: rule parser failed for %s: %s", kind, exc)
            rules = {}
    if rule_fields:
        rules.update({k: v for k, v in rule_fields.items() if v is not None})

    # 2) LLM 腿（失败自动回落规则）
    from app.services import llm_extract

    try:
        extracted = llm_extract.extract_fields(kind, subject, body, rules, provider=provider)
    except Exception as exc:  # noqa: BLE001 — 抽取异常必须可见
        log.warning("skill_runtime: extraction failed for %s: %s", kind, exc)
        return SkillResult(error=f"extraction_failed: {exc}")

    source = str(extracted.get("_source") or "rules")
    llm_fields = {
        k: v
        for k, v in extracted.items()
        if not k.startswith("_") and v is not None and not _is_blank(v)
    }
    # 规则腿补缺：LLM 没抽到（**或抽到空值**）的字段用规则结果兜住（LLM 优先）
    rule_only = {
        k: v for k, v in (rules or {}).items() if v is not None and k not in llm_fields
    }
    fields = {**llm_fields, **rule_only}
    # 逐字段记抽取腿 —— LLM 腿没贡献任何字段时，整体来源就是规则（降级要明示）
    origins = {**{k: "llm" for k in llm_fields}, **{k: "rules" for k in rule_only}}
    if not llm_fields:
        source = "rules"
    diffs = extracted.get("_rule_diffs") or []

    # 3) 确定性引擎腿（算账走引擎，不走模型）
    computed = _run_engine(getattr(skill, "deterministic_engine", None), fields, db=db, tenant_id=tenant_id)
    engine_failed = bool(computed.get("_engine_error"))

    # 4) 证据腿 —— 指不回原文的字段直接丢弃
    evidence = build_evidence(fields, body, source=source, origins=origins)
    evidenced = {e["field"] for e in evidence}
    dropped = [k for k in fields if k not in evidenced]
    payload = {k: v for k, v in fields.items() if k in evidenced}

    warnings: list[str] = []
    if source == "rules":
        warnings.append("rule_fallback")  # 降级要明示，不能藏在背后
    if dropped:
        warnings.append("no_evidence:" + ",".join(sorted(dropped)))
    if engine_failed:
        # 引擎失败不吞掉抽取结果，但必须显式告警（草稿里看得到）
        warnings.append("engine_failed:" + str(computed.get("_engine_error")))
    computed_ok = {k: v for k, v in computed.items() if not k.startswith("_")}
    if computed_ok:
        payload["_computed"] = computed_ok

    # 5) 校验腿
    errors = validate_payload(payload, validator_rules, required)
    confidence = None
    if payload:
        confidence = round(min(0.99, 0.6 + 0.1 * len(payload)), 4)
    return SkillResult(
        payload=payload,
        evidence=evidence,
        confidence=confidence,
        source=source,
        field_diff={"llm_vs_rules": diffs, "dropped_without_evidence": sorted(dropped)},
        warnings=warnings,
        errors=errors,
    )
