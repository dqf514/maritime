"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { SavedViews } from "@/components/SavedViews";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPatch, apiPost, generateTempPassword } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { useToast } from "@/components/ToastProvider";

type UserRow = {
  id: string;
  email: string;
  full_name: string | null;
  status: string;
  roles: string[];
  org_unit_id?: string | null;
  org_unit_code?: string | null;
  org_unit_name?: string | null;
};
type RoleRow = { code: string; name: string };
type OrgUnit = { id: string; code: string; name: string; unit_type: string };

const BUSINESS_ROLES_HINT =
  "可同时勾选多个业务角色（如租船+营运），适合小型企业一人多岗；租户管理员可与业务角色并存。";

function UsersAdminPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const filterOrg = query.dept ?? "";
  const [users, setUsers] = useState<UserRow[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [orgs, setOrgs] = useState<OrgUnit[]>([]);
  const [open, setOpen] = useState<UserRow | null>(null);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({
    email: "",
    full_name: "",
    status: "active",
    role_codes: ["viewer"] as string[],
    org_unit_id: "",
  });
  const [saving, setSaving] = useState(false);
  const [initialPw, setInitialPw] = useState("");

  const assignableRoles = roles.filter((r) => r.code !== "platform_admin");

  async function load() {
    const [u, r, o] = await Promise.all([
      apiGet("/api/v1/admin/users"),
      apiGet("/api/v1/admin/roles"),
      apiGet("/api/v1/admin/org-units"),
    ]);
    setUsers(u);
    setRoles(r);
    setOrgs(o);
  }

  useEffect(() => {
    load().catch(() => toast.error(t("page.users.admin_required", "需要租户管理员角色")));
  }, [t]);

  function toggleRole(list: string[], code: string): string[] {
    if (list.includes(code)) {
      const next = list.filter((c) => c !== code);
      return next.length ? next : ["viewer"];
    }
    return [...list.filter((c) => c !== "viewer" || code === "viewer"), code];
  }

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setEdit({
      email: "",
      full_name: "",
      status: "active",
      role_codes: ["viewer"],
      org_unit_id: "",
    });
  }

  useListHotkeys(openCreate);

  function closeModal() {
    setOpen(null);
    setCreating(false);
  }

  async function copyInitialPw() {
    try {
      await navigator.clipboard.writeText(initialPw);
    } catch {
      window.prompt(t("page.users.copy_manual", "请手动复制初始密码："), initialPw);
    }
    setInitialPw("");
  }

  function openRow(u: UserRow) {
    setCreating(false);
    setOpen(u);
    setEdit({
      email: u.email,
      full_name: u.full_name || "",
      status: u.status,
      role_codes: u.roles.length ? u.roles : ["viewer"],
      org_unit_id: u.org_unit_id || "",
    });
  }

  async function save() {
    setSaving(true);
    try {
      if (creating || !open) {
        const password = generateTempPassword();
        await apiPost("/api/v1/admin/users", {
          email: edit.email,
          full_name: edit.full_name,
          password,
          role_codes: edit.role_codes.length ? edit.role_codes : ["viewer"],
          org_unit_id: edit.org_unit_id || null,
        });
        setInitialPw(password);
        toast.success(t("page.users.created", "用户已创建；初始密码已生成，请通过安全渠道传达。"));
      } else {
        const clearOrg = !edit.org_unit_id;
        await apiPatch(`/api/v1/admin/users/${open.id}`, {
          full_name: edit.full_name,
          status: edit.status,
          role_codes: edit.role_codes.length ? edit.role_codes : ["viewer"],
          org_unit_id: edit.org_unit_id || null,
          clear_org: clearOrg,
        });
        toast.success(t("common.saved", "已保存"));
      }
      closeModal();
      await load();
    } catch {
      toast.error(creating ? t("page.users.create_fail", "创建失败") : t("common.failed", "失败"));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/admin/users/${open.id}`);
      toast.success(t("common.recycled", "已移入回收站"));
      closeModal();
      await load();
    } catch (err: any) {
      toast.error(String(err?.detail?.code || err?.message || t("common.failed", "失败")));
    } finally {
      setSaving(false);
    }
  }

  function RoleCheckboxes({
    value,
    onChange,
  }: {
    value: string[];
    onChange: (next: string[]) => void;
  }) {
    return (
      <div className="role-check-grid">
        {assignableRoles.map((r) => (
          <label key={r.code} className="role-check">
            <input
              type="checkbox"
              checked={value.includes(r.code)}
              onChange={() => onChange(toggleRole(value, r.code))}
            />
            <span>{r.name}</span>
            <code>{r.code}</code>
          </label>
        ))}
      </div>
    );
  }

  const filtered = filterOrg ? users.filter((u) => u.org_unit_id === filterOrg) : users;

  const columns: ColumnDef<UserRow>[] = [
    { key: "full_name", title: t("common.name", "姓名"), width: 160, value: (r) => r.full_name || "" },
    { key: "email", title: t("common.email", "邮箱"), minWidth: 200, value: (r) => r.email },
    {
      key: "org_unit_name",
      title: t("page.org.dept", "部门"),
      width: 180,
      value: (r) => r.org_unit_name || "",
      render: (_v, r) => (r.org_unit_name ? `${r.org_unit_code} · ${r.org_unit_name}` : "—"),
    },
    {
      key: "roles",
      title: t("common.roles", "角色"),
      minWidth: 160,
      value: (r) => r.roles.join(", "),
      render: (_v, r) => <span>{r.roles.join(", ")}</span>,
    },
    { key: "status", title: t("common.status", "状态"), width: 100, value: (r) => r.status },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.admin", "Administration") }]}
        title={t("page.users.title", "用户与角色")}
        subtitle={
          <>
            {t("page.users.sub", "点击用户行打开编辑。一人可同时拥有多个业务角色，并归属到组织部门。")}{" "}
            <Link href="/admin/org">{t("page.org.title", "组织架构")}</Link>
            {" · "}
            <Link href="/admin/security">{t("page.security.title", "登录与安全")}</Link>
          </>
        }
        actions={
          <>
            <SavedViews storageKey="admin_users" onApply={(q) => router.replace(`/admin/users${q}`)} />
            <Link href="/settings/recycle" className="btn btn-ghost">
              {t("nav.recycle", "回收站")}
            </Link>
          </>
        }
      />
      {initialPw ? (
        <p className="flash">
          {t("page.users.pw_ready", "初始密码已生成（仅此一次，复制后即不再显示）。")}{" "}
          <button type="button" className="btn btn-ghost" onClick={() => copyInitialPw().catch(() => setInitialPw(""))}>
            {t("page.users.copy_pw", "复制初始密码")}
          </button>
        </p>
      ) : null}
      <Toolbar
        filterCount={filterOrg ? 1 : 0}
        onClearFilters={() => setQuery({ dept: null }, { resetPage: true })}
        right={
          <>
            <select
              className="input input-sm"
              value={filterOrg}
              onChange={(e) => setQuery({ dept: e.target.value || null }, { resetPage: true })}
              aria-label={t("page.users.filter_dept", "按部门筛选")}
            >
              <option value="">{t("common.all", "全部")}</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.code} · {o.name}
                </option>
              ))}
            </select>
          </>
        }
      >
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.users.invite", "新建用户")}
        </button>
        <button type="button" className="btn btn-sm" onClick={() => load().catch(() => undefined)} title={t("common.refresh", "Refresh")}>
          ↻
        </button>
      </Toolbar>
      <div className="panel">
        <DataGrid<UserRow>
          columns={columns}
          data={filtered}
          rowKey={(u) => u.id}
          storageKey="admin_users_grid"
          emptyText={t("common.none", "无")}
          showFooter={false}
          onRowClick={(u) => openRow(u)}
          onRowDoubleClick={(u) => openRow(u)}
        />
      </div>

      <RecordModal
        open={creating || Boolean(open)}
        title={creating ? t("page.users.invite", "新建用户") : t("page.users.edit", "编辑用户")}
        onClose={closeModal}
        onSave={save}
        onDelete={creating ? undefined : remove}
        canDelete={!creating}
        saving={saving}
      >
        {creating ? (
          <label>
            {t("common.email", "邮箱")}
            <input type="email" value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} required />
          </label>
        ) : (
          <p className="muted">{open?.email}</p>
        )}
        <label>
          {t("page.users.full_name", "姓名")}
          <input value={edit.full_name} onChange={(e) => setEdit({ ...edit, full_name: e.target.value })} required />
        </label>
        <label>
          {t("page.org.dept", "部门")}
          <select value={edit.org_unit_id} onChange={(e) => setEdit({ ...edit, org_unit_id: e.target.value })}>
            <option value="">{t("page.org.unassigned", "未分配")}</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.code} · {o.name}
              </option>
            ))}
          </select>
        </label>
        {!creating ? (
          <label>
            {t("common.status", "状态")}
            <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
              <option value="active">active</option>
              <option value="disabled">disabled</option>
              <option value="invited">invited</option>
            </select>
          </label>
        ) : null}
        <div>
          <div className="muted" style={{ marginBottom: "0.4rem", fontSize: "0.85rem" }}>
            {t("page.users.roles_multi", BUSINESS_ROLES_HINT)}
          </div>
          <RoleCheckboxes
            value={edit.role_codes}
            onChange={(role_codes) => setEdit({ ...edit, role_codes })}
          />
        </div>
      </RecordModal>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <UsersAdminPage />
    </Suspense>
  );
}
