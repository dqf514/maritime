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

type OfficeCfg = {
  override_enabled: boolean;
  client_id: string | null;
  client_secret_masked: string | null;
  ms_tenant: string;
  effective_mode: string;
  redirect_uri: string;
  has_secret: boolean;
};

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
  const [ocfg, setOcfg] = useState<OfficeCfg | null>(null);
  const [oform, setOform] = useState({ override_enabled: false, client_id: "", client_secret: "", ms_tenant: "" });
  const [oclear, setOclear] = useState(false);
  const [otest, setOtest] = useState<{ ok: boolean; text: string } | null>(null);
  const [otestBusy, setOtestBusy] = useState(false);

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
      const oc: OfficeCfg = await apiGet(`/api/v1/platform/tenants/${row.id}/office-config`);
      setOcfg(oc);
      setOform({
        override_enabled: oc.override_enabled,
        client_id: oc.client_id || "",
        client_secret: "",
        ms_tenant: oc.ms_tenant || "",
      });
      setOclear(false);
      setOtest(null);
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

  function officeModeBadge(mode?: string) {
    const map: Record<string, [string, string]> = {
      tenant: ["badge badge-pass", t("platform.officecfg.mode_tenant", "租户专属")],
      global: ["badge badge-info", t("platform.officecfg.mode_global", "平台全局")],
      stub: ["badge badge-warn", t("platform.officecfg.mode_stub", "演示模式")],
      disabled: ["badge", t("platform.officecfg.mode_disabled", "未启用")],
    };
    const [cls, label] = map[mode || ""] || ["badge", mode || "—"];
    return <span className={cls}>{label}</span>;
  }

  async function copyRedirectUri() {
    if (!ocfg) return;
    try {
      await navigator.clipboard.writeText(ocfg.redirect_uri);
      setMsg(t("platform.officecfg.copied", "已复制"));
    } catch {
      window.prompt(t("platform.officecfg.redirect_uri", "回调地址（需登记到 Entra 应用）"), ocfg.redirect_uri);
    }
  }

  async function saveOffice() {
    if (!selected) return;
    const body: Record<string, unknown> = {
      override_enabled: oform.override_enabled,
      client_id: oform.client_id,
      ms_tenant: oform.ms_tenant,
    };
    if (oclear) body.client_secret = null;
    else if (oform.client_secret) body.client_secret = oform.client_secret;
    const oc: OfficeCfg = await apiPut(`/api/v1/platform/tenants/${selected.id}/office-config`, body);
    setOcfg(oc);
    setOform({ ...oform, client_secret: "" });
    setOclear(false);
    setMsg(t("platform.officecfg.saved", "Microsoft 365 配置已保存"));
  }

  async function testOffice() {
    if (!selected) return;
    setOtestBusy(true);
    setOtest(null);
    try {
      const res = await apiPost(`/api/v1/platform/tenants/${selected.id}/office-config/test`);
      setOtest(
        res.ok
          ? { ok: true, text: t("platform.officecfg.test_ok", "连接成功（{ms} ms）", { ms: res.latency_ms }) }
          : { ok: false, text: t("platform.officecfg.test_fail", "测试失败：{msg}", { msg: res.message }) },
      );
    } catch (e) {
      setOtest({ ok: false, text: String((e as Error)?.message || e) });
    } finally {
      setOtestBusy(false);
    }
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

          <h3 style={{ marginTop: "1.5rem" }}>{t("platform.officecfg.title", "Microsoft 365 集成")}</h3>
          <p className="muted">
            {t("platform.officecfg.sub", "为租户单独配置 Entra 应用凭据；关闭覆盖时回落到平台全局环境变量配置。")}
          </p>
          {ocfg ? (
            <div>
              <p style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                {t("platform.officecfg.mode", "当前生效模式")}: {officeModeBadge(ocfg.effective_mode)}
              </p>
              <p style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
                {t("platform.officecfg.redirect_uri", "回调地址（需登记到 Entra 应用）")}:{" "}
                <code>{ocfg.redirect_uri}</code>
                <button className="btn btn-ghost" type="button" onClick={() => copyRedirectUri().catch(() => undefined)}>
                  {t("platform.officecfg.copy", "复制")}
                </button>
              </p>
              <div
                className="form-grid"
                style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: "0.75rem" }}
              >
                <label style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={oform.override_enabled}
                    onChange={(e) => setOform({ ...oform, override_enabled: e.target.checked })}
                  />
                  {t("platform.officecfg.override", "启用租户专属凭据")}
                </label>
                <label>
                  {t("platform.officecfg.client_id", "客户端 ID（Client ID）")}
                  <input
                    value={oform.client_id}
                    onChange={(e) => setOform({ ...oform, client_id: e.target.value })}
                    placeholder="00000000-0000-0000-0000-000000000000"
                  />
                </label>
                <label>
                  {t("platform.officecfg.client_secret", "客户端密钥（Client Secret）")}
                  <input
                    type="password"
                    value={oform.client_secret}
                    onChange={(e) => {
                      setOform({ ...oform, client_secret: e.target.value });
                      if (e.target.value) setOclear(false);
                    }}
                    placeholder={
                      ocfg.has_secret
                        ? `${ocfg.client_secret_masked || "••••"} · ${t("platform.officecfg.secret_keep", "留空表示不修改当前密钥")}`
                        : t("platform.officecfg.secret_state_unset", "未配置密钥")
                    }
                  />
                </label>
                <label>
                  {t("platform.officecfg.tenant", "租户（authority，默认 common）")}
                  <input
                    value={oform.ms_tenant}
                    onChange={(e) => setOform({ ...oform, ms_tenant: e.target.value })}
                    placeholder="common"
                  />
                </label>
              </div>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.85rem", alignItems: "center" }}>
                <button
                  className="btn btn-primary"
                  type="button"
                  onClick={() => saveOffice().catch(() => setMsg(t("common.failed", "保存失败")))}
                >
                  {t("platform.officecfg.save", "保存 Microsoft 365 配置")}
                </button>
                <button className="btn" type="button" disabled={otestBusy} onClick={() => testOffice()}>
                  {otestBusy ? t("platform.officecfg.testing", "测试中…") : t("platform.officecfg.test", "测试连接")}
                </button>
                {ocfg.has_secret ? (
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => {
                      setOclear(true);
                      setOform({ ...oform, client_secret: "" });
                    }}
                  >
                    {t("platform.officecfg.clear_secret", "清除密钥")}
                  </button>
                ) : null}
                {oclear ? <span className="badge badge-warn">{t("platform.officecfg.clear_secret", "清除密钥")}…</span> : null}
              </div>
              {otest ? (
                <p className="flash" style={{ color: otest.ok ? "var(--ok)" : "var(--danger)" }}>
                  {otest.text}
                </p>
              ) : null}
            </div>
          ) : null}
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
