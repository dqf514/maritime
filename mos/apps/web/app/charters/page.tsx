"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DateInput } from "@/components/DateInput";
import { PageGuide } from "@/components/PageGuide";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

// U2：行点击直达单据详情页 /charters/{id}（编辑/变更单/hire/liftings 在详情页）。

type RefItem = { id: string; name: string };
type Charter = {
  id: string;
  charter_no: string;
  charter_type: string;
  status: string;
  vessel_id: string | null;
  counterparty_id: string | null;
  estimate_id: string | null;
  sanctions_blocked: boolean;
};

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

export default function ChartersPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const [rows, setRows] = useState<Charter[]>([]);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

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

  function setTerm(key: keyof TermFields, value: string) {
    setTerms((prev) => ({ ...prev, [key]: value }));
  }

  const load = useCallback(async () => {
    const [c, v, p] = await Promise.all([
      apiGet("/api/v1/charters"),
      apiGet("/api/v1/masterdata/vessels"),
      apiGet("/api/v1/masterdata/counterparties"),
    ]);
    setRows(c);
    setVessels(v);
    setParties(p);
    if (!vesselId && v[0]?.id) setVesselId(v[0].id);
    if (!partyId && p[0]?.id) setPartyId(p[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const freight_terms: Record<string, number | string> = {};
      if (freightRate !== "") freight_terms.freight_rate = Number(freightRate);
      if (cargoQty !== "") {
        freight_terms.cargo_qty = Number(cargoQty);
        freight_terms.cargo = `Bulk ${cargoQty} mt`;
      }
      const cp = await apiPost("/api/v1/charters", {
        charter_type: charterType,
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
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  function vesselName(id: string | null) {
    if (!id) return "—";
    return vessels.find((v) => v.id === id)?.name || id.slice(0, 8);
  }

  function partyName(id: string | null) {
    if (!id) return "—";
    return parties.find((p) => p.id === id)?.name || id.slice(0, 8);
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.charters.title", "租约工作台")}</h1>
          <p className="page-sub">
            {t("page.charters.sub", "新建租约；点击行打开单据详情（可分享链接），编辑、变更与状态推进在详情页。")}
          </p>
        </div>
        <div className="quick-row">
          <PageGuide pageKey="charters" />
          <Link href="/settings/recycle" className="btn btn-ghost">
            {t("nav.recycle", "回收站")}
          </Link>
        </div>
      </div>

      {err ? <p className="flash-err">{err}</p> : null}

      <form className="panel" onSubmit={create}>
        <h3 style={{ marginTop: 0 }}>{t("page.charters.create", "New charter")}</h3>
        <div className="form-grid">
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
          <label>
            {t("page.estimates.counterparty", "Counterparty")}
            <select value={partyId} onChange={(e) => setPartyId(e.target.value)}>
              <option value="">{t("common.select", "Select…")}</option>
              {parties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
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
          <TermInputs value={terms} onChange={setTerm} showTc={isTc(charterType)} />
          <label style={{ gridColumn: "1 / -1" }}>
            {t("page.charters.clauses", "Clauses / notes")}
            <input value={clausesNotes} onChange={(e) => setClausesNotes(e.target.value)} placeholder="CP notes" />
          </label>
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("common.create", "Create")}
          </button>
        </div>
      </form>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.charters.list", "Fixtures")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.charters.no", "编号")}</th>
              <th>{t("common.type", "类型")}</th>
              <th>{t("common.status", "状态")}</th>
              <th>{t("page.estimates.vessel", "船舶")}</th>
              <th>{t("page.estimates.counterparty", "对手方")}</th>
              <th>{t("page.charters.sanctions", "制裁")}</th>
              <th>{t("page.charters.estimate", "估算")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => router.push(`/charters/${r.id}`)}>
                <td>{r.charter_no}</td>
                <td>{r.charter_type}</td>
                <td>{r.status}</td>
                <td>{vesselName(r.vessel_id)}</td>
                <td>{partyName(r.counterparty_id)}</td>
                <td>
                  {r.sanctions_blocked ? (
                    <span className="badge badge-fail">{t("page.charters.blocked", "BLOCKED")}</span>
                  ) : (
                    <span className="badge badge-pass">{t("page.charters.clear", "clear")}</span>
                  )}
                </td>
                <td>
                  {r.estimate_id ? (
                    <Link href="/estimates" onClick={(e) => e.stopPropagation()}>
                      {r.estimate_id.slice(0, 8)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={7} className="muted">
                  {t("common.empty", "暂无记录")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
