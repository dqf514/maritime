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
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { apiGet, apiPost } from "@/lib/api";
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
  const [hPort, setHPort] = useState("");
  const [hCountry, setHCountry] = useState("CN");
  const [hDate, setHDate] = useState("");
  const [hName, setHName] = useState("");
  const [hType, setHType] = useState("public");
  const [hRecurring, setHRecurring] = useState(false);

  // Rate form (RecordModal)
  const [rateOpen, setRateOpen] = useState(false);
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
      setRateOpen(true);
      setRPort("");
      setRAmount("");
    } else {
      setHolidayOpen(true);
      setHPort("");
      setHDate("");
      setHName("");
    }
  }

  useListHotkeys(openCreate);

  async function addHoliday(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await apiPost("/api/v1/reference/ports/holidays", {
        port_unlocode: hPort.toUpperCase(),
        country: hCountry.toUpperCase(),
        holiday_date: hDate,
        holiday_name: hName,
        holiday_type: hType,
        recurring: hRecurring,
      });
      toast.success(t("page.portRef.holiday_added", "Holiday added"));
      setHolidayOpen(false);
      await loadHolidays();
    } catch {
      toast.error(t("common.failed", "Failed"));
    } finally {
      setSaving(false);
    }
  }

  async function addRate(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await apiPost("/api/v1/reference/ports/rates", {
        port_unlocode: rPort.toUpperCase(),
        rate_type: rType,
        amount_usd: parseFloat(rAmount),
        vessel_size_band: rBand,
        basis: rBasis,
      });
      toast.success(t("page.portRef.rate_added", "Rate added"));
      setRateOpen(false);
      await loadRates();
    } catch {
      toast.error(t("common.failed", "Failed"));
    } finally {
      setSaving(false);
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
    },
    { key: "holiday_date", title: t("page.portRef.date", "Date"), width: 120, value: (h) => h.holiday_date },
    { key: "holiday_name", title: t("page.portRef.name", "Name"), minWidth: 160, value: (h) => h.holiday_name },
    { key: "holiday_type", title: t("page.portRef.holiday_type", "Type"), width: 110, value: (h) => h.holiday_type },
    {
      key: "recurring",
      title: t("page.portRef.recurring_short", "Rec."),
      width: 70,
      align: "center",
      value: (h) => h.recurring,
      render: (_v, h) => (h.recurring ? "✓" : ""),
    },
  ];

  const rateColumns: ColumnDef<PortRate>[] = [
    { key: "rate_type", title: t("page.portRef.type", "Type"), width: 130, value: (r) => r.rate_type },
    { key: "vessel_size_band", title: t("page.portRef.band", "Band"), width: 110, value: (r) => r.vessel_size_band },
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
    },
    { key: "basis", title: t("page.portRef.basis", "Basis"), width: 110, value: (r) => r.basis },
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
        title={t("page.portRef.add_holiday", "Add Holiday")}
        onClose={() => setHolidayOpen(false)}
        onSave={addHoliday}
        canDelete={false}
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
        title={t("page.portRef.add_rate", "Add Port Rate")}
        onClose={() => setRateOpen(false)}
        onSave={addRate}
        canDelete={false}
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
