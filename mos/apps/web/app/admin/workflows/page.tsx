"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Step = { name: string; role_code: string };
type Wf = {
  id: string;
  code: string;
  name: string;
  entity_type: string;
  steps: { steps?: Step[] } | Step[];
  enabled: boolean;
};
type RoleRow = { code: string; name: string };

const ENTITY_TYPES = ["charter", "invoice", "pda", "claim"];

function normalizeSteps(raw: Wf["steps"]): Step[] {
  if (Array.isArray(raw)) return raw as Step[];
  if (raw && typeof raw === "object" && Array.isArray((raw as any).steps)) return (raw as any).steps;
  return [];
}

export default function WorkflowsAdminPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Wf[]>([]);
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [msg, setMsg] = useState("");
  const [open, setOpen] = useState<Wf | null>(null);
  const [creating, setCreating] = useState(false);
  const [edit, setEdit] = useState({
    code: "",
    name: "",
    entity_type: "charter",
    enabled: true,
    steps: [{ name: "Review", role_code: "management" }] as Step[],
  });
  const [saving, setSaving] = useState(false);

  async function load() {
    const [w, r] = await Promise.all([apiGet("/api/v1/admin/workflows"), apiGet("/api/v1/admin/roles")]);
    setRows(w);
    setRoles(r.filter((x: RoleRow) => x.code !== "platform_admin"));
  }

  useEffect(() => {
    load().catch(() => setMsg(t("page.wf.admin_required", "需要租户管理员")));
  }, [t]);

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setEdit({
      code: "",
      name: "",
      entity_type: "charter",
      enabled: true,
      steps: [{ name: t("page.wf.step_review", "审核"), role_code: "management" }],
    });
  }

  function openRow(r: Wf) {
    setCreating(false);
    setOpen(r);
    setEdit({
      code: r.code,
      name: r.name,
      entity_type: r.entity_type,
      enabled: r.enabled,
      steps: normalizeSteps(r.steps).length
        ? normalizeSteps(r.steps)
        : [{ name: "Review", role_code: "management" }],
    });
  }

  function updateStep(i: number, patch: Partial<Step>) {
    setEdit((e) => ({
      ...e,
      steps: e.steps.map((s, idx) => (idx === i ? { ...s, ...patch } : s)),
    }));
  }

  async function save() {
    setSaving(true);
    try {
      const steps = edit.steps.filter((s) => s.name.trim() && s.role_code);
      if (!steps.length) throw new Error("steps");
      if (creating || !open) {
        await apiPost("/api/v1/admin/workflows", {
          code: edit.code.trim(),
          name: edit.name.trim(),
          entity_type: edit.entity_type,
          steps,
          enabled: edit.enabled,
        });
      } else {
        await apiPatch(`/api/v1/admin/workflows/${open.id}`, {
          name: edit.name.trim(),
          entity_type: edit.entity_type,
          steps,
          enabled: edit.enabled,
        });
      }
      setMsg(t("common.saved", "已保存"));
      setOpen(null);
      setCreating(false);
      await load();
    } catch {
      setMsg(t("common.failed", "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  async function toggleEnabled(r: Wf, enabled: boolean, e: React.MouseEvent) {
    e.stopPropagation();
    await apiPatch(`/api/v1/admin/workflows/${r.id}`, { enabled });
    await load();
  }

  const modalOpen = creating || Boolean(open);

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.wf.title", "企业工作流")}</h1>
          <p className="page-sub">
            {t(
              "page.wf.sub",
              "配置审批步骤（按角色）。启用后，租约提交审批 / 发票提交审批会进入待办箱。",
            )}{" "}
            <Link href="/workflows/inbox">{t("nav.inbox", "审批待办")}</Link>
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={openCreate}>
          {t("page.wf.create", "新建工作流")}
        </button>
      </div>
      {msg ? <p>{msg}</p> : null}
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code", "编码")}</th>
              <th>{t("common.name", "名称")}</th>
              <th>{t("page.wf.entity", "业务对象")}</th>
              <th>{t("page.wf.steps", "步骤")}</th>
              <th>{t("page.wf.enabled", "启用")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const steps = normalizeSteps(r.steps);
              return (
                <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                  <td>{r.code}</td>
                  <td>{r.name}</td>
                  <td>{r.entity_type}</td>
                  <td>
                    {steps.map((s, i) => (
                      <span key={i} className="muted" style={{ display: "block", fontSize: "0.85rem" }}>
                        {i + 1}. {s.name} → {s.role_code}
                      </span>
                    ))}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={r.enabled}
                      onChange={(e) => toggleEnabled(r, e.target.checked, e as any)}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={modalOpen}
        title={creating ? t("page.wf.create", "新建工作流") : t("page.wf.edit", "编辑工作流")}
        onClose={() => {
          setOpen(null);
          setCreating(false);
        }}
        onSave={save}
        saving={saving}
      >
        {creating ? (
          <label>
            {t("common.code", "编码")}
            <input value={edit.code} onChange={(e) => setEdit({ ...edit, code: e.target.value })} required />
          </label>
        ) : (
          <p className="muted">
            {t("common.code", "编码")}: <code>{edit.code}</code>
          </p>
        )}
        <label>
          {t("common.name", "名称")}
          <input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required />
        </label>
        <label>
          {t("page.wf.entity", "业务对象")}
          <select value={edit.entity_type} onChange={(e) => setEdit({ ...edit, entity_type: e.target.value })}>
            {ENTITY_TYPES.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={edit.enabled}
            onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })}
          />
          {t("page.wf.enabled", "启用")}
        </label>
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <strong>{t("page.wf.steps", "审批步骤")}</strong>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() =>
                setEdit({
                  ...edit,
                  steps: [...edit.steps, { name: "", role_code: roles[0]?.code || "tenant_admin" }],
                })
              }
            >
              {t("page.wf.add_step", "+ 步骤")}
            </button>
          </div>
          {edit.steps.map((s, i) => (
            <div key={i} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
              <input
                placeholder={t("page.wf.step_name", "步骤名称")}
                value={s.name}
                onChange={(e) => updateStep(i, { name: e.target.value })}
                style={{ flex: 1, minWidth: 120 }}
              />
              <select value={s.role_code} onChange={(e) => updateStep(i, { role_code: e.target.value })}>
                {roles.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.name} ({r.code})
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={edit.steps.length <= 1}
                onClick={() => setEdit({ ...edit, steps: edit.steps.filter((_, idx) => idx !== i) })}
              >
                ×
              </button>
            </div>
          ))}
          <p className="muted" style={{ fontSize: "0.85rem" }}>
            {t(
              "page.wf.hint",
              "启用后：charter→pending_approval、invoice→pending_approval 会自动启动；跳过审批直接签发会被拦截。",
            )}
          </p>
        </div>
      </RecordModal>
    </AppShell>
  );
}
