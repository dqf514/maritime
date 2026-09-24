"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { LookupSelect } from "@/components/LookupSelect";
import { RecordModal } from "@/components/RecordModal";
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

export default function CounterpartiesPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Party[]>([]);
  const [name, setName] = useState("");
  const [type, setType] = useState("charterer");
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<Party | null>(null);
  const [edit, setEdit] = useState({ ...emptyEdit });
  const [saving, setSaving] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contactOpen, setContactOpen] = useState(false);
  const [contactEdit, setContactEdit] = useState({ ...emptyContact });
  const [editingContact, setEditingContact] = useState<Contact | null>(null);

  async function load() {
    setRows(await apiGet("/api/v1/masterdata/counterparties"));
  }

  useEffect(() => { load().catch(() => setRows([])); }, []);

  async function loadContacts(partyId: string) {
    try {
      setContacts(await apiGet(`/api/v1/masterdata/counterparties/${partyId}/contacts`));
    } catch { setContacts([]); }
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/masterdata/counterparties", { name, type, sanctions_status: "clear" });
    setName("");
    setMsg(t("page.parties.created", "Counterparty created"));
    await load();
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
      setMsg(t("common.saved", "Saved"));
      setOpen(null);
      await load();
    } finally { setSaving(false); }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/masterdata/counterparties/${open.id}`);
      setMsg(t("common.recycled", "Moved to recycle bin"));
      setOpen(null);
      await load();
    } finally { setSaving(false); }
  }

  async function saveContact(e: FormEvent) {
    e.preventDefault();
    if (!open) return;
    if (editingContact) {
      await apiPatch(`/api/v1/masterdata/counterparties/${open.id}/contacts/${editingContact.id}`, contactEdit);
    } else {
      await apiPost(`/api/v1/masterdata/counterparties/${open.id}/contacts`, contactEdit);
    }
    setContactOpen(false);
    setEditingContact(null);
    setContactEdit({ ...emptyContact });
    await loadContacts(open.id);
  }

  async function deleteContact(c: Contact) {
    if (!open) return;
    await apiDelete(`/api/v1/masterdata/counterparties/${open.id}/contacts/${c.id}`);
    await loadContacts(open.id);
  }

  function openContactForm(c?: Contact) {
    if (c) {
      setEditingContact(c);
      setContactEdit({
        name: c.name, title: c.title || "", email: c.email || "", phone: c.phone || "",
        mobile: c.mobile || "", department: c.department || "", is_primary: c.is_primary, notes: c.notes || "",
      });
    } else {
      setEditingContact(null);
      setContactEdit({ ...emptyContact });
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

      <form className="panel" onSubmit={(e) => onCreate(e).catch(() => setMsg(t("page.parties.create_fail", "Create failed")))} style={{ marginBottom: "1rem" }}>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>{t("common.name", "Name")}
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label style={{ minWidth: 180 }}>{t("common.type", "Type")}
            <LookupSelect dataset="counterparty_types" value={type} onChange={setType} />
          </label>
          <button className="btn btn-primary" type="submit">{t("page.parties.add", "Add counterparty")}</button>
        </div>
        {msg ? <p style={{ marginBottom: 0 }}>{msg}</p> : null}
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
          </tbody>
        </table>
      </div>

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

      {/* Contact add/edit modal */}
      <RecordModal
        open={contactOpen}
        title={editingContact ? t("page.parties.edit_contact", "Edit contact") : t("page.parties.add_contact", "Add contact")}
        onClose={() => { setContactOpen(false); setEditingContact(null); }}
        onSave={saveContact as unknown as () => void}
        saving={false}
      >
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
