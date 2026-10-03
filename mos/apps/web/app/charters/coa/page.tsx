"use client";

// Phase 6 — COA Manager：包运合同列表（DataGrid + 状态/计价过滤，行点击进工作台）。

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { RecordModal } from "@/components/RecordModal";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { DateInput } from "@/components/DateInput";
import { PageHeader } from "@/components/PageHeader";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type CoaContract = {
  id: string;
  coa_no: string;
  charter_id: string;
  total_qty: number;
  qty_unit: string;
  period_from: string;
  period_to: string;
  rate_basis: string;
  rate: number;
  currency: string;
  cargo_spec: string | null;
  status: string;
};

type CharterRef = { id: string; charter_no: string; counterparty_id?: string | null };
type RefItem = { id: string; name: string };

/** API 返回数组或 {items|datasets} 信封 — 统一成数组。 */
function asArray<T>(raw: unknown): T[] {
  if (Array.isArray(raw)) return raw as T[];
  if (raw && typeof raw === "object") {
    const o = raw as Record<string, unknown>;
    if (Array.isArray(o.items)) return o.items as T[];
    if (Array.isArray(o.datasets)) return o.datasets as T[];
    if (Array.isArray(o.results)) return o.results as T[];
  }
  return [];
}

export default function CoaListPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();

  const [rows, setRows] = useState<CoaContract[]>([]);
  const [charters, setCharters] = useState<CharterRef[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const [statusFilter, setStatusFilter] = useState("");
  const [basisFilter, setBasisFilter] = useState("");

  const [openCreate, setOpenCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    coa_no: "",
    charter_id: "",
    total_qty: "",
    qty_unit: "mt",
    period_from: "",
    period_to: "",
    rate_basis: "per_voyage",
    rate: "",
    currency: "USD",
    cargo_spec: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const [c, ch, p] = await Promise.all([
        apiGet("/api/v1/coa"),
        apiGet("/api/v1/charters"),
        apiGet("/api/v1/masterdata/counterparties"),
      ]);
      setRows(asArray<CoaContract>(c));
      setCharters(ch || []);
      setParties(p || []);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function chartererOf(charterId: string) {
    const ch = charters.find((x) => x.id === charterId);
    if (!ch?.counterparty_id) return "—";
    return parties.find((p) => p.id === ch.counterparty_id)?.name || ch.counterparty_id.slice(0, 8);
  }

  const filtered = useMemo(
    () =>
      rows.filter((r) => {
        if (statusFilter && r.status !== statusFilter) return false;
        if (basisFilter && r.rate_basis !== basisFilter) return false;
        return true;
      }),
    [rows, statusFilter, basisFilter],
  );

  const columns: ColumnDef<CoaContract>[] = useMemo(
    () => [
      {
        key: "coa_no",
        title: t("page.coa.col.coa_no", "COA no"),
        width: 140,
        sticky: true,
        value: (r) => r.coa_no,
        render: (v) => <strong>{String(v ?? "")}</strong>,
      },
      {
        key: "charterer",
        title: t("page.coa.col.charterer", "Charterer"),
        width: 160,
        value: (r) => chartererOf(r.charter_id),
      },
      {
        key: "total_qty",
        title: t("page.coa.col.total_qty", "Total qty"),
        align: "right",
        width: 120,
        agg: "sum",
        value: (r) => r.total_qty,
        render: (v, r) => `${Number(v ?? 0).toLocaleString()} ${r.qty_unit || ""}`,
      },
      {
        key: "period",
        title: t("page.coa.col.period", "Period"),
        width: 175,
        value: (r) => `${String(r.period_from || "").slice(0, 10)} → ${String(r.period_to || "").slice(0, 10)}`,
      },
      {
        key: "rate_basis",
        title: t("page.coa.col.rate_basis", "Rate basis"),
        width: 110,
        value: (r) => r.rate_basis,
      },
      {
        key: "rate",
        title: t("page.coa.col.rate", "Rate"),
        align: "right",
        width: 110,
        value: (r) => r.rate,
        render: (v, r) => `${Number(v ?? 0).toLocaleString()} ${r.currency || ""}`,
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 95,
        value: (r) => r.status,
        render: (v) => <span className={`badge tc-status-${String(v)}`}>{String(v)}</span>,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, charters, parties],
  );

  async function create() {
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {
        charter_id: form.charter_id,
        total_qty: Number(form.total_qty),
        qty_unit: form.qty_unit,
        period_from: form.period_from,
        period_to: form.period_to,
        rate_basis: form.rate_basis,
        rate: Number(form.rate),
        currency: form.currency,
      };
      if (form.coa_no) payload.coa_no = form.coa_no;
      if (form.cargo_spec) payload.cargo_spec = form.cargo_spec;
      const created = await apiPost("/api/v1/coa", payload);
      toast.success(t("page.coa.created", "COA created"));
      setOpenCreate(false);
      await load();
      if (created?.id) router.push(`/charters/coa/${created.id}`);
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell
      breadcrumbs={[
        { label: t("page.charters.title", "Charters"), href: "/charters" },
        { label: t("page.coa.title", "COA") },
      ]}
    >
      <PageHeader
        title={t("page.coa.title", "COA")}
        subtitle={t("page.coa.sub", "Contracts of Affreightment. Click a row to open the COA Manager workspace.")}
        actions={
          <div className="coa-toolbar">
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label={t("common.status", "Status")}>
              <option value="">{t("common.all", "All")}</option>
              {["draft", "active", "completed", "cancelled"].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select value={basisFilter} onChange={(e) => setBasisFilter(e.target.value)} aria-label={t("page.coa.col.rate_basis", "Rate basis")}>
              <option value="">{t("common.all", "All")}</option>
              {["per_voyage", "per_mt", "lumpsum"].map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <button type="button" className="btn btn-primary" onClick={() => setOpenCreate(true)}>
              {t("common.create", "Create")}
            </button>
          </div>
        }
      />

      {err ? <p className="flash-err">{err}</p> : null}

      <div className="panel">
        <DataGrid
          columns={columns}
          data={filtered}
          rowKey={(r) => r.id}
          loading={loading}
          showFooter={false}
          storageKey="coa-list"
          emptyText={t("common.empty", "No records")}
          onRowDoubleClick={(r) => router.push(`/charters/coa/${r.id}`)}
          onRowClick={(r) => router.push(`/charters/coa/${r.id}`)}
        />
      </div>

      <RecordModal
        open={openCreate}
        title={t("page.coa.create", "New COA")}
        onClose={() => setOpenCreate(false)}
        onSave={create}
        canDelete={false}
        saving={busy}
        size="lg"
      >
        <FormPanel columns={2}>
          <FormSection title={t("page.coa.terms.basic", "Contract")} dense>
            <FieldRow label={t("page.coa.col.coa_no", "COA no")}>
              <input
                value={form.coa_no}
                onChange={(e) => setForm((f) => ({ ...f, coa_no: e.target.value }))}
                placeholder={t("page.coa.terms.coa_no_hint", "Auto when empty")}
              />
            </FieldRow>
            <FieldRow label={t("page.coa.col.charterer", "Charterer")}>
              <select
                value={form.charter_id}
                onChange={(e) => setForm((f) => ({ ...f, charter_id: e.target.value }))}
                required
              >
                <option value="">{t("common.select", "Select…")}</option>
                {charters.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.charter_no}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.coa.terms.cargo_spec", "Cargo spec")}>
              <input value={form.cargo_spec} onChange={(e) => setForm((f) => ({ ...f, cargo_spec: e.target.value }))} />
            </FieldRow>
          </FormSection>
          <FormSection title={t("page.coa.terms.quantity", "Quantity & period")} dense>
            <FieldRow label={t("page.coa.col.total_qty", "Total qty")}>
              <input
                type="number"
                step="any"
                value={form.total_qty}
                onChange={(e) => setForm((f) => ({ ...f, total_qty: e.target.value }))}
                required
              />
            </FieldRow>
            <FieldRow label={t("page.coa.terms.qty_unit", "Unit")}>
              <select value={form.qty_unit} onChange={(e) => setForm((f) => ({ ...f, qty_unit: e.target.value }))}>
                <option value="mt">mt</option>
                <option value="bbl">bbl</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.coa.col.period_from", "Period from")}>
              <DateInput value={form.period_from} onChange={(v) => setForm((f) => ({ ...f, period_from: v }))} />
            </FieldRow>
            <FieldRow label={t("page.coa.col.period_to", "Period to")}>
              <DateInput value={form.period_to} onChange={(v) => setForm((f) => ({ ...f, period_to: v }))} />
            </FieldRow>
          </FormSection>
          <FormSection title={t("page.coa.terms.rate", "Rate")} dense>
            <FieldRow label={t("page.coa.col.rate_basis", "Rate basis")}>
              <select value={form.rate_basis} onChange={(e) => setForm((f) => ({ ...f, rate_basis: e.target.value }))}>
                <option value="per_voyage">per_voyage</option>
                <option value="per_mt">per_mt</option>
                <option value="lumpsum">lumpsum</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.coa.col.rate", "Rate")}>
              <input type="number" step="any" value={form.rate} onChange={(e) => setForm((f) => ({ ...f, rate: e.target.value }))} required />
            </FieldRow>
            <FieldRow label={t("page.tc.terms.currency", "Currency")}>
              <select value={form.currency} onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))}>
                {["USD", "EUR", "GBP", "CNY"].map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </FieldRow>
          </FormSection>
        </FormPanel>
      </RecordModal>
    </AppShell>
  );
}
