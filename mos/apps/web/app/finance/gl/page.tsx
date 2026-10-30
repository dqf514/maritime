"use client";

// GL 管理工作台：科目表 / 日记账 / 试算平衡 / 资产负债表 / 利润表 / 现金流量表。
// 报表数字统一走 fmt 千分位格式化；日记账支持草稿→过账→冲销。

import { msgOf } from "@/lib/errors";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RowActions } from "@/components/RowActions";
import { SavedViews } from "@/components/SavedViews";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { Tabs, type TabItem } from "@/components/Tabs";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";
import { useListQuery } from "@/lib/useListQuery";
import { formatDateTimeShort } from "@/lib/datetime";

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
  updated_at?: string | null;
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
  updated_at?: string | null;
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

/** P1-24：保留原始数值文本 —— 0 保留为 "0"，非法值原样带出（不静默变 0） */
function rawAmount(v: string | number | undefined | null): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  return Number.isFinite(n) ? String(n) : String(v);
}

/** 日记账的可读标识（用于确认文案指名对象） */
function journalLabel(j: Journal): string {
  return `${j.period}/${j.journal_type}${j.description ? ` · ${j.description}` : ""}`;
}

function GlPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery } = useListQuery();
  const tab: Tab = TAB_IDS.includes(query.tab ?? "") ? (query.tab as Tab) : "accounts";
  const setTab = (id: Tab) => setQuery({ tab: id === "accounts" ? null : id });

  const [period, setPeriodState] = useState(typeof query.period === "string" && query.period ? query.period : currentPeriod());
  const setPeriod = useCallback(
    (p: string) => {
      setPeriodState(p);
      setQuery({ period: p || null }, { resetPage: true });
    },
    [setQuery],
  );
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountsErr, setAccountsErr] = useState<string | null>(null);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [journals, setJournals] = useState<Journal[]>([]);
  const [journalsErr, setJournalsErr] = useState<string | null>(null);
  const [journalsLoading, setJournalsLoading] = useState(true);
  const [stmt, setStmt] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // P1-8：破坏性操作统一走 ConfirmDialog（pending 存待执行函数）
  const [pending, setPending] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  // 科目编辑弹窗
  const [accOpen, setAccOpen] = useState(false);
  const [accEdit, setAccEdit] = useState<Account | null>(null);
  const [accForm, setAccForm] = useState({ account_code: "", account_name: "", account_type: "asset", parent_code: "", currency: "USD" });

  // 日记账弹窗（两行：借/贷）；jrEdit 非空时为编辑草稿
  const [jrOpen, setJrOpen] = useState(false);
  const [jrEdit, setJrEdit] = useState<Journal | null>(null);
  const [jrForm, setJrForm] = useState({
    period: currentPeriod(),
    journal_type: "non_voyage",
    description: "",
    debit_account: "",
    debit: "",
    credit_account: "",
    credit: "",
  });

  // R4 行右键菜单（与工具栏同源 handler）
  const accCtx = useContextMenu<Account>();
  const jrCtx = useContextMenu<Journal>();

  const loadAccounts = useCallback(async () => {
    setAccountsLoading(true);
    setAccountsErr(null);
    try {
      const pg = await apiGet("/api/v1/gl/accounts");
      setAccounts(Array.isArray(pg) ? pg : pg.items || []);
    } catch (ex) {
      // P1-4：主列表取数失败必须可见，不能静默变成空表
      setAccountsErr(msgOf(ex));
    } finally {
      setAccountsLoading(false);
    }
  }, []);

  const loadJournals = useCallback(async () => {
    setJournalsLoading(true);
    setJournalsErr(null);
    try {
      const pg = await apiGet(`/api/v1/gl/journals?period=${encodeURIComponent(period)}`);
      setJournals(Array.isArray(pg) ? pg : pg.items || []);
    } catch (ex) {
      setJournalsErr(msgOf(ex));
    } finally {
      setJournalsLoading(false);
    }
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
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, [tab, period]);

  useEffect(() => {
    if (tab === "accounts") void loadAccounts();
    else if (tab === "journals") void loadJournals();
    else void loadStatement();
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
      toast.error(msgOf(ex));
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
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  const openJournal = useCallback((jr: Journal | null) => {
    setJrEdit(jr);
    if (jr) {
      const entries = jr.entries || [];
      const debitLine = entries.find((e) => Number(e.debit) > 0) || entries[0];
      const creditLine = entries.find((e) => Number(e.credit) > 0) || entries[1] || entries[0];
      setJrForm({
        period: jr.period,
        journal_type: jr.journal_type,
        description: jr.description || "",
        debit_account: debitLine?.account_code || debitLine?.account || "",
        debit: debitLine ? rawAmount(debitLine.debit) : "",
        credit_account: creditLine?.account_code || creditLine?.account || "",
        credit: creditLine ? rawAmount(creditLine.credit) : "",
      });
    } else {
      setJrForm({
        period: currentPeriod(),
        journal_type: "non_voyage",
        description: "",
        debit_account: "",
        debit: "",
        credit_account: "",
        credit: "",
      });
    }
    setJrOpen(true);
  }, []);

  async function saveJournal() {
    // P1-24：非法数值不得被静默转成 0（0 本身合法）
    const debitRaw = jrForm.debit.trim();
    const creditRaw = jrForm.credit.trim();
    const debit = Number(debitRaw);
    const credit = Number(creditRaw);
    if (!debitRaw || !creditRaw || !Number.isFinite(debit) || !Number.isFinite(credit)) {
      toast.error(t("page.gl.journal_bad_amount", "Debit and credit must be numbers"));
      return;
    }
    setBusy(true);
    try {
      const body = {
        period: jrForm.period,
        journal_type: jrForm.journal_type,
        description: jrForm.description || null,
        entries: [
          { account_code: jrForm.debit_account, debit, credit: 0 },
          { account_code: jrForm.credit_account, debit: 0, credit },
        ],
      };
      if (jrEdit) {
        await apiPatch(`/api/v1/gl/journals/${jrEdit.id}`, body);
        toast.success(t("common.saved", "Saved"));
      } else {
        await apiPost("/api/v1/gl/journals", body);
        toast.success(t("page.gl.journal_created", "Journal created (draft)"));
      }
      setJrOpen(false);
      setJrEdit(null);
      await loadJournals();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  const deleteJournal = useCallback(
    async (id: string) => {
      try {
        await apiDelete(`/api/v1/gl/journals/${id}`);
        toast.success(t("page.gl.journal_deleted", "Journal deleted"));
        setJrOpen(false);
        setJrEdit(null);
        await loadJournals();
      } catch (ex) {
        toast.error(msgOf(ex));
      }
    },
    [loadJournals, t, toast],
  );

  async function postJournal(id: string) {
    try {
      await apiPost(`/api/v1/gl/journals/${id}/post`);
      toast.success(t("page.gl.posted", "Journal posted"));
      await loadJournals();
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function reverseJournal(id: string) {
    try {
      await apiPost(`/api/v1/gl/journals/${id}/reverse`);
      toast.success(t("page.gl.reversed", "Journal reversed"));
      await loadJournals();
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  // 行内编辑：值未变化不发请求，避免 blur→reload 打断输入
  async function onJournalCellSave(rowId: string, colKey: string, value: unknown, row: Journal) {
    if (row.status !== "draft") {
      toast.error(t("page.gl.journal_locked", "Only draft journals can be edited or deleted"));
      return;
    }
    const src = row as unknown as Record<string, unknown>;
    if ((src[colKey] ?? "") === (value ?? "")) return;
    try {
      await apiPatch(`/api/v1/gl/journals/${rowId}`, { [colKey]: value === "" ? null : value });
      toast.success(t("common.saved", "Saved"));
      await loadJournals();
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  // —— DataGrid 列 ——
  const accountCols = useMemo<ColumnDef<Account>[]>(
    () => [
      { key: "account_code", title: t("page.gl.code", "Code"), sticky: true },
      {
        key: "account_name",
        title: t("common.name", "Name"),
        render: (v, r) => t(`coa.${r.account_code}`, String(v ?? "")),
      },
      {
        key: "account_type",
        title: t("common.type", "Type"),
        render: (v) => t(`coa.type.${v}`, String(v ?? "")),
      },
      { key: "parent_code", title: t("page.gl.parent", "Parent"), render: (v) => (v ? String(v) : "—") },
      { key: "currency", title: t("common.currency", "Currency") },
      { key: "is_active", title: t("common.active", "Active"), render: (v) => (v ? "✓" : "—") },
      {
        key: "updated_at",
        title: t("list.last_modified", "Last modified"),
        width: 135,
        value: (r) => r.updated_at ?? null,
        render: (v) => formatDateTimeShort(v as string | null),
      },
    ],
    [t],
  );

  const journalCols = useMemo<ColumnDef<Journal>[]>(
    () => [
      { key: "period", title: t("page.gl.period", "Period"), editor: { type: "text" } },
      {
        key: "journal_type",
        title: t("common.type", "Type"),
        editor: { type: "select", options: JOURNAL_TYPES.map((jt) => ({ value: jt, label: t(`gl.journal_type.${jt}`, jt) })) },
      },
      { key: "description", title: t("common.description", "Description"), render: (v) => (v ? String(v) : "—"), editor: { type: "text" } },
      {
        key: "total_debit",
        title: t("page.gl.debit", "Debit"),
        align: "right",
        agg: "sum",
        value: (r) => r.total_debit,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "total_credit",
        title: t("page.gl.credit", "Credit"),
        align: "right",
        agg: "sum",
        value: (r) => r.total_credit,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      { key: "status", title: t("common.status", "Status") },
      {
        key: "updated_at",
        title: t("list.last_modified", "Last modified"),
        width: 135,
        value: (r) => r.updated_at ?? null,
        render: (v) => formatDateTimeShort(v as string | null),
      },
      {
        key: "_actions",
        title: "",
        width: 44,
        align: "center",
        render: (_v, r) => {
          const locked = r.status !== "draft";
          return (
            <span title={locked ? t("page.gl.journal_locked", "Only draft journals can be edited or deleted") : undefined}>
              {locked ? <span className="muted">—</span> : null}
              <RowActions
                canEdit={!locked}
                canDelete={!locked}
                onEdit={() => openJournal(r)}
                onDelete={() => deleteJournal(r.id)}
                label={journalLabel(r)}
              />
            </span>
          );
        },
      },
    ],
    [t, openJournal, deleteJournal],
  );

  const stmtCols = useMemo<ColumnDef<StmtRow>[]>(
    () => [
      { key: "account_code", title: t("page.gl.code", "Code"), sticky: true },
      {
        key: "account_name",
        title: t("common.name", "Name"),
        render: (v, r) => t(`coa.${r.account_code}`, String(v ?? "")),
      },
      {
        key: "balance",
        title: t("page.gl.balance", "Balance"),
        align: "right",
        agg: "sum",
        value: (r) => r.balance,
        render: (v) => <Num v={v as number} digits={2} />,
      },
    ],
    [t],
  );

  const trialCols = useMemo<ColumnDef<StmtRow>[]>(
    () => [
      { key: "account_code", title: t("page.gl.code", "Code"), sticky: true },
      {
        key: "account_name",
        title: t("common.name", "Name"),
        render: (v, r) => t(`coa.${r.account_code}`, String(v ?? "")),
      },
      {
        key: "debit",
        title: t("page.gl.debit", "Debit"),
        align: "right",
        agg: "sum",
        value: (r) => r.debit ?? 0,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "credit",
        title: t("page.gl.credit", "Credit"),
        align: "right",
        agg: "sum",
        value: (r) => r.credit ?? 0,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "balance",
        title: t("page.gl.balance", "Balance"),
        align: "right",
        value: (r) => r.balance,
        render: (v) => <Num v={v as number} digits={2} />,
      },
    ],
    [t],
  );

  function copyId(id: string) {
    void navigator.clipboard?.writeText(id).then(() => {
      toast.success(t("common.copied", "Copied"));
    });
  }

  function exportAccounts(rows: Account[]) {
    downloadCsv(
      "gl-accounts",
      ["id", "account_code", "account_name", "account_type", "parent_code", "currency", "is_active"],
      rows.map((r) => [r.id, r.account_code, r.account_name, r.account_type, r.parent_code ?? "", r.currency, r.is_active ? "1" : "0"]),
    );
  }

  function exportJournals(rows: Journal[]) {
    downloadCsv(
      "gl-journals",
      ["id", "period", "journal_type", "description", "total_debit", "total_credit", "status"],
      rows.map((r) => [r.id, r.period, r.journal_type, r.description ?? "", r.total_debit, r.total_credit, r.status]),
    );
  }

  const accountMenuItems = (row: Account): ContextMenuItem[] => [
    { key: "open", label: t("common.open", "Open"), onClick: () => openAccount(row) },
    { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => copyId(row.id) },
    {
      key: "export",
      label: t("common.export_csv", "Export CSV"),
      onClick: () => exportAccounts([row]),
    },
  ];

  const journalMenuItems = (row: Journal): ContextMenuItem[] => [
    ...(row.status === "draft"
      ? [
          {
            key: "edit",
            label: t("common.edit", "Edit"),
            onClick: () => openJournal(row),
          } as ContextMenuItem,
        ]
      : []),
    { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => copyId(row.id) },
    {
      key: "export",
      label: t("common.export_csv", "Export CSV"),
      onClick: () => exportJournals([row]),
    },
    { key: "div", divider: true, label: "" },
    ...(row.status === "draft"
      ? [
          {
            key: "post",
            label: t("page.gl.post", "Post"),
            onClick: () => postJournal(row.id),
          } as ContextMenuItem,
          {
            key: "delete",
            label: t("common.delete", "Delete"),
            // P1-8：与行内 ✕ 按钮行为统一 —— 都必须二次确认
            onClick: () =>
              setPending({
                message: t("page.gl.delete_journal_confirm", "删除日记账 {label}？记录将移入回收站，可恢复。", {
                  label: journalLabel(row),
                }),
                danger: true,
                action: () => void deleteJournal(row.id),
              }),
          } as ContextMenuItem,
        ]
      : []),
    ...(row.status === "posted"
      ? [
          {
            key: "reverse",
            label: t("page.gl.reverse", "Reverse"),
            // P1-8：冲销已过账凭证不可撤销 —— 二次确认并指名对象
            onClick: () =>
              setPending({
                message: t("page.gl.reverse_journal_confirm", "冲销已过账日记账 {label}？将生成等额反向分录，原凭证不可撤销。", {
                  label: journalLabel(row),
                }),
                danger: true,
                action: () => void reverseJournal(row.id),
              }),
          } as ContextMenuItem,
        ]
      : []),
  ];

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

  const tabs: TabItem[] = [
    { key: "accounts", label: t("page.gl.tab_accounts", "Chart of Accounts") },
    { key: "journals", label: t("page.gl.tab_journals", "Journal Entries") },
    { key: "trial", label: t("page.gl.tab_trial", "Trial Balance") },
    { key: "balance", label: t("page.gl.tab_balance", "Balance Sheet") },
    { key: "income", label: t("page.gl.tab_income", "Income Statement") },
    { key: "cashflow", label: t("page.gl.tab_cashflow", "Cashflow") },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.finance", "Finance"), href: "/finance" },
          { label: t("page.gl.title", "GL management") },
        ]}
        title={t("page.gl.title", "GL management")}
        subtitle={t("page.gl.sub", "Chart of accounts, journals, trial balance and financial statements.")}
        actions={<SavedViews storageKey="finance_gl" onApply={(q) => router.replace(`/finance/gl${q}`)} />}
      />

      <Tabs items={tabs} value={tab} onChange={(k) => setTab(k as Tab)} variant="line" />

      {tab === "accounts" ? (
        <div className="panel">
          <Toolbar>
            <button className="btn btn-primary btn-sm" type="button" onClick={() => openAccount(null)}>
              {t("page.gl.new_account", "New account")}
            </button>
          </Toolbar>
          <StateView
            loading={accountsLoading}
            error={accountsErr ?? undefined}
            empty={!accountsLoading && !accountsErr && !accounts.length}
            emptyText={t("common.empty", "No records")}
            onRetry={() => void loadAccounts()}
          >
            <DataGrid<Account>
              columns={accountCols}
              data={accounts}
              rowKey={(r) => r.id}
              onRowClick={(r) => openAccount(r)}
              onRowContextMenu={(row, _i, e) => accCtx.open(row)(e)}
              storageKey="gl.accounts"
              emptyText={t("common.empty", "No records")}
            />
          </StateView>
        </div>
      ) : null}

      {tab === "journals" ? (
        <div className="panel">
          <Toolbar
            right={
              <label>
                {t("page.gl.period", "Period")}
                <input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="YYYY-MM" style={{ width: 110 }} />
              </label>
            }
          >
            <button className="btn btn-primary btn-sm" type="button" onClick={() => openJournal(null)}>
              {t("page.gl.new_journal", "New journal")}
            </button>
            <StatusLegend statuses={["draft", "posted", "reversed"]} />
          </Toolbar>
          <StateView
            loading={journalsLoading}
            error={journalsErr ?? undefined}
            empty={!journalsLoading && !journalsErr && !journals.length}
            emptyText={t("common.empty", "No records")}
            onRetry={() => void loadJournals()}
          >
            <DataGrid<Journal>
              columns={journalCols}
              data={journals}
              rowKey={(r) => r.id}
              editable
              onCellSave={onJournalCellSave}
              onRowContextMenu={(row, _i, e) => jrCtx.open(row)(e)}
              storageKey="gl.journals"
              emptyText={t("common.empty", "No records")}
            />
          </StateView>
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
                  <button
                    key={j.id}
                    className="btn btn-sm btn-ghost"
                    type="button"
                    onClick={() =>
                      setPending({
                        message: t("page.gl.reverse_journal_confirm", "冲销已过账日记账 {label}？将生成等额反向分录，原凭证不可撤销。", {
                          label: journalLabel(j),
                        }),
                        danger: true,
                        action: () => void reverseJournal(j.id),
                      })
                    }
                  >
                    {t("page.gl.reverse", "Reverse")} {j.period}/{j.journal_type}
                  </button>
                ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {["trial", "balance", "income", "cashflow"].includes(tab) ? (
        <div className="panel">
          <Toolbar
            right={
              <label>
                {t("page.gl.period", "Period")}
                <input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="YYYY-MM" style={{ width: 110 }} />
              </label>
            }
          >
            <button className="btn btn-primary btn-sm" type="button" onClick={() => loadStatement()}>
              {t("common.refresh", "Refresh")}
            </button>
          </Toolbar>
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

      <ContextMenu controller={accCtx} items={accountMenuItems} />
      <ContextMenu controller={jrCtx} items={journalMenuItems} />

      <ConfirmDialog
        open={Boolean(pending)}
        title={t("common.confirm", "确认操作")}
        message={pending?.message || ""}
        danger={pending?.danger}
        onConfirm={() => {
          const fn = pending?.action;
          setPending(null);
          fn?.();
        }}
        onCancel={() => setPending(null)}
      />

      <RecordModal
        open={accOpen}
        title={accEdit ? t("page.gl.edit_account", "Edit account") : t("page.gl.new_account", "New account")}
        onClose={() => setAccOpen(false)}
        onSave={saveAccount}
        canDelete={false}
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
                  {t(`coa.type.${at}`, at)}
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
        {accEdit ? (
          // P1-8：删除科目走指名对象的二次确认（RecordModal 内置文案无法指名对象）
          <div className="desk-toolbar">
            <button
              className="btn btn-danger btn-sm"
              type="button"
              disabled={busy}
              onClick={() =>
                setPending({
                  message: t("page.gl.delete_account_confirm", "删除科目 {code} {name}？已有凭证的科目不可删除。", {
                    code: accForm.account_code,
                    name: accForm.account_name,
                  }),
                  danger: true,
                  action: () => void deleteAccount(),
                })
              }
            >
              {t("common.delete", "删除")}
            </button>
          </div>
        ) : null}
      </RecordModal>

      <RecordModal
        open={jrOpen}
        title={jrEdit ? t("page.gl.edit_journal", "Edit journal") : t("page.gl.new_journal", "New journal")}
        onClose={() => {
          setJrOpen(false);
          setJrEdit(null);
        }}
        onSave={saveJournal}
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
                  {t(`gl.journal_type.${jt}`, jt)}
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
        {jrEdit && jrEdit.status === "draft" ? (
          // P1-8：删除日记账走指名对象的二次确认
          <div className="desk-toolbar">
            <button
              className="btn btn-danger btn-sm"
              type="button"
              disabled={busy}
              onClick={() =>
                setPending({
                  message: t("page.gl.delete_journal_confirm", "删除日记账 {label}？记录将移入回收站，可恢复。", {
                    label: journalLabel(jrEdit),
                  }),
                  danger: true,
                  action: () => void deleteJournal(jrEdit.id),
                })
              }
            >
              {t("common.delete", "删除")}
            </button>
          </div>
        ) : null}
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
