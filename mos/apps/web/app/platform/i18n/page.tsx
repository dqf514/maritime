"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function PlatformI18nPage() {
  const { t } = useI18n();
  const [overview, setOverview] = useState<any>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [terms, setTerms] = useState<any[]>([]);
  const [locale, setLocale] = useState("zh-CN");
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [editKey, setEditKey] = useState("");
  const [editText, setEditText] = useState("");

  async function load() {
    setOverview(await apiGet("/api/v1/platform/i18n/overview"));
    setMessages(await apiGet(`/api/v1/platform/i18n/messages?locale=${locale}`));
    const data = await apiGet(`/api/v1/platform/i18n/terminology?q=${encodeURIComponent(q)}`);
    setTerms(data.items || []);
  }

  useEffect(() => {
    load().catch(() => setMsg(t("i18n.platform_admin_required", "Platform admin required")));
  }, [locale]);

  async function saveMessage(e: FormEvent) {
    e.preventDefault();
    await apiPut("/api/v1/platform/i18n/messages", { msg_key: editKey, locale, text: editText, namespace: "app" });
    setMsg(t("i18n.message_updated", "Message updated"));
    setEditKey("");
    await load();
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("i18n.platform_title", "Platform languages & terminology")}</h1>
      <p className="page-sub">
        {t("i18n.platform_sub", "Global language packs (en / zh-CN) and maritime terminology catalog. Tenants may override labels; secrets stay out of this plane.")}
      </p>
      {msg ? <p className="flash">{msg}</p> : null}

      <div className="kpi-row">
        <div className="kpi-card">
          <span>{t("i18n.ui_keys", "UI keys")}</span>
          <strong>{overview?.ui_message_keys ?? "—"}</strong>
        </div>
        <div className="kpi-card">
          <span>{t("i18n.catalog_count", "Catalog terms")}</span>
          <strong>
            {overview?.terminology_terms ?? "—"}
            <small> / {overview?.target_terminology ?? 500}</small>
          </strong>
        </div>
        <div className="kpi-card">
          <span>{t("i18n.languages", "Languages")}</span>
          <strong>{overview?.languages?.length ?? "—"}</strong>
        </div>
      </div>

      <div className="panel">
        <h2>{t("i18n.languages", "Languages")}</h2>
        <ul className="compact-list">
          {(overview?.languages || []).map((l: any) => (
            <li key={l.code}>
              <strong>{l.native_name}</strong> ({l.code}) {l.enabled ? `· ${t("common.enabled", "enabled")}` : `· ${t("common.disabled", "disabled")}`}
              {l.is_default ? ` · ${t("common.default", "default")}` : ""}
            </li>
          ))}
        </ul>
      </div>

      <div className="panel">
        <h2>{t("i18n.ui_messages", "UI messages")}</h2>
        <label>
          {t("i18n.locale", "Locale")}
          <select value={locale} onChange={(e) => setLocale(e.target.value)}>
            <option value="en">en</option>
            <option value="zh-CN">zh-CN</option>
          </select>
        </label>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("common.key", "Key")}</th>
              <th>{t("i18n.text", "Text")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {messages.slice(0, 50).map((m) => (
              <tr key={m.key}>
                <td>
                  <code>{m.key}</code>
                </td>
                <td>{m.text}</td>
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setEditKey(m.key);
                      setEditText(m.text);
                    }}
                  >
                    {t("common.edit", "Edit")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {editKey ? (
          <form onSubmit={(e) => saveMessage(e).catch(() => setMsg(t("common.failed", "Failed")))}>
            <h3>
              {t("common.edit", "Edit")} <code>{editKey}</code> ({locale})
            </h3>
            <input value={editText} onChange={(e) => setEditText(e.target.value)} style={{ width: "100%" }} />
            <button className="btn btn-primary" type="submit">
              {t("common.save", "Save")}
            </button>
          </form>
        ) : null}
      </div>

      <div className="panel">
        <h2>{t("i18n.terms", "Terminology")}</h2>
        <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("i18n.search", "Search terms")} />
          <button type="button" className="btn btn-ghost" onClick={() => load().catch(() => undefined)}>
            {t("common.search", "Search")}
          </button>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("common.key", "Key")}</th>
              <th>EN</th>
              <th>zh-CN</th>
              <th>{t("common.category", "Category")}</th>
            </tr>
          </thead>
          <tbody>
            {terms.slice(0, 60).map((row) => (
              <tr key={row.term_key}>
                <td>
                  <code>{row.term_key}</code>
                </td>
                <td>{row.en}</td>
                <td>{row.zh_cn}</td>
                <td>{row.category}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
