"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { LookupSelect } from "@/components/LookupSelect";
import { apiGet, apiPost, apiPut, generateTempPassword } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Tenant = {
  id: string;
  name: string;
  code: string;
  status: string;
  profile_tier: string;
  default_locale?: string;
  default_timezone?: string;
  user_count: number;
  license_count: number;
};

type LicRow = { module_code: string; name: string; is_core: boolean; status: string };

export default function PlatformTenantsPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Tenant[]>([]);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [msg, setMsg] = useState("");
  const [selected, setSelected] = useState<Tenant | null>(null);
  const [edit, setEdit] = useState({ name: "", profile_tier: "M", default_locale: "en", default_timezone: "Asia/Shanghai" });
  const [licenses, setLicenses] = useState<LicRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [initialPw, setInitialPw] = useState("");
  const [confirm, setConfirm] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  async function load() {
    setRows(await apiGet("/api/v1/platform/tenants"));
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.tenants.admin_required", "需要平台管理员（租户 sys）")));
  }, [t]);

  async function openTenant(row: Tenant) {
    setBusy(true);
    setMsg("");
    try {
      const detail = await apiGet(`/api/v1/platform/tenants/${row.id}`);
      setSelected(detail);
      setEdit({
        name: detail.name,
        profile_tier: detail.profile_tier || "M",
        default_locale: detail.default_locale || "en",
        default_timezone: detail.default_timezone || "Asia/Shanghai",
      });
      setLicenses(await apiGet(`/api/v1/platform/tenants/${row.id}/licenses`));
    } catch {
      setMsg(t("common.failed", "加载失败"));
    } finally {
      setBusy(false);
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    const adminPassword = generateTempPassword();
    const res = await apiPost("/api/v1/platform/tenants", {
      name,
      code,
      profile_tier: "M",
      admin_email: adminEmail,
      admin_name: "Tenant Admin",
      admin_password: adminPassword,
    });
    setInitialPw(adminPassword);
    setMsg(
      t("page.tenants.created", "已创建租户 {code}；管理员 {email}。初始密码已生成，请通过安全渠道传达。", {
        code: res.code,
        email: res.admin_email,
      }),
    );
    setName("");
    setCode("");
    setAdminEmail("");
    await load();
  }

  async function copyInitialPw() {
    try {
      await navigator.clipboard.writeText(initialPw);
    } catch {
      window.prompt(t("page.tenants.copy_manual", "请手动复制初始密码："), initialPw);
    }
    setInitialPw("");
  }

  async function setStatus(id: string, status: string) {
    if (status === "suspended") {
      setConfirm({
        message: t("page.tenants.confirm_suspend", "暂停租户后，该租户全部用户将立即无法登录（数据保留）。确认暂停？"),
        danger: true,
        action: () => applyStatus(id, status).catch(() => setMsg(t("common.failed", "失败"))),
      });
      return;
    }
    await applyStatus(id, status);
  }

  async function applyStatus(id: string, status: string) {
    await apiPost(`/api/v1/platform/tenants/${id}/status`, { status });
    await load();
    if (selected?.id === id) await openTenant({ ...selected, status });
  }

  async function saveEdit(e: FormEvent) {
    e.preventDefault();
    if (!selected) return;
    await apiPut(`/api/v1/platform/tenants/${selected.id}`, edit);
    setMsg(t("page.tenants.saved", "租户资料已保存"));
    await load();
    await openTenant(selected);
  }

  async function toggleLicense(mod: LicRow) {
    if (!selected || mod.is_core) return;
    const next = mod.status === "active" ? "inactive" : "active";
    if (next === "inactive") {
      setConfirm({
        message: t(
          "page.tenants.confirm_disable_mod",
          "停用模块 {mod} 后，该租户用户将立即失去此模块的访问入口。确认停用？",
          { mod: mod.module_code },
        ),
        danger: true,
        action: () => applyLicense(mod, next).catch(() => setMsg(t("common.failed", "失败"))),
      });
      return;
    }
    await applyLicense(mod, next);
  }

  async function applyLicense(mod: LicRow, next: string) {
    if (!selected) return;
    await apiPost(`/api/v1/platform/tenants/${selected.id}/licenses`, {
      module_code: mod.module_code,
      status: next,
    });
    setLicenses(await apiGet(`/api/v1/platform/tenants/${selected.id}/licenses`));
    await load();
  }

  return (
    <AppShell>
      <h1 style={{ marginTop: 0 }}>{t("page.tenants.title", "租户与模块许可证")}</h1>
      <p className="page-sub">
        {t(
          "page.tenants.sub",
          "开通 / 暂停租户，编辑档位与时区，并按模块开关许可证。点选表格行进入编辑。",
        )}
      </p>
      {msg ? <p className="flash">{msg}</p> : null}
      {initialPw ? (
        <p className="flash">
          {t("page.tenants.pw_ready", "初始密码已生成（仅此一次，复制后即不再显示）。")}{" "}
          <button type="button" className="btn btn-ghost" onClick={() => copyInitialPw().catch(() => setInitialPw(""))}>
            {t("page.tenants.copy_pw", "复制初始密码")}
          </button>
        </p>
      ) : null}

      <form className="panel" onSubmit={(e) => create(e).catch(() => setMsg(t("page.tenants.create_fail", "创建失败")))}>
        <h2 style={{ marginTop: 0 }}>{t("page.tenants.provision", "开通租户")}</h2>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("common.name", "名称")}
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <label>
            {t("common.code", "代码")}
            <input value={code} onChange={(e) => setCode(e.target.value)} required />
          </label>
          <label>
            {t("page.tenants.admin_email", "管理员邮箱")}
            <input type="email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} required />
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.tenants.provision", "开通租户")}
          </button>
        </div>
      </form>

      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "代码")}</th>
              <th>{t("common.name", "名称")}</th>
              <th>{t("common.tier", "档位")}</th>
              <th>{t("common.users", "用户")}</th>
              <th>{t("page.tenants.licenses", "许可证")}</th>
              <th>{t("common.status", "状态")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                style={{ cursor: "pointer", background: selected?.id === row.id ? "rgba(26,155,150,0.08)" : undefined }}
                onClick={() => openTenant(row).catch(() => undefined)}
              >
                <td>{row.code}</td>
                <td>{row.name}</td>
                <td>{row.profile_tier}</td>
                <td>{row.user_count}</td>
                <td>{row.license_count}</td>
                <td>
                  <span className={row.status === "active" ? "badge badge-pass" : "badge badge-fail"}>{row.status}</span>
                </td>
                <td onClick={(e) => e.stopPropagation()}>
                  {row.status === "active" ? (
                    <button className="btn" type="button" onClick={() => setStatus(row.id, "suspended").catch(() => setMsg(t("common.failed", "失败")))}>
                      {t("common.suspend", "暂停")}
                    </button>
                  ) : (
                    <button className="btn btn-primary" type="button" onClick={() => setStatus(row.id, "active").catch(() => setMsg(t("common.failed", "失败")))}>
                      {t("common.activate", "启用")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected ? (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>
            {t("page.tenants.edit", "编辑租户")} · {selected.code}
            {busy ? <span className="muted"> …</span> : null}
          </h2>
          <form onSubmit={(e) => saveEdit(e).catch(() => setMsg(t("common.failed", "保存失败")))}>
            <div className="form-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(180px,1fr))", gap: "0.75rem" }}>
              <label>
                {t("common.name", "名称")}
                <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
              </label>
              <label>
                {t("common.tier", "档位")}
                <select value={edit.profile_tier} onChange={(e) => setEdit({ ...edit, profile_tier: e.target.value })}>
                  {["S", "M", "L", "XL"].map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("page.tenants.locale", "默认语言")}
                <select value={edit.default_locale} onChange={(e) => setEdit({ ...edit, default_locale: e.target.value })}>
                  <option value="en">en</option>
                  <option value="zh-CN">zh-CN</option>
                </select>
              </label>
              <label>
                {t("page.tenants.tz", "默认时区")}
                <LookupSelect
                  dataset="timezones"
                  value={edit.default_timezone}
                  onChange={(v) => setEdit({ ...edit, default_timezone: v })}
                  allowEmpty={false}
                />
              </label>
            </div>
            <button className="btn btn-primary" type="submit" style={{ marginTop: "0.85rem" }}>
              {t("common.save", "保存资料")}
            </button>
          </form>

          <h3 style={{ marginTop: "1.5rem" }}>{t("page.tenants.license_matrix", "模块许可证")}</h3>
          <p className="muted">{t("page.tenants.license_hint", "核心模块始终开通；业务模块可在此启停。")}</p>
          <table className="table">
            <thead>
              <tr>
                <th>{t("page.licenses.module", "模块")}</th>
                <th>{t("common.name", "名称")}</th>
                <th>{t("page.licenses.core", "核心")}</th>
                <th>{t("common.status", "状态")}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {licenses.map((lic) => (
                <tr key={lic.module_code}>
                  <td>
                    <code>{lic.module_code}</code>
                  </td>
                  <td>{lic.name}</td>
                  <td>{lic.is_core ? t("page.licenses.yes", "是") : t("page.licenses.no", "否")}</td>
                  <td>
                    <span className={lic.status === "active" ? "badge badge-pass" : "badge badge-warn"}>{lic.status}</span>
                  </td>
                  <td>
                    {lic.is_core ? (
                      <span className="muted">—</span>
                    ) : (
                      <button className="btn" type="button" onClick={() => toggleLicense(lic).catch(() => setMsg(t("common.failed", "失败")))}>
                        {lic.status === "active" ? t("page.tenants.disable_mod", "停用") : t("page.tenants.enable_mod", "启用")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">{t("page.tenants.pick", "请选择上方租户行，以编辑资料与许可证。")}</p>
      )}
      <ConfirmDialog
        open={Boolean(confirm)}
        title={t("common.confirm", "确认操作")}
        message={confirm?.message || ""}
        danger={confirm?.danger}
        onConfirm={() => {
          const fn = confirm?.action;
          setConfirm(null);
          fn?.();
        }}
        onCancel={() => setConfirm(null)}
      />
    </AppShell>
  );
}
