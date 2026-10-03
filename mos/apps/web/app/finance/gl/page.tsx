"use client";

// GL 管理工作台：科目表 / 日记账 / 试算平衡 / 资产负债表 / 利润表 / 现金流量表。
// 报表数字统一走 fmt 千分位格式化；日记账支持草稿→过账→冲销。

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";

type Tab = "accounts" | "journals" | "trial" | "balance" | "income" | "cashflow";
const TAB_IDS: readonly string[] = ["accounts", "journals", "trial", "balance", "income", "cashflow"];

type Account = {
  id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  parent_code: string | null;
  currency: string;
  is_active: boolean;
};

type Journal = {
  id: string;
  period: string;
  journal_type: string;
  description: string | null;
  total_debit: number;
  total_credit: number;
  status: string;
  posted_at: string | null;
  entries: Array<{ account_code?: string; account?: string; debit: string | number; credit: string | number; reference?: string; description?: string }>;
};

type StmtRow = { account_code: string; account_name: string; balance: number; debit?: number; credit?: number; account_type?: string | null };

const ACCOUNT_TYPES = ["asset", "liability", "equity", "revenue", "expense"];
const JOURNAL_TYPES = ["voyage", "accrual", "non_voyage", "ic"];

function currentPeriod(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const money = (v: number | null | undefined) => (v == null ? "—" : fmt(v));

function GlPage() {
  const { t } = useI18n();
  const toast = useToast();
  const { query, setQuery } = useListQuery();
  const tab: Tab = TAB_IDS.includes(query.tab ?? "") ? (query.tab as Tab) : "accounts";
  const setTab = (id: Tab) => setQuery({ tab: id === "accounts" ? null : id });

  const [period, setPeriod] = useState(currentPeriod());
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [journals, setJournals] = useState<Journal[]>([]);
  const [stmt, setStmt] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // 科目编辑弹窗
  const [accOpen, setAccOpen] = useState(false);
  const [accEdit, setAccEdit] = useState<Account | null>(null);
  const [accForm, setAccForm] = useState({ account_code: "", account_name: "", account_type: "asset", parent_code: "", currency: "USD" });

  // 日记账弹窗（两行：借/贷）
  const [jrOpen, setJrOpen] = useState(false);
  const [jrForm, setJrForm] = useState({
    period: currentPeriod(),
    journal_type: "non_voyage",
    description: "",
    debit_account: "",
    debit: "",
    credit_account: "",
    credit: "",
  });

  const loadAccounts = useCallback(async () => {
    const pg = await apiGet("/api/v1/gl/accounts");
    setAccounts(Array.isArray(pg) ? pg : pg.items || []);
  }, []);

  const loadJournals = useCallback(async () => {
    const pg = await apiGet(`/api/v1/gl/journals?period=${encodeURIComponent(period)}`);
    setJournals(Array.isArray(pg) ? pg : pg.items || []);
  }, [period]);

  const loadStatement = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const path =
        tab === "balance"
          ? `/api/v1/gl/balance-sheet?period=${encodeURIComponent(period)}`
          : tab === "income"
            ? `/api/v1/gl/income-statement?period=${encodeURIComponent(period)}`
            : tab === "cashflow"
              ? `/api/v1/gl/cashflow?period=${encodeURIComponent(period)}`
              : `/api/v1/gl/trial-balance?period=${encodeURIComponent(period)}`;
      setStmt(await apiGet(path));
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }, [tab, period]);

  useEffect(() => {
    if (tab === "accounts") loadAccounts().catch(() => undefined);
    else if (tab === "journals") loadJournals().catch(() => undefined);
    else loadStatement().catch(() => undefined);
  }, [tab, loadAccounts, loadJournals, loadStatement]);

  function openAccount(acc: Account | null) {
    setAccEdit(acc);
    setAccForm(
      acc
        ? { account_code: acc.account_code, account_name: acc.account_name, account_type: acc.account_type, parent_code: acc.parent_code || "", currency: acc.currency }
        : { account_code: "", account_name: "", account_type: "asset", parent_code: "", currency: "USD" },
    );
    setAccOpen(true);
  }

  async function saveAccount() {
    setBusy(true);
    try {
      const body = {
        account_name: accForm.account_name,
        account_type: accForm.account_type,
        parent_code: accForm.parent_code || null,
        currency: accForm.currency,
      };
      if (accEdit) {
        await apiPatch(`/api/v1/gl/accounts/${accEdit.id}`, body);
      } else {
        await apiPost("/api/v1/gl/accounts", { ...body, account_code: accForm.account_code });
      }
      toast.success(t("page.gl.saved", "Account saved"));
      setAccOpen(false);
      await loadAccounts();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function deleteAccount() {
    if (!accEdit) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/gl/accounts/${accEdit.id}`);
      toast.success(t("page.gl.deleted", "Account deleted"));
      setAccOpen(false);
      await loadAccounts();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function createJournal() {
    setBusy(true);
    try {
      await apiPost("/api/v1/gl/journals", {
        period: jrForm.period,
        journal_type: jrForm.journal_type,
        description: jrForm.description || null,
        entries: [
          { account_code: jrForm.debit_account, debit: Number(jrForm.debit) || 0, credit: 0 },
          { account_code: jrForm.credit_account, debit: 0, credit: Number(jrForm.credit) || 0 },
        ],
      });
      toast.success(t("page.gl.journal_created", "Journal created (draft)"));
      setJrOpen(false);
      await loadJournals();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function postJournal(id: string) {
    try {
      await apiPost(`/api/v1/gl/journals/${id}/post`);
      toast.success(t("page.gl.posted", "Journal posted"));
      await loadJournals();
    } catch (ex) {
      toast.error(String(ex));
    }
  }

  async function reverseJournal(id: string) {
    try {
      await apiPost(`/api/v1/gl/journals/${id}/reverse`);
      toast.success(t("page.gl.reversed", "Journal reversed"));
      await loadJournals();
    } catch (ex) {
      toast.error(String(ex));
    }
  }

  // —— DataGrid 列 ——
  const accountCols = useMemo<ColumnDef<Account>[]>(
    () => [
      { key: "account_code", title: t("page.gl.code", "Code"), sticky: true },
      { key: "account_name", title: t("common.name", "Name") },
      { key: "account_type", title: t("common.type", "Type") },
      { key: "parent_code", title: t("page.gl.parent", "Parent"), render: (v) => (v ? String(v) : "—") },
      { key: "currency", title: t("common.currency", "Currency") },
      { key: "is_active", title: t("common.active", "Active"), render: (v) => (v ? "✓" : "—") },
    ],
    [t],
  );

  const journalCols = useMemo<ColumnDef<Journal>[]>(
    () => [
      { key: "period", title: t("page.gl.period", "Period") },
      { key: "journal_type", title: t("common.type", "Type") },
      { key: "description", title: t("common.description", "Description"), render: (v) => (v ? String(v) : "—") },
      { key: "total_debit", title: t("page.gl.debit", "Debit"), align: "right", agg: "sum", render: (v) => money(v as number) },
      { key: "total_credit", title: t("page.gl.credit", "Credit"), align: "right", agg: "sum", render: (v) => money(v as number) },
      { key: "status", title: t("common.status", "Status") },
    ],
    [t],
  );

  const stmtCols = useMemo<ColumnDef<StmtRow>[]>(
    () => [
      { key: "account_code", title: t("page.gl.code", "Code"), sticky: true },
      { key: "account_name", title: t("common.name", "Name") },
      {
        key: "balance",
        title: t("page.gl.balance", "Balance"),
        align: "right",
        agg: "sum",
        render: (v) => money(v as number),
      },
    ],
    [t],
  );

  const trialCols = useMemo<ColumnDef<StmtRow>[]>(
    () => [
      { key: "account_code", title: t("page.gl.code", "Code"), sticky: true },
      { key: "account_name", title: t("common.name", "Name") },
      { key: "debit", title: t("page.gl.debit", "Debit"), align: "right", agg: "sum", render: (v) => money(v as number) },
      { key: "credit", title: t("page.gl.credit", "Credit"), align: "right", agg: "sum", render: (v) => money(v as number) },
      { key: "balance", title: t("page.gl.balance", "Balance"), align: "right", render: (v) => money(v as number) },
    ],
    [t],
  );

  // 报表数据整形
  const stmtRows = useMemo<StmtRow[]>(() => {
    if (!stmt) return [];
    if (tab === "balance") {
      const bs = stmt as { assets: StmtRow[]; liabilities: StmtRow[]; equity: StmtRow[] };
      return [...(bs.assets || []), ...(bs.liabilities || []), ...(bs.equity || [])];
    }
    if (tab === "income") {
      const is = stmt as { revenue: StmtRow[]; expenses: StmtRow[] };
      return [...(is.revenue || []), ...(is.expenses || [])];
    }
    if (tab === "cashflow") {
      const cf = stmt as { operating: number; investing: number; financing: number; net_change_in_cash: number; cash_beginning: number; cash_ending: number };
      return [
        { account_code: "CF.OPERATING", account_name: t("page.gl.cf_operating", "Operating activities"), balance: cf.operating },
        { account_code: "CF.INVESTING", account_name: t("page.gl.cf_investing", "Investing activities"), balance: cf.investing },
        { account_code: "CF.FINANCING", account_name: t("page.gl.cf_financing", "Financing activities"), balance: cf.financing },
        { account_code: "CF.NET", account_name: t("page.gl.cf_net", "Net change in cash"), balance: cf.net_change_in_cash },
        { account_code: "CF.BEGIN", account_name: t("page.gl.cf_begin", "Cash beginning"), balance: cf.cash_beginning },
        { account_code: "CF.END", account_name: t("page.gl.cf_end", "Cash ending"), balance: cf.cash_ending },
      ];
    }
    return (stmt as { rows: StmtRow[] }).rows || [];
  }, [stmt, tab, t]);

  const stmtSummary = useMemo(() => {
    if (!stmt) return null;
    if (tab === "balance") {
      const bs = stmt as { total_assets: number; total_liabilities: number; total_equity: number; net_income: number; balanced: boolean };
      return [
        `${t("page.gl.total_assets", "Total assets")}: ${money(bs.total_assets)}`,
        `${t("page.gl.total_liabilities", "Total liabilities")}: ${money(bs.total_liabilities)}`,
        `${t("page.gl.total_equity", "Total equity")}: ${money(bs.total_equity)}`,
        `${t("page.gl.net_income", "Net income")}: ${money(bs.net_income)}`,
        bs.balanced ? t("page.gl.balanced", "A = L + E ✓") : t("page.gl.unbalanced", "Out of balance!"),
      ];
    }
    if (tab === "income") {
      const is = stmt as { total_revenue: number; total_expenses: number; net_income: number };
      return [
        `${t("page.gl.total_revenue", "Revenue")}: ${money(is.total_revenue)}`,
        `${t("page.gl.total_expenses", "Expenses")}: ${money(is.total_expenses)}`,
        `${t("page.gl.net_income", "Net income")}: ${money(is.net_income)}`,
      ];
    }
    if (tab === "trial") {
      const tb = stmt as { total_debit: number; total_credit: number; balanced: boolean };
      return [
        `${t("page.gl.debit", "Debit")}: ${money(tb.total_debit)}`,
        `${t("page.gl.credit", "Credit")}: ${money(tb.total_credit)}`,
        tb.balanced ? t("page.gl.balanced", "A = L + E ✓") : t("page.gl.unbalanced", "Out of balance!"),
      ];
    }
    return null;
  }, [stmt, tab, t]);

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "accounts", label: t("page.gl.tab_accounts", "Chart of Accounts") },
    { id: "journals", label: t("page.gl.tab_journals", "Journal Entries") },
    { id: "trial", label: t("page.gl.tab_trial", "Trial Balance") },
    { id: "balance", label: t("page.gl.tab_balance", "Balance Sheet") },
    { id: "income", label: t("page.gl.tab_income", "Income Statement") },
    { id: "cashflow", label: t("page.gl.tab_cashflow", "Cashflow") },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("page.gl.title", "GL management")}
        subtitle={t("page.gl.sub", "Chart of accounts, journals, trial balance and financial statements.")}
      />

      <div className="desk-tabs">
        {tabs.map((tb) => (
          <button key={tb.id} type="button" className={`desk-tab${tab === tb.id ? " active" : ""}`} onClick={() => setTab(tb.id)}>
            {tb.label}
          </button>
        ))}
      </div>

      {tab === "accounts" ? (
        <div className="panel">
          <div className="desk-toolbar" style={{ marginTop: 0 }}>
            <button className="btn btn-primary btn-sm" type="button" onClick={() => openAccount(null)}>
              {t("page.gl.new_account", "New account")}
            </button>
          </div>
          <DataGrid<Account>
            columns={accountCols}
            data={accounts}
            rowKey={(r) => r.id}
            onRowClick={(r) => openAccount(r)}
            storageKey="gl.accounts"
            emptyText={t("common.empty", "No records")}
          />
        </div>
      ) : null}

      {tab === "journals" ? (
        <div className="panel">
          <div className="desk-toolbar" style={{ marginTop: 0 }}>
            <label>
              {t("page.gl.period", "Period")}
              <input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="YYYY-MM" style={{ width: 110 }} />
            </label>
            <button className="btn btn-primary btn-sm" type="button" onClick={() => setJrOpen(true)}>
              {t("page.gl.new_journal", "New journal")}
            </button>
          </div>
          <DataGrid<Journal>
            columns={journalCols}
            data={journals}
            rowKey={(r) => r.id}
            storageKey="gl.journals"
            emptyText={t("common.empty", "No records")}
          />
          {journals.length ? (
            <div className="desk-toolbar">
              {journals
                .filter((j) => j.status === "draft")
                .slice(0, 5)
                .map((j) => (
                  <button key={j.id} className="btn btn-sm" type="button" onClick={() => postJournal(j.id)}>
                    {t("page.gl.post", "Post")} {j.period}/{j.journal_type}
                  </button>
                ))}
              {journals
                .filter((j) => j.status === "posted")
                .slice(0, 5)
                .map((j) => (
                  <button key={j.id} className="btn btn-sm btn-ghost" type="button" onClick={() => reverseJournal(j.id)}>
                    {t("page.gl.reverse", "Reverse")} {j.period}/{j.journal_type}
                  </button>
                ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {["trial", "balance", "income", "cashflow"].includes(tab) ? (
        <div className="panel">
          <div className="desk-toolbar" style={{ marginTop: 0 }}>
            <label>
              {t("page.gl.period", "Period")}
              <input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="YYYY-MM" style={{ width: 110 }} />
            </label>
            <button className="btn btn-primary btn-sm" type="button" onClick={() => loadStatement()}>
              {t("common.refresh", "Refresh")}
            </button>
          </div>
          {stmtSummary ? (
            <div className="desk-toolbar" style={{ justifyContent: "flex-start", gap: "var(--gap-lg)" }}>
              {stmtSummary.map((s, i) => (
                <span key={i} className="muted">
                  {s}
                </span>
              ))}
            </div>
          ) : null}
          <StateView loading={loading} error={err ?? undefined} empty={!stmtRows.length} onRetry={() => loadStatement()}>
            <DataGrid<StmtRow>
              columns={tab === "trial" ? trialCols : stmtCols}
              data={stmtRows}
              rowKey={(r) => r.account_code}
              storageKey={`gl.${tab}`}
              emptyText={t("common.empty", "No records")}
            />
          </StateView>
        </div>
      ) : null}

      <RecordModal
        open={accOpen}
        title={accEdit ? t("page.gl.edit_account", "Edit account") : t("page.gl.new_account", "New account")}
        onClose={() => setAccOpen(false)}
        onSave={saveAccount}
        onDelete={accEdit ? deleteAccount : undefined}
        canDelete={!!accEdit}
        saving={busy}
      >
        <div className="form-grid">
          <label>
            {t("page.gl.code", "Code")}
            <input value={accForm.account_code} disabled={!!accEdit} onChange={(e) => setAccForm({ ...accForm, account_code: e.target.value })} />
          </label>
          <label>
            {t("common.name", "Name")}
            <input value={accForm.account_name} onChange={(e) => setAccForm({ ...accForm, account_name: e.target.value })} />
          </label>
          <label>
            {t("common.type", "Type")}
            <select value={accForm.account_type} onChange={(e) => setAccForm({ ...accForm, account_type: e.target.value })}>
              {ACCOUNT_TYPES.map((at) => (
                <option key={at} value={at}>
                  {at}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.gl.parent", "Parent")}
            <input value={accForm.parent_code} onChange={(e) => setAccForm({ ...accForm, parent_code: e.target.value })} />
          </label>
          <label>
            {t("common.currency", "Currency")}
            <input value={accForm.currency} onChange={(e) => setAccForm({ ...accForm, currency: e.target.value })} />
          </label>
        </div>
      </RecordModal>

      <RecordModal
        open={jrOpen}
        title={t("page.gl.new_journal", "New journal")}
        onClose={() => setJrOpen(false)}
        onSave={createJournal}
        canDelete={false}
        saving={busy}
      >
        <div className="form-grid">
          <label>
            {t("page.gl.period", "Period")}
            <input value={jrForm.period} onChange={(e) => setJrForm({ ...jrForm, period: e.target.value })} placeholder="YYYY-MM" />
          </label>
          <label>
            {t("common.type", "Type")}
            <select value={jrForm.journal_type} onChange={(e) => setJrForm({ ...jrForm, journal_type: e.target.value })}>
              {JOURNAL_TYPES.map((jt) => (
                <option key={jt} value={jt}>
                  {jt}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("common.description", "Description")}
            <input value={jrForm.description} onChange={(e) => setJrForm({ ...jrForm, description: e.target.value })} />
          </label>
          <label>
            {t("page.gl.debit_account", "Debit account")}
            <input value={jrForm.debit_account} onChange={(e) => setJrForm({ ...jrForm, debit_account: e.target.value })} list="gl-accounts" />
          </label>
          <label>
            {t("page.gl.debit", "Debit")}
            <input type="number" step="any" value={jrForm.debit} onChange={(e) => setJrForm({ ...jrForm, debit: e.target.value })} />
          </label>
          <label>
            {t("page.gl.credit_account", "Credit account")}
            <input value={jrForm.credit_account} onChange={(e) => setJrForm({ ...jrForm, credit_account: e.target.value })} list="gl-accounts" />
          </label>
          <label>
            {t("page.gl.credit", "Credit")}
            <input type="number" step="any" value={jrForm.credit} onChange={(e) => setJrForm({ ...jrForm, credit: e.target.value })} />
          </label>
        </div>
        <datalist id="gl-accounts">
          {accounts.map((a) => (
            <option key={a.id} value={a.account_code}>
              {a.account_name}
            </option>
          ))}
        </datalist>
      </RecordModal>
    </AppShell>
  );
}

// Next 16: useSearchParams（useListQuery）须位于 Suspense 边界内
export default function Page() {
  return (
    <Suspense fallback={null}>
      <GlPage />
    </Suspense>
  );
}
