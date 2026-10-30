"use client";

import { msgOf } from "@/lib/errors";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { StateView } from "@/components/StateView";
import { DateInput } from "@/components/DateInput";
import { PageGuide } from "@/components/PageGuide";
import { PageHeader } from "@/components/PageHeader";
import { PartyPicker } from "@/components/DataPicker";
import { RecordModal } from "@/components/RecordModal";
import { FormPanel, FormSection } from "@/components/form/FormPanel";
import { Tabs, type TabItem } from "@/components/Tabs";
import { CoaListPanel } from "@/components/charters/CoaListPanel";
import { TcListPanel } from "@/components/charters/TcListPanel";
import { useTodoAdd } from "@/components/TodoQuickAdd";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { useListQuery } from "@/lib/useListQuery";
import { formatDateTimeShort } from "@/lib/datetime";

// U2：行点击直达单据详情页 /charters/{id}（编辑/变更单/hire/liftings 在详情页）。
// A5 双重 UI 归并：本页为租约列表唯一入口。原 /charters/tc、/charters/coa 列表
// 并入 ?type=tc|coa 页签（组件/charters/*Panel），旧路径保留为永久重定向。

type ListType = "fixtures" | "tc" | "coa";

type RefItem = { id: string; name: string };
type Charter = {
  id: string;
  charter_no: string;
  charter_type: string;
  status: string;
  vessel_id: string | null;
  counterparty_id: string | null;
  estimate_id: string | null;
  estimate_title?: string | null;
  fixture_type?: string | null;
  sanctions_blocked: boolean;
  updated_at?: string | null;
};
type MasterContract = {
  id: string;
  contract_no: string;
  title: string;
  contract_type: string;
  status: string;
};

// 单据种类：fixture_type（Head/Relet Fixture）+ 独立的 Master Contract 单据
type DocKind = "voyage_fixture" | "head" | "relet" | "master_contract";

type TermFields = {
  freight_basis: string;
  demurrage_rate: string;
  despatch_rate: string;
  laytime_terms: string;
  cp_form: string;
  load_rate_pd: string;
  disch_rate_pd: string;
  address_comm_pct: string;
  brokerage_pct: string;
  hire_per_day: string;
  hire_cycle_days: string;
  delivery_at: string;
  redelivery_at: string;
  ets_responsibility: string;
};

const EMPTY_TERMS: TermFields = {
  freight_basis: "",
  demurrage_rate: "",
  despatch_rate: "",
  laytime_terms: "",
  cp_form: "",
  load_rate_pd: "",
  disch_rate_pd: "",
  address_comm_pct: "",
  brokerage_pct: "",
  hire_per_day: "",
  hire_cycle_days: "",
  delivery_at: "",
  redelivery_at: "",
  ets_responsibility: "",
};

const TERM_NUM_KEYS = [
  "demurrage_rate",
  "despatch_rate",
  "load_rate_pd",
  "disch_rate_pd",
  "address_comm_pct",
  "brokerage_pct",
  "hire_per_day",
  "hire_cycle_days",
] as const;

function isTc(charterType: string) {
  return charterType === "time" || charterType === "tct";
}

function TermInputs({
  value,
  onChange,
  showTc,
}: {
  value: TermFields;
  onChange: (key: keyof TermFields, v: string) => void;
  showTc: boolean;
}) {
  const { t } = useI18n();
  return (
    <>
      <label>
        {t("page.charters.freight_basis", "Freight basis")}
        <select value={value.freight_basis} onChange={(e) => onChange("freight_basis", e.target.value)}>
          <option value="">—</option>
          <option value="per_mt">per_mt</option>
          <option value="lumpsum">lumpsum</option>
          <option value="worldscale">worldscale</option>
        </select>
      </label>
      <label>
        {t("page.charters.demurrage_rate", "Demurrage rate")}
        <input type="number" step="any" value={value.demurrage_rate} onChange={(e) => onChange("demurrage_rate", e.target.value)} />
      </label>
      <label>
        {t("page.charters.despatch_rate", "Despatch rate")}
        <input type="number" step="any" value={value.despatch_rate} onChange={(e) => onChange("despatch_rate", e.target.value)} />
      </label>
      <label>
        {t("page.charters.laytime_terms", "Laytime terms")}
        <select value={value.laytime_terms} onChange={(e) => onChange("laytime_terms", e.target.value)}>
          <option value="">—</option>
          <option value="SHINC">SHINC</option>
          <option value="SHEX">SHEX</option>
          <option value="SSHEX">SSHEX</option>
          <option value="SSHINC">SSHINC</option>
          <option value="FHEX">FHEX</option>
        </select>
      </label>
      <label>
        {t("page.charters.cp_form", "CP form")}
        <input list="cp-form-opts" value={value.cp_form} onChange={(e) => onChange("cp_form", e.target.value)} placeholder="GENCON / NYPE / …" />
        <datalist id="cp-form-opts">
          <option value="GENCON" />
          <option value="NYPE" />
          <option value="SHELLTIME" />
        </datalist>
      </label>
      <label>
        {t("page.charters.load_rate_pd", "Load rate / day")}
        <input type="number" step="any" value={value.load_rate_pd} onChange={(e) => onChange("load_rate_pd", e.target.value)} />
      </label>
      <label>
        {t("page.charters.disch_rate_pd", "Disch rate / day")}
        <input type="number" step="any" value={value.disch_rate_pd} onChange={(e) => onChange("disch_rate_pd", e.target.value)} />
      </label>
      <label>
        {t("page.charters.address_comm", "Address comm %")}
        <input type="number" step="any" value={value.address_comm_pct} onChange={(e) => onChange("address_comm_pct", e.target.value)} />
      </label>
      <label>
        {t("page.charters.brokerage", "Brokerage %")}
        <input type="number" step="any" value={value.brokerage_pct} onChange={(e) => onChange("brokerage_pct", e.target.value)} />
      </label>
      {showTc ? (
        <>
          <label>
            {t("page.charters.hire_per_day", "Hire / day")}
            <input type="number" step="any" value={value.hire_per_day} onChange={(e) => onChange("hire_per_day", e.target.value)} />
          </label>
          <label>
            {t("page.charters.hire_cycle_days", "Hire cycle days")}
            <input type="number" step="any" value={value.hire_cycle_days} onChange={(e) => onChange("hire_cycle_days", e.target.value)} />
          </label>
          <label>
            {t("page.charters.delivery_at", "Delivery at")}
            <DateInput value={value.delivery_at} onChange={(v) => onChange("delivery_at", v)} />
          </label>
          <label>
            {t("page.charters.redelivery_at", "Redelivery at")}
            <DateInput value={value.redelivery_at} onChange={(v) => onChange("redelivery_at", v)} />
          </label>
          <label>
            {t("page.charters.ets_responsibility", "ETS responsibility")}
            <select value={value.ets_responsibility} onChange={(e) => onChange("ets_responsibility", e.target.value)}>
              <option value="">—</option>
              <option value="owner">owner</option>
              <option value="charterer">charterer</option>
            </select>
          </label>
        </>
      ) : null}
    </>
  );
}

function charterTermsPayload(freightRate: string, cargoQty: string, tm: TermFields) {
  const out: Record<string, number | string> = {};
  if (freightRate !== "") out.freight_rate = Number(freightRate);
  if (cargoQty !== "") out.cargo_qty = Number(cargoQty);
  TERM_NUM_KEYS.forEach((k) => {
    if (tm[k] !== "") out[k] = Number(tm[k]);
  });
  if (tm.freight_basis) out.freight_basis = tm.freight_basis;
  if (tm.laytime_terms) out.laytime_terms = tm.laytime_terms.toUpperCase();
  if (tm.cp_form) out.cp_form = tm.cp_form.toUpperCase();
  if (tm.delivery_at) out.delivery_at = tm.delivery_at;
  if (tm.redelivery_at) out.redelivery_at = tm.redelivery_at;
  if (tm.ets_responsibility) out.ets_responsibility = tm.ets_responsibility;
  return out;
}

function ChartersPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  // A5：?type=tc|coa 驱动列表页签（fixtures 为默认，不进 URL）
  const { query, setQuery } = useListQuery();
  const listType: ListType = query.type === "tc" ? "tc" : query.type === "coa" ? "coa" : "fixtures";
  const setListType = (k: ListType) => setQuery({ type: k === "fixtures" ? null : k, page: null });
  const [rows, setRows] = useState<Charter[]>([]);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [masters, setMasters] = useState<MasterContract[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  /** 参考数据（船 / 对手方 / 母合同）加载失败 —— 局部提示 */
  const [refErr, setRefErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formOpen, setFormOpen] = useState(false);

  // 行右键菜单：打开 / 添加到个人待办 / 复制 id
  const rowCtx = useContextMenu<Charter>();
  const todo = useTodoAdd();
  function charterMenuItems(row: Charter): ContextMenuItem[] {
    return [
      { key: "open", label: t("common.open", "Open"), onClick: () => router.push(`/charters/${row.id}`) },
      { key: "divider", divider: true },
      todo.menuItem({ entityType: "charter", entityId: row.id, title: row.charter_no }),
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(row.id) },
    ];
  }

  const [docKind, setDocKind] = useState<DocKind>("voyage_fixture");
  const [charterType, setCharterType] = useState("voyage");
  const [vesselId, setVesselId] = useState("");
  const [partyId, setPartyId] = useState("");
  const [laycanFrom, setLaycanFrom] = useState("");
  const [laycanTo, setLaycanTo] = useState("");
  const [commission, setCommission] = useState("2.5");
  const [freightRate, setFreightRate] = useState("");
  const [cargoQty, setCargoQty] = useState("");
  const [terms, setTerms] = useState<TermFields>(EMPTY_TERMS);
  const [clausesNotes, setClausesNotes] = useState("");
  const [direction, setDirection] = useState("out");
  const [masterContractId, setMasterContractId] = useState("");
  // master contract fields（docKind === "master_contract" 时显示）
  const [mcTitle, setMcTitle] = useState("");
  const [mcType, setMcType] = useState("voyage_coa");
  const [mcQty, setMcQty] = useState("");
  const [mcFrom, setMcFrom] = useState("");
  const [mcTo, setMcTo] = useState("");

  function setTerm(key: keyof TermFields, value: string) {
    setTerms((prev) => ({ ...prev, [key]: value }));
  }

  const load = useCallback(async () => {
    setLoading(true);
    setRefErr(null);
    // 主列表（租约）与参考数据（船/对手方/母合同）分别成败 ——
    // 参考数据失败只做局部提示，不能让整页变成「空列表」。
    const [cR, vR, pR, mR] = await Promise.allSettled([
      apiGet("/api/v1/charters"),
      apiGet("/api/v1/masterdata/vessels"),
      apiGet("/api/v1/masterdata/counterparties"),
      apiGet("/api/v1/master-contracts"),
    ]);
    if (cR.status === "fulfilled") {
      setRows(cR.value as Charter[]);
      setErr("");
    } else {
      setRows([]);
      setErr(msgOf(cR.reason, t("common.failed", "Failed")));
    }
    if (vR.status === "fulfilled") {
      const v = vR.value as RefItem[];
      setVessels(v);
      if (!vesselId && v[0]?.id) setVesselId(v[0].id);
    } else {
      setVessels([]);
      setRefErr(msgOf(vR.reason));
    }
    if (pR.status === "fulfilled") {
      const p = pR.value as RefItem[];
      setParties(p);
      if (!partyId && p[0]?.id) setPartyId(p[0].id);
    } else {
      setParties([]);
      setRefErr(msgOf(pR.reason));
    }
    if (mR.status === "fulfilled") {
      const m = mR.value;
      setMasters(Array.isArray(m) ? m : ((m as { items?: MasterContract[] })?.items ?? []));
    } else {
      setMasters([]);
      setRefErr(msgOf(mR.reason));
    }
    setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create() {
    setBusy(true);
    setErr("");
    // 数值字段校验：非法输入不得静默变 0 / NaN —— 直接中止提交
    const numFields: Array<[string, string]> = [
      [t("page.estimates.freight_rate", "Freight rate"), freightRate],
      [t("page.estimates.cargo_qty", "Cargo qty"), cargoQty],
      [t("page.estimates.commission", "Commission %"), commission],
      ...TERM_NUM_KEYS.map((k) => [k, terms[k]] as [string, string]),
    ];
    if (docKind === "master_contract") {
      numFields.push([t("page.charters.mc_total_qty", "Total qty"), mcQty]);
    }
    for (const [label, raw] of numFields) {
      if (raw === "" || raw === undefined || raw === null) continue;
      if (!Number.isFinite(Number(raw))) {
        toast.error(t("page.charters.err_number", "{field} must be a valid number", { field: label }));
        setBusy(false);
        return;
      }
    }
    try {
      if (docKind === "master_contract") {
        const mc = await apiPost("/api/v1/master-contracts", {
          title: mcTitle || null,
          counterparty_id: partyId || null,
          contract_type: mcType,
          total_qty: mcQty === "" ? null : Number(mcQty),
          period_from: mcFrom || null,
          period_to: mcTo || null,
        });
        toast.success(t("page.charters.master_created", "Master contract {no} created", { no: mc.contract_no }));
        setMcTitle("");
        setMcQty("");
        setMcFrom("");
        setMcTo("");
        setFormOpen(false);
        await load();
        return;
      }
      const freight_terms: Record<string, number | string> = {};
      if (freightRate !== "") freight_terms.freight_rate = Number(freightRate);
      if (cargoQty !== "") {
        freight_terms.cargo_qty = Number(cargoQty);
        freight_terms.cargo = `Bulk ${cargoQty} mt`;
      }
      const cp = await apiPost("/api/v1/charters", {
        charter_type: charterType,
        fixture_type: docKind,
        charter_direction: direction,
        master_contract_id: masterContractId || null,
        vessel_id: vesselId || null,
        counterparty_id: partyId || null,
        laycan_from: laycanFrom || null,
        laycan_to: laycanTo || null,
        commission_pct: commission === "" ? null : Number(commission),
        freight_terms,
        ...charterTermsPayload(freightRate, cargoQty, terms),
        clauses: clausesNotes ? { notes: clausesNotes } : {},
      });
      toast.success(t("page.charters.created", "Created {no}", { no: cp.charter_no }));
      setFreightRate("");
      setCargoQty("");
      setTerms(EMPTY_TERMS);
      setClausesNotes("");
      setFormOpen(false);
      await load();
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  const vesselName = useCallback((id: string | null) => {
    if (!id) return "—";
    return vessels.find((v) => v.id === id)?.name || id.slice(0, 8);
  }, [vessels]);

  const partyName = useCallback((id: string | null) => {
    if (!id) return "—";
    return parties.find((p) => p.id === id)?.name || id.slice(0, 8);
  }, [parties]);

  const listColumns = useMemo<ColumnDef<Charter>[]>(() => [
    { key: "charter_no", title: t("page.charters.no", "编号"), width: 130, value: (r) => r.charter_no },
    {
      key: "charter_type",
      title: t("common.type", "类型"),
      width: 130,
      value: (r) => `${r.charter_type}${r.fixture_type && r.fixture_type !== "voyage_fixture" ? ` ${r.fixture_type}` : ""}`,
      render: (_v, r) => (
        <>
          {r.charter_type}
          {r.fixture_type && r.fixture_type !== "voyage_fixture" ? (
            <span className="muted" style={{ marginLeft: "0.35rem", fontSize: "0.75rem" }}>{r.fixture_type}</span>
          ) : null}
        </>
      ),
    },
    { key: "status", title: t("common.status", "状态"), width: 110, value: (r) => r.status },
    {
      key: "vessel",
      title: t("page.estimates.vessel", "船舶"),
      width: 130,
      value: (r) => vesselName(r.vessel_id),
    },
    {
      key: "counterparty",
      title: t("page.estimates.counterparty", "对手方"),
      minWidth: 130,
      value: (r) => partyName(r.counterparty_id),
    },
    {
      key: "sanctions_blocked",
      title: t("page.charters.sanctions", "制裁"),
      width: 100,
      value: (r) => Boolean(r.sanctions_blocked),
      render: (_v, r) =>
        r.sanctions_blocked ? (
          <span className="badge badge-fail">{t("page.charters.blocked", "BLOCKED")}</span>
        ) : (
          <span className="badge badge-pass">{t("page.charters.clear", "clear")}</span>
        ),
    },
    {
      key: "estimate_id",
      title: t("page.charters.estimate", "估算"),
      width: 150,
      value: (r) => r.estimate_title || r.estimate_id || "",
      render: (_v, r) =>
        r.estimate_id ? (
          <Link
            href="/estimates"
            title={r.estimate_title || r.estimate_id}
            onClick={(e) => e.stopPropagation()}
          >
            {r.estimate_title || r.estimate_id.slice(0, 8)}
          </Link>
        ) : (
          "—"
        ),
    },
    {
      key: "updated_at",
      title: t("list.last_modified", "Last modified"),
      width: 135,
      value: (r) => r.updated_at ?? null,
      render: (v) => formatDateTimeShort(v as string | null),
    },
  ], [partyName, t, vesselName]);

  const tabs: TabItem[] = [
    { key: "fixtures", label: t("page.charters.list", "Fixtures") },
    { key: "tc", label: t("page.tc.title", "Time Charter") },
    { key: "coa", label: t("page.coa.title", "COA") },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("page.charters.title", "租约工作台")}
        subtitle={t("page.charters.sub", "新建租约；点击行打开单据详情（可分享链接），编辑、变更与状态推进在详情页。")}
        actions={
          <>
            {listType === "fixtures" ? (
              <button type="button" className="btn btn-primary" onClick={() => setFormOpen(true)}>
                + {t("page.charters.create", "New charter")}
              </button>
            ) : null}
            <PageGuide pageKey="charters" />
            <Link href="/settings/recycle" className="btn btn-ghost">
              {t("nav.recycle", "回收站")}
            </Link>
          </>
        }
      />

      <Tabs items={tabs} value={listType} onChange={(k) => setListType(k as ListType)} variant="line" />

      {listType === "fixtures" ? (
        <>
          {err ? <p className="flash-err">{err}</p> : null}
          {refErr ? (
            <p className="flash-err" role="alert">
              {t("page.charters.ref_fail", "Reference data could not be loaded: {err}", { err: refErr })}
            </p>
          ) : null}

          <div className="panel">
            <StateView
              loading={loading}
              error={err || undefined}
              empty={!loading && !err && rows.length === 0}
              emptyText={t("common.empty", "No records")}
              onRetry={() => void load()}
            >
              <DataGrid<Charter>
                columns={listColumns}
                data={rows}
                rowKey={(r) => r.id}
                onRowClick={(r) => router.push(`/charters/${r.id}`)}
                onRowContextMenu={(row, _i, e) => rowCtx.open(row)(e)}
                storageKey="charters_list_grid"
                emptyText={t("common.empty", "No records")}
              />
            </StateView>
          </div>
        </>
      ) : null}
      {listType === "tc" ? <TcListPanel /> : null}
      {listType === "coa" ? <CoaListPanel /> : null}

      <RecordModal
        open={formOpen}
        title={t("page.charters.create", "New charter")}
        onClose={() => setFormOpen(false)}
        onSave={create}
        canDelete={false}
        saving={busy}
        size="xl"
      >
        {/* 多列分组布局 — 与 New TC contract / COA 新建弹窗保持一致 */}
        <FormPanel columns={2}>
          <FormSection title={t("page.tc.terms.basic", "Contract")} dense>
            <label>
              {t("page.charters.contract_type", "Contract type")}
              <select value={docKind} onChange={(e) => setDocKind(e.target.value as DocKind)}>
                <option value="voyage_fixture">{t("page.charters.fixture_voyage", "Voyage Fixture")}</option>
                <option value="head">{t("page.charters.fixture_head", "Head Fixture")}</option>
                <option value="relet">{t("page.charters.fixture_relet", "Relet Fixture")}</option>
                <option value="master_contract">{t("page.charters.master_contract", "Master Contract")}</option>
              </select>
            </label>
            {docKind !== "master_contract" ? (
              <>
                <label>
                  {t("page.charters.type", "Charter type")}
                  <select value={charterType} onChange={(e) => setCharterType(e.target.value)}>
                    <option value="voyage">voyage</option>
                    <option value="time">time</option>
                    <option value="tct">tct</option>
                    <option value="coa">coa</option>
                    <option value="bb">bb</option>
                  </select>
                </label>
                <label>
                  {t("page.charters.direction", "Direction")}
                  <select value={direction} onChange={(e) => setDirection(e.target.value)}>
                    <option value="out">out</option>
                    <option value="in">in</option>
                  </select>
                </label>
                <label>
                  {t("page.charters.master_contract", "Master Contract")}
                  <select value={masterContractId} onChange={(e) => setMasterContractId(e.target.value)}>
                    <option value="">{t("common.none", "None")}</option>
                    {masters.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.contract_no} — {m.title}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            ) : null}
          </FormSection>
          {docKind === "master_contract" ? (
            <FormSection title={t("page.charters.master_contract", "Master Contract")} dense>
              <label>
                {t("page.charters.mc_title", "Contract title")}
                <input value={mcTitle} onChange={(e) => setMcTitle(e.target.value)} placeholder="COA 2026 …" />
              </label>
              <label>
                {t("page.charters.mc_contract_type", "Master contract type")}
                <select value={mcType} onChange={(e) => setMcType(e.target.value)}>
                  <option value="voyage_coa">voyage_coa</option>
                  <option value="time_charter">time_charter</option>
                  <option value="bareboat">bareboat</option>
                </select>
              </label>
              <label>
                {t("page.charters.mc_total_qty", "Total qty")}
                <input type="number" step="any" value={mcQty} onChange={(e) => setMcQty(e.target.value)} />
              </label>
              <label>
                {t("page.charters.mc_period_from", "Period from")}
                <DateInput value={mcFrom} onChange={setMcFrom} />
              </label>
              <label>
                {t("page.charters.mc_period_to", "Period to")}
                <DateInput value={mcTo} onChange={setMcTo} />
              </label>
            </FormSection>
          ) : null}
          <FormSection title={t("page.tc.terms.parties", "Parties & vessel")} dense>
            <label>
              {t("page.estimates.counterparty", "Counterparty")}
              <PartyPicker value={partyId} onChange={setPartyId} />
            </label>
            {docKind !== "master_contract" ? (
              <label>
                {t("page.estimates.vessel", "Vessel")}
                <select value={vesselId} onChange={(e) => setVesselId(e.target.value)}>
                  <option value="">{t("common.select", "Select…")}</option>
                  {vessels.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </FormSection>
          {docKind !== "master_contract" ? (
            <>
              <FormSection title={t("page.charters.sec_laycan", "Laycan & freight")} dense>
                <label>
                  {t("page.charters.laycan_from", "Laycan from")}
                  <DateInput value={laycanFrom} onChange={setLaycanFrom} />
                </label>
                <label>
                  {t("page.charters.laycan_to", "Laycan to")}
                  <DateInput value={laycanTo} onChange={setLaycanTo} />
                </label>
                <label>
                  {t("page.estimates.commission", "Commission %")}
                  <input type="number" step="any" value={commission} onChange={(e) => setCommission(e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.freight_rate", "Freight rate")}
                  <input type="number" step="any" value={freightRate} onChange={(e) => setFreightRate(e.target.value)} />
                </label>
                <label>
                  {t("page.estimates.cargo_qty", "Cargo qty")}
                  <input type="number" step="any" value={cargoQty} onChange={(e) => setCargoQty(e.target.value)} />
                </label>
              </FormSection>
              <FormSection title={t("page.charters.sec_cp_terms", "CP terms")} dense>
                <TermInputs value={terms} onChange={setTerm} showTc={isTc(charterType)} />
              </FormSection>
              <FormSection title={t("page.charters.clauses", "Clauses / notes")} dense>
                <label style={{ gridColumn: "1 / -1" }}>
                  {t("page.charters.clauses", "Clauses / notes")}
                  <input value={clausesNotes} onChange={(e) => setClausesNotes(e.target.value)} placeholder="CP notes" />
                </label>
              </FormSection>
            </>
          ) : null}
        </FormPanel>
      </RecordModal>

      <ContextMenu controller={rowCtx} items={charterMenuItems} />
      {todo.element}
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <ChartersPage />
    </Suspense>
  );
}
