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
    index_symbol: "",
    price_differential: "",
  });
  const [deliverQty, setDeliverQty] = useState("");
  const [bdnQty, setBdnQty] = useState("");
  const [consumption, setConsumption] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [inquiries, setInquiries] = useState<Array<{ id: string; supplier: string; quoted_price: number; status: string }>>([]);
  const [inqSupplier, setInqSupplier] = useState("");
  const [inqPrice, setInqPrice] = useState("");
  const [alloc, setAlloc] = useState<Record<string, unknown> | null>(null);

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
      const useIndex = form.index_symbol.trim() !== "";
      await apiPost("/api/v1/bunker-orders", {
        vessel_id: form.vessel_id || null,
        voyage_id: form.voyage_id || null,
        grade: form.grade,
        qty_ordered: Number(form.qty_ordered) || 0,
        ...(useIndex
          ? { index_symbol: form.index_symbol.trim(), price_differential: Number(form.price_differential) || 0 }
          : { unit_price: Number(form.unit_price) || 0 }),
        rob_before: form.rob_before === "" ? null : Number(form.rob_before),
      });
      setMsg(t("page.bunker.created", "Bunker order created"));
      await load();
    } catch (ex: any) {
      if (ex?.status === 422 && ex?.detail?.code === "NO_INDEX_QUOTE") {
        setErr(t("page.bunker.no_index_quote", "该指数暂无市场报价（NO_INDEX_QUOTE），请先在 Integration Hub 配置报价或改用固定单价"));
      } else {
        setErr(String(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  async function loadInquiries(orderId: string) {
    const rows: Array<{ id: string; supplier: string; quoted_price: number; status: string }> = await apiGet(
      `/api/v1/bunker-orders/${orderId}/inquiries`,
    ).catch(() => []);
    setInquiries(Array.isArray(rows) ? rows : []);
  }

  async function addInquiry() {
    if (!open) return;
    if (!inqSupplier.trim() || inqPrice === "") {
      setErr(t("page.bunker.inq_need", "请填写供应商与报价"));
      return;
    }
    setBusy(true);
    setErr("");
    try {
      await apiPost(`/api/v1/bunker-orders/${open.id}/inquiries`, {
        supplier: inqSupplier.trim(),
        quoted_price: Number(inqPrice),
      });
      await loadInquiries(open.id);
      setInqSupplier("");
      setInqPrice("");
      setMsg(t("page.bunker.inq_ok", "报价已登记"));
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function acceptInquiry(id: string) {
    if (!open) return;
    setBusy(true);
    setErr("");
    try {
      const res = await apiPost(`/api/v1/bunker-inquiries/${id}/accept`);
      await loadInquiries(open.id);
      setOpen({ ...open, unit_price: res.unit_price });
      setForm((f) => ({ ...f, unit_price: String(res.unit_price) }));
      setMsg(t("page.bunker.inq_accepted", "已采纳报价并回写订单价格"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function loadAllocation() {
    if (!open?.voyage_id) return;
    setBusy(true);
    setErr("");
    try {
      setAlloc(await apiGet(`/api/v1/voyages/${open.voyage_id}/bunker-allocation`));
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function move(id: string, target: string) {
    setBusy(true);
    setWarnings([]);
    try {
      const q = new URLSearchParams({ target });
      if (deliverQty) q.set("qty_delivered", deliverQty);
      if (target === "delivered" && bdnQty) q.set("bdn_qty", bdnQty);
      if (consumption) q.set("consumption", consumption);
      const res = await apiPost(`/api/v1/bunker-orders/${id}/transition?${q.toString()}`);
      if (Array.isArray(res?.warnings) && res.warnings.length) setWarnings(res.warnings.map((w: unknown) => String(w)));
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
      index_symbol: "",
      price_differential: "",
    });
    setDeliverQty(r.qty_delivered != null ? String(r.qty_delivered) : String(r.qty_ordered));
    setBdnQty("");
    setConsumption("");
    setWarnings([]);
    setInquiries([]);
    setInqSupplier("");
    setInqPrice("");
    setAlloc(null);
    loadInquiries(r.id).catch(() => undefined);
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
      {warnings.length ? (
        <div className="panel" style={{ borderColor: "var(--warn)" }}>
          {warnings.map((w, i) => (
            <p key={i} style={{ color: "var(--warn)", fontWeight: 600, margin: "0.25rem 0" }}>
              {w}
            </p>
          ))}
        </div>
      ) : null}

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
            {t("page.bunker.index_symbol", "Index symbol")}
            <input value={form.index_symbol} onChange={(e) => setForm({ ...form, index_symbol: e.target.value })} placeholder="SIN380 (可选)" />
          </label>
          {form.index_symbol.trim() !== "" ? (
            <label>
              {t("page.bunker.price_diff", "Price differential")}
              <input value={form.price_differential} onChange={(e) => setForm({ ...form, price_differential: e.target.value })} placeholder="+12" />
            </label>
          ) : (
            <label>
              {t("page.bunker.price", "Unit price")}
              <input value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
            </label>
          )}
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
          {t("page.bunker.bdn_qty", "BDN qty")}
          <input value={bdnQty} onChange={(e) => setBdnQty(e.target.value)} placeholder={t("common.optional", "Optional")} />
        </label>
        <label>
          {t("page.bunker.consumption", "Consumption")}
          <input value={consumption} onChange={(e) => setConsumption(e.target.value)} />
        </label>
        <div className="desk-section" style={{ margin: "0.5rem 0" }}>
          <h3 style={{ marginTop: 0 }}>{t("page.bunker.inquiries", "询比价 Inquiries")}</h3>
          {inquiries.length ? (
            <table className="table">
              <tbody>
                {inquiries.map((q) => (
                  <tr key={q.id}>
                    <td>{q.supplier}</td>
                    <td>{q.quoted_price.toLocaleString()}</td>
                    <td>
                      <span className={`badge ${q.status === "accepted" ? "badge-pass" : q.status === "rejected" ? "badge-fail" : "badge-warn"}`}>
                        {q.status}
                      </span>
                    </td>
                    <td>
                      {q.status === "quoted" ? (
                        <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => acceptInquiry(q.id)}>
                          {t("page.bunker.accept", "采纳")}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted" style={{ margin: 0 }}>{t("page.bunker.no_inquiries", "暂无报价")}</p>
          )}
          <div className="form-grid" style={{ marginTop: "0.5rem" }}>
            <label>
              {t("page.bunker.supplier", "Supplier")}
              <input value={inqSupplier} onChange={(e) => setInqSupplier(e.target.value)} />
            </label>
            <label>
              {t("page.bunker.quoted_price", "Quoted price")}
              <input type="number" step="any" value={inqPrice} onChange={(e) => setInqPrice(e.target.value)} />
            </label>
            <div style={{ display: "flex", alignItems: "end" }}>
              <button className="btn btn-sm" type="button" disabled={busy} onClick={addInquiry}>
                {t("page.bunker.add_inquiry", "登记报价")}
              </button>
            </div>
          </div>
        </div>
        {open?.voyage_id ? (
          <div className="desk-section" style={{ margin: "0.5rem 0" }}>
            <div className="desk-toolbar" style={{ margin: 0 }}>
              <h3 style={{ margin: 0, fontSize: "0.95rem" }}>{t("page.bunker.allocation", "航次分摊估算")}</h3>
              <button className="btn btn-sm" type="button" disabled={busy} onClick={loadAllocation}>
                {t("page.bunker.alloc_run", "查询分摊")}
              </button>
            </div>
            {alloc ? (
              <div className="desk-results" style={{ marginTop: "0.5rem" }}>
                <div className="kv-box">
                  <span>{t("page.bunker.alloc_consumption", "Consumption mt")}</span>
                  <strong>{String(alloc.consumption_mt ?? "—")}</strong>
                </div>
                <div className="kv-box">
                  <span>{t("page.bunker.alloc_wavg", "Weighted avg price")}</span>
                  <strong>{alloc.weighted_avg_price != null ? String(alloc.weighted_avg_price) : "—"}</strong>
                </div>
                <div className="kv-box">
                  <span>{t("page.bunker.alloc_amount", "Allocated amount")}</span>
                  <strong>
                    {alloc.allocated_amount != null ? `${String(alloc.allocated_amount)} ${String(alloc.currency || "")}` : "—"}
                  </strong>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
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
