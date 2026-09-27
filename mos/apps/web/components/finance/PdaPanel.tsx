"use client";

// 3.6：PDA/FDA 面板（自取数 + 创建/流转）。

import { FormEvent, useCallback, useEffect, useState } from "react";
import { LookupSelect } from "@/components/LookupSelect";
import { useToast } from "@/components/ToastProvider";
import { apiGet, apiPost } from "@/lib/api";
import { fmt } from "@/lib/fmt";
import { useI18n } from "@/lib/i18n";

type VoyageRef = { id: string; voyage_no: string };
type Pda = { id: string; voyage_id: string | null; status: string; pda_amount: number; fda_amount?: number | null; variance?: number | null; currency: string };

export function PdaPanel() {
  const { t } = useI18n();
  const toast = useToast();
  const [pdas, setPdas] = useState<Pda[]>([]);
  const [voyages, setVoyages] = useState<VoyageRef[]>([]);
  const [voyage, setVoyage] = useState("");
  const [pdaAmount, setPdaAmount] = useState("25000");
  const [fdaAmount, setFdaAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [p, v] = await Promise.all([
      apiGet("/api/v1/port-disbursements").catch(() => []),
      apiGet("/api/v1/voyages").catch(() => []),
    ]);
    setPdas(p);
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
      await apiPost("/api/v1/port-disbursements", {
        voyage_id: voyage || null,
        pda_amount: Number(pdaAmount) || 0,
        currency: currency || "USD",
        lines: {},
      });
      toast.success(t("page.finance.pda_ok", "PDA created"));
      await load();
    } catch (ex) {
      toast.error(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function transition(id: string, target: string) {
    setBusy(true);
    try {
      const q = new URLSearchParams({ target });
      if (target === "fda" && fdaAmount) q.set("fda_amount", String(Number(fdaAmount) || 0));
      await apiPost(`/api/v1/port-disbursements/${id}/transition?${q.toString()}`);
      toast.success(t("page.finance.pda_moved", "PDA → {target}", { target }));
      setFdaAmount("");
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
        <h3 style={{ marginTop: 0 }}>{t("page.finance.new_pda", "New PDA")}</h3>
        <div className="form-grid">
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
          <label>
            PDA {t("common.amount", "Amount")}
            <input type="number" step="any" value={pdaAmount} onChange={(e) => setPdaAmount(e.target.value)} />
          </label>
          <label>
            {t("page.finance.currency", "Currency")}
            <LookupSelect dataset="currencies" value={currency} onChange={setCurrency} allowEmpty={false} />
          </label>
          <label>
            FDA {t("page.finance.fda_amount", "FDA amount (on transfer)")}
            <input type="number" step="any" value={fdaAmount} onChange={(e) => setFdaAmount(e.target.value)} placeholder={t("common.optional", "Optional")} />
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
              <th>ID</th>
              <th>{t("page.voyages.list", "Voyages")}</th>
              <th>PDA</th>
              <th>FDA</th>
              <th>{t("page.finance.variance", "差异")}</th>
              <th>{t("common.status", "Status")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {pdas.map((r) => (
              <tr key={r.id}>
                <td>{r.id.slice(0, 8)}</td>
                <td>{r.voyage_id ? voyages.find((v) => v.id === r.voyage_id)?.voyage_no || r.voyage_id.slice(0, 8) : "—"}</td>
                <td>{fmt(r.pda_amount)}</td>
                <td>{fmt(r.fda_amount ?? null)}</td>
                <td>{fmt(r.variance ?? null)}</td>
                <td>{r.status}</td>
                <td>
                  <div className="desk-toolbar" style={{ margin: 0 }}>
                    {r.status === "draft" ? (
                      <button className="btn btn-sm" type="button" disabled={busy} onClick={() => transition(r.id, "submitted")}>
                        {t("common.submit", "提交")}
                      </button>
                    ) : null}
                    {r.status === "submitted" ? (
                      <button className="btn btn-sm" type="button" disabled={busy} onClick={() => transition(r.id, "approved")}>
                        {t("common.approve", "批准")}
                      </button>
                    ) : null}
                    {r.status === "approved" ? (
                      <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => transition(r.id, "fda")}>
                        → FDA
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
            {!pdas.length ? (
              <tr>
                <td colSpan={7} className="muted">
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
