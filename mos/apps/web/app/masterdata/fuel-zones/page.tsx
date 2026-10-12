"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { StatusBadge } from "@/components/StatusBadge";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { apiGet, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type FuelZone = {
  id: string;
  zone_name: string;
  zone_type: string;
  is_active: boolean;
  fuel_requirements: Record<string, unknown> | null;
  eu_ets_factor: number | null;
  fueleu_limit: number | null;
};

type PositionResult = {
  lat: number;
  lon: number;
  zones: { id: string; zone_name: string; zone_type: string; fuel_requirements: Record<string, unknown> | null }[];
};

function FuelZonesPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [zones, setZones] = useState<FuelZone[]>([]);

  // Position lookup
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [posResult, setPosResult] = useState<PositionResult | null>(null);

  // Compliance check
  const [cLat, setCLat] = useState("");
  const [cLon, setCLon] = useState("");
  const [cFuel, setCFuel] = useState("HFO");
  const [cSulfur, setCSulfur] = useState("");
  const [complianceResult, setComplianceResult] = useState<Record<string, unknown> | null>(null);

  // Create zone (RecordModal)
  const [creating, setCreating] = useState(false);
  const [zName, setZName] = useState("");
  const [zType, setZType] = useState("eca");
  const [zSulfur, setZSulfur] = useState("");
  const [saving, setSaving] = useState(false);
  const zoneCtx = useContextMenu<FuelZone>();

  async function load() {
    setZones(await apiGet("/api/v1/reference/fuel-zones"));
  }

  useEffect(() => {
    load().catch(() => setZones([]));
  }, []);

  async function lookupPosition() {
    const res = await apiGet(`/api/v1/reference/fuel-zones/position?lat=${lat}&lon=${lon}`);
    setPosResult(res);
  }

  async function checkCompliance() {
    const sulfurParam = cSulfur ? `&sulfur_pct=${cSulfur}` : "";
    const res = await apiGet(`/api/v1/reference/fuel-zones/compliance?lat=${cLat}&lon=${cLon}&fuel_type=${cFuel}${sulfurParam}`);
    setComplianceResult(res);
  }

  function openCreate() {
    setCreating(true);
    setZName("");
    setZType("eca");
    setZSulfur("");
  }

  useListHotkeys(openCreate);

  function closeCreate() {
    setCreating(false);
  }

  async function createZone(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const fuelReqs = zSulfur ? { sulfur_max: parseFloat(zSulfur), fuel_type: "MGO" } : null;
      await apiPost("/api/v1/reference/fuel-zones", {
        zone_name: zName,
        zone_type: zType,
        fuel_requirements: fuelReqs,
      });
      toast.success(t("page.fuelZones.zone_created", "Zone created"));
      closeCreate();
      await load();
    } catch {
      toast.error(t("common.failed", "Failed"));
    } finally {
      setSaving(false);
    }
  }

  async function seedPresets() {
    await apiPost("/api/v1/reference/fuel-zones/seed-presets", {});
    toast.success(t("page.fuelZones.presets_seeded", "Preset zones seeded"));
    await load();
  }

  function validateZone(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    if (!zName.trim()) issues.push({ level: "error", message: t("page.fuelZones.err_name", "Zone name is required") });
    if (zSulfur) {
      const s = parseFloat(zSulfur);
      if (!Number.isFinite(s) || s < 0 || s > 10)
        issues.push({ level: "error", message: t("page.fuelZones.err_sulfur", "Sulfur % must be between 0 and 10") });
    } else {
      issues.push({ level: "warn", message: t("page.fuelZones.warn_sulfur", "No sulfur limit set") });
    }
    return issues;
  }

  function copyZoneId(z: FuelZone) {
    void navigator.clipboard.writeText(z.id);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  function exportZones(list: FuelZone[]) {
    downloadCsv(
      "fuel_zones",
      ["id", "zone_name", "zone_type", "is_active", "sulfur_max", "eu_ets_factor", "fueleu_limit"],
      list.map((z) => [
        z.id,
        z.zone_name,
        z.zone_type,
        z.is_active ? "Y" : "N",
        (z.fuel_requirements as Record<string, number> | null)?.sulfur_max ?? "",
        z.eu_ets_factor ?? "",
        z.fueleu_limit ?? "",
      ]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  const zoneMenuItems = (z: FuelZone): ContextMenuItem[] => [
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyZoneId(z) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportZones([z]) },
  ];

  const zoneTypeColor = (z: string) => {
    if (z === "eca") return "var(--blue-700)";
    if (z === "eu_ets") return "var(--purple-700)";
    if (z === "fueleu") return "var(--amber-700)";
    return "var(--text-secondary)";
  };

  const columns: ColumnDef<FuelZone>[] = [
    { key: "zone_name", title: t("page.fuelZones.name", "Name"), minWidth: 160, value: (z) => z.zone_name },
    {
      key: "zone_type",
      title: t("page.fuelZones.type", "Type"),
      width: 110,
      value: (z) => z.zone_type,
      render: (_v, z) => (
        <span style={{ color: zoneTypeColor(z.zone_type), fontWeight: 500, fontSize: 12 }}>
          {z.zone_type.toUpperCase()}
        </span>
      ),
    },
    {
      key: "sulfur",
      title: t("page.fuelZones.sulfur_limit", "Sulfur Limit"),
      width: 120,
      align: "right",
      value: (z) => (z.fuel_requirements as Record<string, number> | null)?.sulfur_max ?? null,
      render: (_v, z) =>
        z.fuel_requirements ? (
          <>
            <Num v={(z.fuel_requirements as Record<string, number>).sulfur_max ?? null} digits={2} />%
          </>
        ) : (
          "—"
        ),
    },
    {
      key: "is_active",
      title: t("page.fuelZones.active", "Active"),
      width: 100,
      value: (z) => (z.is_active ? "active" : "inactive"),
      render: (_v, z) => <StatusBadge status={z.is_active ? "active" : "inactive"} />,
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.master", "Master data") }]}
        title={t("page.fuelZones.title", "Fuel Zone Management")}
      />

      <Toolbar
        right={
          <button type="button" className="btn btn-secondary" onClick={seedPresets}>
            {t("page.fuelZones.seed_presets", "Seed Preset Zones")}
          </button>
        }
      >
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.fuelZones.create_zone", "Create Zone")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>

      <div className="form-grid">
        <div className="card">
          <h3 className="muted">{t("page.fuelZones.position_lookup", "Position Lookup")}</h3>
          <div className="toolbar">
            <input placeholder={t("page.fuelZones.lat", "Latitude")} value={lat} onChange={(e) => setLat(e.target.value)} className="input input-sm" />
            <input placeholder={t("page.fuelZones.lon", "Longitude")} value={lon} onChange={(e) => setLon(e.target.value)} className="input input-sm" />
            <button className="btn btn-primary" onClick={lookupPosition}>
              {t("common.lookup", "Lookup")}
            </button>
          </div>
          {posResult && (
            <div>
              <p className="muted">
                {t("page.fuelZones.position_result", "Position ({lat}, {lon}) — {n} zone(s)", {
                  lat: posResult.lat,
                  lon: posResult.lon,
                  n: posResult.zones.length,
                })}
              </p>
              {posResult.zones.map((z) => (
                <div key={z.id} className="row-line">
                  <span>{z.zone_name}</span>
                  <span style={{ marginLeft: 8, fontSize: 12, color: zoneTypeColor(z.zone_type) }}>
                    {z.zone_type.toUpperCase()}
                  </span>
                  {z.fuel_requirements ? (
                    <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>
                      {t("page.fuelZones.sulfur_le", "S≤{pct}%", {
                        pct: (z.fuel_requirements as Record<string, number>).sulfur_max ?? "?",
                      })}
                    </span>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h3 className="muted">{t("page.fuelZones.compliance_check", "Fuel Compliance Check")}</h3>
          <div className="form-grid">
            <input placeholder={t("page.fuelZones.lat", "Latitude")} value={cLat} onChange={(e) => setCLat(e.target.value)} className="input input-sm" />
            <input placeholder={t("page.fuelZones.lon", "Longitude")} value={cLon} onChange={(e) => setCLon(e.target.value)} className="input input-sm" />
            <select value={cFuel} onChange={(e) => setCFuel(e.target.value)} className="input input-sm">
              <option value="HFO">HFO</option>
              <option value="MGO">MGO</option>
              <option value="MDO">MDO</option>
              <option value="LNG">LNG</option>
            </select>
            <input placeholder={t("page.fuelZones.sulfur_pct", "Sulfur %")} type="number" step="0.01" value={cSulfur} onChange={(e) => setCSulfur(e.target.value)} className="input input-sm" />
          </div>
          <button className="btn btn-primary" onClick={checkCompliance}>
            {t("page.fuelZones.check", "Check Compliance")}
          </button>
          {complianceResult ? (
            <div>
              <div
                className={complianceResult.compliant ? "badge" : "badge"}
                style={{
                  padding: "8px 12px",
                  background: (complianceResult as Record<string, boolean>).compliant ? "var(--green-50)" : "var(--red-50)",
                  color: (complianceResult as Record<string, boolean>).compliant ? "var(--green-700)" : "var(--red-700)",
                }}
              >
                {(complianceResult as Record<string, boolean>).compliant
                  ? t("page.fuelZones.compliant", "COMPLIANT")
                  : t("page.fuelZones.non_compliant", "NON-COMPLIANT")}
              </div>
              {(((complianceResult as Record<string, unknown>).violations as unknown[]) || []).length > 0 ? (
                <ul className="muted">
                  {((complianceResult as Record<string, unknown>).violations as string[]).map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <div className="card">
        <h3 className="muted">
          {t("page.fuelZones.zone_list", "Zone List")} ({zones.length})
        </h3>
        <StatusLegend statuses={["active", "inactive"]} />
        {zones.length === 0 ? (
          <div className="muted" style={{ textAlign: "center", padding: 24 }}>
            {t("page.fuelZones.no_zones", "No fuel zones defined. Seed presets to get started.")}
          </div>
        ) : (
          <DataGrid<FuelZone>
            columns={columns}
            data={zones}
            rowKey={(z) => z.id}
            onRowContextMenu={(z, _i, e) => zoneCtx.open(z)(e)}
            storageKey="fuel_zones_grid"
            showFooter={false}
            emptyText={t("page.fuelZones.no_zones", "No fuel zones defined. Seed presets to get started.")}
          />
        )}
        <ContextMenu controller={zoneCtx} items={zoneMenuItems} />
      </div>

      <RecordModal
        open={creating}
        title={t("page.fuelZones.create_zone", "Create Zone")}
        onClose={closeCreate}
        onSave={createZone}
        canDelete={false}
        saving={saving}
      >
        <label>
          {t("page.fuelZones.name", "Name")}
          <input value={zName} onChange={(e) => setZName(e.target.value)} required />
        </label>
        <label>
          {t("page.fuelZones.type", "Type")}
          <select value={zType} onChange={(e) => setZType(e.target.value)}>
            <option value="eca">{t("page.fuelZones.type_eca", "ECA")}</option>
            <option value="eu_ets">{t("page.fuelZones.type_eu_ets", "EU ETS")}</option>
            <option value="fueleu">{t("page.fuelZones.type_fueleu", "FuelEU")}</option>
            <option value="cii">{t("page.fuelZones.type_cii", "CII")}</option>
            <option value="non_eca">{t("page.fuelZones.type_non_eca", "Non-ECA")}</option>
          </select>
        </label>
        <label>
          {t("page.fuelZones.sulfur_limit", "Max sulfur %")}
          <input type="number" step="0.01" value={zSulfur} onChange={(e) => setZSulfur(e.target.value)} />
        </label>
        <div className="record-modal-validate">
          <ValidateButton onValidate={validateZone} />
        </div>
      </RecordModal>
    </AppShell>
  );
}

export default function Page() {
  return <FuelZonesPage />;
}
