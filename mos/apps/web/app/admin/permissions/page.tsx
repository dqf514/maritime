"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { RecordModal } from "@/components/RecordModal";
import { Tabs, type TabItem } from "@/components/Tabs";
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type FeatureRow = { code: string; name: string; module: string };
type MatrixRow = { role_code: string; feature_code: string; allowed: boolean };

type EntityRegistryItem = { entity: string; fields: string[] };
type FieldRule = {
  id: string;
  entity: string;
  field: string;
  role: string;
  mode: string;
  active: boolean;
};

type TabKey = "features" | "fields";

const MODES = ["read", "write", "hidden"] as const;

export default function PermissionsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [tab, setTab] = useState<TabKey>("features");

  // ── Feature matrix (tab 1) ──
  const [catalog, setCatalog] = useState<FeatureRow[]>([]);
  const [matrix, setMatrix] = useState<MatrixRow[]>([]);
  const [roles, setRoles] = useState<Array<{ code: string }>>([]);

  // ── Field permissions (tab 2) ──
  const [registry, setRegistry] = useState<EntityRegistryItem[]>([]);
  const [rules, setRules] = useState<FieldRule[]>([]);
  const [fpEntity, setFpEntity] = useState("");
  const [fpRole, setFpRole] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [edit, setEdit] = useState({ entity: "", field: "", role: "", mode: "read" });

  async function load() {
    const [c, m, r] = await Promise.all([
      apiGet("/api/v1/admin/features/catalog"),
      apiGet("/api/v1/admin/features/matrix"),
      apiGet("/api/v1/admin/roles"),
    ]);
    setCatalog(c);
    setMatrix(m);
    setRoles(r);
  }

  async function loadFieldPerms() {
    const [ent, rl] = await Promise.all([
      apiGet("/api/v1/field-permissions/entities"),
      apiGet("/api/v1/field-permissions"),
    ]);
    setRegistry(ent);
    setRules(rl);
    if (!fpEntity && ent.length) setFpEntity(ent[0].entity);
  }

  useEffect(() => {
    load().catch(() => toast.error(t("page.perm.admin_required", "需要租户管理员")));
    loadFieldPerms().catch(() => toast.error(t("fp.load_fail", "Failed to load field permissions")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t]);

  async function toggle(role_code: string, feature_code: string, allowed: boolean) {
    await apiPut("/api/v1/admin/features", { role_code, feature_code, allowed });
    toast.success(`${role_code} · ${feature_code} = ${allowed ? t("page.perm.allow", "允许") : t("page.perm.deny", "拒绝")}`);
    await load();
  }

  const roleCodes = roles.map((r) => r.code).filter((c) => c !== "platform_admin");

  function allowedFor(role: string, featureCode: string): boolean {
    if (role === "tenant_admin") return true;
    const hit = matrix.find((m) => m.role_code === role && m.feature_code === featureCode);
    return hit ? hit.allowed : true;
  }

  const columns: ColumnDef<FeatureRow>[] = [
    {
      key: "feature",
      title: t("page.perm.feature", "功能"),
      minWidth: 220,
      value: (r) => r.name,
      render: (_v, r) => (
        <span>
          <b>{r.name}</b>
          <div className="muted">
            {r.code} · {r.module}
          </div>
        </span>
      ),
    },
    ...roleCodes.map(
      (role): ColumnDef<FeatureRow> => ({
        key: role,
        title: role,
        width: 110,
        align: "center",
        value: (r) => allowedFor(role, r.code),
        render: (_v, r) => (
          <input
            type="checkbox"
            checked={allowedFor(role, r.code)}
            disabled={role === "tenant_admin"}
            onChange={(e) =>
              toggle(role, r.code, e.target.checked).catch(() =>
                toast.error(t("page.perm.update_fail", "更新失败")),
              )
            }
          />
        ),
      }),
    ),
  ];

  // ── Field-permission helpers ──
  const fieldOptions = useMemo(() => {
    const hit = registry.find((e) => e.entity === edit.entity);
    return hit?.fields ?? [];
  }, [registry, edit.entity]);

  const visibleRules = useMemo(
    () =>
      rules.filter(
        (r) =>
          (!fpEntity || r.entity === fpEntity) &&
          (!fpRole || r.role === fpRole),
      ),
    [rules, fpEntity, fpRole],
  );

  const roleOptions = useMemo(() => {
    const set = new Set<string>(roleCodes);
    rules.forEach((r) => set.add(r.role));
    return [...set].sort();
  }, [rules, roleCodes]);

  async function changeMode(row: FieldRule, mode: string) {
    try {
      await apiPatch(`/api/v1/field-permissions/${row.id}`, { mode });
      toast.success(t("fp.updated", "Rule updated"));
      await loadFieldPerms();
    } catch {
      toast.error(t("fp.update_fail", "Failed to update rule"));
    }
  }

  async function removeRule(row: FieldRule) {
    try {
      await apiDelete(`/api/v1/field-permissions/${row.id}`);
      toast.success(t("fp.deleted", "Rule deleted"));
      await loadFieldPerms();
    } catch {
      toast.error(t("fp.delete_fail", "Failed to delete rule"));
    }
  }

  async function saveRule(e: FormEvent) {
    e.preventDefault();
    if (!edit.entity || !edit.field || !edit.role) {
      toast.error(t("fp.required", "Entity, field and role are required"));
      return;
    }
    setSaving(true);
    try {
      await apiPost("/api/v1/field-permissions", edit);
      toast.success(t("fp.created", "Rule created"));
      setAddOpen(false);
      setEdit({ entity: fpEntity || "", field: "", role: "", mode: "read" });
      await loadFieldPerms();
    } catch {
      toast.error(t("fp.create_fail", "Failed to create rule (duplicate?)"));
    } finally {
      setSaving(false);
    }
  }

  const fpColumns: ColumnDef<FieldRule>[] = [
    {
      key: "field",
      title: t("fp.field", "字段"),
      minWidth: 180,
      value: (r) => r.field,
      render: (_v, r) => (
        <span>
          <b>{r.field}</b>
          <div className="muted">{r.entity}</div>
        </span>
      ),
    },
    {
      key: "role",
      title: t("fp.role", "角色"),
      width: 140,
      value: (r) => r.role,
    },
    {
      key: "mode",
      title: t("fp.mode", "模式"),
      width: 140,
      value: (r) => r.mode,
      render: (_v, r) => (
        <select value={r.mode} onChange={(e) => changeMode(r, e.target.value)}>
          {MODES.map((m) => (
            <option key={m} value={m}>
              {t(`fp.mode.${m}`, m)}
            </option>
          ))}
        </select>
      ),
    },
    {
      key: "active",
      title: t("fp.active", "启用"),
      width: 80,
      align: "center",
      value: (r) => r.active,
      render: (_v, r) => <span>{r.active ? t("common.yes", "是") : t("common.no", "否")}</span>,
    },
    {
      key: "actions",
      title: t("common.actions", "操作"),
      width: 90,
      align: "center",
      value: (r) => r.id,
      render: (_v, r) => (
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => removeRule(r)}>
          {t("common.delete", "删除")}
        </button>
      ),
    },
  ];

  const tabs: TabItem[] = [
    { key: "features", label: t("page.perm.tab.features", "Feature matrix") },
    { key: "fields", label: t("fp.tab", "Field permissions") },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("page.perm.title", "功能权限")}
        subtitle={t(
          "page.perm.sub",
          "按角色精细控制能力。未配置的单元格默认允许（继承角色）；取消勾选会写入拒绝并在业务 API 生效。租户管理员始终放行。",
        )}
      />
      <Tabs items={tabs} value={tab} onChange={(k) => setTab(k as TabKey)} variant="line" />

      {tab === "features" ? (
        <div className="panel" style={{ overflowX: "auto", marginTop: "1rem" }}>
          <DataGrid<FeatureRow>
            columns={columns}
            data={catalog}
            rowKey={(r) => r.code}
            storageKey="admin_permissions_grid"
            emptyText={t("common.none", "无")}
            showFooter={false}
          />
        </div>
      ) : (
        <div style={{ marginTop: "1rem", display: "grid", gap: "1rem" }}>
          <div className="panel" style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "flex-end" }}>
            <label style={{ minWidth: 160 }}>
              {t("fp.entity", "实体")}
              <select value={fpEntity} onChange={(e) => setFpEntity(e.target.value)}>
                <option value="">{t("fp.all_entities", "All entities")}</option>
                {registry.map((e) => (
                  <option key={e.entity} value={e.entity}>
                    {e.entity}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ minWidth: 160 }}>
              {t("fp.role", "角色")}
              <select value={fpRole} onChange={(e) => setFpRole(e.target.value)}>
                <option value="">{t("fp.all_roles", "All roles")}</option>
                {roleOptions.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                setEdit({ entity: fpEntity || registry[0]?.entity || "", field: "", role: fpRole || "", mode: "read" });
                setAddOpen(true);
              }}
            >
              {t("fp.add", "+ Add rule")}
            </button>
          </div>

          <div className="panel">
            <DataGrid<FieldRule>
              columns={fpColumns}
              data={visibleRules}
              rowKey={(r) => r.id}
              storageKey="admin_field_perms_grid"
              emptyText={t("fp.empty", "No field rules — all fields writable")}
              showFooter={false}
            />
          </div>

          <RecordModal
            open={addOpen}
            title={t("fp.add_title", "Add field permission")}
            onClose={() => setAddOpen(false)}
            onSave={saveRule}
            canDelete={false}
            saving={saving}
          >
            <label>
              {t("fp.entity", "实体")}
              <select
                value={edit.entity}
                onChange={(e) => setEdit({ ...edit, entity: e.target.value, field: "" })}
                required
              >
                <option value="">—</option>
                {registry.map((e) => (
                  <option key={e.entity} value={e.entity}>
                    {e.entity}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("fp.field", "字段")}
              <select value={edit.field} onChange={(e) => setEdit({ ...edit, field: e.target.value })} required>
                <option value="">—</option>
                {fieldOptions.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("fp.role", "角色")}
              <select value={edit.role} onChange={(e) => setEdit({ ...edit, role: e.target.value })} required>
                <option value="">—</option>
                {roleOptions.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("fp.mode", "模式")}
              <select value={edit.mode} onChange={(e) => setEdit({ ...edit, mode: e.target.value })}>
                {MODES.map((m) => (
                  <option key={m} value={m}>
                    {t(`fp.mode.${m}`, m)}
                  </option>
                ))}
              </select>
            </label>
          </RecordModal>
        </div>
      )}
    </AppShell>
  );
}
