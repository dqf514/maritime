"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { RecordModal } from "@/components/RecordModal";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type RefItem = { id: string; name: string };
type Charter = {
  id: string;
  charter_no: string;
  charter_type: string;
  status: string;
  vessel_id: string | null;
  counterparty_id: string | null;
  estimate_id: string | null;
  laycan_from: string | null;
  laycan_to: string | null;
  commission_pct: number | null;
  freight_terms: Record<string, unknown>;
  clauses: Record<string, unknown>;
  sanctions_blocked: boolean;
};

export default function ChartersPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Charter[]>([]);
  const [vessels, setVessels] = useState<RefItem[]>([]);
  const [parties, setParties] = useState<RefItem[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const [charterType, setCharterType] = useState("voyage");
  const [vesselId, setVesselId] = useState("");
  const [partyId, setPartyId] = useState("");
  const [laycanFrom, setLaycanFrom] = useState("");
  const [laycanTo, setLaycanTo] = useState("");
  const [commission, setCommission] = useState("2.5");
  const [freightRate, setFreightRate] = useState("");
  const [cargoQty, setCargoQty] = useState("");
  const [clausesNotes, setClausesNotes] = useState("");
  const [liftPeriod, setLiftPeriod] = useState("2026-Q4");
  const [liftQty, setLiftQty] = useState("50000");
  const [open, setOpen] = useState<Charter | null>(null);
  const [edit, setEdit] = useState({
    charter_type: "voyage",
    vessel_id: "",
    counterparty_id: "",
    laycan_from: "",
    laycan_to: "",
    commission_pct: "2.5",
    freight_rate: "",
    cargo_qty: "",
    notes: "",
  });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const [c, v, p] = await Promise.all([
      apiGet("/api/v1/charters"),
      apiGet("/api/v1/masterdata/vessels"),
      apiGet("/api/v1/masterdata/counterparties"),
    ]);
    setRows(c);
    setVessels(v);
    setParties(p);
    if (!vesselId && v[0]?.id) setVesselId(v[0].id);
    if (!partyId && p[0]?.id) setPartyId(p[0].id);
  }, [vesselId, partyId]);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const freight_terms: Record<string, number | string> = {};
      if (freightRate !== "") freight_terms.freight_rate = Number(freightRate);
      if (cargoQty !== "") {
        freight_terms.cargo_qty = Number(cargoQty);
        freight_terms.cargo = `Bulk ${cargoQty} mt`;
      }
      const cp = await apiPost("/api/v1/charters", {
        charter_type: charterType,
        vessel_id: vesselId || null,
        counterparty_id: partyId || null,
        laycan_from: laycanFrom || null,
        laycan_to: laycanTo || null,
        commission_pct: commission === "" ? null : Number(commission),
        freight_terms,
        clauses: clausesNotes ? { notes: clausesNotes } : {},
      });
      setMsg(t("page.charters.created", "Created {no}", { no: cp.charter_no }));
      setFreightRate("");
      setCargoQty("");
      setClausesNotes("");
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function move(id: string, target: string) {
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/charters/${id}/transition`, { target });
      setMsg(t("page.charters.moved", "Moved to {target}", { target }));
      await load();
    } catch (ex: any) {
      const code = ex?.detail?.code || "";
      if (code === "WORKFLOW_REQUIRED" || String(ex?.message || "").includes("workflow")) {
        setErr(
          t(
            "page.charters.workflow_required",
            "Approval required via workflow inbox — open Approvals, or activate as tenant admin.",
          ),
        );
      } else if (code === "SANCTIONS_BLOCKED") {
        setErr(t("page.charters.sanctions_block", "Cannot activate — counterparty sanctions blocked."));
      } else {
        setErr(ex?.message || String(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  async function addLifting(id: string) {
    setBusy(true);
    setErr("");
    try {
      const q = new URLSearchParams({
        period_label: liftPeriod,
        planned_qty: String(Number(liftQty) || 0),
      });
      const res = await apiPost(`/api/v1/charters/${id}/liftings?${q.toString()}`);
      setMsg(t("page.charters.lifting_ok", "Lifting added: {period}", { period: res.period_label }));
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  function vesselName(id: string | null) {
    if (!id) return "—";
    return vessels.find((v) => v.id === id)?.name || id.slice(0, 8);
  }

  function partyName(id: string | null) {
    if (!id) return "—";
    return parties.find((p) => p.id === id)?.name || id.slice(0, 8);
  }

  function openRow(r: Charter) {
    const ft = r.freight_terms || {};
    setOpen(r);
    setEdit({
      charter_type: r.charter_type,
      vessel_id: r.vessel_id || "",
      counterparty_id: r.counterparty_id || "",
      laycan_from: r.laycan_from || "",
      laycan_to: r.laycan_to || "",
      commission_pct: r.commission_pct != null ? String(r.commission_pct) : "",
      freight_rate: ft.freight_rate != null ? String(ft.freight_rate) : "",
      cargo_qty: ft.cargo_qty != null ? String(ft.cargo_qty) : "",
      notes: typeof (r.clauses || {}).notes === "string" ? String((r.clauses as any).notes) : "",
    });
  }

  async function saveCharter() {
    if (!open) return;
    setSaving(true);
    setErr("");
    try {
      const freight_terms: Record<string, number | string> = {
        ...((open.freight_terms || {}) as Record<string, number | string>),
      };
      if (edit.freight_rate !== "") freight_terms.freight_rate = Number(edit.freight_rate);
      if (edit.cargo_qty !== "") {
        freight_terms.cargo_qty = Number(edit.cargo_qty);
        freight_terms.cargo = `Bulk ${edit.cargo_qty} mt`;
      }
      await apiPatch(`/api/v1/charters/${open.id}`, {
        charter_type: edit.charter_type,
        vessel_id: edit.vessel_id || null,
        counterparty_id: edit.counterparty_id || null,
        clear_vessel: !edit.vessel_id,
        clear_counterparty: !edit.counterparty_id,
        laycan_from: edit.laycan_from || null,
        laycan_to: edit.laycan_to || null,
        commission_pct: edit.commission_pct === "" ? null : Number(edit.commission_pct),
        freight_terms,
        clauses: edit.notes ? { notes: edit.notes } : {},
      });
      setMsg(t("common.saved", "已保存"));
      setOpen(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  async function removeCharter() {
    if (!open) return;
    setSaving(true);
    try {
      await apiDelete(`/api/v1/charters/${open.id}`);
      setMsg(t("common.recycled", "已移入回收站"));
      setOpen(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.charters.title", "租约工作台")}</h1>
          <p className="page-sub">
            {t("page.charters.sub", "新建租约；点击行打开弹窗编辑、删除或推进状态。")}
          </p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "回收站")}
        </Link>
      </div>

      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <form className="panel" onSubmit={create}>
        <h3 style={{ marginTop: 0 }}>{t("page.charters.create", "New charter")}</h3>
        <div className="form-grid">
          <label>
            {t("page.charters.type", "Charter type")}
            <select value={charterType} onChange={(e) => setCharterType(e.target.value)}>
              <option value="voyage">voyage</option>
              <option value="tct">tct</option>
              <option value="coa">coa</option>
              <option value="bb">bb</option>
            </select>
          </label>
          <label>
            {t("page.estimates.vessel", "Vessel")}
            <select value={vesselId} onChange={(e) => setVesselId(e.target.value)}>
              <option value="">{t("common.select", "Select…")}</option>
              {vessels.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.estimates.counterparty", "Counterparty")}
            <select value={partyId} onChange={(e) => setPartyId(e.target.value)}>
              <option value="">{t("common.select", "Select…")}</option>
              {parties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.charters.laycan_from", "Laycan from")}
            <input type="date" value={laycanFrom} onChange={(e) => setLaycanFrom(e.target.value)} />
          </label>
          <label>
            {t("page.charters.laycan_to", "Laycan to")}
            <input type="date" value={laycanTo} onChange={(e) => setLaycanTo(e.target.value)} />
          </label>
          <label>
            {t("page.estimates.commission", "Commission %")}
            <input type="number" step="any" value={commission} onChange={(e) => setCommission(e.target.value)} />
          </label>
          <label>
            {t("page.estimates.freight_rate", "Freight rate")}
            <input type="number" step="any" value={freightRate} onChange={(e) => setFreightRate(e.target.value)} />
          </label>
          <label>
            {t("page.estimates.cargo_qty", "Cargo qty")}
            <input type="number" step="any" value={cargoQty} onChange={(e) => setCargoQty(e.target.value)} />
          </label>
          <label style={{ gridColumn: "1 / -1" }}>
            {t("page.charters.clauses", "Clauses / notes")}
            <input value={clausesNotes} onChange={(e) => setClausesNotes(e.target.value)} placeholder="CP notes" />
          </label>
        </div>
        <div className="desk-toolbar">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {t("common.create", "Create")}
          </button>
        </div>
      </form>

      {charterType === "coa" || rows.some((r) => r.charter_type === "coa") ? (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{t("page.charters.lifting_form", "COA lifting defaults")}</h3>
          <div className="form-grid">
            <label>
              {t("page.charters.period", "Period label")}
              <input value={liftPeriod} onChange={(e) => setLiftPeriod(e.target.value)} />
            </label>
            <label>
              {t("page.charters.planned_qty", "Planned qty")}
              <input type="number" step="any" value={liftQty} onChange={(e) => setLiftQty(e.target.value)} />
            </label>
          </div>
        </div>
      ) : null}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.charters.list", "Fixtures")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.charters.no", "编号")}</th>
              <th>{t("common.type", "类型")}</th>
              <th>{t("common.status", "状态")}</th>
              <th>{t("page.estimates.vessel", "船舶")}</th>
              <th>{t("page.estimates.counterparty", "对手方")}</th>
              <th>{t("page.charters.sanctions", "制裁")}</th>
              <th>{t("page.charters.estimate", "估算")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                <td>{r.charter_no}</td>
                <td>{r.charter_type}</td>
                <td>{r.status}</td>
                <td>{vesselName(r.vessel_id)}</td>
                <td>{partyName(r.counterparty_id)}</td>
                <td>
                  {r.sanctions_blocked ? (
                    <span className="badge badge-fail">{t("page.charters.blocked", "BLOCKED")}</span>
                  ) : (
                    <span className="badge badge-pass">{t("page.charters.clear", "clear")}</span>
                  )}
                </td>
                <td>
                  {r.estimate_id ? (
                    <Link href="/estimates" onClick={(e) => e.stopPropagation()}>
                      {r.estimate_id.slice(0, 8)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
            {!rows.length ? (
              <tr>
                <td colSpan={7} className="muted">
                  {t("common.empty", "暂无记录")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={open ? `${t("page.charters.edit", "编辑租约")} · ${open.charter_no}` : ""}
        onClose={() => setOpen(null)}
        onSave={saveCharter}
        onDelete={removeCharter}
        saving={saving || busy}
      >
        <p className="muted">
          {t("common.status", "状态")}: {open?.status}
        </p>
        <label>
          {t("page.charters.type", "类型")}
          <select value={edit.charter_type} onChange={(e) => setEdit({ ...edit, charter_type: e.target.value })}>
            <option value="voyage">voyage</option>
            <option value="tct">tct</option>
            <option value="coa">coa</option>
            <option value="bb">bb</option>
          </select>
        </label>
        <label>
          {t("page.estimates.vessel", "船舶")}
          <select value={edit.vessel_id} onChange={(e) => setEdit({ ...edit, vessel_id: e.target.value })}>
            <option value="">—</option>
            {vessels.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("page.estimates.counterparty", "对手方")}
          <select value={edit.counterparty_id} onChange={(e) => setEdit({ ...edit, counterparty_id: e.target.value })}>
            <option value="">—</option>
            {parties.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Laycan from
          <input type="date" value={edit.laycan_from} onChange={(e) => setEdit({ ...edit, laycan_from: e.target.value })} />
        </label>
        <label>
          Laycan to
          <input type="date" value={edit.laycan_to} onChange={(e) => setEdit({ ...edit, laycan_to: e.target.value })} />
        </label>
        <label>
          {t("page.estimates.commission", "佣金 %")}
          <input value={edit.commission_pct} onChange={(e) => setEdit({ ...edit, commission_pct: e.target.value })} />
        </label>
        <label>
          {t("page.estimates.freight_rate", "运价")}
          <input value={edit.freight_rate} onChange={(e) => setEdit({ ...edit, freight_rate: e.target.value })} />
        </label>
        <label>
          {t("page.estimates.cargo_qty", "货量")}
          <input value={edit.cargo_qty} onChange={(e) => setEdit({ ...edit, cargo_qty: e.target.value })} />
        </label>
        <label>
          {t("page.charters.notes", "条款备注")}
          <input value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} />
        </label>
        <div className="desk-toolbar" style={{ marginTop: "0.5rem" }}>
          {open?.status === "draft" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => open && move(open.id, "pending_approval").then(() => setOpen(null))}>
              {t("common.submit", "提交审批")}
            </button>
          ) : null}
          {open?.status === "pending_approval" ? (
            <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => open && move(open.id, "active").then(() => setOpen(null))}>
              {t("common.activate", "激活")}
            </button>
          ) : null}
          {open?.status === "active" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => open && move(open.id, "completed").then(() => setOpen(null))}>
              {t("page.charters.complete", "完成")}
            </button>
          ) : null}
          {open?.charter_type === "coa" ? (
            <button className="btn btn-sm" type="button" disabled={busy} onClick={() => open && addLifting(open.id)}>
              {t("page.charters.add_lifting", "添加 lifting")}
            </button>
          ) : null}
        </div>
      </RecordModal>
    </AppShell>
  );
}
