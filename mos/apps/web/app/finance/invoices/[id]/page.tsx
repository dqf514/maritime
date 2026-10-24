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
import { StateView } from "@/components/StateView";
import { StatusBadge } from "@/components/StatusBadge";
import { ValidateButton, type ValidateIssue } from "@/components/ValidateButton";
import { useStateActions } from "@/components/useTransitions";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { baseAmountPreview } from "@/lib/numbers";
import { formatInTz } from "@/lib/datetime";
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
  const { t, locale } = useI18n();
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
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [sectionErr, setSectionErr] = useState<{ payments?: string; creditNotes?: string; mirror?: string }>({});
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [confirm, setConfirm] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  const nextStatuses = useStateActions("invoice", inv?.status);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet(`/api/v1/invoices/${id}`);
      setInv(data);
      setEditType(data.invoice_type || "freight");
      setEditAmount(String(data.amount ?? ""));
      setLoadErr("");
      // 附属数据失败不拖垮整页，但必须可见（不能静默变空列表）
      const [pays, cns, chain] = await Promise.allSettled([
        apiGet(`/api/v1/invoices/${id}/payments`),
        apiGet(`/api/v1/invoices/${id}/credit-notes`),
        apiGet(`/api/v1/invoices/${id}/mirror-chain`),
      ]);
      setPayments(pays.status === "fulfilled" && Array.isArray(pays.value) ? pays.value : []);
      setCreditNotes(cns.status === "fulfilled" && Array.isArray(cns.value) ? cns.value : []);
      setMirrorChain(chain.status === "fulfilled" && Array.isArray(chain.value?.items) ? chain.value.items : []);
      const sectionErr: { payments?: string; creditNotes?: string; mirror?: string } = {};
      if (pays.status === "rejected") sectionErr.payments = msgOf(pays.reason);
      if (cns.status === "rejected") sectionErr.creditNotes = msgOf(cns.reason);
      if (chain.status === "rejected") sectionErr.mirror = msgOf(chain.reason);
      setSectionErr(sectionErr);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    refresh()
      .catch((ex) => {
        if (ex?.status === 404) setNotFound(true);
        else setLoadErr(msgOf(ex));
      });
  }, [refresh]);

  /** 重新加载（错误态重试按钮用） */
  function reload() {
    setLoadErr("");
    setNotFound(false);
    refresh().catch((ex) => {
      if (ex?.status === 404) setNotFound(true);
      else setLoadErr(msgOf(ex));
    });
  }

  async function save() {
    const raw = editAmount.trim();
    const amount = Number(raw);
    if (!raw || !Number.isFinite(amount) || amount < 0) {
      const msg = t("page.finance.bad_amount", "金额必须是有效数字");
      setErr(msg);
      toast.error(msg);
      return;
    }
    // P1-13：保存前跑校验，阻断级（error）问题中止提交
    const blockers = blockingIssues(inv ? { ...inv, amount, invoice_type: editType } : null);
    if (blockers.length) {
      const msg = blockingMessage(blockers);
      setErr(msg);
      toast.error(msg);
      return;
    }
    setSaving(true);
    setErr("");
    try {
      await apiPatch(`/api/v1/invoices/${id}`, { amount, invoice_type: editType });
      toast.success(t("common.saved", "Saved"));
      await refresh();
    } catch (ex: any) {
      setErr(msgOf(ex));
      toast.error(msgOf(ex));
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
      setErr(msgOf(ex));
      toast.error(msgOf(ex));
      setSaving(false);
    }
  }

  async function transition(target: string) {
    // P1-13：提交/开票等推进动作同样受阻断级校验约束
    if (["pending_approval", "issued"].includes(target)) {
      const blockers = blockingIssues(inv);
      if (blockers.length) {
        const msg = blockingMessage(blockers);
        setErr(msg);
        toast.error(msg);
        return;
      }
    }
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
        const msg = msgOf(ex);
        setErr(msg);
        toast.error(msg);
      }
    } finally {
      setBusy(false);
    }
  }

  async function recordPayment(e: FormEvent) {
    e.preventDefault();
    const raw = payAmount.trim();
    const amount = Number(raw);
    if (!raw || !Number.isFinite(amount) || amount <= 0) {
      const msg = t("page.finance.need_pay", "Enter payment amount");
      setErr(msg);
      toast.error(msg);
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
      const msg = msgOf(ex);
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
        msg = msgOf(ex);
      }
      setErr(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  async function createCreditNote(e: FormEvent) {
    e.preventDefault();
    const raw = cnAmount.trim();
    const amount = Number(raw);
    if (!raw || !Number.isFinite(amount)) {
      const msg = t("page.finance.bad_amount", "金额必须是有效数字");
      setErr(msg);
      toast.error(msg);
      return;
    }
    // P1-8：红冲是不可逆操作 —— 二次确认并指名对象
    setConfirm({
      message: t("page.finance.cn_confirm", "对发票 {no} 红冲 {amount} {cur}？红冲后不可撤销。", {
        no: inv?.invoice_no || id,
        amount: amount.toLocaleString(undefined, { maximumFractionDigits: 2 }),
        cur: inv?.currency || "USD",
      }),
      danger: true,
      action: () => void postCreditNote(amount),
    });
  }

  async function postCreditNote(amount: number) {
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
        msg = msgOf(ex);
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
      const msg = msgOf(ex);
      setErr(msg);
      toast.error(msg);
    } finally {
      setBusy(false);
    }
  }

  /** R4 前端校验：错误阻断 / 警告可继续 / 全绿通过 */
  function validateInvoice(target: Invoice | null = inv): ValidateIssue[] {
    const issues: ValidateIssue[] = [];
    if (!target) return issues;
    if (!(Number(target.amount) > 0)) {
      issues.push({ level: "error", message: t("validate.inv_amount", "Amount must be greater than zero.") });
    }
    if (!target.counterparty_id) {
      issues.push({ level: "error", message: t("validate.inv_counterparty", "Counterparty is required.") });
    }
    if (!INVOICE_TYPES.includes(target.invoice_type || "")) {
      issues.push({ level: "error", message: t("validate.inv_type", "Invalid invoice type: {type}", { type: target.invoice_type || "—" }) });
    }
    if (target.due_date && target.issued_at && String(target.due_date) < String(target.issued_at).slice(0, 10)) {
      issues.push({ level: "error", message: t("validate.inv_due", "Due date is before the invoice date.") });
    }
    if (target.currency && target.currency !== "USD" && (target.fx_rate === null || target.fx_rate === undefined)) {
      issues.push({ level: "warn", message: t("validate.inv_fx", "FX rate missing on non-base currency ({cur}).", { cur: target.currency }) });
    }
    if (!target.voyage_id) {
      issues.push({ level: "warn", message: t("validate.inv_voyage", "No PDA / linked voyage on this invoice.") });
    }
    return issues;
  }

  /** 只取阻断级（error）问题 —— 存在即不允许保存/提交 */
  function blockingIssues(target: Invoice | null): ValidateIssue[] {
    return validateInvoice(target).filter((i) => i.level === "error");
  }

  function blockingMessage(issues: ValidateIssue[]): string {
    return t("page.finance.blocking_issues", "存在 {n} 项阻断级问题，操作已中止：{list}", {
      n: issues.length,
      list: issues.map((i) => i.message).join(" / "),
    });
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
        render: (v) => (v ? formatInTz(v as string | null, null, undefined, locale) : "—"),
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
                  message: t("page.finance.void_payment_confirm", "冲正付款 {amount} {cur}？将生成等额反向付款行。", {
                    amount: fmt(p.amount),
                    cur: p.currency || "USD",
                  }),
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

  // P1-5：loading / error / content 三态互斥 —— 错误绝不能被骨架屏吞掉
  if (!inv) {
    return (
      <AppShell>
        <StateView
          loading={loading}
          error={loadErr || undefined}
          empty={!loading && !loadErr}
          emptyText={t("common.empty", "No records")}
          onRetry={reload}
        >
          <SkeletonCard />
        </StateView>
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
      onClick: () => {
        // P1-8：作废发票是不可逆操作 —— 二次确认并指名对象
        if (target === "void") {
          setConfirm({
            message: t("page.finance.void_invoice_confirm", "作废发票 {no}？作废后不可撤销。", { no: inv?.invoice_no || id }),
            danger: true,
            action: () => void transition(target),
          });
          return;
        }
        void transition(target);
      },
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
        message: t("page.finance.delete_invoice_confirm", "删除发票 {no}？记录将移入回收站，可恢复。", { no: inv?.invoice_no || id }),
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
        entityType="invoice"
        entityId={id}
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
      {loadErr ? (
        <p className="state-view-text state-view-error">
          {t("page.finance.load_failed", "数据加载失败：{msg}", { msg: loadErr })}
        </p>
      ) : null}
      {sectionErr.mirror ? (
        <p className="state-view-text state-view-error">
          {t("page.finance.mirror_chain_failed", "镜像链加载失败：{msg}", { msg: sectionErr.mirror })}
        </p>
      ) : null}

      <div className={showDraftWatermark ? "draft-watermark" : undefined}>
      <PrintDoc
        title={t("page.finance.invoice_doc", "INVOICE")}
        no={inv?.invoice_no}
        meta={inv ? `${inv.status} · ${inv.currency || "USD"}` : undefined}
        entityType="invoice"
        entityId={id}
      >
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
            baseAmount={baseAmountPreview(editAmount, inv?.fx_rate) ?? (inv?.base_amount ?? null)}
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
        {sectionErr.payments ? (
          <p className="state-view-text state-view-error">
            {t("page.finance.payments_failed", "付款记录加载失败：{msg}", { msg: sectionErr.payments })}
          </p>
        ) : null}
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
        {sectionErr.creditNotes ? (
          <p className="state-view-text state-view-error">
            {t("page.finance.credit_notes_failed", "红冲记录加载失败：{msg}", { msg: sectionErr.creditNotes })}
          </p>
        ) : null}
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
