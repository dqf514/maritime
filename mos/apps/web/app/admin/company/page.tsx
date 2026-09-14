"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { API_BASE, apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function CompanyBrandPage() {
  const { t } = useI18n();
  const [form, setForm] = useState({
    legal_name: "",
    display_name: "",
    logo_url: "",
    website: "",
    tax_no: "",
    address: "",
    phone: "",
    brand_primary: "#1A9B96",
  });
  const [msg, setMsg] = useState("");

  useEffect(() => {
    apiGet("/api/v1/admin/company-profile")
      .then((p) => setForm((f) => ({ ...f, ...p })))
      .catch(() => setMsg(t("page.company.admin_required", "Tenant admin required")));
  }, [t]);

  async function save(e: FormEvent) {
    e.preventDefault();
    const res = await fetch(`${API_BASE}/api/v1/admin/company-profile`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("voyageos_token")}`,
      },
      body: JSON.stringify(form),
    });
    if (!res.ok) throw new Error("save failed");
    setMsg(t("page.company.saved", "Company brand saved — appears in Shell & documents."));
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.company.title", "Company & brand")}</h1>
      <p className="page-sub">{t("page.company.sub", "Tenant company profile shown in shell and documents.")}</p>
      {msg ? <p>{msg}</p> : null}
      <form className="panel" onSubmit={(e) => save(e).catch(() => setMsg(t("common.failed", "Failed")))}>
        <div className="kv-grid">
          {Object.entries(form).map(([k, v]) => (
            <label key={k}>
              {k.replaceAll("_", " ")}
              <input value={v || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
            </label>
          ))}
        </div>
        <button className="btn btn-primary" type="submit" style={{ marginTop: "1rem" }}>
          {t("page.company.save", "Save profile")}
        </button>
      </form>
    </AppShell>
  );
}
