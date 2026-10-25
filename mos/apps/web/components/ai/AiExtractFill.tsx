"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RecordModal } from "@/components/RecordModal";
import { apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";

/**
 * AiExtractFill —— 粘贴邮件/聊天记录 → AI 解析 → 逐字段预览确认 → 填入表单。
 *
 * 产品语义与 AiFill 一致：AI 只产出建议，应用由用户勾选/改值后触发
 * （onApply）。本组件不写任何业务数据。三处入口共用：
 * 估算/TCE 表单内、邮件复核详情、航次工作台（后两者走 sessionStorage
 * prefill 转运到估算页）。
 */

export type ExtractedValues = Record<string, unknown>;

/** 解析结果（POST /ai/assist/extract 的响应形状） */
export type ExtractResult = {
  kind: string;
  classification: { type: string; confidence: number };
  fields: ExtractedValues;
  _source: "llm" | "rules";
  _rule_diffs: Array<{ field: string; llm_value: unknown; rule_value: unknown }>;
  truncated: boolean;
};

/** 上下文预置（工作台/邮件入口携带的航次上下文 —— 展示但不参与勾选） */
export type ExtractContext = {
  vessel_name?: string;
  load_port?: string;
  disch_port?: string;
  counterparty?: string;
};

/** v1 没有对应表单字段的键 —— 预览置灰「仅参考」，不写入表单。
 *  charterers/owners 不在其列：估算页会把它们映射到对手方（partyId）。 */
const INFO_ONLY_KEYS = new Set([
  "laycan",
  "demurrage_rate",
  "despatch_rate",
  "laytime_load",
  "laytime_discharge",
  "position",
  "draft",
  "date_time",
  "imo",
]);

/** 邮件详情入口：现成 parse_result 直接预填预览（不二次解析） */
function fieldsFromParseResult(parse: Record<string, unknown>): ExtractedValues {
  const sub = ((parse.fixture_recap || parse.nor || parse.laytime) as Record<string, unknown>) || parse;
  const out: ExtractedValues = {};
  for (const [k, v] of Object.entries(sub || {})) {
    if (k === "email_type" || k === "source" || k === "graph_id" || k === "applied") continue;
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[k] = v;
  }
  return out;
}

type Props = {
  open: boolean;
  onClose: () => void;
  /** textarea 初始文本（邮件详情可传正文；工作台留空） */
  initialText?: string;
  /** 现成解析字段（邮件详情传 parse_result）—— 有它则跳过解析直接进预览 */
  initialFields?: Record<string, unknown>;
  initialKind?: string;
  /** 航次上下文预置（工作台入口）—— 只展示，不参与勾选 */
  context?: ExtractContext;
  /** 用户确认后回调：仅带勾选字段 */
  onApply: (values: ExtractedValues, meta: { kind: string; source: string }) => void;
};

const FIELD_ORDER = [
  "vessel", "cargo", "load_port", "discharge_port", "laycan",
  "freight_rate", "demurrage_rate", "despatch_rate",
  "laytime_load", "laytime_discharge", "commission",
  "charterers", "owners",
  "port", "date_time", "position", "draft",
];

export function AiExtractFill({
  open,
  onClose,
  initialText = "",
  initialFields,
  initialKind,
  context,
  onApply,
}: Props) {
  const { t } = useI18n();
  const [text, setText] = useState(initialText);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ExtractResult | null>(null);
  /** 字段编辑值（预览里可改） */
  const [values, setValues] = useState<ExtractedValues>({});
  /** 勾选集合（默认全选非空字段） */
  const [checked, setChecked] = useState<Set<string>>(new Set());

  // 打开时重置；邮件详情入口带 initialFields → 直接进预览
  useEffect(() => {
    if (!open) return;
    setText(initialText);
    setError(null);
    setBusy(false);
    if (initialFields && Object.keys(initialFields).length) {
      const f = fieldsFromParseResult(initialFields);
      setResult({
        kind: initialKind || "fixture_recap",
        classification: { type: initialKind || "fixture_recap", confidence: 1 },
        fields: f,
        _source: "rules",
        _rule_diffs: [],
        truncated: false,
      });
      setValues(f);
      setChecked(new Set(Object.keys(f)));
    } else {
      setResult(null);
      setValues({});
      setChecked(new Set());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const parse = useCallback(async () => {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = (await apiPost("/api/v1/ai/assist/extract", { body: text })) as ExtractResult;
      setResult(res);
      setValues({ ...res.fields });
      setChecked(new Set(Object.entries(res.fields).filter(([, v]) => v != null && v !== "").map(([k]) => k)));
    } catch (ex) {
      setError(msgOf(ex, t("ai.extract.fail", "解析失败")));
    } finally {
      setBusy(false);
    }
  }, [text, t]);

  const orderedKeys = useMemo(() => {
    if (!result) return [];
    const keys = Object.keys(result.fields).filter((k) => {
      const v = result.fields[k];
      return v != null && v !== "" && !(Array.isArray(v) && v.length === 0);
    });
    const known = FIELD_ORDER.filter((k) => keys.includes(k));
    const rest = keys.filter((k) => !FIELD_ORDER.includes(k)).sort();
    return [...known, ...rest];
  }, [result]);

  function toggle(k: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  function apply() {
    const picked: ExtractedValues = {};
    for (const k of checked) {
      if (INFO_ONLY_KEYS.has(k)) continue; // 仅参考键不写入表单
      const v = values[k];
      if (v != null && v !== "") picked[k] = v;
    }
    onApply(picked, { kind: result?.kind || "", source: result?._source || "rules" });
    onClose();
  }

  return (
    <RecordModal
      open={open}
      title={t("ai.extract.title", "从文本填充（AI 解析）")}
      onClose={onClose}
      canEdit={false}
      canDelete={false}
      size="lg"
    >
      <label>
        {t("ai.extract.paste_hint", "粘贴邮件 / 微信 / 聊天记录，AI 自动识别船舶、港口、运价等字段")}
        <textarea
          rows={7}
          value={text}
          placeholder={t("ai.extract.placeholder", "例：Fixture Recap — Vessel: MV PACIFIC STAR / Load Port: Tubarao / Freight Rate: 24.75 …")}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <p className="row-actions">
        <button className="btn btn-primary btn-sm" type="button" disabled={busy || !text.trim()} onClick={() => void parse()}>
          {busy ? t("ai.extract.parsing", "解析中…") : t("ai.extract.parse_btn", "解析")}
        </button>
        {result ? (
          <span className="badge">{result._source === "llm" ? "AI" : "rules"}</span>
        ) : null}
        {result?.truncated ? (
          <span className="badge badge-warn">{t("ai.extract.truncated", "文本超长已截断")}</span>
        ) : null}
      </p>
      {error ? (
        <p className="state-view-error" role="alert">
          {error}
        </p>
      ) : null}
      {result && result._source !== "llm" ? (
        <p className="ai-fill-note">
          {t("ai.extract.rules_note", "AI 模型未配置或暂不可用 — 以上结果由内置规则生成。")}
        </p>
      ) : null}
      {result && result._rule_diffs?.length ? (
        <p className="ai-fill-note">
          {t("ai.extract.diff_note", "AI 与规则结果有 {n} 处不一致，请人工核对。", {
            n: result._rule_diffs.length,
          })}
        </p>
      ) : null}

      {context && Object.values(context).some(Boolean) ? (
        <div className="form-row">
          <span className="hint">
            {t("ai.extract.context", "航次上下文")}：
            {[context.vessel_name, context.load_port && `→ ${context.load_port}`, context.disch_port && `→ ${context.disch_port}`, context.counterparty]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </div>
      ) : null}

      {orderedKeys.length ? (
        <>
        <ul className="ai-extract-list">
          {orderedKeys.map((k) => {
            const infoOnly = INFO_ONLY_KEYS.has(k);
            const isChecked = checked.has(k);
            return (
              <li key={k} className={`ai-extract-row${infoOnly ? " info-only" : ""}`}>
                {!infoOnly ? (
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => toggle(k)}
                    aria-label={t(`email.parse.${k}`, k)}
                  />
                ) : (
                  <span className="ai-extract-ref" title={t("ai.extract.info_only", "暂无对应表单项，仅作参考")}>
                    ·
                  </span>
                )}
                <span className="ai-extract-key">{t(`email.parse.${k}`, k)}</span>
                <input
                  className="ai-extract-val"
                  value={String(values[k] ?? "")}
                  disabled={infoOnly}
                  onChange={(e) => {
                    const raw = e.target.value;
                    const num = Number(raw);
                    setValues((prev) => ({ ...prev, [k]: raw !== "" && Number.isFinite(num) ? num : raw }));
                  }}
                />
                {infoOnly ? (
                  <span className="hint">{t("ai.extract.ref_badge", "仅参考")}</span>
                ) : null}
              </li>
            );
          })}
        </ul>
        {/* canEdit=false 时 RecordModal 不渲染页脚保存 —— 应用按钮放正文内 */}
        <p className="row-actions">
          <button className="btn btn-primary" type="button" onClick={apply}>
            {t("ai.extract.apply_btn", "应用到表单")}
          </button>
        </p>
        </>
      ) : result ? (
        <p className="muted">{t("ai.extract.none", "未识别到可用字段 — 请检查文本是否包含船舶/港口/运价等信息。")}</p>
      ) : null}
    </RecordModal>
  );
}
