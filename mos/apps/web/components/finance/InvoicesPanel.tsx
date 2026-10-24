"use client";

// 3.6：Invoices 面板（自取数 + 创建/hire 排程 + 分页表 + 批量导出）。

import { msgOf, handled } from "@/lib/errors";
import { FormEvent, useCallback, useEffect, useRef, useState, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { CurrencyField } from "@/components/CurrencyField";
import { DataGrid } from "@/components/grid";
import type { ColumnDef as GridColumnDef } from "@/components/grid";
import { PartyPicker } from "@/components/DataPicker";
import { DateInput } from "@/components/DateInput";
import { ExportButton } from "@/components/ExportButton";
import { Num } from "@/components/Num";
import { StateView } from "@/components/StateView";
import { useTodoAdd } from "@/components/TodoQuickAdd";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiList, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { readFormDefaults, writeFormDefaults } from "@/lib/formDefaults";
import { useI18n } from "@/lib/i18n";
import { baseAmountPreview } from "@/lib/numbers";
import { useListQuery } from "@/lib/useListQuery";

const INVOICE_TYPES = ["freight", "hire", "demurrage", "bunker", "port_disbursement", "credit_note", "other"];

/** 数字输入解析：空串 → null；非法输入 → NaN（调用方必须报错，禁止静默转 0）。 */
function numOrNull(raw: string): number | null {
  const s = raw.trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : NaN;
}

type RefItem = { id: string; name: string };
type VoyageRef = { id: string; voyage_no: string };
type CharterRef = { id: string; charter_no: string };
type Invoice = {
  id: string;
  invoice_no: string;
  status: string;
  amount: number;
  paid_amount?: number;
  invoice_type?: string;
  base_amount?: number | null;
  updated_at?: string | null;
};

export function InvoicesPanel() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const { query, setQuery, page, limit } = useListQuery();

  const [rows, setRows] = useState<Invoice[]>([]);
  const [total, setTotal] = useState(0);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [voyages, setVoyages] = useState<VoyageRef[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [charters, setCharters] = useState<CharterRef[]>([]);
  const [busy, setBusy] = useState(false);
  // P1-4：主列表取数失败 → 三态错误（绝不能静默变成「No records」）
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  // 参考数据（航次/交易对手/租约）失败：不拖垮主列表，但必须显式提示
  const [refErr, setRefErr] = useState<string | null>(null);
  // 首次成功加载后，后续刷新不再整表 spinner（避免卸载 DataGrid 丢失排序/列布局）
  const loadedOnce = useRef(false);

  const [invType, setInvType] = useState(() => readFormDefaults("finance.invoice", { invType: "freight" }).invType);
  const [invAmount, setInvAmount] = useState("100000");
  const [invFx, setInvFx] = useState(() => readFormDefaults("finance.invoice", { invFx: "" }).invFx);
  const [invVoyage, setInvVoyage] = useState("");
  const [invParty, setInvParty] = useState("");
  const [hsCharter, setHsCharter] = useState("");
  const [hsStart, setHsStart] = useState("");
  const [hsEnd, setHsEnd] = useState("");
  const invCtx = useContextMenu<Invoice>();
  const todo = useTodoAdd();

  // 参考数据：逐个容错，任一失败只记 refErr（面板顶部提示），不影响主列表三态
  const loadRefs = useCallback(async () => {
    const [v, p, ch] = await Promise.allSettled([
      apiGet("/api/v1/voyages/options") as Promise<VoyageRef[]>,
      apiGet("/api/v1/masterdata/counterparties") as Promise<RefItem[]>,
      apiGet("/api/v1/charters") as Promise<CharterRef[]>,
    ]);
    const problems: string[] = [];
    if (v.status === "fulfilled") setVoyages(v.value);
    else {
      setVoyages([]);
      problems.push(msgOf(v.reason));
    }
    if (p.status === "fulfilled") setParties(p.value);
    else {
      setParties([]);
      problems.push(msgOf(p.reason));
    }
    if (ch.status === "fulfilled") setCharters(ch.value);
    else {
      setCharters([]);
      problems.push(msgOf(ch.reason));
    }
    setRefErr(problems.length ? problems.join(" · ") : null);
  }, []);

  const loadList = useCallback(async () => {
    // 只有首次加载才显示整表 spinner；后续刷新（增删改后）保持表格挂载，
    // 免得排序/列布局被卸载重置。
    if (!loadedOnce.current) setLoading(true);
    setErr(null);
    try {
      const pg = await apiList<Invoice>("/api/v1/invoices", { limit, offset: (page - 1) * limit });
      setRows(pg.items);
      setTotal(pg.total);
      loadedOnce.current = true;
      // 翻页/刷新后剪掉已不在当前页的选择，避免「导出选中」导出空集
      const ids = new Set(pg.items.map((r) => r.id));
      setSel((prev) => new Set([...prev].filter((k) => ids.has(k))));
      if (!pg.items.length && pg.total > 0 && page > 1) setQuery({ page: Math.ceil(pg.total / limit) });
    } catch (ex) {
      setRows([]);
      setTotal(0);
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, [limit, page, setQuery]);

  useEffect(() => {
    loadRefs().catch(handled);
  }, [loadRefs]);
  useEffect(() => {
    loadList().catch(handled);
  }, [loadList]);

  async function create(e: FormEvent) {
    e.preventDefault();
    // P1-24：非法数字必须报错，不能静默转 0（0 也是合法值，用 Number.isFinite 判定）
    const amount = numOrNull(invAmount);
    if (amount === null || Number.isNaN(amount) || amount < 0) {
      toast.error(t("page.finance.bad_amount", "金额必须是有效数字"));
      return;
    }
    let fxRate: number | undefined;
    if (invFx.trim() !== "") {
      const fx = numOrNull(invFx);
      if (fx === null || Number.isNaN(fx) || fx <= 0) {
        toast.error(t("page.finance.bad_fx", "汇率必须是有效的正数"));
        return;
      }
      fxRate = fx;
    }
    setBusy(true);
    try {
      const inv = await apiPost("/api/v1/invoices", {
        invoice_type: invType,
        amount,
        voyage_id: invVoyage || null,
        counterparty_id: invParty || null,
        fx_rate: fxRate,
      });
      toast.success(t("page.finance.created_inv", "Invoice {no} created", { no: inv.invoice_no }));
      writeFormDefaults("finance.invoice", { invType, invFx });
      await loadList();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function createHireSchedule(e: FormEvent) {
    e.preventDefault();
    if (!hsCharter || !hsStart || !hsEnd) {
      toast.error(t("page.finance.hs_need", "请选择租约并填写期间"));
      return;
    }
    setBusy(true);
    try {
      const inv = await apiPost("/api/v1/invoices/hire-schedule", {
        charter_id: hsCharter,
        period_start: hsStart,
        period_end: hsEnd,
      });
      toast.success(t("page.finance.created_inv", "Invoice {no} created", { no: inv.invoice_no }));
      await loadList();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  const cols = useMemo<GridColumnDef<Invoice>[]>(
    () => [
      {
        key: "invoice_no",
        title: t("page.finance.no", "编号"),
        // 编号做成真链接：行内点击之外还能右键新标签页打开 / 复制链接（行 onClick 不可发现）。
        render: (v, r) => (
          <Link href={`/finance/invoices/${r.id}`} className="row-link">
            {String(v ?? "")}
          </Link>
        ),
      },
      { key: "status", title: t("common.status", "Status") },
      {
        key: "amount",
        title: t("common.amount", "Amount"),
        align: "right",
        value: (r) => r.amount,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "base_amount",
        title: t("page.finance.base_amount", "Base"),
        align: "right",
        value: (r) => r.base_amount ?? null,
        render: (v) => (v != null ? <Num v={v as number} digits={2} /> : "—"),
      },
      {
        key: "paid_amount",
        title: t("page.finance.paid_col", "已付"),
        align: "right",
        value: (r) => r.paid_amount ?? 0,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "updated_at",
        title: t("list.last_modified", "Last modified"),
        width: 135,
        value: (r) => r.updated_at ?? null,
        render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
      },
    ],
    [t],
  );

  function exportRows(rows: Invoice[]) {
    downloadCsv(
      "invoices-selected",
      ["invoice_no", "status", "type", "amount", "base_amount", "paid_amount"],
      rows.map((r) => [r.invoice_no, r.status, r.invoice_type || "", r.amount, r.base_amount ?? "", r.paid_amount ?? ""]),
    );
  }

  const invMenuItems = (row: Invoice): ContextMenuItem[] => [
    { key: "open", label: t("common.open", "Open"), onClick: () => router.push(`/finance/invoices/${row.id}`) },
    { key: "divider", divider: true },
    todo.menuItem({ entityType: "invoice", entityId: row.id, title: row.invoice_no }),
    { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(row.id) },
    {
      key: "export",
      label: t("page.finance.export_selected", "Export selected CSV"),
      onClick: () => exportRows(sel.has(row.id) ? rows.filter((r) => sel.has(r.id)) : [row]),
    },
  ];

  return (
    <>
      {refErr ? (
        <p className="flash-err">
          {t("page.finance.ref_load_failed", "Some reference lists could not be loaded")}: {refErr}
        </p>
      ) : null}
      <form className="panel" onSubmit={create}>
        <h3 style={{ marginTop: 0 }}>{t("page.finance.new_invoice", "New invoice")}</h3>
        <div className="form-grid">
          <label>
            {t("common.type", "Type")}
            <select value={invType} onChange={(e) => setInvType(e.target.value)}>
              {INVOICE_TYPES.map((it) => (
                <option key={it} value={it}>
                  {t(`invoice.type.${it}`, it)}
                </option>
              ))}
            </select>
          </label>
          <CurrencyField
            amount={invAmount}
            currency="USD"
            baseAmount={baseAmountPreview(invAmount, invFx)}
            fxRate={invFx === "" ? 1 : invFx}
            onAmountChange={setInvAmount}
            onFxRateChange={setInvFx}
          />
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
            <PartyPicker value={invParty} onChange={setInvParty} />
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
            {t("page.finance.hs_action", "Generate hire invoice")}
          </button>
        </div>
      </form>

      <div className="panel">
        <div className="desk-toolbar" style={{ marginTop: 0, justifyContent: "flex-end" }}>
          <button
            className="btn btn-sm btn-ghost"
            type="button"
            disabled={!sel.size}
            onClick={() => exportRows(rows.filter((r) => sel.has(r.id)))}
          >
            {t("page.finance.export_selected", "Export selected CSV")} {sel.size ? `(${sel.size})` : ""}
          </button>
          <ExportButton entity="invoices" />
          <button
            className="btn btn-sm btn-ghost"
            type="button"
            disabled={page <= 1}
            onClick={() => setQuery({ page: page > 2 ? page - 1 : null }, { resetPage: false })}
            aria-label={t("common.prev_page", "Previous page")}
          >
            ←
          </button>
          <span className="muted">
            {page} / {Math.max(1, Math.ceil(total / limit))}
          </span>
          <button
            className="btn btn-sm btn-ghost"
            type="button"
            disabled={page * limit >= total}
            onClick={() => setQuery({ page: page + 1 }, { resetPage: false })}
            aria-label={t("common.next_page", "Next page")}
          >
            →
          </button>
        </div>
        <StateView
          loading={loading}
          error={err ?? undefined}
          empty={!rows.length}
          emptyText={t("common.empty", "No records")}
          onRetry={() => loadList()}
        >
          <DataGrid<Invoice>
            data={rows}
            columns={cols}
            rowKey={(r) => r.id}
            storageKey="finance.invoices"
            emptyText={t("common.empty", "No records")}
            selectable
            selectedKeys={sel}
            onSelectedKeysChange={(keys) => setSel(new Set(keys))}
            onRowClick={(r) => router.push(`/finance/invoices/${r.id}`)}
            onRowContextMenu={(row, _i, e) => invCtx.open(row)(e)}
          />
        </StateView>
      </div>
      <ContextMenu controller={invCtx} items={invMenuItems} />
      {todo.element}
    </>
  );
}
