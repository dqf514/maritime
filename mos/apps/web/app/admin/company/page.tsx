"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { apiGet, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

export default function CompanyBrandPage() {
  const { t } = useI18n();
  const toast = useToast();
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

  useEffect(() => {
    apiGet("/api/v1/admin/company-profile")
      .then((p) => setForm((f) => ({ ...f, ...p })))
      .catch(() => toast.success(t("page.company.admin_required", "Tenant admin required")));
  }, [t]);

  async function save(e: FormEvent) {
    e.preventDefault();
    await apiPut("/api/v1/admin/company-profile", form);
    toast.success(t("page.company.saved", "Company brand saved — appears in Shell & documents."));
  }

  return (
    <AppShell>
      <PageHeader
        title={t("page.company.title", "Company & brand")}
        subtitle={t("page.company.sub", "Tenant company profile shown in shell and documents.")}
      />
      <form className="panel" onSubmit={(e) => save(e).catch(() => toast.success(t("common.failed", "Failed")))}>
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
