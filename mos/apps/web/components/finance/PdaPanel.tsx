"use client";

// 3.6：PDA/FDA 面板（自取数 + 创建/流转）。

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { LookupSelect } from "@/components/LookupSelect";
import { Num } from "@/components/Num";
import { useToast } from "@/components/ToastProvider";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type VoyageRef = { id: string; voyage_no: string };
type Pda = { id: string; voyage_id: string | null; status: string; pda_amount: number; fda_amount?: number | null; variance?: number | null; currency: string };

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
  const ctx = useContextMenu<Pda>();

  const load = useCallback(async () => {
    const [p, v] = await Promise.all([
      apiGet("/api/v1/port-disbursements").catch(() => []),
      apiGet("/api/v1/voyages").catch(() => []),
    ]);
    setPdas(p);
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
      await apiPost("/api/v1/port-disbursements", {
        voyage_id: voyage || null,
        pda_amount: Number(pdaAmount) || 0,
        currency: currency || "USD",
        lines: {},
      });
      toast.success(t("page.finance.pda_ok", "PDA created"));
      await load();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function transition(id: string, target: string) {
    setBusy(true);
    try {
      const q = new URLSearchParams({ target });
      if (target === "fda" && fdaAmount) q.set("fda_amount", String(Number(fdaAmount) || 0));
      await apiPost(`/api/v1/port-disbursements/${id}/transition?${q.toString()}`);
      toast.success(t("page.finance.pda_moved", "PDA → {target}", { target }));
      setFdaAmount("");
      await load();
    } catch (ex) {
      toast.error(String(ex));
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
      },
      {
        key: "pda_amount",
        title: "PDA",
        align: "right",
        value: (r) => r.pda_amount,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "fda_amount",
        title: "FDA",
        align: "right",
        value: (r) => r.fda_amount ?? null,
        render: (v) => <Num v={v as number | null} digits={2} />,
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
        width: 170,
        value: () => "",
        render: (_v, r) => (
          <div className="desk-toolbar" style={{ margin: 0 }}>
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
        <DataGrid<Pda>
          columns={cols}
          data={pdas}
          rowKey={(r) => r.id}
          onRowContextMenu={(row, _i, e) => ctx.open(row)(e)}
          storageKey="finance_pda_grid"
          showFooter={false}
          emptyText={t("common.empty", "No records")}
        />
      </div>
      <ContextMenu controller={ctx} items={menuItems} />
    </>
  );
}
