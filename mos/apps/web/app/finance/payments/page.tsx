"use client";

// 付款批次工作台：批次列表 + 新建批次（勾选应付发票）+ 审批/冲正 + 导出银行 XML。

import { msgOf, handled } from "@/lib/errors";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { DateInput } from "@/components/DateInput";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RowActions } from "@/components/RowActions";
import { SavedViews } from "@/components/SavedViews";
import { StateView } from "@/components/StateView";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { useToast } from "@/components/ToastProvider";
import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, readStorage, TOKEN_STORAGE_KEY } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";
import { parseUtc, formatDateTimeShort } from "@/lib/datetime";
import { useListQuery } from "@/lib/useListQuery";

type Batch = {
  id: string;
  batch_number: string;
  batch_date: string | null;
  status: string;
  total_amount: number;
  currency: string;
  payment_count: number;
  bank_charge_mode: string | null;
  approved_at: string | null;
  updated_at?: string | null;
  payments?: PaymentRow[];
};

type PaymentRow = {
  id: string;
  invoice_id: string;
  amount: number;
  currency: string;
  reference: string | null;
  paid_at: string | null;
};

type PayableInvoice = {
  id: string;
  invoice_no: string;
  invoice_type: string;
  status: string;
  amount: number;
  paid_amount: number;
  outstanding: number;
  currency: string;
  due_date: string | null;
};

const money = (v: number | null | undefined) => (v == null ? "—" : fmt(v));

function PaymentsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  // U1 列表协议：筛选进 URL
  const { query, setQuery } = useListQuery();
  const statusFilter = typeof query.status === "string" ? query.status : "";

  const [rows, setRows] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // 新建批次
  const [createOpen, setCreateOpen] = useState(false);
  const [payable, setPayable] = useState<PayableInvoice[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [batchDate, setBatchDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [chargeMode, setChargeMode] = useState("shared");

  // 批次详情（draft 可改日期/银行费用，或删除）
  const [detail, setDetail] = useState<Batch | null>(null);
  const [detailDate, setDetailDate] = useState("");
  const [detailCharge, setDetailCharge] = useState("shared");

  // R4 行右键菜单
  const batchCtx = useContextMenu<Batch>();

  // P1-8：破坏性操作统一走 ConfirmDialog（pending 存待执行函数）
  const [pending, setPending] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  // B6 列表热键：按 N 新建付款批次
  useListHotkeys(() => {
    void openCreate();
  });

  const filteredRows = useMemo(
    () => (statusFilter ? rows.filter((r) => r.status === statusFilter) : rows),
    [rows, statusFilter],
  );

  const loadBatches = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const pg = await apiGet("/api/v1/payments/batches");
      setRows(Array.isArray(pg) ? pg : pg.items || []);
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBatches().catch(handled);
  }, [loadBatches]);

  async function openCreate() {
    try {
      const list = await apiGet("/api/v1/payments/payable-invoices");
      setPayable(Array.isArray(list) ? list : list.items || []);
      setPicked(new Set());
      setCreateOpen(true);
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  function togglePick(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function createBatch() {
    if (!picked.size) {
      toast.error(t("page.payments.pick_one", "Select at least one invoice"));
      return;
    }
    setBusy(true);
    try {
      await apiPost("/api/v1/payments/batches", {
        invoice_ids: [...picked],
        batch_date: batchDate,
        bank_charge_mode: chargeMode,
      });
      toast.success(t("page.payments.created", "Payment batch created"));
      setCreateOpen(false);
      await loadBatches();
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function openDetail(id: string) {
    try {
      const batch: Batch = await apiGet(`/api/v1/payments/batches/${id}`);
      setDetail(batch);
      setDetailDate(batch.batch_date || "");
      setDetailCharge(batch.bank_charge_mode || "shared");
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function saveDetail() {
    if (!detail) return;
    setBusy(true);
    try {
      await apiPatch(`/api/v1/payments/batches/${detail.id}`, {
        batch_date: detailDate || null,
        bank_charge_mode: detailCharge,
      });
      toast.success(t("common.saved", "Saved"));
      await loadBatches();
      await openDetail(detail.id);
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function approve(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/payments/batches/${id}/approve`);
      toast.success(t("page.payments.approved", "Batch approved"));
      await loadBatches();
      await openDetail(id);
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function reverse(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/payments/batches/${id}/reverse`);
      toast.success(t("page.payments.reversed", "Batch reversed"));
      await loadBatches();
      await openDetail(id);
    } catch (ex) {
      toast.error(msgOf(ex));
    } finally {
      setBusy(false);
    }
  }

  async function exportXml(id: string) {
    try {
      const res = await fetch(`${API_BASE}/api/v1/payments/batches/${id}/export-xml`, {
        credentials: "include",
        headers: { ...(readStorage(TOKEN_STORAGE_KEY) ? { Authorization: `Bearer ${readStorage(TOKEN_STORAGE_KEY)}` } : {}) },
      });
      if (!res.ok) throw new Error(`export-xml failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `payment-batch-${id}.xml`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  // 行内编辑：值未变化不发请求，避免 blur→reload 打断输入
  async function onBatchCellSave(rowId: string, colKey: string, value: unknown, row: Batch) {
    if (row.status !== "draft") {
      toast.error(t("page.payments.batch_locked", "Only draft batches can be edited or deleted"));
      return;
    }
    const src = row as unknown as Record<string, unknown>;
    if (colKey === "batch_date") {
      const prev = row.batch_date;
      const next = value ? String(value) : null;
      const prevT = prev ? parseUtc(prev)?.getTime() ?? null : null;
      const nextT = next ? new Date(next).getTime() : null;
      if (prevT === nextT) return;
      try {
        await apiPatch(`/api/v1/payments/batches/${rowId}`, { batch_date: next });
        toast.success(t("common.saved", "Saved"));
        await loadBatches();
      } catch (ex) {
        toast.error(msgOf(ex));
      }
      return;
    }
    if ((src[colKey] ?? "") === (value ?? "")) return;
    try {
      await apiPatch(`/api/v1/payments/batches/${rowId}`, { [colKey]: value === "" ? null : value });
      toast.success(t("common.saved", "Saved"));
      await loadBatches();
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  async function deleteBatch(id: string) {
    try {
      await apiDelete(`/api/v1/payments/batches/${id}`);
      toast.success(t("page.payments.deleted", "Batch deleted"));
      setDetail(null);
      await loadBatches();
    } catch (ex) {
      toast.error(msgOf(ex));
    }
  }

  // —— P1-8：二次确认入口（确认文案指名批次） ——
  function askApprove(batch: Batch) {
    setPending({
      message: t("page.payments.approve_confirm", "审批付款批次 {no}？审批后批次锁定，不可再编辑。", { no: batch.batch_number }),
      danger: false,
      action: () => void approve(batch.id),
    });
  }

  function askReverse(batch: Batch) {
    setPending({
      message: t("page.payments.reverse_confirm", "反转付款批次 {no}？将生成反向付款，操作不可撤销。", { no: batch.batch_number }),
      danger: true,
      action: () => void reverse(batch.id),
    });
  }

  function askDelete(batch: Batch) {
    setPending({
      message: t("page.payments.delete_confirm", "删除付款批次 {no}？记录将移入回收站，可恢复。", { no: batch.batch_number }),
      danger: true,
      action: () => void deleteBatch(batch.id),
    });
  }

  const cols = useMemo<ColumnDef<Batch>[]>(
    () => [
      { key: "batch_number", title: t("page.payments.batch_no", "Batch no"), sticky: true },
      { key: "batch_date", title: t("page.payments.batch_date", "Date"), editor: { type: "date" } },
      {
        key: "status",
        title: t("common.status", "Status"),
        render: (v) => <span className={`badge badge-${v === "completed" ? "ok" : v === "reversed" ? "warn" : "info"}`}>{t(`status.${v}`, String(v))}</span>,
      },
      {
        key: "payment_count",
        title: t("page.payments.count", "Payments"),
        align: "right",
        agg: "sum",
        value: (r) => r.payment_count,
        render: (v) => <Num v={v as number} digits={0} />,
      },
      {
        key: "total_amount",
        title: t("common.amount", "Amount"),
        align: "right",
        agg: "sum",
        value: (r) => r.total_amount,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      { key: "currency", title: t("common.currency", "Currency") },
      {
        key: "bank_charge_mode",
        title: t("page.payments.charge_mode", "Bank charges"),
        render: (v) => (v ? t(`page.payments.charge_${v}`, String(v)) : "—"),
        editor: {
          type: "select",
          options: ["shared", "sender", "receiver"].map((m) => ({
            value: m,
            label: t(`page.payments.charge_${m}`, m),
          })),
        },
      },
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
            <span title={locked ? t("page.payments.batch_locked", "Only draft batches can be edited or deleted") : undefined}>
              {locked ? <span className="muted">—</span> : null}
              <RowActions
                canEdit={false}
                canDelete={!locked}
                onDelete={() => deleteBatch(r.id)}
                label={r.batch_number}
              />
            </span>
          );
        },
      },
    ],
    [t],
  );

  const payableCols = useMemo<ColumnDef<PayableInvoice>[]>(
    () => [
      {
        key: "pick",
        title: t("page.payments.pick", "Pick"),
        render: (_v, r) => (
          <input
            type="checkbox"
            checked={picked.has(r.id)}
            onChange={() => togglePick(r.id)}
            onClick={(e) => e.stopPropagation()}
          />
        ),
      },
      { key: "invoice_no", title: t("page.finance.no", "No") },
      { key: "invoice_type", title: t("common.type", "Type") },
      {
        key: "outstanding",
        title: t("page.payments.outstanding", "Outstanding"),
        align: "right",
        agg: "sum",
        value: (r) => r.outstanding,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      { key: "currency", title: t("common.currency", "Currency") },
      { key: "due_date", title: t("page.payments.due", "Due"), render: (v) => (v ? String(v) : "—") },
    ],
    [t, picked],
  );

  const paymentCols = useMemo<ColumnDef<PaymentRow>[]>(
    () => [
      { key: "invoice_id", title: t("page.finance.invoice", "Invoice"), render: (v) => String(v).slice(0, 8) },
      {
        key: "amount",
        title: t("common.amount", "Amount"),
        align: "right",
        agg: "sum",
        value: (r) => r.amount,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      { key: "currency", title: t("common.currency", "Currency") },
      { key: "reference", title: t("common.reference", "Reference"), render: (v) => (v ? String(v) : "—") },
    ],
    [t],
  );

  function exportBatches(rows: Batch[]) {
    downloadCsv(
      "payment-batches",
      ["id", "batch_number", "batch_date", "status", "payment_count", "total_amount", "currency", "bank_charge_mode"],
      rows.map((r) => [r.id, r.batch_number, r.batch_date ?? "", r.status, r.payment_count, r.total_amount, r.currency, r.bank_charge_mode ?? ""]),
    );
  }

  const batchMenuItems = (row: Batch): ContextMenuItem[] => [
    { key: "open", label: t("common.open", "Open"), onClick: () => openDetail(row.id) },
    { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(row.id) },
    { key: "export", label: t("page.finance.export_selected", "导出所选 CSV"), onClick: () => exportBatches([row]) },
    { key: "div", divider: true, label: "" },
    ...(row.status === "draft"
      ? [{ key: "approve", label: t("page.payments.approve", "Approve"), onClick: () => askApprove(row) } as ContextMenuItem]
      : []),
    ...(row.status === "completed" || row.status === "processing"
      ? [{ key: "reverse", label: t("page.payments.reverse", "Reverse"), onClick: () => askReverse(row) } as ContextMenuItem]
      : []),
    { key: "xml", label: t("page.payments.export_xml", "Export XML"), onClick: () => exportXml(row.id) },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[
          { label: t("nav.finance", "Finance"), href: "/finance" },
          { label: t("page.payments.title", "Payment batches") },
        ]}
        title={t("page.payments.title", "Payment batches")}
        subtitle={t("page.payments.sub", "Batch invoice payments, approve, reverse and export bank XML.")}
        actions={<SavedViews storageKey="finance_payments" onApply={(q) => router.replace(`/finance/payments${q}`)} />}
      />

      <div className="panel">
        <Toolbar
          filterCount={statusFilter ? 1 : 0}
          onClearFilters={() => setQuery({ status: null }, { resetPage: true })}
          right={
            <select
              className="input input-sm"
              value={statusFilter}
              onChange={(e) => setQuery({ status: e.target.value || null }, { resetPage: true })}
              aria-label={t("common.status", "Status")}
            >
              <option value="">{t("page.payments.all_status", "All statuses")}</option>
              <option value="draft">draft</option>
              <option value="processing">processing</option>
              <option value="completed">completed</option>
              <option value="reversed">reversed</option>
            </select>
          }
        >
          <button className="btn btn-primary btn-sm" type="button" onClick={openCreate}>
            {t("page.payments.new_batch", "New batch")}
          </button>
          <StatusLegend statuses={["draft", "processing", "completed", "reversed"]} />
        </Toolbar>
        <StateView loading={loading} error={err ?? undefined} empty={!filteredRows.length} onRetry={() => loadBatches()}>
          <DataGrid<Batch>
            columns={cols}
            data={filteredRows}
            rowKey={(r) => r.id}
            editable
            onCellSave={onBatchCellSave}
            onRowClick={(r) => openDetail(r.id)}
            onRowContextMenu={(row, _i, e) => batchCtx.open(row)(e)}
            storageKey="payments.batches"
            emptyText={t("common.empty", "No records")}
          />
        </StateView>
      </div>

      <RecordModal
        open={createOpen}
        title={t("page.payments.new_batch", "New batch")}
        onClose={() => setCreateOpen(false)}
        onSave={createBatch}
        canDelete={false}
        saving={busy}
        size="xl"
      >
        <div className="form-grid">
          <label>
            {t("page.payments.batch_date", "Batch date")}
            <DateInput value={batchDate} onChange={setBatchDate} />
          </label>
          <label>
            {t("page.payments.charge_mode", "Bank charges")}
            <select value={chargeMode} onChange={(e) => setChargeMode(e.target.value)}>
              <option value="shared">{t("page.payments.charge_shared", "Shared")}</option>
              <option value="sender">{t("page.payments.charge_sender", "Sender")}</option>
              <option value="receiver">{t("page.payments.charge_receiver", "Receiver")}</option>
            </select>
          </label>
        </div>
        <DataGrid<PayableInvoice>
          columns={payableCols}
          data={payable}
          rowKey={(r) => r.id}
          onRowClick={(r) => togglePick(r.id)}
          storageKey="payments.payable"
          emptyText={t("page.payments.no_payable", "No payable invoices")}
        />
        <p className="muted">
          {t("page.payments.selected", "Selected")}: {picked.size}
        </p>
      </RecordModal>

      <RecordModal
        open={!!detail}
        title={detail ? `${detail.batch_number} · ${t(`status.${detail.status}`, detail.status)}` : ""}
        onClose={() => setDetail(null)}
        onSave={detail && detail.status === "draft" ? saveDetail : undefined}
        canEdit={detail?.status === "draft"}
        canDelete={false}
        saving={busy}
        size="lg"
      >
        {detail ? (
          <>
            <div className="form-grid">
              <span>
                {t("common.amount", "Amount")}: {money(detail.total_amount)} {detail.currency}
              </span>
              <span>
                {t("page.payments.count", "Payments")}: {detail.payment_count}
              </span>
              {detail.status === "draft" ? (
                <>
                  <label>
                    {t("page.payments.batch_date", "Batch date")}
                    <DateInput value={detailDate} onChange={setDetailDate} />
                  </label>
                  <label>
                    {t("page.payments.charge_mode", "Bank charges")}
                    <select value={detailCharge} onChange={(e) => setDetailCharge(e.target.value)}>
                      <option value="shared">{t("page.payments.charge_shared", "Shared")}</option>
                      <option value="sender">{t("page.payments.charge_sender", "Sender")}</option>
                      <option value="receiver">{t("page.payments.charge_receiver", "Receiver")}</option>
                    </select>
                  </label>
                </>
              ) : (
                <span>
                  {t("page.payments.charge_mode", "Bank charges")}:{" "}
                  {detail.bank_charge_mode
                    ? t(`page.payments.charge_${detail.bank_charge_mode}`, detail.bank_charge_mode)
                    : "—"}
                </span>
              )}
            </div>
            <DataGrid<PaymentRow>
              columns={paymentCols}
              data={detail.payments || []}
              rowKey={(r) => r.id}
              storageKey="payments.detail"
              emptyText={t("common.empty", "No records")}
            />
            <div className="desk-toolbar">
              {detail.status === "draft" ? (
                <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => askApprove(detail)}>
                  {t("page.payments.approve", "Approve")}
                </button>
              ) : null}
              {detail.status === "completed" || detail.status === "processing" ? (
                <button className="btn btn-sm btn-ghost" type="button" disabled={busy} onClick={() => askReverse(detail)}>
                  {t("page.payments.reverse", "Reverse")}
                </button>
              ) : null}
              <button className="btn btn-sm" type="button" onClick={() => exportXml(detail.id)}>
                {t("page.payments.export_xml", "Export XML")}
              </button>
              {detail.status === "draft" ? (
                // P1-8：删除批次走指名对象的二次确认
                <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => askDelete(detail)}>
                  {t("common.delete", "删除")}
                </button>
              ) : null}
            </div>
          </>
        ) : null}
      </RecordModal>

      <ContextMenu controller={batchCtx} items={batchMenuItems} />

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
    </AppShell>
  );
}

export default function Page() {
  return (
    <Suspense fallback={null}>
      <PaymentsPage />
    </Suspense>
  );
}
