"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ContactPicker } from "@/components/DataPicker";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";
import { SkeletonCard } from "@/components/Skeleton";

// U2 单据详情页：原 finance 页索赔弹窗的路由化版本（可深链/收藏/分享）。

type Claim = {
  id: string;
  claim_no: string;
  claim_type?: string;
  status: string;
  amount: number;
  currency?: string;
  time_bar?: string | null;
  days_to_timebar?: number | null;
  settlement_amount?: number | null;
  notes?: string | null;
};
type ClaimTypeOpt = { code: string; label: { en: string; zh?: string } };

function ClaimDetailPage() {
  const { t, locale } = useI18n();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const id = params.id;

  const [claim, setClaim] = useState<Claim | null>(null);
  const [claimTypes, setClaimTypes] = useState<ClaimTypeOpt[]>([]);
  const [editType, setEditType] = useState("demurrage");
  const [editContact, setEditContact] = useState("");
  const [editAmount, setEditAmount] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [settleAmount, setSettleAmount] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [confirm, setConfirm] = useState<{ message: string; danger?: boolean; action: () => void } | null>(null);

  const refresh = useCallback(async () => {
    const data = await apiGet(`/api/v1/claims/${id}`);
    setClaim(data);
    setEditType(data.claim_type || "demurrage");
    setEditContact(data.contact?.id || "");
    setEditAmount(String(data.amount ?? ""));
    setEditNotes(data.notes || "");
    setSettleAmount(String(data.settlement_amount ?? data.amount ?? ""));
  }, [id]);

  useEffect(() => {
    refresh().catch((ex) => {
      if (ex?.status === 404) setNotFound(true);
      else setErr(String(ex));
    });
    apiGet("/api/v1/claims/types")
      .then((r: { items: ClaimTypeOpt[] }) => setClaimTypes(r.items))
      .catch(() => setClaimTypes([]));
  }, [refresh]);

  async function save() {
    setSaving(true);
    setErr("");
    try {
      await apiPatch(`/api/v1/claims/${id}`, {
        claim_type: editType,
        contact_id: editContact || null,
        amount: Number(editAmount) || 0,
        notes: editNotes || null,
      });
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
      await apiDelete(`/api/v1/claims/${id}`);
      window.location.href = "/finance?tab=claims";
    } catch (ex) {
      setErr(String(ex));
      setSaving(false);
    }
  }

  async function transition(target: string) {
    setBusy(true);
    setErr("");
    try {
      const q = new URLSearchParams({ target });
      if (target === "settled" && settleAmount !== "") q.set("settlement_amount", String(Number(settleAmount) || 0));
      await apiPost(`/api/v1/claims/${id}/transition?${q.toString()}`);
      toast.success(t("page.finance.claim_moved", "Claim → {target}", { target }));
      await refresh();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function toInvoice() {
    setBusy(true);
    setErr("");
    try {
      const inv = await apiPost(`/api/v1/claims/${id}/to-invoice`);
      toast.success(t("page.finance.created_inv", "Invoice {no} created", { no: inv.invoice_no }));
      await refresh();
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

  if (!claim && !notFound) {
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
          <Link href="/finance?tab=claims" className="btn">
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
        { label: claim?.claim_no || t("page.finance.no", "编号") },
      ]}
    >
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>
            {claim?.claim_no || "…"}
            {claim ? (
              <span className="badge badge-warn" style={{ marginLeft: "0.6rem" }}>
                {claim.status}
              </span>
            ) : null}
          </h1>
          <p className="page-sub">{t("page.finance.edit_claim", "编辑索赔")}</p>
        </div>
        <div className="desk-toolbar" style={{ margin: 0 }}>
          <Link href="/finance?tab=claims" className="btn btn-ghost">
            {t("common.back", "返回")}
          </Link>
          <button className="btn btn-sm" type="button" disabled={busy || saving} onClick={() => window.print()}>
            {t("common.print", "打印 / PDF")}
          </button>
        </div>
      </div>

      {err ? <p className="err-text">{err}</p> : null}

      <div className="panel">
        {claim?.days_to_timebar != null ? (
          <p style={{ margin: "0 0 0.75rem" }}>
            {t("page.finance.days_to_timebar", "Days to time bar")}:{" "}
            <strong style={claim.days_to_timebar < 14 ? { color: "#dc2626" } : undefined}>{claim.days_to_timebar}</strong>
            {claim.time_bar ? <span className="muted">（{claim.time_bar}）</span> : null}
          </p>
        ) : null}
        <div className="form-grid">
          <label>
            {t("page.finance.claim_type", "索赔类型")}
            <select value={editType} onChange={(e) => setEditType(e.target.value)}>
              {claimTypes.map((ct) => (
                <option key={ct.code} value={ct.code}>
                  {locale.startsWith("zh") ? ct.label.zh || ct.label.en : ct.label.en}
                </option>
              ))}
              {!claimTypes.some((ct) => ct.code === editType) ? <option value={editType}>{editType}</option> : null}
            </select>
          </label>
          <label>
            {t("page.parties.contact", "对方联系人")}
            <ContactPicker value={editContact} onChange={setEditContact} placeholder={t("picker.search", "搜索联系人…")} />
          </label>
          <label>
            {t("common.amount", "Amount")}
            <input type="number" step="any" value={editAmount} onChange={(e) => setEditAmount(e.target.value)} />
          </label>
          <label>
            {t("page.finance.notes", "备注")}
            <input value={editNotes} onChange={(e) => setEditNotes(e.target.value)} />
          </label>
          {claim && (claim.status === "open" || claim.status === "negotiating") ? (
            <label>
              {t("page.finance.settlement_amount", "Settlement amount")}
              <input type="number" step="any" value={settleAmount} onChange={(e) => setSettleAmount(e.target.value)} />
            </label>
          ) : null}
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="button" disabled={saving || busy} onClick={save}>
            {t("common.save", "保存")}
          </button>
          {claim?.status === "open" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => transition("negotiating")}>
              {t("page.finance.negotiate", "谈判")}
            </button>
          ) : null}
          {claim && (claim.status === "open" || claim.status === "negotiating") ? (
            <>
              <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => transition("settled")}>
                {t("page.finance.settle", "结清")}
              </button>
              <button className="btn btn-sm" type="button" disabled={busy} onClick={() => transition("withdrawn")}>
                {t("page.finance.withdraw", "撤回")}
              </button>
            </>
          ) : null}
          {claim?.status === "settled" ? (
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={toInvoice}>
              {t("page.finance.to_invoice", "生成发票")}
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
  return <ClaimDetailPage />;
}
