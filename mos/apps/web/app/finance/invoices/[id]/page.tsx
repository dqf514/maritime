"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { SkeletonCard } from "@/components/Skeleton";
import { PrintDoc } from "@/components/PrintDoc";

// U2 单据详情页：原 finance 页发票弹窗的路由化版本（可深链/收藏/分享）。

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
};
type Payment = { id: string; amount: number; currency: string; reference: string | null; paid_at: string | null; is_void_reversal: boolean };
type CreditNote = { id: string; amount: number; reason?: string | null; created_at?: string | null };

function fmt(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function InvoiceDetailPage() {
  const { t } = useI18n();
  const toast = useToast();
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
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [confirm, setConfirm] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  const refresh = useCallback(async () => {
    const data = await apiGet(`/api/v1/invoices/${id}`);
    setInv(data);
    setEditType(data.invoice_type || "freight");
    setEditAmount(String(data.amount ?? ""));
    const [pays, cns] = await Promise.all([
      apiGet(`/api/v1/invoices/${id}/payments`).catch(() => []),
      apiGet(`/api/v1/invoices/${id}/credit-notes`).catch(() => []),
    ]);
    setPayments(Array.isArray(pays) ? pays : []);
    setCreditNotes(Array.isArray(cns) ? cns : []);
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
    if (!editAmount.trim() || Number.isNaN(amount)) {
      setErr(t("page.finance.bad_amount", "金额必须是有效数字"));
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await apiPatch(`/api/v1/invoices/${id}`, { amount, invoice_type: editType });
      toast.success(t("common.saved", "Saved"));
      await refresh();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setSaving(true);
    try {
      await apiDelete(`/api/v1/invoices/${id}`);
      window.location.href = "/finance?tab=invoices";
    } catch (ex) {
      setErr(String(ex));
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
        setErr(t("page.finance.credit_required", "发票已收款，需先红冲（credit note）后才能作废。"));
      } else {
        setErr(String(ex));
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
    } catch (ex) {
      setErr(String(ex));
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
      if (ex?.status === 409 && ex?.detail?.code === "CREDIT_EXCEEDS_BALANCE") {
        setErr(t("page.finance.cn_exceeds", "红冲金额超过发票余额"));
      } else {
        setErr(String(ex));
      }
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
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

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

  return (
    <AppShell
      breadcrumbs={[
        { label: t("page.finance.title", "Finance / laytime / P&L"), href: "/finance" },
        { label: inv?.invoice_no || t("page.finance.no", "编号") },
      ]}
    >
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>
            {inv?.invoice_no || "…"}
            {inv ? (
              <span className={`badge ${inv.status === "paid" ? "badge-ok" : "badge-warn"}`} style={{ marginLeft: "0.6rem" }}>
                {inv.status}
              </span>
            ) : null}
          </h1>
          <p className="page-sub">{t("page.finance.edit_inv", "编辑发票")}</p>
        </div>
        <div className="desk-toolbar" style={{ margin: 0 }}>
          <Link href="/finance?tab=invoices" className="btn btn-ghost">
            {t("common.back", "返回")}
          </Link>
          <button className="btn btn-sm" type="button" disabled={busy || saving} onClick={() => window.print()}>
            {t("common.print", "打印 / PDF")}
          </button>
        </div>
      </div>

      {err ? <p className="err-text">{err}</p> : null}

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
          <label>
            {t("common.amount", "Amount")}
            <input type="number" step="any" value={editAmount} onChange={(e) => setEditAmount(e.target.value)} />
          </label>
          <label>
            {t("page.finance.currency", "Currency")}
            <input value={inv?.currency || ""} disabled />
          </label>
          <label>
            {t("page.finance.paid_col", "已付")}
            <input value={fmt(inv?.paid_amount)} disabled />
          </label>
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="button" disabled={saving || busy} onClick={save}>
            {t("common.save", "保存")}
          </button>
          {inv?.status === "draft" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => transition("pending_approval")}>
              {t("common.submit", "提交")}
            </button>
          ) : null}
          {inv?.status === "pending_approval" ? (
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => transition("issued")}>
              {t("page.finance.issue", "开票")}
            </button>
          ) : null}
          {inv && ["issued", "partially_paid"].includes(inv.status) ? (
            <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={() => transition("void")}>
              {t("page.finance.void", "作废")}
            </button>
          ) : null}
          {inv && ["issued", "partially_paid", "paid"].includes(inv.status) ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={glPost}>
              {t("page.finance.gl", "过账")}
            </button>
          ) : null}
          <button
            className="btn btn-danger btn-sm"
            type="button"
            disabled={saving || busy}
            onClick={() =>
              setConfirm({
                message: t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored."),
                danger: true,
                action: remove,
              })
            }
          >
            {t("common.delete", "删除")}
          </button>
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
              {payments.map((p) => (
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

      <div className="panel">
        <div className="desk-toolbar" style={{ marginTop: 0 }}>
          <h3 style={{ margin: 0 }}>{t("page.finance.credit_notes", "Credit notes")} ({creditNotes.length})</h3>
          <button className="btn btn-sm" type="button" disabled={busy} onClick={() => setCnOpen((v) => !v)}>
            {t("page.finance.credit_note", "红冲")}
          </button>
        </div>
        {creditNotes.length ? (
          <table className="table" style={{ marginTop: "0.5rem" }}>
            <tbody>
              {creditNotes.map((cn) => (
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

      </PrintDoc>

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
