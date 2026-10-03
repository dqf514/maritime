"use client";

// Phase 5 — TC Manager：期租合同列表（DataGrid + 类型/状态过滤，行点击进工作台）。

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { RecordModal } from "@/components/RecordModal";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { DateInput } from "@/components/DateInput";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/DataPicker";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type RefItem = { id: string; name: string };

type TcContract = {
  id: string;
  charter_id: string;
  contract_type: string; // tci | tco
  contract_style: string; // time_charter | bareboat
  parent_contract_id: string | null;
  vessel_id: string;
  counterparty_id: string;
  delivery_port: string | null;
  delivery_date: string | null;
  redelivery_port: string | null;
  redelivery_date: string | null;
  hire_rate: number;
  hire_currency: string;
  payment_frequency: string;
  cancel_date: string | null;
  profit_share_pct: number | null;
  profit_share_threshold: number | null;
  address_comm_pct: number | null;
  brokerage_pct: number | null;
  status: string;
};

type CharterRef = { id: string; charter_no: string; charter_type: string };

function tcTypeOf(c: Pick<TcContract, "contract_type" | "contract_style">) {
  if (c.contract_style === "bareboat") return "bareboat";
  return c.contract_type === "tci" ? "tci" : "tco";
}

export default function TcListPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();

  const [rows, setRows] = useState<TcContract[]>([]);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [charters, setCharters] = useState<CharterRef[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  // create modal
  const [openCreate, setOpenCreate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    charter_id: "",
    contract_type: "tci",
    contract_style: "time_charter",
    vessel_id: "",
    counterparty_id: "",
    hire_rate: "",
    hire_currency: "USD",
    payment_frequency: "monthly",
    delivery_port: "",
    delivery_date: "",
    redelivery_port: "",
    redelivery_date: "",
    cancel_date: "",
    address_comm_pct: "",
    brokerage_pct: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const [c, v, p, ch] = await Promise.all([
        apiGet("/api/v1/tc/contracts"),
        apiGet("/api/v1/masterdata/vessels"),
        apiGet("/api/v1/masterdata/counterparties"),
        apiGet("/api/v1/charters"),
      ]);
      setRows(Array.isArray(c) ? c : []);
      setVessels(v || []);
      setParties(p || []);
      setCharters(ch || []);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function nameOf(list: RefItem[], id: string | null) {
    if (!id) return "—";
    return list.find((x) => x.id === id)?.name || id.slice(0, 8);
  }
  function charterNo(id: string) {
    return charters.find((x) => x.id === id)?.charter_no || id.slice(0, 8);
  }

  const filtered = useMemo(
    () =>
      rows.filter((r) => {
        if (typeFilter && tcTypeOf(r) !== typeFilter) return false;
        if (statusFilter && r.status !== statusFilter) return false;
        return true;
      }),
    [rows, typeFilter, statusFilter],
  );

  const columns: ColumnDef<TcContract>[] = useMemo(
    () => [
      {
        key: "contract_no",
        title: t("page.tc.col.contract_no", "Contract no"),
        width: 150,
        sticky: true,
        value: (r) => charterNo(r.charter_id),
        render: (v) => <strong>{String(v ?? "")}</strong>,
      },
      {
        key: "type",
        title: t("common.type", "Type"),
        width: 90,
        value: (r) => tcTypeOf(r),
        render: (v) =>
          v === "tci"
            ? t("page.tc.type.tci", "TC In")
            : v === "tco"
              ? t("page.tc.type.tco", "TC Out")
              : t("page.tc.type.bareboat", "Bareboat"),
      },
      {
        key: "vessel",
        title: t("page.estimates.vessel", "Vessel"),
        width: 130,
        value: (r) => nameOf(vessels, r.vessel_id),
      },
      {
        key: "counterparty",
        title: t("page.estimates.counterparty", "Counterparty"),
        width: 150,
        value: (r) => nameOf(parties, r.counterparty_id),
      },
      {
        key: "hire_rate",
        title: t("page.tc.col.hire_rate", "Hire rate"),
        align: "right",
        width: 110,
        agg: "avg",
        value: (r) => r.hire_rate,
        render: (v, r) => `${Number(v ?? 0).toLocaleString()} ${r.hire_currency}/day`,
      },
      {
        key: "status",
        title: t("common.status", "Status"),
        width: 90,
        value: (r) => r.status,
        render: (v) => <span className={`badge tc-status-${String(v)}`}>{String(v)}</span>,
      },
      {
        key: "delivery_date",
        title: t("page.tc.col.delivery", "Delivery"),
        width: 105,
        value: (r) => r.delivery_date || "",
      },
      {
        key: "redelivery_date",
        title: t("page.tc.col.redelivery", "Redelivery"),
        width: 105,
        value: (r) => r.redelivery_date || "",
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, vessels, parties, charters],
  );

  async function create() {
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {
        charter_id: form.charter_id,
        contract_type: form.contract_type,
        contract_style: form.contract_style,
        vessel_id: form.vessel_id,
        counterparty_id: form.counterparty_id,
        hire_rate: Number(form.hire_rate),
        hire_currency: form.hire_currency,
        payment_frequency: form.payment_frequency,
      };
      if (form.delivery_port) payload.delivery_port = form.delivery_port;
      if (form.delivery_date) payload.delivery_date = form.delivery_date;
      if (form.redelivery_port) payload.redelivery_port = form.redelivery_port;
      if (form.redelivery_date) payload.redelivery_date = form.redelivery_date;
      if (form.cancel_date) payload.cancel_date = form.cancel_date;
      if (form.address_comm_pct !== "") payload.address_comm_pct = Number(form.address_comm_pct);
      if (form.brokerage_pct !== "") payload.brokerage_pct = Number(form.brokerage_pct);
      const created = await apiPost("/api/v1/tc/contracts", payload);
      toast.success(t("page.tc.created", "TC contract created"));
      setOpenCreate(false);
      await load();
      if (created?.id) router.push(`/charters/tc/${created.id}`);
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  const typeOptions = [
    { value: "", label: t("common.all", "All") },
    { value: "tci", label: t("page.tc.type.tci", "TC In") },
    { value: "tco", label: t("page.tc.type.tco", "TC Out") },
    { value: "bareboat", label: t("page.tc.type.bareboat", "Bareboat") },
  ];
  const statusOptions = ["draft", "active", "completed", "cancelled"];

  return (
    <AppShell
      breadcrumbs={[{ label: t("page.charters.title", "Charters"), href: "/charters" }, { label: t("page.tc.title", "Time Charter") }]}
    >
      <PageHeader
        title={t("page.tc.title", "Time Charter")}
        subtitle={t("page.tc.sub", "TC In / TC Out / Bareboat contracts. Click a row to open the TC Manager workspace.")}
        actions={
          <div className="tc-toolbar">
            <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label={t("common.type", "Type")}>
              {typeOptions.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              aria-label={t("common.status", "Status")}
            >
              <option value="">{t("common.all", "All")}</option>
              {statusOptions.map((s) => (
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
          storageKey="tc-list"
          emptyText={t("common.empty", "No records")}
          onRowDoubleClick={(r) => router.push(`/charters/tc/${r.id}`)}
          onRowClick={(r) => router.push(`/charters/tc/${r.id}`)}
        />
      </div>

      <RecordModal
        open={openCreate}
        title={t("page.tc.create", "New TC contract")}
        onClose={() => setOpenCreate(false)}
        onSave={create}
        canDelete={false}
        saving={busy}
        size="lg"
      >
        <FormPanel columns={2}>
          <FormSection title={t("page.tc.terms.basic", "Contract")} dense>
            <FieldRow label={t("page.tc.col.contract_no", "Contract no")}>
              <select
                value={form.charter_id}
                onChange={(e) => setForm((f) => ({ ...f, charter_id: e.target.value }))}
                required
              >
                <option value="">{t("common.select", "Select…")}</option>
                {charters.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.charter_no} ({c.charter_type})
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("common.type", "Type")}>
              <select
                value={form.contract_type}
                onChange={(e) => setForm((f) => ({ ...f, contract_type: e.target.value }))}
              >
                <option value="tci">TC In</option>
                <option value="tco">TC Out</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.tc.col.style", "Style")}>
              <select
                value={form.contract_style}
                onChange={(e) => setForm((f) => ({ ...f, contract_style: e.target.value }))}
              >
                <option value="time_charter">Time charter</option>
                <option value="bareboat">Bareboat</option>
              </select>
            </FieldRow>
            <FieldRow label={t("common.status", "Status")}>
              <input value="draft" disabled />
            </FieldRow>
          </FormSection>
          <FormSection title={t("page.tc.terms.parties", "Parties & vessel")} dense>
            <FieldRow label={t("page.estimates.vessel", "Vessel")}>
              <select
                value={form.vessel_id}
                onChange={(e) => setForm((f) => ({ ...f, vessel_id: e.target.value }))}
                required
              >
                <option value="">{t("common.select", "Select…")}</option>
                {vessels.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.estimates.counterparty", "Counterparty")}>
              <PartyPicker
                value={form.counterparty_id}
                onChange={(id) => setForm((f) => ({ ...f, counterparty_id: id }))}
              />
            </FieldRow>
          </FormSection>
          <FormSection title={t("page.tc.terms.hire", "Hire")} dense>
            <FieldRow label={t("page.tc.col.hire_rate", "Hire rate")}>
              <input
                type="number"
                step="any"
                value={form.hire_rate}
                onChange={(e) => setForm((f) => ({ ...f, hire_rate: e.target.value }))}
                required
              />
            </FieldRow>
            <FieldRow label={t("page.tc.terms.currency", "Currency")}>
              <select
                value={form.hire_currency}
                onChange={(e) => setForm((f) => ({ ...f, hire_currency: e.target.value }))}
              >
                {["USD", "EUR", "GBP", "CNY"].map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.tc.terms.pay_freq", "Payment")}>
              <select
                value={form.payment_frequency}
                onChange={(e) => setForm((f) => ({ ...f, payment_frequency: e.target.value }))}
              >
                <option value="monthly">monthly</option>
                <option value="semi_monthly">semi_monthly</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.charters.address_comm", "Address comm %")}>
              <input
                type="number"
                step="any"
                value={form.address_comm_pct}
                onChange={(e) => setForm((f) => ({ ...f, address_comm_pct: e.target.value }))}
              />
            </FieldRow>
            <FieldRow label={t("page.charters.brokerage", "Brokerage %")}>
              <input
                type="number"
                step="any"
                value={form.brokerage_pct}
                onChange={(e) => setForm((f) => ({ ...f, brokerage_pct: e.target.value }))}
              />
            </FieldRow>
          </FormSection>
          <FormSection title={t("page.tc.terms.period", "Delivery / redelivery")} dense>
            <FieldRow label={t("page.tc.col.delivery", "Delivery")}>
              <DateInput
                value={form.delivery_date}
                onChange={(v) => setForm((f) => ({ ...f, delivery_date: v }))}
              />
            </FieldRow>
            <FieldRow label={t("page.tc.terms.delivery_port", "Delivery port")}>
              <input
                value={form.delivery_port}
                onChange={(e) => setForm((f) => ({ ...f, delivery_port: e.target.value }))}
              />
            </FieldRow>
            <FieldRow label={t("page.tc.col.redelivery", "Redelivery")}>
              <DateInput
                value={form.redelivery_date}
                onChange={(v) => setForm((f) => ({ ...f, redelivery_date: v }))}
              />
            </FieldRow>
            <FieldRow label={t("page.tc.terms.redelivery_port", "Redelivery port")}>
              <input
                value={form.redelivery_port}
                onChange={(e) => setForm((f) => ({ ...f, redelivery_port: e.target.value }))}
              />
            </FieldRow>
            <FieldRow label={t("page.tc.terms.cancel_date", "Cancel date")}>
              <DateInput value={form.cancel_date} onChange={(v) => setForm((f) => ({ ...f, cancel_date: v }))} />
            </FieldRow>
          </FormSection>
        </FormPanel>
      </RecordModal>
    </AppShell>
  );
}
