"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { RecordModal } from "@/components/RecordModal";
import { LookupSelect } from "@/components/LookupSelect";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiGet, apiPost, apiPut, generateTempPassword } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

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

type BackupRow = {
  id: string;
  status: string;
  trigger: string;
  storage_path: string | null;
  created_at: string | null;
  total_rows?: number;
};

function PlatformTenantsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const { query, setQuery } = useListQuery();
  const filterStatus = query.status ?? "";
  const filterQ = query.q ?? "";
  const [rows, setRows] = useState<Tenant[]>([]);
  const [creating, setCreating] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [selected, setSelected] = useState<Tenant | null>(null);
  const [editOpen, setEditOpen] = useState(false);
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
  // 租户数据运维（一键备份 / 恢复 / 清理）
  const [backups, setBackups] = useState<BackupRow[]>([]);
  const [dbBusy, setDbBusy] = useState(false);
  const [dbMsg, setDbMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [purgeOpen, setPurgeOpen] = useState(false);
  const [purgeConfirmText, setPurgeConfirmText] = useState("");
  const [purgeIncludeUsers, setPurgeIncludeUsers] = useState(false);

  async function load() {
    setRows(await apiGet("/api/v1/platform/tenants"));
  }

  useEffect(() => {
    load().catch(() => toast.error(t("page.tenants.admin_required", "需要平台管理员（租户 sys）")));
  }, [t]);

  async function openTenant(row: Tenant) {
    setBusy(true);
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
      // 数据运维：备份记录
      setDbMsg(null);
      setPurgeOpen(false);
      setPurgeConfirmText("");
      setPurgeIncludeUsers(false);
      setBackups(await apiGet(`/api/v1/platform/tenants/${row.id}/backups`).catch(() => []));
    } catch {
      toast.error(t("common.failed", "加载失败"));
    } finally {
      setBusy(false);
    }
  }

  async function tenantBackup() {
    if (!selected) return;
    setDbBusy(true);
    setDbMsg(null);
    try {
      const res: BackupRow & { total_rows?: number } = await apiPost(`/api/v1/platform/tenants/${selected.id}/backup`);
      setBackups(await apiGet(`/api/v1/platform/tenants/${selected.id}/backups`));
      setDbMsg({
        ok: true,
        text: t("page.tenants.backup_done", "备份完成：{n} 行 → {p}", { n: res.total_rows ?? 0, p: res.storage_path || "" }),
      });
    } catch {
      setDbMsg({ ok: false, text: t("page.tenants.backup_failed", "备份失败") });
    } finally {
      setDbBusy(false);
    }
  }

  async function tenantRestore(row: BackupRow) {
    if (!selected || !row.storage_path) return;
    setDbBusy(true);
    setDbMsg(null);
    try {
      const res = await apiPost(`/api/v1/platform/tenants/${selected.id}/restore`, { storage_path: row.storage_path });
      setDbMsg({
        ok: true,
        text: t("page.tenants.restore_done", "恢复完成：新插入 {n} 行（已存在主键跳过）", { n: res.inserted_total ?? 0 }),
      });
    } catch {
      setDbMsg({ ok: false, text: t("page.tenants.restore_failed", "恢复失败") });
    } finally {
      setDbBusy(false);
    }
  }

  async function tenantPurge() {
    if (!selected) return;
    setDbBusy(true);
    setDbMsg(null);
    try {
      const res = await apiPost(`/api/v1/platform/tenants/${selected.id}/purge`, {
        confirm: purgeConfirmText,
        backup_first: true,
        include_users: purgeIncludeUsers,
      });
      setPurgeOpen(false);
      setPurgeConfirmText("");
      setBackups(await apiGet(`/api/v1/platform/tenants/${selected.id}/backups`));
      setDbMsg({
        ok: true,
        text: t("page.tenants.purge_done", "已清理 {n} 行业务数据（清理前已自动备份）", { n: res.deleted_total ?? 0 }),
      });
    } catch {
      setDbMsg({ ok: false, text: t("page.tenants.purge_failed", "清理失败（确认代码需与租户代码一致）") });
    } finally {
      setDbBusy(false);
    }
  }

  function openCreate() {
    setName("");
    setCode("");
    setAdminEmail("");
    setCreating(true);
  }

  useListHotkeys(openCreate);

  async function create(e: FormEvent) {
    e.preventDefault();
    setCreateSaving(true);
    try {
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
      toast.success(
        t("page.tenants.created", "已创建租户 {code}；管理员 {email}。初始密码已生成，请通过安全渠道传达。", {
          code: res.code,
          email: res.admin_email,
        }),
      );
      setCreating(false);
      await load();
    } catch (err) {
      toast.error(t("page.tenants.create_fail", "创建失败: {err}", { err: String(err) }));
    } finally {
      setCreateSaving(false);
    }
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
        action: () => applyStatus(id, status).catch(() => toast.error(t("common.failed", "失败"))),
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
    try {
      await apiPut(`/api/v1/platform/tenants/${selected.id}`, edit);
      toast.success(t("page.tenants.saved", "租户资料已保存"));
      setEditOpen(false);
      await load();
      await openTenant(selected);
    } catch (err) {
      toast.error(t("page.tenants.save_fail", "保存失败: {err}", { err: String(err) }));
    }
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
        action: () => applyLicense(mod, next).catch(() => toast.error(t("common.failed", "失败"))),
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
      toast.success(t("platform.officecfg.copied", "已复制"));
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
    toast.success(t("platform.officecfg.saved", "Microsoft 365 配置已保存"));
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

  const filtered = rows.filter((r) => {
    if (filterStatus && r.status !== filterStatus) return false;
    if (filterQ) {
      const needle = filterQ.toLowerCase();
      if (!r.code.toLowerCase().includes(needle) && !r.name.toLowerCase().includes(needle)) return false;
    }
    return true;
  });

  const tenantColumns: ColumnDef<Tenant>[] = [
    {
      key: "code",
      title: t("common.code", "代码"),
      width: 110,
      value: (r) => r.code,
      render: (v, r) => (
        <button type="button" className="linklike" onClick={(e) => { e.stopPropagation(); openTenant(r).catch(() => undefined); }}>
          {String(v)}
        </button>
      ),
    },
    { key: "name", title: t("common.name", "名称"), minWidth: 150, value: (r) => r.name },
    { key: "profile_tier", title: t("common.tier", "档位"), width: 80, value: (r) => r.profile_tier },
    { key: "user_count", title: t("common.users", "用户"), width: 80, align: "right", value: (r) => r.user_count },
    { key: "license_count", title: t("page.tenants.licenses", "许可证"), width: 90, align: "right", value: (r) => r.license_count },
    {
      key: "status",
      title: t("common.status", "状态"),
      width: 100,
      value: (r) => r.status,
      render: (v) => (
        <span className={v === "active" ? "badge badge-pass" : "badge badge-fail"}>{String(v)}</span>
      ),
    },
    {
      key: "_actions",
      title: "",
      width: 100,
      align: "right",
      render: (_v, r) =>
        r.status === "active" ? (
          <button
            className="btn"
            type="button"
            onClick={(e) => { e.stopPropagation(); setStatus(r.id, "suspended").catch(() => toast.error(t("common.failed", "失败"))); }}
          >
            {t("common.suspend", "暂停")}
          </button>
        ) : (
          <button
            className="btn btn-primary"
            type="button"
            onClick={(e) => { e.stopPropagation(); setStatus(r.id, "active").catch(() => toast.error(t("common.failed", "失败"))); }}
          >
            {t("common.activate", "启用")}
          </button>
        ),
    },
  ];

  const licColumns: ColumnDef<LicRow>[] = [
    {
      key: "module_code",
      title: t("page.licenses.module", "模块"),
      width: 140,
      value: (r) => r.module_code,
      render: (v) => <code>{String(v)}</code>,
    },
    { key: "name", title: t("common.name", "名称"), minWidth: 150, value: (r) => r.name },
    {
      key: "is_core",
      title: t("page.licenses.core", "核心"),
      width: 80,
      value: (r) => r.is_core,
      render: (v) => (v ? t("page.licenses.yes", "是") : t("page.licenses.no", "否")),
    },
    {
      key: "status",
      title: t("common.status", "状态"),
      width: 100,
      value: (r) => r.status,
      render: (v) => (
        <span className={v === "active" ? "badge badge-pass" : "badge badge-warn"}>{String(v)}</span>
      ),
    },
    {
      key: "_actions",
      title: "",
      width: 100,
      align: "right",
      render: (_v, lic) =>
        lic.is_core ? (
          <span className="muted">—</span>
        ) : (
          <button
            className="btn"
            type="button"
            onClick={() => toggleLicense(lic).catch(() => toast.error(t("common.failed", "失败")))}
          >
            {lic.status === "active" ? t("page.tenants.disable_mod", "停用") : t("page.tenants.enable_mod", "启用")}
          </button>
        ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("page.tenants.title", "Tenants & licenses")}
        subtitle={t(
          "page.tenants.sub",
          "Provision / suspend tenants, edit tier & timezone, and toggle module licenses. Click a row to edit.",
        )}
        breadcrumb={[{ label: t("page.platform.title", "Platform"), href: "/platform" }, { label: t("page.tenants.title", "Tenants & licenses") }]}
        actions={<SavedViews storageKey="platform_tenants" onApply={(qs) => router.replace(`${pathname}${qs}`)} />}
      />
      {initialPw ? (
        <p className="flash">
          {t("page.tenants.pw_ready", "Initial password generated (shown once — copy it now).")}{" "}
          <button type="button" className="btn btn-ghost" onClick={() => copyInitialPw().catch(() => setInitialPw(""))}>
            {t("page.tenants.copy_pw", "Copy initial password")}
          </button>
        </p>
      ) : null}

      <Toolbar
        filterCount={(filterStatus ? 1 : 0) + (filterQ ? 1 : 0)}
        onClearFilters={() => setQuery({ status: null, q: null }, { resetPage: true })}
        right={
          <>
            <input
              className="input input-sm"
              value={filterQ}
              onChange={(e) => setQuery({ q: e.target.value || null }, { resetPage: true })}
              placeholder={t("page.tenants.search", "Search code or name")}
              aria-label={t("page.tenants.search", "Search code or name")}
            />
            <select
              className="input input-sm"
              value={filterStatus}
              onChange={(e) => setQuery({ status: e.target.value || null }, { resetPage: true })}
              aria-label={t("page.tenants.filter_status", "Filter by status")}
            >
              <option value="">{t("common.all", "All")}</option>
              <option value="active">{t("common.active", "Active")}</option>
              <option value="suspended">{t("common.suspended", "Suspended")}</option>
            </select>
          </>
        }
      >
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.tenants.provision", "Provision tenant")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>

      <div className="panel">
        <DataGrid<Tenant>
          columns={tenantColumns}
          data={filtered}
          rowKey={(r) => r.id}
          storageKey="platform_tenants_grid"
          onRowClick={(r) => openTenant(r).catch(() => undefined)}
          onRowDoubleClick={(r) => {
            openTenant(r)
              .then(() => setEditOpen(true))
              .catch(() => undefined);
          }}
          emptyText={t("common.no_data", "No data")}
        />
      </div>

      {selected ? (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>
            {t("page.tenants.edit", "编辑租户")} · {selected.code}
            {busy ? <span className="muted"> …</span> : null}
          </h2>
          <button type="button" className="btn btn-ghost" onClick={() => setEditOpen(true)}>
            {t("page.tenants.edit_profile", "编辑资料")}
          </button>

          <h3 style={{ marginTop: "1.5rem" }}>{t("page.tenants.license_matrix", "模块许可证")}</h3>
          <p className="muted">{t("page.tenants.license_hint", "核心模块始终开通；业务模块可在此启停。")}</p>
          <DataGrid<LicRow>
            columns={licColumns}
            data={licenses}
            rowKey={(r) => r.module_code}
            storageKey="platform_tenants_licenses_grid"
            emptyText={t("common.no_data", "No data")}
          />

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
                  onClick={() => saveOffice().catch(() => toast.error(t("common.failed", "保存失败")))}
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

          <h3 style={{ marginTop: "1.5rem" }}>{t("page.tenants.dataops", "数据管理（备份 / 恢复 / 清理）")}</h3>
          <p className="muted">
            {t(
              "page.tenants.dataops_sub",
              "一键全量备份该租户全部业务数据；清理用于清除测试数据（自动先备份，保留租户/用户/许可底座）。",
            )}
          </p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
            <button className="btn btn-primary" type="button" disabled={dbBusy} onClick={() => tenantBackup()}>
              {t("page.tenants.backup_now", "立即备份")}
            </button>
            <button
              className="btn btn-danger"
              type="button"
              disabled={dbBusy}
              onClick={() => {
                setPurgeOpen(true);
                setPurgeConfirmText("");
                setPurgeIncludeUsers(false);
              }}
            >
              {t("page.tenants.purge_open", "清理租户数据…")}
            </button>
            {dbBusy ? <span className="muted">{t("common.working", "处理中…")}</span> : null}
          </div>
          {dbMsg ? (
            <p className="flash" style={{ color: dbMsg.ok ? "var(--ok)" : "var(--danger)" }}>
              {dbMsg.text}
            </p>
          ) : null}
          {purgeOpen ? (
            <div className="panel" style={{ marginTop: "0.75rem", borderColor: "var(--danger)" }}>
              <p style={{ marginTop: 0 }}>
                {t(
                  "page.tenants.purge_confirm_hint",
                  "将清空 {code} 的全部业务数据（估价/租约/航次/财务/船舶等）。请输入租户代码以确认：",
                  { code: selected.code },
                )}
              </p>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                <input
                  value={purgeConfirmText}
                  onChange={(e) => setPurgeConfirmText(e.target.value)}
                  placeholder={selected.code}
                  style={{ maxWidth: 220 }}
                />
                <label style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={purgeIncludeUsers}
                    onChange={(e) => setPurgeIncludeUsers(e.target.checked)}
                  />
                  {t("page.tenants.purge_include_users", "同时删除用户")}
                </label>
                <button
                  className="btn btn-danger"
                  type="button"
                  disabled={dbBusy || purgeConfirmText !== selected.code}
                  onClick={() => tenantPurge()}
                >
                  {t("page.tenants.purge_run", "确认清理")}
                </button>
                <button className="btn btn-ghost" type="button" disabled={dbBusy} onClick={() => setPurgeOpen(false)}>
                  {t("common.cancel", "取消")}
                </button>
              </div>
            </div>
          ) : null}
          {backups.length > 0 ? (
            <table className="table" style={{ marginTop: "0.75rem" }}>
              <thead>
                <tr>
                  <th>{t("page.tenants.backup_trigger", "触发")}</th>
                  <th>{t("page.tenants.backup_time", "时间")}</th>
                  <th>{t("page.tenants.backup_path", "文件")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {backups.slice(0, 8).map((b) => (
                  <tr key={b.id}>
                    <td>
                      <span className={b.trigger === "manual" ? "badge badge-info" : "badge"}>
                        {b.trigger === "platform_purge"
                          ? t("page.tenants.trigger_purge", "清理前自动")
                          : b.trigger === "auto"
                            ? t("page.tenants.trigger_auto", "自动")
                            : b.trigger}
                      </span>
                    </td>
                    <td>{b.created_at ? new Date(b.created_at).toLocaleString() : "-"}</td>
                    <td>
                      <code style={{ fontSize: "0.75rem" }}>{b.storage_path}</code>
                    </td>
                    <td>
                      <button
                        className="btn btn-sm"
                        type="button"
                        disabled={dbBusy || !b.storage_path}
                        onClick={() => tenantRestore(b)}
                      >
                        {t("page.tenants.restore", "恢复")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted" style={{ marginTop: "0.75rem" }}>
              {t("page.tenants.no_backups", "暂无备份记录")}
            </p>
          )}
        </div>
      ) : (
        <p className="muted">{t("page.tenants.pick", "请选择上方租户行，以编辑资料与许可证。")}</p>
      )}

      <RecordModal
        open={creating}
        title={t("page.tenants.provision", "开通租户")}
        onClose={() => setCreating(false)}
        onSave={create}
        saving={createSaving}
        canDelete={false}
      >
        <div className="form-grid">
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
        </div>
      </RecordModal>

      <RecordModal
        open={editOpen && Boolean(selected)}
        title={t("page.tenants.edit", "编辑租户") + (selected ? ` · ${selected.code}` : "")}
        onClose={() => setEditOpen(false)}
        onSave={saveEdit}
        saving={busy}
        canDelete={false}
      >
        <div className="form-grid">
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
      </RecordModal>

      <ConfirmDialog
        open={Boolean(confirm)}
        title={t("common.confirm", "Confirm")}
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

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <PlatformTenantsPage />
    </Suspense>
  );
}
