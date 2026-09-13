"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { LookupSelect } from "@/components/LookupSelect";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type RefItem = { id: string; name: string };
type Voyage = { id: string; voyage_no: string; status: string };
type Invoice = { id: string; invoice_no: string; status: string; amount: number; paid_amount?: number; invoice_type?: string };
type Claim = { id: string; claim_no: string; status: string; amount: number };
type Laytime = {
  id: string;
  voyage_id: string | null;
  status: string;
  inputs: Record<string, unknown>;
  results: { amount?: number; used_hours?: number; demurrage_hours?: number; despatch_hours?: number };
};
type PnlRow = {
  voyage_id: string;
  voyage_no: string;
  status: string;
  estimated_revenue: number;
  estimated_cost: number;
  estimated_pnl: number;
  actual_revenue: number;
  actual_cost: number;
  actual_pnl: number;
  variance_pnl: number;
  estimated_tce?: number | null;
};

type Accrual = {
  id: string;
  voyage_id: string | null;
  period_ym: string;
  line_type: string;
  amount: number;
  currency: string;
  status: string;
  notes?: string | null;
};
type Pda = {
  id: string;
  voyage_id: string | null;
  status: string;
  pda_amount: number;
  fda_amount?: number | null;
  variance?: number | null;
  currency: string;
};

type Tab = "invoices" | "laytime" | "pnl" | "claims" | "accruals" | "pda";

function fmt(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function FinanceHubPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("invoices");
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [laytimes, setLaytimes] = useState<Laytime[]>([]);
  const [pnl, setPnl] = useState<PnlRow[]>([]);
  const [accruals, setAccruals] = useState<Accrual[]>([]);
  const [pdas, setPdas] = useState<Pda[]>([]);
  const [voyages, setVoyages] = useState<Voyage[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const [accPeriod, setAccPeriod] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [accType, setAccType] = useState("freight");
  const [accAmount, setAccAmount] = useState("10000");
  const [accVoyage, setAccVoyage] = useState("");
  const [pdaAmount, setPdaAmount] = useState("25000");
  const [pdaVoyage, setPdaVoyage] = useState("");
  const [fdaAmount, setFdaAmount] = useState("");
  const [pdaCurrency, setPdaCurrency] = useState("USD");
  const [accCurrency, setAccCurrency] = useState("USD");

  const [invType, setInvType] = useState("freight");
  const [invAmount, setInvAmount] = useState("100000");
  const [invVoyage, setInvVoyage] = useState("");
  const [invParty, setInvParty] = useState("");
  const [payAmount, setPayAmount] = useState("");

  const [ltVoyage, setLtVoyage] = useState("");
  const [ltAllowed, setLtAllowed] = useState("72");
  const [ltCargoQty, setLtCargoQty] = useState("");
  const [ltLoadRate, setLtLoadRate] = useState("");
  const [ltTurn, setLtTurn] = useState("6");
  const [ltDem, setLtDem] = useState("24000");
  const [ltDes, setLtDes] = useState("12000");
  const [ltE1Start, setLtE1Start] = useState("2026-09-01T08:00");
  const [ltE1End, setLtE1End] = useState("2026-09-04T20:00");
  const [ltE2Start, setLtE2Start] = useState("2026-09-02T00:00");
  const [ltE2End, setLtE2End] = useState("2026-09-02T12:00");
  const [selectedLt, setSelectedLt] = useState<string | null>(null);
  const [openInv, setOpenInv] = useState<Invoice | null>(null);
  const [openClaim, setOpenClaim] = useState<Claim | null>(null);
  const [editInv, setEditInv] = useState({ amount: "", invoice_type: "freight" });
  const [editClaim, setEditClaim] = useState({ amount: "", notes: "" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const [i, c, l, v, p, a, pd] = await Promise.all([
      apiGet("/api/v1/invoices").catch(() => []),
      apiGet("/api/v1/claims").catch(() => []),
      apiGet("/api/v1/laytimes").catch(() => []),
      apiGet("/api/v1/voyages").catch(() => []),
      apiGet("/api/v1/masterdata/counterparties").catch(() => []),
      apiGet("/api/v1/finance/accruals").catch(() => []),
      apiGet("/api/v1/port-disbursements").catch(() => []),
    ]);
    setInvoices(i);
    setClaims(c);
    setLaytimes(l);
    setVoyages(v);
    setParties(p);
    setAccruals(a);
    setPdas(pd);
    if (!invVoyage && v[0]?.id) setInvVoyage(v[0].id);
    if (!ltVoyage && v[0]?.id) setLtVoyage(v[0].id);
    if (!accVoyage && v[0]?.id) setAccVoyage(v[0].id);
    if (!pdaVoyage && v[0]?.id) setPdaVoyage(v[0].id);
    if (!invParty && p[0]?.id) setInvParty(p[0].id);
  }, [invVoyage, ltVoyage, invParty, accVoyage, pdaVoyage]);

  const loadPnl = useCallback(async () => {
    try {
      setPnl(await apiGet("/api/v1/analytics/reports/voyage-pnl"));
    } catch {
      setPnl([]);
    }
  }, []);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
    loadPnl().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createInvoice(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const inv = await apiPost("/api/v1/invoices", {
        invoice_type: invType,
        amount: Number(invAmount) || 0,
        voyage_id: invVoyage || null,
        counterparty_id: invParty || null,
      });
      setMsg(t("page.finance.created_inv", "Invoice {no} created", { no: inv.invoice_no }));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function invTransition(id: string, target: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/invoices/${id}/transition?target=${encodeURIComponent(target)}`);
      setMsg(t("page.finance.inv_moved", "Invoice → {target}", { target }));
      setOpenInv(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function saveInvoice() {
    if (!openInv) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/invoices/${openInv.id}`, {
        amount: Number(editInv.amount) || 0,
        invoice_type: editInv.invoice_type,
      });
      setMsg(t("common.saved", "Saved"));
      setOpenInv(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  async function removeInvoice() {
    if (!openInv) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/invoices/${openInv.id}`);
      setMsg(t("common.recycled", "Moved to recycle bin"));
      setOpenInv(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  async function saveClaim() {
    if (!openClaim) return;
    setSaving(true);
    try {
      await apiPatch(`/api/v1/claims/${openClaim.id}`, {
        amount: Number(editClaim.amount) || 0,
        notes: editClaim.notes || null,
      });
      setMsg(t("common.saved", "Saved"));
      setOpenClaim(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  async function removeClaim() {
    if (!openClaim) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/claims/${openClaim.id}`);
      setMsg(t("common.recycled", "Moved to recycle bin"));
      setOpenClaim(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  async function removeLaytime() {
    if (!selectedLt) return;
    if (!window.confirm(t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored."))) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/laytimes/${selectedLt}`);
      setSelectedLt(null);
      setMsg(t("common.recycled", "Moved to recycle bin"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function payInvoice(id: string) {
    const amount = Number(payAmount);
    if (!amount) {
      setErr(t("page.finance.need_pay", "Enter payment amount"));
      return;
    }
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/invoices/${id}/payments?amount=${amount}`);
      setMsg(t("page.finance.pay_ok", "Payment posted · status {status}", { status: res.status }));
      setPayAmount("");
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function glPost(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/invoices/${id}/gl-post`);
      setMsg(t("page.finance.gl_ok", "GL posted"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function createLaytime(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const inputs: Record<string, unknown> = {
        turn_time_hours: Number(ltTurn) || 0,
        demurrage_rate_per_day: Number(ltDem) || 0,
        despatch_rate_per_day: Number(ltDes) || 0,
        events: [
          { start: ltE1Start.length === 16 ? `${ltE1Start}:00` : ltE1Start, end: ltE1End.length === 16 ? `${ltE1End}:00` : ltE1End, excluded: false },
          { start: ltE2Start.length === 16 ? `${ltE2Start}:00` : ltE2Start, end: ltE2End.length === 16 ? `${ltE2End}:00` : ltE2End, excluded: true },
        ],
      };
      if (ltAllowed !== "") inputs.allowed_hours = Number(ltAllowed);
      if (ltCargoQty !== "" && ltLoadRate !== "") {
        inputs.cargo_qty = Number(ltCargoQty);
        inputs.load_rate_per_day = Number(ltLoadRate);
      }
      const lt = await apiPost("/api/v1/laytimes", {
        voyage_id: ltVoyage || null,
        inputs,
      });
      setSelectedLt(lt.id);
      setMsg(t("page.finance.lt_created", "Laytime draft created"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function calcLaytime(id: string) {
    setBusy(true);
    try {
      const res = await apiPost(`/api/v1/laytimes/${id}/calculate`);
      setMsg(t("page.finance.lt_calc", "Laytime amount {amt}", { amt: fmt(res.results?.amount) }));
      setSelectedLt(id);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function finalizeLaytime(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/laytimes/${id}/finalize`);
      setMsg(t("page.finance.lt_final", "Laytime finalized"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function claimFromLaytime(lt: Laytime) {
    setBusy(true);
    try {
      const claim = await apiPost("/api/v1/claims", {
        voyage_id: lt.voyage_id,
        laytime_id: lt.id,
        claim_type: (lt.results as any)?.result_type === "despatch" ? "despatch" : "demurrage",
        amount: lt.results?.amount ?? undefined,
      });
      setMsg(t("page.finance.claim_ok", "Claim {no} created", { no: claim.claim_no }));
      setTab("claims");
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function claimTransition(id: string, target: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/claims/${id}/transition?target=${encodeURIComponent(target)}`);
      setMsg(t("page.finance.claim_moved", "Claim → {target}", { target }));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function createAccrual(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await apiPost("/api/v1/finance/accruals", {
        voyage_id: accVoyage || null,
        period_ym: accPeriod,
        line_type: accType,
        amount: Number(accAmount) || 0,
        currency: accCurrency || "USD",
      });
      setMsg(t("page.finance.accrual_ok", "Accrual created"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function postAccrual(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/finance/accruals/${id}/post`);
      setMsg(t("page.finance.accrual_posted", "Accrual posted"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function createPda(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await apiPost("/api/v1/port-disbursements", {
        voyage_id: pdaVoyage || null,
        pda_amount: Number(pdaAmount) || 0,
        currency: pdaCurrency || "USD",
        lines: {},
      });
      setMsg(t("page.finance.pda_ok", "PDA created"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function pdaTransition(id: string, target: string) {
    setBusy(true);
    try {
      const q = new URLSearchParams({ target });
      if (target === "fda" && fdaAmount) q.set("fda_amount", String(Number(fdaAmount) || 0));
      await apiPost(`/api/v1/port-disbursements/${id}/transition?${q.toString()}`);
      setMsg(t("page.finance.pda_moved", "PDA → {target}", { target }));
      setFdaAmount("");
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "invoices", label: t("page.finance.invoices", "Invoices") },
    { id: "laytime", label: t("page.finance.laytime", "Laytime") },
    { id: "pnl", label: t("page.finance.pnl", "Dynamic P&L") },
    { id: "claims", label: t("page.finance.claims", "Claims") },
    { id: "accruals", label: t("page.finance.accruals", "Voyage accruals") },
    { id: "pda", label: t("page.finance.pda", "Port PDA/FDA") },
  ];

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.finance.title", "Finance / laytime / P&L")}</h1>
          <p className="page-sub">
            {t("page.finance.sub", "Invoices, laytime, claims, accruals and PDA/FDA. Open a row to edit or delete.")}
          </p>
        </div>
        <div className="quick-row">
          <Link href="/settings/recycle" className="btn btn-ghost">
            {t("nav.recycle", "Recycle bin")}
          </Link>
          <button className="btn btn-ghost" type="button" onClick={() => loadPnl()}>
            {t("page.finance.refresh_pnl", "刷新损益")}
          </button>
        </div>
      </div>

      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <div className="desk-tabs">
        {tabs.map((tb) => (
          <button
            key={tb.id}
            type="button"
            className={`desk-tab${tab === tb.id ? " active" : ""}`}
            onClick={() => setTab(tb.id)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      {tab === "invoices" ? (
        <>
          <form className="panel" onSubmit={createInvoice}>
            <h3 style={{ marginTop: 0 }}>{t("page.finance.new_invoice", "New invoice")}</h3>
            <div className="form-grid">
              <label>
                {t("common.type", "Type")}
                <select value={invType} onChange={(e) => setInvType(e.target.value)}>
                  <option value="freight">freight</option>
                  <option value="hire">hire</option>
                  <option value="demurrage">demurrage</option>
                  <option value="bunker">bunker</option>
                  <option value="other">other</option>
                </select>
              </label>
              <label>
                {t("common.amount", "Amount")}
                <input type="number" step="any" value={invAmount} onChange={(e) => setInvAmount(e.target.value)} />
              </label>
              <label>
                {t("page.voyages.list", "Voyages")}
                <select value={invVoyage} onChange={(e) => setInvVoyage(e.target.value)}>
                  <option value="">{t("common.select", "Select…")}</option>
                  {voyages.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.voyage_no}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("page.estimates.counterparty", "Counterparty")}
                <select value={invParty} onChange={(e) => setInvParty(e.target.value)}>
                  <option value="">{t("common.select", "Select…")}</option>
                  {parties.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="desk-toolbar">
              <button className="btn btn-primary" type="submit" disabled={busy}>
                {t("common.create", "Create")}
              </button>
            </div>
          </form>

          <div className="panel">
            <div className="form-grid" style={{ marginBottom: "0.75rem", maxWidth: 280 }}>
              <label>
                {t("page.finance.pay_amount", "Payment amount")}
                <input type="number" step="any" value={payAmount} onChange={(e) => setPayAmount(e.target.value)} />
              </label>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>{t("page.finance.no", "编号")}</th>
                  <th>{t("common.status", "Status")}</th>
                  <th>{t("common.amount", "Amount")}</th>
                  <th>{t("page.finance.paid_col", "已付")}</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((r) => (
                  <tr
                    key={r.id}
                    className="row-openable"
                    onClick={() => {
                      setOpenInv(r);
                      setEditInv({ amount: String(r.amount), invoice_type: r.invoice_type || "freight" });
                    }}
                  >
                    <td>{r.invoice_no}</td>
                    <td>{r.status}</td>
                    <td>{fmt(r.amount)}</td>
                    <td>{fmt(r.paid_amount)}</td>
                  </tr>
                ))}
                {!invoices.length ? (
                  <tr>
                    <td colSpan={4} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {tab === "laytime" ? (
        <>
          <form className="panel" onSubmit={createLaytime}>
            <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_desk", "Laytime desk")}</h3>
            <div className="form-grid">
              <label>
                {t("page.voyages.list", "Voyages")}
                <select value={ltVoyage} onChange={(e) => setLtVoyage(e.target.value)}>
                  <option value="">{t("common.select", "Select…")}</option>
                  {voyages.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.voyage_no}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("page.finance.allowed_hours", "Allowed hours")}
                <input type="number" step="any" value={ltAllowed} onChange={(e) => setLtAllowed(e.target.value)} />
              </label>
              <label>
                {t("page.estimates.cargo_qty", "Cargo qty")}
                <input type="number" step="any" value={ltCargoQty} onChange={(e) => setLtCargoQty(e.target.value)} placeholder="alt to allowed hours" />
              </label>
              <label>
                {t("page.finance.load_rate", "Load rate / day")}
                <input type="number" step="any" value={ltLoadRate} onChange={(e) => setLtLoadRate(e.target.value)} />
              </label>
              <label>
                {t("page.finance.turn_time", "Turn time hours")}
                <input type="number" step="any" value={ltTurn} onChange={(e) => setLtTurn(e.target.value)} />
              </label>
              <label>
                {t("page.finance.dem_rate", "Demurrage / day")}
                <input type="number" step="any" value={ltDem} onChange={(e) => setLtDem(e.target.value)} />
              </label>
              <label>
                {t("page.finance.des_rate", "Despatch / day")}
                <input type="number" step="any" value={ltDes} onChange={(e) => setLtDes(e.target.value)} />
              </label>
              <label>
                {t("page.finance.ev1_start", "Event 1 start")}
                <input type="datetime-local" value={ltE1Start} onChange={(e) => setLtE1Start(e.target.value)} />
              </label>
              <label>
                {t("page.finance.ev1_end", "Event 1 end")}
                <input type="datetime-local" value={ltE1End} onChange={(e) => setLtE1End(e.target.value)} />
              </label>
              <label>
                {t("page.finance.ev2_start", "Event 2 start (excluded)")}
                <input type="datetime-local" value={ltE2Start} onChange={(e) => setLtE2Start(e.target.value)} />
              </label>
              <label>
                {t("page.finance.ev2_end", "Event 2 end")}
                <input type="datetime-local" value={ltE2End} onChange={(e) => setLtE2End(e.target.value)} />
              </label>
            </div>
            <div className="desk-toolbar">
              <button className="btn btn-primary" type="submit" disabled={busy}>
                {t("common.create", "Create")}
              </button>
            </div>
          </form>

          <div className="panel">
            {selectedLt ? (
              <div className="desk-toolbar" style={{ marginBottom: "0.75rem" }}>
                <span className="muted">
                  {t("page.finance.lt_selected", "已选滞期")} {selectedLt.slice(0, 8)}
                </span>
                <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={removeLaytime}>
                  {t("common.delete", "删除")}
                </button>
              </div>
            ) : null}
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>{t("page.voyages.list", "Voyages")}</th>
                  <th>{t("common.status", "Status")}</th>
                  <th>{t("common.amount", "Amount")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {laytimes.map((r) => (
                  <tr key={r.id} className={r.id === selectedLt ? "selected" : ""} style={{ cursor: "pointer" }} onClick={() => setSelectedLt(r.id)}>
                    <td>{r.id.slice(0, 8)}</td>
                    <td>{r.voyage_id ? voyages.find((v) => v.id === r.voyage_id)?.voyage_no || r.voyage_id.slice(0, 8) : "—"}</td>
                    <td>{r.status}</td>
                    <td>{fmt(r.results?.amount)}</td>
                    <td>
                      <div className="desk-toolbar" style={{ margin: 0 }}>
                        {r.status === "draft" || r.status === "calculated" ? (
                          <button className="btn btn-sm" type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); calcLaytime(r.id); }}>
                            {t("page.estimates.calculate", "Calculate")}
                          </button>
                        ) : null}
                        {r.status === "calculated" ? (
                          <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); finalizeLaytime(r.id); }}>
                            {t("page.finance.finalize", "Finalize")}
                          </button>
                        ) : null}
                        {r.status === "finalized" || r.status === "calculated" ? (
                          <button className="btn btn-sm" type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); claimFromLaytime(r); }}>
                            {t("page.finance.create_claim", "Create claim")}
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
                {!laytimes.length ? (
                  <tr>
                    <td colSpan={5} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {tab === "pnl" ? (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.finance.pnl", "Dynamic P&L")}</h3>
          <table className="table">
            <thead>
              <tr>
                <th>{t("page.voyages.no", "No")}</th>
                <th>{t("common.status", "Status")}</th>
                <th>{t("page.finance.est_rev", "Est. revenue")}</th>
                <th>{t("page.finance.est_cost", "Est. cost")}</th>
                <th>{t("page.finance.est_pnl", "Est. P&L")}</th>
                <th>{t("page.finance.act_rev", "Actual revenue")}</th>
                <th>{t("page.finance.act_cost", "Actual cost")}</th>
                <th>{t("page.finance.act_pnl", "Actual P&L")}</th>
                <th>{t("page.finance.variance", "Variance")}</th>
                <th>TCE</th>
              </tr>
            </thead>
            <tbody>
              {pnl.map((r) => (
                <tr key={r.voyage_id}>
                  <td>{r.voyage_no}</td>
                  <td>{r.status}</td>
                  <td>{fmt(r.estimated_revenue)}</td>
                  <td>{fmt(r.estimated_cost)}</td>
                  <td>{fmt(r.estimated_pnl)}</td>
                  <td>{fmt(r.actual_revenue)}</td>
                  <td>{fmt(r.actual_cost)}</td>
                  <td>{fmt(r.actual_pnl)}</td>
                  <td>{fmt(r.variance_pnl)}</td>
                  <td>{fmt(r.estimated_tce ?? null)}</td>
                </tr>
              ))}
              {!pnl.length ? (
                <tr>
                  <td colSpan={10} className="muted">
                    {t("common.empty", "No records")}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}

      {tab === "claims" ? (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.finance.claims", "Claims")}</h3>
          <table className="table">
            <thead>
              <tr>
                <th>{t("page.finance.no", "编号")}</th>
                <th>{t("common.status", "Status")}</th>
                <th>{t("common.amount", "Amount")}</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((r) => (
                <tr
                  key={r.id}
                  className="row-openable"
                  onClick={() => {
                    setOpenClaim(r);
                    setEditClaim({ amount: String(r.amount), notes: "" });
                  }}
                >
                  <td>{r.claim_no}</td>
                  <td>{r.status}</td>
                  <td>{fmt(r.amount)}</td>
                </tr>
              ))}
              {!claims.length ? (
                <tr>
                  <td colSpan={3} className="muted">
                    {t("common.empty", "No records")}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ) : null}

      {tab === "accruals" ? (
        <>
          <form className="panel" onSubmit={createAccrual}>
            <h3 style={{ marginTop: 0 }}>{t("page.finance.new_accrual", "New accrual")}</h3>
            <div className="form-grid">
              <label>
                {t("page.finance.period", "Period YYYY-MM")}
                <input value={accPeriod} onChange={(e) => setAccPeriod(e.target.value)} required />
              </label>
              <label>
                {t("common.type", "类型")}
                <select value={accType} onChange={(e) => setAccType(e.target.value)}>
                  <option value="freight">{t("page.finance.line_freight", "Freight")}</option>
                  <option value="hire">{t("page.finance.line_hire", "Hire")}</option>
                  <option value="commission">{t("page.finance.line_commission", "Commission")}</option>
                  <option value="bunker">{t("page.finance.line_bunker", "Bunker")}</option>
                  <option value="port">{t("page.finance.line_port", "Port costs")}</option>
                  <option value="other">{t("page.finance.line_other", "Other")}</option>
                </select>
              </label>
              <label>
                {t("common.amount", "Amount")}
                <input type="number" step="any" value={accAmount} onChange={(e) => setAccAmount(e.target.value)} />
              </label>
              <label>
                {t("page.finance.currency", "Currency")}
                <LookupSelect dataset="currencies" value={accCurrency} onChange={setAccCurrency} allowEmpty={false} />
              </label>
              <label>
                {t("page.voyages.list", "Voyages")}
                <select value={accVoyage} onChange={(e) => setAccVoyage(e.target.value)}>
                  <option value="">—</option>
                  {voyages.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.voyage_no}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {t("common.create", "Create")}
            </button>
          </form>
          <div className="panel">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("page.finance.period", "Period YYYY-MM")}</th>
                  <th>{t("common.type", "类型")}</th>
                  <th>{t("page.voyages.list", "Voyages")}</th>
                  <th>{t("common.amount", "Amount")}</th>
                  <th>{t("common.status", "Status")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {accruals.map((r) => (
                  <tr key={r.id}>
                    <td>{r.period_ym}</td>
                    <td>{r.line_type}</td>
                    <td>{r.voyage_id ? voyages.find((v) => v.id === r.voyage_id)?.voyage_no || r.voyage_id.slice(0, 8) : "—"}</td>
                    <td>
                      {fmt(r.amount)} {r.currency}
                    </td>
                    <td>{r.status}</td>
                    <td>
                      {r.status === "draft" ? (
                        <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => postAccrual(r.id)}>
                          {t("page.finance.post", "Post")}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
                {!accruals.length ? (
                  <tr>
                    <td colSpan={6} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {tab === "pda" ? (
        <>
          <form className="panel" onSubmit={createPda}>
            <h3 style={{ marginTop: 0 }}>{t("page.finance.new_pda", "New PDA")}</h3>
            <div className="form-grid">
              <label>
                {t("page.voyages.list", "Voyages")}
                <select value={pdaVoyage} onChange={(e) => setPdaVoyage(e.target.value)}>
                  <option value="">—</option>
                  {voyages.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.voyage_no}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                PDA {t("common.amount", "Amount")}
                <input type="number" step="any" value={pdaAmount} onChange={(e) => setPdaAmount(e.target.value)} />
              </label>
              <label>
                {t("page.finance.currency", "Currency")}
                <LookupSelect dataset="currencies" value={pdaCurrency} onChange={setPdaCurrency} allowEmpty={false} />
              </label>
              <label>
                FDA {t("page.finance.fda_amount", "FDA amount (on transfer)")}
                <input type="number" step="any" value={fdaAmount} onChange={(e) => setFdaAmount(e.target.value)} placeholder={t("common.optional", "Optional")} />
              </label>
            </div>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {t("common.create", "Create")}
            </button>
          </form>
          <div className="panel">
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>{t("page.voyages.list", "Voyages")}</th>
                  <th>PDA</th>
                  <th>FDA</th>
                  <th>{t("page.finance.variance", "差异")}</th>
                  <th>{t("common.status", "Status")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {pdas.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id.slice(0, 8)}</td>
                    <td>{r.voyage_id ? voyages.find((v) => v.id === r.voyage_id)?.voyage_no || r.voyage_id.slice(0, 8) : "—"}</td>
                    <td>{fmt(r.pda_amount)}</td>
                    <td>{fmt(r.fda_amount ?? null)}</td>
                    <td>{fmt(r.variance ?? null)}</td>
                    <td>{r.status}</td>
                    <td>
                      <div className="desk-toolbar" style={{ margin: 0 }}>
                        {r.status === "draft" ? (
                          <button className="btn btn-sm" type="button" disabled={busy} onClick={() => pdaTransition(r.id, "submitted")}>
                            {t("common.submit", "提交")}
                          </button>
                        ) : null}
                        {r.status === "submitted" ? (
                          <button className="btn btn-sm" type="button" disabled={busy} onClick={() => pdaTransition(r.id, "approved")}>
                            {t("common.approve", "批准")}
                          </button>
                        ) : null}
                        {r.status === "approved" ? (
                          <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => pdaTransition(r.id, "fda")}>
                            → FDA
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
                {!pdas.length ? (
                  <tr>
                    <td colSpan={7} className="muted">
                      {t("common.empty", "No records")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      <RecordModal
        open={Boolean(openInv)}
        title={openInv ? `${t("page.finance.edit_inv", "编辑发票")} · ${openInv.invoice_no}` : ""}
        onClose={() => setOpenInv(null)}
        onSave={saveInvoice}
        onDelete={removeInvoice}
        saving={saving || busy}
      >
        <p className="muted">
          {t("common.status", "Status")}: {openInv?.status}
        </p>
        <label>
          {t("common.type", "类型")}
          <select value={editInv.invoice_type} onChange={(e) => setEditInv({ ...editInv, invoice_type: e.target.value })}>
            <option value="freight">freight</option>
            <option value="demurrage">demurrage</option>
            <option value="other">other</option>
          </select>
        </label>
        <label>
          {t("common.amount", "Amount")}
          <input type="number" step="any" value={editInv.amount} onChange={(e) => setEditInv({ ...editInv, amount: e.target.value })} />
        </label>
        <div className="desk-toolbar">
          {openInv?.status === "draft" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => openInv && invTransition(openInv.id, "pending_approval")}>
              {t("common.submit", "提交")}
            </button>
          ) : null}
          {openInv?.status === "pending_approval" ? (
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => openInv && invTransition(openInv.id, "issued")}>
              {t("page.finance.issue", "开票")}
            </button>
          ) : null}
          {openInv && (openInv.status === "issued" || openInv.status === "partially_paid") ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => openInv && payInvoice(openInv.id)}>
              {t("page.finance.pay", "收款")}
            </button>
          ) : null}
          {openInv && ["issued", "partially_paid", "paid"].includes(openInv.status) ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => openInv && glPost(openInv.id)}>
              {t("page.finance.gl", "过账")}
            </button>
          ) : null}
        </div>
      </RecordModal>

      <RecordModal
        open={Boolean(openClaim)}
        title={openClaim ? `${t("page.finance.edit_claim", "编辑索赔")} · ${openClaim.claim_no}` : ""}
        onClose={() => setOpenClaim(null)}
        onSave={saveClaim}
        onDelete={removeClaim}
        saving={saving || busy}
      >
        <p className="muted">
          {t("common.status", "Status")}: {openClaim?.status}
        </p>
        <label>
          {t("common.amount", "Amount")}
          <input type="number" step="any" value={editClaim.amount} onChange={(e) => setEditClaim({ ...editClaim, amount: e.target.value })} />
        </label>
        <label>
          {t("page.finance.notes", "备注")}
          <input value={editClaim.notes} onChange={(e) => setEditClaim({ ...editClaim, notes: e.target.value })} />
        </label>
        <div className="desk-toolbar">
          {openClaim?.status === "open" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => openClaim && claimTransition(openClaim.id, "negotiating")}>
              {t("page.finance.negotiate", "谈判")}
            </button>
          ) : null}
          {openClaim && (openClaim.status === "open" || openClaim.status === "negotiating") ? (
            <>
              <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => openClaim && claimTransition(openClaim.id, "settled")}>
                {t("page.finance.settle", "结清")}
              </button>
              <button className="btn btn-sm" type="button" disabled={busy} onClick={() => openClaim && claimTransition(openClaim.id, "withdrawn")}>
                {t("page.finance.withdraw", "撤回")}
              </button>
            </>
          ) : null}
        </div>
      </RecordModal>
    </AppShell>
  );
}
