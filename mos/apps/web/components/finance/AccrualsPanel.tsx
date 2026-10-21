"use client";

// 3.6：Voyage accruals 面板（自取数 + 创建/过账）。

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { LookupSelect } from "@/components/LookupSelect";
import { Num } from "@/components/Num";
import { RowActions } from "@/components/RowActions";
import { useToast } from "@/components/ToastProvider";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type VoyageRef = { id: string; voyage_no: string };
type Accrual = { id: string; voyage_id: string | null; period_ym: string; line_type: string; amount: number; currency: string; status: string };

export function AccrualsPanel() {
  const { t } = useI18n();
  const toast = useToast();
  const [accruals, setAccruals] = useState<Accrual[]>([]);
  const [voyages, setVoyages] = useState<VoyageRef[]>([]);
  const [period, setPeriod] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [lineType, setLineType] = useState("freight");
  const [amount, setAmount] = useState("10000");
  const [voyage, setVoyage] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [busy, setBusy] = useState(false);
  const ctx = useContextMenu<Accrual>();

  const load = useCallback(async () => {
    const [a, v] = await Promise.all([
      apiGet("/api/v1/finance/accruals").catch(() => []),
      apiGet("/api/v1/voyages").catch(() => []),
    ]);
    setAccruals(a);
    setVoyages(v);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await apiPost("/api/v1/finance/accruals", {
        voyage_id: voyage || null,
        period_ym: period,
        line_type: lineType,
        amount: Number(amount) || 0,
        currency: currency || "USD",
      });
      toast.success(t("page.finance.accrual_ok", "Accrual created"));
      await load();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function post(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/finance/accruals/${id}/post`);
      toast.success(t("page.finance.accrual_posted", "Accrual posted"));
      await load();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  // 行内编辑（失焦保存；值未变化不发请求；仅草稿可改）
  async function onCellSave(rowId: string, colKey: string, value: unknown, row: Accrual) {
    if (row.status !== "draft") return;
    const src = row as unknown as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "amount") {
      const n = value === null || value === "" ? null : Number(value);
      if (n === null || isNaN(n) || n < 0) return;
      if (Number(src.amount ?? -1) === n) return;
      payload = { amount: n };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      if (value === "" && (colKey === "voyage_id" || colKey === "notes")) payload = { [colKey]: null };
      else if (value === "") return; // period/line_type 非空列不允许空串
      else payload = { [colKey]: value };
    }
    try {
      await apiPatch(`/api/v1/finance/accruals/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  async function remove(id: string) {
    try {
      await apiDelete(`/api/v1/finance/accruals/${id}`);
      toast.success(t("common.deleted", "Deleted"));
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  const cols = useMemo<ColumnDef<Accrual>[]>(
    () => [
      {
        key: "period_ym",
        title: t("page.finance.period", "Period YYYY-MM"),
        width: 110,
        value: (r) => r.period_ym,
        editor: {
          type: "text",
          validate: (v) =>
            /^\d{4}-\d{2}$/.test(String(v ?? "")) ? null : t("page.finance.accrual_period_fmt", "Format YYYY-MM"),
        },
      },
      {
        key: "line_type",
        title: t("common.type", "类型"),
        width: 110,
        value: (r) => r.line_type,
        editor: {
          type: "select",
          options: ["freight", "hire", "commission", "bunker", "port", "other"].map((x) => ({
            value: x,
            label: x,
          })),
        },
      },
      {
        key: "voyage_id",
        title: t("page.voyages.list", "Voyages"),
        value: (r) => r.voyage_id ?? "",
        render: (v, r) =>
          r.voyage_id
            ? voyages.find((x) => x.id === r.voyage_id)?.voyage_no || r.voyage_id.slice(0, 8)
            : "—",
        editor: {
          type: "select",
          options: voyages.map((x) => ({ value: x.id, label: x.voyage_no })),
        },
      },
      {
        key: "amount",
        title: t("common.amount", "Amount"),
        align: "right",
        value: (r) => r.amount,
        render: (v, r) => (
          <>
            <Num v={v as number} digits={2} /> {r.currency}
          </>
        ),
        editor: { type: "number", step: 0.01 },
      },
      { key: "status", title: t("common.status", "Status"), width: 90 },
      {
        key: "actions",
        title: "",
        width: 120,
        value: () => "",
        render: (_v, r) => (
          <span className="row-actions" onClick={(e) => e.stopPropagation()}>
            {r.status === "draft" ? (
              <button
                className="btn btn-primary btn-sm"
                type="button"
                disabled={busy}
                onClick={() => post(r.id)}
              >
                {t("page.finance.post", "Post")}
              </button>
            ) : null}
            <RowActions
              canDelete={r.status === "draft"}
              onDelete={() => remove(r.id)}
              label={`${r.period_ym} ${r.line_type}`}
            />
          </span>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, busy, voyages],
  );

  const menuItems = (row: Accrual): ContextMenuItem[] => [
    { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(row.id) },
    ...(row.status === "draft"
      ? [{ key: "post", label: t("page.finance.post", "Post"), onClick: () => post(row.id) } as ContextMenuItem]
      : []),
  ];

  return (
    <>
      <form className="panel" onSubmit={create}>
        <h3 style={{ marginTop: 0 }}>{t("page.finance.new_accrual", "New accrual")}</h3>
        <div className="form-grid">
          <label>
            {t("page.finance.period", "Period YYYY-MM")}
            <input value={period} onChange={(e) => setPeriod(e.target.value)} required />
          </label>
          <label>
            {t("common.type", "类型")}
            <select value={lineType} onChange={(e) => setLineType(e.target.value)}>
              <option value="freight">{t("page.finance.line_freight", "Freight")}</option>
              <option value="hire">{t("page.finance.line_hire", "Hire")}</option>
              <option value="commission">{t("page.finance.line_commission", "Commission")}</option>
              <option value="bunker">{t("page.finance.line_bunker", "Bunker")}</option>
              <option value="port">{t("page.finance.line_port", "Port costs")}</option>
              <option value="other">{t("page.finance.line_other", "Other")}</option>
            </select>
          </label>
          <label>
            {t("common.amount", "Amount")}
            <input type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label>
            {t("page.finance.currency", "Currency")}
            <LookupSelect dataset="currencies" value={currency} onChange={setCurrency} allowEmpty={false} />
          </label>
          <label>
            {t("page.voyages.list", "Voyages")}
            <select value={voyage} onChange={(e) => setVoyage(e.target.value)}>
              <option value="">—</option>
              {voyages.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.voyage_no}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {t("common.create", "Create")}
        </button>
      </form>
      <div className="panel">
        <DataGrid<Accrual>
          columns={cols}
          data={accruals}
          rowKey={(r) => r.id}
          onRowContextMenu={(row, _i, e) => ctx.open(row)(e)}
          storageKey="finance_accruals_grid"
          showFooter={false}
          editable
          onCellSave={onCellSave}
          emptyText={t("common.empty", "No records")}
        />
      </div>
      <ContextMenu controller={ctx} items={menuItems} />
    </>
  );
}
