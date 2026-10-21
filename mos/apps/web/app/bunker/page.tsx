"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { BunkerRequirementsPanel } from "@/components/BunkerRequirementsPanel";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { PartyPicker } from "@/components/DataPicker";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid";
import { LookupSelect } from "@/components/LookupSelect";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RecordModal } from "@/components/RecordModal";
import { RowActions } from "@/components/RowActions";
import { StatusLegend } from "@/components/StatusLegend";
import { Toolbar } from "@/components/Toolbar";
import { useListHotkeys } from "@/components/useListHotkeys";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

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
  updated_at?: string | null;
};

type Inquiry = { id: string; supplier: string; quoted_price: number; status: string; updated_at?: string | null };

const EMPTY_FORM = {
  vessel_id: "",
  voyage_id: "",
  grade: "VLSFO",
  qty_ordered: "100",
  unit_price: "550",
  rob_before: "200",
  index_symbol: "",
  price_differential: "",
};

export default function BunkerDeskPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Order[]>([]);
  const [vessels, setVessels] = useState<Ref[]>([]);
  const [voyages, setVoyages] = useState<Ref[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Order | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [deliverQty, setDeliverQty] = useState("");
  const [bdnQty, setBdnQty] = useState("");
  const [consumption, setConsumption] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [inquiries, setInquiries] = useState<Inquiry[]>([]);
  const [inqSupplier, setInqSupplier] = useState("");
  const [inqPrice, setInqPrice] = useState("");
  const [alloc, setAlloc] = useState<Record<string, unknown> | null>(null);

  useListHotkeys(openCreate);

  const orderCtx = useContextMenu<Order>();
  const inqCtx = useContextMenu<Inquiry>();

  function exportOrders(selected: Order[]) {
    downloadCsv(
      "bunker-orders",
      ["id", "order_no", "status", "grade", "qty_ordered", "qty_delivered", "unit_price", "amount", "currency", "rob_before", "rob_after"],
      selected.map((r) => [
        r.id,
        r.order_no,
        r.status,
        r.grade,
        r.qty_ordered,
        r.qty_delivered ?? "",
        r.unit_price,
        r.amount,
        r.currency,
        r.rob_before ?? "",
        r.rob_after ?? "",
      ]),
    );
  }

  function orderMenuItems(target: Order): ContextMenuItem[] {
    return [
      { key: "open", label: t("common.open", "Open"), onClick: () => openRow(target) },
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportOrders([target]) },
      { key: "div", divider: true, label: "" },
      ...(target.status === "planned"
        ? [{ key: "inq", label: t("page.bunker.inquiry", "Inquiry"), onClick: () => move(target.id, "inquiry") } as ContextMenuItem]
        : []),
      ...(target.status === "inquiry"
        ? [{ key: "ord", label: t("page.bunker.order", "Place order"), onClick: () => move(target.id, "ordered") } as ContextMenuItem]
        : []),
      ...(target.status === "ordered"
        ? [{ key: "del", label: t("page.bunker.confirm_delivery", "Confirm delivery"), onClick: () => move(target.id, "delivered") } as ContextMenuItem]
        : []),
      ...(target.status === "delivered"
        ? [{ key: "close", label: t("common.close", "Close"), onClick: () => move(target.id, "closed") } as ContextMenuItem]
        : []),
    ];
  }

  function inqMenuItems(target: Inquiry): ContextMenuItem[] {
    return [
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      ...(target.status === "quoted"
        ? [{ key: "accept", label: t("page.bunker.accept", "Accept"), onClick: () => acceptInquiry(target.id) } as ContextMenuItem]
        : []),
    ];
  }

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

  function openCreate() {
    setCreating(true);
    setOpen(null);
    setForm({ ...EMPTY_FORM });
    setDeliverQty("");
    setBdnQty("");
    setConsumption("");
    setWarnings([]);
    setInquiries([]);
    setInqSupplier("");
    setInqPrice("");
    setAlloc(null);
    setErr("");
  }

  function closeModal() {
    setOpen(null);
    setCreating(false);
  }

  async function loadInquiries(orderId: string) {
    const rows: Inquiry[] = await apiGet(`/api/v1/bunker-orders/${orderId}/inquiries`).catch(() => []);
    setInquiries(Array.isArray(rows) ? rows : []);
  }

  async function addInquiry() {
    if (!open) return;
    if (!inqSupplier.trim() || inqPrice === "") {
      setErr(t("page.bunker.inq_need", "Enter supplier and quote"));
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
      toast.success(t("page.bunker.inq_ok", "Quote logged"));
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
      toast.success(t("page.bunker.inq_accepted", "Quote accepted and order price updated"));
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
      toast.success(t("page.bunker.moved", "Status → {target}", { target }));
      closeModal();
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setErr("");
    try {
      if (creating || !open) {
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
        toast.success(t("page.bunker.created", "Bunker order created"));
        closeModal();
      } else {
        if (orderLocked(open)) {
          toast.error(t("page.bunker.order_locked", "Delivered/closed orders cannot be edited or deleted"));
          return;
        }
        await apiPatch(`/api/v1/bunker-orders/${open.id}`, {
          grade: form.grade,
          qty_ordered: Number(form.qty_ordered) || 0,
          unit_price: Number(form.unit_price) || 0,
          rob_before: form.rob_before === "" ? null : Number(form.rob_before),
          vessel_id: form.vessel_id || null,
          voyage_id: form.voyage_id || null,
        });
        toast.success(t("common.saved", "Saved"));
        closeModal();
      }
      await load();
    } catch (ex: any) {
      if (ex?.status === 422 && ex?.detail?.code === "NO_INDEX_QUOTE") {
        setErr(t("page.bunker.no_index_quote", "No market quote for this index (NO_INDEX_QUOTE). Configure pricing in Integration Hub or use a fixed unit price."));
      } else {
        setErr(String(ex));
      }
    } finally {
      setBusy(false);
    }
  }

  function openRow(r: Order) {
    setCreating(false);
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

  function orderLocked(r: Order) {
    return r.status === "delivered" || r.status === "closed";
  }

  async function deleteOrder(id: string) {
    try {
      await apiDelete(`/api/v1/bunker-orders/${id}`);
      toast.success(t("common.recycled", "Moved to recycle bin"));
      closeModal();
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  // ── 行内编辑（失焦/回车保存；值未变化不发请求，避免 blur→reload 打断输入） ──
  async function onOrderCellSave(rowId: string, colKey: string, value: unknown, row: Order) {
    if (orderLocked(row)) {
      toast.error(t("page.bunker.order_locked", "Delivered/closed orders cannot be edited or deleted"));
      return;
    }
    const numFields = ["qty_ordered", "unit_price", "rob_before"];
    let payload: Record<string, unknown>;
    if (numFields.includes(colKey)) {
      const n = Number(value);
      if (value === null || value === "" || isNaN(n)) return;
      const prev = Number((row as unknown as Record<string, unknown>)[colKey]);
      if (n === prev) return;
      payload = { [colKey]: n };
    } else {
      if (((row as unknown as Record<string, unknown>)[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    }
    try {
      await apiPatch(`/api/v1/bunker-orders/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  const columns: ColumnDef<Order>[] = [
    { key: "order_no", title: t("page.finance.number", "No."), width: 130, value: (r) => r.order_no },
    { key: "grade", title: t("page.bunker.grade", "Grade"), width: 110, value: (r) => r.grade, editor: { type: "text" } },
    { key: "status", title: t("common.status", "Status"), width: 110, value: (r) => r.status },
    {
      key: "qty_ordered",
      title: t("page.bunker.qty", "Ordered qty (mt)"),
      width: 130,
      align: "right",
      value: (r) => r.qty_ordered,
      render: (v) => <Num v={v as number} digits={2} />,
      editor: { type: "number", min: 0 },
    },
    {
      key: "unit_price",
      title: t("page.bunker.price", "Unit price"),
      width: 110,
      align: "right",
      value: (r) => r.unit_price,
      render: (v) => <Num v={v as number} digits={2} />,
      editor: { type: "number", min: 0 },
    },
    {
      key: "amount",
      title: t("common.amount", "Amount"),
      width: 120,
      align: "right",
      value: (r) => r.amount,
      render: (v) => <Num v={v as number} digits={2} />,
    },
    {
      key: "rob_before",
      title: t("page.bunker.rob_before", "ROB before"),
      width: 110,
      align: "right",
      value: (r) => r.rob_before,
      render: (v) => <Num v={v as number | null} digits={2} />,
      editor: { type: "number", min: 0 },
    },
    {
      key: "rob_after",
      title: t("page.bunker.rob_after", "ROB after"),
      width: 110,
      align: "right",
      value: (r) => r.rob_after,
      render: (v) => <Num v={v as number | null} digits={2} />,
    },
    {
      key: "updated_at",
      title: t("list.last_modified", "Last modified"),
      width: 135,
      value: (r) => r.updated_at ?? null,
      render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
    },
    {
      key: "_actions",
      title: "",
      width: 64,
      align: "center",
      render: (_v, r) => (
        <span title={orderLocked(r) ? t("page.bunker.order_locked", "Delivered/closed orders cannot be edited or deleted") : undefined}>
          <RowActions
            onEdit={() => openRow(r)}
            onDelete={() => deleteOrder(r.id)}
            canEdit={!orderLocked(r)}
            canDelete={!orderLocked(r)}
            label={r.order_no}
          />
        </span>
      ),
    },
  ];

  const inquiryColumns: ColumnDef<Inquiry>[] = [
    { key: "supplier", title: t("page.bunker.supplier", "Supplier"), minWidth: 120, value: (r) => r.supplier },
    {
      key: "quoted_price",
      title: t("page.bunker.quoted_price", "Quoted price"),
      width: 110,
      align: "right",
      value: (r) => r.quoted_price,
      render: (v) => <Num v={v as number} digits={2} />,
    },
    {
      key: "status",
      title: t("common.status", "Status"),
      width: 100,
      value: (r) => r.status,
      render: (_v, r) => (
        <span className={`badge ${r.status === "accepted" ? "badge-pass" : r.status === "rejected" ? "badge-fail" : "badge-warn"}`}>
          {r.status}
        </span>
      ),
    },
    {
      key: "updated_at",
      title: t("list.last_modified", "Last modified"),
      width: 135,
      value: (r) => r.updated_at ?? null,
      render: (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—"),
    },
    {
      key: "actions",
      title: "",
      width: 90,
      render: (_v, r) =>
        r.status === "quoted" ? (
          <button
            className="btn btn-primary btn-sm"
            type="button"
            disabled={busy}
            onClick={(e) => {
              e.stopPropagation();
              acceptInquiry(r.id);
            }}
          >
            {t("page.bunker.accept", "Accept")}
          </button>
        ) : null,
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.bunker", "Bunker desk") }]}
        title={t("page.bunker.title", "Bunker desk")}
        subtitle={t("page.bunker.sub", "Stem, delivery and ROB. Price feeds live in Integration Hub.")}
      />
      <Toolbar>
        <button type="button" className="btn btn-primary btn-sm" onClick={openCreate}>
          {t("page.bunker.create", "Create bunker order")}
        </button>
        <Link href="/settings/connectors" className="btn btn-ghost btn-sm">
          {t("page.connectors.title", "Integration Hub")}
        </Link>
      </Toolbar>
      {err ? <p className="flash-err">{err}</p> : null}
      {warnings.length ? (
        <div className="panel panel-warn">
          {warnings.map((w, i) => (
            <p key={i} className="flash-warn">
              {w}
            </p>
          ))}
        </div>
      ) : null}

      <div className="panel panel-gap-top">
        <StatusLegend statuses={["planned", "inquiry", "ordered", "delivered", "closed"]} />
        <DataGrid<Order>
          columns={columns}
          data={rows}
          rowKey={(r) => r.id}
          editable
          onCellSave={onOrderCellSave}
          onRowClick={(r) => openRow(r)}
          onRowContextMenu={(row, _i, e) => orderCtx.open(row)(e)}
          storageKey="bunker_orders_grid"
          emptyText={t("common.empty", "No records")}
        />
      </div>

      <BunkerRequirementsPanel />

      <RecordModal
        open={creating || Boolean(open)}
        title={
          creating
            ? t("page.bunker.create", "Create bunker order")
            : open
              ? `${t("page.bunker.edit", "Edit bunker order")} · ${open.order_no}`
              : ""
        }
        onClose={closeModal}
        onSave={save}
        canEdit={!open || !orderLocked(open)}
        canDelete={open ? !orderLocked(open) : false}
        onDelete={open ? () => deleteOrder(open.id) : undefined}
        saving={busy}
      >
        {!creating && open ? (
          <p className="muted">
            {t("common.status", "Status")}: {open.status}
          </p>
        ) : null}
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
        {creating ? (
          <label>
            {t("page.bunker.index_symbol", "Index symbol")}
            <input
              value={form.index_symbol}
              onChange={(e) => setForm({ ...form, index_symbol: e.target.value })}
              placeholder={t("page.bunker.index_symbol_ph", "SIN380 (optional)")}
            />
          </label>
        ) : null}
        {creating && form.index_symbol.trim() !== "" ? (
          <label>
            {t("page.bunker.price_diff", "Price differential")}
            <input
              value={form.price_differential}
              onChange={(e) => setForm({ ...form, price_differential: e.target.value })}
              placeholder="+12"
            />
          </label>
        ) : (
          <label>
            {t("page.bunker.price", "Unit price")}
            <input value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
          </label>
        )}
        <label>
          {t("page.bunker.rob_before", "ROB before")}
          <input value={form.rob_before} onChange={(e) => setForm({ ...form, rob_before: e.target.value })} />
        </label>
        {!creating && open ? (
          <>
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
            <div className="desk-section desk-section-tight">
              <h3>{t("page.bunker.inquiries", "Inquiries")}</h3>
              {inquiries.length ? (
                <DataGrid<Inquiry>
                  columns={inquiryColumns}
                  data={inquiries}
                  rowKey={(r) => r.id}
                  onRowContextMenu={(row, _i, e) => inqCtx.open(row)(e)}
                  storageKey="bunker_inquiries_grid"
                  showFooter={false}
                  showColumnMenu={false}
                  emptyText={t("page.bunker.no_inquiries", "No quotes yet")}
                />
              ) : (
                <p className="muted m-0">{t("page.bunker.no_inquiries", "No quotes yet")}</p>
              )}
              <div className="form-grid mt-sm">
                <label>
                  {t("page.bunker.supplier", "Supplier")}
                  <PartyPicker value="" onChange={(_id, item) => item && setInqSupplier(item.label)} placeholder={inqSupplier || t("picker.search", "Search counterparty…")} />
                </label>
                <label>
                  {t("page.bunker.quoted_price", "Quoted price")}
                  <input type="number" step="any" value={inqPrice} onChange={(e) => setInqPrice(e.target.value)} />
                </label>
                <div className="editor-actions">
                  <button className="btn btn-sm" type="button" disabled={busy} onClick={addInquiry}>
                    {t("page.bunker.add_inquiry", "Add quote")}
                  </button>
                </div>
              </div>
            </div>
            {open.voyage_id ? (
              <div className="desk-section desk-section-tight">
                <div className="desk-toolbar desk-toolbar-flush">
                  <h3 className="h3-compact">{t("page.bunker.allocation", "Voyage allocation estimate")}</h3>
                  <button className="btn btn-sm" type="button" disabled={busy} onClick={loadAllocation}>
                    {t("page.bunker.alloc_run", "Run allocation")}
                  </button>
                </div>
                {alloc ? (
                  <div className="desk-results mt-sm">
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
              {open.status === "planned" ? (
                <button type="button" className="btn btn-sm" onClick={() => move(open.id, "inquiry")}>
                  {t("page.bunker.inquiry", "Inquiry")}
                </button>
              ) : null}
              {open.status === "inquiry" ? (
                <button type="button" className="btn btn-sm" onClick={() => move(open.id, "ordered")}>
                  {t("page.bunker.order", "Place order")}
                </button>
              ) : null}
              {open.status === "ordered" ? (
                <button type="button" className="btn btn-primary btn-sm" onClick={() => move(open.id, "delivered")}>
                  {t("page.bunker.confirm_delivery", "Confirm delivery")}
                </button>
              ) : null}
              {open.status === "delivered" ? (
                <button type="button" className="btn btn-sm" onClick={() => move(open.id, "closed")}>
                  {t("common.close", "Close")}
                </button>
              ) : null}
            </div>
          </>
        ) : null}
      </RecordModal>

      <ContextMenu controller={orderCtx} items={orderMenuItems} />
      <ContextMenu controller={inqCtx} items={inqMenuItems} />
    </AppShell>
  );
}
