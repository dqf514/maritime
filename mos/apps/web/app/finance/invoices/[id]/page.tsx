"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { CurrencyField } from "@/components/CurrencyField";
import { DetailHeader, type DetailAction } from "@/components/DetailHeader";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { Num } from "@/components/Num";
import { RevisionsPanel } from "@/components/RevisionsPanel";
import { StatusBadge } from "@/components/StatusBadge";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { useStateActions } from "@/components/useTransitions";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { SkeletonCard } from "@/components/Skeleton";
import { PrintDoc } from "@/components/PrintDoc";

// U2 单据详情页：原 finance 页发票弹窗的路由化版本（可深链/收藏/分享）。
// R4：DetailHeader + 状态机动作过滤 + 镜像徽章 + DRAFT 水印 + Validate + Revisions。

const INVOICE_TYPES = ["freight", "hire", "demurrage", "bunker", "port_disbursement", "credit_note", "other"];

type Invoice = {
  id: string;
  invoice_no: string;
  status: string;
  amount: number;
  tax_amount?: number;
  paid_amount?: number;
  invoice_type?: string;
  currency?: string;
  due_date?: string | null;
  gl_posted?: boolean;
  counterparty_id?: string | null;
  voyage_id?: string | null;
  mirror_of_id?: string | null;
  fx_rate?: number | null;
  base_amount?: number | null;
  issued_at?: string | null;
};
type Payment = { id: string; amount: number; currency: string; reference: string | null; paid_at: string | null; is_void_reversal: boolean };
type CreditNote = { id: string; amount: number; reason?: string | null; created_at?: string | null };
type MirrorChainItem = { id: string; invoice_no: string; is_mirror: boolean; mirror_of_id: string | null };

function fmt(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function InvoiceDetailPage() {
  const { t } = useI18n();
  const toast = useToast();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [inv, setInv] = useState<Invoice | null>(null);
  const [editType, setEditType] = useState("freight");
  const [editAmount, setEditAmount] = useState("");
  const [payAmount, setPayAmount] = useState("");
  const [payRef, setPayRef] = useState("");
  const [cnOpen, setCnOpen] = useState(false);
  const [cnAmount, setCnAmount] = useState("");
  const [cnReason, setCnReason] = useState("");
  const [payments, setPayments] = useState<Payment[]>([]);
  const [creditNotes, setCreditNotes] = useState<CreditNote[]>([]);
  const [mirrorChain, setMirrorChain] = useState<MirrorChainItem[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [confirm, setConfirm] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  const nextStatuses = useStateActions("invoice", inv?.status);

  const refresh = useCallback(async () => {
    const data = await apiGet(`/api/v1/invoices/${id}`);
    setInv(data);
    setEditType(data.invoice_type || "freight");
    setEditAmount(String(data.amount ?? ""));
    const [pays, cns, chain] = await Promise.all([
      apiGet(`/api/v1/invoices/${id}/payments`).catch(() => []),
      apiGet(`/api/v1/invoices/${id}/credit-notes`).catch(() => []),
      apiGet(`/api/v1/invoices/${id}/mirror-chain`).catch(() => ({ items: [] })),
    ]);
    setPayments(Array.isArray(pays) ? pays : []);
    setCreditNotes(Array.isArray(cns) ? cns : []);
    setMirrorChain(Array.isArray(chain?.items) ? chain.items : []);
  }, [id]);

  useEffect(() => {
    refresh()
      .catch((ex) => {
        if (ex?.status === 404) setNotFound(true);
        else setErr(String(ex));
      });
  }, [refresh]);

  async function save() {
    const amount = Number(editAmount);
    if (!editAmount.trim() || Number.isNaN(amount) || amount < 0) {
      setErr(t("page.finance.bad_amount", "金额必须是有效数字"));
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await apiPatch(`/api/v1/invoices/${id}`, { amount, invoice_type: editType });
      toast.success(t("common.saved", "Saved"));
      await refresh();
    } catch (ex: any) {
      setErr(ex?.message || String(ex));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setSaving(true);
    try {
      await apiDelete(`/api/v1/invoices/${id}`);
      window.location.href = "/finance?tab=invoices";
    } catch (ex: any) {
      setErr(ex?.message || String(ex));
      setSaving(false);
    }
  }

  async function transition(target: string) {
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/invoices/${id}/transition?target=${encodeURIComponent(target)}`);
      toast.success(t("page.finance.inv_moved", "Invoice → {target}", { target }));
      await refresh();
    } catch (ex: any) {
      if (ex?.status === 409 && ex?.detail?.code === "CREDIT_NOTE_REQUIRED") {
        const msg = t("page.finance.credit_required", "发票已收款，需先红冲（credit note）后才能作废。");
        setErr(msg);
        toast.error(msg);
      } else {
        const msg = ex?.message || String(ex);
        setErr(msg);
        toast.error(msg);
      }
    } finally {
      setBusy(false);
    }
  }

  async function recordPayment(e: FormEvent) {
    e.preventDefault();
    const amount = Number(payAmount);
    if (!amount) {
      setErr(t("page.finance.need_pay", "Enter payment amount"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const ref = payRef.trim();
      await apiPost(`/api/v1/invoices/${id}/payments?amount=${amount}${ref ? `&reference=${encodeURIComponent(ref)}` : ""}`);
      toast.success(t("page.finance.pay_ok", "Payment posted"));
      setPayAmount("");
      setPayRef("");
      await refresh();
    } catch (ex: any) {
      const msg = ex?.message || String(ex);
      setErr(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  async function voidPayment(paymentId: string) {
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/payments/${paymentId}/void`);
      toast.success(t("page.finance.void_ok", "付款已冲正"));
      await refresh();
    } catch (ex: any) {
      const code = ex?.detail?.code || "";
      let msg: string;
      if (ex?.status === 409 && code === "ALREADY_VOIDED") {
        msg = t("page.finance.void_already", "该付款已冲正，请勿重复操作");
      } else if (ex?.status === 409 && code === "GL_POSTED") {
        msg = t("page.finance.void_gl_posted", "发票已过账（GL posted），禁止冲正其付款");
      } else {
        msg = ex?.message || String(ex);
      }
      setErr(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  async function createCreditNote(e: FormEvent) {
    e.preventDefault();
    const amount = Number(cnAmount);
    if (!cnAmount.trim() || Number.isNaN(amount)) {
      setErr(t("page.finance.bad_amount", "金额必须是有效数字"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/invoices/${id}/credit-note`, { amount, reason: cnReason || null });
      toast.success(t("page.finance.cn_ok", "Credit note posted"));
      setCnAmount("");
      setCnReason("");
      setCnOpen(false);
      await refresh();
    } catch (ex: any) {
      let msg: string;
      if (ex?.status === 409 && ex?.detail?.code === "CREDIT_EXCEEDS_BALANCE") {
        msg = t("page.finance.cn_exceeds", "红冲金额超过发票余额");
      } else {
        msg = ex?.message || String(ex);
      }
      setErr(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  async function glPost() {
    setBusy(true);
    try {
      await apiPost(`/api/v1/invoices/${id}/gl-post`);
      toast.success(t("page.finance.gl_ok", "GL posted"));
      await refresh();
    } catch (ex: any) {
      const msg = ex?.message || String(ex);
      setErr(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  /** R4 前端校验：错误阻断 / 警告可继续 / 全绿通过 */
  function validateInvoice(): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    if (!inv) return issues;
    if (!(Number(inv.amount) > 0)) {
      issues.push({ level: "error", message: t("validate.inv_amount", "Amount must be greater than zero.") });
    }
    if (!inv.counterparty_id) {
      issues.push({ level: "error", message: t("validate.inv_counterparty", "Counterparty is required.") });
    }
    if (!INVOICE_TYPES.includes(inv.invoice_type || "")) {
      issues.push({ level: "error", message: t("validate.inv_type", "Invalid invoice type: {type}", { type: inv.invoice_type || "—" }) });
    }
    if (inv.due_date && inv.issued_at && String(inv.due_date) < String(inv.issued_at).slice(0, 10)) {
      issues.push({ level: "error", message: t("validate.inv_due", "Due date is before the invoice date.") });
    }
    if (inv.currency && inv.currency !== "USD" && (inv.fx_rate === null || inv.fx_rate === undefined)) {
      issues.push({ level: "warn", message: t("validate.inv_fx", "FX rate missing on non-base currency ({cur}).", { cur: inv.currency }) });
    }
    if (!inv.voyage_id) {
      issues.push({ level: "warn", message: t("validate.inv_voyage", "No PDA / linked voyage on this invoice.") });
    }
    return issues;
  }

  function transitionLabel(target: string): string {
    switch (target) {
      case "pending_approval":
        return t("common.submit", "提交");
      case "issued":
        return t("page.finance.issue", "开票");
      case "void":
        return t("page.finance.void", "作废");
      case "draft":
        return t("page.finance.back_to_draft", "Back to draft");
      case "paid":
        return t("page.finance.mark_paid", "Mark paid");
      case "partially_paid":
        return t("page.finance.mark_partial", "Partially paid");
      default:
        return target.replace(/_/g, " ");
    }
  }

  const paymentCols = useMemo<ColumnDef<Payment>[]>(
    () => [
      {
        key: "amount",
        title: t("common.amount", "Amount"),
        align: "right",
        value: (r) => r.amount,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      { key: "currency", title: t("page.finance.currency", "Currency"), width: 90 },
      {
        key: "reference",
        title: t("page.finance.reference", "Reference"),
        value: (r) => r.reference ?? "",
        render: (v) => (v ? String(v) : "—"),
      },
      {
        key: "paid_at",
        title: t("page.finance.paid_at", "时间"),
        value: (r) => r.paid_at ?? "",
        render: (v) => (v ? new Date(String(v)).toLocaleString() : "—"),
      },
      {
        key: "actions",
        title: "",
        width: 90,
        value: () => "",
        render: (_v, p) =>
          p.is_void_reversal ? (
            <span className="badge badge-warn">{t("page.finance.voided_badge", "冲正")}</span>
          ) : (
            <button
              className="btn btn-danger btn-sm"
              type="button"
              disabled={busy}
              onClick={(e) => {
                e.stopPropagation();
                setConfirm({
                  message: t("page.finance.void_confirm", "确认冲正这笔付款？将生成等额反向付款行。"),
                  danger: true,
                  action: () => voidPayment(p.id),
                });
              }}
            >
              {t("page.finance.void_payment", "冲正")}
            </button>
          ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, busy],
  );

  const creditNoteCols = useMemo<ColumnDef<CreditNote>[]>(
    () => [
      {
        key: "amount",
        title: t("common.amount", "Amount"),
        align: "right",
        value: (r) => r.amount,
        render: (v) => <Num v={v as number} digits={2} />,
      },
      {
        key: "reason",
        title: t("page.finance.reason", "Reason"),
        value: (r) => r.reason ?? "",
        render: (v) => (v ? String(v) : "—"),
      },
    ],
    [t],
  );

  if (!inv && !notFound) {
    return (
      <AppShell>
        <SkeletonCard />
      </AppShell>
    );
  }

  if (notFound) {
    return (
      <AppShell>
        <div className="panel">
          <p>{t("common.not_found", "Not found")}</p>
          <Link href="/finance?tab=invoices" className="btn">
            {t("common.back", "返回")}
          </Link>
        </div>
      </AppShell>
    );
  }

  const isMirror = Boolean(inv?.mirror_of_id);
  const mirrorSource = mirrorChain.find((c) => !c.is_mirror && c.id !== inv?.id);
  const mirrorCount = mirrorChain.filter((c) => c.id !== inv?.id).length;
  const showDraftWatermark = inv?.status === "draft" || !inv?.gl_posted;

  const headerActions: DetailAction[] = [
    {
      key: "back",
      label: t("common.back", "返回"),
      onClick: () => router.push("/finance?tab=invoices"),
    },
    {
      key: "print",
      label: t("common.print", "打印 / PDF"),
      onClick: () => window.print(),
      disabled: busy || saving,
    },
    ...nextStatuses.map((target) => ({
      key: `tr-${target}`,
      label: transitionLabel(target),
      variant: (target === "issued" || target === "paid" ? "primary" : target === "void" ? "danger" : "default") as DetailAction["variant"],
      disabled: busy,
      onClick: () => transition(target),
    })),
  ];
  if (inv && ["issued", "partially_paid", "paid"].includes(inv.status)) {
    headerActions.push({
      key: "gl-post",
      label: t("page.finance.gl", "过账"),
      disabled: busy,
      onClick: glPost,
    });
  }
  headerActions.push({
    key: "delete",
    label: t("common.delete", "删除"),
    variant: "danger",
    disabled: saving || busy,
    onClick: () =>
      setConfirm({
        message: t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored."),
        danger: true,
        action: remove,
      }),
  });

  return (
    <AppShell>
      <DetailHeader
        breadcrumb={[
          { label: t("nav.finance", "Finance"), href: "/finance?tab=invoices" },
          { label: inv?.invoice_no ? `#${inv.invoice_no}` : `#${id}` },
        ]}
        title={inv?.invoice_no || "…"}
        status={inv?.status}
        subtitle={t("page.finance.edit_inv", "编辑发票")}
        badges={
          isMirror ? (
            <StatusBadge
              status="mirror"
              tone="muted"
              title={t("invoice.mirror_of", "Mirror of source invoice")}
              label={
                mirrorSource ? (
                  <Link href={`/finance/invoices/${inv?.mirror_of_id}`}>
                    {t("invoice.mirror_badge", "Mirror")} ← #{mirrorSource.invoice_no}
                  </Link>
                ) : (
                  t("invoice.mirror_badge", "Mirror")
                )
              }
            />
          ) : mirrorCount > 0 ? (
            <StatusBadge
              status="mirror_source"
              tone="muted"
              title={t("invoice.mirror_source_hint", "This invoice has intercompany mirrors")}
              label={`${t("invoice.mirror_source_badge", "Mirror source")} (${mirrorCount})`}
            />
          ) : null
        }
        actions={headerActions}
      />

      {err ? <p className="err-text">{err}</p> : null}

      <div className={showDraftWatermark ? "draft-watermark" : undefined}>
      <PrintDoc title={t("page.finance.invoice_doc", "INVOICE")} no={inv?.invoice_no} meta={inv ? `${inv.status} · ${inv.currency || "USD"}` : undefined}>
      <div className="panel">
        <div className="form-grid">
          <label>
            {t("common.type", "类型")}
            <select value={editType} onChange={(e) => setEditType(e.target.value)}>
              {INVOICE_TYPES.map((it) => (
                <option key={it} value={it}>
                  {it}
                </option>
              ))}
            </select>
          </label>
          <CurrencyField
            amount={editAmount}
            currency={inv?.currency || "USD"}
            baseAmount={
              editAmount.trim() && !Number.isNaN(Number(editAmount))
                ? Number(editAmount) * (Number(inv?.fx_rate) || 1)
                : (inv?.base_amount ?? null)
            }
            fxRate={inv?.fx_rate ?? 1}
            onAmountChange={setEditAmount}
          />
          <label>
            {t("page.finance.paid_col", "已付")}
            <input value={fmt(inv?.paid_amount)} disabled />
          </label>
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="button" disabled={saving || busy} onClick={save}>
            {t("common.save", "保存")}
          </button>
          <ValidateButton onValidate={validateInvoice} disabled={!inv} />
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.finance.payments", "付款记录")} ({payments.length})</h3>
        <form className="form-grid" onSubmit={recordPayment}>
          <label>
            {t("page.finance.pay_amount", "Payment amount")}
            <input type="number" step="any" value={payAmount} onChange={(e) => setPayAmount(e.target.value)} />
          </label>
          <label>
            {t("page.finance.reference", "Reference")}
            <input value={payRef} onChange={(e) => setPayRef(e.target.value)} placeholder={t("common.optional", "Optional")} />
          </label>
          <div style={{ display: "flex", alignItems: "end" }}>
            <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>
              {t("page.finance.pay", "收款")}
            </button>
          </div>
        </form>
        {payments.length ? (
          <div style={{ marginTop: "0.5rem" }}>
            <DataGrid<Payment>
              columns={paymentCols}
              data={payments}
              rowKey={(r) => r.id}
              storageKey="invoice_payments_grid"
              showFooter={false}
              emptyText={t("page.finance.no_payments", "暂无付款记录")}
            />
          </div>
        ) : (
          <p className="muted" style={{ margin: "0.25rem 0" }}>{t("page.finance.no_payments", "暂无付款记录")}</p>
        )}
      </div>

      <div className="panel">
        <div className="desk-toolbar" style={{ marginTop: 0 }}>
          <h3 style={{ margin: 0 }}>{t("page.finance.credit_notes", "Credit notes")} ({creditNotes.length})</h3>
          <button className="btn btn-sm" type="button" disabled={busy} onClick={() => setCnOpen((v) => !v)}>
            {t("page.finance.credit_note", "红冲")}
          </button>
        </div>
        {creditNotes.length ? (
          <div style={{ marginTop: "0.5rem" }}>
            <DataGrid<CreditNote>
              columns={creditNoteCols}
              data={creditNotes}
              rowKey={(r) => r.id}
              storageKey="invoice_credit_notes_grid"
              showFooter={false}
              emptyText={t("common.empty", "No records")}
            />
          </div>
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

      </PrintDoc>
      </div>

      {id ? <RevisionsPanel entityType="invoice" entityId={id} /> : null}

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

export default function Page() {
  return <InvoiceDetailPage />;
}
