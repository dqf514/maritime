"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { API_BASE, apiGet } from "@/lib/api";
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
    load().catch(() => setMsg(t("page.perm.admin_required", "需要租户管理员")));
  }, [t]);

  async function toggle(role_code: string, feature_code: string, allowed: boolean) {
    const res = await fetch(`${API_BASE}/api/v1/admin/features`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${localStorage.getItem("voyageos_token")}`,
      },
      body: JSON.stringify({ role_code, feature_code, allowed }),
    });
    if (!res.ok) throw new Error("failed");
    setMsg(`${role_code} · ${feature_code} = ${allowed ? t("page.perm.allow", "允许") : t("page.perm.deny", "拒绝")}`);
    await load();
  }

  const roleCodes = roles.map((r) => r.code).filter((c) => c !== "platform_admin");

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.perm.title", "功能权限")}</h1>
      <p className="page-sub">
        {t(
          "page.perm.sub",
          "按角色精细控制能力。未配置的单元格默认允许（继承角色）；取消勾选会写入拒绝并在业务 API 生效。租户管理员始终放行。",
        )}
      </p>
      {msg ? <p>{msg}</p> : null}
      <div className="panel" style={{ overflowX: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.perm.feature", "功能")}</th>
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
                  const allowed = role === "tenant_admin" ? true : hit ? hit.allowed : true;
                  return (
                    <td key={role}>
                      <input
                        type="checkbox"
                        checked={allowed}
                        disabled={role === "tenant_admin"}
                        onChange={(e) =>
                          toggle(role, f.code, e.target.checked).catch(() =>
                            setMsg(t("page.perm.update_fail", "更新失败")),
                          )
                        }
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
