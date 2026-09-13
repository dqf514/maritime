"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function PermissionsPage() {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<Array<{ code: string; name: string; module: string }>>([]);
  const [matrix, setMatrix] = useState<Array<{ role_code: string; feature_code: string; allowed: boolean }>>([]);
  const [roles, setRoles] = useState<Array<{ code: string }>>([]);
  const [msg, setMsg] = useState("");

  async function load() {
    const [c, m, r] = await Promise.all([
      apiGet("/api/v1/admin/features/catalog"),
      apiGet("/api/v1/admin/features/matrix"),
      apiGet("/api/v1/admin/roles"),
    ]);
    setCatalog(c);
    setMatrix(m);
    setRoles(r);
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.perm.admin_required", "Tenant admin required")));
  }, [t]);

  async function toggle(role_code: string, feature_code: string, allowed: boolean) {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000"}/api/v1/admin/features`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("voyageos_token")}`,
      },
      body: JSON.stringify({ role_code, feature_code, allowed }),
    });
    if (!res.ok) throw new Error("failed");
    setMsg(`${role_code} · ${feature_code} = ${allowed}`);
    await load();
  }

  const roleCodes = roles.map((r) => r.code).filter((c) => c !== "platform_admin");

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.perm.title", "Feature permissions")}</h1>
      <p className="page-sub">{t("page.perm.sub", "Fine-grained capability matrix by role.")}</p>
      {msg ? <p>{msg}</p> : null}
      <div className="panel" style={{ overflowX: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.perm.feature", "Feature")}</th>
              {roleCodes.map((r) => (
                <th key={r}>{r}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {catalog.map((f) => (
              <tr key={f.code}>
                <td>
                  <b>{f.name}</b>
                  <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
                    {f.code} · {f.module}
                  </div>
                </td>
                {roleCodes.map((role) => {
                  const hit = matrix.find((m) => m.role_code === role && m.feature_code === f.code);
                  const allowed = hit ? hit.allowed : role === "tenant_admin";
                  return (
                    <td key={role}>
                      <input
                        type="checkbox"
                        checked={allowed}
                        onChange={(e) => toggle(role, f.code, e.target.checked).catch(() => setMsg(t("page.perm.update_fail", "Update failed")))}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
