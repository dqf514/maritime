"use client";

import { RefreshButton } from "@/components/RefreshButton";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf, handled } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";

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
  const toast = useToast();
  const [rows, setRows] = useState<Unit[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [open, setOpen] = useState<Unit | null>(null);
  const [creating, setCreating] = useState(false);
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
  // 主列表加载态 / 错误态（P1-4）：失败不能静默变成「无数据」
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  // 成员列表属于附属数据，失败要有可见提示但不能整页报错
  const [membersErr, setMembersErr] = useState("");

  async function load() {
    setLoading(true);
    setLoadErr("");
    try {
      const [units, us] = await Promise.all([apiGet("/api/v1/admin/org-units"), apiGet("/api/v1/admin/users")]);
      setRows(units);
      setUsers(us);
    } catch (e) {
      setRows([]);
      setLoadErr(msgOf(e, t("page.org.admin_required", "需要租户管理员")));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t]);

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setMembers([]);
    setEdit({
      code: "",
      name: "",
      unit_type: "dept",
      status: "active",
      parent_id: rows.find((r) => r.unit_type === "company")?.id || "",
      manager_user_id: "",
    });
  }

  useListHotkeys(openCreate);

  function closeModal() {
    setOpen(null);
    setCreating(false);
  }

  async function openRow(r: Unit) {
    setCreating(false);
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
      setMembersErr("");
      setMembers(await apiGet(`/api/v1/admin/org-units/${r.id}/members`));
    } catch (e) {
      setMembers([]);
      setMembersErr(msgOf(e, t("common.failed", "失败")));
    }
  }

  async function save() {
    setSaving(true);
    try {
      if (creating || !open) {
        await apiPost("/api/v1/admin/org-units", {
          code: edit.code,
          name: edit.name,
          unit_type: edit.unit_type,
          parent_id: edit.parent_id || null,
          manager_user_id: edit.manager_user_id || null,
        });
        toast.success(t("common.created", "已创建"));
      } else {
        await apiPatch(`/api/v1/admin/org-units/${open.id}`, {
          code: edit.code,
          name: edit.name,
          unit_type: edit.unit_type,
          status: edit.status,
          parent_id: edit.parent_id || null,
          manager_user_id: edit.manager_user_id || null,
        });
        toast.success(t("common.saved", "已保存"));
      }
      closeModal();
      await load();
    } catch {
      toast.error(t("common.failed", "失败"));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/admin/org-units/${open.id}`);
      toast.success(t("common.recycled", "已移入回收站"));
      closeModal();
      await load();
    } catch (e) {
      toast.error(msgOf(e, t("common.failed", "失败")));
    } finally {
      setSaving(false);
    }
  }

  const parentLabel = useCallback(
    (id: string | null) => {
      if (!id) return "—";
      const p = rows.find((r) => r.id === id);
      return p ? `${p.code} · ${p.name}` : id.slice(0, 8);
    },
    [rows],
  );

  const columns = useMemo<ColumnDef<Unit>[]>(
    () => [
      { key: "code", title: t("common.code", "编码"), width: 120, value: (r) => r.code },
      { key: "name", title: t("common.name", "名称"), minWidth: 160, value: (r) => r.name },
      { key: "unit_type", title: t("common.type", "类型"), width: 100, value: (r) => r.unit_type },
      {
        key: "parent",
        title: t("page.org.parent", "上级"),
        minWidth: 180,
        value: (r) => parentLabel(r.parent_id),
      },
      {
        key: "manager",
        title: t("page.org.manager", "负责人"),
        width: 140,
        value: (r) => r.manager_name || "",
        render: (_v, r) => <span>{r.manager_name || "—"}</span>,
      },
      {
        key: "member_count",
        title: t("page.org.members", "成员数"),
        width: 90,
        align: "right",
        value: (r) => r.member_count ?? 0,
      },
    ],
    [t, parentLabel],
  );

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.admin", "Administration") }]}
        title={t("page.org.title", "组织架构")}
        subtitle={
          <>
            {t("page.org.sub", "总部、部门与团队。人员归属在「用户与角色」中设置，此处可查看成员与负责人。")}{" "}
            <Link href="/admin/users">{t("page.users.title", "用户与角色")}</Link>
          </>
        }
        actions={
          <Link href="/settings/recycle" className="btn btn-ghost">
            {t("nav.recycle", "回收站")}
          </Link>
        }
      />
      <Toolbar>
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.org.add_dept", "新建部门")}
        </button>
        <RefreshButton label={t("common.refresh", "Refresh")} className="btn btn-sm" onClick={() => load().catch(handled)} />
      </Toolbar>
      <div className="panel">
        <StateView
          loading={loading}
          error={loadErr || undefined}
          empty={!loadErr && !rows.length}
          emptyText={t("common.none", "无")}
          onRetry={() => void load()}
        >
          <DataGrid<Unit>
            columns={columns}
            data={rows}
            rowKey={(r) => r.id}
            storageKey="admin_org_units_grid"
            emptyText={t("common.none", "无")}
            showFooter={false}
            onRowClick={(r) => openRow(r)}
            onRowDoubleClick={(r) => openRow(r)}
          />
        </StateView>
      </div>

      <RecordModal
        open={creating || Boolean(open)}
        title={creating ? t("page.org.add_dept", "新建部门") : t("page.org.edit", "编辑组织单元")}
        onClose={closeModal}
        onSave={save}
        onDelete={creating ? undefined : remove}
        canDelete={!creating}
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
        {!creating ? (
          <label>
            {t("common.status", "状态")}
            <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
              <option value="active">active</option>
              <option value="disabled">disabled</option>
            </select>
          </label>
        ) : null}
        {!creating ? (
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
              {membersErr ? <li className="flash-err">{membersErr}</li> : null}
              {!members.length && !membersErr ? <li className="muted">{t("page.org.no_members", "暂无成员 — 请在用户管理中分配部门")}</li> : null}
            </ul>
          </div>
        ) : null}
      </RecordModal>
    </AppShell>
  );
}
