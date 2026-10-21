"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RowActions } from "@/components/RowActions";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type Holiday = {
  id: string;
  port_unlocode: string;
  country: string;
  holiday_date: string;
  holiday_name: string;
  holiday_type: string;
  recurring: boolean;
};

type PortRate = {
  id: string;
  port_unlocode: string;
  rate_type: string;
  vessel_size_band: string;
  amount_usd: number;
  currency: string;
  basis: string;
  source: string;
};

type Restriction = {
  port_unlocode: string;
  max_draft_m: number | null;
  max_loa_m: number | null;
  max_beam_m: number | null;
  max_dwt: number | null;
  working_hours: string | null;
  night_work_allowed: boolean;
  requires_pilot: boolean;
};

type Tab = "holidays" | "rates" | "restrictions";
const TAB_IDS: readonly string[] = ["holidays", "rates", "restrictions"];

function PortReferencePage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery } = useListQuery();
  const tab: Tab = TAB_IDS.includes(query.tab ?? "") ? (query.tab as Tab) : "holidays";
  const setTab = (k: Tab) => setQuery({ tab: k === "holidays" ? null : k }, { resetPage: true });
  const resPort = query.port ?? "";
  const setResPort = (v: string) => setQuery({ port: v || null }, { resetPage: true });

  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [rates, setRates] = useState<PortRate[]>([]);

  // Holiday form (RecordModal)
  const [holidayOpen, setHolidayOpen] = useState(false);
  const [holidayEditId, setHolidayEditId] = useState<string | null>(null);
  const [hPort, setHPort] = useState("");
  const [hCountry, setHCountry] = useState("CN");
  const [hDate, setHDate] = useState("");
  const [hName, setHName] = useState("");
  const [hType, setHType] = useState("public");
  const [hRecurring, setHRecurring] = useState(false);

  // Rate form (RecordModal)
  const [rateOpen, setRateOpen] = useState(false);
  const [rateEditId, setRateEditId] = useState<string | null>(null);
  const [rPort, setRPort] = useState("");
  const [rType, setRType] = useState("pilotage");
  const [rAmount, setRAmount] = useState("");
  const [rBand, setRBand] = useState("medium");
  const [rBasis, setRBasis] = useState("per_call");

  const [saving, setSaving] = useState(false);

  // Restriction lookup
  const [restriction, setRestriction] = useState<Restriction | null>(null);

  const holidayCtx = useContextMenu<Holiday>();
  const rateCtx = useContextMenu<PortRate>();

  async function loadHolidays() {
    setHolidays(await apiGet("/api/v1/reference/ports/holidays"));
  }

  async function loadRates() {
    if (resPort) {
      setRates(await apiGet(`/api/v1/reference/ports/rates?port_unlocode=${resPort}`));
    }
  }

  useEffect(() => {
    if (tab === "holidays") loadHolidays().catch(() => {});
  }, [tab]);

  useEffect(() => {
    if (tab === "rates" && resPort) loadRates().catch(() => setRates([]));
  }, [tab, resPort]);

  function openCreate() {
    if (tab === "rates") {
      setRateEditId(null);
      setRateOpen(true);
      setRPort("");
      setRType("pilotage");
      setRAmount("");
      setRBand("medium");
      setRBasis("per_call");
    } else {
      setHolidayEditId(null);
      setHolidayOpen(true);
      setHPort("");
      setHCountry("CN");
      setHDate("");
      setHName("");
      setHType("public");
      setHRecurring(false);
    }
  }

  function openEditHoliday(h: Holiday) {
    setHolidayEditId(h.id);
    setHPort(h.port_unlocode);
    setHCountry(h.country);
    setHDate(h.holiday_date);
    setHName(h.holiday_name);
    setHType(h.holiday_type);
    setHRecurring(h.recurring);
    setHolidayOpen(true);
  }

  function openEditRate(r: PortRate) {
    setRateEditId(r.id);
    setRPort(r.port_unlocode);
    setRType(r.rate_type);
    setRAmount(String(r.amount_usd));
    setRBand(r.vessel_size_band);
    setRBasis(r.basis);
    setRateOpen(true);
  }

  useListHotkeys(openCreate);

  async function saveHoliday(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        port_unlocode: hPort.toUpperCase(),
        country: hCountry.toUpperCase(),
        holiday_date: hDate,
        holiday_name: hName,
        holiday_type: hType,
        recurring: hRecurring,
      };
      if (holidayEditId) {
        await apiPatch(`/api/v1/reference/ports/holidays/${holidayEditId}`, body);
        toast.success(t("common.saved", "Saved"));
      } else {
        await apiPost("/api/v1/reference/ports/holidays", body);
        toast.success(t("page.portRef.holiday_added", "Holiday added"));
      }
      setHolidayOpen(false);
      await loadHolidays();
    } catch (ex: any) {
      toast.error(ex?.message || t("common.failed", "Failed"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteHoliday(id: string) {
    try {
      await apiDelete(`/api/v1/reference/ports/holidays/${id}`);
      toast.success(t("common.deleted", "Deleted"));
      if (holidayEditId === id) setHolidayOpen(false);
      await loadHolidays();
    } catch (ex: any) {
      toast.error(ex?.message || t("common.failed", "Failed"));
    }
  }

  async function saveRate(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const body = {
        port_unlocode: rPort.toUpperCase(),
        rate_type: rType,
        amount_usd: parseFloat(rAmount),
        vessel_size_band: rBand,
        basis: rBasis,
      };
      if (rateEditId) {
        await apiPatch(`/api/v1/reference/ports/rates/${rateEditId}`, body);
        toast.success(t("common.saved", "Saved"));
      } else {
        await apiPost("/api/v1/reference/ports/rates", body);
        toast.success(t("page.portRef.rate_added", "Rate added"));
      }
      setRateOpen(false);
      await loadRates();
    } catch (ex: any) {
      toast.error(ex?.message || t("common.failed", "Failed"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteRate(id: string) {
    try {
      await apiDelete(`/api/v1/reference/ports/rates/${id}`);
      toast.success(t("common.deleted", "Deleted"));
      if (rateEditId === id) setRateOpen(false);
      await loadRates();
    } catch (ex: any) {
      toast.error(ex?.message || t("common.failed", "Failed"));
    }
  }

  // ── 行内编辑（值未变化不发请求，避免 blur→reload 打断输入） ──
  async function onHolidayCellSave(rowId: string, colKey: string, value: unknown, row: Holiday) {
    const src = row as unknown as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "recurring") {
      const next = Boolean(value);
      if (row.recurring === next) return;
      payload = { recurring: next };
    } else if (colKey === "holiday_date") {
      const prev = row.holiday_date;
      const next = value ? String(value).slice(0, 10) : "";
      if (!next || prev === next) return;
      payload = { holiday_date: next };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    }
    try {
      await apiPatch(`/api/v1/reference/ports/holidays/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await loadHolidays();
    } catch (ex: any) {
      toast.error(ex?.message || t("common.failed", "Failed"));
    }
  }

  async function onRateCellSave(rowId: string, colKey: string, value: unknown, row: PortRate) {
    const src = row as unknown as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "amount_usd") {
      const next = value === null || value === "" ? null : Number(value);
      if (next === null || isNaN(next) || next === row.amount_usd) return;
      payload = { amount_usd: next };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    }
    try {
      await apiPatch(`/api/v1/reference/ports/rates/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await loadRates();
    } catch (ex: any) {
      toast.error(ex?.message || t("common.failed", "Failed"));
    }
  }

  async function lookupRestriction() {
    if (!resPort) return;
    const r = await apiGet(`/api/v1/reference/ports/${resPort.toUpperCase()}/restrictions`);
    setRestriction(r);
  }

  function validateHoliday(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    if (!hPort.trim() || hPort.trim().length !== 5)
      issues.push({ level: "error", message: t("page.portRef.err_hport", "Port UNLOCODE must be 5 characters") });
    if (!hDate.trim()) issues.push({ level: "error", message: t("page.portRef.err_hdate", "Holiday date is required") });
    if (!hName.trim()) issues.push({ level: "error", message: t("page.portRef.err_hname", "Holiday name is required") });
    return issues;
  }

  function validateRate(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    if (!rPort.trim() || rPort.trim().length !== 5)
      issues.push({ level: "error", message: t("page.portRef.err_rport", "Port UNLOCODE must be 5 characters") });
    const amt = parseFloat(rAmount);
    if (!Number.isFinite(amt)) issues.push({ level: "error", message: t("page.portRef.err_amount", "Amount must be a number") });
    else if (amt < 0) issues.push({ level: "error", message: t("page.portRef.err_amount_neg", "Amount must not be negative") });
    return issues;
  }

  function copyHolidayId(h: Holiday) {
    void navigator.clipboard.writeText(h.id);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  function exportHolidays(list: Holiday[]) {
    downloadCsv(
      "port_holidays",
      ["id", "port_unlocode", "country", "holiday_date", "holiday_name", "holiday_type", "recurring"],
      list.map((h) => [h.id, h.port_unlocode, h.country, h.holiday_date, h.holiday_name, h.holiday_type, h.recurring ? "Y" : "N"]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  function exportRates(list: PortRate[]) {
    downloadCsv(
      "port_rates",
      ["id", "port_unlocode", "rate_type", "vessel_size_band", "amount_usd", "currency", "basis"],
      list.map((r) => [r.id, r.port_unlocode, r.rate_type, r.vessel_size_band, r.amount_usd, r.currency, r.basis]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  const holidayMenuItems = (h: Holiday): ContextMenuItem[] => [
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyHolidayId(h) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportHolidays([h]) },
    {
      key: "export_all",
      label: t("ctx.export_all", "Export all"),
      onClick: () => exportHolidays(holidays),
    },
  ];

  const rateMenuItems = (r: PortRate): ContextMenuItem[] => [
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => { void navigator.clipboard.writeText(r.id); toast.success(t("ctx.copied_id", "ID copied")); } },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportRates([r]) },
    { key: "export_all", label: t("ctx.export_all", "Export all"), onClick: () => exportRates(rates) },
  ];

  const holidayColumns: ColumnDef<Holiday>[] = [
    {
      key: "port_unlocode",
      title: t("page.portRef.port", "Port"),
      width: 100,
      value: (h) => h.port_unlocode,
      render: (_v, h) => <code>{h.port_unlocode}</code>,
      editor: { type: "text" },
    },
    { key: "holiday_date", title: t("page.portRef.date", "Date"), width: 120, value: (h) => h.holiday_date, editor: { type: "date" } },
    { key: "holiday_name", title: t("page.portRef.name", "Name"), minWidth: 160, value: (h) => h.holiday_name, editor: { type: "text" } },
    {
      key: "holiday_type",
      title: t("page.portRef.holiday_type", "Type"),
      width: 110,
      value: (h) => h.holiday_type,
      editor: { type: "select", options: [
        { value: "public", label: t("page.portRef.public", "Public") },
        { value: "religious", label: t("page.portRef.religious", "Religious") },
        { value: "local", label: t("page.portRef.local", "Local") },
      ] },
    },
    {
      key: "recurring",
      title: t("page.portRef.recurring_short", "Rec."),
      width: 70,
      align: "center",
      value: (h) => h.recurring,
      render: (_v, h) => (h.recurring ? "✓" : ""),
      editor: { type: "checkbox" },
    },
    {
      key: "_actions",
      title: "",
      width: 64,
      align: "center",
      render: (_v, h) => (
        <RowActions
          onEdit={() => openEditHoliday(h)}
          onDelete={() => deleteHoliday(h.id)}
          label={`${h.port_unlocode} ${h.holiday_date}`}
        />
      ),
    },
  ];

  const rateColumns: ColumnDef<PortRate>[] = [
    {
      key: "rate_type",
      title: t("page.portRef.type", "Type"),
      width: 130,
      value: (r) => r.rate_type,
      editor: { type: "select", options: [
        { value: "pilotage", label: t("page.portRef.pilotage", "Pilotage") },
        { value: "towage", label: t("page.portRef.towage", "Towage") },
        { value: "mooring", label: t("page.portRef.mooring", "Mooring") },
        { value: "wharfage", label: t("page.portRef.wharfage", "Wharfage") },
        { value: "light_dues", label: t("page.portRef.light_dues", "Light Dues") },
      ] },
    },
    {
      key: "vessel_size_band",
      title: t("page.portRef.band", "Band"),
      width: 110,
      value: (r) => r.vessel_size_band,
      editor: { type: "select", options: [
        { value: "small", label: t("page.portRef.band_small", "Small (≤10k DWT)") },
        { value: "medium", label: t("page.portRef.band_medium", "Medium (10-50k DWT)") },
        { value: "large", label: t("page.portRef.band_large", "Large (50-150k DWT)") },
        { value: "xl", label: t("page.portRef.band_xl", "XL >150k DWT") },
      ] },
    },
    {
      key: "amount_usd",
      title: t("page.portRef.amount", "Amount"),
      width: 120,
      align: "right",
      value: (r) => r.amount_usd,
      render: (v) => (
        <>
          $
          <Num v={v as number} digits={2} />
        </>
      ),
      editor: { type: "number" },
    },
    {
      key: "basis",
      title: t("page.portRef.basis", "Basis"),
      width: 110,
      value: (r) => r.basis,
      editor: { type: "select", options: [
        { value: "per_call", label: t("page.portRef.per_call", "Per Call") },
        { value: "per_day", label: t("page.portRef.per_day", "Per Day") },
        { value: "per_gt", label: t("page.portRef.per_gt", "Per GT") },
        { value: "per_dwt", label: t("page.portRef.per_dwt", "Per DWT") },
      ] },
    },
    {
      key: "_actions",
      title: "",
      width: 64,
      align: "center",
      render: (_v, r) => (
        <RowActions
          onEdit={() => openEditRate(r)}
          onDelete={() => deleteRate(r.id)}
          label={`${r.port_unlocode} ${r.rate_type}`}
        />
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.master", "Master data") }]}
        title={t("page.portRef.title", "Port Reference Data")}
      />

      <Toolbar
        filterCount={(tab !== "holidays" ? 1 : 0) + (resPort ? 1 : 0)}
        onClearFilters={() => setQuery({ tab: null, port: null }, { resetPage: true })}
        right={
          <>
            <select
              className="input input-sm"
              value={tab}
              onChange={(e) => setTab(e.target.value as Tab)}
              aria-label={t("page.portRef.tab", "Section")}
            >
              <option value="holidays">{t("page.portRef.holidays", "Holidays")}</option>
              <option value="rates">{t("page.portRef.rates", "Port Rates")}</option>
              <option value="restrictions">{t("page.portRef.restrictions", "Restrictions")}</option>
            </select>
            <SavedViews storageKey="md_port_ref" onApply={(qs) => router.replace(`${pathname}${qs}`)} />
          </>
        }
      >
        {tab !== "restrictions" ? (
          <button type="button" className="btn btn-primary" onClick={openCreate}>
            {tab === "rates" ? t("page.portRef.add_rate", "Add Port Rate") : t("page.portRef.add_holiday", "Add Holiday")}
          </button>
        ) : null}
      </Toolbar>

      {tab === "holidays" ? (
        <div className="card">
          <h3 className="muted">
            {t("page.portRef.holiday_list", "Holiday List")} ({holidays.length})
          </h3>
          <DataGrid<Holiday>
            columns={holidayColumns}
            data={holidays}
            rowKey={(h) => h.id}
            editable
            onCellSave={onHolidayCellSave}
            onRowContextMenu={(h, _i, e) => holidayCtx.open(h)(e)}
            storageKey="port_ref_holidays_grid"
            showFooter={false}
            emptyText={t("common.empty", "No records")}
          />
          <ContextMenu controller={holidayCtx} items={holidayMenuItems} />
        </div>
      ) : null}

      {tab === "rates" ? (
        <div className="card">
          <div className="toolbar">
            <input
              placeholder={t("page.portRef.filter_port", "Port UNLOCODE to filter")}
              value={resPort}
              onChange={(e) => setResPort(e.target.value)}
              className="input input-sm"
            />
          </div>
          <DataGrid<PortRate>
            columns={rateColumns}
            data={rates}
            rowKey={(r) => r.id}
            editable
            onCellSave={onRateCellSave}
            onRowContextMenu={(r, _i, e) => rateCtx.open(r)(e)}
            storageKey="port_ref_rates_grid"
            showFooter={false}
            emptyText={t("common.empty", "No records")}
          />
          <ContextMenu controller={rateCtx} items={rateMenuItems} />
        </div>
      ) : null}

      {tab === "restrictions" ? (
        <div className="card">
          <div className="toolbar">
            <input
              placeholder={t("page.portRef.port_placeholder", "Port UNLOCODE (e.g. CNSHA)")}
              value={resPort}
              onChange={(e) => setResPort(e.target.value)}
              className="input input-sm"
            />
            <button className="btn btn-primary" onClick={lookupRestriction}>
              {t("common.lookup", "Lookup")}
            </button>
          </div>
          {restriction ? (
            <div className="form-grid">
              <div>
                <h4 className="muted">{t("page.portRef.size_limits", "Size Limits")}</h4>
                <div>
                  <span>{t("page.portRef.max_draft", "Max Draft")}: {restriction.max_draft_m ? <><Num v={restriction.max_draft_m} digits={2} />m</> : "—"}</span>
                  <br />
                  <span>{t("page.portRef.max_loa", "Max LOA")}: {restriction.max_loa_m ? <><Num v={restriction.max_loa_m} digits={2} />m</> : "—"}</span>
                  <br />
                  <span>{t("page.portRef.max_beam", "Max Beam")}: {restriction.max_beam_m ? <><Num v={restriction.max_beam_m} digits={2} />m</> : "—"}</span>
                  <br />
                  <span>{t("page.portRef.max_dwt", "Max DWT")}: {restriction.max_dwt ? <><Num v={restriction.max_dwt} digits={0} />t</> : "—"}</span>
                </div>
              </div>
              <div>
                <h4 className="muted">{t("page.portRef.operations", "Operations")}</h4>
                <div>
                  <span>{t("page.portRef.working_hours", "Working Hours")}: {restriction.working_hours || "—"}</span>
                  <br />
                  <span>{t("page.portRef.night_work", "Night Work")}: {restriction.night_work_allowed ? t("common.yes", "Yes") : t("common.no", "No")}</span>
                  <br />
                  <span>{t("page.portRef.pilot_required", "Pilot Required")}: {restriction.requires_pilot ? t("common.yes", "Yes") : t("common.no", "No")}</span>
                </div>
              </div>
            </div>
          ) : resPort ? (
            <p className="muted">{t("page.portRef.no_restrictions", "No restrictions found for {port}", { port: resPort.toUpperCase() })}</p>
          ) : null}
        </div>
      ) : null}

      <RecordModal
        open={holidayOpen}
        title={holidayEditId ? t("page.portRef.edit_holiday", "Edit Holiday") : t("page.portRef.add_holiday", "Add Holiday")}
        onClose={() => setHolidayOpen(false)}
        onSave={saveHoliday}
        canDelete={!!holidayEditId}
        onDelete={holidayEditId ? () => deleteHoliday(holidayEditId) : undefined}
        saving={saving}
      >
        <label>
          {t("page.portRef.port", "Port UNLOCODE")}
          <input value={hPort} onChange={(e) => setHPort(e.target.value)} required maxLength={5} />
        </label>
        <label>
          {t("page.portRef.country", "Country")}
          <input value={hCountry} onChange={(e) => setHCountry(e.target.value)} required maxLength={2} />
        </label>
        <label>
          {t("page.portRef.date", "Date")}
          <input type="date" value={hDate} onChange={(e) => setHDate(e.target.value)} required />
        </label>
        <label>
          {t("page.portRef.holiday_name", "Holiday name")}
          <input value={hName} onChange={(e) => setHName(e.target.value)} required />
        </label>
        <label>
          {t("page.portRef.holiday_type", "Type")}
          <select value={hType} onChange={(e) => setHType(e.target.value)}>
            <option value="public">{t("page.portRef.public", "Public")}</option>
            <option value="religious">{t("page.portRef.religious", "Religious")}</option>
            <option value="local">{t("page.portRef.local", "Local")}</option>
          </select>
        </label>
        <label>
          <input type="checkbox" checked={hRecurring} onChange={(e) => setHRecurring(e.target.checked)} />
          {t("page.portRef.recurring", "Recurring annually")}
        </label>
        <div className="record-modal-validate">
          <ValidateButton onValidate={validateHoliday} />
        </div>
      </RecordModal>

      <RecordModal
        open={rateOpen}
        title={rateEditId ? t("page.portRef.edit_rate", "Edit Port Rate") : t("page.portRef.add_rate", "Add Port Rate")}
        onClose={() => setRateOpen(false)}
        onSave={saveRate}
        canDelete={!!rateEditId}
        onDelete={rateEditId ? () => deleteRate(rateEditId) : undefined}
        saving={saving}
      >
        <label>
          {t("page.portRef.port", "Port UNLOCODE")}
          <input value={rPort} onChange={(e) => setRPort(e.target.value)} required maxLength={5} />
        </label>
        <label>
          {t("page.portRef.rate_type", "Rate type")}
          <select value={rType} onChange={(e) => setRType(e.target.value)}>
            <option value="pilotage">{t("page.portRef.pilotage", "Pilotage")}</option>
            <option value="towage">{t("page.portRef.towage", "Towage")}</option>
            <option value="mooring">{t("page.portRef.mooring", "Mooring")}</option>
            <option value="wharfage">{t("page.portRef.wharfage", "Wharfage")}</option>
            <option value="light_dues">{t("page.portRef.light_dues", "Light Dues")}</option>
          </select>
        </label>
        <label>
          {t("page.portRef.amount_usd", "Amount (USD)")}
          <input type="number" step="0.01" value={rAmount} onChange={(e) => setRAmount(e.target.value)} required />
        </label>
        <label>
          {t("page.portRef.band", "Size band")}
          <select value={rBand} onChange={(e) => setRBand(e.target.value)}>
            <option value="small">{t("page.portRef.band_small", "Small (≤10k DWT)")}</option>
            <option value="medium">{t("page.portRef.band_medium", "Medium (10-50k DWT)")}</option>
            <option value="large">{t("page.portRef.band_large", "Large (50-150k DWT)")}</option>
            <option value="xl">{t("page.portRef.band_xl", "XL >150k DWT")}</option>
          </select>
        </label>
        <label>
          {t("page.portRef.basis", "Basis")}
          <select value={rBasis} onChange={(e) => setRBasis(e.target.value)}>
            <option value="per_call">{t("page.portRef.per_call", "Per Call")}</option>
            <option value="per_day">{t("page.portRef.per_day", "Per Day")}</option>
            <option value="per_gt">{t("page.portRef.per_gt", "Per GT")}</option>
            <option value="per_dwt">{t("page.portRef.per_dwt", "Per DWT")}</option>
          </select>
        </label>
        <div className="record-modal-validate">
          <ValidateButton onValidate={validateRate} />
        </div>
      </RecordModal>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <PortReferencePage />
    </Suspense>
  );
}
