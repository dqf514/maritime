"use client";

// 3.6：Invoices 面板（自取数 + 创建/hire 排程 + 分页表 + 批量导出）。

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { DateInput } from "@/components/DateInput";
import { ExportButton } from "@/components/ExportButton";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiList, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { fmt } from "@/lib/fmt";
import { readFormDefaults, writeFormDefaults } from "@/lib/formDefaults";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

const INVOICE_TYPES = ["freight", "hire", "demurrage", "bunker", "port_disbursement", "credit_note", "other"];

type RefItem = { id: string; name: string };
type VoyageRef = { id: string; voyage_no: string };
type CharterRef = { id: string; charter_no: string };
type Invoice = {
  id: string;
  invoice_no: string;
  status: string;
  amount: number;
  paid_amount?: number;
  invoice_type?: string;
  base_amount?: number | null;
};

export function InvoicesPanel() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery, page, limit } = useListQuery();

  const [rows, setRows] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [sel, setSel] = useState<Set<string | number>>(new Set());
  const [voyages, setVoyages] = useState<VoyageRef[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [charters, setCharters] = useState<CharterRef[]>([]);
  const [busy, setBusy] = useState(false);

  const [invType, setInvType] = useState(() => readFormDefaults("finance.invoice", { invType: "freight" }).invType);
  const [invAmount, setInvAmount] = useState("100000");
  const [invFx, setInvFx] = useState(() => readFormDefaults("finance.invoice", { invFx: "" }).invFx);
  const [invVoyage, setInvVoyage] = useState("");
  const [invParty, setInvParty] = useState("");
  const [hsCharter, setHsCharter] = useState("");
  const [hsStart, setHsStart] = useState("");
  const [hsEnd, setHsEnd] = useState("");

  const loadRefs = useCallback(async () => {
    const [v, p, ch] = await Promise.all([
      apiGet("/api/v1/voyages").catch(() => []),
      apiGet("/api/v1/masterdata/counterparties").catch(() => []),
      apiGet("/api/v1/charters").catch(() => []),
    ]);
    setVoyages(v);
    setParties(p);
    setCharters(ch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadList = useCallback(async () => {
    const pg = await apiList<Invoice>("/api/v1/invoices", { limit, offset: (page - 1) * limit });
    setRows(pg.items);
    setTotal(pg.total);
    if (!pg.items.length && pg.total > 0 && page > 1) setQuery({ page: Math.ceil(pg.total / limit) });
  }, [limit, page, setQuery]);

  useEffect(() => {
    loadRefs().catch(() => undefined);
  }, [loadRefs]);
  useEffect(() => {
    loadList().catch(() => undefined);
  }, [loadList]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const amount = Number(invAmount);
    if (!invAmount.trim() || Number.isNaN(amount)) {
      toast.error(t("page.finance.bad_amount", "金额必须是有效数字"));
      setBusy(false);
      return;
    }
    try {
      const inv = await apiPost("/api/v1/invoices", {
        invoice_type: invType,
        amount,
        voyage_id: invVoyage || null,
        counterparty_id: invParty || null,
        fx_rate: invFx === "" ? undefined : Number(invFx),
      });
      toast.success(t("page.finance.created_inv", "Invoice {no} created", { no: inv.invoice_no }));
      writeFormDefaults("finance.invoice", { invType, invFx });
      await loadList();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function createHireSchedule(e: FormEvent) {
    e.preventDefault();
    if (!hsCharter || !hsStart || !hsEnd) {
      toast.error(t("page.finance.hs_need", "请选择租约并填写期间"));
      return;
    }
    setBusy(true);
    try {
      const inv = await apiPost("/api/v1/invoices/hire-schedule", {
        charter_id: hsCharter,
        period_start: hsStart,
        period_end: hsEnd,
      });
      toast.success(t("page.finance.created_inv", "Invoice {no} created", { no: inv.invoice_no }));
      await loadList();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  const cols: ColumnDef<Invoice>[] = [
    { key: "invoice_no", title: t("page.finance.no", "编号") },
    { key: "status", title: t("common.status", "Status") },
    { key: "amount", title: t("common.amount", "Amount"), align: "right", render: (v) => fmt(v as number) },
    { key: "base_amount", title: t("page.finance.base_amount", "Base"), align: "right", render: (v) => (v != null ? fmt(v as number) : "—") },
    { key: "paid_amount", title: t("page.finance.paid_col", "已付"), align: "right", render: (v) => fmt(v as number) },
  ];

  return (
    <>
      <form className="panel" onSubmit={create}>
        <h3 style={{ marginTop: 0 }}>{t("page.finance.new_invoice", "New invoice")}</h3>
        <div className="form-grid">
          <label>
            {t("common.type", "Type")}
            <select value={invType} onChange={(e) => setInvType(e.target.value)}>
              {INVOICE_TYPES.map((it) => (
                <option key={it} value={it}>
                  {it}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("common.amount", "Amount")}
            <input type="number" step="any" value={invAmount} onChange={(e) => setInvAmount(e.target.value)} />
          </label>
          <label>
            {t("page.finance.fx_rate", "FX rate")}
            <input type="number" step="any" value={invFx} onChange={(e) => setInvFx(e.target.value)} placeholder={t("common.optional", "Optional")} />
          </label>
          <label>
            {t("page.voyages.list", "Voyages")}
            <select value={invVoyage} onChange={(e) => setInvVoyage(e.target.value)}>
              <option value="">{t("common.select", "Select…")}</option>
              {voyages.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.voyage_no}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.estimates.counterparty", "Counterparty")}
            <select value={invParty} onChange={(e) => setInvParty(e.target.value)}>
              <option value="">{t("common.select", "Select…")}</option>
              {parties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("common.create", "Create")}
          </button>
        </div>
      </form>

      <form className="panel" onSubmit={createHireSchedule}>
        <h3 style={{ marginTop: 0 }}>{t("page.finance.hire_schedule", "Hire invoice (schedule)")}</h3>
        <div className="form-grid">
          <label>
            {t("page.charters.title", "租约")}
            <select value={hsCharter} onChange={(e) => setHsCharter(e.target.value)}>
              <option value="">{t("common.select", "Select…")}</option>
              {charters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.charter_no}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.finance.period_start", "Period start")}
            <DateInput value={hsStart} onChange={setHsStart} />
          </label>
          <label>
            {t("page.finance.period_end", "Period end")}
            <DateInput value={hsEnd} onChange={setHsEnd} />
          </label>
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("page.finance.hs_generate", "生成 hire 发票")}
          </button>
        </div>
      </form>

      <div className="panel">
        <div className="desk-toolbar" style={{ marginTop: 0, justifyContent: "flex-end" }}>
          <button
            className="btn btn-sm btn-ghost"
            type="button"
            disabled={!sel.size}
            onClick={() => {
              const picked = rows.filter((r) => sel.has(r.id));
              downloadCsv(
                "invoices-selected",
                ["invoice_no", "status", "type", "amount", "base_amount", "paid_amount"],
                picked.map((r) => [r.invoice_no, r.status, r.invoice_type || "", r.amount, r.base_amount ?? "", r.paid_amount ?? ""]),
              );
            }}
          >
            {t("page.finance.export_selected", "导出所选 CSV")} {sel.size ? `(${sel.size})` : ""}
          </button>
          <ExportButton entity="invoices" />
        </div>
        <DataTable<Invoice>
          data={rows}
          columns={cols}
          paginatable
          selectable
          selectedIds={sel}
          onSelectionChange={setSel}
          storageKey="finance.invoices"
          total={total}
          page={page}
          onPageChange={(p, l) => setQuery({ page: p > 1 ? p : null, limit: l === 50 ? null : l })}
          emptyText={t("common.empty", "No records")}
          onRowClick={(r) => router.push(`/finance/invoices/${r.id}`)}
        />
      </div>
    </>
  );
}
