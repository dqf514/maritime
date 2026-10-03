"use client";

// Phase 8 — Report Designer：可视化报表设计器（数据集 → 查询规格 → 实时预览）。
// query_spec v2 声明式规格：datasets / joins / fields / filters / group_by。

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type DatasetField = { name: string; type: string; label: string };
type Dataset = { entity: string; name: string; description: string; fields: DatasetField[] };

type SpecDataset = { dataset: string; alias: string };
type SpecJoin = { left: string; right: string; join_type: string; left_field: string; right_field: string };
type SpecFilter = { dataset: string; field: string; op: string; value: string };
type FieldState = { agg: string; visible: boolean; label?: string; format?: string };

type PreviewResult = {
  columns: { key: string; label: string; format?: string | null; agg?: string | null }[];
  rows: Record<string, unknown>[];
  total_rows: number;
};

const JOIN_TYPES = ["left", "inner", "right"];
const FORMAT_OPTIONS = ["", "number", "currency", "date", "text"];
const AGG_OPTIONS = ["", "sum", "avg", "count", "min", "max"];
const FILTER_OPS = ["eq", "ne", "gt", "gte", "lt", "lte", "like", "ilike", "in", "not_in", "between", "is_null", "not_null"];

function asArray(raw: unknown): Record<string, unknown>[] {
  if (Array.isArray(raw)) return raw as Record<string, unknown>[];
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    if (Array.isArray(o.items)) return o.items as Record<string, unknown>[];
    if (Array.isArray(o.datasets)) return o.datasets as Record<string, unknown>[];
    if (Array.isArray(o.results)) return o.results as Record<string, unknown>[];
  }
  return [];
}

function normalizeDatasets(raw: unknown): Dataset[] {
  return asArray(raw)
    .map((r) => {
      const entity = String(r.entity || r.name || r.code || "");
      const rawFields = r.fields ?? [];
      const fields: DatasetField[] = Array.isArray(rawFields)
        ? rawFields
            .map((f) => {
              const fo = f as Record<string, unknown>;
              const name = String(fo.name || fo.field || fo.field_name || "");
              return {
                name,
                type: String(fo.type || "string"),
                label: String(fo.label || name),
              };
            })
            .filter((f) => f.name)
        : Object.entries(rawFields as Record<string, unknown>).map(([k, v]) => ({
            name: k,
            type: String(v),
            label: k.replace(/_/g, " "),
          }));
      return {
        entity,
        name: String(r.name || entity),
        description: String(r.description || ""),
        fields,
      };
    })
    .filter((d) => d.entity);
}

function fieldLabelOf(ds: Dataset | undefined, field: string): string {
  return ds?.fields.find((f) => f.name === field)?.label || field;
}

export default function ReportBuilderPage() {
  const { t } = useI18n();
  const toast = useToast();

  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  // query spec state
  const [selected, setSelected] = useState<SpecDataset[]>([]);
  const [joins, setJoins] = useState<SpecJoin[]>([]);
  const [fieldState, setFieldState] = useState<Record<string, FieldState>>({});
  const [filters, setFilters] = useState<SpecFilter[]>([]);
  const [groupKeys, setGroupKeys] = useState<string[]>([]);

  // preview / save
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [reportName, setReportName] = useState("");
  const [reportDesc, setReportDesc] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editId, setEditId] = useState<string | null>(null);

  useEffect(() => {
    apiGet("/api/v1/reports/datasets")
      .then((raw) => {
        setDatasets(normalizeDatasets(raw));
      })
      .catch((ex) => setErr(String(ex)))
      .finally(() => setLoading(false));
  }, []);

  // Edit existing report: /analytics/reports/builder?id=<report_id>
  // (window.location.search — Next useSearchParams needs a Suspense boundary here)
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) return;
    apiGet(`/api/v1/reports/${id}`)
      .then((r: Record<string, unknown>) => {
        const spec = (r.query_spec || null) as Record<string, unknown> | null;
        setEditId(String(r.id || id));
        setReportName(String(r.report_name || ""));
        setReportDesc(String(r.description || ""));
        if (!spec) return;
        const specDatasets = (spec.datasets || []) as { dataset: string; alias: string }[];
        setSelected(specDatasets.map((d) => ({ dataset: d.dataset, alias: d.alias })));
        setJoins(((spec.joins || []) as SpecJoin[]).map((j) => ({ ...j })));
        const fs: Record<string, FieldState> = {};
        for (const f of (spec.fields || []) as {
          dataset: string;
          field: string;
          agg?: string | null;
          label?: string;
          format?: string | null;
          visible?: boolean;
        }[]) {
          fs[`${f.dataset}.${f.field}`] = {
            agg: f.agg || "",
            visible: f.visible !== false,
            label: f.label || "",
            format: f.format || "",
          };
        }
        setFieldState(fs);
        setFilters(
          ((spec.filters || []) as { dataset: string; field: string; op: string; value: unknown }[]).map((f) => ({
            dataset: f.dataset,
            field: f.field,
            op: f.op,
            value: Array.isArray(f.value) ? f.value.join(", ") : String(f.value ?? ""),
          })),
        );
        setGroupKeys(
          ((spec.group_by || []) as { dataset: string; field: string }[]).map((g) => `${g.dataset}.${g.field}`),
        );
      })
      .catch((ex) => setErr(String(ex)));
  }, []);

  const dsByEntity = useMemo(() => {
    const m: Record<string, Dataset> = {};
    for (const d of datasets) m[d.entity] = d;
    return m;
  }, [datasets]);

  const aliasOf = useCallback(
    (entity: string) => selected.find((s) => s.dataset === entity)?.alias || "",
    [selected],
  );

  function addDataset(entity: string) {
    setSelected((prev) => {
      if (prev.some((s) => s.dataset === entity)) return prev;
      const used = new Set(prev.map((s) => s.alias));
      let n = prev.length + 1;
      while (used.has(`d${n}`)) n += 1;
      return [...prev, { dataset: entity, alias: `d${n}` }];
    });
    setExpanded(entity);
  }

  function removeDataset(entity: string) {
    const alias = aliasOf(entity);
    setSelected((prev) => prev.filter((s) => s.dataset !== entity));
    setJoins((prev) => prev.filter((j) => j.left !== alias && j.right !== alias));
    setFieldState((prev) => {
      const next: Record<string, FieldState> = {};
      for (const [k, v] of Object.entries(prev)) {
        if (!k.startsWith(`${alias}.`)) next[k] = v;
      }
      return next;
    });
    setFilters((prev) => prev.filter((f) => f.dataset !== alias));
    setGroupKeys((prev) => prev.filter((k) => !k.startsWith(`${alias}.`)));
  }

  function toggleField(alias: string, field: string) {
    const key = `${alias}.${field}`;
    setFieldState((prev) => {
      const next = { ...prev };
      if (next[key]) delete next[key];
      else next[key] = { agg: "", visible: true };
      return next;
    });
  }

  function setFieldAgg(key: string, agg: string) {
    setFieldState((prev) => ({ ...prev, [key]: { ...(prev[key] || { visible: true }), agg } }));
  }

  /** Filter values typed in the UI are strings; in/not_in/between need lists. */
  function coerceFilterValue(op: string, raw: string): unknown {
    if (op === "in" || op === "not_in") {
      return raw
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s !== "");
    }
    if (op === "between") {
      return raw
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s !== "")
        .slice(0, 2);
    }
    return raw;
  }

  const buildSpec = useCallback(() => {
    const fields = Object.entries(fieldState)
      .filter(([, v]) => v.visible)
      .map(([key, v], i) => {
        const dot = key.indexOf(".");
        const dataset = key.slice(0, dot);
        const field = key.slice(dot + 1);
        return {
          dataset,
          field,
          label: v.label?.trim() || fieldLabelOf(dsByEntity[selected.find((s) => s.alias === dataset)?.dataset || ""], field),
          agg: v.agg || null,
          format: v.format || null,
          visible: true,
          sort_order: i,
        };
      });
    return {
      datasets: selected.map((s) => ({ dataset: s.dataset, alias: s.alias })),
      joins: joins.map((j) => ({ ...j })),
      fields,
      filters: filters
        .filter((f) => f.field && f.op)
        .map((f) => ({ dataset: f.dataset, field: f.field, op: f.op, value: coerceFilterValue(f.op, f.value) })),
      group_by: groupKeys.map((k) => {
        const dot = k.indexOf(".");
        return { dataset: k.slice(0, dot), field: k.slice(dot + 1) };
      }),
      order_by: [],
    };
  }, [fieldState, selected, joins, filters, groupKeys, dsByEntity]);

  async function runPreview() {
    if (!selected.length) {
      toast.error(t("page.rb.err.no_dataset", "Add at least one dataset first"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const spec = buildSpec();
      const res = await apiPost("/api/v1/reports/preview", { spec, params: {}, limit: 100 });
      setPreview(res);
      toast.success(t("page.rb.previewed", "Preview updated ({n} rows)", { n: res?.total_rows ?? 0 }));
    } catch (ex) {
      setErr(String(ex));
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function saveReport() {
    if (!selected.length) {
      toast.error(t("page.rb.err.no_dataset", "Add at least one dataset first"));
      return;
    }
    if (!reportName.trim()) {
      toast.error(t("page.rb.err.no_name", "Report name is required"));
      return;
    }
    setBusy(true);
    try {
      const spec = buildSpec();
      const payload = {
        report_name: reportName.trim(),
        report_type: "custom",
        data_source: "spec",
        query_spec: spec,
        spec_version: "v2",
        description: reportDesc || null,
      };
      if (editId) {
        await apiPut(`/api/v1/reports/${editId}`, payload);
      } else {
        await apiPost("/api/v1/reports", payload);
      }
      toast.success(t("page.rb.saved", "Report saved"));
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  const previewColumns: ColumnDef<Record<string, unknown>>[] = useMemo(
    () =>
      (preview?.columns || []).map((c) => ({
        key: c.key,
        title: c.label,
        width: 140,
        align: c.format === "currency" || c.format === "number" ? ("right" as const) : undefined,
        value: (r: Record<string, unknown>) => r[c.key],
        render: (v: unknown) => {
          if (v === null || v === undefined) return "";
          if (c.format === "currency") return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
          if (c.format === "number") return Number(v).toLocaleString();
          return String(v);
        },
      })),
    [preview],
  );

  const selectedFieldKeys = Object.keys(fieldState);

  return (
    <AppShell
      breadcrumbs={[
        { label: t("nav.reports", "Reports"), href: "/analytics/reports" },
        { label: t("page.rb.title", "Report Designer") },
      ]}
    >
      <PageHeader
        title={t("page.rb.title", "Report Designer")}
        subtitle={t("page.rb.sub", "Visual query builder — pick datasets, joins, fields and filters, then preview and save.")}
        actions={
          <Link href="/analytics/reports" className="btn btn-ghost">
            {t("page.rb.back_reports", "Report list")}
          </Link>
        }
      />

      {err ? <p className="flash-err">{err}</p> : null}

      <div className="rb-toolbar">
        <input
          type="text"
          value={reportName}
          onChange={(e) => setReportName(e.target.value)}
          placeholder={t("page.rb.report_name", "Report name")}
        />
        <input
          type="text"
          value={reportDesc}
          onChange={(e) => setReportDesc(e.target.value)}
          placeholder={t("page.rb.report_desc", "Description (optional)")}
        />
        <button type="button" className="btn btn-primary" onClick={runPreview} disabled={busy || loading}>
          {t("page.rb.preview", "Preview")}
        </button>
        <button type="button" className="btn btn-primary" onClick={saveReport} disabled={busy || loading}>
          {editId ? t("page.rb.save_changes", "Save changes") : t("common.save", "Save")}
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          disabled={busy}
          onClick={() => {
            setSelected([]);
            setJoins([]);
            setFieldState({});
            setFilters([]);
            setGroupKeys([]);
            setPreview(null);
          }}
        >
          {t("page.rb.reset", "Reset")}
        </button>
      </div>

      <div className="rb-layout">
        {/* Left — dataset catalog */}
        <div className="rb-panel">
          <div className="rb-panel-head">
            <h3>{t("page.rb.datasets", "Datasets")}</h3>
          </div>
          <div className="rb-panel-body">
            {loading ? <p className="muted">{t("common.loading", "Loading…")}</p> : null}
            {!loading && !datasets.length ? (
              <p className="muted">{t("page.rb.no_datasets", "No datasets available.")}</p>
            ) : null}
            {datasets.map((ds) => {
              const alias = aliasOf(ds.entity);
              const inQuery = Boolean(alias);
              const open = expanded === ds.entity;
              return (
                <div key={ds.entity} className="rb-ds-item">
                  <div className="rb-ds-head">
                    <button
                      type="button"
                      className="rb-ds-toggle"
                      onClick={() => setExpanded(open ? null : ds.entity)}
                    >
                      <span>
                        {inQuery ? (
                          <span className="rb-chip" style={{ marginRight: 6 }}>
                            {alias}
                          </span>
                        ) : null}
                        {ds.name}
                      </span>
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      onClick={() => (inQuery ? removeDataset(ds.entity) : addDataset(ds.entity))}
                    >
                      {inQuery ? "−" : "+"}
                    </button>
                  </div>
                  {ds.description ? <p className="rb-ds-desc">{ds.description}</p> : null}
                  {open ? (
                    <ul className="rb-field-list">
                      {ds.fields.map((f) => {
                        const key = `${alias || ds.entity}.${f.name}`;
                        const selectedField = Boolean(alias && fieldState[key]);
                        return (
                          <li key={f.name}>
                            <button
                              type="button"
                              className={selectedField ? "selected" : ""}
                              disabled={!alias}
                              onClick={() => alias && toggleField(alias, f.name)}
                              title={f.type}
                            >
                              <span>{f.label}</span>
                              <span className="rb-field-type">{f.type}</span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        {/* Center — query spec editor */}
        <div className="rb-panel">
          <div className="rb-panel-head">
            <h3>{t("page.rb.query_spec", "Query spec")}</h3>
            <span className="rb-preview-meta">
              {t("page.rb.n_datasets", "{n} datasets", { n: selected.length })} ·{" "}
              {t("page.rb.n_fields", "{n} fields", { n: selectedFieldKeys.length })}
            </span>
          </div>
          <div className="rb-panel-body">
            <div className="rb-block">
              <h4>{t("page.rb.selected_datasets", "Datasets in query")}</h4>
              {selected.length === 0 ? (
                <p className="muted">{t("page.rb.hint_add_ds", "Add a dataset from the left panel.")}</p>
              ) : (
                <div className="rb-chips">
                  {selected.map((s) => (
                    <span key={s.alias} className="rb-chip">
                      {s.alias} = {dsByEntity[s.dataset]?.name || s.dataset}
                      <button type="button" onClick={() => removeDataset(s.dataset)} aria-label="remove">
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="rb-block">
              <h4>{t("page.rb.joins", "Joins")}</h4>
              {selected.length < 2 ? (
                <p className="muted">{t("page.rb.hint_join", "Joins need at least two datasets.")}</p>
              ) : (
                <>
                  {joins.map((j, i) => {
                    const leftDs = dsByEntity[selected.find((s) => s.alias === j.left)?.dataset || ""];
                    const rightDs = dsByEntity[selected.find((s) => s.alias === j.right)?.dataset || ""];
                    return (
                      <div key={i}>
                        <div className="rb-row-grid">
                          <select
                            value={j.left}
                            onChange={(e) =>
                              setJoins((prev) => prev.map((x, k) => (k === i ? { ...x, left: e.target.value, left_field: "" } : x)))
                            }
                          >
                            {selected.map((s) => (
                              <option key={s.alias} value={s.alias}>
                                {s.alias}
                              </option>
                            ))}
                          </select>
                          <select
                            value={j.left_field}
                            onChange={(e) =>
                              setJoins((prev) => prev.map((x, k) => (k === i ? { ...x, left_field: e.target.value } : x)))
                            }
                          >
                            <option value="">{t("page.rb.pick_field", "Field…")}</option>
                            {(leftDs?.fields || []).map((f) => (
                              <option key={f.name} value={f.name}>
                                {f.label}
                              </option>
                            ))}
                          </select>
                          <select
                            value={j.join_type}
                            onChange={(e) =>
                              setJoins((prev) => prev.map((x, k) => (k === i ? { ...x, join_type: e.target.value } : x)))
                            }
                          >
                            {JOIN_TYPES.map((jt) => (
                              <option key={jt} value={jt}>
                                {jt}
                              </option>
                            ))}
                          </select>
                          <select
                            value={j.right}
                            onChange={(e) =>
                              setJoins((prev) => prev.map((x, k) => (k === i ? { ...x, right: e.target.value, right_field: "" } : x)))
                            }
                          >
                            {selected.map((s) => (
                              <option key={s.alias} value={s.alias}>
                                {s.alias}
                              </option>
                            ))}
                          </select>
                          <select
                            value={j.right_field}
                            onChange={(e) =>
                              setJoins((prev) => prev.map((x, k) => (k === i ? { ...x, right_field: e.target.value } : x)))
                            }
                          >
                            <option value="">{t("page.rb.pick_field", "Field…")}</option>
                            {(rightDs?.fields || []).map((f) => (
                              <option key={f.name} value={f.name}>
                                {f.label}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="rb-row-del"
                            onClick={() => setJoins((prev) => prev.filter((_, k) => k !== i))}
                          >
                            ×
                          </button>
                        </div>
                        <div className="rb-join-line">
                          {j.left}.{j.left_field} {j.join_type} {j.right}.{j.right_field}
                        </div>
                      </div>
                    );
                  })}
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() =>
                      setJoins((prev) => [
                        ...prev,
                        {
                          left: selected[0]?.alias || "",
                          right: selected[1]?.alias || "",
                          join_type: "left",
                          left_field: "",
                          right_field: "",
                        },
                      ])
                    }
                  >
                    {t("page.rb.add_join", "Add join")}
                  </button>
                </>
              )}
            </div>

            <div className="rb-block">
              <h4>{t("page.rb.fields", "Fields")}</h4>
              {!selectedFieldKeys.length ? (
                <p className="muted">{t("page.rb.hint_fields", "Expand a dataset on the left and click fields to select.")}</p>
              ) : (
                selectedFieldKeys.map((key) => {
                  const dot = key.indexOf(".");
                  const alias = key.slice(0, dot);
                  const field = key.slice(dot + 1);
                  const ds = dsByEntity[selected.find((s) => s.alias === alias)?.dataset || ""];
                  return (
                    <div key={key} className="rb-field-row">
                      <input
                        type="checkbox"
                        checked={fieldState[key]?.visible !== false}
                        onChange={() => setFieldState((prev) => ({ ...prev, [key]: { ...prev[key], visible: !prev[key]?.visible } }))}
                      />
                      <span>
                        {alias}.{fieldLabelOf(ds, field)}
                      </span>
                      <input
                        type="text"
                        className="rb-field-label"
                        value={fieldState[key]?.label ?? ""}
                        placeholder={fieldLabelOf(ds, field)}
                        onChange={(e) =>
                          setFieldState((prev) => ({ ...prev, [key]: { ...prev[key], label: e.target.value } }))
                        }
                        aria-label={t("page.rb.label", "Label")}
                      />
                      <select
                        value={fieldState[key]?.agg || ""}
                        onChange={(e) => setFieldAgg(key, e.target.value)}
                        aria-label={t("page.rb.agg", "Aggregation")}
                      >
                        {AGG_OPTIONS.map((a) => (
                          <option key={a} value={a}>
                            {a || t("page.rb.agg_none", "none")}
                          </option>
                        ))}
                      </select>
                      <select
                        value={fieldState[key]?.format || ""}
                        onChange={(e) =>
                          setFieldState((prev) => ({ ...prev, [key]: { ...prev[key], format: e.target.value } }))
                        }
                        aria-label={t("page.rb.format", "Format")}
                      >
                        {FORMAT_OPTIONS.map((f) => (
                          <option key={f} value={f}>
                            {f || t("page.rb.format_none", "auto")}
                          </option>
                        ))}
                      </select>
                    </div>
                  );
                })
              )}
            </div>

            <div className="rb-block">
              <h4>{t("page.rb.filters", "Filters")}</h4>
              {filters.map((f, i) => {
                const ds = dsByEntity[selected.find((s) => s.alias === f.dataset)?.dataset || ""];
                return (
                  <div key={i} className="rb-row-grid">
                    <select
                      value={f.dataset}
                      onChange={(e) =>
                        setFilters((prev) => prev.map((x, k) => (k === i ? { ...x, dataset: e.target.value, field: "" } : x)))
                      }
                    >
                      {selected.map((s) => (
                        <option key={s.alias} value={s.alias}>
                          {s.alias}
                        </option>
                      ))}
                    </select>
                    <select
                      value={f.field}
                      onChange={(e) => setFilters((prev) => prev.map((x, k) => (k === i ? { ...x, field: e.target.value } : x)))}
                    >
                      <option value="">{t("page.rb.pick_field", "Field…")}</option>
                      {(ds?.fields || []).map((fd) => (
                        <option key={fd.name} value={fd.name}>
                          {fd.label}
                        </option>
                      ))}
                    </select>
                    <select
                      value={f.op}
                      onChange={(e) => setFilters((prev) => prev.map((x, k) => (k === i ? { ...x, op: e.target.value } : x)))}
                    >
                      {FILTER_OPS.map((op) => (
                        <option key={op} value={op}>
                          {op}
                        </option>
                      ))}
                    </select>
                    <input
                      type="text"
                      value={f.value}
                      onChange={(e) => setFilters((prev) => prev.map((x, k) => (k === i ? { ...x, value: e.target.value } : x)))}
                      placeholder={t("page.rb.value", "Value")}
                    />
                    <button
                      type="button"
                      className="rb-row-del"
                      onClick={() => setFilters((prev) => prev.filter((_, k) => k !== i))}
                    >
                      ×
                    </button>
                  </div>
                );
              })}
              <button
                type="button"
                className="btn btn-ghost"
                disabled={!selected.length}
                onClick={() =>
                  setFilters((prev) => [
                    ...prev,
                    { dataset: selected[0]?.alias || "", field: "", op: "eq", value: "" },
                  ])
                }
              >
                {t("page.rb.add_filter", "Add filter")}
              </button>
            </div>

            <div className="rb-block">
              <h4>{t("page.rb.group_by", "Group by")}</h4>
              {!selectedFieldKeys.length ? (
                <p className="muted">{t("page.rb.hint_group", "Select fields first, then choose group-by columns.")}</p>
              ) : (
                <div className="rb-group-list">
                  {selectedFieldKeys.map((key) => (
                    <label key={key}>
                      <input
                        type="checkbox"
                        checked={groupKeys.includes(key)}
                        onChange={() =>
                          setGroupKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
                        }
                      />
                      {key}
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right — live preview */}
        <div className="rb-panel rb-preview">
          <div className="rb-panel-head">
            <h3>{t("page.rb.preview", "Preview")}</h3>
            <span className="rb-preview-meta">
              {preview ? t("page.rb.n_rows", "{n} rows", { n: preview.total_rows }) : t("page.rb.not_run", "Not run")}
            </span>
          </div>
          <div className="rb-panel-body">
            {!preview ? (
              <p className="muted">{t("page.rb.hint_preview", "Press Preview to sample the query result.")}</p>
            ) : (
              <DataGrid
                columns={previewColumns}
                data={preview.rows}
                rowKey={(_, i) => String(i)}
                loading={busy}
                showFooter
                storageKey="rb-preview"
                emptyText={t("common.empty", "No records")}
              />
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
