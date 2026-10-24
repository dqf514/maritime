"use client";

// 3.6：PDA/FDA 面板（自取数 + 创建/流转）。

import { msgOf, handled } from "@/lib/errors";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { LookupSelect } from "@/components/LookupSelect";
import { Num } from "@/components/Num";
import { RowActions } from "@/components/RowActions";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type VoyageRef = { id: string; voyage_no: string };
type Pda = { id: string; voyage_id: string | null; status: string; pda_amount: number; fda_amount?: number | null; variance?: number | null; currency: string };

// 与后端 _PDA_LOCKED_STATUSES 一致：金额已承诺后不可改/删
const PDA_LOCKED = new Set(["approved", "fda", "closed"]);

/** 数字输入解析：空串 → null；非法输入 → NaN（调用方必须报错，禁止静默转 0）。 */
function numOrNull(raw: string): number | null {
  const s = raw.trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

export function PdaPanel() {
  const { t } = useI18n();
  const toast = useToast();
  const [pdas, setPdas] = useState<Pda[]>([]);
  const [voyages, setVoyages] = useState<VoyageRef[]>([]);
  const [voyage, setVoyage] = useState("");
  const [pdaAmount, setPdaAmount] = useState("25000");
  const [fdaAmount, setFdaAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [busy, setBusy] = useState(false);
  // P1-4：主列表失败 → 三态错误；航次参照失败 → 单独提示
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refErr, setRefErr] = useState<string | null>(null);
  // 首次成功加载后，后续刷新不再整表 spinner（避免卸载 DataGrid 丢失排序/列布局）
  const loadedOnce = useRef(false);
  const ctx = useContextMenu<Pda>();

  const load = useCallback(async () => {
    if (!loadedOnce.current) setLoading(true);
    setErr(null);
    const [p, v] = await Promise.allSettled([
      apiGet("/api/v1/port-disbursements") as Promise<Pda[]>,
      apiGet("/api/v1/voyages/options") as Promise<VoyageRef[]>,
    ]);
    if (p.status === "fulfilled") {
      setPdas(Array.isArray(p.value) ? p.value : []);
      loadedOnce.current = true;
    } else {
      setPdas([]);
      setErr(msgOf(p.reason));
    }
    if (v.status === "fulfilled") {
      setVoyages(Array.isArray(v.value) ? v.value : []);
      setRefErr(null);
    } else {
      setVoyages([]);
      setRefErr(msgOf(v.reason));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load().catch(handled);
  }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    // P1-24：非法数字必须报错并中止提交，不能静默转 0
    const pda = numOrNull(pdaAmount);
    if (pda === null || Number.isNaN(pda)) {
      toast.error(t("page.finance.bad_number", "Enter a valid number"));
      return;
    }
    setBusy(true);
    try {
      await apiPost("/api/v1/port-disbursements", {
        voyage_id: voyage || null,
        pda_amount: pda,
        currency: currency || "USD",
        lines: {},
      });
      toast.success(t("page.finance.pda_ok", "PDA created"));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  // 行内编辑（失焦保存；值未变化不发请求；锁定状态直接忽略）
  async function onCellSave(rowId: string, colKey: string, value: unknown, row: Pda) {
    if (PDA_LOCKED.has(row.status)) return;
    const src = row as unknown as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "pda_amount" || colKey === "fda_amount") {
      const n = value === null || value === "" ? null : Number(value);
      if (n !== null && !Number.isFinite(n)) {
        toast.error(t("page.finance.bad_number", "Enter a valid number"));
        return;
      }
      const prev = src[colKey];
      if ((prev ?? null) === n || (prev == null && n == null)) return;
      payload = { [colKey]: n };
    } else if (colKey === "voyage_id") {
      if ((row.voyage_id ?? "") === (value ?? "")) return;
      payload = { voyage_id: value || null };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value };
    }
    try {
      await apiPatch(`/api/v1/port-disbursements/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  async function remove(id: string) {
    try {
      await apiDelete(`/api/v1/port-disbursements/${id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      await load();
    } catch (ex: any) {
      toast.error(msgOf(ex));
    }
  }

  async function transition(id: string, target: string) {
    let fdaNum: number | null = null;
    if (target === "fda" && fdaAmount.trim() !== "") {
      fdaNum = numOrNull(fdaAmount);
      if (fdaNum === null || Number.isNaN(fdaNum)) {
        toast.error(t("page.finance.bad_number", "Enter a valid number"));
        return;
      }
    }
    setBusy(true);
    try {
      const q = new URLSearchParams({ target });
      if (target === "fda" && fdaNum !== null) q.set("fda_amount", String(fdaNum));
      await apiPost(`/api/v1/port-disbursements/${id}/transition?${q.toString()}`);
      toast.success(t("page.finance.pda_moved", "PDA → {target}", { target }));
      setFdaAmount("");
      await load();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  const cols = useMemo<ColumnDef<Pda>[]>(
    () => [
      {
        key: "id",
        title: "ID",
        width: 90,
        value: (r) => r.id,
        render: (v) => String(v).slice(0, 8),
      },
      {
        key: "voyage_id",
        title: t("page.voyages.list", "Voyages"),
        value: (r) => r.voyage_id ?? "",
        render: (v, r) =>
          r.voyage_id
            ? voyages.find((x) => x.id === r.voyage_id)?.voyage_no || r.voyage_id.slice(0, 8)
            : "—",
        editor: { type: "select", options: voyages.map((x) => ({ value: x.id, label: x.voyage_no })) },
      },
      {
        key: "pda_amount",
        title: "PDA",
        align: "right",
        value: (r) => r.pda_amount,
        render: (v) => <Num v={v as number} digits={2} />,
        editor: { type: "number", step: 0.01 },
      },
      {
        key: "fda_amount",
        title: "FDA",
        align: "right",
        value: (r) => r.fda_amount ?? null,
        render: (v) => <Num v={v as number | null} digits={2} />,
        editor: { type: "number", step: 0.01 },
      },
      {
        key: "currency",
        title: t("page.finance.currency", "Currency"),
        width: 80,
        value: (r) => r.currency,
        editor: { type: "text" },
      },
      {
        key: "variance",
        title: t("page.finance.variance", "差异"),
        align: "right",
        value: (r) => r.variance ?? null,
        render: (v) => <Num v={v as number | null} digits={2} />,
      },
      { key: "status", title: t("common.status", "Status"), width: 100 },
      {
        key: "actions",
        title: "",
        width: 200,
        value: () => "",
        render: (_v, r) => (
          <div className="desk-toolbar" style={{ margin: 0 }}>
            <RowActions
              canEdit={!PDA_LOCKED.has(r.status)}
              canDelete={!PDA_LOCKED.has(r.status)}
              onDelete={() => remove(r.id)}
              label={String(r.id).slice(0, 8)}
            />
            {r.status === "draft" ? (
              <button
                className="btn btn-sm"
                type="button"
                disabled={busy}
                onClick={(e) => {
                  e.stopPropagation();
                  transition(r.id, "submitted");
                }}
              >
                {t("common.submit", "提交")}
              </button>
            ) : null}
            {r.status === "submitted" ? (
              <button
                className="btn btn-sm"
                type="button"
                disabled={busy}
                onClick={(e) => {
                  e.stopPropagation();
                  transition(r.id, "approved");
                }}
              >
                {t("common.approve", "批准")}
              </button>
            ) : null}
            {r.status === "approved" ? (
              <button
                className="btn btn-primary btn-sm"
                type="button"
                disabled={busy}
                onClick={(e) => {
                  e.stopPropagation();
                  transition(r.id, "fda");
                }}
              >
                → FDA
              </button>
            ) : null}
          </div>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, busy, voyages, fdaAmount],
  );

  // 同源 handler：右键菜单与行内按钮共用 transition()
  const menuItems = (row: Pda): ContextMenuItem[] => {
    const items: ContextMenuItem[] = [
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(row.id) },
    ];
    if (row.status === "draft") {
      items.push({ key: "submit", label: t("common.submit", "提交"), onClick: () => transition(row.id, "submitted") });
    }
    if (row.status === "submitted") {
      items.push({ key: "approve", label: t("common.approve", "批准"), onClick: () => transition(row.id, "approved") });
    }
    if (row.status === "approved") {
      items.push({ key: "fda", label: "→ FDA", onClick: () => transition(row.id, "fda") });
    }
    return items;
  };

  return (
    <>
      {refErr ? (
        <p className="flash-err">
          {t("page.finance.ref_load_failed", "Some reference lists could not be loaded")}: {refErr}
        </p>
      ) : null}
      <form className="panel" onSubmit={create}>
        <h3 style={{ marginTop: 0 }}>{t("page.finance.new_pda", "New PDA")}</h3>
        <div className="form-grid">
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
          <label>
            PDA {t("common.amount", "Amount")}
            <input type="number" step="any" value={pdaAmount} onChange={(e) => setPdaAmount(e.target.value)} />
          </label>
          <label>
            {t("page.finance.currency", "Currency")}
            <LookupSelect dataset="currencies" value={currency} onChange={setCurrency} allowEmpty={false} />
          </label>
          <label>
            FDA {t("page.finance.fda_amount", "FDA amount (on transfer)")}
            <input type="number" step="any" value={fdaAmount} onChange={(e) => setFdaAmount(e.target.value)} placeholder={t("common.optional", "Optional")} />
          </label>
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {t("common.create", "Create")}
        </button>
      </form>
      <div className="panel">
        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!pdas.length}
          emptyText={t("common.empty", "No records")}
          onRetry={() => load()}
        >
          <DataGrid<Pda>
            columns={cols}
            data={pdas}
            rowKey={(r) => r.id}
            onRowContextMenu={(row, _i, e) => ctx.open(row)(e)}
            storageKey="finance_pda_grid"
            showFooter={false}
            editable
            onCellSave={onCellSave}
            emptyText={t("common.empty", "No records")}
          />
        </StateView>
      </div>
      <ContextMenu controller={ctx} items={menuItems} />
    </>
  );
}
