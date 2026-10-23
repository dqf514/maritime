"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { ExportButton } from "@/components/ExportButton";
import { FormSection } from "@/components/form/FormPanel";
import { LookupSelect } from "@/components/LookupSelect";
import { PageGuide } from "@/components/PageGuide";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { useListQuery } from "@/lib/useListQuery";
import { CLASS_SOCIETIES, FLEET_GROUPS, OWNERSHIP_OPTIONS, TRADE_AREAS } from "@/lib/vessel-catalog";

type Vessel = {
  id: string;
  name: string;
  imo: string | null;
  flag: string | null;
  vessel_type: string | null;
  status: string;
  fleet_group?: string;
  updated_at?: string | null;
  // IMOS 对齐字段（migration 26c3fccfee50）
  vessel_code?: string | null;
  ownership?: string | null;
  trade_area?: string | null;
  class_society?: string | null;
  dwt?: number | string | null;
  speed_laden?: number | string | null;
  speed_ballast?: number | string | null;
  tpc?: number | string | null;
  daily_cost?: number | string | null;
};

const emptyVessel = {
  name: "", imo: "", flag: "", vessel_type: "", status: "active", fleet_group: "mother_vessel",
  vessel_code: "", ownership: "", trade_area: "", class_society: "",
  dwt: "", speed_laden: "", speed_ballast: "", tpc: "", daily_cost: "",
};

// 表单值（字符串）↔ API 值（数字/null）互转：空串一律归 null，避免写成 0。
function numIn(v: string): number | null {
  return v === "" || v === null || v === undefined ? null : Number(v);
}
function numOut(v: number | string | null | undefined): string {
  return v === null || v === undefined || v === "" ? "" : String(v);
}

function VesselsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery } = useListQuery();
  const q = query.q ?? "";
  const [rows, setRows] = useState<Vessel[]>([]);
  const [open, setOpen] = useState<Vessel | null>(null);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({ ...emptyVessel });
  const [saving, setSaving] = useState(false);

  async function load() {
    setRows(await apiGet("/api/v1/masterdata/vessels"));
  }

  useEffect(() => {
    load().catch(() => setRows([]));
  }, []);

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setEdit({ ...emptyVessel });
  }

  useListHotkeys(openCreate);

  function closeModal() {
    setOpen(null);
    setCreating(false);
  }

  function openRow(r: Vessel) {
    setCreating(false);
    setOpen(r);
    setEdit({
      name: r.name,
      imo: r.imo || "",
      flag: r.flag || "",
      vessel_type: r.vessel_type || "",
      status: r.status || "active",
      fleet_group: r.fleet_group || "mother_vessel",
      vessel_code: r.vessel_code || "",
      ownership: r.ownership || "",
      trade_area: r.trade_area || "",
      class_society: r.class_society || "",
      dwt: numOut(r.dwt),
      speed_laden: numOut(r.speed_laden),
      speed_ballast: numOut(r.speed_ballast),
      tpc: numOut(r.tpc),
      daily_cost: numOut(r.daily_cost),
    });
  }

  function payload() {
    return {
      name: edit.name,
      imo: edit.imo || null,
      flag: edit.flag || null,
      vessel_type: edit.vessel_type || null,
      status: edit.status,
      fleet_group: edit.fleet_group || "mother_vessel",
      vessel_code: edit.vessel_code || null,
      ownership: edit.ownership || null,
      trade_area: edit.trade_area || null,
      class_society: edit.class_society || null,
      dwt: numIn(edit.dwt),
      speed_laden: numIn(edit.speed_laden),
      speed_ballast: numIn(edit.speed_ballast),
      tpc: numIn(edit.tpc),
      daily_cost: numIn(edit.daily_cost),
    };
  }

  async function save() {
    setSaving(true);
    try {
      if (creating || !open) {
        await apiPost("/api/v1/masterdata/vessels", payload());
        toast.success(t("page.vessels.created", "Vessel created"));
      } else {
        await apiPatch(`/api/v1/masterdata/vessels/${open.id}`, payload());
        toast.success(t("common.saved", "Saved"));
      }
      closeModal();
      await load();
    } catch {
      toast.error(creating ? t("page.vessels.create_fail", "Create failed") : t("common.failed", "Failed"));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/masterdata/vessels/${open.id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      closeModal();
      await load();
    } finally {
      setSaving(false);
    }
  }

  const filtered = q
    ? rows.filter((r) => {
        const needle = q.toLowerCase();
        return (
          r.name.toLowerCase().includes(needle) ||
          (r.imo || "").toLowerCase().includes(needle) ||
          (r.vessel_code || "").toLowerCase().includes(needle) ||
          (r.flag || "").toLowerCase().includes(needle) ||
          (r.vessel_type || "").toLowerCase().includes(needle) ||
          (r.class_society || "").toLowerCase().includes(needle) ||
          (r.trade_area || "").toLowerCase().includes(needle) ||
          (r.ownership || "").toLowerCase().includes(needle) ||
          (r.fleet_group || "").toLowerCase().includes(needle) ||
          (r.status || "").toLowerCase().includes(needle)
        );
      })
    : rows;

  const columns: ColumnDef<Vessel>[] = [
    {
      key: "name",
      title: t("common.name", "Name"),
      minWidth: 150,
      value: (r) => r.name,
      // A5：列表行链接到船舶卡片 /ship/vessels/[id]（list masterdata / detail shipyard）
      render: (_v, r) => (
        <Link
          href={`/ship/vessels/${r.id}`}
          onClick={(e) => e.stopPropagation()}
          style={{ color: "inherit", textDecoration: "none" }}
        >
          {r.name}
        </Link>
      ),
    },
    {
      key: "vessel_code",
      title: t("page.vessels.vessel_code", "Code"),
      width: 96,
      value: (r) => r.vessel_code || "",
      render: (_v, r) => r.vessel_code || "—",
    },
    {
      key: "imo",
      title: t("page.vessels.imo", "IMO"),
      width: 110,
      value: (r) => r.imo || "",
      render: (_v, r) => r.imo || "—",
    },
    {
      key: "vessel_type",
      title: t("common.type", "Type"),
      width: 130,
      value: (r) => r.vessel_type || "",
      render: (_v, r) => r.vessel_type || "—",
    },
    {
      key: "dwt",
      title: t("page.vessels.dwt", "DWT (MT)"),
      width: 110,
      align: "right",
      value: (r) => (r.dwt ?? null) as number | string | null,
      render: (_v, r) => (r.dwt === null || r.dwt === undefined || r.dwt === "" ? "—" : String(r.dwt)),
    },
    {
      key: "speed_laden",
      title: t("page.vessels.speed_laden", "Speed laden (kn)"),
      width: 120,
      align: "right",
      value: (r) => (r.speed_laden ?? null) as number | string | null,
      render: (_v, r) => (r.speed_laden === null || r.speed_laden === undefined || r.speed_laden === "" ? "—" : String(r.speed_laden)),
    },
    {
      key: "speed_ballast",
      title: t("page.vessels.speed_ballast", "Speed ballast (kn)"),
      width: 125,
      align: "right",
      value: (r) => (r.speed_ballast ?? null) as number | string | null,
      render: (_v, r) => (r.speed_ballast === null || r.speed_ballast === undefined || r.speed_ballast === "" ? "—" : String(r.speed_ballast)),
    },
    {
      key: "tpc",
      title: t("page.vessels.tpc", "TPC"),
      width: 90,
      align: "right",
      value: (r) => (r.tpc ?? null) as number | string | null,
      render: (_v, r) => (r.tpc === null || r.tpc === undefined || r.tpc === "" ? "—" : String(r.tpc)),
    },
    {
      key: "class_society",
      title: t("page.vessels.class_society", "Class society"),
      width: 130,
      value: (r) => r.class_society || "",
      render: (_v, r) => r.class_society || "—",
    },
    {
      key: "trade_area",
      title: t("page.vessels.trade_area", "Trade area"),
      width: 120,
      value: (r) => r.trade_area || "",
      render: (_v, r) => r.trade_area || "—",
    },
    {
      key: "ownership",
      title: t("page.vessels.ownership", "Ownership"),
      width: 120,
      value: (r) => r.ownership || "",
      render: (_v, r) =>
        r.ownership ? t(`page.vessels.ownership.${r.ownership}`, r.ownership) : "—",
    },
    {
      key: "fleet_group",
      title: t("page.vessels.fleet_group", "Fleet group"),
      width: 140,
      value: (r) => r.fleet_group || "mother_vessel",
      render: (_v, r) => t(`page.vessels.group.${r.fleet_group || "mother_vessel"}`, r.fleet_group || "mother_vessel"),
    },
    {
      key: "flag",
      title: t("page.vessels.flag", "Flag"),
      width: 110,
      value: (r) => r.flag || "",
      render: (_v, r) => r.flag || "—",
    },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "updated_at",
      title: t("list.last_modified", "Last modified"),
      width: 135,
      value: (r) => r.updated_at ?? null,
      render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
    },
    {
      key: "actions",
      title: "",
      width: 90,
      align: "right",
      render: (_v, r) => (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={(e) => {
            e.stopPropagation();
            openRow(r);
          }}
        >
          {t("common.edit", "Edit")}
        </button>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.master", "Master data") }]}
        title={t("page.vessels.title", "Vessels")}
        subtitle={t("page.vessels.sub", "Fleet master data. Click a row to open the vessel card.")}
        actions={
          <>
            <ExportButton entity="vessels" />
            <PageGuide pageKey="masterdata_vessels" />
            <Link href="/settings/recycle" className="btn btn-ghost">
              {t("nav.recycle", "Recycle bin")}
            </Link>
          </>
        }
      />
      <Toolbar
        filterCount={q ? 1 : 0}
        onClearFilters={() => setQuery({ q: null }, { resetPage: true })}
        right={
          <>
            <input
              className="input input-sm"
              type="search"
              value={q}
              onChange={(e) => setQuery({ q: e.target.value || null }, { resetPage: true })}
              placeholder={t("page.vessels.search", "Search name / IMO / flag / type…")}
              aria-label={t("common.search", "Search")}
            />
            <SavedViews storageKey="md_vessels" onApply={(qs) => router.replace(`${pathname}${qs}`)} />
          </>
        }
      >
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.vessels.add", "New vessel")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>
      <div className="panel">
        <DataGrid<Vessel>
          columns={columns}
          data={filtered}
          rowKey={(r) => r.id}
          onRowClick={(r) => router.push(`/ship/vessels/${r.id}`)}
          storageKey="masterdata_vessels_grid"
          emptyText={t("common.empty", "No records")}
        />
      </div>

      <RecordModal
        open={creating || Boolean(open)}
        title={creating ? t("page.vessels.add", "New vessel") : t("page.vessels.edit", "Edit vessel")}
        onClose={closeModal}
        onSave={save}
        onDelete={creating ? undefined : remove}
        canDelete={!creating}
        saving={saving}
      >
        <label>
          {t("common.name", "Name")}
          <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
        </label>
        <label>
          {t("page.vessels.imo", "IMO")}
          <input value={edit.imo} onChange={(e) => setEdit({ ...edit, imo: e.target.value })} />
        </label>
        <label>
          {t("common.type", "Type")}
          <LookupSelect
            dataset="vessel_types"
            value={edit.vessel_type}
            onChange={(v) => setEdit({ ...edit, vessel_type: v })}
          />
        </label>
        <label>
          {t("page.vessels.flag", "Flag")}
          <LookupSelect dataset="countries" value={edit.flag} onChange={(v) => setEdit({ ...edit, flag: v })} />
        </label>
        <label>
          {t("page.vessels.fleet_group", "Fleet group")}
          <select
            value={edit.fleet_group}
            onChange={(e) => setEdit({ ...edit, fleet_group: e.target.value })}
          >
            {FLEET_GROUPS.map((g) => (
              <option key={g} value={g}>
                {t(`page.vessels.group.${g}`, g)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("common.status", "Status")}
          <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
            <option value="active">active</option>
            <option value="laid_up">laid_up</option>
            <option value="sold">sold</option>
          </select>
        </label>

        <FormSection title={t("page.vessels.section_commercial", "IMOS · commercial identity")}>
          <label>
            {t("page.vessels.vessel_code", "Code")}
            <input
              value={edit.vessel_code}
              onChange={(e) => setEdit({ ...edit, vessel_code: e.target.value })}
              maxLength={12}
              placeholder={t("page.vessels.vessel_code_ph", "e.g. ACKATH")}
            />
          </label>
          <label>
            {t("page.vessels.ownership", "Ownership")}
            <select value={edit.ownership} onChange={(e) => setEdit({ ...edit, ownership: e.target.value })}>
              {OWNERSHIP_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o === "" ? t("common.none", "None") : t(`page.vessels.ownership.${o}`, o)}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.vessels.trade_area", "Trade area")}
            <input
              list="vessel-trade-areas"
              value={edit.trade_area}
              onChange={(e) => setEdit({ ...edit, trade_area: e.target.value })}
              placeholder={t("page.vessels.trade_area_ph", "e.g. ASIA / EURO")}
            />
            <datalist id="vessel-trade-areas">
              {TRADE_AREAS.map((a) => (
                <option key={a} value={a} />
              ))}
            </datalist>
          </label>
          <label>
            {t("page.vessels.class_society", "Class society")}
            <input
              list="vessel-class-societies"
              value={edit.class_society}
              onChange={(e) => setEdit({ ...edit, class_society: e.target.value })}
              placeholder="ABS"
            />
            <datalist id="vessel-class-societies">
              {CLASS_SOCIETIES.map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </label>
          <label>
            {t("page.vessels.dwt", "DWT (MT)")}
            <input type="number" value={edit.dwt} onChange={(e) => setEdit({ ...edit, dwt: e.target.value })} />
          </label>
          <label>
            {t("page.vessels.speed_laden", "Speed laden (kn)")}
            <input type="number" step="0.01" value={edit.speed_laden} onChange={(e) => setEdit({ ...edit, speed_laden: e.target.value })} />
          </label>
          <label>
            {t("page.vessels.speed_ballast", "Speed ballast (kn)")}
            <input type="number" step="0.01" value={edit.speed_ballast} onChange={(e) => setEdit({ ...edit, speed_ballast: e.target.value })} />
          </label>
          <label>
            {t("page.vessels.tpc", "TPC")}
            <input type="number" step="0.01" value={edit.tpc} onChange={(e) => setEdit({ ...edit, tpc: e.target.value })} />
          </label>
          <label>
            {t("page.vessels.daily_cost", "Daily cost (USD)")}
            <input type="number" step="0.01" value={edit.daily_cost} onChange={(e) => setEdit({ ...edit, daily_cost: e.target.value })} />
          </label>
        </FormSection>
      </RecordModal>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <VesselsPage />
    </Suspense>
  );
}
