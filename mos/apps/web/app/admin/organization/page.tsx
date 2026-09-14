"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { API_BASE, apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Org = {
  name: string;
  code: string;
  profile_tier: string;
  default_locale: string;
  default_timezone: string;
  user_count: number;
  active_licenses: number;
  status: string;
};

export default function OrgPage() {
  const { t } = useI18n();
  const [org, setOrg] = useState<Org | null>(null);
  const [tier, setTier] = useState("M");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    apiGet("/api/v1/admin/organization")
      .then((o) => {
        setOrg(o);
        setTier(o.profile_tier);
      })
      .catch(() => setMsg(t("page.organization.admin_required", "Tenant admin role required")));
  }, [t]);

  async function save(e: FormEvent) {
    e.preventDefault();
    await fetch(`${API_BASE}/api/v1/admin/organization`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("voyageos_token")}`,
      },
      body: JSON.stringify({ profile_tier: tier }),
    });
    setMsg(t("page.organization.updated", "Organization updated — nav density follows tier (S/M/L/E)."));
    const o = await apiGet("/api/v1/admin/organization");
    setOrg(o);
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.organization.title", "Organization")}</h1>
      <p className="page-sub">{t("page.organization.sub", "Tenant profile and defaults.")}</p>
      {msg ? <p>{msg}</p> : null}
      {org ? (
        <form className="panel" onSubmit={(e) => save(e).catch(() => setMsg(t("common.failed", "Failed")))}>
          <div className="kv-grid">
            <div>
              <label>{t("common.name", "Name")}</label>
              <div className="kv">{org.name}</div>
            </div>
            <div>
              <label>{t("common.code", "Code")}</label>
              <div className="kv">{org.code}</div>
            </div>
            <div>
              <label>{t("common.users", "Users")}</label>
              <div className="kv">{org.user_count}</div>
            </div>
            <div>
              <label>{t("page.organization.licenses", "Active licenses")}</label>
              <div className="kv">{org.active_licenses}</div>
            </div>
            <div>
              <label>{t("page.organization.tier", "Profile tier")}</label>
              <select value={tier} onChange={(e) => setTier(e.target.value)}>
                <option value="S">S — Solo (compact nav)</option>
                <option value="M">M — Mid-size operator</option>
                <option value="L">L — Large fleet</option>
                <option value="E">E — Enterprise group</option>
              </select>
            </div>
          </div>
          <button className="btn btn-primary" type="submit" style={{ marginTop: "1rem" }}>
            {t("common.save", "Save")}
          </button>
        </form>
      ) : null}
    </AppShell>
  );
}
