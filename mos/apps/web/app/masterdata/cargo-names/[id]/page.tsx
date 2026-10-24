"use client";

// U-CARGO 货物品名卡片（IMOS Data Center > Cargo Names 对齐）。
// Tabs: Details · Properties。
// Details = 品名标识 / 危险品（IMSBC + IMDG）/ 积载与 API / 商务条款 四组。

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordAttribution } from "@/components/RecordAttribution";
import { StateView } from "@/components/StateView";
import { Tabs } from "@/components/Tabs";
import { FormSection } from "@/components/form/FormPanel";
import { VesselCrudGrid, type ColumnDef, type FieldDef } from "@/components/ship/VesselCrudGrid";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiPatch } from "@/lib/api";
import { msgOf } from "@/lib/errors";

type Tab = "details" | "properties";

const TABS: { key: Tab; labelKey: string; label: string }[] = [
  { key: "details", labelKey: "page.cargo.tab_details", label: "Details" },
  { key: "properties", labelKey: "page.cargo.tab_properties", label: "Properties" },
];

type CargoGroup = "identity" | "danger" | "stowage" | "commercial";

/** 文本字段 —— key 与 CargoNameIn 列名 1:1。 */
const TEXT_FIELDS: { key: string; label: string; group: CargoGroup }[] = [
  { key: "full_name", label: "Full name", group: "identity" },
  { key: "cargo_class", label: "Cargo class", group: "identity" },
  { key: "product_code", label: "Product code", group: "identity" },
  { key: "description", label: "Description", group: "identity" },
  // 危险品（IMSBC + IMDG）
  { key: "imo_name", label: "IMO name", group: "danger" },
  { key: "ibc_code", label: "IBC code", group: "danger" },
  { key: "imsbc_code", label: "IMSBC code", group: "danger" },
  { key: "un_number", label: "UN no.", group: "danger" },
  { key: "imdg_class", label: "IMDG class", group: "danger" },
  // 商务（default_cp_unit 单独渲染 unit datalist，见下方 special-case）
  { key: "capacity_basis", label: "Capacity basis", group: "commercial" },
  { key: "bill_by", label: "Bill by", group: "commercial" },
];

const NUM_FIELDS: { key: string; label: string; group: CargoGroup; step?: string }[] = [
  { key: "stow_factor_m3_mt", label: "Stow factor (m3/MT)", group: "stowage", step: "0.0001" },
  { key: "stow_factor_ft3_mt", label: "Stow factor (ft3/MT)", group: "stowage", step: "0.001" },
  { key: "api_gravity", label: "API gravity", group: "stowage", step: "0.1" },
];

const BOOL_FIELDS: { key: string; label: string; group: CargoGroup }[] = [
  { key: "dangerous", label: "Dangerous", group: "danger" },
  { key: "special_handling", label: "Special handling", group: "danger" },
  { key: "pre_clearance_us_ca", label: "Pre-clearance US / CA", group: "danger" },
  { key: "inactive", label: "Inactive", group: "commercial" },
];

const UNIT_OPTS = ["MT", "LT", "BBL", "CBM", "LTR", "PCS", "TU"];

function numOut(v: unknown): string {
  return v === null || v === undefined || v === "" ? "" : String(v);
}

export default function CargoNameDetailPage() {
  const params = useParams<{ id: string }>();
  const cargoId = String(params.id);
  const { t } = useI18n();
  const toast = useToast();

  const [tab, setTab] = useState<Tab>("details");
  const [cargo, setCargo] = useState<Record<string, any> | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [init, setInit] = useState<Record<string, string>>({});
  const [bools, setBools] = useState<Record<string, boolean>>({});
  const [boolInit, setBoolInit] = useState<Record<string, boolean>>({});
  const [groups, setGroups] = useState<{ id: string; name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [groupsErr, setGroupsErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet(`/api/v1/masterdata/cargo-names/${cargoId}`);
      setCargo(data);
      const next: Record<string, string> = {};
      next.short_name = data?.short_name ?? "";
      next.cargo_group_id = data?.cargo_group_id ?? "";
      for (const f of TEXT_FIELDS) next[f.key] = data?.[f.key] ?? "";
      for (const f of NUM_FIELDS) next[f.key] = numOut(data?.[f.key]);
      setForm(next);
      setInit({ ...next });
      const b: Record<string, boolean> = {};
      for (const f of BOOL_FIELDS) b[f.key] = Boolean(data?.[f.key]);
      setBools(b);
      setBoolInit({ ...b });
      setLoadErr("");
    } catch (ex) {
      // 取数失败必须显性报错，不能静默留空表单
      setCargo(null);
      setLoadErr(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setLoading(false);
    }
  }, [cargoId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    apiGet("/api/v1/masterdata/cargo-groups")
      .then((d: any) => {
        setGroups(Array.isArray(d) ? d : []);
        setGroupsErr("");
      })
      // 参考数据失败：不让整页报错，但必须可见（分组下拉会空）
      .catch((ex) => {
        setGroups([]);
        setGroupsErr(msgOf(ex));
      });
  }, []);

  // PATCH 走 exclude_unset：只提交改动的键，未提交字段不动。
  async function save() {
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {};
      if (form.short_name !== init.short_name) payload.short_name = form.short_name;
      if (form.cargo_group_id !== init.cargo_group_id) payload.cargo_group_id = form.cargo_group_id || null;
      for (const f of TEXT_FIELDS) {
        if (form[f.key] === init[f.key]) continue;
        payload[f.key] = form[f.key] === "" ? null : form[f.key];
      }
      for (const f of NUM_FIELDS) {
        if (form[f.key] === init[f.key]) continue;
        if (form[f.key] === "") {
          payload[f.key] = null;
          continue;
        }
        // P1-24：非法数字必须中止提交（不能静默变成 NaN）
        const n = Number(form[f.key]);
        if (!Number.isFinite(n)) {
          toast.error(t("page.cargo.err_numeric", "{field} must be a valid number", { field: f.label }));
          setBusy(false);
          return;
        }
        payload[f.key] = n;
      }
      for (const f of BOOL_FIELDS) {
        if (bools[f.key] === boolInit[f.key]) continue;
        payload[f.key] = bools[f.key];
      }
      if (Object.keys(payload).length === 0) {
        toast.success(t("common.saved", "Saved"));
        setBusy(false);
        return;
      }
      await apiPatch(`/api/v1/masterdata/cargo-names/${cargoId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }

  const secGroups: { key: CargoGroup; labelKey: string; label: string }[] = [
    { key: "identity", labelKey: "page.cargo.grp_identity", label: "Name & classification" },
    { key: "danger", labelKey: "page.cargo.grp_danger", label: "Dangerous goods" },
    { key: "stowage", labelKey: "page.cargo.grp_stowage", label: "Stowage & API" },
    { key: "commercial", labelKey: "page.cargo.grp_commercial", label: "Commercial" },
  ];

  const propertyColumns = useMemo<ColumnDef[]>(
    () => [
      { key: "title", label: t("common.title", "Title"), width: 220 },
      { key: "value", label: t("common.value", "Value") },
    ],
    [t],
  );

  // CRUD 弹窗字段定义：每次渲染都换身份会让 VesselCrudGrid 的列模型缓存失效
  const propertyFields = useMemo<FieldDef[]>(
    () => [
      { key: "title", label: t("common.title", "Title"), type: "text", required: true },
      { key: "value", label: t("common.value", "Value"), type: "text", span: true },
    ],
    [t],
  );

  return (
    <AppShell>
      <PageHeader
        title={cargo?.short_name || t("page.cargo.card", "Cargo name")}
        subtitle={
          <>
            {`${cargo?.full_name || "—"} · ${groups.find((g) => g.id === cargo?.cargo_group_id)?.name || "—"}`} ·{" "}
            <RecordAttribution entityType="cargo_name" entityId={cargoId} />
          </>
        }
        breadcrumb={[
          { label: t("nav.master", "Master data"), href: "/masterdata" },
          { label: t("page.cargo_names.title", "Cargo names"), href: "/masterdata/cargo-names" },
          { label: cargo?.short_name || t("page.cargo.card", "Cargo name") },
        ]}
        actions={
          <>
            <Link href="/masterdata/cargo-names" className="btn btn-ghost">
              {t("page.cargo_names.title", "Cargo names")}
            </Link>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={save}>
              {busy ? t("common.saving", "Saving…") : t("common.save", "Save")}
            </button>
          </>
        }
      />

      <Tabs
        items={TABS.map((tb) => ({ key: tb.key, label: t(tb.labelKey, tb.label) }))}
        value={tab}
        onChange={(k) => setTab(k as Tab)}
        variant="line"
      />

      {tab === "details" ? (
        <div className="panel">
          {groupsErr ? (
            <p className="flash-warn">
              {t("page.cargo_names.groups_load_failed", "Cargo groups could not be loaded — the group picker may be incomplete.")}{" "}
              {groupsErr}
            </p>
          ) : null}
          <StateView loading={loading} error={loadErr || undefined} empty={false} onRetry={() => void load()}>
          {secGroups.map((g) => (
            <FormSection key={g.key} title={t(g.labelKey, g.label)}>
              {g.key === "identity" ? (
                <>
                  <label>
                    {t("page.cargo.short_name", "Short name")}
                    <input
                      value={form.short_name ?? ""}
                      onChange={(e) => setForm({ ...form, short_name: e.target.value })}
                      required
                    />
                  </label>
                  <label>
                    {t("page.cargo.group", "Cargo group")}
                    <select
                      value={form.cargo_group_id ?? ""}
                      onChange={(e) => setForm({ ...form, cargo_group_id: e.target.value })}
                    >
                      <option value="">{t("common.none", "None")}</option>
                      {groups.map((grp) => (
                        <option key={grp.id} value={grp.id}>
                          {grp.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              ) : null}

              {TEXT_FIELDS.filter((f) => f.group === g.key).map((f) => (
                <label key={f.key}>
                  {t(`page.cargo.f_${f.key}`, f.label)}
                  <input value={form[f.key] ?? ""} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })} />
                </label>
              ))}

              {NUM_FIELDS.filter((f) => f.group === g.key).map((f) => (
                <label key={f.key}>
                  {t(`page.cargo.f_${f.key}`, f.label)}
                  <input
                    type="number"
                    step={f.step}
                    value={form[f.key] ?? ""}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  />
                </label>
              ))}

              {g.key === "commercial" ? (
                <label>
                  {t("page.cargo.f_default_cp_unit", "Default CP unit")}
                  <input list="cargo-units" value={form.default_cp_unit ?? ""} onChange={(e) => setForm({ ...form, default_cp_unit: e.target.value })} />
                  <datalist id="cargo-units">
                    {UNIT_OPTS.map((u) => (
                      <option key={u} value={u} />
                    ))}
                  </datalist>
                </label>
              ) : null}

              {BOOL_FIELDS.filter((f) => f.group === g.key).map((f) => (
                <label key={f.key} className="check-row">
                  <input
                    type="checkbox"
                    checked={Boolean(bools[f.key])}
                    onChange={(e) => setBools({ ...bools, [f.key]: e.target.checked })}
                  />
                  {t(`page.cargo.flag_${f.key}`, f.label)}
                </label>
              ))}
            </FormSection>
          ))}
          </StateView>
        </div>
      ) : null}

      {tab === "properties" ? (
        <VesselCrudGrid
          vesselId={cargoId}
          path="properties"
          basePath={`/api/v1/masterdata/cargo-names/${cargoId}/properties`}
          title={t("page.cargo.tab_properties", "Properties")}
          addLabel={t("page.cargo.add_property", "Add property")}
          emptyText={t("page.cargo.no_properties", "No properties yet")}
          columns={propertyColumns}
          fields={propertyFields}
        />
      ) : null}
    </AppShell>
  );
}
