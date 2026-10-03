"use client";

// 估算多方案对比 — 类似汽车 App 多车并列对比
// 特性：字段自上而下、方案左右并列、拖拽排序、差异高亮、隐藏相同项、字段排序

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useI18n } from "@/lib/i18n";

export type CompareVariant = {
  id: string;
  name: string;
  subtitle?: string;
  values: Record<string, unknown>;
};

export type CompareFieldDef = {
  key: string;
  label: string;
  labelEn?: string;
  labelZh?: string;
  category: string;
  categoryEn?: string;
  categoryZh?: string;
  format?: "number" | "money" | "percent" | "text" | "date";
  unit?: string;
  preference?: "higher" | "lower" | "neutral";
};

type Props = {
  variants: CompareVariant[];
  fields: CompareFieldDef[];
  /** 最优值高亮 */
  highlightBest?: boolean;
};

function fieldLabel(f: CompareFieldDef, locale: string): string {
  return locale.startsWith("zh") ? f.labelZh || f.label : f.labelEn || f.label;
}
function fieldCategory(f: CompareFieldDef, locale: string): string {
  return locale.startsWith("zh") ? f.categoryZh || f.category : f.categoryEn || f.category;
}

function formatValue(val: unknown, field: CompareFieldDef): string {
  if (val === null || val === undefined || val === "") return "—";
  const n = Number(val);
  switch (field.format) {
    case "money":
      return isFinite(n) ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : String(val);
    case "number":
      return isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(val);
    case "percent":
      return isFinite(n) ? `${n.toFixed(1)}%` : String(val);
    case "date":
      return String(val).slice(0, 10);
    default:
      return String(val);
  }
}

export function EstimateCompare({ variants, fields, highlightBest = true }: Props) {
  const { t, locale } = useI18n();
  const [colOrder, setColOrder] = useState<string[]>(() => variants.map((v) => v.id));
  const [fullscreen, setFullscreen] = useState(false);

  // Sync colOrder when variants change
  useEffect(() => {
    setColOrder(variants.map((v) => v.id));
  }, [variants]);
  const [hideSame, setHideSame] = useState(false);
  const [sortMode, setSortMode] = useState<"category" | "alpha" | "diff">("category");
  const [collapsedCats, setCollapsedCats] = useState<Set<string>>(new Set());
  const [dragCol, setDragCol] = useState<string | null>(null);
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);
  const tableRef = useRef<HTMLDivElement>(null);

  // 按 colOrder 排序的变体列表
  const orderedVariants = useMemo(
    () => colOrder.map((id) => variants.find((v) => v.id === id)).filter(Boolean) as CompareVariant[],
    [colOrder, variants],
  );

  // 计算每行是否有差异
  const fieldDiff = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const f of fields) {
      const vals = variants.map((v) => v.values[f.key]);
      const unique = new Set(vals.map((v) => String(v ?? "")));
      map.set(f.key, unique.size > 1);
    }
    return map;
  }, [fields, variants]);

  // 最优值计算
  const bestValues = useMemo(() => {
    const map = new Map<string, unknown>();
    if (!highlightBest) return map;
    for (const f of fields) {
      if (f.preference !== "higher" && f.preference !== "lower") continue;
      const nums = variants
        .map((v) => Number(v.values[f.key]))
        .filter((n) => isFinite(n));
      if (nums.length < 2) continue;
      map.set(f.key, f.preference === "higher" ? Math.max(...nums) : Math.min(...nums));
    }
    return map;
  }, [fields, variants, highlightBest]);

  // 排序字段
  const sortedFields = useMemo(() => {
    let list = [...fields];
    if (hideSame) list = list.filter((f) => fieldDiff.get(f.key));
    switch (sortMode) {
      case "alpha":
        list.sort((a, b) => a.label.localeCompare(b.label));
        break;
      case "diff":
        list.sort((a, b) => (fieldDiff.get(b.key) ? 1 : 0) - (fieldDiff.get(a.key) ? 1 : 0));
        break;
      case "category":
      default:
        // 保持原始顺序（按 category 分组）
        break;
    }
    return list;
  }, [fields, fieldDiff, hideSame, sortMode]);

  // 按分类分组
  const grouped = useMemo(() => {
    const groups: { category: string; label: string; fields: CompareFieldDef[] }[] = [];
    let current = "";
    for (const f of sortedFields) {
      const catLabel = fieldCategory(f, locale);
      if (f.category !== current) {
        current = f.category;
        groups.push({ category: current, label: catLabel, fields: [] });
      }
      groups[groups.length - 1].fields.push(f);
    }
    return groups;
  }, [sortedFields, locale]);

  // 拖拽排序
  const handleDragStart = useCallback((colId: string) => {
    setDragCol(colId);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, colId: string) => {
    e.preventDefault();
    setDragOverCol(colId);
  }, []);

  const handleDrop = useCallback(
    (targetId: string) => {
      if (!dragCol || dragCol === targetId) {
        setDragCol(null);
        setDragOverCol(null);
        return;
      }
      setColOrder((prev) => {
        const next = [...prev];
        const from = next.indexOf(dragCol);
        const to = next.indexOf(targetId);
        next.splice(from, 1);
        next.splice(to, 0, dragCol);
        return next;
      });
      setDragCol(null);
      setDragOverCol(null);
    },
    [dragCol],
  );

  function toggleCat(cat: string) {
    setCollapsedCats((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

  return (
    <div className="compare-container">
      {/* 工具栏 */}
      <div className="compare-toolbar">
        <div className="compare-toolbar-left">
          <button
            type="button"
            className={`btn btn-sm ${hideSame ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setHideSame((v) => !v)}
          >
            {hideSame
              ? t("compare.show_all", "显示全部")
              : t("compare.hide_same", "隐藏相同项")}
          </button>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => setSortMode((m) => (m === "category" ? "alpha" : m === "alpha" ? "diff" : "category"))}
          >
            {t("compare.sort", "排序")}:{" "}
            {sortMode === "category" ? t("compare.by_category", "分类") : sortMode === "alpha" ? t("compare.by_alpha", "字母") : t("compare.by_diff", "差异优先")}
          </button>
        </div>
        <div className="compare-toolbar-right">
          <span className="compare-stats">
            {variants.length} {t("compare.variants", "方案")} ·{" "}
            {fields.filter((f) => fieldDiff.get(f.key)).length} {t("compare.diff_fields", "项差异")}
          </span>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => setFullscreen(true)}
            title={t("compare.fullscreen", "全屏对比")}
          >
            ⛶
          </button>
        </div>
      </div>

      {/* Fullscreen modal */}
      {fullscreen ? (
        <div className="compare-fullscreen-backdrop" onClick={() => setFullscreen(false)}>
          <div
            className="compare-fullscreen-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="compare-fullscreen-head">
              <strong>{t("compare.title", "方案对比")}</strong>
              <span className="compare-stats">
                {variants.length} {t("compare.variants", "方案")} ·{" "}
                {fields.filter((f) => fieldDiff.get(f.key)).length} {t("compare.diff_fields", "项差异")}
              </span>
              <button
                type="button"
                className="icon-btn"
                onClick={() => setFullscreen(false)}
                aria-label={t("common.close", "关闭")}
              >
                ×
              </button>
            </div>
            <div className="compare-fullscreen-body">
              <table className="compare-table">
                <thead>
                  <tr>
                    <th className="compare-field-header">{t("compare.field", "字段")}</th>
                    {orderedVariants.map((v) => (
                      <th key={v.id} className="compare-variant-header">
                        <div className="compare-variant-name">{v.name}</div>
                        {v.subtitle ? <div className="compare-variant-sub">{v.subtitle}</div> : null}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {grouped.map((group) => (
                    <>
                      <tr key={`fs-cat-${group.category}`} className="compare-category-row" onClick={() => toggleCat(group.category)}>
                        <td colSpan={1 + orderedVariants.length}>
                          <span className="compare-category-toggle">{collapsedCats.has(group.category) ? "▸" : "▾"}</span>
                          <strong>{group.label}</strong>
                          <span className="compare-category-count">{group.fields.length}</span>
                        </td>
                      </tr>
                      {!collapsedCats.has(group.category) &&
                        group.fields.map((f) => {
                          const isDiff = fieldDiff.get(f.key);
                          const best = bestValues.get(f.key);
                          return (
                            <tr key={f.key} className={`compare-row ${isDiff ? "is-diff" : "is-same"}`}>
                              <td className="compare-field-cell">
                                <span className="compare-field-label">{fieldLabel(f, locale)}</span>
                                {f.unit ? <span className="compare-field-unit">{f.unit}</span> : null}
                                {isDiff ? <span className="compare-diff-badge">Δ</span> : null}
                              </td>
                              {orderedVariants.map((v) => {
                                const val = v.values[f.key];
                                const isBest = highlightBest && best !== undefined && val !== null && val !== undefined && Number(val) === Number(best);
                                return (
                                  <td key={v.id} className={`compare-value-cell ${isBest ? "is-best" : ""}`}>
                                    {formatValue(val, f)}
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })}
                    </>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}

      {/* 对比表格 */}
      <div className="compare-scroll" ref={tableRef}>
        <table className="compare-table">
          <thead>
            <tr>
              {/* 字段名列头 */}
              <th className="compare-field-header">
                <span>{t("compare.field", "字段")}</span>
              </th>
              {/* 各方案列头（可拖拽） */}
              {orderedVariants.map((v) => (
                <th
                  key={v.id}
                  className={`compare-variant-header ${dragOverCol === v.id ? "drag-over" : ""} ${dragCol === v.id ? "dragging" : ""}`}
                  draggable
                  onDragStart={() => handleDragStart(v.id)}
                  onDragOver={(e) => handleDragOver(e, v.id)}
                  onDrop={() => handleDrop(v.id)}
                  onDragEnd={() => { setDragCol(null); setDragOverCol(null); }}
                >
                  <div className="compare-variant-drag" aria-hidden>⠿</div>
                  <div className="compare-variant-name">{v.name}</div>
                  {v.subtitle ? <div className="compare-variant-sub">{v.subtitle}</div> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grouped.map((group) => (
              <>
                {/* 分类标题行 */}
                <tr
                  key={`cat-${group.category}`}
                  className="compare-category-row"
                  onClick={() => toggleCat(group.category)}
                >
                  <td colSpan={1 + orderedVariants.length}>
                    <span className="compare-category-toggle">
                      {collapsedCats.has(group.category) ? "▸" : "▾"}
                    </span>
                    <strong>{group.label}</strong>
                    <span className="compare-category-count">{group.fields.length}</span>
                  </td>
                </tr>
                {/* 字段行 */}
                {!collapsedCats.has(group.category) &&
                  group.fields.map((f) => {
                    const isDiff = fieldDiff.get(f.key);
                    const best = bestValues.get(f.key);
                    return (
                      <tr key={f.key} className={`compare-row ${isDiff ? "is-diff" : "is-same"}`}>
                        <td className="compare-field-cell">
                          <span className="compare-field-label">{fieldLabel(f, locale)}</span>
                          {f.unit ? <span className="compare-field-unit">{f.unit}</span> : null}
                          {isDiff ? <span className="compare-diff-badge">Δ</span> : null}
                        </td>
                        {orderedVariants.map((v) => {
                          const val = v.values[f.key];
                          const isBest =
                            highlightBest &&
                            best !== undefined &&
                            val !== null &&
                            val !== undefined &&
                            Number(val) === Number(best);
                          return (
                            <td
                              key={v.id}
                              className={`compare-value-cell ${isBest ? "is-best" : ""}`}
                            >
                              {formatValue(val, f)}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
