"use client";

// 对手方与联系人（数据闭环重做）：
// - Tabs：公司 / 联系人 两个视角，联系人不再藏在公司弹窗里
// - 显著搜索框（服务端 q：名称/公司/邮箱/职务/部门）
// - 联系人目录跨公司可见；新建联系人用 PartyPicker 选公司
// - 公司详情弹窗保留联系人区块（按公司上下文管理）

import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { LookupSelect } from "@/components/LookupSelect";
import { PartyPicker } from "@/components/DataPicker";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { StatusLegend } from "@/components/StatusLegend";
import { Tabs, type TabItem } from "@/components/Tabs";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { useToast } from "@/components/ToastProvider";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type Party = {
  id: string;
  name: string;
  type: string;
  country: string | null;
  sanctions_status: string;
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
  name: "", type: "charterer", country: "", sanctions_status: "clear",
  address: "", tax_id: "", swift_code: "", registration_no: "",
  website: "", phone: "", email: "", notes: "",
};

const emptyContact = {
  name: "", title: "", email: "", phone: "", mobile: "", department: "", is_primary: false, notes: "",
};

type Tab = "parties" | "contacts";

function CounterpartiesPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery } = useListQuery();
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

  // 公司列表（服务端搜索）
  const load = useCallback(async (q: string) => {
    setRows(await apiGet(`/api/v1/masterdata/counterparties?q=${encodeURIComponent(q)}&limit=200`));
  }, []);

  // 联系人目录（服务端搜索）
  const loadAllContacts = useCallback(async (q: string) => {
    try {
      const data = await apiGet(`/api/v1/masterdata/counterparty-contacts?q=${encodeURIComponent(q)}&limit=200`);
      setAllContacts((data as { items: Contact[] }).items ?? []);
    } catch {
      setAllContacts([]);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (tab === "parties") load(search).catch(() => setRows([]));
      else loadAllContacts(search).catch(() => setAllContacts([]));
    }, 200);
    return () => clearTimeout(timer);
  }, [tab, search, load, loadAllContacts]);

  async function loadContacts(partyId: string) {
    try {
      setContacts(await apiGet(`/api/v1/masterdata/counterparties/${partyId}/contacts`));
    } catch { setContacts([]); }
  }

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

  function openRow(r: Party) {
    setOpen(r);
    setEdit({
      name: r.name, type: r.type, country: r.country || "", sanctions_status: r.sanctions_status || "clear",
      address: r.address || "", tax_id: r.tax_id || "", swift_code: r.swift_code || "",
      registration_no: r.registration_no || "", website: r.website || "", phone: r.phone || "",
      email: r.email || "", notes: r.notes || "",
    });
    setEditorOpen(true);
    loadContacts(r.id);
  }

  function editorBody() {
    return {
      name: edit.name, type: edit.type, country: edit.country || null,
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
    } finally { setSaving(false); }
  }

  async function remove() {
    if (!open) return;
    await removeParty(open);
  }

  async function removeParty(p: Party) {
    setSaving(true);
    try {
      await apiDelete(`/api/v1/masterdata/counterparties/${p.id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      setOpen(null);
      setEditorOpen(false);
      await load(search);
    } finally { setSaving(false); }
  }

  async function saveContact(e: FormEvent) {
    e.preventDefault();
    const partyId = open?.id || contactParty;
    if (!partyId) {
      toast.error(t("page.parties.need_company", "Please select a company"));
      return;
    }
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
  }

  async function deleteContact(c: Contact) {
    await apiDelete(`/api/v1/masterdata/counterparties/${c.counterparty_id}/contacts/${c.id}`);
    toast.success(t("common.recycled", "Moved to recycle bin"));
    if (open) await loadContacts(open.id);
    await loadAllContacts(search);
  }

  function openContactForm(c?: Contact) {
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
  }

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
    { key: "open", label: t("ctx.open", "Open"), onClick: () => openRow(r) },
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyId(r.id) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportParties([r]) },
    { key: "d1", label: "", divider: true },
    {
      key: "delete",
      label: t("common.delete", "Delete"),
      danger: true,
      disabled: r.sanctions_status === "blocked",
      onClick: () => {
        void removeParty(r);
      },
    },
  ];

  const contactMenuItems = (r: Contact): ContextMenuItem[] => [
    { key: "edit", label: t("common.edit", "Edit"), onClick: () => openContactForm(r) },
    { key: "copy", label: t("ctx.copy_id", "Copy id"), onClick: () => copyId(r.id) },
    { key: "export", label: t("ctx.export_selected", "Export selected"), onClick: () => exportContacts([r]) },
    { key: "d1", label: "", divider: true },
    { key: "delete", label: t("common.delete", "Delete"), danger: true, onClick: () => void deleteContact(r) },
  ];

  const partyColumns: ColumnDef<Party>[] = [
    { key: "name", title: t("common.name", "Name"), minWidth: 150, value: (r) => r.name },
    { key: "type", title: t("common.type", "Type"), width: 120, value: (r) => r.type },
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
      key: "updated_at",
      title: t("list.last_modified", "Last modified"),
      width: 135,
      value: (r) => r.updated_at ?? null,
      render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
    },
  ];

  function contactColumns(opts: { showCompany: boolean; compact?: boolean }): ColumnDef<Contact>[] {
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
                deleteContact(r);
              }}
            >
              {t("common.delete", "Delete")}
            </button>
          </>
        ),
      },
    );
    return cols;
  }

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
              {tab === "parties" ? rows.length : allContacts.length} {t("common.records", "records")}
            </span>
            <SavedViews storageKey="md_counterparties" onApply={(q) => router.replace(`${pathname}${q}`)} />
          </>
        }
      >
        <button className="btn btn-primary btn-sm" type="button" onClick={openCreate}>
          + {tab === "parties" ? t("page.parties.add", "Add counterparty") : t("page.parties.add_contact", "Add contact")}
        </button>
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => {
            if (tab === "parties") load(search).catch(() => undefined);
            else loadAllContacts(search).catch(() => undefined);
          }}
          title={t("common.refresh", "Refresh")}
        >
          ↻
        </button>
      </Toolbar>

      {tab === "parties" ? (
        <div className="panel">
          <StatusLegend statuses={["clear", "review", "blocked"]} />
          <DataGrid<Party>
            columns={partyColumns}
            data={rows}
            rowKey={(r) => r.id}
            onRowClick={(r) => openRow(r)}
            onRowContextMenu={(r, _i, e) => partyCtx.open(r)(e)}
            storageKey="masterdata_counterparties_grid"
            emptyText={t("common.empty", "No records")}
          />
          <ContextMenu controller={partyCtx} items={partyMenuItems} />
        </div>
      ) : (
        <div className="panel">
          <DataGrid<Contact>
            columns={contactColumns({ showCompany: true })}
            data={allContacts}
            rowKey={(r) => r.id}
            onRowContextMenu={(r, _i, e) => contactCtx.open(r)(e)}
            storageKey="masterdata_contacts_grid"
            emptyText={t("common.empty", "No records")}
          />
          <ContextMenu controller={contactCtx} items={contactMenuItems} />
        </div>
      )}

      {/* 公司新建/编辑弹窗（编辑时含其联系人区块） */}
      <RecordModal
        open={editorOpen}
        title={open ? t("page.parties.edit", "Edit counterparty") : t("page.parties.add", "Add counterparty")}
        onClose={() => { setEditorOpen(false); setOpen(null); }}
        onSave={save}
        onDelete={open ? remove : undefined}
        canDelete={!!open}
        saving={saving}
      >
        <label>{t("common.name", "Name")}
          <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
        </label>
        <label style={{ minWidth: 180 }}>{t("common.type", "Type")}
          <LookupSelect dataset="counterparty_types" value={edit.type} onChange={(v) => setEdit({ ...edit, type: v })} />
        </label>
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
              columns={contactColumns({ showCompany: false, compact: true })}
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
