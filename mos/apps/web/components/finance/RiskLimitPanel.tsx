"use client";

// 3.6 前端拆分试点：Risk limits 面板（自取数 + 自建表单，finance 页标签挂载）。

import { FormEvent, useCallback, useEffect, useState } from "react";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { LookupSelect } from "@/components/LookupSelect";
import { Num } from "@/components/Num";
import { RowActions } from "@/components/RowActions";
import { useToast } from "@/components/ToastProvider";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type RiskLimit = { id: string; scope: string; limit_type: string; amount: number; currency: string };

export function RiskLimitPanel() {
  const { t } = useI18n();
  const toast = useToast();
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

  // 行内编辑（失焦保存；值未变化不发请求）
  async function onCellSave(rowId: string, colKey: string, value: unknown, row: RiskLimit) {
    const src = row as unknown as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "amount") {
      const n = value === null || value === "" ? null : Number(value);
      if (n === null || isNaN(n)) return;
      if (Number(src.amount ?? NaN) === n) return;
      payload = { amount: n };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      if (value === "") return; // scope/limit_type/currency 非空
      payload = { [colKey]: value };
    }
    try {
      await apiPatch(`/api/v1/risk/limits/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
      await load();
    }
  }

  async function remove(id: string) {
    try {
      await apiDelete(`/api/v1/risk/limits/${id}`);
      toast.success(t("common.deleted", "Deleted"));
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  const cols: ColumnDef<RiskLimit>[] = [
    {
      key: "scope",
      title: t("page.finance.scope", "Scope"),
      value: (r) => r.scope,
      editor: { type: "text" },
    },
    {
      key: "limit_type",
      title: t("common.type", "Type"),
      value: (r) => r.limit_type,
      editor: { type: "text" },
    },
    {
      key: "amount",
      title: t("common.amount", "Amount"),
      align: "right",
      value: (r) => r.amount,
      render: (v) => <Num v={v as number} digits={2} />,
      editor: { type: "number", step: 0.01 },
    },
    {
      key: "currency",
      title: t("page.finance.currency", "Currency"),
      value: (r) => r.currency,
      editor: { type: "text" },
    },
    {
      key: "_actions",
      title: "",
      value: () => "",
      render: (_v, r) => (
        <span className="row-actions">
          <RowActions onDelete={() => remove(r.id)} label={`${r.scope} ${r.limit_type}`} />
        </span>
      ),
    },
  ];

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
        <DataGrid<RiskLimit>
          data={limits}
          columns={cols}
          rowKey={(r) => r.id}
          storageKey="finance_risk_limits_grid"
          showFooter={false}
          editable
          onCellSave={onCellSave}
          emptyText={t("common.empty", "No records")}
        />
      </div>
    </>
  );
}
