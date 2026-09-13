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
};

export default function CounterpartiesPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Party[]>([]);
  const [name, setName] = useState("");
  const [type, setType] = useState("charterer");
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<Party | null>(null);
  const [edit, setEdit] = useState({ name: "", type: "charterer", country: "", sanctions_status: "clear" });
  const [saving, setSaving] = useState(false);

  async function load() {
    setRows(await apiGet("/api/v1/masterdata/counterparties"));
  }

  useEffect(() => {
    load().catch(() => setRows([]));
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/masterdata/counterparties", { name, type, sanctions_status: "clear" });
    setName("");
    setMsg(t("page.parties.created", "对手方已创建"));
    await load();
  }

  function openRow(r: Party) {
    setOpen(r);
    setEdit({
      name: r.name,
      type: r.type,
      country: r.country || "",
      sanctions_status: r.sanctions_status || "clear",
    });
  }

  async function save() {
    if (!open) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/masterdata/counterparties/${open.id}`, {
        name: edit.name,
        type: edit.type,
        country: edit.country || null,
        sanctions_status: edit.sanctions_status,
      });
      setMsg(t("common.saved", "Saved"));
      setOpen(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/masterdata/counterparties/${open.id}`);
      setMsg(t("common.recycled", "Moved to recycle bin"));
      setOpen(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.parties.title", "对手方")}</h1>
          <p className="page-sub">{t("page.parties.sub", "船东、租家、经纪与代理。点击行打开编辑。")}</p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "Recycle bin")}
        </Link>
      </div>
      <form
        className="panel"
        onSubmit={(e) => onCreate(e).catch(() => setMsg(t("page.parties.create_fail", "创建失败")))}
        style={{ marginBottom: "1rem" }}
      >
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("common.name", "Name")}
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            {t("common.type", "类型")}
            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="charterer">charterer</option>
              <option value="owner">owner</option>
              <option value="broker">broker</option>
              <option value="agent">agent</option>
              <option value="other">other</option>
            </select>
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.parties.add", "新建对手方")}
          </button>
        </div>
        {msg ? <p style={{ marginBottom: 0 }}>{msg}</p> : null}
      </form>
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "Name")}</th>
              <th>{t("common.type", "类型")}</th>
              <th>{t("page.ports.country", "Country")}</th>
              <th>{t("page.parties.sanctions", "Sanctions status")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                <td>{r.name}</td>
                <td>{r.type}</td>
                <td>{r.country || "—"}</td>
                <td>{r.sanctions_status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={t("page.parties.edit", "Edit counterparty")}
        onClose={() => setOpen(null)}
        onSave={save}
        onDelete={remove}
        saving={saving}
      >
        <label>
          {t("common.name", "Name")}
          <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
        </label>
        <label>
          {t("common.type", "类型")}
          <select value={edit.type} onChange={(e) => setEdit({ ...edit, type: e.target.value })}>
            <option value="charterer">charterer</option>
            <option value="owner">owner</option>
            <option value="broker">broker</option>
            <option value="agent">agent</option>
            <option value="other">other</option>
          </select>
        </label>
        <label>
          {t("page.ports.country", "Country")}
          <LookupSelect dataset="countries" value={edit.country} onChange={(v) => setEdit({ ...edit, country: v })} />
        </label>
        <label>
          {t("page.parties.sanctions", "Sanctions status")}
          <select value={edit.sanctions_status} onChange={(e) => setEdit({ ...edit, sanctions_status: e.target.value })}>
            <option value="clear">clear</option>
            <option value="review">review</option>
            <option value="blocked">blocked</option>
          </select>
        </label>
      </RecordModal>
    </AppShell>
  );
}
