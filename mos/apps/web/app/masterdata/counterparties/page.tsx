"use client";

// 对手方与联系人（数据闭环重做）：
// - Tabs：公司 / 联系人 两个视角，联系人不再藏在公司弹窗里
// - 显著搜索框（服务端 q：名称/公司/邮箱/职务/部门）
// - 联系人目录跨公司可见；新建联系人用 PartyPicker 选公司
// - 公司详情弹窗保留联系人区块（按公司上下文管理）

import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { RefreshButton } from "@/components/RefreshButton";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { LookupSelect, useLookupItems } from "@/components/LookupSelect";
import { PartyPicker } from "@/components/DataPicker";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { StateView } from "@/components/StateView";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { useToast } from "@/components/ToastProvider";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type Party = {
  id: string;
  name: string;
  type: string;
  country: string | null;
  sanctions_status: string;
  // IMOS 对齐字段（CounterpartyIn 全量序列化）
  short_name?: string | null;
  company_no?: string | null;
  ref_no?: string | null;
  main_contact?: string | null;
  status?: string | null;
  credit_term?: number | string | null;
  address_types?: string[] | null;
  address: string | null;
  tax_id: string | null;
  swift_code: string | null;
  registration_no: string | null;
  website: string | null;
  phone: string | null;
  email: string | null;
  notes: string | null;
  updated_at?: string | null;
};

type Contact = {
  id: string;
  counterparty_id: string;
  counterparty_name?: string;
  name: string;
  title: string | null;
  email: string | null;
  phone: string | null;
  mobile: string | null;
  department: string | null;
  is_primary: boolean;
  notes: string | null;
};

const emptyEdit = {
  name: "", types: ["charterer"] as string[], country: "", sanctions_status: "clear",
  address: "", tax_id: "", swift_code: "", registration_no: "",
  website: "", phone: "", email: "", notes: "",
};

const emptyContact = {
  name: "", title: "", email: "", phone: "", mobile: "", department: "", is_primary: false, notes: "",
};

type Tab = "parties" | "contacts";

/** 「代码 — 标签」选项文案（与 LookupSelect 展示口径一致） */
function showCodeLabel(it: { code: string; label: string }): string {
  return `${it.code} — ${it.label}`;
}

function CounterpartiesPage() {
  const { t } = useI18n();
  // 类型多选项清单（与 LookupSelect 共用参照表缓存）
  const { items: typeItems, error: typeErr } = useLookupItems("counterparty_types");
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery, page, limit } = useListQuery();
  const tab: Tab = query.tab === "contacts" ? "contacts" : "parties";
  const urlQ = query.q ?? "";
  const [search, setSearch] = useState(urlQ);
  const [rows, setRows] = useState<Party[]>([]);
  const [open, setOpen] = useState<Party | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [edit, setEdit] = useState({ ...emptyEdit });
  const [saving, setSaving] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [allContacts, setAllContacts] = useState<Contact[]>([]);
  const [contactOpen, setContactOpen] = useState(false);
  const [contactEdit, setContactEdit] = useState({ ...emptyContact });
  const [editingContact, setEditingContact] = useState<Contact | null>(null);
  const [contactParty, setContactParty] = useState(""); // 联系人表单所属公司（跨公司新建用）
  // 列表取数状态（失败必须走 StateView 错误态，不得静默变空列表）
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");
  const [contactsErr, setContactsErr] = useState("");
  // 分页（服务端 limit/offset）—— 截断必须对用户可见
  const [hasMore, setHasMore] = useState(false);
  // 破坏性操作二次确认：pending 存待执行函数 + 被指名的对象
  const [pendingDelete, setPendingDelete] = useState<{ run: () => void; name: string } | null>(null);

  const partyCtx = useContextMenu<Party>();
  const contactCtx = useContextMenu<Contact>();

  // URL → input sync（后退 / SavedViews 应用）
  useEffect(() => {
    setSearch(urlQ);
  }, [urlQ]);

  // input → URL（防抖，避免每次键入都 replace）
  useEffect(() => {
    if (search === urlQ) return;
    const timer = setTimeout(() => setQuery({ q: search || null }, { resetPage: true }), 300);
    return () => clearTimeout(timer);
  }, [search, urlQ, setQuery]);

  // 公司列表（服务端搜索 + 分页；多取一条用于探测「还有更多」）
  const load = useCallback(async (q: string) => {
    setLoading(true);
    try {
      const offset = (page - 1) * limit;
      const res = await apiGet(
        `/api/v1/masterdata/counterparties?q=${encodeURIComponent(q)}&limit=${limit + 1}&offset=${offset}`,
      );
      const arr = Array.isArray(res) ? (res as Party[]) : [];
      setHasMore(arr.length > limit);
      setRows(arr.slice(0, limit));
      setListErr("");
    } catch (ex) {
      setRows([]);
      setHasMore(false);
      setListErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, [page, limit]);

  // 联系人目录（服务端搜索；上限 200 条）
  const loadAllContacts = useCallback(async (q: string) => {
    setLoading(true);
    try {
      const data = await apiGet(`/api/v1/masterdata/counterparty-contacts?q=${encodeURIComponent(q)}&limit=200`);
      setAllContacts((data as { items: Contact[] }).items ?? []);
      setContactsErr("");
    } catch (ex) {
      setAllContacts([]);
      setContactsErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (tab === "parties") void load(search);
      else void loadAllContacts(search);
    }, 200);
    return () => clearTimeout(timer);
  }, [tab, search, load, loadAllContacts]);

  const loadContacts = useCallback(async (partyId: string) => {
    try {
      setContacts(await apiGet(`/api/v1/masterdata/counterparties/${partyId}/contacts`));
    } catch (ex) {
      setContacts([]);
      toast.error(msgOf(ex));
    }
  }, [toast]);

  const openContactForm = useCallback((c?: Contact) => {
    if (c) {
      setEditingContact(c);
      setContactParty(c.counterparty_id);
      setContactEdit({
        name: c.name, title: c.title || "", email: c.email || "", phone: c.phone || "",
        mobile: c.mobile || "", department: c.department || "", is_primary: c.is_primary, notes: c.notes || "",
      });
    } else {
      setEditingContact(null);
      setContactEdit({ ...emptyContact });
      setContactParty(open?.id || "");
    }
    setContactOpen(true);
  }, [open]);

  function openCreate() {
    if (tab === "contacts") {
      openContactForm();
      return;
    }
    setOpen(null);
    setEdit({ ...emptyEdit });
    setContacts([]);
    setEditorOpen(true);
  }

  useListHotkeys(openCreate);

  const openRow = useCallback((r: Party) => {
    setOpen(r);
    setEdit({
      name: r.name,
      // 类型多选：优先读 IMOS 多角色集合；老数据只有单值 type 时退化为一项
      types: r.address_types?.length ? r.address_types : r.type ? [r.type] : [],
      country: r.country || "", sanctions_status: r.sanctions_status || "clear",
      address: r.address || "", tax_id: r.tax_id || "", swift_code: r.swift_code || "",
      registration_no: r.registration_no || "", website: r.website || "", phone: r.phone || "",
      email: r.email || "", notes: r.notes || "",
    });
    setEditorOpen(true);
    loadContacts(r.id);
  }, [loadContacts]);

  function editorBody() {
    return {
      name: edit.name,
      // type 保留单值（历史筛选字段，取首个勾选）；完整多选集合写 address_types
      type: edit.types[0] || "other",
      address_types: edit.types.length ? edit.types : null,
      country: edit.country || null,
      sanctions_status: edit.sanctions_status, address: edit.address || null,
      tax_id: edit.tax_id || null, swift_code: edit.swift_code || null,
      registration_no: edit.registration_no || null, website: edit.website || null,
      phone: edit.phone || null, email: edit.email || null, notes: edit.notes || null,
    };
  }

  async function save() {
    setSaving(true);
    try {
      if (open) {
        await apiPatch(`/api/v1/masterdata/counterparties/${open.id}`, editorBody());
        toast.success(t("common.saved", "Saved"));
      } else {
        await apiPost("/api/v1/masterdata/counterparties", editorBody());
        toast.success(t("page.parties.created", "Counterparty created"));
      }
      setOpen(null);
      setEditorOpen(false);
      await load(search);
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally { setSaving(false); }
  }

  async function removeParty(p: Party) {
    setSaving(true);
    try {
      await apiDelete(`/api/v1/masterdata/counterparties/${p.id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      setOpen(null);
      setEditorOpen(false);
      await load(search);
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally { setSaving(false); }
  }

  /** 删除是不可逆动作 —— 统一走 ConfirmDialog，确认文案指名对象。 */
  function requestDeleteParty(p: Party) {
    setPendingDelete({ run: () => void removeParty(p), name: p.name });
  }

  async function saveContact(e: FormEvent) {
    e.preventDefault();
    const partyId = open?.id || contactParty;
    if (!partyId) {
      toast.error(t("page.parties.need_company", "Please select a company"));
      return;
    }
    try {
      if (editingContact) {
        await apiPatch(`/api/v1/masterdata/counterparties/${editingContact.counterparty_id}/contacts/${editingContact.id}`, contactEdit);
      } else {
        await apiPost(`/api/v1/masterdata/counterparties/${partyId}/contacts`, contactEdit);
      }
      setContactOpen(false);
      setEditingContact(null);
      setContactEdit({ ...emptyContact });
      setContactParty("");
      toast.success(t("common.saved", "Saved"));
      if (open) await loadContacts(open.id);
      await loadAllContacts(search);
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  const deleteContact = useCallback(async (c: Contact) => {
    try {
      await apiDelete(`/api/v1/masterdata/counterparties/${c.counterparty_id}/contacts/${c.id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      if (open) await loadContacts(open.id);
      await loadAllContacts(search);
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }, [toast, t, open, loadContacts, loadAllContacts, search]);

  /** 删除是不可逆动作 —— 统一走 ConfirmDialog，确认文案指名对象。 */
  const requestDeleteContact = useCallback((c: Contact) => {
    setPendingDelete({ run: () => void deleteContact(c), name: c.name });
  }, [deleteContact]);

  function changeTab(k: Tab) {
    setQuery({ tab: k === "parties" ? null : k, q: null }, { resetPage: true });
  }

  function validateEdit(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    if (!edit.name.trim()) issues.push({ level: "error", message: t("page.parties.err_name", "Name is required") });
    if (edit.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(edit.email.trim()))
      issues.push({ level: "error", message: t("page.parties.err_email", "Email format is invalid") });
    if (!edit.email.trim()) issues.push({ level: "error", message: t("page.parties.err_email_missing", "Email is required") });
    if (!edit.address.trim()) issues.push({ level: "warn", message: t("page.parties.warn_address", "Address is empty") });
    if (edit.sanctions_status === "blocked")
      issues.push({ level: "error", message: t("page.parties.err_sanctions", "Sanctions status is blocked — cannot save as clear counterparty") });
    if (edit.sanctions_status === "review")
      issues.push({ level: "warn", message: t("page.parties.warn_sanctions", "Sanctions status is under review") });
    return issues;
  }

  function copyId(id: string) {
    void navigator.clipboard.writeText(id);
    toast.success(t("ctx.copied_id", "ID copied"));
  }

  function exportParties(list: Party[]) {
    downloadCsv(
      "counterparties",
      ["id", "name", "type", "country", "sanctions_status", "email", "phone"],
      list.map((r) => [r.id, r.name, r.type, r.country ?? "", r.sanctions_status, r.email ?? "", r.phone ?? ""]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  function exportContacts(list: Contact[]) {
    downloadCsv(
      "counterparty_contacts",
      ["id", "name", "counterparty_name", "title", "email", "phone"],
      list.map((r) => [r.id, r.name, r.counterparty_name ?? "", r.title ?? "", r.email ?? "", r.phone ?? ""]),
      { emptyGuard: t("export.empty_confirm", "No rows to export. Export anyway?") },
    );
  }

  const partyMenuItems = (r: Party): ContextMenuItem[] => [
    { key: "open", label: t("ctx.open", "Open"), onClick: () => router.push(`/masterdata/counterparties/${r.id}`) },
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyId(r.id) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportParties([r]) },
    { key: "d1", label: "", divider: true },
    {
      key: "delete",
      label: t("common.delete", "Delete"),
      danger: true,
      disabled: r.sanctions_status === "blocked",
      onClick: () => requestDeleteParty(r),
    },
  ];

  const contactMenuItems = (r: Contact): ContextMenuItem[] => [
    { key: "edit", label: t("common.edit", "Edit"), onClick: () => openContactForm(r) },
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyId(r.id) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportContacts([r]) },
    { key: "d1", label: "", divider: true },
    { key: "delete", label: t("common.delete", "Delete"), danger: true, onClick: () => requestDeleteContact(r) },
  ];

  const partyColumns = useMemo<ColumnDef<Party>[]>(() => [
    {
      key: "name",
      title: t("common.name", "Name"),
      minWidth: 160,
      value: (r) => r.name,
      // A5：列表行链接到对手方卡片
      render: (_v, r) => (
        <Link href={`/masterdata/counterparties/${r.id}`} onClick={(e) => e.stopPropagation()} className="row-link">
          {r.name}
        </Link>
      ),
    },
    {
      key: "short_name",
      title: t("page.parties.short_name", "Short name"),
      width: 120,
      value: (r) => r.short_name || "",
      render: (_v, r) => r.short_name || "—",
    },
    {
      key: "type",
      title: t("common.type", "Type"),
      width: 120,
      value: (r) => r.type,
      // 多角色公司展示完整集合；老数据只有单值
      render: (_v, r) => (r.address_types?.length ? r.address_types.join(", ") : r.type),
    },
    {
      key: "company_no",
      title: t("page.parties.company_no", "Company no."),
      width: 130,
      value: (r) => r.company_no || "",
      render: (_v, r) => r.company_no || "—",
    },
    {
      key: "ref_no",
      title: t("page.parties.ref_no", "Ref no."),
      width: 120,
      value: (r) => r.ref_no || "",
      render: (_v, r) => r.ref_no || "—",
    },
    {
      key: "country",
      title: t("page.ports.country", "Country"),
      width: 110,
      value: (r) => r.country || "",
      render: (_v, r) => r.country || "—",
    },
    {
      key: "sanctions_status",
      title: t("page.parties.sanctions_col", "Sanctions"),
      width: 110,
      value: (r) => r.sanctions_status,
      render: (_v, r) => (
        <span className={`pill ${r.sanctions_status === "clear" ? "valid" : r.sanctions_status === "blocked" ? "danger" : "warn"}`}>
          {r.sanctions_status}
        </span>
      ),
    },
    {
      key: "email",
      title: t("common.email", "Email"),
      minWidth: 140,
      value: (r) => r.email || "",
      render: (_v, r) => r.email || "—",
    },
    {
      key: "phone",
      title: t("common.phone", "Phone"),
      width: 120,
      value: (r) => r.phone || "",
      render: (_v, r) => r.phone || "—",
    },
    {
      key: "main_contact",
      title: t("page.parties.main_contact", "Main contact"),
      minWidth: 140,
      value: (r) => r.main_contact || "",
      render: (_v, r) => r.main_contact || "—",
    },
    {
      key: "credit_term",
      title: t("page.parties.credit_term", "Credit term"),
      width: 110,
      align: "right",
      value: (r) => (r.credit_term ?? null) as number | string | null,
      render: (_v, r) =>
        r.credit_term === null || r.credit_term === undefined || r.credit_term === "" ? "—" : String(r.credit_term),
    },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 105,
      value: (r) => r.status || "active",
      render: (_v, r) => (
        <span className={`pill ${r.status === "inactive" ? "warn" : "valid"}`}>
          {t(`page.parties.status_${r.status || "active"}`, r.status || "active")}
        </span>
      ),
    },
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
  ], [t, openRow]);

  const contactColumns = useCallback((opts: { showCompany: boolean; compact?: boolean }): ColumnDef<Contact>[] => {
    const cols: ColumnDef<Contact>[] = [
      {
        key: "name",
        title: t("common.name", "Name"),
        minWidth: 130,
        value: (r) => r.name,
        render: (_v, r) => (
          <>
            {r.is_primary ? <strong>{r.name}</strong> : r.name} {r.is_primary && <span className="pill valid">{t("page.parties.primary", "primary")}</span>}
          </>
        ),
      },
    ];
    if (opts.showCompany) {
      cols.push({
        key: "counterparty_name",
        title: t("page.parties.company", "Company"),
        minWidth: 140,
        value: (r) => r.counterparty_name || "",
        render: (_v, r) => (
          <button
            type="button"
            className="btn-link"
            onClick={async (e) => {
              e.stopPropagation();
              const party = (await apiGet(`/api/v1/masterdata/counterparties/${r.counterparty_id}`)) as Party;
              setQuery({ tab: null, q: null }, { resetPage: true });
              openRow(party);
            }}
          >
            {r.counterparty_name || "—"}
          </button>
        ),
      });
    }
    cols.push(
      {
        key: "title",
        title: t("page.parties.title_role", "Title / Role"),
        minWidth: 130,
        value: (r) => `${r.title || ""}${r.department ? ` / ${r.department}` : ""}`,
        render: (_v, r) => (
          <>
            {r.title || "—"}
            {r.department ? ` / ${r.department}` : ""}
          </>
        ),
      },
      {
        key: "email",
        title: t("common.email", "Email"),
        minWidth: 130,
        value: (r) => r.email || "",
        render: (_v, r) => r.email || "—",
      },
      {
        key: "phone",
        title: t("common.phone", "Phone"),
        width: 120,
        value: (r) => r.phone || r.mobile || "",
        render: (_v, r) => r.phone || r.mobile || "—",
      },
      {
        key: "actions",
        title: "",
        width: opts.compact ? 110 : 130,
        align: "right",
        render: (_v, r) => (
          <>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={(e) => {
                e.stopPropagation();
                openContactForm(r);
              }}
            >
              {t("common.edit", "Edit")}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-danger-text"
              onClick={(e) => {
                e.stopPropagation();
                requestDeleteContact(r);
              }}
            >
              {t("common.delete", "Delete")}
            </button>
          </>
        ),
      },
    );
    return cols;
  }, [t, setQuery, openRow, openContactForm, requestDeleteContact]);

  const contactColsDirectory = useMemo<ColumnDef<Contact>[]>(
    () => contactColumns({ showCompany: true }),
    [contactColumns],
  );

  const contactColsParty = useMemo<ColumnDef<Contact>[]>(
    () => contactColumns({ showCompany: false, compact: true }),
    [contactColumns],
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.master", "Master data") }]}
        title={t("page.parties.title", "Counterparties")}
        subtitle={t("page.parties.sub", "Shipowners, charterers, brokers & agents. Click row to edit.")}
        actions={<Link href="/settings/recycle" className="btn btn-ghost">{t("nav.recycle", "Recycle bin")}</Link>}
      />

      {/* Tabs：公司 / 联系人 */}
      <Tabs
        items={
          [
            { key: "parties", label: t("page.parties.tab_companies", "Companies") },
            { key: "contacts", label: t("page.parties.tab_contacts", "Contacts") },
          ] satisfies TabItem[]
        }
        value={tab}
        onChange={(k) => changeTab(k as Tab)}
        variant="line"
      />

      <Toolbar
        filterCount={search ? 1 : 0}
        onClearFilters={() => {
          setSearch("");
          setQuery({ q: null }, { resetPage: true });
        }}
        right={
          <>
            <input
              type="search"
              className="input input-sm"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={
                tab === "parties"
                  ? t("page.parties.search_companies", "Search name / country / email…")
                  : t("page.parties.search_contacts", "Search contact name / company / email / title…")
              }
              aria-label={t("common.search", "Search")}
            />
            <span className="muted">
              {tab === "parties"
                ? hasMore
                  ? t("list.count_more", "{n}+ records", { n: (page - 1) * limit + rows.length })
                  : t("list.count_total", "{n} records", { n: (page - 1) * limit + rows.length })
                : t("list.count_total", "{n} records", { n: allContacts.length })}
            </span>
            <SavedViews storageKey="md_counterparties" onApply={(q) => router.replace(`${pathname}${q}`)} />
          </>
        }
      >
        <button className="btn btn-primary btn-sm" type="button" onClick={openCreate}>
          + {tab === "parties" ? t("page.parties.add", "Add counterparty") : t("page.parties.add_contact", "Add contact")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => {
            if (tab === "parties") void load(search);
            else void loadAllContacts(search);
          }} />
      </Toolbar>

      {tab === "parties" ? (
        <div className="panel">
          <StatusLegend statuses={["clear", "review", "blocked"]} />
          <StateView
            loading={loading}
            error={listErr || undefined}
            empty={!rows.length}
            emptyText={t("common.empty", "No records")}
            onRetry={() => void load(search)}
          >
            <DataGrid<Party>
              columns={partyColumns}
              data={rows}
              rowKey={(r) => r.id}
              onRowClick={(r) => router.push(`/masterdata/counterparties/${r.id}`)}
              onRowContextMenu={(r, _i, e) => partyCtx.open(r)(e)}
              storageKey="masterdata_counterparties_grid"
              emptyText={t("common.empty", "No records")}
            />
          </StateView>
          {page > 1 || hasMore ? (
            <div className="toolbar">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={page <= 1}
                onClick={() => setQuery({ page: page - 1 })}
              >
                ← {t("common.prev", "Previous")}
              </button>
              <span className="muted">{t("list.page_of", "Page {page}", { page })}</span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={!hasMore}
                onClick={() => setQuery({ page: page + 1 })}
              >
                {t("common.next", "Next")} →
              </button>
            </div>
          ) : null}
          <ContextMenu controller={partyCtx} items={partyMenuItems} />
        </div>
      ) : (
        <div className="panel">
          <StateView
            loading={loading}
            error={contactsErr || undefined}
            empty={!allContacts.length}
            emptyText={t("common.empty", "No records")}
            onRetry={() => void loadAllContacts(search)}
          >
            <DataGrid<Contact>
              columns={contactColsDirectory}
              data={allContacts}
              rowKey={(r) => r.id}
              onRowContextMenu={(r, _i, e) => contactCtx.open(r)(e)}
              storageKey="masterdata_contacts_grid"
              emptyText={t("common.empty", "No records")}
            />
          </StateView>
          {allContacts.length >= 200 ? (
            <p className="muted">
              {t("page.parties.contacts_truncated", "Showing the first 200 contacts — narrow the search to see the rest.")}
            </p>
          ) : null}
          <ContextMenu controller={contactCtx} items={contactMenuItems} />
        </div>
      )}

      {/* 公司新建/编辑弹窗（编辑时含其联系人区块） */}
      <RecordModal
        open={editorOpen}
        title={open ? t("page.parties.edit", "Edit counterparty") : t("page.parties.add", "Add counterparty")}
        onClose={() => { setEditorOpen(false); setOpen(null); }}
        onSave={save}
        saving={saving}
      >
        <label>{t("common.name", "Name")}
          <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
        </label>
        <div className="form-type-multi">
          <span className="field-label">{t("common.type", "Type")}</span>
          {/* 类型多选：一家公司常同时是船东+经纪人。勾选集合写 IMOS address_types，
              type 单值字段取首个勾选（历史筛选兼容） */}
          <div className="check-grid">
            {typeItems.map((it) => (
              <label key={it.code} className="check-row">
                <input
                  type="checkbox"
                  checked={edit.types.includes(it.code)}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      types: e.target.checked
                        ? [...edit.types, it.code]
                        : edit.types.filter((c) => c !== it.code),
                    })
                  }
                />
                {showCodeLabel(it)}
              </label>
            ))}
          </div>
          {!typeItems.length && !typeErr ? (
            <span className="muted">{t("common.loading", "加载中…")}</span>
          ) : null}
          {typeErr ? (
            <span className="field-error" role="alert">{typeErr}</span>
          ) : null}
        </div>
        <label>{t("page.ports.country", "Country")}
          <LookupSelect dataset="countries" value={edit.country} onChange={(v) => setEdit({ ...edit, country: v })} />
        </label>
        <label>{t("page.parties.sanctions", "Sanctions status")}
          <select value={edit.sanctions_status} onChange={(e) => setEdit({ ...edit, sanctions_status: e.target.value })}>
            <option value="clear">clear</option>
            <option value="review">review</option>
            <option value="blocked">blocked</option>
          </select>
        </label>
        <label>{t("common.email", "Email")}
          <input type="email" value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} />
        </label>
        <label>{t("common.phone", "Phone")}
          <input value={edit.phone} onChange={(e) => setEdit({ ...edit, phone: e.target.value })} />
        </label>
        <label>{t("page.parties.address", "Address")}
          <input value={edit.address} onChange={(e) => setEdit({ ...edit, address: e.target.value })} />
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
          <label>{t("page.parties.tax_id", "Tax ID")}
            <input value={edit.tax_id} onChange={(e) => setEdit({ ...edit, tax_id: e.target.value })} />
          </label>
          <label>{t("page.parties.swift", "SWIFT / BIC")}
            <input value={edit.swift_code} onChange={(e) => setEdit({ ...edit, swift_code: e.target.value })} />
          </label>
        </div>
        <label>{t("page.parties.reg_no", "Registration No.")}
          <input value={edit.registration_no} onChange={(e) => setEdit({ ...edit, registration_no: e.target.value })} />
        </label>
        <label>{t("page.parties.website", "Website")}
          <input value={edit.website} onChange={(e) => setEdit({ ...edit, website: e.target.value })} />
        </label>
        <label>{t("common.notes", "Notes")}
          <textarea value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} rows={2} />
        </label>

        <div className="record-modal-validate">
          <ValidateButton onValidate={validateEdit} />
        </div>

        {/* P1-8：删除公司是不可逆动作 —— 走指名对象的二次确认。 */}
        {open ? (
          <div className="desk-toolbar">
            <button
              type="button"
              className="btn btn-danger btn-sm"
              disabled={saving}
              onClick={() => requestDeleteParty(open)}
            >
              {t("common.delete", "Delete")}
            </button>
          </div>
        ) : null}

        {/* Contacts section（仅编辑已有公司时展示） */}
        {open ? (
        <div style={{ gridColumn: "1 / -1", borderTop: "1px solid var(--border)", paddingTop: "0.75rem", marginTop: "0.5rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <h3 style={{ margin: 0, fontSize: "0.9rem" }}>{t("page.parties.contacts", "Contacts")}</h3>
            <button type="button" className="btn btn-ghost" style={{ fontSize: "0.78rem", padding: "0.2rem 0.6rem" }} onClick={() => openContactForm()}>
              + {t("common.add", "Add")}
            </button>
          </div>
          {contacts.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>{t("page.parties.no_contacts", "No contacts yet")}</p>
          ) : (
            <DataGrid<Contact>
              columns={contactColsParty}
              data={contacts}
              rowKey={(r) => r.id}
              storageKey="masterdata_party_contacts_grid"
              showFooter={false}
              showColumnMenu={false}
              emptyText={t("page.parties.no_contacts", "No contacts yet")}
            />
          )}
        </div>
        ) : null}
      </RecordModal>

      {/* Contact add/edit modal（跨公司：用 PartyPicker 选公司） */}
      <RecordModal
        open={contactOpen}
        title={editingContact ? t("page.parties.edit_contact", "Edit contact") : t("page.parties.add_contact", "Add contact")}
        onClose={() => { setContactOpen(false); setEditingContact(null); }}
        onSave={saveContact}
        saving={false}
      >
        {!open ? (
          <label>{t("page.parties.company", "Company")}
            <PartyPicker value={contactParty} onChange={(id) => setContactParty(id)} allowEmpty={false} placeholder={t("page.parties.pick_company", "Search company…")} />
          </label>
        ) : (
          <p className="muted" style={{ margin: 0 }}>{t("page.parties.company", "Company")}: <strong>{open.name}</strong></p>
        )}
        <label>{t("common.name", "Name")}
          <input value={contactEdit.name} onChange={(e) => setContactEdit({ ...contactEdit, name: e.target.value })} required />
        </label>
        <label>{t("page.parties.title_role", "Title / Role")}
          <input value={contactEdit.title} onChange={(e) => setContactEdit({ ...contactEdit, title: e.target.value })} />
        </label>
        <label>{t("page.parties.department", "Department")}
          <input value={contactEdit.department} onChange={(e) => setContactEdit({ ...contactEdit, department: e.target.value })} />
        </label>
        <label>{t("common.email", "Email")}
          <input type="email" value={contactEdit.email} onChange={(e) => setContactEdit({ ...contactEdit, email: e.target.value })} />
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
          <label>{t("common.phone", "Phone")}
            <input value={contactEdit.phone} onChange={(e) => setContactEdit({ ...contactEdit, phone: e.target.value })} />
          </label>
          <label>{t("page.parties.mobile", "Mobile")}
            <input value={contactEdit.mobile} onChange={(e) => setContactEdit({ ...contactEdit, mobile: e.target.value })} />
          </label>
        </div>
        <label>
          <input type="checkbox" checked={contactEdit.is_primary} onChange={(e) => setContactEdit({ ...contactEdit, is_primary: e.target.checked })} />
          {" "}{t("page.parties.primary_contact", "Primary contact")}
        </label>
        <label>{t("common.notes", "Notes")}
          <textarea value={contactEdit.notes} onChange={(e) => setContactEdit({ ...contactEdit, notes: e.target.value })} rows={2} />
        </label>
      </RecordModal>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={t("common.confirm", "Confirm")}
        message={t("common.confirm_delete_named", 'Delete "{name}"?', {
          name: pendingDelete?.name ?? "",
        })}
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
      <CounterpartiesPage />
    </Suspense>
  );
}
