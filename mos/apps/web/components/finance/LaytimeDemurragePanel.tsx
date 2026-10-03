"use client";

// Laytime 深度面板：预付滞期（on-account）/ 根因分摊 / 延误跟踪 / 时效任务。
// 自取数 + 自建表单，挂载在 laytime 单据详情页（B10）。

import { FormEvent, useCallback, useEffect, useState } from "react";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Estimated = {
  demurrage_amount: number;
  on_account_total: number;
  on_account_pending: number;
  outstanding: number;
  overpaid: number;
  currency: string;
  result_type?: string;
};

type OnAccountRow = {
  id: string;
  amount: number;
  currency: string;
  payment_date: string | null;
  status: string;
  notes: string | null;
};

type RootCauseRow = {
  id: string;
  cause: string;
  delay_hours: number;
  responsible_party: string;
  share_pct?: number;
  allocated_amount?: number;
};

type DelayRow = {
  id: string;
  delay_type: string;
  start_at: string | null;
  end_at: string | null;
  duration_hours: number | null;
  excluded_from_laytime: boolean;
  cost_impact: number | null;
};

type Envelope<T> = { items: T[]; total: number } & Record<string, unknown>;

function fmt(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function LaytimeDemurragePanel({ laytimeId }: { laytimeId: string }) {
  const { t } = useI18n();
  const [est, setEst] = useState<Estimated | null>(null);
  const [onAcc, setOnAcc] = useState<Envelope<OnAccountRow> | null>(null);
  const [causes, setCauses] = useState<Envelope<RootCauseRow> | null>(null);
  const [delays, setDelays] = useState<Envelope<DelayRow> | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const [oaAmount, setOaAmount] = useState("");
  const [oaStatus, setOaStatus] = useState("paid");
  const [rcCause, setRcCause] = useState("port_congestion");
  const [rcHours, setRcHours] = useState("");
  const [rcParty, setRcParty] = useState("charterer");
  const [dType, setDType] = useState("port_congestion");
  const [dStart, setDStart] = useState("");
  const [dEnd, setDEnd] = useState("");
  const [dExcluded, setDExcluded] = useState(false);

  const load = useCallback(async () => {
    const [e, oa, rc, dl] = await Promise.all([
      apiGet(`/api/v1/laytimes/${laytimeId}/estimated-demurrage`),
      apiGet(`/api/v1/laytimes/${laytimeId}/demurrage-on-account`),
      apiGet(`/api/v1/laytimes/${laytimeId}/root-causes`),
      apiGet(`/api/v1/laytimes/${laytimeId}/delays`),
    ]);
    setEst(e);
    setOnAcc(oa);
    setCauses(rc);
    setDelays(dl);
  }, [laytimeId]);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await action();
      setMsg(t("common.created", "Created"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addOnAccount(e: FormEvent) {
    e.preventDefault();
    await run(() =>
      apiPost(`/api/v1/laytimes/${laytimeId}/demurrage-on-account`, {
        amount: Number(oaAmount),
        status: oaStatus,
      })
    );
    setOaAmount("");
  }

  async function addRootCause(e: FormEvent) {
    e.preventDefault();
    await run(() =>
      apiPost(`/api/v1/laytimes/${laytimeId}/root-causes`, {
        cause: rcCause,
        delay_hours: Number(rcHours),
        responsible_party: rcParty,
      })
    );
    setRcHours("");
  }

  async function addDelay(e: FormEvent) {
    e.preventDefault();
    await run(() =>
      apiPost(`/api/v1/laytimes/${laytimeId}/delays`, {
        delay_type: dType,
        start_at: dStart,
        end_at: dEnd || null,
        excluded_from_laytime: dExcluded,
      })
    );
    setDStart("");
    setDEnd("");
  }

  async function makeTimeBarTask() {
    await run(() => apiPost(`/api/v1/laytimes/${laytimeId}/time-bar-task`, {}));
  }

  const oaCols: ColumnDef<OnAccountRow>[] = [
    { key: "amount", title: t("common.amount", "Amount"), align: "right", render: (v) => fmt(v as number) },
    { key: "currency", title: t("page.finance.currency", "Currency") },
    { key: "payment_date", title: t("common.date", "Date") },
    { key: "status", title: t("common.status", "Status") },
    { key: "notes", title: t("common.notes", "Notes") },
  ];

  const rcCols: ColumnDef<RootCauseRow>[] = [
    { key: "cause", title: t("page.finance.lt_cause", "Cause") },
    { key: "responsible_party", title: t("page.finance.lt_party", "Responsible") },
    { key: "delay_hours", title: t("page.finance.lt_hours", "Hours"), align: "right", render: (v) => fmt(v as number) },
    { key: "share_pct", title: t("page.finance.lt_share", "Share %"), align: "right", render: (v) => fmt(v as number) },
    { key: "allocated_amount", title: t("page.finance.lt_allocated", "Allocated"), align: "right", render: (v) => fmt(v as number) },
  ];

  const dCols: ColumnDef<DelayRow>[] = [
    { key: "delay_type", title: t("common.type", "Type") },
    {
      key: "start_at",
      title: t("common.start", "Start"),
      render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
    },
    {
      key: "end_at",
      title: t("common.end", "End"),
      render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
    },
    { key: "duration_hours", title: t("page.finance.lt_hours", "Hours"), align: "right", render: (v) => fmt(v as number) },
    {
      key: "excluded_from_laytime",
      title: t("page.finance.ev_excluded", "Excluded"),
      render: (v) => (v ? t("common.yes", "Yes") : t("common.no", "No")),
    },
    { key: "cost_impact", title: t("page.finance.lt_cost", "Cost impact"), align: "right", render: (v) => fmt(v as number) },
  ];

  return (
    <>
      <div className="panel no-print">
        <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_demurrage_depth", "Demurrage / on-account / root causes")}</h3>
        {msg ? <p className="flash">{msg}</p> : null}
        {err ? <p className="flash-err">{err}</p> : null}
        <div className="desk-results">
          <div className="kv-box">
            <span>{t("page.finance.lt_demurrage", "Demurrage")}</span>
            <strong>{fmt(est?.demurrage_amount)}</strong>
          </div>
          <div className="kv-box">
            <span>{t("page.finance.lt_on_account", "On account (paid)")}</span>
            <strong>{fmt(est?.on_account_total)}</strong>
          </div>
          <div className="kv-box">
            <span>{t("page.finance.lt_on_account_pending", "On account (pending)")}</span>
            <strong>{fmt(est?.on_account_pending)}</strong>
          </div>
          <div className="kv-box">
            <span>{t("page.finance.lt_outstanding", "Outstanding")}</span>
            <strong>{fmt(est?.outstanding)}</strong>
          </div>
        </div>
        <div className="desk-toolbar" style={{ margin: "0.5rem 0 0" }}>
          <button className="btn btn-sm" type="button" disabled={busy} onClick={makeTimeBarTask}>
            {t("page.finance.lt_timebar_task", "Generate time bar task")}
          </button>
        </div>
      </div>

      <div className="panel no-print">
        <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_on_account", "Demurrage on account")}</h3>
        <form className="form-grid" onSubmit={addOnAccount}>
          <label>
            {t("common.amount", "Amount")}
            <input type="number" step="any" value={oaAmount} onChange={(e) => setOaAmount(e.target.value)} required />
          </label>
          <label>
            {t("common.status", "Status")}
            <select value={oaStatus} onChange={(e) => setOaStatus(e.target.value)}>
              <option value="pending">pending</option>
              <option value="paid">paid</option>
              <option value="applied">applied</option>
            </select>
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("common.create", "Create")}
          </button>
        </form>
        <DataTable data={onAcc?.items || []} columns={oaCols} emptyText={t("common.empty", "No records")} />
      </div>

      <div className="panel no-print">
        <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_root_causes", "Root causes (allocated)")}</h3>
        <form className="form-grid" onSubmit={addRootCause}>
          <label>
            {t("page.finance.lt_cause", "Cause")}
            <select value={rcCause} onChange={(e) => setRcCause(e.target.value)}>
              <option value="port_congestion">port_congestion</option>
              <option value="weather">weather</option>
              <option value="cargo_delay">cargo_delay</option>
              <option value="documentation">documentation</option>
              <option value="other">other</option>
            </select>
          </label>
          <label>
            {t("page.finance.lt_hours", "Hours")}
            <input type="number" step="any" value={rcHours} onChange={(e) => setRcHours(e.target.value)} required />
          </label>
          <label>
            {t("page.finance.lt_party", "Responsible")}
            <select value={rcParty} onChange={(e) => setRcParty(e.target.value)}>
              <option value="owner">owner</option>
              <option value="charterer">charterer</option>
              <option value="port">port</option>
              <option value="agent">agent</option>
              <option value="other">other</option>
            </select>
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("common.create", "Create")}
          </button>
        </form>
        <DataTable data={causes?.items || []} columns={rcCols} emptyText={t("common.empty", "No records")} />
        {causes ? (
          <p className="page-sub">
            {t("page.finance.lt_allocated_total", "Allocated total")}: {fmt(causes.allocated_total as number)} ·{" "}
            {t("page.finance.lt_hours", "Hours")}: {fmt(causes.total_delay_hours as number)}
          </p>
        ) : null}
      </div>

      <div className="panel no-print">
        <h3 style={{ marginTop: 0 }}>{t("page.finance.lt_delays", "Delay tracking")}</h3>
        <form className="form-grid" onSubmit={addDelay}>
          <label>
            {t("common.type", "Type")}
            <select value={dType} onChange={(e) => setDType(e.target.value)}>
              <option value="weather">weather</option>
              <option value="port_congestion">port_congestion</option>
              <option value="cargo">cargo</option>
              <option value="documentation">documentation</option>
              <option value="breakdown">breakdown</option>
              <option value="other">other</option>
            </select>
          </label>
          <label>
            {t("common.start", "Start")}
            <input type="datetime-local" value={dStart} onChange={(e) => setDStart(e.target.value)} required />
          </label>
          <label>
            {t("common.end", "End")}
            <input type="datetime-local" value={dEnd} onChange={(e) => setDEnd(e.target.value)} />
          </label>
          <label>
            {t("page.finance.ev_excluded", "Excluded from laytime")}
            <input type="checkbox" checked={dExcluded} onChange={(e) => setDExcluded(e.target.checked)} />
          </label>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("common.create", "Create")}
          </button>
        </form>
        <DataTable data={delays?.items || []} columns={dCols} emptyText={t("common.empty", "No records")} />
        {delays?.summary ? (
          <p className="page-sub">
            {t("page.finance.lt_total_hours", "Total")}: {fmt((delays.summary as Record<string, number>).total_delay_hours)} ·{" "}
            {t("page.finance.ev_excluded", "Excluded")}: {fmt((delays.summary as Record<string, number>).excluded_hours)} ·{" "}
            {t("page.finance.lt_counted", "Counted")}: {fmt((delays.summary as Record<string, number>).counted_hours)}
          </p>
        ) : null}
      </div>
    </>
  );
}
