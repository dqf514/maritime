"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { LookupSelect } from "@/components/LookupSelect";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Port = {
  id: string;
  name: string;
  unlocode: string | null;
  country: string | null;
  timezone: string;
};

export default function PortsPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Port[]>([]);
  const [name, setName] = useState("");
  const [unlocode, setUnlocode] = useState("");
  const [country, setCountry] = useState("CN");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<Port | null>(null);
  const [edit, setEdit] = useState({ name: "", unlocode: "", country: "", timezone: "UTC" });
  const [saving, setSaving] = useState(false);

  async function load() {
    setRows(await apiGet("/api/v1/masterdata/ports"));
  }

  useEffect(() => {
    load().catch(() => setRows([]));
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/masterdata/ports", {
      name,
      unlocode: unlocode || null,
      country: country || null,
      timezone: timezone || "UTC",
    });
    setName("");
    setUnlocode("");
    setMsg(t("page.ports.created", "Port created"));
    await load();
  }

  function openRow(r: Port) {
    setOpen(r);
    setEdit({
      name: r.name,
      unlocode: r.unlocode || "",
      country: r.country || "",
      timezone: r.timezone || "UTC",
    });
  }

  async function save() {
    if (!open) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/masterdata/ports/${open.id}`, {
        name: edit.name,
        unlocode: edit.unlocode || null,
        country: edit.country || null,
        timezone: edit.timezone || "UTC",
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
      await apiDelete(`/api/v1/masterdata/ports/${open.id}`);
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
          <h1 style={{ margin: 0 }}>{t("page.ports.title", "Ports")}</h1>
          <p className="page-sub">{t("page.ports.sub", "Port master data (UN/LOCODE). Open a row to edit.")}</p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "Recycle bin")}
        </Link>
      </div>
      <form
        className="panel"
        onSubmit={(e) => onCreate(e).catch(() => setMsg(t("page.ports.create_fail", "Create failed")))}
        style={{ marginBottom: "1rem" }}
      >
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("common.name", "Name")}
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            UN/LOCODE
            <input value={unlocode} onChange={(e) => setUnlocode(e.target.value)} />
          </label>
          <label>
            {t("page.ports.country", "Country")}
            <LookupSelect dataset="countries" value={country} onChange={setCountry} />
          </label>
          <label>
            {t("page.ports.timezone", "Time zone")}
            <LookupSelect dataset="timezones" value={timezone} onChange={setTimezone} allowEmpty={false} />
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.ports.add", "New port")}
          </button>
        </div>
        {msg ? <p style={{ marginBottom: 0 }}>{msg}</p> : null}
      </form>
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "Name")}</th>
              <th>UN/LOCODE</th>
              <th>{t("page.ports.country", "Country")}</th>
              <th>{t("page.ports.timezone", "Time zone")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                <td>{r.name}</td>
                <td>{r.unlocode || "—"}</td>
                <td>{r.country || "—"}</td>
                <td>{r.timezone}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={t("page.ports.edit", "Edit port")}
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
          UN/LOCODE
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
      </RecordModal>
    </AppShell>
  );
}
