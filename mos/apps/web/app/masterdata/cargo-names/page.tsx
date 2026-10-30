"use client";

// U-CARGONAMES 货物品名主数据（IMOS Data Center > Cargo Names 对齐）。
// Tabs: Names · Groups —— 名称列表点行进详情卡（含 Title/Value 属性子表）。

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { RefreshButton } from "@/components/RefreshButton";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { StateView } from "@/components/StateView";
import { Tabs } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiGet, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { useListQuery } from "@/lib/useListQuery";
import { formatDateTimeShort } from "@/lib/datetime";

type CargoName = {
  id: string;
  short_name: string;
  full_name: string | null;
  cargo_group_id: string | null;
  cargo_class: string | null;
  dangerous?: boolean;
  imdg_class?: string | null;
  default_cp_unit?: string | null;
  capacity_basis?: string | null;
  stow_factor_m3_mt?: number | string | null;
  inactive?: boolean;
  updated_at?: string | null;
};

type CargoGroup = { id: string; name: string; description?: string | null; created_at?: string | null };

const emptyName = {
  short_name: "",
  full_name: "",
  cargo_group_id: "",
  cargo_class: "",
  default_cp_unit: "",
  dangerous: false,
  inactive: false,
};

function CargoNamesPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery } = useListQuery();
  const tab = query.tab === "groups" ? "groups" : "names";
  const q = query.q ?? "";

  const [rows, setRows] = useState<CargoName[]>([]);
  const [groups, setGroups] = useState<CargoGroup[]>([]);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({ ...emptyName });
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");
  const [groupsErr, setGroupsErr] = useState("");

  async function load() {
    setLoading(true);
    const url = q ? `/api/v1/masterdata/cargo-names?q=${encodeURIComponent(q)}&limit=500` : "/api/v1/masterdata/cargo-names?limit=500";
    try {
      const d = await apiGet(url);
      setRows(Array.isArray(d) ? (d as CargoName[]) : []);
      setListErr("");
    } catch (ex) {
      // 列表取数失败必须走错误态，不能静默变成「No records」
      setRows([]);
      setListErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }

  async function loadGroups() {
    try {
      const d = await apiGet("/api/v1/masterdata/cargo-groups");
      setGroups(Array.isArray(d) ? (d as CargoGroup[]) : []);
      setGroupsErr("");
    } catch (ex) {
      // 参考数据失败：不让整页报错，但必须可见（分组列会空）
      setGroups([]);
      setGroupsErr(msgOf(ex));
    }
  }

  useEffect(() => {
    void load();
  }, [q]);

  useEffect(() => {
    void loadGroups();
  }, []);

  function openCreate() {
    setEdit({ ...emptyName });
    setCreating(true);
  }

  useListHotkeys(openCreate);

  async function save() {
    if (!edit.short_name.trim()) {
      toast.error(t("page.cargo.err_short", "Short name is required"));
      return;
    }
    setSaving(true);
    try {
      await apiPost("/api/v1/masterdata/cargo-names", {
        short_name: edit.short_name,
        full_name: edit.full_name || null,
        cargo_group_id: edit.cargo_group_id || null,
        cargo_class: edit.cargo_class || null,
        default_cp_unit: edit.default_cp_unit || null,
        dangerous: edit.dangerous,
        inactive: edit.inactive,
      });
      toast.success(t("page.cargo.created", "Cargo name created"));
      setCreating(false);
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setSaving(false);
    }
  }

  const groupId = useCallback(
    (id: string | null) => (id ? groups.find((g) => g.id === id)?.name ?? "" : ""),
    [groups],
  );

  const nameColumns = useMemo<ColumnDef<CargoName>[]>(() => [
    {
      key: "short_name",
      title: t("page.cargo.short_name", "Short name"),
      minWidth: 140,
      value: (r) => r.short_name,
      render: (_v, r) => (
        <Link href={`/masterdata/cargo-names/${r.id}`} onClick={(e) => e.stopPropagation()} className="row-link">
          {r.short_name}
        </Link>
      ),
    },
    { key: "full_name", title: t("page.cargo.full_name", "Full name"), minWidth: 180, value: (r) => r.full_name || "", render: (_v, r) => r.full_name || "—" },
    {
      key: "cargo_group_id",
      title: t("page.cargo.group", "Group"),
      width: 140,
      value: (r) => groupId(r.cargo_group_id),
      render: (_v, r) => groupId(r.cargo_group_id) || "—",
    },
    { key: "cargo_class", title: t("page.cargo.class", "Class"), width: 130, value: (r) => r.cargo_class || "", render: (_v, r) => r.cargo_class || "—" },
    {
      key: "dangerous",
      title: t("page.cargo.dangerous", "DG"),
      width: 80,
      value: (r) => Boolean(r.dangerous),
      render: (_v, r) =>
        r.dangerous ? <span className="pill danger">{r.imdg_class || t("page.cargo.dangerous", "DG")}</span> : "—",
    },
    { key: "default_cp_unit", title: t("page.cargo.unit", "Unit"), width: 90, value: (r) => r.default_cp_unit || "", render: (_v, r) => r.default_cp_unit || "—" },
    {
      key: "stow_factor_m3_mt",
      title: t("page.cargo.stow", "Stow (m3/MT)"),
      width: 125,
      align: "right",
      value: (r) => (r.stow_factor_m3_mt ?? null) as number | string | null,
      render: (_v, r) =>
        r.stow_factor_m3_mt === null || r.stow_factor_m3_mt === undefined || r.stow_factor_m3_mt === ""
          ? "—"
          : String(r.stow_factor_m3_mt),
    },
    {
      key: "inactive",
      title: t("common.status", "Status"),
      width: 105,
      value: (r) => Boolean(r.inactive),
      render: (_v, r) =>
        r.inactive ? (
          <span className="pill warn">{t("common.inactive", "Inactive")}</span>
        ) : (
          <span className="pill valid">{t("common.active", "Active")}</span>
        ),
    },
    {
      key: "updated_at",
      title: t("list.last_modified", "Last modified"),
      width: 135,
      value: (r) => r.updated_at ?? null,
      render: (v) => formatDateTimeShort(v as string | null),
    },
    {
      key: "actions",
      title: "",
      width: 90,
      align: "right",
      render: (_v, r) => (
        <Link href={`/masterdata/cargo-names/${r.id}`} className="btn btn-ghost btn-sm" onClick={(e) => e.stopPropagation()}>
          {t("common.open", "Open")}
        </Link>
      ),
    },
  ], [t, groupId]);

  const groupColumns = useMemo<ColumnDef<CargoGroup>[]>(() => [
    { key: "name", title: t("common.name", "Name"), minWidth: 160, value: (r) => r.name },
    { key: "description", title: t("common.notes", "Notes"), value: (r) => r.description || "", render: (_v, r) => r.description || "—" },
    {
      key: "created_at",
      title: t("list.last_modified", "Last modified"),
      width: 135,
      value: (r) => r.created_at ?? null,
      render: (v) => formatDateTimeShort(v as string | null),
    },
  ], [t]);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.master", "Master data") }]}
        title={t("page.cargo_names.title", "Cargo names")}
        subtitle={t("page.cargo_names.sub", "Cargo name master data — IMSBC / IMDG attributes and stowage factors.")}
        actions={
          <Link href="/settings/recycle" className="btn btn-ghost">
            {t("nav.recycle", "Recycle bin")}
          </Link>
        }
      />
      <Tabs
        items={[
          { key: "names", label: t("page.cargo.tab_names", "Cargo names") },
          { key: "groups", label: t("page.cargo.tab_groups", "Cargo groups") },
        ]}
        value={tab}
        onChange={(k) => setQuery({ tab: k === "groups" ? "groups" : null }, { resetPage: true })}
        variant="line"
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
              placeholder={t("page.cargo.search", "Search short / full name / product code…")}
              aria-label={t("common.search", "Search")}
            />
            <SavedViews storageKey="md_cargo_names" onApply={(qs) => router.replace(`${pathname}${qs}`)} />
          </>
        }
      >
        {tab === "names" ? (
          <button type="button" className="btn btn-primary" onClick={openCreate}>
            {t("page.cargo.add", "New cargo name")}
          </button>
        ) : null}
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => void (tab === "names" ? load() : loadGroups())} />
      </Toolbar>

      {groupsErr ? (
        <p className="flash-warn">
          {t("page.cargo_names.groups_load_failed", "Cargo groups could not be loaded — the group column may be empty.")} {groupsErr}
        </p>
      ) : null}

      {tab === "names" ? (
        <div className="panel">
          <StateView
            loading={loading}
            error={listErr || undefined}
            empty={!rows.length}
            emptyText={t("common.empty", "No records")}
            onRetry={() => void load()}
          >
            <DataGrid<CargoName>
              columns={nameColumns}
              data={rows}
              rowKey={(r) => r.id}
              onRowClick={(r) => router.push(`/masterdata/cargo-names/${r.id}`)}
              storageKey="masterdata_cargo_names_grid"
              emptyText={t("common.empty", "No records")}
            />
          </StateView>
          {/* P1-28：列表总数必须可见 */}
          {!listErr && rows.length ? (
            <p className="muted">{t("list.count_total", "{n} records", { n: rows.length })}</p>
          ) : null}
        </div>
      ) : (
        <div className="panel">
          <StateView
            loading={loading}
            error={groupsErr || undefined}
            empty={!groups.length}
            emptyText={t("common.empty", "No records")}
            onRetry={() => void loadGroups()}
          >
            <DataGrid<CargoGroup>
              columns={groupColumns}
              data={groups}
              rowKey={(r) => r.id}
              storageKey="masterdata_cargo_groups_grid"
              emptyText={t("common.empty", "No records")}
            />
          </StateView>
        </div>
      )}

      <RecordModal
        open={creating}
        title={t("page.cargo.add", "New cargo name")}
        onClose={() => setCreating(false)}
        onSave={save}
        saving={saving}
      >
        <label>
          {t("page.cargo.short_name", "Short name")}
          <input
            value={edit.short_name}
            onChange={(e) => setEdit({ ...edit, short_name: e.target.value })}
            required
            maxLength={64}
          />
        </label>
        <label>
          {t("page.cargo.full_name", "Full name")}
          <input value={edit.full_name} onChange={(e) => setEdit({ ...edit, full_name: e.target.value })} />
        </label>
        <label>
          {t("page.cargo.group", "Cargo group")}
          <select value={edit.cargo_group_id} onChange={(e) => setEdit({ ...edit, cargo_group_id: e.target.value })}>
            <option value="">{t("common.none", "None")}</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.cargo.class", "Class")}
          <input value={edit.cargo_class} onChange={(e) => setEdit({ ...edit, cargo_class: e.target.value })} />
        </label>
        <label>
          {t("page.cargo.unit", "Unit")}
          <input value={edit.default_cp_unit} onChange={(e) => setEdit({ ...edit, default_cp_unit: e.target.value })} />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={edit.dangerous}
            onChange={(e) => setEdit({ ...edit, dangerous: e.target.checked })}
          />
          {t("page.cargo.dangerous", "Dangerous")}
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={edit.inactive}
            onChange={(e) => setEdit({ ...edit, inactive: e.target.checked })}
          />
          {t("common.inactive", "Inactive")}
        </label>
      </RecordModal>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <CargoNamesPage />
    </Suspense>
  );
}
