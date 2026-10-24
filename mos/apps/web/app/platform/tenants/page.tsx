"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { msgOf, handled } from "@/lib/errors";
import { FormEvent, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { RecordModal } from "@/components/RecordModal";
import { LookupSelect } from "@/components/LookupSelect";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { StateView } from "@/components/StateView";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPatch, apiPost, apiPut, generateTempPassword } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { formatInTz } from "@/lib/datetime";
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

type PUserRow = {
  id: string;
  email: string;
  full_name: string | null;
  status: string;
  roles: string[];
};
type RoleRow = { id: string; code: string; name: string };

function PlatformTenantsPage() {
  const { t, locale } = useI18n();
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
  // 租户用户管理（平台侧增删改 + 密码重置）
  const [pusers, setPusers] = useState<PUserRow[]>([]);
  const [proles, setProles] = useState<RoleRow[]>([]);
  const [userModal, setUserModal] = useState<{ mode: "create" | "edit"; user?: PUserRow } | null>(null);
  const [userEdit, setUserEdit] = useState({ email: "", full_name: "", status: "active", role_codes: ["viewer"] as string[], send_email: true });
  const [userSaving, setUserSaving] = useState(false);
  const [userPw, setUserPw] = useState(""); // 一次性临时密码 flash
  const [resetTarget, setResetTarget] = useState<PUserRow | null>(null);
  // 三态 / 分级错误：主列表失败 → 整页 error；附属数据失败 → 局部提示
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [usersErr, setUsersErr] = useState<string | null>(null);
  const [rolesErr, setRolesErr] = useState<string | null>(null);
  const [backupsErr, setBackupsErr] = useState<string | null>(null);
  // 密钥默认隐藏（不常驻明文）
  const [revealInitialPw, setRevealInitialPw] = useState(false);
  const [revealUserPw, setRevealUserPw] = useState(false);
  // 恢复备份：不可逆，需输入租户代码确认
  const [restoreTarget, setRestoreTarget] = useState<BackupRow | null>(null);
  const [restoreConfirmText, setRestoreConfirmText] = useState("");
  // 备份列表客户端分页（总数常显，不静默截断）
  const [backupPage, setBackupPage] = useState(1);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setRows(await apiGet("/api/v1/platform/tenants"));
    } catch (ex) {
      setErr(msgOf(ex, t("page.tenants.admin_required", "需要平台管理员（租户 sys）")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t]);

  const loadUsers = useCallback(async (tid?: string) => {
    if (!tid) return;
    setUsersErr(null);
    setRolesErr(null);
    try {
      setPusers(await apiGet(`/api/v1/platform/tenants/${tid}/users`));
    } catch (ex) {
      setUsersErr(msgOf(ex));
      setPusers([]);
    }
    try {
      setProles(await apiGet(`/api/v1/platform/tenants/${tid}/roles`));
    } catch (ex) {
      setRolesErr(msgOf(ex));
      setProles([]);
    }
  }, []);

  const openTenant = useCallback(async (row: Tenant) => {
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
      setBackupsErr(null);
      setBackups(
        await apiGet(`/api/v1/platform/tenants/${row.id}/backups`).catch((ex) => {
          setBackupsErr(msgOf(ex));
          return [] as BackupRow[];
        }),
      );
      // 用户管理区
      await loadUsers(row.id);
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "加载失败")));
    } finally {
      setBusy(false);
    }
  }, [loadUsers, t, toast]);

  const assignableRoles = proles.filter((r) => r.code !== "platform_admin");

  function toggleRole(list: string[], code: string): string[] {
    if (list.includes(code)) {
      const next = list.filter((c) => c !== code);
      return next.length ? next : ["viewer"];
    }
    return [...list.filter((c) => c !== "viewer" || code === "viewer"), code];
  }

  function openUserCreate() {
    setUserEdit({ email: "", full_name: "", status: "active", role_codes: ["viewer"], send_email: true });
    setUserModal({ mode: "create" });
  }

  function openUserRow(u: PUserRow) {
    setUserEdit({ email: u.email, full_name: u.full_name || "", status: u.status, role_codes: u.roles.length ? u.roles : ["viewer"], send_email: true });
    setUserModal({ mode: "edit", user: u });
  }

  async function copyUserPw() {
    try {
      await navigator.clipboard.writeText(userPw);
      setUserPw("");
    } catch {
      // 剪贴板不可用：不把明文放进 prompt，改为按需显示由用户手动复制
      setRevealUserPw(true);
    }
  }

  async function saveUser(e: FormEvent) {
    e.preventDefault();
    if (!selected || !userModal) return;
    setUserSaving(true);
    try {
      if (userModal.mode === "create") {
        // 不传 password → 服务端生成临时密码并（按 send_email）邮件下发
        const res = await apiPost(`/api/v1/platform/tenants/${selected.id}/users`, {
          email: userEdit.email,
          full_name: userEdit.full_name,
          role_codes: userEdit.role_codes.length ? userEdit.role_codes : ["viewer"],
          send_email: userEdit.send_email,
        });
        if (res.temp_password) setUserPw(res.temp_password);
        toast.success(
          res.emailed
            ? t("page.tenants.user_created_mailed", "用户已创建；临时密码已邮件发送给该用户（也可立即复制）。")
            : t("page.tenants.user_created", "用户已创建；临时密码已生成，请通过安全渠道传达。"),
        );
      } else if (userModal.user) {
        await apiPatch(`/api/v1/platform/tenants/${selected.id}/users/${userModal.user.id}`, {
          full_name: userEdit.full_name,
          status: userEdit.status,
          role_codes: userEdit.role_codes.length ? userEdit.role_codes : ["viewer"],
        });
        toast.success(t("common.saved", "已保存"));
      }
      setUserModal(null);
      await loadUsers(selected.id);
      await load();
    } catch (err: any) {
      const code = err?.detail?.code;
      toast.error(
        code === "LAST_TENANT_ADMIN"
          ? t("page.tenants.last_admin_guard", "该用户是最后一个启用的租户管理员，不能停用/降级/删除。")
          : code === "USER_EXISTS"
            ? t("page.tenants.user_exists", "该邮箱已存在于本租户")
            : t("common.failed", "失败"),
      );
    } finally {
      setUserSaving(false);
    }
  }

  async function removeUser(u: PUserRow) {
    if (!selected) return;
    try {
      await apiDelete(`/api/v1/platform/tenants/${selected.id}/users/${u.id}`);
      toast.success(t("common.recycled", "已移入回收站"));
      await loadUsers(selected.id);
      await load();
    } catch (err: any) {
      toast.error(
        err?.detail?.code === "LAST_TENANT_ADMIN"
          ? t("page.tenants.last_admin_guard", "该用户是最后一个启用的租户管理员，不能停用/降级/删除。")
          : t("common.failed", "失败"),
      );
    }
  }

  async function resetUserPw(u: PUserRow) {
    if (!selected) return;
    try {
      const res = await apiPost(`/api/v1/platform/tenants/${selected.id}/users/${u.id}/reset-password`, { send_email: true });
      if (res.temp_password) setUserPw(res.temp_password);
      toast.success(
        res.emailed
          ? t("page.tenants.user_reset_mailed", "密码已重置并邮件发送；该用户现有登录会话已全部失效。")
          : t("page.tenants.user_reset", "密码已重置；临时密码请立即复制传达。"),
      );
    } catch (err) {
      toast.error(msgOf(err, t("common.failed", "失败")));
    } finally {
      setResetTarget(null);
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
      toast.error(t("page.tenants.create_fail", "创建失败: {err}", { err: msgOf(err) }));
    } finally {
      setCreateSaving(false);
    }
  }

  async function copyInitialPw() {
    try {
      await navigator.clipboard.writeText(initialPw);
      setInitialPw("");
    } catch {
      // 剪贴板不可用：不把明文放进 prompt，改为按需显示由用户手动复制
      setRevealInitialPw(true);
    }
  }

  /** DELETE /platform/tenants/{id} = deactivate（status→suspended，数据保留，可再启用） */
  const deactivateTenant = useCallback(async (id: string) => {
    try {
      await apiDelete(`/api/v1/platform/tenants/${id}`);
      toast.success(t("page.tenants.deactivated", "租户已停用（数据保留）"));
      await load();
      if (selected?.id === id) await openTenant({ ...selected, status: "suspended" });
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "失败")));
    }
  }, [load, openTenant, selected, t, toast]);

  const applyStatus = useCallback(async (id: string, status: string) => {
    await apiPost(`/api/v1/platform/tenants/${id}/status`, { status });
    await load();
    if (selected?.id === id) await openTenant({ ...selected, status });
  }, [load, openTenant, selected]);

  const setStatus = useCallback(async (id: string, status: string) => {
    if (status === "suspended") {
      // 停用走 DELETE（后端 deactivate，数据保留）；文案强调可恢复、不丢数据
      setConfirm({
        message: t("page.tenants.confirm_suspend", "暂停租户后，该租户全部用户将立即无法登录（数据保留）。确认暂停？"),
        danger: true,
        action: () => deactivateTenant(id).catch(() => toast.error(t("common.failed", "失败"))),
      });
      return;
    }
    await applyStatus(id, status);
  }, [applyStatus, deactivateTenant, t, toast]);

  /** 最后一个 active 租户不可停用（后端 LAST_ACTIVE_TENANT 409）；提前隐藏按钮 */
  const activeCount = rows.filter((r) => r.status === "active").length;

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
      toast.error(t("page.tenants.save_fail", "保存失败: {err}", { err: msgOf(err) }));
    }
  }

  const applyLicense = useCallback(async (mod: LicRow, next: string) => {
    if (!selected) return;
    await apiPost(`/api/v1/platform/tenants/${selected.id}/licenses`, {
      module_code: mod.module_code,
      status: next,
    });
    setLicenses(await apiGet(`/api/v1/platform/tenants/${selected.id}/licenses`));
    await load();
  }, [selected, load]);

  const toggleLicense = useCallback(async (mod: LicRow) => {
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
  }, [selected, applyLicense, t, toast]);

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
      setOtest({ ok: false, text: msgOf(e) });
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

  // 备份列表客户端分页：总数常显，不做静默 slice
  const BACKUP_PAGE_SIZE = 8;
  const backupPages = Math.max(1, Math.ceil(backups.length / BACKUP_PAGE_SIZE));
  const backupPageSafe = Math.min(Math.max(1, backupPage), backupPages);
  const backupRows = backups.slice((backupPageSafe - 1) * BACKUP_PAGE_SIZE, backupPageSafe * BACKUP_PAGE_SIZE);

  const tenantColumns = useMemo<ColumnDef<Tenant>[]>(() => [
    {
      key: "code",
      title: t("common.code", "代码"),
      width: 110,
      value: (r) => r.code,
      render: (v, r) => (
        <button type="button" className="linklike" onClick={(e) => { e.stopPropagation(); openTenant(r).catch(handled); }}>
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
        <span className={v === "active" ? "badge badge-pass" : "badge badge-fail"}>{t(`status.${v}`, String(v))}</span>
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
            disabled={activeCount <= 1}
            title={activeCount <= 1 ? t("page.tenants.last_active_hint", "Cannot deactivate the last active tenant") : undefined}
            onClick={(e) => { e.stopPropagation(); setStatus(r.id, "suspended").catch(() => toast.error(t("common.failed", "失败"))); }}
          >
            {t("page.tenants.deactivate", "Deactivate")}
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
  ], [t, openTenant, activeCount, setStatus, toast]);

  const licColumns = useMemo<ColumnDef<LicRow>[]>(() => [
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
        <span className={v === "active" ? "badge badge-pass" : "badge badge-warn"}>{t(`status.${v}`, String(v))}</span>
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
  ], [t, toggleLicense, toast]);

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
        <div className="flash">
          <span>{t("page.tenants.pw_ready", "Initial password generated (shown once — copy it now).")}</span>{" "}
          <button type="button" className="btn btn-ghost" onClick={() => copyInitialPw().catch(() => toast.error(t("page.tenants.copy_fail", "Copy failed")))}>
            {t("page.tenants.copy_pw", "Copy initial password")}
          </button>{" "}
          <button
            type="button"
            className="btn btn-ghost"
            aria-expanded={revealInitialPw}
            aria-label={t("page.tenants.reveal_pw", "显示密码")}
            onClick={() => setRevealInitialPw((v) => !v)}
          >
            {revealInitialPw ? t("page.tenants.hide_pw", "隐藏密码") : t("page.tenants.reveal_pw", "显示密码")}
          </button>
          {revealInitialPw ? <code>{initialPw}</code> : null}
        </div>
      ) : null}
      {userPw ? (
        <div className="flash">
          <span>{t("page.tenants.user_pw_ready", "临时密码已生成（仅此一次，复制后即不再显示）。")}</span>{" "}
          <button type="button" className="btn btn-ghost" onClick={() => copyUserPw().catch(() => toast.error(t("page.tenants.copy_fail", "Copy failed")))}>
            {t("page.tenants.copy_pw", "Copy initial password")}
          </button>{" "}
          <button
            type="button"
            className="btn btn-ghost"
            aria-expanded={revealUserPw}
            aria-label={t("page.tenants.reveal_pw", "显示密码")}
            onClick={() => setRevealUserPw((v) => !v)}
          >
            {revealUserPw ? t("page.tenants.hide_pw", "隐藏密码") : t("page.tenants.reveal_pw", "显示密码")}
          </button>
          {revealUserPw ? <code>{userPw}</code> : null}
        </div>
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
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load().catch(handled)} />
      </Toolbar>

      <div className="panel">
        <DataGrid<Tenant>
          columns={tenantColumns}
          data={filtered}
          rowKey={(r) => r.id}
          storageKey="platform_tenants_grid"
          onRowClick={(r) => openTenant(r).catch(handled)}
          onRowDoubleClick={(r) => {
            openTenant(r)
              .then(() => setEditOpen(true))
              .catch(handled);
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

          <h3 style={{ marginTop: "1.5rem" }}>{t("page.tenants.users", "用户管理")}</h3>
          <p className="muted">
            {t(
              "page.tenants.users_sub",
              "平台可为该租户新建 / 编辑 / 停用用户，也可重置密码（重置后邮件发送新临时密码，旧会话立即失效）。可直接把某人设为租户管理员。",
            )}
          </p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
            <button className="btn btn-primary" type="button" onClick={openUserCreate}>
              {t("page.tenants.user_add", "新建用户")}
            </button>
            <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => loadUsers(selected.id).catch(handled)} />
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>{t("common.email", "邮箱")}</th>
                <th>{t("common.name", "姓名")}</th>
                <th>{t("common.roles", "角色")}</th>
                <th>{t("common.status", "状态")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pusers.map((u) => (
                <tr key={u.id}>
                  <td>
                    <button type="button" className="linklike" onClick={() => openUserRow(u)}>
                      {u.email}
                    </button>
                  </td>
                  <td>{u.full_name || "—"}</td>
                  <td>{u.roles.map((c) => t(`role.${c}`, c)).join(locale.startsWith("zh") ? "、" : ", ")}</td>
                  <td>
                    <span className={u.status === "active" ? "badge badge-pass" : "badge badge-warn"}>{t(`status.${u.status}`, u.status)}</span>
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button className="btn btn-sm" type="button" onClick={() => setResetTarget(u)}>
                      {t("page.tenants.user_reset_pw", "重置密码")}
                    </button>{" "}
                    <button
                      className="btn btn-sm btn-danger"
                      type="button"
                      onClick={() =>
                        setConfirm({
                          message: t("page.tenants.user_delete_confirm", "删除用户 {email}？（软删除，可在回收站恢复）", { email: u.email }),
                          danger: true,
                          action: () => removeUser(u).catch(handled),
                        })
                      }
                    >
                      {t("common.delete", "删除")}
                    </button>
                  </td>
                </tr>
              ))}
              {!pusers.length ? (
                <tr>
                  <td colSpan={5} className="muted">
                    {t("common.no_data", "No data")}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>

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
                <button className="btn btn-ghost" type="button" onClick={() => copyRedirectUri().catch(handled)}>
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
                  aria-label={t("page.tenants.purge_confirm_input", "Type the tenant code to confirm")}
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
                {backupRows.map((b) => (
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
                    <td>{b.created_at ? formatInTz(b.created_at) : "-"}</td>
                    <td>
                      <code style={{ fontSize: "0.75rem" }}>{b.storage_path}</code>
                    </td>
                    <td>
                      <button
                        className="btn btn-sm"
                        type="button"
                        disabled={dbBusy || !b.storage_path}
                        onClick={() => {
                          setRestoreTarget(b);
                          setRestoreConfirmText("");
                        }}
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
          {backupsErr ? <p className="text-danger">{backupsErr}</p> : null}
          {backups.length > 0 ? (
            <div className="dt-pager">
              <span className="muted">{t("common.count_total", "共 {n} 条", { n: backups.length })}</span>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={backupPageSafe <= 1}
                aria-label={t("common.page_prev", "上一页")}
                onClick={() => setBackupPage((p) => Math.max(1, p - 1))}
              >
                ←
              </button>
              <span className="muted">
                {backupPageSafe} / {backupPages}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={backupPageSafe >= backupPages}
                aria-label={t("common.page_next", "下一页")}
                onClick={() => setBackupPage((p) => Math.min(backupPages, p + 1))}
              >
                →
              </button>
            </div>
          ) : null}
          {restoreTarget && selected ? (
            <div className="panel" style={{ marginTop: "0.75rem", borderColor: "var(--danger)" }}>
              <p style={{ marginTop: 0 }}>
                {t(
                  "page.tenants.restore_confirm_hint",
                  "恢复备份 {path} 会把该快照的数据写回租户 {code}，覆盖/合并当前线上数据且不可撤销。请输入租户代码以确认：",
                  { path: restoreTarget.storage_path || "", code: selected.code },
                )}
              </p>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center" }}>
                <input
                  value={restoreConfirmText}
                  onChange={(e) => setRestoreConfirmText(e.target.value)}
                  aria-label={t("page.tenants.restore_confirm_input", "Type the tenant code to confirm")}
                  placeholder={selected.code}
                  style={{ maxWidth: 220 }}
                />
                <button
                  className="btn btn-danger"
                  type="button"
                  disabled={dbBusy || restoreConfirmText !== selected.code}
                  onClick={() => {
                    const b = restoreTarget;
                    setRestoreTarget(null);
                    setRestoreConfirmText("");
                    if (b) tenantRestore(b);
                  }}
                >
                  {t("page.tenants.restore_run", "确认恢复")}
                </button>
                <button
                  className="btn btn-ghost"
                  type="button"
                  disabled={dbBusy}
                  onClick={() => {
                    setRestoreTarget(null);
                    setRestoreConfirmText("");
                  }}
                >
                  {t("common.cancel", "取消")}
                </button>
              </div>
            </div>
          ) : null}
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

      <RecordModal
        open={Boolean(userModal)}
        title={
          userModal?.mode === "create"
            ? t("page.tenants.user_add", "新建用户")
            : t("page.tenants.user_edit", "编辑用户") + (userModal?.user ? ` · ${userModal.user.email}` : "")
        }
        onClose={() => setUserModal(null)}
        onSave={saveUser}
        saving={userSaving}
        canDelete={false}
      >
        {userModal?.mode === "create" ? (
          <div className="form-grid">
            <label>
              {t("common.email", "邮箱")}
              <input
                type="email"
                value={userEdit.email}
                onChange={(e) => setUserEdit({ ...userEdit, email: e.target.value })}
                required
              />
            </label>
            <label>
              {t("page.users.full_name", "姓名")}
              <input
                value={userEdit.full_name}
                onChange={(e) => setUserEdit({ ...userEdit, full_name: e.target.value })}
                required
              />
            </label>
            <label style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
              <input
                type="checkbox"
                checked={userEdit.send_email}
                onChange={(e) => setUserEdit({ ...userEdit, send_email: e.target.checked })}
              />
              {t("page.tenants.user_send_email", "创建后邮件发送登录凭据（需平台配置邮件通道）")}
            </label>
          </div>
        ) : (
          <div className="form-grid">
            <label>
              {t("page.users.full_name", "姓名")}
              <input
                value={userEdit.full_name}
                onChange={(e) => setUserEdit({ ...userEdit, full_name: e.target.value })}
                required
              />
            </label>
            <label>
              {t("common.status", "状态")}
              <select value={userEdit.status} onChange={(e) => setUserEdit({ ...userEdit, status: e.target.value })}>
                <option value="active">{t("status.active", "active")}</option>
                <option value="disabled">{t("status.disabled", "disabled")}</option>
                <option value="invited">{t("status.invited", "invited")}</option>
              </select>
            </label>
          </div>
        )}
        <div>
          <div className="muted" style={{ marginBottom: "0.4rem", fontSize: "0.85rem" }}>
            {t("page.users.roles_multi", "可同时勾选多个业务角色（如租船+营运），适合小型企业一人多岗；租户管理员可与业务角色并存。")}
          </div>
          <div className="role-check-grid">
            {assignableRoles.map((r) => (
              <label key={r.code} className="role-check">
                <input
                  type="checkbox"
                  checked={userEdit.role_codes.includes(r.code)}
                  onChange={() => setUserEdit({ ...userEdit, role_codes: toggleRole(userEdit.role_codes, r.code) })}
                />
                <span>{r.name}</span>
                <code>{r.code}</code>
              </label>
            ))}
          </div>
        </div>
      </RecordModal>

      <ConfirmDialog
        open={Boolean(resetTarget)}
        title={t("page.tenants.user_reset_pw", "重置密码")}
        message={t(
          "page.tenants.user_reset_confirm",
          "将为 {email} 生成新的临时密码并邮件发送，其现有登录会话会立即失效。确认重置？",
          { email: resetTarget?.email || "" },
        )}
        danger
        onConfirm={() => {
          const u = resetTarget;
          setResetTarget(null);
          if (u) resetUserPw(u).catch(handled);
        }}
        onCancel={() => setResetTarget(null)}
      />

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
