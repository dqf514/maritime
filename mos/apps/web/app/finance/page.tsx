"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateInput, DateTimeInput } from "@/components/DateInput";
import { LookupSelect } from "@/components/LookupSelect";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type RefItem = { id: string; name: string };
type Voyage = { id: string; voyage_no: string; status: string };
type Invoice = {
  id: string;
  invoice_no: string;
  status: string;
  amount: number;
  paid_amount?: number;
  invoice_type?: string;
  fx_rate?: number | null;
  base_amount?: number | null;
};
type Claim = { id: string; claim_no: string; status: string; amount: number; time_bar?: string | null; days_to_timebar?: number | null };
type CreditNote = { id: string; amount: number; reason?: string | null; created_at?: string | null };
type Payment = { id: string; amount: number; currency: string; reference: string | null; paid_at: string | null; is_void_reversal: boolean };
type CharterRef = { id: string; charter_no: string };
type RiskLimit = { id: string; scope: string; limit_type: string; amount: number; currency: string };

const INVOICE_TYPES = ["freight", "hire", "demurrage", "bunker", "port_disbursement", "credit_note", "other"];
type Laytime = {
  id: string;
  voyage_id: string | null;
  port_call_id?: string | null;
  status: string;
  inputs: Record<string, unknown>;
  results: { amount?: number; used_hours?: number; demurrage_hours?: number; despatch_hours?: number };
};
type LaytimeEventRow = {
  start: string;
  end: string;
  kind: string;
  caller_excluded: boolean;
  gross_hours: number;
  term_excluded_hours: number;
  counted_hours: number;
  cumulative_hours: number;
  note?: string;
};
type LaytimeStatement = {
  id: string;
  status: string;
  format?: string;
  terms?: string;
  allowed_hours?: number;
  used_hours?: number;
  excluded_hours?: number;
  balance_hours?: number;
  result_type?: string;
  amount?: number;
  currency?: string;
  events?: LaytimeEventRow[];
  ports?: Array<{ port?: string; events?: LaytimeEventRow[] }>;
};
type PnlLineKey = "revenue" | "hire" | "demurrage" | "port_costs" | "canal" | "bunker" | "commission" | "emissions" | "other";
const PNL_LINE_KEYS: PnlLineKey[] = ["revenue", "hire", "demurrage", "port_costs", "canal", "bunker", "commission", "emissions", "other"];
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
  lines?: Record<string, number>;
  lines_accrual?: Record<string, number>;
  accrual_net?: number;
  accrual_pnl?: number;
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

type Tab = "invoices" | "laytime" | "pnl" | "claims" | "accruals" | "pda" | "risk";

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
  const [invFx, setInvFx] = useState("");
  const [payAmount, setPayAmount] = useState("");

  const [charters, setCharters] = useState<CharterRef[]>([]);
  const [hsCharter, setHsCharter] = useState("");
  const [hsStart, setHsStart] = useState("");
  const [hsEnd, setHsEnd] = useState("");

  const [creditNotes, setCreditNotes] = useState<{ inv: string; rows: CreditNote[] } | null>(null);
  const [payments, setPayments] = useState<{ inv: string; rows: Payment[] } | null>(null);
  const [cnAmount, setCnAmount] = useState("");
  const [cnReason, setCnReason] = useState("");
  const [cnOpen, setCnOpen] = useState(false);
  const [settleAmount, setSettleAmount] = useState("");

  const [limits, setLimits] = useState<RiskLimit[]>([]);
  const [rlScope, setRlScope] = useState("global");
  const [rlType, setRlType] = useState("exposure");
  const [rlAmount, setRlAmount] = useState("");
  const [rlCurrency, setRlCurrency] = useState("USD");

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
  const [sofPortCallId, setSofPortCallId] = useState("");
  const [sofAllowed, setSofAllowed] = useState("");
  const [sofTerms, setSofTerms] = useState("");
  const [ltExport, setLtExport] = useState<LaytimeStatement | null>(null);
  const [pnlBasis, setPnlBasis] = useState<"actual" | "accrual">("actual");
  const [selectedPnl, setSelectedPnl] = useState<string | null>(null);
  const [openInv, setOpenInv] = useState<Invoice | null>(null);
  const [openClaim, setOpenClaim] = useState<Claim | null>(null);
  const [editInv, setEditInv] = useState({ amount: "", invoice_type: "freight" });
  const [editClaim, setEditClaim] = useState({ amount: "", notes: "" });
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  const load = useCallback(async () => {
    const [i, c, l, v, p, a, pd, ch, rl] = await Promise.all([
      apiGet("/api/v1/invoices").catch(() => []),
      apiGet("/api/v1/claims").catch(() => []),
      apiGet("/api/v1/laytimes").catch(() => []),
      apiGet("/api/v1/voyages").catch(() => []),
      apiGet("/api/v1/masterdata/counterparties").catch(() => []),
      apiGet("/api/v1/finance/accruals").catch(() => []),
      apiGet("/api/v1/port-disbursements").catch(() => []),
      apiGet("/api/v1/charters").catch(() => []),
      apiGet("/api/v1/risk/limits").catch(() => []),
    ]);
    setInvoices(i);
    setClaims(c);
    setLaytimes(l);
    setVoyages(v);
    setParties(p);
    setAccruals(a);
    setPdas(pd);
    setCharters(ch);
    setLimits(rl);
    if (!hsCharter && ch[0]?.id) setHsCharter(ch[0].id);
    if (!invVoyage && v[0]?.id) setInvVoyage(v[0].id);
    if (!ltVoyage && v[0]?.id) setLtVoyage(v[0].id);
    if (!accVoyage && v[0]?.id) setAccVoyage(v[0].id);
    if (!pdaVoyage && v[0]?.id) setPdaVoyage(v[0].id);
    if (!invParty && p[0]?.id) setInvParty(p[0].id);
  }, [invVoyage, ltVoyage, invParty, accVoyage, pdaVoyage, hsCharter]);

  const loadPnl = useCallback(async (basis: "actual" | "accrual" = "actual") => {
    try {
      setPnl(await apiGet(`/api/v1/analytics/reports/voyage-pnl?basis=${basis}`));
    } catch {
      setPnl([]);
    }
  }, []);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
    loadPnl().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!openInv) return;
    let cancelled = false;
    apiGet(`/api/v1/invoices/${openInv.id}/credit-notes`)
      .then((rows: CreditNote[]) => {
        if (!cancelled) setCreditNotes({ inv: openInv.id, rows: Array.isArray(rows) ? rows : [] });
      })
      .catch(() => {
        if (!cancelled) setCreditNotes({ inv: openInv.id, rows: [] });
      });
    apiGet(`/api/v1/invoices/${openInv.id}/payments`)
      .then((rows: Payment[]) => {
        if (!cancelled) setPayments({ inv: openInv.id, rows: Array.isArray(rows) ? rows : [] });
      })
      .catch(() => {
        if (!cancelled) setPayments({ inv: openInv.id, rows: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [openInv]);

  async function createInvoice(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    const amount = Number(invAmount);
    if (!invAmount.trim() || Number.isNaN(amount)) {
      setErr(t("page.finance.bad_amount", "金额必须是有效数字"));
      setBusy(false);
      return;
    }
    try {
      const inv = await apiPost("/api/v1/invoices", {
        invoice_type: invType,
        amount,
        voyage_id: invVoyage || null,
        counterparty_id: invParty || null,
        fx_rate: invFx === "" ? undefined : Number(invFx),
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
    } catch (ex: any) {
      if (ex?.status === 409 && ex?.detail?.code === "CREDIT_NOTE_REQUIRED") {
        setErr(t("page.finance.credit_required", "发票已收款，需先红冲（credit note）后才能作废。"));
      } else {
        setErr(String(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  async function createCreditNote(e: FormEvent) {
    e.preventDefault();
    if (!openInv) return;
    const amount = Number(cnAmount);
    if (!cnAmount.trim() || Number.isNaN(amount)) {
      setErr(t("page.finance.bad_amount", "金额必须是有效数字"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/invoices/${openInv.id}/credit-note`, { amount, reason: cnReason || null });
      setMsg(t("page.finance.cn_ok", "Credit note posted"));
      setCnAmount("");
      setCnReason("");
      setCnOpen(false);
      const rows = await apiGet(`/api/v1/invoices/${openInv.id}/credit-notes`).catch(() => []);
      setCreditNotes({ inv: openInv.id, rows: Array.isArray(rows) ? rows : [] });
      await load();
    } catch (ex: any) {
      if (ex?.status === 409 && ex?.detail?.code === "CREDIT_EXCEEDS_BALANCE") {
        setErr(t("page.finance.cn_exceeds", "红冲金额超过发票余额"));
      } else {
        setErr(String(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  async function createHireSchedule(e: FormEvent) {
    e.preventDefault();
    if (!hsCharter || !hsStart || !hsEnd) {
      setErr(t("page.finance.hs_need", "请选择租约并填写期间"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const inv = await apiPost("/api/v1/invoices/hire-schedule", {
        charter_id: hsCharter,
        period_start: hsStart,
        period_end: hsEnd,
      });
      setMsg(t("page.finance.created_inv", "Invoice {no} created", { no: inv.invoice_no }));
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
    const amount = Number(editInv.amount);
    if (!String(editInv.amount).trim() || Number.isNaN(amount)) {
      setErr(t("page.finance.bad_amount", "金额必须是有效数字"));
      setSaving(false);
      return;
    }
    try {
      await apiPatch(`/api/v1/invoices/${openInv.id}`, {
        amount,
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
      if (openInv?.id === id) {
        const rows = await apiGet(`/api/v1/invoices/${id}/payments`).catch(() => []);
        setPayments({ inv: id, rows: Array.isArray(rows) ? rows : [] });
      }
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function voidPayment(id: string) {
    if (!openInv) return;
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/payments/${id}/void`);
      setMsg(t("page.finance.void_ok", "付款已冲正"));
      const rows = await apiGet(`/api/v1/invoices/${openInv.id}/payments`).catch(() => []);
      setPayments({ inv: openInv.id, rows: Array.isArray(rows) ? rows : [] });
      await load();
    } catch (ex: any) {
      const code = ex?.detail?.code || "";
      if (ex?.status === 409 && code === "ALREADY_VOIDED") {
        setErr(t("page.finance.void_already", "该付款已冲正，请勿重复操作"));
      } else if (ex?.status === 409 && code === "GL_POSTED") {
        setErr(t("page.finance.void_gl_posted", "发票已过账（GL posted），禁止冲正其付款"));
      } else {
        setErr(String(ex));
      }
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

  async function createFromSof(e: FormEvent) {
    e.preventDefault();
    if (!sofPortCallId.trim()) {
      setErr(t("page.finance.sof_need_pc", "请填写 port_call_id"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const body: Record<string, unknown> = { port_call_id: sofPortCallId.trim() };
      if (sofAllowed !== "") body.allowed_hours = Number(sofAllowed);
      if (sofTerms) body.terms = sofTerms;
      const lt = await apiPost("/api/v1/laytimes/from-sof", body);
      setSelectedLt(lt.id);
      setMsg(t("page.finance.lt_sof_ok", "已从 SOF 生成并计算"));
      await load();
    } catch (ex: any) {
      const code = ex?.detail?.code || "";
      if (ex?.status === 422 && code === "ALLOWED_HOURS_REQUIRED") {
        setErr(t("page.finance.sof_allowed_required", "无法从租约推导允许小时，请填写 allowed hours"));
      } else if (ex?.status === 422 && code === "INSUFFICIENT_SOF") {
        setErr(t("page.finance.sof_insufficient", "SOF 事件不足（至少需要 COMMENCED 与 COMPLETED）"));
      } else {
        setErr(String(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  async function exportLaytime(id: string) {
    setBusy(true);
    setErr("");
    try {
      const data: LaytimeStatement = await apiGet(`/api/v1/laytimes/${id}/export`);
      setLtExport(data);
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
      const q = new URLSearchParams({ target });
      if (target === "settled" && settleAmount !== "") q.set("settlement_amount", String(Number(settleAmount) || 0));
      await apiPost(`/api/v1/claims/${id}/transition?${q.toString()}`);
      setMsg(t("page.finance.claim_moved", "Claim → {target}", { target }));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function claimToInvoice(id: string) {
    setBusy(true);
    try {
      const inv = await apiPost(`/api/v1/claims/${id}/to-invoice`);
      setMsg(t("page.finance.created_inv", "Invoice {no} created", { no: inv.invoice_no }));
      setOpenClaim(null);
      await load();
    } catch (ex: any) {
      if (ex?.status === 409) {
        setErr(t("page.finance.claim_not_settled", "索赔未结清，不能生成发票"));
      } else {
        setErr(String(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  async function createRiskLimit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await apiPost("/api/v1/risk/limits", {
        scope: rlScope || "global",
        limit_type: rlType || "exposure",
        amount: Number(rlAmount) || 0,
        currency: rlCurrency || "USD",
      });
      setMsg(t("page.finance.limit_ok", "Risk limit saved"));
      setRlAmount("");
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

  const cnRows = openInv && creditNotes?.inv === openInv.id ? creditNotes.rows : [];
  const payRows = openInv && payments?.inv === openInv.id ? payments.rows : [];

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "invoices", label: t("page.finance.invoices", "Invoices") },
    { id: "laytime", label: t("page.finance.laytime", "Laytime") },
    { id: "pnl", label: t("page.finance.pnl", "Dynamic P&L") },
    { id: "claims", label: t("page.finance.claims", "Claims") },
    { id: "accruals", label: t("page.finance.accruals", "Voyage accruals") },
    { id: "pda", label: t("page.finance.pda", "Port PDA/FDA") },
    { id: "risk", label: t("page.finance.risk", "Risk limits") },
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
          <button className="btn btn-ghost" type="button" onClick={() => loadPnl(pnlBasis)}>
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
                  {INVOICE_TYPES.map((it) => (
                    <option key={it} value={it}>
                      {it}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("common.amount", "Amount")}
                <input type="number" step="any" value={invAmount} onChange={(e) => setInvAmount(e.target.value)} />
              </label>
              <label>
                {t("page.finance.fx_rate", "FX rate")}
                <input type="number" step="any" value={invFx} onChange={(e) => setInvFx(e.target.value)} placeholder={t("common.optional", "Optional")} />
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

          <form className="panel" onSubmit={createHireSchedule}>
            <h3 style={{ marginTop: 0 }}>{t("page.finance.hire_schedule", "Hire invoice (schedule)")}</h3>
            <div className="form-grid">
              <label>
                {t("page.charters.title", "租约")}
                <select value={hsCharter} onChange={(e) => setHsCharter(e.target.value)}>
                  <option value="">{t("common.select", "Select…")}</option>
                  {charters.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.charter_no}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("page.finance.period_start", "Period start")}
                <DateInput value={hsStart} onChange={setHsStart} />
              </label>
              <label>
                {t("page.finance.period_end", "Period end")}
                <DateInput value={hsEnd} onChange={setHsEnd} />
              </label>
            </div>
            <div className="desk-toolbar">
              <button className="btn btn-primary" type="submit" disabled={busy}>
                {t("page.finance.hs_generate", "生成 hire 发票")}
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
                  <th>{t("page.finance.base_amount", "Base")}</th>
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
                      setCnOpen(false);
                      setCnAmount("");
                      setCnReason("");
                    }}
                  >
                    <td>{r.invoice_no}</td>
                    <td>{r.status}</td>
                    <td>{fmt(r.amount)}</td>
                    <td>{r.base_amount != null ? fmt(r.base_amount) : "—"}</td>
                    <td>{fmt(r.paid_amount)}</td>
                  </tr>
                ))}
                {!invoices.length ? (
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
                <DateTimeInput value={ltE1Start} onChange={setLtE1Start} />
              </label>
              <label>
                {t("page.finance.ev1_end", "Event 1 end")}
                <DateTimeInput value={ltE1End} onChange={setLtE1End} />
              </label>
              <label>
                {t("page.finance.ev2_start", "Event 2 start (excluded)")}
                <DateTimeInput value={ltE2Start} onChange={setLtE2Start} />
              </label>
              <label>
                {t("page.finance.ev2_end", "Event 2 end")}
                <DateTimeInput value={ltE2End} onChange={setLtE2End} />
              </label>
            </div>
            <div className="desk-toolbar">
              <button className="btn btn-primary" type="submit" disabled={busy}>
                {t("common.create", "Create")}
              </button>
            </div>
          </form>

          <form className="panel" onSubmit={createFromSof}>
            <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_from_sof", "从 SOF 生成")}</h3>
            <div className="form-grid">
              <label>
                Port call ID
                <input value={sofPortCallId} onChange={(e) => setSofPortCallId(e.target.value)} placeholder="port_call_id (UUID)" />
              </label>
              <label>
                {t("page.finance.allowed_hours", "Allowed hours")}
                <input type="number" step="any" value={sofAllowed} onChange={(e) => setSofAllowed(e.target.value)} placeholder={t("common.optional", "Optional")} />
              </label>
              <label>
                {t("page.charters.laytime_terms", "Laytime terms")}
                <select value={sofTerms} onChange={(e) => setSofTerms(e.target.value)}>
                  <option value="">—</option>
                  <option value="SHINC">SHINC</option>
                  <option value="SHEX">SHEX</option>
                  <option value="SSHEX">SSHEX</option>
                  <option value="SSHINC">SSHINC</option>
                  <option value="FHEX">FHEX</option>
                </select>
              </label>
            </div>
            <div className="desk-toolbar">
              <button className="btn btn-sm" type="submit" disabled={busy}>
                {t("page.finance.lt_from_sof_btn", "从 SOF 生成")}
              </button>
            </div>
          </form>

          <div className="panel">
            {selectedLt ? (
              <div className="desk-toolbar" style={{ marginBottom: "0.75rem" }}>
                <span className="muted">
                  {t("page.finance.lt_selected", "已选滞期")} {selectedLt.slice(0, 8)}
                </span>
                <button
                  className="btn btn-danger btn-sm"
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    setConfirm({
                      message: t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored."),
                      danger: true,
                      action: removeLaytime,
                    })
                  }
                >
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
                    <td>
                      {r.status}
                      {r.status === "finalized" ? (
                        <span className="badge badge-warn" style={{ marginLeft: "0.4rem" }}>
                          {t("page.finance.lt_locked", "已锁定")}
                        </span>
                      ) : null}
                    </td>
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
                        <button className="btn btn-ghost btn-sm" type="button" disabled={busy} onClick={(e) => { e.stopPropagation(); exportLaytime(r.id); }}>
                          {t("page.finance.lt_export", "导出计算书")}
                        </button>
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
          <div className="desk-toolbar" style={{ marginBottom: "0.75rem" }}>
            <h3 style={{ margin: 0 }}>{t("page.finance.pnl", "Dynamic P&L")}</h3>
            <button
              className={`btn btn-sm${pnlBasis === "actual" ? " btn-primary" : ""}`}
              type="button"
              onClick={() => {
                setPnlBasis("actual");
                loadPnl("actual");
              }}
            >
              actual
            </button>
            <button
              className={`btn btn-sm${pnlBasis === "accrual" ? " btn-primary" : ""}`}
              type="button"
              onClick={() => {
                setPnlBasis("accrual");
                loadPnl("accrual");
              }}
            >
              accrual
            </button>
          </div>
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
                {pnlBasis === "accrual" ? <th>{t("page.finance.accrual_net", "Accrual net")}</th> : null}
                <th>{t("page.finance.variance", "Variance")}</th>
                <th>TCE</th>
              </tr>
            </thead>
            <tbody>
              {pnl.map((r) => (
                <tr
                  key={r.voyage_id}
                  className={r.voyage_id === selectedPnl ? "selected" : ""}
                  style={{ cursor: "pointer" }}
                  onClick={() => setSelectedPnl(r.voyage_id === selectedPnl ? null : r.voyage_id)}
                >
                  <td>{r.voyage_no}</td>
                  <td>{r.status}</td>
                  <td>{fmt(r.estimated_revenue)}</td>
                  <td>{fmt(r.estimated_cost)}</td>
                  <td>{fmt(r.estimated_pnl)}</td>
                  <td>{fmt(r.actual_revenue)}</td>
                  <td>{fmt(r.actual_cost)}</td>
                  <td>{fmt(r.actual_pnl)}</td>
                  {pnlBasis === "accrual" ? <td>{fmt(r.accrual_net ?? null)}</td> : null}
                  <td>{fmt(r.variance_pnl)}</td>
                  <td>{fmt(r.estimated_tce ?? null)}</td>
                </tr>
              ))}
              {!pnl.length ? (
                <tr>
                  <td colSpan={pnlBasis === "accrual" ? 11 : 10} className="muted">
                    {t("common.empty", "No records")}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
          {(() => {
            const sel = pnl.find((r) => r.voyage_id === selectedPnl);
            if (!sel || !sel.lines) return null;
            return (
              <div className="desk-section">
                <h3>
                  {t("page.finance.pnl_lines", "行项分列")} · {sel.voyage_no}
                </h3>
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("page.finance.line", "Line")}</th>
                      <th>{pnlBasis === "accrual" ? t("page.finance.lines_merged", "Merged") : t("page.finance.lines_actual", "Actual")}</th>
                      {pnlBasis === "accrual" ? <th>{t("page.finance.lines_accrual", "Accrual")}</th> : null}
                    </tr>
                  </thead>
                  <tbody>
                    {PNL_LINE_KEYS.map((k) => (
                      <tr key={k}>
                        <td>{k}</td>
                        <td>{fmt(sel.lines?.[k] ?? 0)}</td>
                        {pnlBasis === "accrual" ? <td>{fmt(sel.lines_accrual?.[k] ?? 0)}</td> : null}
                      </tr>
                    ))}
                    {pnlBasis === "accrual" ? (
                      <tr>
                        <td>
                          <strong>{t("page.finance.accrual_net", "Accrual net")}</strong>
                        </td>
                        <td>
                          <strong>{fmt(sel.accrual_net ?? null)}</strong>
                        </td>
                        <td></td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            );
          })()}
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
                <th>{t("page.finance.days_to_timebar", "Days to time bar")}</th>
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
                    setSettleAmount(String(r.amount));
                  }}
                >
                  <td>{r.claim_no}</td>
                  <td>{r.status}</td>
                  <td>{fmt(r.amount)}</td>
                  <td>
                    {r.days_to_timebar != null ? (
                      <span style={r.days_to_timebar < 14 ? { color: "#dc2626", fontWeight: 600 } : undefined}>
                        {r.days_to_timebar}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
              {!claims.length ? (
                <tr>
                  <td colSpan={4} className="muted">
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

      {tab === "risk" ? (
        <>
          <form className="panel" onSubmit={createRiskLimit}>
            <h3 style={{ marginTop: 0 }}>{t("page.finance.new_limit", "New risk limit")}</h3>
            <div className="form-grid">
              <label>
                {t("page.finance.scope", "Scope")}
                <input value={rlScope} onChange={(e) => setRlScope(e.target.value)} placeholder="global / symbol:X / counterparty:Y" required />
              </label>
              <label>
                {t("common.type", "Type")}
                <input value={rlType} onChange={(e) => setRlType(e.target.value)} placeholder="exposure" required />
              </label>
              <label>
                {t("common.amount", "Amount")}
                <input type="number" step="any" value={rlAmount} onChange={(e) => setRlAmount(e.target.value)} required />
              </label>
              <label>
                {t("page.finance.currency", "Currency")}
                <LookupSelect dataset="currencies" value={rlCurrency} onChange={setRlCurrency} allowEmpty={false} />
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
                  <th>{t("page.finance.scope", "Scope")}</th>
                  <th>{t("common.type", "Type")}</th>
                  <th>{t("common.amount", "Amount")}</th>
                  <th>{t("page.finance.currency", "Currency")}</th>
                </tr>
              </thead>
              <tbody>
                {limits.map((r, i) => (
                  <tr key={r.id || i}>
                    <td>{r.scope}</td>
                    <td>{r.limit_type}</td>
                    <td>{fmt(r.amount)}</td>
                    <td>{r.currency}</td>
                  </tr>
                ))}
                {!limits.length ? (
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
            {INVOICE_TYPES.map((it) => (
              <option key={it} value={it}>
                {it}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("common.amount", "Amount")}
          <input type="number" step="any" value={editInv.amount} onChange={(e) => setEditInv({ ...editInv, amount: e.target.value })} />
        </label>
        <div className="desk-section" style={{ margin: "0.5rem 0" }}>
          <div className="desk-toolbar" style={{ margin: 0 }}>
            <h3 style={{ margin: 0, fontSize: "0.95rem" }}>
              {t("page.finance.credit_notes", "Credit notes")} ({cnRows.length})
            </h3>
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => setCnOpen((v) => !v)}>
              {t("page.finance.credit_note", "红冲")}
            </button>
          </div>
          {cnRows.length ? (
            <table className="table" style={{ marginTop: "0.5rem" }}>
              <tbody>
                {cnRows.map((cn) => (
                  <tr key={cn.id}>
                    <td>{fmt(cn.amount)}</td>
                    <td>{cn.reason || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {cnOpen ? (
            <form className="form-grid" style={{ marginTop: "0.5rem" }} onSubmit={createCreditNote}>
              <label>
                {t("common.amount", "Amount")}
                <input type="number" step="any" value={cnAmount} onChange={(e) => setCnAmount(e.target.value)} />
              </label>
              <label>
                {t("page.finance.reason", "Reason")}
                <input value={cnReason} onChange={(e) => setCnReason(e.target.value)} />
              </label>
              <div style={{ display: "flex", alignItems: "end" }}>
                <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>
                  {t("page.finance.cn_submit", "提交红冲")}
                </button>
              </div>
            </form>
          ) : null}
        </div>
        <div className="desk-section" style={{ margin: "0.5rem 0" }}>
          <h3 style={{ margin: 0, fontSize: "0.95rem" }}>
            {t("page.finance.payments", "付款记录")} ({payRows.length})
          </h3>
          {payRows.length ? (
            <table className="table" style={{ marginTop: "0.5rem" }}>
              <thead>
                <tr>
                  <th>{t("common.amount", "Amount")}</th>
                  <th>{t("page.finance.currency", "Currency")}</th>
                  <th>{t("page.finance.reference", "Reference")}</th>
                  <th>{t("page.finance.paid_at", "时间")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {payRows.map((p) => (
                  <tr key={p.id}>
                    <td>{fmt(p.amount)}</td>
                    <td>{p.currency}</td>
                    <td>{p.reference || "—"}</td>
                    <td>{p.paid_at ? new Date(p.paid_at).toLocaleString() : "—"}</td>
                    <td>
                      {p.is_void_reversal ? (
                        <span className="badge badge-warn">{t("page.finance.voided_badge", "冲正")}</span>
                      ) : (
                        <button
                          className="btn btn-danger btn-sm"
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            setConfirm({
                              message: t("page.finance.void_confirm", "确认冲正这笔付款？将生成等额反向付款行。"),
                              danger: true,
                              action: () => voidPayment(p.id),
                            })
                          }
                        >
                          {t("page.finance.void_payment", "冲正")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted" style={{ margin: "0.25rem 0" }}>{t("page.finance.no_payments", "暂无付款记录")}</p>
          )}
        </div>
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
          {openInv && ["issued", "partially_paid"].includes(openInv.status) ? (
            <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => openInv && invTransition(openInv.id, "void")}>
              {t("page.finance.void", "作废")}
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
        {openClaim && (openClaim.status === "open" || openClaim.status === "negotiating") ? (
          <label>
            {t("page.finance.settlement_amount", "Settlement amount")}
            <input type="number" step="any" value={settleAmount} onChange={(e) => setSettleAmount(e.target.value)} />
          </label>
        ) : null}
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
          {openClaim?.status === "settled" ? (
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => openClaim && claimToInvoice(openClaim.id)}>
              {t("page.finance.to_invoice", "生成发票")}
            </button>
          ) : null}
        </div>
      </RecordModal>
      <RecordModal
        open={Boolean(ltExport)}
        title={t("page.finance.lt_statement", "Laytime 计算书")}
        onClose={() => setLtExport(null)}
        canEdit={false}
        canDelete={false}
      >
        {ltExport ? (
          <>
            <p className="muted">
              {ltExport.format || "LAYTIME_STATEMENT_v1"} · {ltExport.status}
              {ltExport.terms ? ` · ${ltExport.terms}` : ""}
            </p>
            <div className="desk-results" style={{ marginBottom: "0.75rem" }}>
              <div className="kv-box">
                <span>{t("page.finance.allowed_hours", "Allowed hours")}</span>
                <strong>{fmt(ltExport.allowed_hours ?? null)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.finance.used_hours", "Used hours")}</span>
                <strong>{fmt(ltExport.used_hours ?? null)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.finance.excluded_hours", "Excluded hours")}</span>
                <strong>{fmt(ltExport.excluded_hours ?? null)}</strong>
              </div>
              <div className="kv-box">
                <span>{t("page.finance.balance_hours", "Balance hours")}</span>
                <strong>{fmt(ltExport.balance_hours ?? null)}</strong>
              </div>
              <div className="kv-box">
                <span>{ltExport.result_type || "—"}</span>
                <strong>
                  {fmt(ltExport.amount ?? null)} {ltExport.currency || ""}
                </strong>
              </div>
            </div>
            {(ltExport.events?.length ? [{ port: undefined, events: ltExport.events }] : ltExport.ports || []).map((grp, gi) =>
              grp.events?.length ? (
                <div key={gi} className="desk-section">
                  {grp.port ? <h3>{grp.port}</h3> : null}
                  <table className="table">
                    <thead>
                      <tr>
                        <th>{t("page.finance.ev_start", "Start")}</th>
                        <th>{t("page.finance.ev_end", "End")}</th>
                        <th>{t("common.type", "类型")}</th>
                        <th>{t("page.finance.gross_hours", "Gross h")}</th>
                        <th>{t("page.finance.term_excluded", "剔除 h")}</th>
                        <th>{t("page.finance.counted", "计入 h")}</th>
                        <th>{t("page.finance.cumulative", "累计 h")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {grp.events.map((ev, i) => (
                        <tr key={i}>
                          <td>{ev.start?.replace("T", " ").slice(0, 16)}</td>
                          <td>{ev.end?.replace("T", " ").slice(0, 16)}</td>
                          <td>
                            {ev.kind}
                            {ev.caller_excluded ? ` (${t("page.finance.ev_excluded", "剔除")})` : ""}
                          </td>
                          <td>{fmt(ev.gross_hours)}</td>
                          <td>{fmt(ev.term_excluded_hours)}</td>
                          <td>{fmt(ev.counted_hours)}</td>
                          <td>{fmt(ev.cumulative_hours)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null,
            )}
          </>
        ) : null}
      </RecordModal>
      <ConfirmDialog
        open={Boolean(confirm)}
        title={t("common.confirm", "确认操作")}
        message={confirm?.message || ""}
        danger={confirm?.danger}
        onConfirm={() => {
          const fn = confirm?.action;
          setConfirm(null);
          fn?.();
        }}
        onCancel={() => setConfirm(null)}
      />
    </AppShell>
  );
}
