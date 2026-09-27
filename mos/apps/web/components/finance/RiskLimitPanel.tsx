"use client";

// 3.6 前端拆分试点：Risk limits 面板（自取数 + 自建表单，finance 页标签挂载）。

import { FormEvent, useCallback, useEffect, useState } from "react";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { LookupSelect } from "@/components/LookupSelect";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type RiskLimit = { id: string; scope: string; limit_type: string; amount: number; currency: string };

function fmt(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function RiskLimitPanel() {
  const { t } = useI18n();
  const [limits, setLimits] = useState<RiskLimit[]>([]);
  const [scope, setScope] = useState("global");
  const [limitType, setLimitType] = useState("exposure");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      setLimits(await apiGet("/api/v1/risk/limits"));
    } catch {
      setLimits([]);
    }
  }, []);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await apiPost("/api/v1/risk/limits", {
        scope,
        limit_type: limitType,
        amount: Number(amount),
        currency,
      });
      setMsg(t("common.created", "Created"));
      setAmount("");
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <form className="panel" onSubmit={create}>
        <h3 style={{ marginTop: 0 }}>{t("page.finance.new_limit", "New risk limit")}</h3>
        {msg ? <p className="flash">{msg}</p> : null}
        {err ? <p className="flash-err">{err}</p> : null}
        <div className="form-grid">
          <label>
            {t("page.finance.scope", "Scope")}
            <input value={scope} onChange={(e) => setScope(e.target.value)} placeholder="global / symbol:X / counterparty:Y" required />
          </label>
          <label>
            {t("common.type", "Type")}
            <input value={limitType} onChange={(e) => setLimitType(e.target.value)} placeholder="exposure" required />
          </label>
          <label>
            {t("common.amount", "Amount")}
            <input type="number" step="any" value={amount} onChange={(e) => setAmount(e.target.value)} required />
          </label>
          <label>
            {t("page.finance.currency", "Currency")}
            <LookupSelect dataset="currencies" value={currency} onChange={setCurrency} allowEmpty={false} />
          </label>
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {t("common.create", "Create")}
        </button>
      </form>
      <div className="panel">
        {(() => {
          const cols: ColumnDef<(typeof limits)[number]>[] = [
            { key: "scope", title: t("page.finance.scope", "Scope") },
            { key: "limit_type", title: t("common.type", "Type") },
            { key: "amount", title: t("common.amount", "Amount"), align: "right", render: (v) => fmt(v as number) },
            { key: "currency", title: t("page.finance.currency", "Currency") },
          ];
          return (
            <DataTable
              data={limits}
              columns={cols}
              emptyText={t("common.empty", "No records")}
              editable={{
                keys: ["amount"],
                onSave: async (row, key, value) => {
                  const n = Number(value);
                  if (!Number.isFinite(n)) return;
                  try {
                    await apiPatch(`/api/v1/risk/limits/${row.id}`, { [key]: n });
                    await load();
                  } catch {
                    // 保存失败静默回读（行内编辑容错）
                    await load();
                  }
                },
              }}
            />
          );
        })()}
      </div>
    </>
  );
}
