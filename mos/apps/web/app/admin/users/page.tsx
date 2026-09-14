"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost, generateTempPassword } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

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

export default function UsersAdminPage() {
  const { t } = useI18n();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [orgs, setOrgs] = useState<OrgUnit[]>([]);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [createRoles, setCreateRoles] = useState<string[]>(["viewer"]);
  const [createOrg, setCreateOrg] = useState("");
  const [filterOrg, setFilterOrg] = useState("");
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<UserRow | null>(null);
  const [edit, setEdit] = useState({
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
    load().catch(() => setMsg(t("page.users.admin_required", "需要租户管理员角色")));
  }, [t]);

  function toggleRole(list: string[], code: string): string[] {
    if (list.includes(code)) {
      const next = list.filter((c) => c !== code);
      return next.length ? next : ["viewer"];
    }
    return [...list.filter((c) => c !== "viewer" || code === "viewer"), code];
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    const password = generateTempPassword();
    await apiPost("/api/v1/admin/users", {
      email,
      full_name: fullName,
      password,
      role_codes: createRoles.length ? createRoles : ["viewer"],
      org_unit_id: createOrg || null,
    });
    setEmail("");
    setFullName("");
    setCreateRoles(["viewer"]);
    setCreateOrg("");
    setInitialPw(password);
    setMsg(t("page.users.created", "用户已创建；初始密码已生成，请通过安全渠道传达。"));
    await load();
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
    setOpen(u);
    setEdit({
      full_name: u.full_name || "",
      status: u.status,
      role_codes: u.roles.length ? u.roles : ["viewer"],
      org_unit_id: u.org_unit_id || "",
    });
  }

  async function save() {
    if (!open) return;
    setSaving(true);
    try {
      const clearOrg = !edit.org_unit_id;
      await apiPatch(`/api/v1/admin/users/${open.id}`, {
        full_name: edit.full_name,
        status: edit.status,
        role_codes: edit.role_codes.length ? edit.role_codes : ["viewer"],
        org_unit_id: edit.org_unit_id || null,
        clear_org: clearOrg,
      });
      setMsg(t("common.saved", "已保存"));
      setOpen(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/admin/users/${open.id}`);
      setMsg(t("common.recycled", "已移入回收站"));
      setOpen(null);
      await load();
    } catch (err: any) {
      setMsg(String(err?.detail?.code || err?.message || t("common.failed", "失败")));
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

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.users.title", "用户与角色")}</h1>
          <p className="page-sub">
            {t("page.users.sub", "点击用户行打开编辑。一人可同时拥有多个业务角色，并归属到组织部门。")}{" "}
            <Link href="/admin/org">{t("page.org.title", "组织架构")}</Link>
            {" · "}
            <Link href="/admin/security">{t("page.security.title", "登录与安全")}</Link>
          </p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "回收站")}
        </Link>
      </div>
      {msg ? <p>{msg}</p> : null}
      {initialPw ? (
        <p className="flash">
          {t("page.users.pw_ready", "初始密码已生成（仅此一次，复制后即不再显示）。")}{" "}
          <button type="button" className="btn btn-ghost" onClick={() => copyInitialPw().catch(() => setInitialPw(""))}>
            {t("page.users.copy_pw", "复制初始密码")}
          </button>
        </p>
      ) : null}
      <form className="panel" onSubmit={(e) => create(e).catch(() => setMsg(t("page.users.create_fail", "创建失败")))}>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("page.users.full_name", "姓名")}
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          </label>
          <label>
            {t("common.email", "邮箱")}
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label>
            {t("page.org.dept", "部门")}
            <select value={createOrg} onChange={(e) => setCreateOrg(e.target.value)}>
              <option value="">{t("page.org.unassigned", "未分配")}</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.code} · {o.name}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.users.invite", "新建用户")}
          </button>
        </div>
        <div style={{ marginTop: "0.75rem" }}>
          <div className="muted" style={{ marginBottom: "0.4rem", fontSize: "0.85rem" }}>
            {t("page.users.roles_multi", BUSINESS_ROLES_HINT)}
          </div>
          <RoleCheckboxes value={createRoles} onChange={setCreateRoles} />
        </div>
      </form>
      <div className="panel">
        <div style={{ marginBottom: "0.75rem" }}>
          <label>
            {t("page.users.filter_dept", "按部门筛选")}
            <select value={filterOrg} onChange={(e) => setFilterOrg(e.target.value)}>
              <option value="">{t("common.all", "全部")}</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.code} · {o.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "姓名")}</th>
              <th>{t("common.email", "邮箱")}</th>
              <th>{t("page.org.dept", "部门")}</th>
              <th>{t("common.roles", "角色")}</th>
              <th>{t("common.status", "状态")}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.id} className="row-openable" onClick={() => openRow(u)}>
                <td>{u.full_name}</td>
                <td>{u.email}</td>
                <td>{u.org_unit_name ? `${u.org_unit_code} · ${u.org_unit_name}` : "—"}</td>
                <td>{u.roles.join(", ")}</td>
                <td>{u.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={t("page.users.edit", "编辑用户")}
        onClose={() => setOpen(null)}
        onSave={save}
        onDelete={remove}
        saving={saving}
      >
        <p className="muted">{open?.email}</p>
        <label>
          {t("page.users.full_name", "姓名")}
          <input value={edit.full_name} onChange={(e) => setEdit({ ...edit, full_name: e.target.value })} />
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
        <label>
          {t("common.status", "状态")}
          <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
            <option value="active">active</option>
            <option value="disabled">disabled</option>
            <option value="invited">invited</option>
          </select>
        </label>
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
