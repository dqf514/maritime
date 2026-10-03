"use client";

// 付款批次工作台：批次列表 + 新建批次（勾选应付发票）+ 审批/冲正 + 导出银行 XML。

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { DateInput } from "@/components/DateInput";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { StateView } from "@/components/StateView";
import { useToast } from "@/components/ToastProvider";
import { API_BASE, apiGet, apiPost, readStorage, TOKEN_STORAGE_KEY } from "@/lib/api";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";

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

  // 批次详情
  const [detail, setDetail] = useState<Batch | null>(null);

  const loadBatches = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const pg = await apiGet("/api/v1/payments/batches");
      setRows(Array.isArray(pg) ? pg : pg.items || []);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBatches().catch(() => undefined);
  }, [loadBatches]);

  async function openCreate() {
    try {
      const list = await apiGet("/api/v1/payments/payable-invoices");
      setPayable(Array.isArray(list) ? list : list.items || []);
      setPicked(new Set());
      setCreateOpen(true);
    } catch (ex) {
      toast.error(String(ex));
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
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function openDetail(id: string) {
    try {
      setDetail(await apiGet(`/api/v1/payments/batches/${id}`));
    } catch (ex) {
      toast.error(String(ex));
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
      toast.error(String(ex));
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
      toast.error(String(ex));
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
      toast.error(String(ex));
    }
  }

  const cols = useMemo<ColumnDef<Batch>[]>(
    () => [
      { key: "batch_number", title: t("page.payments.batch_no", "Batch no"), sticky: true },
      { key: "batch_date", title: t("page.payments.batch_date", "Date") },
      { key: "status", title: t("common.status", "Status") },
      { key: "payment_count", title: t("page.payments.count", "Payments"), align: "right", agg: "sum" },
      { key: "total_amount", title: t("common.amount", "Amount"), align: "right", agg: "sum", render: (v) => money(v as number) },
      { key: "currency", title: t("common.currency", "Currency") },
      { key: "bank_charge_mode", title: t("page.payments.charge_mode", "Bank charges"), render: (v) => (v ? String(v) : "—") },
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
      { key: "outstanding", title: t("page.payments.outstanding", "Outstanding"), align: "right", agg: "sum", render: (v) => money(v as number) },
      { key: "currency", title: t("common.currency", "Currency") },
      { key: "due_date", title: t("page.payments.due", "Due"), render: (v) => (v ? String(v) : "—") },
    ],
    [t, picked],
  );

  const paymentCols = useMemo<ColumnDef<PaymentRow>[]>(
    () => [
      { key: "invoice_id", title: t("page.finance.invoice", "Invoice"), render: (v) => String(v).slice(0, 8) },
      { key: "amount", title: t("common.amount", "Amount"), align: "right", agg: "sum", render: (v) => money(v as number) },
      { key: "currency", title: t("common.currency", "Currency") },
      { key: "reference", title: t("common.reference", "Reference"), render: (v) => (v ? String(v) : "—") },
    ],
    [t],
  );

  return (
    <AppShell>
      <PageHeader
        title={t("page.payments.title", "Payment batches")}
        subtitle={t("page.payments.sub", "Batch invoice payments, approve, reverse and export bank XML.")}
        actions={
          <button className="btn btn-primary" type="button" onClick={openCreate}>
            {t("page.payments.new_batch", "New batch")}
          </button>
        }
      />

      <div className="panel">
        <StateView loading={loading} error={err ?? undefined} empty={!rows.length} onRetry={() => loadBatches()}>
          <DataGrid<Batch>
            columns={cols}
            data={rows}
            rowKey={(r) => r.id}
            onRowClick={(r) => openDetail(r.id)}
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
              <option value="shared">shared</option>
              <option value="sender">sender</option>
              <option value="receiver">receiver</option>
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
        title={detail ? `${detail.batch_number} · ${detail.status}` : ""}
        onClose={() => setDetail(null)}
        canEdit={false}
        canDelete={false}
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
              <span>
                {t("page.payments.charge_mode", "Bank charges")}: {detail.bank_charge_mode || "—"}
              </span>
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
                <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => approve(detail.id)}>
                  {t("page.payments.approve", "Approve")}
                </button>
              ) : null}
              {detail.status === "completed" || detail.status === "processing" ? (
                <button className="btn btn-sm btn-ghost" type="button" disabled={busy} onClick={() => reverse(detail.id)}>
                  {t("page.payments.reverse", "Reverse")}
                </button>
              ) : null}
              <button className="btn btn-sm" type="button" onClick={() => exportXml(detail.id)}>
                {t("page.payments.export_xml", "Export XML")}
              </button>
            </div>
          </>
        ) : null}
      </RecordModal>
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
