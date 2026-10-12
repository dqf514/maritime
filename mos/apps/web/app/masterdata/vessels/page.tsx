"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { ExportButton } from "@/components/ExportButton";
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

type Vessel = {
  id: string;
  name: string;
  imo: string | null;
  flag: string | null;
  vessel_type: string | null;
  status: string;
  updated_at?: string | null;
};

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
  const [edit, setEdit] = useState({ name: "", imo: "", flag: "", vessel_type: "", status: "active" });
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
    setEdit({ name: "", imo: "", flag: "", vessel_type: "", status: "active" });
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
    });
  }

  function payload() {
    return {
      name: edit.name,
      imo: edit.imo || null,
      flag: edit.flag || null,
      vessel_type: edit.vessel_type || null,
      status: edit.status,
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
          (r.flag || "").toLowerCase().includes(needle) ||
          (r.vessel_type || "").toLowerCase().includes(needle) ||
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
      key: "flag",
      title: t("page.vessels.flag", "Flag"),
      width: 120,
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
          {t("common.status", "Status")}
          <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
            <option value="active">active</option>
            <option value="laid_up">laid_up</option>
            <option value="sold">sold</option>
          </select>
        </label>
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
