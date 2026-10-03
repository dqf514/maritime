"use client";

// 加油需求采购链面板：需求 → 招标 → 供应商报价 → 选定（A1/A2/A6）。
// 自取数 + 自建表单，挂载在 Bunker desk 页。

import { FormEvent, useCallback, useEffect, useState } from "react";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Ref = { id: string; name: string };

type Requirement = {
  id: string;
  requirement_no: string;
  status: string;
  vessel_id: string;
  fuel_type: string;
  qty_required: number;
  port_id: string | null;
  window_from: string | null;
  window_to: string | null;
};

type Option = {
  id: string;
  requirement_id: string;
  supplier_id: string;
  fuel_type: string;
  qty: number;
  price_per_mt: number;
  amount: number;
  status: string;
};

function fmt(n: number | undefined | null) {
  if (n === undefined || n === null) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function BunkerRequirementsPanel() {
  const { t } = useI18n();
  const toast = useToast();
  const [reqs, setReqs] = useState<Requirement[]>([]);
  const [opts, setOpts] = useState<Option[]>([]);
  const [vessels, setVessels] = useState<Ref[]>([]);
  const [parties, setParties] = useState<Ref[]>([]);
  const [ports, setPorts] = useState<Ref[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [form, setForm] = useState({ vessel_id: "", fuel_type: "VLSFO", qty_required: "500", port_id: "" });
  const [optForm, setOptForm] = useState({ supplier_id: "", price_per_mt: "600" });

  const load = useCallback(async () => {
    const [r, v, p, pt] = await Promise.all([
      apiGet("/api/v1/bunker/requirements").catch(() => ({ items: [] })),
      apiGet("/api/v1/masterdata/vessels").catch(() => []),
      apiGet("/api/v1/masterdata/ports").catch(() => []),
      apiGet("/api/v1/masterdata/counterparties").catch(() => []),
    ]);
    setReqs(r.items || []);
    setVessels(v);
    setPorts(p);
    setParties(pt);
  }, []);

  const loadOptions = useCallback(async (requirementId: string) => {
    if (!requirementId) {
      setOpts([]);
      return;
    }
    const r = await apiGet(`/api/v1/bunker/options?requirement_id=${requirementId}`).catch(() => ({ items: [] }));
    setOpts(r.items || []);
  }, []);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
  }, [load, t]);

  useEffect(() => {
    loadOptions(selected).catch(() => undefined);
  }, [selected, loadOptions]);

  async function createRequirement(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await apiPost("/api/v1/bunker/requirements", {
        vessel_id: form.vessel_id,
        fuel_type: form.fuel_type,
        qty_required: Number(form.qty_required) || 0,
        port_id: form.port_id || null,
      });
      toast.success(t("page.bunker.req_created", "Bunker requirement created"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function tender(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/bunker/requirements/${id}/tender`);
      toast.success(t("page.bunker.req_tendering", "Tendering opened"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function move(id: string, target: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/bunker/requirements/${id}/transition?target=${target}`);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addOption(e: FormEvent) {
    e.preventDefault();
    if (!selected) return;
    setBusy(true);
    setErr("");
    try {
      await apiPost("/api/v1/bunker/options", {
        requirement_id: selected,
        supplier_id: optForm.supplier_id,
        price_per_mt: Number(optForm.price_per_mt) || 0,
      });
      toast.success(t("page.bunker.opt_created", "Option registered"));
      await loadOptions(selected);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function selectOption(id: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/bunker/options/${id}/select`);
      toast.success(t("page.bunker.opt_selected", "Option selected"));
      await load();
      await loadOptions(selected);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  const reqCols: ColumnDef<Requirement>[] = [
    { key: "requirement_no", title: t("page.finance.number", "No.") },
    { key: "fuel_type", title: t("page.bunker.grade", "Grade") },
    { key: "qty_required", title: t("page.bunker.qty", "Qty (mt)"), align: "right", render: (v) => fmt(v as number) },
    { key: "status", title: t("common.status", "Status") },
    {
      key: "id",
      title: t("common.actions", "Actions"),
      render: (_v, row) => (
        <span className="desk-toolbar" style={{ margin: 0 }}>
          {row.status === "draft" || row.status === "approved" ? (
            <button className="btn btn-sm" type="button" onClick={() => tender(row.id)}>
              {t("page.bunker.req_tender", "Tender")}
            </button>
          ) : null}
          {row.status === "ordered" ? (
            <button className="btn btn-sm" type="button" onClick={() => move(row.id, "fulfilled")}>
              {t("page.bunker.req_fulfill", "Fulfill")}
            </button>
          ) : null}
          {row.status !== "fulfilled" && row.status !== "cancelled" ? (
            <button className="btn btn-sm btn-ghost" type="button" onClick={() => move(row.id, "cancelled")}>
              {t("common.cancel", "Cancel")}
            </button>
          ) : null}
        </span>
      ),
    },
  ];

  const optCols: ColumnDef<Option>[] = [
    { key: "supplier_id", title: t("page.bunker.supplier", "Supplier"), render: (v) => String(v).slice(0, 8) },
    { key: "fuel_type", title: t("page.bunker.grade", "Grade") },
    { key: "qty", title: t("page.bunker.qty", "Qty (mt)"), align: "right", render: (v) => fmt(v as number) },
    { key: "price_per_mt", title: t("page.bunker.price", "Price/mt"), align: "right", render: (v) => fmt(v as number) },
    { key: "status", title: t("common.status", "Status") },
    {
      key: "id",
      title: t("common.actions", "Actions"),
      render: (_v, row) =>
        row.status === "offered" ? (
          <button className="btn btn-sm" type="button" onClick={() => selectOption(row.id)}>
            {t("page.bunker.opt_select", "Select")}
          </button>
        ) : null,
    },
  ];

  return (
    <>
      <form className="panel" onSubmit={createRequirement}>
        <h3 style={{ marginTop: 0 }}>{t("page.bunker.requirements", "Bunker requirements")}</h3>
        {err ? <p className="flash-err">{err}</p> : null}
        <div className="form-grid">
          <label>
            {t("page.estimates.vessel", "Vessel")}
            <select value={form.vessel_id} onChange={(e) => setForm({ ...form, vessel_id: e.target.value })} required>
              <option value="">—</option>
              {vessels.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.bunker.grade", "Grade")}
            <input value={form.fuel_type} onChange={(e) => setForm({ ...form, fuel_type: e.target.value })} required />
          </label>
          <label>
            {t("page.bunker.qty", "Qty required (mt)")}
            <input value={form.qty_required} onChange={(e) => setForm({ ...form, qty_required: e.target.value })} required />
          </label>
          <label>
            {t("page.masterdata.port", "Port")}
            <select value={form.port_id} onChange={(e) => setForm({ ...form, port_id: e.target.value })}>
              <option value="">—</option>
              {ports.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
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
        <DataTable
          data={reqs}
          columns={reqCols}
          emptyText={t("common.empty", "No records")}
          onRowClick={(row) => setSelected(row.id)}
        />
      </div>

      {selected ? (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.bunker.options", "Supplier options")}</h3>
          <form className="form-grid" onSubmit={addOption}>
            <label>
              {t("page.bunker.supplier", "Supplier")}
              <select
                value={optForm.supplier_id}
                onChange={(e) => setOptForm({ ...optForm, supplier_id: e.target.value })}
                required
              >
                <option value="">—</option>
                {parties.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("page.bunker.price", "Price/mt")}
              <input
                value={optForm.price_per_mt}
                onChange={(e) => setOptForm({ ...optForm, price_per_mt: e.target.value })}
                required
              />
            </label>
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {t("common.create", "Create")}
            </button>
          </form>
          <DataTable data={opts} columns={optCols} emptyText={t("common.empty", "No records")} />
        </div>
      ) : null}
    </>
  );
}
