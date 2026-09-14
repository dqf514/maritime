"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Unit = {
  id: string;
  code: string;
  name: string;
  parent_id: string | null;
  unit_type: string;
  status?: string;
  manager_user_id?: string | null;
  manager_name?: string | null;
  member_count?: number;
};
type UserRow = { id: string; email: string; full_name: string | null };
type Member = { id: string; email: string; full_name: string | null; status: string; is_manager: boolean };

export default function OrgStructurePage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Unit[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<Unit | null>(null);
  const [edit, setEdit] = useState({
    code: "",
    name: "",
    unit_type: "dept",
    status: "active",
    parent_id: "",
    manager_user_id: "",
  });
  const [members, setMembers] = useState<Member[]>([]);
  const [saving, setSaving] = useState(false);

  async function load() {
    const [units, us] = await Promise.all([apiGet("/api/v1/admin/org-units"), apiGet("/api/v1/admin/users")]);
    setRows(units);
    setUsers(us);
  }
  useEffect(() => {
    load().catch(() => setMsg(t("page.org.admin_required", "需要租户管理员")));
  }, [t]);

  async function create(e: FormEvent) {
    e.preventDefault();
    await apiPost("/api/v1/admin/org-units", {
      code,
      name,
      unit_type: "dept",
      parent_id: rows.find((r) => r.unit_type === "company")?.id || null,
    });
    setCode("");
    setName("");
    setMsg(t("common.created", "已创建"));
    await load();
  }

  async function openRow(r: Unit) {
    setOpen(r);
    setEdit({
      code: r.code,
      name: r.name,
      unit_type: r.unit_type,
      status: r.status || "active",
      parent_id: r.parent_id || "",
      manager_user_id: r.manager_user_id || "",
    });
    try {
      setMembers(await apiGet(`/api/v1/admin/org-units/${r.id}/members`));
    } catch {
      setMembers([]);
    }
  }

  async function save() {
    if (!open) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/admin/org-units/${open.id}`, {
        code: edit.code,
        name: edit.name,
        unit_type: edit.unit_type,
        status: edit.status,
        parent_id: edit.parent_id || null,
        manager_user_id: edit.manager_user_id || null,
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
      await apiDelete(`/api/v1/admin/org-units/${open.id}`);
      setMsg(t("common.recycled", "已移入回收站"));
      setOpen(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  function parentLabel(id: string | null) {
    if (!id) return "—";
    const p = rows.find((r) => r.id === id);
    return p ? `${p.code} · ${p.name}` : id.slice(0, 8);
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.org.title", "组织架构")}</h1>
          <p className="page-sub">
            {t("page.org.sub", "总部、部门与团队。人员归属在「用户与角色」中设置，此处可查看成员与负责人。")}{" "}
            <Link href="/admin/users">{t("page.users.title", "用户与角色")}</Link>
          </p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "回收站")}
        </Link>
      </div>
      {msg ? <p>{msg}</p> : null}
      <form className="panel" onSubmit={(e) => create(e).catch(() => setMsg(t("common.failed", "失败")))}>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("common.code", "编码")}
            <input value={code} onChange={(e) => setCode(e.target.value)} required />
          </label>
          <label>
            {t("common.name", "名称")}
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.org.add_dept", "新建部门")}
          </button>
        </div>
      </form>
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "编码")}</th>
              <th>{t("common.name", "名称")}</th>
              <th>{t("common.type", "类型")}</th>
              <th>{t("page.org.parent", "上级")}</th>
              <th>{t("page.org.manager", "负责人")}</th>
              <th>{t("page.org.members", "成员数")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                <td>{r.code}</td>
                <td>{r.name}</td>
                <td>{r.unit_type}</td>
                <td>{parentLabel(r.parent_id)}</td>
                <td>{r.manager_name || "—"}</td>
                <td>{r.member_count ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={t("page.org.edit", "编辑组织单元")}
        onClose={() => setOpen(null)}
        onSave={save}
        onDelete={remove}
        saving={saving}
      >
        <label>
          {t("common.code", "编码")}
          <input value={edit.code} onChange={(e) => setEdit({ ...edit, code: e.target.value })} required />
        </label>
        <label>
          {t("common.name", "名称")}
          <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
        </label>
        <label>
          {t("common.type", "类型")}
          <select value={edit.unit_type} onChange={(e) => setEdit({ ...edit, unit_type: e.target.value })}>
            <option value="company">company</option>
            <option value="dept">dept</option>
            <option value="team">team</option>
          </select>
        </label>
        <label>
          {t("page.org.parent", "上级")}
          <select value={edit.parent_id} onChange={(e) => setEdit({ ...edit, parent_id: e.target.value })}>
            <option value="">—</option>
            {rows
              .filter((r) => r.id !== open?.id)
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.code} · {r.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          {t("page.org.manager", "负责人")}
          <select
            value={edit.manager_user_id}
            onChange={(e) => setEdit({ ...edit, manager_user_id: e.target.value })}
          >
            <option value="">—</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name || u.email}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("common.status", "状态")}
          <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
            <option value="active">active</option>
            <option value="disabled">disabled</option>
          </select>
        </label>
        <div>
          <div className="muted" style={{ marginBottom: "0.35rem" }}>
            {t("page.org.members", "部门成员")} ({members.length})
          </div>
          <ul className="compact-list">
            {members.map((m) => (
              <li key={m.id}>
                {m.full_name || m.email}
                {m.is_manager ? ` · ${t("page.org.manager", "负责人")}` : ""}
              </li>
            ))}
            {!members.length ? <li className="muted">{t("page.org.no_members", "暂无成员 — 请在用户管理中分配部门")}</li> : null}
          </ul>
        </div>
      </RecordModal>
    </AppShell>
  );
}
