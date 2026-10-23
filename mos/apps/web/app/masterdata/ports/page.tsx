"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { LookupSelect } from "@/components/LookupSelect";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { useListQuery } from "@/lib/useListQuery";

type Port = {
  id: string;
  name: string;
  unlocode: string | null;
  country: string | null;
  timezone: string;
  holidays?: string[] | null;
  is_eu?: boolean;
  // IMOS 对齐字段（PortIn 全量序列化）
  port_type?: string | null;
  region_code?: string | null;
  loadline_zone?: string | null;
  std_gmt_offset?: number | string | null;
  dst_gmt_offset?: number | string | null;
  fuel_zone_default?: string | null;
  bunkering_port?: boolean;
  lightering_port?: boolean;
  inactive?: boolean;
  latitude?: number | string | null;
  longitude?: number | string | null;
};

function parseHolidays(v: string): string[] {
  return v
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function PortsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery } = useListQuery();
  const q = query.q ?? "";
  const [rows, setRows] = useState<Port[]>([]);
  const [open, setOpen] = useState<Port | null>(null);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({ name: "", unlocode: "", country: "", timezone: "UTC", holidays: "", is_eu: false });
  const [saving, setSaving] = useState(false);
  const rowCtx = useContextMenu<Port>();

  async function load() {
    setRows(await apiGet("/api/v1/masterdata/ports"));
  }

  useEffect(() => {
    load().catch(() => setRows([]));
  }, []);

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setEdit({
      name: "",
      unlocode: "",
      country: "CN",
      timezone: "Asia/Shanghai",
      holidays: "",
      is_eu: false,
    });
  }

  useListHotkeys(openCreate);

  function closeModal() {
    setOpen(null);
    setCreating(false);
  }

  function openRow(r: Port) {
    setCreating(false);
    setOpen(r);
    setEdit({
      name: r.name,
      unlocode: r.unlocode || "",
      country: r.country || "",
      timezone: r.timezone || "UTC",
      holidays: (r.holidays || []).join(", "),
      is_eu: Boolean(r.is_eu),
    });
  }

  function payload() {
    return {
      name: edit.name,
      unlocode: edit.unlocode || null,
      country: edit.country || null,
      timezone: edit.timezone || "UTC",
      holidays: parseHolidays(edit.holidays),
      is_eu: edit.is_eu,
    };
  }

  async function save() {
    setSaving(true);
    try {
      if (creating || !open) {
        await apiPost("/api/v1/masterdata/ports", payload());
        toast.success(t("page.ports.created", "Port created"));
      } else {
        await apiPatch(`/api/v1/masterdata/ports/${open.id}`, payload());
        toast.success(t("common.saved", "Saved"));
      }
      closeModal();
      await load();
    } catch {
      toast.error(creating ? t("page.ports.create_fail", "Create failed") : t("common.failed", "Failed"));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!open) return;
    await removePort(open);
  }

  async function removePort(p: Port) {
    setSaving(true);
    try {
      await apiDelete(`/api/v1/masterdata/ports/${p.id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      closeModal();
      await load();
    } finally {
      setSaving(false);
    }
  }

  function validateEdit(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    if (!edit.name.trim()) issues.push({ level: "error", message: t("page.ports.err_name", "Name is required") });
    if (edit.unlocode && edit.unlocode.trim().length !== 5)
      issues.push({ level: "warn", message: t("page.ports.warn_unlocode", "UN/LOCODE is usually 5 characters") });
    if (!edit.country.trim()) issues.push({ level: "warn", message: t("page.ports.warn_country", "Country is empty") });
    if (!edit.timezone.trim()) issues.push({ level: "error", message: t("page.ports.err_tz", "Time zone is required") });
    return issues;
  }

  function copyId(id: string) {
    void navigator.clipboard.writeText(id);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  function exportPorts(list: Port[]) {
    downloadCsv(
      "ports",
      ["id", "name", "unlocode", "country", "timezone", "is_eu"],
      list.map((r) => [r.id, r.name, r.unlocode ?? "", r.country ?? "", r.timezone, r.is_eu ? "Y" : "N"]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  const menuItems = (r: Port): ContextMenuItem[] => [
    { key: "open", label: t("ctx.open", "Open"), onClick: () => router.push(`/masterdata/ports/${r.id}`) },
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyId(r.id) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportPorts([r]) },
    { key: "d1", label: "", divider: true },
    { key: "delete", label: t("common.delete", "Delete"), danger: true, onClick: () => void removePort(r) },
  ];

  const filtered = q
    ? rows.filter((r) => {
        const needle = q.toLowerCase();
        return (
          r.name.toLowerCase().includes(needle) ||
          (r.unlocode || "").toLowerCase().includes(needle) ||
          (r.country || "").toLowerCase().includes(needle) ||
          (r.port_type || "").toLowerCase().includes(needle) ||
          (r.region_code || "").toLowerCase().includes(needle) ||
          (r.loadline_zone || "").toLowerCase().includes(needle) ||
          (r.fuel_zone_default || "").toLowerCase().includes(needle)
        );
      })
    : rows;

  const dash = (v: string | null | undefined) => v || "—";

  const columns: ColumnDef<Port>[] = [
    {
      key: "name",
      title: t("common.name", "Name"),
      minWidth: 150,
      value: (r) => r.name,
      // A5：列表行链接到港口卡片（list masterdata / detail 同域）
      render: (_v, r) => (
        <Link href={`/masterdata/ports/${r.id}`} onClick={(e) => e.stopPropagation()} className="row-link">
          {r.name}
        </Link>
      ),
    },
    {
      key: "unlocode",
      title: t("page.ports.unlocode", "UN/LOCODE"),
      width: 120,
      value: (r) => r.unlocode || "",
      render: (_v, r) => dash(r.unlocode),
    },
    {
      key: "country",
      title: t("page.ports.country", "Country"),
      width: 100,
      value: (r) => r.country || "",
      render: (_v, r) => dash(r.country),
    },
    {
      key: "port_type",
      title: t("page.ports.port_type", "Port type"),
      width: 130,
      value: (r) => r.port_type || "",
      render: (_v, r) => (r.port_type ? t(`page.port.type_${r.port_type}`, r.port_type) : "—"),
    },
    {
      key: "region_code",
      title: t("page.ports.region", "Region"),
      width: 110,
      value: (r) => r.region_code || "",
      render: (_v, r) => dash(r.region_code),
    },
    {
      key: "loadline_zone",
      title: t("page.ports.loadline", "Loadline"),
      width: 120,
      value: (r) => r.loadline_zone || "",
      render: (_v, r) => dash(r.loadline_zone),
    },
    { key: "timezone", title: t("page.ports.timezone", "Time zone"), width: 135, value: (r) => r.timezone },
    {
      key: "std_gmt_offset",
      title: t("page.ports.std_gmt", "STD GMT +/−"),
      width: 110,
      align: "right",
      value: (r) => (r.std_gmt_offset ?? null) as number | string | null,
      render: (_v, r) => (r.std_gmt_offset === null || r.std_gmt_offset === undefined || r.std_gmt_offset === "" ? "—" : String(r.std_gmt_offset)),
    },
    {
      key: "dst_gmt_offset",
      title: t("page.ports.dst_gmt", "DST GMT +/−"),
      width: 110,
      align: "right",
      value: (r) => (r.dst_gmt_offset ?? null) as number | string | null,
      render: (_v, r) => (r.dst_gmt_offset === null || r.dst_gmt_offset === undefined || r.dst_gmt_offset === "" ? "—" : String(r.dst_gmt_offset)),
    },
    {
      key: "fuel_zone_default",
      title: t("page.ports.fuel_zone", "Fuel zone"),
      width: 120,
      value: (r) => r.fuel_zone_default || "",
      render: (_v, r) => dash(r.fuel_zone_default),
    },
    {
      key: "flags",
      title: t("page.ports.flags", "Flags"),
      width: 170,
      value: (r) => (r.is_eu ? "EU" : ""),
      render: (_v, r) => (
        <>
          {r.is_eu ? <span className="badge badge-pass">{t("page.ports.eu", "EU")}</span> : null}{" "}
          {r.bunkering_port ? <span className="badge">{t("page.ports.bunkering", "Bunker")}</span> : null}{" "}
          {r.lightering_port ? <span className="badge">{t("page.ports.lightering", "LTG")}</span> : null}
        </>
      ),
    },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 110,
      value: (r) => (r.inactive ? "inactive" : "active"),
      render: (_v, r) =>
        r.inactive ? (
          <span className="badge badge-warn">{t("common.inactive", "Inactive")}</span>
        ) : (
          <span className="badge badge-pass">{t("common.active", "Active")}</span>
        ),
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
        title={t("page.ports.title", "Ports")}
        subtitle={t("page.ports.sub", "Port master data (UN/LOCODE). Click a row to open the port card.")}
        actions={
          <Link href="/settings/recycle" className="btn btn-ghost">
            {t("nav.recycle", "Recycle bin")}
          </Link>
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
              placeholder={t("page.ports.search", "Search name / UN/LOCODE / country…")}
              aria-label={t("common.search", "Search")}
            />
            <SavedViews storageKey="md_ports" onApply={(qs) => router.replace(`${pathname}${qs}`)} />
          </>
        }
      >
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.ports.add", "New port")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>
      <div className="panel">
        <DataGrid<Port>
          columns={columns}
          data={filtered}
          rowKey={(r) => r.id}
          onRowClick={(r) => router.push(`/masterdata/ports/${r.id}`)}
          onRowContextMenu={(r, _i, e) => rowCtx.open(r)(e)}
          storageKey="masterdata_ports_grid"
          emptyText={t("common.empty", "No records")}
        />
        <ContextMenu controller={rowCtx} items={menuItems} />
      </div>

      <RecordModal
        open={creating || Boolean(open)}
        title={creating ? t("page.ports.add", "New port") : t("page.ports.edit", "Edit port")}
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
          {t("page.ports.unlocode", "UN/LOCODE")}
          <input value={edit.unlocode} onChange={(e) => setEdit({ ...edit, unlocode: e.target.value })} />
        </label>
        <label>
          {t("page.ports.country", "Country")}
          <LookupSelect dataset="countries" value={edit.country} onChange={(v) => setEdit({ ...edit, country: v })} />
        </label>
        <label>
          {t("page.ports.timezone", "Time zone")}
          <LookupSelect
            dataset="timezones"
            value={edit.timezone}
            onChange={(v) => setEdit({ ...edit, timezone: v })}
            allowEmpty={false}
          />
        </label>
        <label>
          {t("page.ports.holidays", "Holidays")}
          <input
            value={edit.holidays}
            onChange={(e) => setEdit({ ...edit, holidays: e.target.value })}
            placeholder={t("page.ports.holidays_ph", "YYYY-MM-DD, YYYY-MM-DD")}
          />
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <input type="checkbox" checked={edit.is_eu} onChange={(e) => setEdit({ ...edit, is_eu: e.target.checked })} />
          {t("page.ports.is_eu", "EU/EEA port")}
        </label>
        <div className="record-modal-validate">
          <ValidateButton onValidate={validateEdit} />
        </div>
      </RecordModal>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <PortsPage />
    </Suspense>
  );
}
