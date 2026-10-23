"use client";

// P11 IMOS Cargo detail — 货盘详情：CP 条款 / Laycan 四字段 / 支付块 + Itinerary / Options 子表格。
// 数据源：GET/PATCH /api/v1/cargo/{id}，CRUD /cargo/{id}/itinerary、/cargo/{id}/options。

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DateInput, DateTimeInput } from "@/components/DateInput";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { DetailHeader } from "@/components/DetailHeader";
import { FormPanel, FormSection, FieldRow } from "@/components/form/FormPanel";
import { Num } from "@/components/Num";
import { StateView } from "@/components/StateView";
import { Tabs, type TabItem } from "@/components/Tabs";
import { useToast } from "@/components/ToastProvider";
import { useStateActions } from "@/components/useTransitions";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type CargoDetail = {
  id: string;
  cargo_no: string;
  cargo_type: string | null;
  commodity: string | null;
  qty: number | null;
  qty_unit: string | null;
  load_port_id: string | null;
  disch_port_id: string | null;
  laycan_from: string | null;
  laycan_to: string | null;
  charterer_id: string | null;
  freight_basis: string | null;
  freight_rate: number | null;
  status: string;
  voyage_id: string | null;
  charter_id: string | null;
  coa_id: string | null;
  notes: string | null;
  // P11 IMOS Cargo detail
  cargo_name_id: string | null;
  api_gravity: number | null;
  specific_gravity: number | null;
  cp_date: string | null;
  cp_form: string | null;
  option_pct: number | null;
  option_type: string | null;
  min_qty: number | null;
  max_qty: number | null;
  freight_type: string | null;
  currency: string | null;
  exchange_rate: number | null;
  min_inv_qty: number | null;
  freight_via: string | null;
  demurrage_via: string | null;
  cp_draft_m: number | null;
  coordinator: string | null;
  reference_no: string | null;
  booking_no: string | null;
  vc_in_id: string | null;
  nominated_vessel_id: string | null;
  voyage_no: string | null;
  contract_link: string | null;
  company_code: string | null;
  department: string | null;
  trade_area: string | null;
  laycan_from_override: string | null;
  laycan_to_override: string | null;
  laycan_confirmed: boolean;
  remittance_bank: string | null;
  invoice_pct: number | null;
  balance_pct: number | null;
  payment_terms_code: string | null;
  payment_terms_desc: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

type CargoItinRow = {
  id: string;
  cargo_id: string;
  seq: number;
  flag: string;
  port_id: string | null;
  port_name: string | null;
  berth: string | null;
  qty: number | null;
  ld_rate: number | null;
  ru: string | null;
  terms: string | null;
  incoterms: string | null;
  port_exp: number | null;
  oexp_per_t: number | null;
  liner_exp: number | null;
  draft: number | null;
  unit: string | null;
  salinity: number | null;
};

type CargoOptRow = {
  id: string;
  cargo_id: string;
  kind: "load" | "disch";
  seq: number;
  port_area: string | null;
  ld_rate: number | null;
  ru: string | null;
  terms: string | null;
  tt_days: number | null;
  pexp: number | null;
  draft: number | null;
};

type RefItem = { id: string; name: string };

const TAB_KEYS = ["terms", "itinerary", "options"] as const;
type TabId = (typeof TAB_KEYS)[number];

const STR_FIELDS = [
  "cargo_type", "commodity", "qty_unit", "freight_basis", "cp_form", "option_type",
  "freight_type", "currency", "freight_via", "demurrage_via", "coordinator",
  "reference_no", "booking_no", "vc_in_id", "voyage_no", "contract_link",
  "company_code", "department", "trade_area", "payment_terms_code",
  "payment_terms_desc", "remittance_bank", "notes",
] as const;
const REF_FIELDS = ["load_port_id", "disch_port_id", "charterer_id", "nominated_vessel_id", "cargo_name_id"] as const;
const DATE_FIELDS = ["laycan_from", "laycan_to", "cp_date"] as const;
const DT_FIELDS = ["laycan_from_override", "laycan_to_override"] as const;
const NUM_FIELDS = [
  "qty", "freight_rate", "option_pct", "min_qty", "max_qty", "exchange_rate",
  "min_inv_qty", "cp_draft_m", "api_gravity", "specific_gravity",
  "invoice_pct", "balance_pct",
] as const;

function numStr(v: number | null | undefined): string {
  return v == null ? "" : String(v);
}

function toDraft(c: CargoDetail): Record<string, string> {
  const d: Record<string, string> = {};
  for (const f of STR_FIELDS) d[f] = (c as unknown as Record<string, string | null>)[f] ?? "";
  for (const f of REF_FIELDS) d[f] = (c as unknown as Record<string, string | null>)[f] ?? "";
  for (const f of DATE_FIELDS) d[f] = ((c as unknown as Record<string, string | null>)[f] ?? "").slice(0, 10);
  for (const f of DT_FIELDS) d[f] = ((c as unknown as Record<string, string | null>)[f] ?? "").slice(0, 16).replace(" ", "T");
  for (const f of NUM_FIELDS) d[f] = numStr((c as unknown as Record<string, number | null>)[f]);
  d.laycan_confirmed = c.laycan_confirmed ? "1" : "0";
  return d;
}

const EMPTY_ITIN = {
  seq: "", flag: "L", port_id: "", berth: "", qty: "", ld_rate: "", ru: "",
  terms: "", incoterms: "", port_exp: "", oexp_per_t: "", liner_exp: "",
  draft: "", unit: "", salinity: "",
};

const EMPTY_OPT = { seq: "", port_area: "", ld_rate: "", ru: "", terms: "", tt_days: "", pexp: "", draft: "" };

export default function CargoDetailPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const cargoId = params.id;

  const [cargo, setCargo] = useState<CargoDetail | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [ports, setPorts] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [cargoNames, setCargoNames] = useState<RefItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<TabId>("terms");

  const [itinRows, setItinRows] = useState<CargoItinRow[]>([]);
  const [itinBusy, setItinBusy] = useState(false);
  const [itinForm, setItinForm] = useState(EMPTY_ITIN);
  const [optRows, setOptRows] = useState<CargoOptRow[]>([]);
  const [optBusy, setOptBusy] = useState(false);
  const [optForms, setOptForms] = useState({ load: EMPTY_OPT, disch: EMPTY_OPT });

  const nextStatuses = useStateActions("cargo", cargo?.status);

  const load = useCallback(async () => {
    setLoading(true);
    setErr("");
    try {
      const c = await apiGet(`/api/v1/cargo/${cargoId}`);
      setCargo(c);
      setDraft(toDraft(c));
      apiGet("/api/v1/masterdata/ports")
        .then((p: RefItem[]) => setPorts(Array.isArray(p) ? p : []))
        .catch(() => setPorts([]));
      apiGet("/api/v1/masterdata/counterparties")
        .then((p: RefItem[]) => setParties(Array.isArray(p) ? p : []))
        .catch(() => setParties([]));
      apiGet("/api/v1/masterdata/vessels")
        .then((v: RefItem[]) => setVessels(Array.isArray(v) ? v : []))
        .catch(() => setVessels([]));
      apiGet("/api/v1/masterdata/cargo-names")
        .then((n: RefItem[]) => setCargoNames(Array.isArray(n) ? n : []))
        .catch(() => setCargoNames([]));
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }, [cargoId]);

  useEffect(() => {
    load();
  }, [load]);

  const loadItinerary = useCallback(async () => {
    setItinBusy(true);
    try {
      const res = await apiGet(`/api/v1/cargo/${cargoId}/itinerary`);
      setItinRows(Array.isArray(res) ? res : []);
    } catch {
      setItinRows([]);
    } finally {
      setItinBusy(false);
    }
  }, [cargoId]);

  const loadOptions = useCallback(async () => {
    setOptBusy(true);
    try {
      const res = await apiGet(`/api/v1/cargo/${cargoId}/options`);
      const all: CargoOptRow[] = Array.isArray(res) ? res : [];
      setOptRows(all);
    } catch {
      setOptRows([]);
    } finally {
      setOptBusy(false);
    }
  }, [cargoId]);

  useEffect(() => {
    if (tab === "itinerary") loadItinerary();
    if (tab === "options") loadOptions();
  }, [tab, loadItinerary, loadOptions]);

  async function save() {
    if (!cargo) return;
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const f of STR_FIELDS) payload[f] = draft[f] || null;
      for (const f of REF_FIELDS) payload[f] = draft[f] || null;
      for (const f of DATE_FIELDS) payload[f] = draft[f] || null;
      for (const f of DT_FIELDS) {
        const v = draft[f];
        // datetime-local 是 naive 值 —— 按 UTC 存（IMOS 的 GMT 口径）
        payload[f] = v ? (v.includes("Z") || v.includes("+") ? v : `${v}Z`) : null;
      }
      for (const f of NUM_FIELDS) payload[f] = draft[f] === "" ? null : Number(draft[f]);
      payload.laycan_confirmed = draft.laycan_confirmed === "1";
      const updated = await apiPatch(`/api/v1/cargo/${cargoId}`, payload);
      setCargo(updated);
      setDraft(toDraft(updated));
      toast.success(t("common.saved", "Saved"));
    } catch (ex) {
      toast.error(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setSaving(false);
    }
  }

  async function transitionTo(target: string) {
    try {
      const res = await apiPost(`/api/v1/cargo/${cargoId}/transition?target=${encodeURIComponent(target)}`);
      if (cargo) setCargo({ ...cargo, status: res.status });
      toast.success(t("page.cargo_detail.transitioned", "Status → {s}", { s: res.status }));
    } catch (ex) {
      toast.error(ex instanceof Error ? ex.message : String(ex));
    }
  }

  async function addItinRow() {
    setItinBusy(true);
    try {
      const port = ports.find((p) => p.id === itinForm.port_id);
      await apiPost(`/api/v1/cargo/${cargoId}/itinerary`, {
        seq: itinForm.seq === "" ? itinRows.length + 1 : Number(itinForm.seq),
        flag: itinForm.flag,
        port_id: itinForm.port_id || null,
        port_name: port ? port.name : null,
        berth: itinForm.berth || null,
        qty: itinForm.qty === "" ? null : Number(itinForm.qty),
        ld_rate: itinForm.ld_rate === "" ? null : Number(itinForm.ld_rate),
        ru: itinForm.ru || null,
        terms: itinForm.terms || null,
        incoterms: itinForm.incoterms || null,
        port_exp: itinForm.port_exp === "" ? null : Number(itinForm.port_exp),
        oexp_per_t: itinForm.oexp_per_t === "" ? null : Number(itinForm.oexp_per_t),
        liner_exp: itinForm.liner_exp === "" ? null : Number(itinForm.liner_exp),
        draft: itinForm.draft === "" ? null : Number(itinForm.draft),
        unit: itinForm.unit || null,
        salinity: itinForm.salinity === "" ? null : Number(itinForm.salinity),
      });
      setItinForm(EMPTY_ITIN);
      await loadItinerary();
    } catch (ex) {
      toast.error(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setItinBusy(false);
    }
  }

  async function delItinRow(rowId: string) {
    setItinBusy(true);
    try {
      await apiDelete(`/api/v1/cargo/${cargoId}/itinerary/${rowId}`);
      await loadItinerary();
    } catch (ex) {
      toast.error(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setItinBusy(false);
    }
  }

  async function addOptRow(kind: "load" | "disch") {
    setOptBusy(true);
    try {
      const f = optForms[kind];
      await apiPost(`/api/v1/cargo/${cargoId}/options`, {
        kind,
        seq: f.seq === "" ? optRows.filter((r) => r.kind === kind).length + 1 : Number(f.seq),
        port_area: f.port_area || null,
        ld_rate: f.ld_rate === "" ? null : Number(f.ld_rate),
        ru: f.ru || null,
        terms: f.terms || null,
        tt_days: f.tt_days === "" ? null : Number(f.tt_days),
        pexp: f.pexp === "" ? null : Number(f.pexp),
        draft: f.draft === "" ? null : Number(f.draft),
      });
      setOptForms((s) => ({ ...s, [kind]: EMPTY_OPT }));
      await loadOptions();
    } catch (ex) {
      toast.error(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setOptBusy(false);
    }
  }

  async function delOptRow(rowId: string) {
    setOptBusy(true);
    try {
      await apiDelete(`/api/v1/cargo/${cargoId}/options/${rowId}`);
      await loadOptions();
    } catch (ex) {
      toast.error(ex instanceof Error ? ex.message : String(ex));
    } finally {
      setOptBusy(false);
    }
  }

  const set = (k: string) => (v: string) => setDraft((d) => ({ ...d, [k]: v }));
  const val = (k: string) => draft[k] ?? "";
  const nameOf = (list: RefItem[], id: string) => list.find((x) => x.id === id)?.name || "";

  const itinColumns: ColumnDef<CargoItinRow>[] = useMemo(
    () => [
      { key: "seq", title: "#", width: 46, align: "right", value: (r) => r.seq },
      { key: "flag", title: t("page.cargo_detail.flag", "F"), width: 42, value: (r) => r.flag },
      { key: "port_name", title: t("page.cargo_detail.port", "Port"), minWidth: 130, value: (r) => r.port_name || "", render: (v) => (v ? String(v) : "—") },
      { key: "berth", title: t("page.cargo_detail.berth", "Berth"), width: 100, value: (r) => r.berth || "", render: (v) => (v ? String(v) : "—") },
      {
        key: "qty", title: t("page.cargo_detail.qty", "Qty"), width: 100, align: "right", agg: "sum",
        value: (r) => r.qty ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      {
        key: "ld_rate", title: t("page.cargo_detail.ld_rate", "L/D Rate"), width: 95, align: "right",
        value: (r) => r.ld_rate ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      { key: "ru", title: t("page.cargo_detail.ru", "RU"), width: 70, value: (r) => r.ru || "", render: (v) => (v ? String(v) : "—") },
      { key: "terms", title: t("page.fixtures.terms", "Terms"), width: 90, value: (r) => r.terms || "", render: (v) => (v ? String(v) : "—") },
      { key: "incoterms", title: t("page.cargo_detail.incoterms", "Incoterms"), width: 100, value: (r) => r.incoterms || "", render: (v) => (v ? String(v) : "—") },
      {
        key: "port_exp", title: t("page.fixtures.port_exp", "PortExp"), width: 100, align: "right", agg: "sum",
        value: (r) => r.port_exp ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      {
        key: "oexp_per_t", title: t("page.fixtures.oexp_per_t", "OExp/t"), width: 90, align: "right",
        value: (r) => r.oexp_per_t ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      {
        key: "liner_exp", title: t("page.fixtures.liner_exp", "LinerExp"), width: 100, align: "right", agg: "sum",
        value: (r) => r.liner_exp ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      {
        key: "draft", title: t("page.cargo_detail.draft", "Draft"), width: 80, align: "right",
        value: (r) => r.draft ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      { key: "unit", title: t("page.cargo_detail.unit", "Unit"), width: 70, value: (r) => r.unit || "", render: (v) => (v ? String(v) : "—") },
      {
        key: "salinity", title: t("page.cargo_detail.salinity", "Salinity"), width: 90, align: "right",
        value: (r) => r.salinity ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      {
        key: "actions", title: "", width: 72,
        render: (_v, r) => (
          <button type="button" className="btn btn-danger btn-sm" disabled={itinBusy} onClick={() => void delItinRow(r.id)}>
            {t("common.delete", "删除")}
          </button>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, itinBusy],
  );

  const optColumns: ColumnDef<CargoOptRow>[] = useMemo(
    () => [
      { key: "seq", title: "#", width: 46, align: "right", value: (r) => r.seq },
      { key: "port_area", title: t("page.cargo_detail.port_area", "Port / Area"), minWidth: 140, value: (r) => r.port_area || "", render: (v) => (v ? String(v) : "—") },
      {
        key: "ld_rate", title: t("page.cargo_detail.ld_rate", "L/D Rate"), width: 95, align: "right",
        value: (r) => r.ld_rate ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      { key: "ru", title: t("page.cargo_detail.ru", "RU"), width: 70, value: (r) => r.ru || "", render: (v) => (v ? String(v) : "—") },
      { key: "terms", title: t("page.fixtures.terms", "Terms"), width: 90, value: (r) => r.terms || "", render: (v) => (v ? String(v) : "—") },
      {
        key: "tt_days", title: t("page.cargo_detail.tt_days", "TT Days"), width: 90, align: "right",
        value: (r) => r.tt_days ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      {
        key: "pexp", title: t("page.cargo_detail.pexp", "PExp"), width: 95, align: "right", agg: "sum",
        value: (r) => r.pexp ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      {
        key: "draft", title: t("page.cargo_detail.draft", "Draft"), width: 80, align: "right",
        value: (r) => r.draft ?? null, render: (v) => (v == null ? "—" : <Num v={v as number} digits={2} />),
      },
      {
        key: "actions", title: "", width: 72,
        render: (_v, r) => (
          <button type="button" className="btn btn-danger btn-sm" disabled={optBusy} onClick={() => void delOptRow(r.id)}>
            {t("common.delete", "删除")}
          </button>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, optBusy],
  );

  const tabs: TabItem[] = useMemo(
    () => [
      { key: "terms", label: t("page.cargo_detail.tab_terms", "Terms") },
      { key: "itinerary", label: t("page.cargo_detail.tab_itinerary", "Itinerary"), badge: itinRows.length || undefined },
      { key: "options", label: t("page.cargo_detail.tab_options", "Options") },
    ],
    [t, itinRows.length],
  );

  if (loading) {
    return (
      <AppShell>
        <StateView loading error={""} empty={false} emptyText="" onRetry={() => void load()}>
          <span />
        </StateView>
      </AppShell>
    );
  }

  if (err || !cargo) {
    return (
      <AppShell>
        <StateView loading={false} error={err || t("common.not_found", "Not found")} empty={false} emptyText="" onRetry={() => void load()}>
          <span />
        </StateView>
        <Link href="/cargo" className="btn">
          {t("common.back", "返回")}
        </Link>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <DetailHeader
        breadcrumb={[
          { label: t("nav.cargo-book", "Cargo Book"), href: "/cargo" },
          { label: cargo.cargo_no },
        ]}
        title={cargo.cargo_no}
        status={cargo.status}
        subtitle={[
          cargo.commodity,
          cargo.qty != null ? `${cargo.qty.toLocaleString()} ${cargo.qty_unit || ""}` : null,
          cargo.cp_form,
          nameOf(parties, cargo.charterer_id || ""),
        ]
          .filter(Boolean)
          .join(" · ")}
        actions={[
          {
            key: "save",
            label: t("common.save", "Save"),
            variant: "primary",
            disabled: saving,
            onClick: () => void save(),
          },
          ...nextStatuses.map((s) => ({
            key: `go-${s}`,
            label: t(`page.cargo_detail.action.${s}`, s.replace(/_/g, " ")),
            variant: s === "cancelled" ? ("danger" as const) : ("default" as const),
            onClick: () => void transitionTo(s),
          })),
          ...(cargo.voyage_id
            ? [{
                key: "voyage",
                label: t("page.cargo_detail.open_voyage", "Open voyage"),
                onClick: () => router.push(`/operations/voyages/${cargo.voyage_id}/workspace`),
              }]
            : []),
          ...(cargo.charter_id
            ? [{
                key: "charter",
                label: t("page.cargo_detail.open_fixture", "Open fixture"),
                onClick: () => router.push(`/charters/${cargo.charter_id}`),
              }]
            : []),
        ]}
      />

      <Tabs items={tabs} value={tab} onChange={(k) => setTab(k as TabId)} variant="line" />

      {tab === "terms" ? (
        <FormPanel columns={3}>
          <FormSection title={t("page.cargo_detail.sec_cargo", "Cargo")} dense>
            <FieldRow label={t("page.cargo_detail.cargo_name", "Cargo name")}>
              <select value={val("cargo_name_id")} onChange={(e) => set("cargo_name_id")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                {cargoNames.map((n) => (
                  <option key={n.id} value={n.id}>{n.name}</option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.cargo.type", "Cargo type")}>
              <select value={val("cargo_type")} onChange={(e) => set("cargo_type")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                <option value="bulk">bulk</option>
                <option value="liquid">liquid</option>
                <option value="dry">dry</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.commodity", "Commodity")}>
              <input value={val("commodity")} onChange={(e) => set("commodity")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo.qty", "Qty")}>
              <input type="number" step="any" value={val("qty")} onChange={(e) => set("qty")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.qty_unit", "Unit")}>
              <input value={val("qty_unit")} onChange={(e) => set("qty_unit")(e.target.value)} placeholder="mt" />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.charterer", "Charterer")}>
              <select value={val("charterer_id")} onChange={(e) => set("charterer_id")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                {parties.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.cargo.load_port", "Load port")}>
              <select value={val("load_port_id")} onChange={(e) => set("load_port_id")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                {ports.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.cargo.disch_port", "Disch port")}>
              <select value={val("disch_port_id")} onChange={(e) => set("disch_port_id")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                {ports.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.api_gravity", "API gravity")}>
              <input type="number" step="any" value={val("api_gravity")} onChange={(e) => set("api_gravity")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.spec_gravity", "Spec. gravity")}>
              <input type="number" step="any" value={val("specific_gravity")} onChange={(e) => set("specific_gravity")(e.target.value)} />
            </FieldRow>
          </FormSection>

          <FormSection title={t("page.cargo_detail.sec_cp", "CP terms")} dense>
            <FieldRow label={t("page.cargo_detail.cp_date", "CP date")}>
              <DateInput value={val("cp_date")} onChange={set("cp_date")} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.cp_form", "CP form")}>
              <select value={val("cp_form")} onChange={(e) => set("cp_form")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                <option value="GENCON">GENCON</option>
                <option value="NYPE">NYPE</option>
                <option value="LINERTIME">LINERTIME</option>
                <option value="BOLEVOY">BOLEVOY</option>
                <option value="SAFECON">SAFECON</option>
                <option value="RECPC">RECPC</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.option_type", "Option type")}>
              <select value={val("option_type")} onChange={(e) => set("option_type")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                <option value="MOLOO">MOLOO</option>
                <option value="MINLO">MINLO</option>
                <option value="MOLOA">MOLOA</option>
                <option value="MINLOA">MINLOA</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.option_pct", "Option %")}>
              <input type="number" step="any" value={val("option_pct")} onChange={(e) => set("option_pct")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.min_qty", "Min qty")}>
              <input type="number" step="any" value={val("min_qty")} onChange={(e) => set("min_qty")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.max_qty", "Max qty")}>
              <input type="number" step="any" value={val("max_qty")} onChange={(e) => set("max_qty")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.freight_type", "Freight type")}>
              <select value={val("freight_type")} onChange={(e) => set("freight_type")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                <option value="F">F — Freight prepaid</option>
                <option value="L">L — Liner</option>
                <option value="LS">LS — Liner out</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.freight_basis", "Freight basis")}>
              <select value={val("freight_basis")} onChange={(e) => set("freight_basis")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                <option value="per_mt">per mt</option>
                <option value="lumpsum">lumpsum</option>
                <option value="worldscale">worldscale</option>
              </select>
            </FieldRow>
            <FieldRow label={t("page.estimates.freight_rate", "Freight rate")}>
              <input type="number" step="any" value={val("freight_rate")} onChange={(e) => set("freight_rate")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.tc.terms.currency", "Currency")}>
              <input value={val("currency")} onChange={(e) => set("currency")(e.target.value)} placeholder="USD" />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.exchange_rate", "Exch. rate")}>
              <input type="number" step="any" value={val("exchange_rate")} onChange={(e) => set("exchange_rate")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.min_inv_qty", "Min inv. qty")}>
              <input type="number" step="any" value={val("min_inv_qty")} onChange={(e) => set("min_inv_qty")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.cp_draft", "CP draft (m)")}>
              <input type="number" step="any" value={val("cp_draft_m")} onChange={(e) => set("cp_draft_m")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.freight_via", "Freight via")}>
              <input value={val("freight_via")} onChange={(e) => set("freight_via")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.demurrage_via", "Demurrage via")}>
              <input value={val("demurrage_via")} onChange={(e) => set("demurrage_via")(e.target.value)} />
            </FieldRow>
          </FormSection>

          <FormSection title={t("page.cargo_detail.sec_laycan", "Laycan")} dense>
            <FieldRow label={t("page.cargo_detail.laycan_from", "From (local)")}>
              <DateInput value={val("laycan_from")} onChange={set("laycan_from")} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.laycan_to", "To (local)")}>
              <DateInput value={val("laycan_to")} onChange={set("laycan_to")} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.laycan_from_ovr", "Override from")}>
              <DateTimeInput value={val("laycan_from_override")} onChange={set("laycan_from_override")} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.laycan_to_ovr", "Override to")}>
              <DateTimeInput value={val("laycan_to_override")} onChange={set("laycan_to_override")} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.laycan_confirmed", "Confirmed")}>
              <select value={val("laycan_confirmed")} onChange={(e) => set("laycan_confirmed")(e.target.value)}>
                <option value="0">{t("common.no", "No")}</option>
                <option value="1">{t("common.yes", "Yes")}</option>
              </select>
            </FieldRow>
          </FormSection>

          <FormSection title={t("page.cargo_detail.sec_payment", "Payment")} dense>
            <FieldRow label={t("page.cargo_detail.remittance_bank", "Remittance bank")}>
              <input value={val("remittance_bank")} onChange={(e) => set("remittance_bank")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.invoice_pct", "Invoice %")}>
              <input type="number" step="any" value={val("invoice_pct")} onChange={(e) => set("invoice_pct")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.balance_pct", "Balance %")}>
              <input type="number" step="any" value={val("balance_pct")} onChange={(e) => set("balance_pct")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.pay_terms_code", "Terms code")}>
              <input value={val("payment_terms_code")} onChange={(e) => set("payment_terms_code")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.pay_terms_desc", "Terms description")} span={3}>
              <input value={val("payment_terms_desc")} onChange={(e) => set("payment_terms_desc")(e.target.value)} />
            </FieldRow>
          </FormSection>

          <FormSection title={t("page.cargo_detail.sec_header", "Reference")} dense>
            <FieldRow label={t("page.cargo_detail.coordinator", "Coordinator")}>
              <input value={val("coordinator")} onChange={(e) => set("coordinator")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.reference_no", "Reference no.")}>
              <input value={val("reference_no")} onChange={(e) => set("reference_no")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.booking_no", "Booking no.")}>
              <input value={val("booking_no")} onChange={(e) => set("booking_no")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.vc_in_id", "VC In id")}>
              <input value={val("vc_in_id")} onChange={(e) => set("vc_in_id")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.nominated_vessel", "Nominated vessel")}>
              <select value={val("nominated_vessel_id")} onChange={(e) => set("nominated_vessel_id")(e.target.value)}>
                <option value="">{t("common.select", "Select…")}</option>
                {vessels.map((v) => (
                  <option key={v.id} value={v.id}>{v.name}</option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("page.fixtures.voyage_no", "Voyage No.")}>
              <input value={val("voyage_no")} onChange={(e) => set("voyage_no")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.contract_link", "Contract link")}>
              <input value={val("contract_link")} onChange={(e) => set("contract_link")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.tc.header.company_code", "Company")}>
              <input value={val("company_code")} onChange={(e) => set("company_code")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.department", "Department")}>
              <input value={val("department")} onChange={(e) => set("department")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.tc.header.trade_area", "Trade area")}>
              <input value={val("trade_area")} onChange={(e) => set("trade_area")(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("page.cargo_detail.notes", "Notes")} span={3}>
              <textarea rows={3} value={val("notes")} onChange={(e) => set("notes")(e.target.value)} />
            </FieldRow>
          </FormSection>
        </FormPanel>
      ) : null}

      {tab === "itinerary" ? (
        <>
          <DataGrid<CargoItinRow>
            columns={itinColumns}
            data={itinRows}
            rowKey={(r) => r.id}
            loading={itinBusy}
            showFooter
            storageKey="cargo_itinerary_grid"
            emptyText={t("page.cargo_detail.itin_empty", "No itinerary rows — add the first leg below.")}
          />
          <div className="desk-toolbar mt-sm">
            <input type="number" placeholder={t("page.fixtures.seq", "Seq")} value={itinForm.seq} onChange={(e) => setItinForm((f) => ({ ...f, seq: e.target.value }))} />
            <select aria-label={t("page.cargo_detail.flag", "F")} value={itinForm.flag} onChange={(e) => setItinForm((f) => ({ ...f, flag: e.target.value }))}>
              <option value="L">L — Load</option>
              <option value="D">D — Discharge</option>
            </select>
            <select aria-label={t("page.cargo_detail.port", "Port")} value={itinForm.port_id} onChange={(e) => setItinForm((f) => ({ ...f, port_id: e.target.value }))}>
              <option value="">{t("common.select", "Select…")}</option>
              {ports.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <input placeholder={t("page.cargo_detail.berth", "Berth")} value={itinForm.berth} onChange={(e) => setItinForm((f) => ({ ...f, berth: e.target.value }))} />
            <input type="number" step="any" placeholder={t("page.cargo_detail.qty", "Qty")} value={itinForm.qty} onChange={(e) => setItinForm((f) => ({ ...f, qty: e.target.value }))} />
            <input type="number" step="any" placeholder={t("page.cargo_detail.ld_rate", "L/D rate")} value={itinForm.ld_rate} onChange={(e) => setItinForm((f) => ({ ...f, ld_rate: e.target.value }))} />
            <input placeholder={t("page.fixtures.terms", "Terms")} value={itinForm.terms} onChange={(e) => setItinForm((f) => ({ ...f, terms: e.target.value }))} />
            <input placeholder={t("page.cargo_detail.incoterms", "Incoterms")} value={itinForm.incoterms} onChange={(e) => setItinForm((f) => ({ ...f, incoterms: e.target.value }))} />
            <input type="number" step="any" placeholder={t("page.cargo_detail.salinity", "Salinity")} value={itinForm.salinity} onChange={(e) => setItinForm((f) => ({ ...f, salinity: e.target.value }))} />
            <input type="number" step="any" placeholder={t("page.fixtures.port_exp", "PortExp")} value={itinForm.port_exp} onChange={(e) => setItinForm((f) => ({ ...f, port_exp: e.target.value }))} />
            <input type="number" step="any" placeholder={t("page.fixtures.liner_exp", "LinerExp")} value={itinForm.liner_exp} onChange={(e) => setItinForm((f) => ({ ...f, liner_exp: e.target.value }))} />
            <input placeholder={t("page.cargo_detail.unit", "Unit")} value={itinForm.unit} onChange={(e) => setItinForm((f) => ({ ...f, unit: e.target.value }))} />
            <button type="button" className="btn btn-primary" disabled={itinBusy} onClick={() => void addItinRow()}>
              {t("common.add", "Add")}
            </button>
          </div>
        </>
      ) : null}

      {tab === "options" ? (
        <>
          {(["load", "disch"] as const).map((kind) => (
            <section key={kind} className="panel mt-sm">
              <div className="desk-toolbar">
                <strong>
                  {kind === "load"
                    ? t("page.cargo_detail.load_options", "Load Options")
                    : t("page.cargo_detail.disch_options", "Discharge Options")}
                </strong>
                <span className="muted">
                  {t("page.cargo_detail.options_count", "{n} row(s)", { n: optRows.filter((r) => r.kind === kind).length })}
                </span>
              </div>
              <DataGrid<CargoOptRow>
                columns={optColumns}
                data={optRows.filter((r) => r.kind === kind)}
                rowKey={(r) => r.id}
                loading={optBusy}
                showFooter
                storageKey={`cargo_options_${kind}_grid`}
                emptyText={t("page.cargo_detail.opt_empty", "No options — add one below.")}
              />
              <div className="desk-toolbar mt-sm">
                <input
                  type="number"
                  placeholder={t("page.fixtures.seq", "Seq")}
                  value={optForms[kind].seq}
                  onChange={(e) => setOptForms((s) => ({ ...s, [kind]: { ...s[kind], seq: e.target.value } }))}
                />
                <input
                  placeholder={t("page.cargo_detail.port_area", "Port / Area")}
                  value={optForms[kind].port_area}
                  onChange={(e) => setOptForms((s) => ({ ...s, [kind]: { ...s[kind], port_area: e.target.value } }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.cargo_detail.ld_rate", "L/D rate")}
                  value={optForms[kind].ld_rate}
                  onChange={(e) => setOptForms((s) => ({ ...s, [kind]: { ...s[kind], ld_rate: e.target.value } }))}
                />
                <input
                  placeholder={t("page.fixtures.terms", "Terms")}
                  value={optForms[kind].terms}
                  onChange={(e) => setOptForms((s) => ({ ...s, [kind]: { ...s[kind], terms: e.target.value } }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.cargo_detail.tt_days", "TT days")}
                  value={optForms[kind].tt_days}
                  onChange={(e) => setOptForms((s) => ({ ...s, [kind]: { ...s[kind], tt_days: e.target.value } }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.cargo_detail.pexp", "PExp")}
                  value={optForms[kind].pexp}
                  onChange={(e) => setOptForms((s) => ({ ...s, [kind]: { ...s[kind], pexp: e.target.value } }))}
                />
                <input
                  type="number"
                  step="any"
                  placeholder={t("page.cargo_detail.draft", "Draft")}
                  value={optForms[kind].draft}
                  onChange={(e) => setOptForms((s) => ({ ...s, [kind]: { ...s[kind], draft: e.target.value } }))}
                />
                <button type="button" className="btn btn-primary" disabled={optBusy} onClick={() => void addOptRow(kind)}>
                  {t("common.add", "Add")}
                </button>
              </div>
            </section>
          ))}
        </>
      ) : null}
    </AppShell>
  );
}
