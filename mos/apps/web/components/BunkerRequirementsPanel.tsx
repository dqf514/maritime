"use client";

// 加油需求采购链面板：需求 → 招标 → 供应商报价 → 选定（A1/A2/A6）。
// 自取数 + 自建表单，挂载在 Bunker desk 页。

import { FormEvent, useCallback, useEffect, useState } from "react";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { RowActions } from "@/components/RowActions";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
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

  // 状态门（与后端一致）：ordered|fulfilled|cancelled 不可改删；option 仅 offered 可改删
  function reqEditable(r: Requirement) {
    return r.status !== "ordered" && r.status !== "fulfilled" && r.status !== "cancelled";
  }
  function optEditable(r: Option) {
    return r.status === "offered";
  }

  // 行内编辑（失焦保存；值未变化不发请求）
  async function onReqCellSave(rowId: string, colKey: string, value: unknown, row: Requirement) {
    if (!reqEditable(row)) return;
    const src = row as unknown as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "qty_required") {
      const n = value === null || value === "" ? null : Number(value);
      if (n === null || isNaN(n) || n <= 0) return;
      if (Number(src.qty_required ?? NaN) === n) return;
      payload = { qty_required: n };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      if (value === "") return; // fuel_type 非空
      payload = { [colKey]: value };
    }
    try {
      await apiPatch(`/api/v1/bunker/requirements/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  async function deleteReq(id: string) {
    try {
      await apiDelete(`/api/v1/bunker/requirements/${id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      if (selected === id) setSelected("");
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  async function onOptCellSave(rowId: string, colKey: string, value: unknown, row: Option) {
    if (!optEditable(row)) return;
    const src = row as unknown as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "qty" || colKey === "price_per_mt") {
      const n = value === null || value === "" ? null : Number(value);
      if (n === null || isNaN(n) || n < 0) return;
      if (Number(src[colKey] ?? NaN) === n) return;
      payload = { [colKey]: n };
    } else if (colKey === "supplier_id") {
      if ((row.supplier_id ?? "") === (value ?? "")) return;
      if (!value) return;
      payload = { supplier_id: value };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      if (value === "") return;
      payload = { [colKey]: value };
    }
    try {
      await apiPatch(`/api/v1/bunker/options/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await loadOptions(selected);
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  async function deleteOpt(id: string) {
    try {
      await apiDelete(`/api/v1/bunker/options/${id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      await loadOptions(selected);
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  const reqCols: ColumnDef<Requirement>[] = [
    { key: "requirement_no", title: t("page.finance.number", "No."), value: (r) => r.requirement_no },
    {
      key: "fuel_type",
      title: t("page.bunker.grade", "Grade"),
      value: (r) => r.fuel_type,
      editor: { type: "text" },
    },
    {
      key: "qty_required",
      title: t("page.bunker.qty", "Qty (mt)"),
      align: "right",
      value: (r) => r.qty_required,
      render: (v) => fmt(v as number),
      editor: { type: "number", step: 0.1, min: 0 },
    },
    { key: "status", title: t("common.status", "Status"), value: (r) => r.status },
    {
      key: "_actions",
      title: t("common.actions", "Actions"),
      value: () => "",
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
          <RowActions
            canEdit={reqEditable(row)}
            canDelete={reqEditable(row)}
            onDelete={() => deleteReq(row.id)}
            label={row.requirement_no}
          />
        </span>
      ),
    },
  ];

  const optCols: ColumnDef<Option>[] = [
    {
      key: "supplier_id",
      title: t("page.bunker.supplier", "Supplier"),
      value: (r) => r.supplier_id,
      render: (v) => parties.find((p) => p.id === v)?.name || String(v ?? "").slice(0, 8),
      editor: { type: "select", options: parties.map((p) => ({ value: p.id, label: p.name })) },
    },
    {
      key: "fuel_type",
      title: t("page.bunker.grade", "Grade"),
      value: (r) => r.fuel_type,
      editor: { type: "text" },
    },
    {
      key: "qty",
      title: t("page.bunker.qty", "Qty (mt)"),
      align: "right",
      value: (r) => r.qty,
      render: (v) => fmt(v as number),
      editor: { type: "number", step: 0.1, min: 0 },
    },
    {
      key: "price_per_mt",
      title: t("page.bunker.price", "Price/mt"),
      align: "right",
      value: (r) => r.price_per_mt,
      render: (v) => fmt(v as number),
      editor: { type: "number", step: 0.01, min: 0 },
    },
    { key: "status", title: t("common.status", "Status"), value: (r) => r.status },
    {
      key: "_actions",
      title: t("common.actions", "Actions"),
      value: () => "",
      render: (_v, row) => (
        <span className="row-actions">
          {row.status === "offered" ? (
            <button className="btn btn-sm" type="button" onClick={() => selectOption(row.id)}>
              {t("page.bunker.opt_select", "Select")}
            </button>
          ) : null}
          <RowActions
            canEdit={optEditable(row)}
            canDelete={optEditable(row)}
            onDelete={() => deleteOpt(row.id)}
            label={`${row.fuel_type} ${fmt(row.price_per_mt)}`}
          />
        </span>
      ),
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
        <DataGrid<Requirement>
          data={reqs}
          columns={reqCols}
          rowKey={(r) => r.id}
          storageKey="bunker_requirements_grid"
          showFooter={false}
          editable
          onCellSave={onReqCellSave}
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
          <DataGrid<Option>
            data={opts}
            columns={optCols}
            rowKey={(r) => r.id}
            storageKey="bunker_options_grid"
            showFooter={false}
            editable
            onCellSave={onOptCellSave}
            emptyText={t("common.empty", "No records")}
          />
        </div>
      ) : null}
    </>
  );
}
