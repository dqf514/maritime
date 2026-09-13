"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { LookupSelect } from "@/components/LookupSelect";
import { RecordModal } from "@/components/RecordModal";
import { apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Ref = { id: string; name: string; voyage_no?: string };
type Order = {
  id: string;
  order_no: string;
  status: string;
  vessel_id: string | null;
  voyage_id: string | null;
  grade: string;
  qty_ordered: number;
  qty_delivered: number | null;
  unit_price: number;
  rob_before: number | null;
  rob_after: number | null;
  amount: number;
  currency: string;
};

export default function BunkerDeskPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Order[]>([]);
  const [vessels, setVessels] = useState<Ref[]>([]);
  const [voyages, setVoyages] = useState<Ref[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Order | null>(null);
  const [form, setForm] = useState({
    vessel_id: "",
    voyage_id: "",
    grade: "VLSFO",
    qty_ordered: "100",
    unit_price: "550",
    rob_before: "200",
  });
  const [deliverQty, setDeliverQty] = useState("");
  const [consumption, setConsumption] = useState("");

  const load = useCallback(async () => {
    const [b, v, voy] = await Promise.all([
      apiGet("/api/v1/bunker-orders"),
      apiGet("/api/v1/masterdata/vessels").catch(() => []),
      apiGet("/api/v1/voyages").catch(() => []),
    ]);
    setRows(b);
    setVessels(v);
    setVoyages(voy);
  }, []);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
  }, [load, t]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await apiPost("/api/v1/bunker-orders", {
        vessel_id: form.vessel_id || null,
        voyage_id: form.voyage_id || null,
        grade: form.grade,
        qty_ordered: Number(form.qty_ordered) || 0,
        unit_price: Number(form.unit_price) || 0,
        rob_before: form.rob_before === "" ? null : Number(form.rob_before),
      });
      setMsg(t("page.bunker.created", "Bunker order created"));
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
      const q = new URLSearchParams({ target });
      if (deliverQty) q.set("qty_delivered", deliverQty);
      if (consumption) q.set("consumption", consumption);
      await apiPost(`/api/v1/bunker-orders/${id}/transition?${q.toString()}`);
      setMsg(t("page.bunker.moved", "Status → {target}", { target }));
      setOpen(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!open) return;
    setBusy(true);
    try {
      await apiPatch(`/api/v1/bunker-orders/${open.id}`, {
        grade: form.grade,
        qty_ordered: Number(form.qty_ordered) || 0,
        unit_price: Number(form.unit_price) || 0,
        rob_before: form.rob_before === "" ? null : Number(form.rob_before),
        vessel_id: form.vessel_id || null,
        voyage_id: form.voyage_id || null,
      });
      setMsg(t("common.saved", "Saved"));
      setOpen(null);
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  function openRow(r: Order) {
    setOpen(r);
    setForm({
      vessel_id: r.vessel_id || "",
      voyage_id: r.voyage_id || "",
      grade: r.grade,
      qty_ordered: String(r.qty_ordered),
      unit_price: String(r.unit_price),
      rob_before: r.rob_before != null ? String(r.rob_before) : "",
    });
    setDeliverQty(r.qty_delivered != null ? String(r.qty_delivered) : String(r.qty_ordered));
    setConsumption("");
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.bunker.title", "Bunker desk")}</h1>
          <p className="page-sub">{t("page.bunker.sub", "Stem, delivery and ROB. Price feeds live in Integration Hub.")}</p>
        </div>
        <Link href="/settings/connectors" className="btn btn-ghost">
          {t("page.connectors.title", "Integration Hub")}
        </Link>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <form className="panel" onSubmit={create}>
        <div className="form-grid">
          <label>
            {t("page.estimates.vessel", "Vessel")}
            <select value={form.vessel_id} onChange={(e) => setForm({ ...form, vessel_id: e.target.value })}>
              <option value="">—</option>
              {vessels.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.voyages.list", "Voyages")}
            <select value={form.voyage_id} onChange={(e) => setForm({ ...form, voyage_id: e.target.value })}>
              <option value="">—</option>
              {voyages.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.voyage_no || v.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("page.bunker.grade", "Grade")}
            <LookupSelect
              dataset="fuel_grades"
              value={form.grade}
              onChange={(v) => setForm({ ...form, grade: v })}
              allowEmpty={false}
            />
          </label>
          <label>
            {t("page.bunker.qty", "Ordered qty (mt)")}
            <input value={form.qty_ordered} onChange={(e) => setForm({ ...form, qty_ordered: e.target.value })} />
          </label>
          <label>
            {t("page.bunker.price", "Unit price")}
            <input value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
          </label>
          <label>
            ROB before
            <input value={form.rob_before} onChange={(e) => setForm({ ...form, rob_before: e.target.value })} />
          </label>
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {t("page.bunker.create", "Create bunker order")}
        </button>
      </form>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.finance.number", "No.")}</th>
              <th>{t("page.bunker.grade", "Grade")}</th>
              <th>{t("common.status", "Status")}</th>
              <th>{t("page.bunker.qty", "Ordered qty (mt)")}</th>
              <th>{t("common.amount", "Amount")}</th>
              <th>ROB</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="row-openable" onClick={() => openRow(r)}>
                <td>{r.order_no}</td>
                <td>{r.grade}</td>
                <td>{r.status}</td>
                <td>{r.qty_ordered}</td>
                <td>{r.amount.toLocaleString()}</td>
                <td>
                  {r.rob_before ?? "—"} → {r.rob_after ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <RecordModal
        open={Boolean(open)}
        title={open ? `${t("page.bunker.edit", "Edit bunker order")} · ${open.order_no}` : ""}
        onClose={() => setOpen(null)}
        onSave={save}
        canDelete={false}
        saving={busy}
      >
        <p className="muted">
          {t("common.status", "Status")}: {open?.status}
        </p>
        <label>
          {t("page.bunker.grade", "Grade")}
          <LookupSelect
            dataset="fuel_grades"
            value={form.grade}
            onChange={(v) => setForm({ ...form, grade: v })}
            allowEmpty={false}
          />
        </label>
        <label>
          {t("page.bunker.qty", "Ordered qty (mt)")}
          <input value={form.qty_ordered} onChange={(e) => setForm({ ...form, qty_ordered: e.target.value })} />
        </label>
        <label>
          {t("page.bunker.price", "Unit price")}
          <input value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
        </label>
        <label>
          {t("page.bunker.deliver_qty", "Delivered qty")}
          <input value={deliverQty} onChange={(e) => setDeliverQty(e.target.value)} />
        </label>
        <label>
          {t("page.bunker.consumption", "Consumption")}
          <input value={consumption} onChange={(e) => setConsumption(e.target.value)} />
        </label>
        <div className="desk-toolbar">
          {open?.status === "planned" ? (
            <button type="button" className="btn btn-sm" onClick={() => open && move(open.id, "inquiry")}>
              {t("page.bunker.inquiry", "Inquiry")}
            </button>
          ) : null}
          {open?.status === "inquiry" ? (
            <button type="button" className="btn btn-sm" onClick={() => open && move(open.id, "ordered")}>
              {t("page.bunker.order", "Place order")}
            </button>
          ) : null}
          {open?.status === "ordered" ? (
            <button type="button" className="btn btn-primary btn-sm" onClick={() => open && move(open.id, "delivered")}>
              {t("page.bunker.confirm_delivery", "Confirm delivery")}
            </button>
          ) : null}
          {open?.status === "delivered" ? (
            <button type="button" className="btn btn-sm" onClick={() => open && move(open.id, "closed")}>
              {t("common.close", "Close")}
            </button>
          ) : null}
        </div>
      </RecordModal>
    </AppShell>
  );
}
