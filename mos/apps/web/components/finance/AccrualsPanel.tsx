"use client";

// 3.6：Voyage accruals 面板（自取数 + 创建/过账）。

import { FormEvent, useCallback, useEffect, useState } from "react";
import { LookupSelect } from "@/components/LookupSelect";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiPost } from "@/lib/api";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";

type VoyageRef = { id: string; voyage_no: string };
type Accrual = { id: string; voyage_id: string | null; period_ym: string; line_type: string; amount: number; currency: string; status: string };

export function AccrualsPanel() {
  const { t } = useI18n();
  const toast = useToast();
  const [accruals, setAccruals] = useState<Accrual[]>([]);
  const [voyages, setVoyages] = useState<VoyageRef[]>([]);
  const [period, setPeriod] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [lineType, setLineType] = useState("freight");
  const [amount, setAmount] = useState("10000");
  const [voyage, setVoyage] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [a, v] = await Promise.all([
      apiGet("/api/v1/finance/accruals").catch(() => []),
      apiGet("/api/v1/voyages").catch(() => []),
    ]);
    setAccruals(a);
    setVoyages(v);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await apiPost("/api/v1/finance/accruals", {
        voyage_id: voyage || null,
        period_ym: period,
        line_type: lineType,
        amount: Number(amount) || 0,
        currency: currency || "USD",
      });
      toast.success(t("page.finance.accrual_ok", "Accrual created"));
      await load();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function post(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/finance/accruals/${id}/post`);
      toast.success(t("page.finance.accrual_posted", "Accrual posted"));
      await load();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="panel" onSubmit={create}>
        <h3 style={{ marginTop: 0 }}>{t("page.finance.new_accrual", "New accrual")}</h3>
        <div className="form-grid">
          <label>
            {t("page.finance.period", "Period YYYY-MM")}
            <input value={period} onChange={(e) => setPeriod(e.target.value)} required />
          </label>
          <label>
            {t("common.type", "类型")}
            <select value={lineType} onChange={(e) => setLineType(e.target.value)}>
              <option value="freight">{t("page.finance.line_freight", "Freight")}</option>
              <option value="hire">{t("page.finance.line_hire", "Hire")}</option>
              <option value="commission">{t("page.finance.line_commission", "Commission")}</option>
              <option value="bunker">{t("page.finance.line_bunker", "Bunker")}</option>
              <option value="port">{t("page.finance.line_port", "Port costs")}</option>
              <option value="other">{t("page.finance.line_other", "Other")}</option>
            </select>
          </label>
          <label>
            {t("common.amount", "Amount")}
            <input type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label>
            {t("page.finance.currency", "Currency")}
            <LookupSelect dataset="currencies" value={currency} onChange={setCurrency} allowEmpty={false} />
          </label>
          <label>
            {t("page.voyages.list", "Voyages")}
            <select value={voyage} onChange={(e) => setVoyage(e.target.value)}>
              <option value="">—</option>
              {voyages.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.voyage_no}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {t("common.create", "Create")}
        </button>
      </form>
      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.finance.period", "Period YYYY-MM")}</th>
              <th>{t("common.type", "类型")}</th>
              <th>{t("page.voyages.list", "Voyages")}</th>
              <th>{t("common.amount", "Amount")}</th>
              <th>{t("common.status", "Status")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {accruals.map((r) => (
              <tr key={r.id}>
                <td>{r.period_ym}</td>
                <td>{r.line_type}</td>
                <td>{r.voyage_id ? voyages.find((v) => v.id === r.voyage_id)?.voyage_no || r.voyage_id.slice(0, 8) : "—"}</td>
                <td>
                  {fmt(r.amount)} {r.currency}
                </td>
                <td>{r.status}</td>
                <td>
                  {r.status === "draft" ? (
                    <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => post(r.id)}>
                      {t("page.finance.post", "Post")}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
            {!accruals.length ? (
              <tr>
                <td colSpan={6} className="muted">
                  {t("common.empty", "No records")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </>
  );
}
