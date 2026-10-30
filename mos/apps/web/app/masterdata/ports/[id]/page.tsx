"use client";

// U-PORT 港口卡片（IMOS Data Center > Port Detail 对齐）。
// Tabs: Details · Berths · Aliases。
// Details = 分类 / 位置与时区 / 燃油与作业 / 合规开关族（14 项 IMOS compliance flags）。

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { DetailRail } from "@/components/masterdetail/DetailRail";
import { MasterDetail } from "@/components/masterdetail/MasterDetail";
import { useDetailRail } from "@/components/masterdetail/useRailItems";
import { RecordAttribution } from "@/components/RecordAttribution";
import { StateView } from "@/components/StateView";
import { Tabs } from "@/components/Tabs";
import { FormSection } from "@/components/form/FormPanel";
import { LookupSelect } from "@/components/LookupSelect";
import { VesselCrudGrid, type ColumnDef, type FieldDef } from "@/components/ship/VesselCrudGrid";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiPatch } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useListBackHref } from "@/lib/listContext";

type Tab = "details" | "berths" | "aliases";

const TABS: { key: Tab; labelKey: string; label: string }[] = [
  { key: "details", labelKey: "page.port.tab_details", label: "Details" },
  { key: "berths", labelKey: "page.port.tab_berths", label: "Berths" },
  { key: "aliases", labelKey: "page.port.tab_aliases", label: "Aliases" },
];

type PortGroup = "basics" | "classification" | "location" | "ops";

/** 左栏清单行 —— /masterdata/ports 列表接口的形状。 */
type PortRow = {
  id: string;
  name?: string | null;
  unlocode?: string | null;
  country?: string | null;
  port_type?: string | null;
};

/** 港口分类与地理归属 —— IMOS Port Detail 左栏。 */
const PORT_TEXT_FIELDS: { key: string; label: string; group: PortGroup; list?: string }[] = [
  { key: "port_type", label: "Port type", group: "classification", list: "port-types" },
  { key: "parent_country", label: "Parent country", group: "classification", list: "port-parent-countries" },
  { key: "port_operator", label: "Port operator", group: "classification" },
  { key: "port_area", label: "Port area", group: "classification" },
  { key: "region_code", label: "Region code", group: "classification", list: "port-regions" },
  { key: "loadline_zone", label: "Loadline zone", group: "classification", list: "port-loadline" },
  { key: "external_ref", label: "External ref no.", group: "ops" },
  { key: "fuel_zone_default", label: "Fuel zone (default)", group: "ops", list: "port-fuel-zones" },
  { key: "supported_scrubbers", label: "Supported scrubbers", group: "ops", list: "port-scrubbers" },
  { key: "alerts", label: "Alerts", group: "ops" },
  { key: "remarks", label: "Remarks", group: "ops" },
];

/** 数值列：港序号 + 双时区偏移 + 经纬度。 */
const PORT_NUM_FIELDS: { key: string; label: string; group: PortGroup; step?: string }[] = [
  { key: "port_no", label: "Port no.", group: "classification" },
  { key: "std_gmt_offset", label: "STD GMT +/−", group: "location", step: "0.25" },
  { key: "dst_gmt_offset", label: "DST GMT +/−", group: "location", step: "0.25" },
  { key: "latitude", label: "Latitude", group: "location", step: "0.000001" },
  { key: "longitude", label: "Longitude", group: "location", step: "0.000001" },
];

/** IMOS 合规开关族 —— 排放区 / 作业属性布尔位。 */
const PORT_FLAGS: { key: string; label: string }[] = [
  { key: "is_eu", label: "EU/EEA port" },
  { key: "inactive", label: "Inactive" },
  { key: "bunkering_port", label: "Bunkering port" },
  { key: "single_berth", label: "Single berth" },
  { key: "port_range", label: "Port range" },
  { key: "hide_passing_point", label: "Hide passing point ETA/ETD" },
  { key: "projection_port", label: "Projection port" },
  { key: "lightering_port", label: "Lightering port" },
  { key: "use_high_sulfur_fuel", label: "Use high sulfur fuel" },
  { key: "eu_ets_port", label: "EU ETS port of call" },
  { key: "sts_exclusion", label: "STS exclusion" },
  { key: "outermost_region", label: "Outermost region" },
  { key: "fuel_eu", label: "FuelEU port" },
  { key: "uk_ets_port", label: "UK ETS port of call" },
  { key: "uk_ets_ni", label: "UK ETS Northern Ireland" },
];

const PORT_TYPE_OPTS = ["", "seaport", "river_port", "lake_port", "canal", "anchorage", "passing_point"];
const REGION_OPTS = ["ASIA", "EURO", "USEC", "USG", "USWC", "TRANSATL", "ME", "AFR", "GLOBAL"];
const LOADLINE_OPTS = ["SUMMER", "WINTER", "TROPICAL", "FRESH", "NORTH ATLANTIC WINTER"];

function numOut(v: unknown): string {
  return v === null || v === undefined || v === "" ? "" : String(v);
}

export default function PortDetailPage() {
  const params = useParams<{ id: string }>();
  const portId = String(params.id);
  const { t } = useI18n();
  const toast = useToast();

  const [tab, setTab] = useState<Tab>("details");
  const [port, setPort] = useState<Record<string, any> | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [init, setInit] = useState<Record<string, string>>({});
  const [bools, setBools] = useState<Record<string, boolean>>({});
  const [boolInit, setBoolInit] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");

  // 左栏（IMOS 式兄弟清单）+ 顶部「返回列表」（带列表的筛选/排序/页码）
  const backHref = useListBackHref("/masterdata/ports");
  const currentRailItem = useMemo(
    () =>
      port
        ? {
            id: portId,
            title: String(port.name || port.unlocode || portId),
            meta: [String(port.unlocode || ""), String(port.country || "")],
            href: `/masterdata/ports/${portId}`,
          }
        : null,
    [port, portId],
  );
  const rail = useDetailRail<PortRow>(
    {
      endpoint: "/api/v1/masterdata/ports",
      params: { limit: 300 },
      mapRow: (r) => ({
        id: r.id,
        title: r.name || r.unlocode || r.id,
        meta: [r.unlocode || "", r.country || "", r.port_type || ""],
        href: `/masterdata/ports/${r.id}`,
      }),
    },
    currentRailItem,
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet(`/api/v1/masterdata/ports/${portId}`);
      setPort(data);
      const next: Record<string, string> = {};
      next.name = data?.name ?? "";
      next.unlocode = data?.unlocode ?? "";
      next.country = data?.country ?? "";
      next.timezone = data?.timezone ?? "UTC";
      next.holidays = Array.isArray(data?.holidays) ? data.holidays.join(", ") : "";
      for (const f of PORT_TEXT_FIELDS) next[f.key] = data?.[f.key] ?? "";
      for (const f of PORT_NUM_FIELDS) next[f.key] = numOut(data?.[f.key]);
      setForm(next);
      setInit({ ...next });
      const b: Record<string, boolean> = {};
      for (const fl of PORT_FLAGS) b[fl.key] = Boolean(data?.[fl.key]);
      setBools(b);
      setBoolInit({ ...b });
      setLoadErr("");
    } catch (ex) {
      // 取数失败必须显性报错，不能静默留空表单
      setPort(null);
      setLoadErr(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setLoading(false);
    }
  }, [portId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  // PATCH 走 exclude_unset：只提交改动的键，未提交字段不动。
  async function save() {
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {};
      if (form.name !== init.name) payload.name = form.name;
      for (const key of ["unlocode", "country", "timezone"] as const) {
        if (form[key] !== init[key]) payload[key] = form[key] || null;
      }
      if (form.holidays !== init.holidays) {
        payload.holidays = form.holidays.split(",").map((s) => s.trim()).filter(Boolean);
      }
      for (const f of PORT_TEXT_FIELDS) {
        if (form[f.key] === init[f.key]) continue;
        payload[f.key] = form[f.key] === "" ? null : form[f.key];
      }
      for (const f of PORT_NUM_FIELDS) {
        if (form[f.key] === init[f.key]) continue;
        if (form[f.key] === "") {
          payload[f.key] = null;
          continue;
        }
        // P1-24：非法数字必须中止提交（不能静默变成 NaN）
        const n = Number(form[f.key]);
        if (!Number.isFinite(n)) {
          toast.error(t("page.port.err_numeric", "{field} must be a valid number", { field: f.label }));
          setBusy(false);
          return;
        }
        payload[f.key] = n;
      }
      for (const fl of PORT_FLAGS) {
        if (bools[fl.key] === boolInit[fl.key]) continue;
        payload[fl.key] = bools[fl.key];
      }
      if (Object.keys(payload).length === 0) {
        toast.success(t("common.saved", "Saved"));
        setBusy(false);
        return;
      }
      await apiPatch(`/api/v1/masterdata/ports/${portId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }

  const groups: { key: PortGroup; labelKey: string; label: string }[] = [
    { key: "basics", labelKey: "page.port.grp_basics", label: "Basics" },
    { key: "classification", labelKey: "page.port.grp_classification", label: "Classification" },
    { key: "location", labelKey: "page.port.grp_location", label: "Location & time" },
    { key: "ops", labelKey: "page.port.grp_ops", label: "Fuel, ops & remarks" },
  ];

  const berthColumns = useMemo<ColumnDef[]>(
    () => [
      { key: "short_name", label: t("page.port.short_name", "Short name"), width: 160 },
      { key: "full_name", label: t("page.port.full_name", "Full name") },
      {
        key: "inactive",
        label: t("common.inactive", "Inactive"),
        width: 110,
        render: (r) => (r.inactive ? t("common.inactive", "Inactive") : "—"),
      },
    ],
    [t],
  );

  const aliasColumns = useMemo<ColumnDef[]>(
    () => [{ key: "alias", label: t("page.port.alias", "Alias"), minWidth: 200 }],
    [t],
  );

  // CRUD 弹窗字段定义：每次渲染都换身份会让 VesselCrudGrid 的列模型缓存失效
  const berthFields = useMemo<FieldDef[]>(
    () => [
      { key: "short_name", label: t("page.port.short_name", "Short name"), type: "text", required: true },
      { key: "full_name", label: t("page.port.full_name", "Full name"), type: "text", span: true },
      { key: "inactive", label: t("common.inactive", "Inactive"), type: "checkbox" },
    ],
    [t],
  );

  const aliasFields = useMemo<FieldDef[]>(
    () => [{ key: "alias", label: t("page.port.alias", "Alias"), type: "text", required: true }],
    [t],
  );

  function renderText(f: (typeof PORT_TEXT_FIELDS)[number]) {
    const label = t(`page.port.f_${f.key}`, f.label);
    const value = form[f.key] ?? "";
    if (f.key === "parent_country") {
      return (
        <label key={f.key}>
          {label}
          <LookupSelect dataset="countries" value={value} onChange={(v) => setForm({ ...form, parent_country: v })} />
        </label>
      );
    }
    return (
      <label key={f.key}>
        {label}
        <input
          list={f.list}
          value={value}
          onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
        />
        {f.list ? (
          <datalist id={f.list}>
            {f.key === "region_code"
              ? REGION_OPTS.map((o) => <option key={o} value={o} />)
              : f.key === "loadline_zone"
                ? LOADLINE_OPTS.map((o) => <option key={o} value={o} />)
                : f.key === "port_type"
                  ? PORT_TYPE_OPTS.slice(1).map((o) => <option key={o} value={o} />)
                  : null}
          </datalist>
        ) : null}
      </label>
    );
  }

  return (
    <AppShell
      breadcrumbs={[
        { label: t("nav.master", "Master data"), href: "/masterdata" },
        { label: t("page.ports.title", "Ports"), href: backHref },
        { label: port?.name || t("page.port.card", "Port") },
      ]}
    >
      <MasterDetail
        rail={
          <DetailRail
            items={rail.items}
            activeId={portId}
            title={t("page.ports.title", "Ports")}
            backHref={backHref}
            backLabel={t("common.back_to_list", { en: "Back to list", zh: "返回列表" })}
            loading={rail.loading}
            error={rail.error}
            onRetry={rail.reload}
          />
        }
        header={
          <>
            <PageHeader
              title={port?.name || t("page.port.card", "Port card")}
              subtitle={
                <>
                  {`${port?.unlocode ? port.unlocode : "—"} · ${port?.country || "—"} · ${port?.timezone || "—"}`} ·{" "}
                  <RecordAttribution entityType="port" entityId={portId} />
                </>
              }
              breadcrumb={[
                { label: t("nav.master", "Master data"), href: "/masterdata" },
                { label: t("page.ports.title", "Ports"), href: "/masterdata/ports" },
                { label: port?.name || t("page.port.card", "Port") },
              ]}
              actions={
                <>
                  <Link href="/masterdata/ports" className="btn btn-ghost">
                    {t("page.ports.title", "Ports")}
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
          </>
        }
      >

      {tab === "details" ? (
        <div className="panel">
          <StateView loading={loading} error={loadErr || undefined} empty={false} onRetry={() => void load()}>
          {groups.map((g) => (
            <FormSection key={g.key} title={t(g.labelKey, g.label)}>
              {g.key === "basics" ? (
                <>
                  <label>
                    {t("common.name", "Name")}
                    <input value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
                  </label>
                  <label>
                    {t("page.ports.unlocode", "UN/LOCODE")}
                    <input value={form.unlocode ?? ""} onChange={(e) => setForm({ ...form, unlocode: e.target.value })} />
                  </label>
                  <label>
                    {t("page.ports.country", "Country")}
                    <LookupSelect dataset="countries" value={form.country ?? ""} onChange={(v) => setForm({ ...form, country: v })} />
                  </label>
                  <label>
                    {t("page.ports.timezone", "Time zone")}
                    <LookupSelect
                      dataset="timezones"
                      value={form.timezone || "UTC"}
                      onChange={(v) => setForm({ ...form, timezone: v })}
                      allowEmpty={false}
                    />
                  </label>
                  <label className="span-all">
                    {t("page.ports.holidays", "Holidays")}
                    <input
                      value={form.holidays ?? ""}
                      onChange={(e) => setForm({ ...form, holidays: e.target.value })}
                      placeholder={t("page.ports.holidays_ph", "YYYY-MM-DD, YYYY-MM-DD")}
                    />
                  </label>
                </>
              ) : null}

              {g.key === "classification" || g.key === "ops"
                ? PORT_TEXT_FIELDS.filter((f) => f.group === g.key).map(renderText)
                : null}

              {g.key === "classification"
                ? PORT_NUM_FIELDS.filter((f) => f.group === g.key).map((f) => (
                    <label key={f.key}>
                      {t(`page.port.f_${f.key}`, f.label)}
                      <input
                        type="number"
                        step={f.step}
                        value={form[f.key] ?? ""}
                        onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                      />
                    </label>
                  ))
                : null}

              {g.key === "location"
                ? PORT_NUM_FIELDS.filter((f) => f.group === g.key).map((f) => (
                    <label key={f.key}>
                      {t(`page.port.f_${f.key}`, f.label)}
                      <input
                        type="number"
                        step={f.step}
                        value={form[f.key] ?? ""}
                        onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                      />
                    </label>
                  ))
                : null}
            </FormSection>
          ))}

          <FormSection title={t("page.port.grp_compliance", "Compliance flags")}>
            <div className="check-grid span-all">
              {PORT_FLAGS.map((fl) => (
                <label key={fl.key} className="check-row">
                  <input
                    type="checkbox"
                    checked={Boolean(bools[fl.key])}
                    onChange={(e) => setBools({ ...bools, [fl.key]: e.target.checked })}
                  />
                  {t(`page.port.flag_${fl.key}`, fl.label)}
                </label>
              ))}
            </div>
          </FormSection>
          </StateView>
        </div>
      ) : null}

      {tab === "berths" ? (
        <VesselCrudGrid
          vesselId={portId}
          path="berths"
          basePath={`/api/v1/masterdata/ports/${portId}/berths`}
          title={t("page.port.tab_berths", "Berths")}
          addLabel={t("page.port.add_berth", "Add berth")}
          emptyText={t("page.port.no_berths", "No berths yet")}
          columns={berthColumns}
          fields={berthFields}
        />
      ) : null}

      {tab === "aliases" ? (
        <VesselCrudGrid
          vesselId={portId}
          path="aliases"
          basePath={`/api/v1/masterdata/ports/${portId}/aliases`}
          title={t("page.port.tab_aliases", "Aliases")}
          addLabel={t("page.port.add_alias", "Add alias")}
          emptyText={t("page.port.no_aliases", "No aliases yet")}
          columns={aliasColumns}
          fields={aliasFields}
        />
      ) : null}
      </MasterDetail>
    </AppShell>
  );
}
