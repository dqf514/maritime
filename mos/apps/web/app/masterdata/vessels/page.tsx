"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { LookupSelect } from "@/components/LookupSelect";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Vessel = {
  id: string;
  name: string;
  imo: string | null;
  flag: string | null;
  vessel_type: string | null;
  status: string;
};

export default function VesselsPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Vessel[]>([]);
  const [name, setName] = useState("");
  const [imo, setImo] = useState("");
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<Vessel | null>(null);
  const [edit, setEdit] = useState({ name: "", imo: "", flag: "", vessel_type: "", status: "active" });
  const [saving, setSaving] = useState(false);

  async function load() {
    setRows(await apiGet("/api/v1/masterdata/vessels"));
  }

  useEffect(() => {
    load().catch(() => setRows([]));
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setMsg("");
    await apiPost("/api/v1/masterdata/vessels", { name, imo: imo || null, status: "active" });
    setName("");
    setImo("");
    setMsg(t("page.vessels.created", "Vessel created"));
    await load();
  }

  function openRow(r: Vessel) {
    setOpen(r);
    setEdit({
      name: r.name,
      imo: r.imo || "",
      flag: r.flag || "",
      vessel_type: r.vessel_type || "",
      status: r.status || "active",
    });
  }

  async function save() {
    if (!open) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/masterdata/vessels/${open.id}`, {
        name: edit.name,
        imo: edit.imo || null,
        flag: edit.flag || null,
        vessel_type: edit.vessel_type || null,
        status: edit.status,
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
      await apiDelete(`/api/v1/masterdata/vessels/${open.id}`);
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
          <h1 style={{ margin: 0 }}>{t("page.vessels.title", "Vessels")}</h1>
          <p className="page-sub">{t("page.vessels.sub", "Fleet master data. Open a row to edit or delete.")}</p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "Recycle bin")}
        </Link>
      </div>
      <form
        className="panel"
        onSubmit={(e) => onCreate(e).catch(() => setMsg(t("page.vessels.create_fail", "Create failed")))}
        style={{ marginBottom: "1rem" }}
      >
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("common.name", "Name")}
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            IMO
            <input value={imo} onChange={(e) => setImo(e.target.value)} />
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.vessels.add", "New vessel")}
          </button>
        </div>
        {msg ? <p style={{ marginBottom: 0 }}>{msg}</p> : null}
      </form>
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "Name")}</th>
              <th>IMO</th>
              <th>{t("common.type", "类型")}</th>
              <th>{t("page.vessels.flag", "Flag")}</th>
              <th>{t("common.status", "Status")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                <td>{r.name}</td>
                <td>{r.imo || "—"}</td>
                <td>{r.vessel_type || "—"}</td>
                <td>{r.flag || "—"}</td>
                <td>{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={t("page.vessels.edit", "Edit vessel")}
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
          IMO
          <input value={edit.imo} onChange={(e) => setEdit({ ...edit, imo: e.target.value })} />
        </label>
        <label>
          {t("common.type", "类型")}
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
