"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type UserRow = { id: string; email: string; full_name: string | null; status: string; roles: string[] };
type RoleRow = { code: string; name: string };

const BUSINESS_ROLES_HINT =
  "可同时勾选多个业务角色（如租船+营运），适合小型企业一人多岗；租户管理员可与业务角色并存。";

export default function UsersAdminPage() {
  const { t } = useI18n();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [createRoles, setCreateRoles] = useState<string[]>(["viewer"]);
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<UserRow | null>(null);
  const [edit, setEdit] = useState({ full_name: "", status: "active", role_codes: ["viewer"] as string[] });
  const [saving, setSaving] = useState(false);

  const assignableRoles = roles.filter((r) => r.code !== "platform_admin");

  async function load() {
    const [u, r] = await Promise.all([apiGet("/api/v1/admin/users"), apiGet("/api/v1/admin/roles")]);
    setUsers(u);
    setRoles(r);
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
    await apiPost("/api/v1/admin/users", {
      email,
      full_name: fullName,
      password: "Demo1234!",
      role_codes: createRoles.length ? createRoles : ["viewer"],
    });
    setEmail("");
    setFullName("");
    setCreateRoles(["viewer"]);
    setMsg(t("page.users.created", "用户已创建（临时密码 Demo1234!）"));
    await load();
  }

  function openRow(u: UserRow) {
    setOpen(u);
    setEdit({
      full_name: u.full_name || "",
      status: u.status,
      role_codes: u.roles.length ? u.roles : ["viewer"],
    });
  }

  async function save() {
    if (!open) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/admin/users/${open.id}`, {
        full_name: edit.full_name,
        status: edit.status,
        role_codes: edit.role_codes.length ? edit.role_codes : ["viewer"],
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

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.users.title", "用户与角色")}</h1>
          <p className="page-sub">
            {t("page.users.sub", "点击用户行打开编辑。一人可同时拥有多个业务角色。")}{" "}
            <a href="/admin/security">{t("page.security.title", "登录与安全")}</a>
          </p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "回收站")}
        </Link>
      </div>
      {msg ? <p>{msg}</p> : null}
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
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.name", "姓名")}</th>
              <th>{t("common.email", "邮箱")}</th>
              <th>{t("common.roles", "角色")}</th>
              <th>{t("common.status", "状态")}</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="row-openable" onClick={() => openRow(u)}>
                <td>{u.full_name}</td>
                <td>{u.email}</td>
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
