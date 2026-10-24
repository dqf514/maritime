"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { RefreshButton } from "@/components/RefreshButton";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { LookupSelect } from "@/components/LookupSelect";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { StateView } from "@/components/StateView";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
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
  const { query, setQuery, page, limit } = useListQuery();
  const q = query.q ?? "";
  // 检索框本地草稿 + 防抖（服务端检索：每敲一个字发一次请求会把 API 打满）
  const [qDraft, setQDraft] = useState(q);
  useEffect(() => {
    setQDraft(q);
  }, [q]);
  useEffect(() => {
    if (qDraft === q) return;
    const timer = setTimeout(() => setQuery({ q: qDraft || null }, { resetPage: true }), 300);
    return () => clearTimeout(timer);
  }, [qDraft, q, setQuery]);
  const [rows, setRows] = useState<Port[]>([]);
  const [open, setOpen] = useState<Port | null>(null);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({ name: "", unlocode: "", country: "", timezone: "UTC", holidays: "", is_eu: false });
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");
  const [pendingDelete, setPendingDelete] = useState<{ run: () => void; name: string } | null>(null);
  // P1-28：服务端分页 —— 后端支持 limit/offset；多取一条用来判断"还有更多"
  const [hasMore, setHasMore] = useState(false);
  const rowCtx = useContextMenu<Port>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 服务端检索 + 服务端分页（limit+1 探测是否还有下一页）
      const offset = (page - 1) * limit;
      const qs = new URLSearchParams({ limit: String(limit + 1), offset: String(offset) });
      if (q.trim()) qs.set("q", q.trim());
      const data = await apiGet(`/api/v1/masterdata/ports?${qs.toString()}`);
      const arr = Array.isArray(data) ? (data as Port[]) : [];
      setHasMore(arr.length > limit);
      setRows(arr.slice(0, limit));
      setListErr("");
    } catch (ex) {
      // 列表取数失败必须走错误态，不能静默变成「No records」
      setRows([]);
      setHasMore(false);
      setListErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, [page, limit, q]);

  useEffect(() => {
    void load();
  }, [load]);

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
    } catch (ex) {
      // 写入失败必须报错（此前 try/catch 无消息体，失败被吞成一句通用文案）
      toast.error(msgOf(ex, creating ? t("page.ports.create_fail", "Create failed") : t("common.failed", "Failed")));
    } finally {
      setSaving(false);
    }
  }

  async function removePort(p: Port) {
    setSaving(true);
    try {
      await apiDelete(`/api/v1/masterdata/ports/${p.id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      closeModal();
      await load();
    } catch (ex) {
      // 删除失败必须报错（此前 try/finally 无 catch，失败被静默吞掉）
      toast.error(msgOf(ex));
    } finally {
      setSaving(false);
    }
  }

  /** 删除是不可逆动作 —— 走 ConfirmDialog，确认文案指名对象。 */
  function requestDeletePort(p: Port) {
    setPendingDelete({ run: () => void removePort(p), name: p.name });
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
    { key: "delete", label: t("common.delete", "Delete"), danger: true, onClick: () => requestDeletePort(r) },
  ];

  // 检索与分页都在服务端完成（后端 q 覆盖 name/unlocode/country/port_type/
  // region_code/parent_country）—— 这里不再做客户端过滤，否则只会过滤当前页。
  const filtered = rows;

  const dash = (v: string | null | undefined) => v || "—";

  const columns = useMemo<ColumnDef<Port>[]>(() => [
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
  ], [t]);

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
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
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
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => void load()} />
      </Toolbar>
      <div className="panel">
        <StateView
          loading={loading}
          error={listErr || undefined}
          empty={!filtered.length}
          emptyText={t("common.empty", "No records")}
          onRetry={() => void load()}
        >
          <DataGrid<Port>
            columns={columns}
            data={filtered}
            rowKey={(r) => r.id}
            onRowClick={(r) => router.push(`/masterdata/ports/${r.id}`)}
            onRowContextMenu={(r, _i, e) => rowCtx.open(r)(e)}
            storageKey="masterdata_ports_grid"
            emptyText={t("common.empty", "No records")}
          />
        </StateView>
        {/* P1-28：分页 —— 截断必须对用户可见，且能翻到下一页 */}
        {!listErr && filtered.length ? (
          <p className="muted">
            {t("list.count_total", "{n} records", { n: filtered.length })}
            {hasMore ? t("page.ports.more", " (more available — use the pager below)") : ""}
          </p>
        ) : null}
        {!listErr && filtered.length ? (
          <div className="dt-pagination">
            <span className="dt-page-info">
              {t("page.ports.page_of", "Page {page}", { page })}
            </span>
            <span className="dt-page-btns">
              <button
                type="button"
                onClick={() => setQuery({ page: page > 2 ? page - 1 : null })}
                disabled={page <= 1}
                aria-label="prev"
              >
                ‹
              </button>
              <button
                type="button"
                onClick={() => setQuery({ page: page + 1 })}
                disabled={!hasMore}
                aria-label="next"
              >
                ›
              </button>
            </span>
          </div>
        ) : null}
        <ContextMenu controller={rowCtx} items={menuItems} />
      </div>

      <RecordModal
        open={creating || Boolean(open)}
        title={creating ? t("page.ports.add", "New port") : t("page.ports.edit", "Edit port")}
        onClose={closeModal}
        onSave={save}
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

        {/* P1-8：删除港口是不可逆动作 —— 走指名对象的二次确认（RecordModal 内置文案无法指名对象）。 */}
        {open ? (
          <div className="desk-toolbar">
            <button
              type="button"
              className="btn btn-danger btn-sm"
              disabled={saving}
              onClick={() => requestDeletePort(open)}
            >
              {t("common.delete", "Delete")}
            </button>
          </div>
        ) : null}
      </RecordModal>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={t("common.confirm", "Confirm")}
        message={t("common.confirm_delete_named", 'Delete "{name}"?', { name: pendingDelete?.name ?? "" })}
        danger
        confirmLabel={t("common.delete", "Delete")}
        onConfirm={() => {
          const fn = pendingDelete;
          setPendingDelete(null);
          fn?.run();
        }}
        onCancel={() => setPendingDelete(null)}
      />
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
