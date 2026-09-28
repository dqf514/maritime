"use client";

// 对手方与联系人（数据闭环重做）：
// - Tabs：公司 / 联系人 两个视角，联系人不再藏在公司弹窗里
// - 显著搜索框（服务端 q：名称/公司/邮箱/职务/部门）
// - 联系人目录跨公司可见；新建联系人用 PartyPicker 选公司
// - 公司详情弹窗保留联系人区块（按公司上下文管理）

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { LookupSelect } from "@/components/LookupSelect";
import { PartyPicker } from "@/components/DataPicker";
import { RecordModal } from "@/components/RecordModal";
import { useToast } from "@/components/ToastProvider";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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

export default function CounterpartiesPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("parties");
  const [search, setSearch] = useState("");
  const [rows, setRows] = useState<Party[]>([]);
  const [name, setName] = useState("");
  const [type, setType] = useState("charterer");
  const [open, setOpen] = useState<Party | null>(null);
  const [edit, setEdit] = useState({ ...emptyEdit });
  const [saving, setSaving] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [allContacts, setAllContacts] = useState<Contact[]>([]);
  const [contactOpen, setContactOpen] = useState(false);
  const [contactEdit, setContactEdit] = useState({ ...emptyContact });
  const [editingContact, setEditingContact] = useState<Contact | null>(null);
  const [contactParty, setContactParty] = useState(""); // 联系人表单所属公司（跨公司新建用）

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

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/masterdata/counterparties", { name, type, sanctions_status: "clear" });
    setName("");
    toast.success(t("page.parties.created", "Counterparty created"));
    await load(search);
  }

  function openRow(r: Party) {
    setOpen(r);
    setEdit({
      name: r.name, type: r.type, country: r.country || "", sanctions_status: r.sanctions_status || "clear",
      address: r.address || "", tax_id: r.tax_id || "", swift_code: r.swift_code || "",
      registration_no: r.registration_no || "", website: r.website || "", phone: r.phone || "",
      email: r.email || "", notes: r.notes || "",
    });
    loadContacts(r.id);
  }

  async function save() {
    if (!open) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/masterdata/counterparties/${open.id}`, {
        name: edit.name, type: edit.type, country: edit.country || null,
        sanctions_status: edit.sanctions_status, address: edit.address || null,
        tax_id: edit.tax_id || null, swift_code: edit.swift_code || null,
        registration_no: edit.registration_no || null, website: edit.website || null,
        phone: edit.phone || null, email: edit.email || null, notes: edit.notes || null,
      });
      toast.success(t("common.saved", "Saved"));
      setOpen(null);
      await load(search);
    } finally { setSaving(false); }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/masterdata/counterparties/${open.id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      setOpen(null);
      await load(search);
    } finally { setSaving(false); }
  }

  async function saveContact(e: FormEvent) {
    e.preventDefault();
    const partyId = open?.id || contactParty;
    if (!partyId) {
      toast.error(t("page.parties.need_company", "请选择所属公司"));
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

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.parties.title", "Counterparties")}</h1>
          <p className="page-sub">{t("page.parties.sub", "Shipowners, charterers, brokers & agents. Click row to edit.")}</p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">{t("nav.recycle", "Recycle bin")}</Link>
      </div>

      {/* Tabs：公司 / 联系人 */}
      <div className="desk-tabs">
        <button type="button" className={`desk-tab${tab === "parties" ? " active" : ""}`} onClick={() => { setTab("parties"); setSearch(""); }}>
          {t("page.parties.tab_companies", "公司")}
        </button>
        <button type="button" className={`desk-tab${tab === "contacts" ? " active" : ""}`} onClick={() => { setTab("contacts"); setSearch(""); }}>
          {t("page.parties.tab_contacts", "联系人")}
        </button>
      </div>

      {/* 显著搜索框 */}
      <div className="panel" style={{ display: "flex", gap: "0.75rem", alignItems: "center", padding: "0.75rem 1rem", marginBottom: "1rem" }}>
        <input
          type="search"
          className="party-search"
          style={{ flex: 1, height: 40, fontSize: "0.95rem", border: "1px solid var(--border)", borderRadius: 8, padding: "0 0.85rem" }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={
            tab === "parties"
              ? t("page.parties.search_companies", "搜索公司名称 / 国家 / 邮箱…")
              : t("page.parties.search_contacts", "搜索联系人姓名 / 公司 / 邮箱 / 职务…")
          }
          aria-label={t("common.search", "Search")}
        />
        <span className="muted">
          {tab === "parties" ? rows.length : allContacts.length} {t("common.records", "条")}
        </span>
      </div>

      {tab === "parties" ? (
        <>
          <form className="panel" onSubmit={(e) => onCreate(e).catch(() => toast.error(t("page.parties.create_fail", "Create failed")))} style={{ marginBottom: "1rem" }}>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
              <label>{t("common.name", "Name")}
                <input value={name} onChange={(e) => setName(e.target.value)} required />
              </label>
              <label style={{ minWidth: 180 }}>{t("common.type", "Type")}
                <LookupSelect dataset="counterparty_types" value={type} onChange={setType} />
              </label>
              <button className="btn btn-primary" type="submit">{t("page.parties.add", "Add counterparty")}</button>
            </div>
          </form>

          <div className="panel">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("common.name", "Name")}</th>
                  <th>{t("common.type", "Type")}</th>
                  <th>{t("page.ports.country", "Country")}</th>
                  <th>{t("page.parties.sanctions", "Sanctions")}</th>
                  <th>{t("common.email", "Email")}</th>
                  <th>{t("common.phone", "Phone")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                    <td>{r.name}</td>
                    <td>{r.type}</td>
                    <td>{r.country || "—"}</td>
                    <td><span className={`pill ${r.sanctions_status === "clear" ? "valid" : r.sanctions_status === "blocked" ? "danger" : "warn"}`}>{r.sanctions_status}</span></td>
                    <td>{r.email || "—"}</td>
                    <td>{r.phone || "—"}</td>
                  </tr>
                ))}
                {!rows.length ? (
                  <tr><td colSpan={6} className="muted">{t("common.empty", "No records")}</td></tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="panel">
          <div className="desk-toolbar" style={{ marginTop: 0, justifyContent: "flex-end" }}>
            <button className="btn btn-primary btn-sm" type="button" onClick={() => openContactForm()}>
              + {t("page.parties.add_contact", "Add contact")}
            </button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>{t("common.name", "Name")}</th>
                <th>{t("page.parties.company", "公司")}</th>
                <th>{t("page.parties.title_role", "Title / Role")}</th>
                <th>{t("common.email", "Email")}</th>
                <th>{t("common.phone", "Phone")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {allContacts.map((c) => (
                <tr key={c.id}>
                  <td>{c.is_primary ? <strong>{c.name}</strong> : c.name} {c.is_primary && <span className="pill valid">primary</span>}</td>
                  <td>
                    <button
                      type="button"
                      className="btn-link"
                      style={{ background: "none", border: "none", color: "var(--accent)", cursor: "pointer", padding: 0, font: "inherit" }}
                      onClick={async () => {
                        const party = (await apiGet(`/api/v1/masterdata/counterparties/${c.counterparty_id}`)) as Party;
                        setTab("parties");
                        openRow(party);
                      }}
                    >
                      {c.counterparty_name || "—"}
                    </button>
                  </td>
                  <td>{c.title || "—"}{c.department ? ` / ${c.department}` : ""}</td>
                  <td>{c.email || "—"}</td>
                  <td>{c.phone || c.mobile || "—"}</td>
                  <td style={{ textAlign: "right" }}>
                    <button type="button" className="btn btn-ghost" style={{ fontSize: "0.75rem", padding: "0.1rem 0.4rem", marginRight: "0.25rem" }} onClick={() => openContactForm(c)}>{t("common.edit", "Edit")}</button>
                    <button type="button" className="btn btn-ghost" style={{ fontSize: "0.75rem", padding: "0.1rem 0.4rem", color: "var(--danger)" }} onClick={() => deleteContact(c)}>{t("common.delete", "Delete")}</button>
                  </td>
                </tr>
              ))}
              {!allContacts.length ? (
                <tr><td colSpan={6} className="muted">{t("common.empty", "No records")}</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}

      {/* 公司编辑弹窗（含其联系人区块） */}
      <RecordModal open={Boolean(open)} title={t("page.parties.edit", "Edit counterparty")} onClose={() => setOpen(null)} onSave={save} onDelete={remove} saving={saving}>
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

        {/* Contacts section */}
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
            <table className="table" style={{ fontSize: "0.82rem" }}>
              <thead>
                <tr>
                  <th>{t("common.name", "Name")}</th>
                  <th>{t("page.parties.title_role", "Title / Role")}</th>
                  <th>{t("common.email", "Email")}</th>
                  <th>{t("common.phone", "Phone")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {contacts.map((c) => (
                  <tr key={c.id}>
                    <td>{c.is_primary ? <strong>{c.name}</strong> : c.name} {c.is_primary && <span className="pill valid">primary</span>}</td>
                    <td>{c.title || "—"}{c.department ? ` / ${c.department}` : ""}</td>
                    <td>{c.email || "—"}</td>
                    <td>{c.phone || c.mobile || "—"}</td>
                    <td style={{ textAlign: "right" }}>
                      <button type="button" className="btn btn-ghost" style={{ fontSize: "0.75rem", padding: "0.1rem 0.4rem", marginRight: "0.25rem" }} onClick={() => openContactForm(c)}>{t("common.edit", "Edit")}</button>
                      <button type="button" className="btn btn-ghost" style={{ fontSize: "0.75rem", padding: "0.1rem 0.4rem", color: "var(--danger)" }} onClick={() => deleteContact(c)}>{t("common.delete", "Delete")}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </RecordModal>

      {/* Contact add/edit modal（跨公司：用 PartyPicker 选公司） */}
      <RecordModal
        open={contactOpen}
        title={editingContact ? t("page.parties.edit_contact", "Edit contact") : t("page.parties.add_contact", "Add contact")}
        onClose={() => { setContactOpen(false); setEditingContact(null); }}
        onSave={saveContact as unknown as () => void}
        saving={false}
      >
        {!open ? (
          <label>{t("page.parties.company", "公司")}
            <PartyPicker value={contactParty} onChange={(id) => setContactParty(id)} allowEmpty={false} placeholder={t("page.parties.search_companies", "搜索公司…")} />
          </label>
        ) : (
          <p className="muted" style={{ margin: 0 }}>{t("page.parties.company", "公司")}: <strong>{open.name}</strong></p>
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
