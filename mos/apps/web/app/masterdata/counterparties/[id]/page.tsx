"use client";

// U-PARTY 对手方卡片（IMOS Data Center > Address Book Detail 对齐）。
// Tabs: Details · Contacts · Properties · Bank。
// Details = 身份编号 / 地址与联系 / 授信 / 合规 / GL 科目五组；
// Address Types 是 IMOS 的多角色集合（Agents + Brokers + Charterers + Owners + Company Info + Misc）。

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { RecordAttribution } from "@/components/RecordAttribution";
import { StateView } from "@/components/StateView";
import { Tabs } from "@/components/Tabs";
import { FormSection } from "@/components/form/FormPanel";
import { LookupSelect } from "@/components/LookupSelect";
import { VesselCrudGrid, type ColumnDef, type FieldDef } from "@/components/ship/VesselCrudGrid";
import { PARTY_ROLES, PARTY_STATUS, SANCTIONS_STATUS } from "@/lib/party-catalog";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiPatch } from "@/lib/api";
import { msgOf } from "@/lib/errors";

type Tab = "details" | "contacts" | "properties" | "bank";

const TABS: { key: Tab; labelKey: string; label: string }[] = [
  { key: "details", labelKey: "page.parties.tab_details", label: "Details" },
  { key: "contacts", labelKey: "page.parties.tab_contacts", label: "Contacts" },
  { key: "properties", labelKey: "page.parties.tab_properties", label: "Properties" },
  { key: "bank", labelKey: "page.parties.tab_bank", label: "Bank" },
];

type PartyGroup = "identity" | "contact" | "credit" | "compliance" | "gl";

/** 文本字段 —— key 与 CounterpartyIn 列名 1:1。 */
const TEXT_FIELDS: { key: string; label: string; group: PartyGroup; list?: string }[] = [
  // 身份编号（一家公司常有三套编号 + 对接 IMOS 的外部主键）
  { key: "short_name", label: "Short name", group: "identity" },
  { key: "company_no", label: "Company no.", group: "identity" },
  { key: "ref_no", label: "Ref no.", group: "identity" },
  { key: "cross_ref", label: "Cross ref", group: "identity" },
  { key: "reference_code", label: "Reference code", group: "identity" },
  { key: "veslink_id", label: "Veslink ID", group: "identity" },
  // 地址与联系（fax / telex / department / main contact 是 IMOS 特有）
  { key: "phone", label: "Phone", group: "contact" },
  { key: "fax", label: "Fax", group: "contact" },
  { key: "telex", label: "Telex", group: "contact" },
  { key: "email", label: "Email", group: "contact" },
  { key: "website", label: "Website", group: "contact" },
  { key: "department", label: "Department", group: "contact" },
  { key: "main_contact", label: "Main contact", group: "contact" },
  // 授信
  { key: "currency", label: "Currency", group: "credit", list: "party-currency" },
  { key: "credit_rating", label: "Credit rating", group: "credit" },
  // 合规
  { key: "tax_id", label: "Tax ID", group: "compliance" },
  { key: "vat_no", label: "VAT no.", group: "compliance" },
  { key: "registration_no", label: "Registration no.", group: "compliance" },
  { key: "swift_code", label: "SWIFT", group: "compliance" },
  // GL 科目链
  { key: "ap_account", label: "AP account", group: "gl", list: "gl-ap-accounts" },
  { key: "ar_account", label: "AR account", group: "gl", list: "gl-ar-accounts" },
  { key: "ic_account", label: "IC account", group: "gl", list: "gl-ic-accounts" },
  { key: "default_account", label: "Default account", group: "gl", list: "gl-default-accounts" },
];

/** GL 科目字段共用一份科目表 datalist（值存 account_code）。 */
const GL_KEYS = new Set(["ap_account", "ar_account", "ic_account", "default_account"]);

const NUM_FIELDS: { key: string; label: string; group: PartyGroup; step?: string }[] = [
  { key: "credit_term", label: "Credit term (days)", group: "credit" },
  { key: "credit_line", label: "Credit line", group: "credit", step: "0.01" },
  { key: "demurrage_tb_days", label: "Demurrage TB days", group: "credit", step: "0.5" },
];

const DATE_FIELDS: { key: string; label: string; group: PartyGroup }[] = [
  { key: "rating_date", label: "Rating date", group: "credit" },
];

function numOut(v: unknown): string {
  return v === null || v === undefined || v === "" ? "" : String(v);
}

export default function CounterpartyDetailPage() {
  const params = useParams<{ id: string }>();
  const partyId = String(params.id);
  const { t } = useI18n();
  const toast = useToast();

  const [tab, setTab] = useState<Tab>("details");
  const [party, setParty] = useState<Record<string, any> | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [init, setInit] = useState<Record<string, string>>({});
  const [roles, setRoles] = useState<Record<string, boolean>>({});
  const [glAccounts, setGlAccounts] = useState<{ account_code: string; account_name: string }[]>([]);
  const [roleInit, setRoleInit] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [glErr, setGlErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet(`/api/v1/masterdata/counterparties/${partyId}`);
      setParty(data);
      const next: Record<string, string> = {};
      next.name = data?.name ?? "";
      next.type = data?.type ?? "";
      next.country = data?.country ?? "";
      next.status = data?.status ?? "active";
      next.sanctions_status = data?.sanctions_status ?? "clear";
      next.address = data?.address ?? "";
      next.notes = data?.notes ?? "";
      for (const f of TEXT_FIELDS) next[f.key] = data?.[f.key] ?? "";
      for (const f of NUM_FIELDS) next[f.key] = numOut(data?.[f.key]);
      for (const f of DATE_FIELDS) next[f.key] = data?.[f.key] ?? "";
      setForm(next);
      setInit({ ...next });

      const selected: string[] = Array.isArray(data?.address_types) ? data.address_types : [];
      const r: Record<string, boolean> = {};
      for (const role of PARTY_ROLES) r[role] = selected.includes(role);
      setRoles(r);
      setRoleInit({ ...r });
      setLoadErr("");
    } catch (ex) {
      // 取数失败必须显性报错，不能静默留空表单
      setParty(null);
      setLoadErr(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setLoading(false);
    }
  }, [partyId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  // 科目表仅用于 datalist 提示（finance 模块未授权时静默留空，不打断表单）
  useEffect(() => {
    apiGet("/api/v1/gl/accounts?limit=500")
      .then((d: any) => {
        setGlAccounts(Array.isArray(d?.items) ? d.items : Array.isArray(d) ? d : []);
        setGlErr("");
      })
      // 参考数据失败：不让整页报错，但必须可见（科目下拉提示会空）
      .catch((ex) => {
        setGlAccounts([]);
        setGlErr(msgOf(ex));
      });
  }, []);

  // PATCH 走 exclude_unset：只提交改动的键，未提交字段不动。
  async function save() {
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {};
      for (const key of ["name", "type", "country", "status", "sanctions_status", "address", "notes"] as const) {
        if (form[key] !== init[key]) payload[key] = form[key];
      }
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
          toast.error(t("page.parties.err_numeric", "{field} must be a valid number", { field: f.label }));
          setBusy(false);
          return;
        }
        payload[f.key] = n;
      }
      for (const f of DATE_FIELDS) {
        if (form[f.key] === init[f.key]) continue;
        payload[f.key] = form[f.key] === "" ? null : form[f.key];
      }
      const nextRoles = PARTY_ROLES.filter((r) => roles[r]);
      const prevRoles = PARTY_ROLES.filter((r) => roleInit[r]);
      if (nextRoles.join(",") !== prevRoles.join(",")) payload.address_types = nextRoles.length ? nextRoles : null;

      if (Object.keys(payload).length === 0) {
        toast.success(t("common.saved", "Saved"));
        setBusy(false);
        return;
      }
      await apiPatch(`/api/v1/masterdata/counterparties/${partyId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex) {
      toast.error(msgOf(ex, t("common.failed", "Failed")));
    } finally {
      setBusy(false);
    }
  }

  const groups: { key: PartyGroup; labelKey: string; label: string }[] = [
    { key: "identity", labelKey: "page.parties.grp_identity", label: "Identity" },
    { key: "contact", labelKey: "page.parties.grp_contact", label: "Address & contact" },
    { key: "credit", labelKey: "page.parties.grp_credit", label: "Credit" },
    { key: "compliance", labelKey: "page.parties.grp_compliance", label: "Compliance" },
    { key: "gl", labelKey: "page.parties.grp_gl", label: "GL accounts" },
  ];

  const contactColumns = useMemo<ColumnDef[]>(
    () => [
      { key: "name", label: t("common.name", "Name"), minWidth: 150 },
      { key: "title", label: t("page.parties.contact_title", "Title"), width: 130 },
      { key: "email", label: t("common.email", "Email"), minWidth: 180 },
      { key: "phone", label: t("page.parties.phone", "Phone"), width: 140 },
      { key: "mobile", label: t("page.parties.mobile", "Mobile"), width: 140 },
      { key: "department", label: t("page.parties.department", "Department"), width: 140 },
      {
        key: "is_primary",
        label: t("page.parties.primary", "Primary"),
        width: 90,
        render: (r) => (r.is_primary ? "★" : "—"),
      },
    ],
    [t],
  );

  const propertyColumns = useMemo<ColumnDef[]>(
    () => [
      { key: "title", label: t("common.title", "Title"), width: 220 },
      { key: "value", label: t("common.value", "Value") },
    ],
    [t],
  );

  // CRUD 弹窗字段定义：每次渲染都换身份会让 VesselCrudGrid 的列模型缓存失效
  const contactFields = useMemo<FieldDef[]>(
    () => [
      { key: "name", label: t("common.name", "Name"), type: "text", required: true },
      { key: "title", label: t("page.parties.contact_title", "Title"), type: "text" },
      { key: "email", label: t("common.email", "Email"), type: "text" },
      { key: "phone", label: t("page.parties.phone", "Phone"), type: "text" },
      { key: "mobile", label: t("page.parties.mobile", "Mobile"), type: "text" },
      { key: "department", label: t("page.parties.department", "Department"), type: "text" },
      { key: "is_primary", label: t("page.parties.primary", "Primary"), type: "checkbox" },
      { key: "notes", label: t("common.notes", "Notes"), type: "text", span: true },
    ],
    [t],
  );

  const propertyFields = useMemo<FieldDef[]>(
    () => [
      { key: "title", label: t("common.title", "Title"), type: "text", required: true },
      { key: "value", label: t("common.value", "Value"), type: "text", span: true },
    ],
    [t],
  );

  const bankFields = useMemo<FieldDef[]>(
    () => [
      { key: "bank_name", label: t("page.parties.bank_name", "Bank"), type: "text", required: true },
      { key: "account_name", label: t("page.parties.account_name", "Account name"), type: "text", required: true },
      { key: "account_number", label: t("page.parties.account_no", "Account no."), type: "text", required: true },
      { key: "swift_code", label: "SWIFT", type: "text" },
      { key: "iban", label: "IBAN", type: "text", span: true },
      { key: "currency", label: t("page.parties.currency", "Curr"), type: "text" },
      { key: "is_default", label: t("page.parties.default", "Def"), type: "checkbox" },
    ],
    [t],
  );

  const bankColumns = useMemo<ColumnDef[]>(
    () => [
      { key: "bank_name", label: t("page.parties.bank_name", "Bank"), minWidth: 150 },
      { key: "account_name", label: t("page.parties.account_name", "Account name"), minWidth: 150 },
      { key: "account_number", label: t("page.parties.account_no", "Account no."), width: 160 },
      { key: "swift_code", label: "SWIFT", width: 120 },
      { key: "iban", label: t("page.parties.iban", "IBAN"), width: 180 },
      { key: "currency", label: t("page.parties.currency", "Curr"), width: 80 },
      {
        key: "is_default",
        label: t("page.parties.default", "Def"),
        width: 70,
        render: (r) => (r.is_default ? "★" : "—"),
      },
    ],
    [t],
  );

  function renderField(f: (typeof TEXT_FIELDS)[number]) {
    const label = t(`page.parties.f_${f.key}`, f.label);
    const value = form[f.key] ?? "";
    const onChange = (next: string) => setForm({ ...form, [f.key]: next });
    if (f.key === "currency") {
      return (
        <label key={f.key}>
          {label}
          <input list={f.list} value={value} onChange={(e) => onChange(e.target.value)} maxLength={3} />
          <datalist id={f.list}>
            {["USD", "EUR", "GBP", "CNY", "JPY"].map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </label>
      );
    }
    if (GL_KEYS.has(f.key)) {
      return (
        <label key={f.key}>
          {label}
          <input list="gl-accounts" value={value} onChange={(e) => onChange(e.target.value)} placeholder="4000" />
        </label>
      );
    }
    return (
      <label key={f.key}>
        {label}
        <input value={value} onChange={(e) => onChange(e.target.value)} />
      </label>
    );
  }

  return (
    <AppShell>
      <PageHeader
        title={party?.name || t("page.parties.card", "Counterparty")}
        subtitle={
          <>
            {`${party?.type || "—"} · ${party?.country || "—"} · ${t(
              `page.parties.status_${party?.status || "active"}`,
              party?.status || "active",
            )}`} · <RecordAttribution entityType="counterparty" entityId={partyId} />
          </>
        }
        breadcrumb={[
          { label: t("nav.master", "Master data"), href: "/masterdata" },
          { label: t("page.parties.title", "Counterparties"), href: "/masterdata/counterparties" },
          { label: party?.name || t("page.parties.card", "Counterparty") },
        ]}
        actions={
          <>
            <Link href="/masterdata/counterparties" className="btn btn-ghost">
              {t("page.parties.title", "Counterparties")}
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
          {glErr ? (
            <p className="flash-warn">
              {t("page.parties.gl_accounts_load_failed", "GL accounts could not be loaded — the account suggestions may be incomplete.")}{" "}
              {glErr}
            </p>
          ) : null}
          <StateView
            loading={loading}
            error={loadErr || undefined}
            empty={false}
            onRetry={() => void load()}
          >
          {groups.map((g) => (
            <FormSection key={g.key} title={t(g.labelKey, g.label)}>
              {g.key === "identity" ? (
                <>
                  <label>
                    {t("common.name", "Name")}
                    <input value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
                  </label>
                  <label>
                    {t("page.parties.type", "Type")}
                    <LookupSelect dataset="counterparty_types" value={form.type ?? ""} onChange={(v) => setForm({ ...form, type: v })} />
                  </label>
                  <label>
                    {t("page.parties.country", "Country")}
                    <LookupSelect dataset="countries" value={form.country ?? ""} onChange={(v) => setForm({ ...form, country: v })} />
                  </label>
                  <label>
                    {t("common.status", "Status")}
                    <select value={form.status || "active"} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                      {PARTY_STATUS.map((s) => (
                        <option key={s} value={s}>
                          {t(`page.parties.status_${s}`, s)}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              ) : null}

              {g.key === "contact" ? (
                <label className="span-all">
                  {t("page.parties.address", "Address")}
                  <textarea rows={2} value={form.address ?? ""} onChange={(e) => setForm({ ...form, address: e.target.value })} />
                </label>
              ) : null}

              {g.key === "gl" ? (
                <datalist id="gl-accounts">
                  {glAccounts.map((a) => (
                    <option key={a.account_code} value={a.account_code}>
                      {a.account_name}
                    </option>
                  ))}
                </datalist>
              ) : null}

              {TEXT_FIELDS.filter((f) => f.group === g.key).map(renderField)}

              {NUM_FIELDS.filter((f) => f.group === g.key).map((f) => (
                <label key={f.key}>
                  {t(`page.parties.f_${f.key}`, f.label)}
                  <input
                    type="number"
                    step={f.step}
                    value={form[f.key] ?? ""}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  />
                </label>
              ))}

              {DATE_FIELDS.filter((f) => f.group === g.key).map((f) => (
                <label key={f.key}>
                  {t(`page.parties.f_${f.key}`, f.label)}
                  <input
                    type="date"
                    value={form[f.key] ?? ""}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                  />
                </label>
              ))}

              {g.key === "compliance" ? (
                <>
                  <label>
                    {t("page.parties.sanctions", "Sanctions")}
                    <select
                      value={form.sanctions_status || "clear"}
                      onChange={(e) => setForm({ ...form, sanctions_status: e.target.value })}
                    >
                      {SANCTIONS_STATUS.map((s) => (
                        <option key={s} value={s}>
                          {t(`page.parties.sanctions_${s}`, s)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="span-all">
                    {t("common.notes", "Notes")}
                    <textarea rows={2} value={form.notes ?? ""} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                  </label>
                </>
              ) : null}
            </FormSection>
          ))}

          <FormSection title={t("page.parties.address_types", "Address types (IMOS multi-role)")}>
            <div className="check-grid span-all">
              {PARTY_ROLES.map((role) => (
                <label key={role} className="check-row">
                  <input
                    type="checkbox"
                    checked={Boolean(roles[role])}
                    onChange={(e) => setRoles({ ...roles, [role]: e.target.checked })}
                  />
                  {t(`page.parties.role_${role}`, role)}
                </label>
              ))}
            </div>
          </FormSection>
          </StateView>
        </div>
      ) : null}

      {tab === "contacts" ? (
        <VesselCrudGrid
          vesselId={partyId}
          path="contacts"
          basePath={`/api/v1/masterdata/counterparties/${partyId}/contacts`}
          title={t("page.parties.contacts", "Contacts")}
          addLabel={t("page.parties.add_contact", "Add contact")}
          emptyText={t("page.parties.no_contacts", "No contacts yet")}
          columns={contactColumns}
          fields={contactFields}
        />
      ) : null}

      {tab === "properties" ? (
        <VesselCrudGrid
          vesselId={partyId}
          path="properties"
          basePath={`/api/v1/masterdata/counterparties/${partyId}/properties`}
          title={t("page.parties.tab_properties", "Properties")}
          addLabel={t("page.parties.add_property", "Add property")}
          emptyText={t("page.parties.no_properties", "No properties yet")}
          columns={propertyColumns}
          fields={propertyFields}
        />
      ) : null}

      {tab === "bank" ? (
        <VesselCrudGrid
          vesselId={partyId}
          path="bank-accounts"
          basePath="/api/v1/payments/bank-accounts"
          query={`?counterparty_id=${partyId}`}
          defaults={{ counterparty_id: partyId }}
          title={t("page.parties.tab_bank", "Bank")}
          addLabel={t("page.parties.add_bank", "Add bank account")}
          emptyText={t("page.parties.no_bank", "No bank accounts yet")}
          columns={bankColumns}
          fields={bankFields}
        />
      ) : null}
    </AppShell>
  );
}
