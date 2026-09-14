"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

import { API_BASE as API } from "@/lib/api";

export default function TenantI18nPage() {
  const { t, term, reload } = useI18n();
  const [settings, setSettings] = useState<any>(null);
  const [terms, setTerms] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [editKey, setEditKey] = useState("");
  const [editLabel, setEditLabel] = useState("");

  async function load() {
    setSettings(await apiGet("/api/v1/admin/i18n/settings"));
    const data = await apiGet(`/api/v1/admin/i18n/terminology?q=${encodeURIComponent(q)}`);
    setTerms(data.items || []);
  }

  useEffect(() => {
    load().catch(() => setMsg(t("i18n.admin_required", "Tenant admin required")));
  }, []);

  async function saveSettings(e: FormEvent) {
    e.preventDefault();
    const res = await fetch(`${API}/api/v1/admin/i18n/settings`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("voyageos_token")}`,
      },
      body: JSON.stringify(settings),
    });
    if (!res.ok) throw new Error("fail");
    setMsg(t("common.saved", "Saved"));
    await reload();
    await load();
  }

  async function saveOverride(e: FormEvent) {
    e.preventDefault();
    const res = await fetch(`${API}/api/v1/admin/i18n/terminology/overrides`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("voyageos_token")}`,
      },
      body: JSON.stringify({
        term_key: editKey,
        locale: settings?.default_locale || "en",
        label: editLabel,
      }),
    });
    if (!res.ok) throw new Error("fail");
    setMsg(t("i18n.override_saved", "Override saved"));
    setEditKey("");
    setEditLabel("");
    await load();
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("i18n.page_title", "Languages & terminology")}</h1>
      <p className="page-sub">
        {t(
          "i18n.page_sub",
          "Tenant policy for default UI language and local overrides of maritime terms (e.g. company-preferred)",
        )}{" "}
        {term("term.tce", "TCE")} {t("i18n.page_sub_end", "wording).")}
      </p>
      {msg ? <p className="flash">{msg}</p> : null}

      {settings ? (
        <form className="panel" onSubmit={(e) => saveSettings(e).catch(() => setMsg(t("common.failed", "Failed")))}>
          <h2>{t("i18n.languages", "Languages")}</h2>
          <label>
            {t("i18n.default_locale", "Default locale")}
            <select
              value={settings.default_locale}
              onChange={(e) => setSettings({ ...settings, default_locale: e.target.value })}
            >
              {(settings.allowed_locales || ["en", "zh-CN"]).map((c: string) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={settings.allow_user_override}
              onChange={(e) => setSettings({ ...settings, allow_user_override: e.target.checked })}
            />
            {t("i18n.allow_user", "Allow users to switch language")}
          </label>
          <button className="btn btn-primary" type="submit">
            {t("common.save", "Save")}
          </button>
        </form>
      ) : null}

      <div className="panel">
        <h2>{t("i18n.terms", "Terminology")}</h2>
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("i18n.search", "Search terms")}
          />
          <button type="button" className="btn btn-ghost" onClick={() => load().catch(() => undefined)}>
            {t("common.search", "Search")}
          </button>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("common.key", "Key")}</th>
              <th>{t("common.label", "Label")}</th>
              <th>{t("common.category", "Category")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {terms.slice(0, 40).map((row) => (
              <tr key={row.key}>
                <td>
                  <code>{row.key}</code>
                </td>
                <td>
                  {row.label}
                  {row.overridden ? <span className="pill valid">{t("common.override", "Override")}</span> : null}
                </td>
                <td>{row.category}</td>
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setEditKey(row.key);
                      setEditLabel(row.label);
                    }}
                  >
                    {t("common.override", "Override")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {editKey ? (
          <form onSubmit={(e) => saveOverride(e).catch(() => setMsg(t("i18n.override_fail", "Override failed")))} style={{ marginTop: "1rem" }}>
            <h3>
              {t("common.override", "Override")} <code>{editKey}</code>
            </h3>
            <input value={editLabel} onChange={(e) => setEditLabel(e.target.value)} required />
            <button className="btn btn-primary" type="submit">
              {t("common.save", "Save")}
            </button>
          </form>
        ) : null}
      </div>
    </AppShell>
  );
}
