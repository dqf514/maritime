"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { ContextMenu, useContextMenu, type ContextMenuItem } from "@/components/ContextMenu";
import { Num } from "@/components/Num";
import { PageHeader } from "@/components/PageHeader";
import { RowActions } from "@/components/RowActions";
import { StatusLegend } from "@/components/StatusLegend";
import { DataGrid } from "@/components/grid";
import type { ColumnDef } from "@/components/grid/types";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

type Row = {
  id: string;
  voyage_id: string | null;
  voyage_no?: string | null;
  vessel_id: string | null;
  vessel_name?: string | null;
  fo_mt: number;
  do_mt: number;
  co2_mt: number;
  cii_rating: string | null;
  period: string | null;
  updated_at?: string | null;
};
type Ref = { id: string; name?: string; voyage_no?: string };

export default function EmissionsPage() {
  const { t } = useI18n();
  const toast = useToast();
  const [rows, setRows] = useState<Row[]>([]);
  const [voyages, setVoyages] = useState<Ref[]>([]);
  const [vessels, setVessels] = useState<Ref[]>([]);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [form, setForm] = useState({
    voyage_id: "",
    vessel_id: "",
    fo_mt: "120",
    do_mt: "20",
    lng_mt: "0",
    cargo_mt: "",
    distance_nm: "",
    eu_share: "1",
    ets_price_eur: "70",
  });

  const load = useCallback(async () => {
    const [e, v, s] = await Promise.all([
      apiGet("/api/v1/emissions"),
      apiGet("/api/v1/voyages").catch(() => []),
      apiGet("/api/v1/masterdata/vessels").catch(() => []),
    ]);
    setRows(e);
    setVoyages(v);
    setVessels(s);
  }, []);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
  }, [load, t]);

  async function calc() {
    try {
      const res = await apiPost("/api/v1/emissions/fueleu-calc", {
        voyage_id: form.voyage_id || null,
        vessel_id: form.vessel_id || null,
        fo_mt: Number(form.fo_mt) || 0,
        do_mt: Number(form.do_mt) || 0,
        lng_mt: Number(form.lng_mt) || 0,
        cargo_mt: Number(form.cargo_mt) || 0,
        distance_nm: Number(form.distance_nm) || 0,
        eu_share: Number(form.eu_share) || 1,
        ets_price_eur: Number(form.ets_price_eur) || 70,
      });
      setResult(res);
      toast.success(t("page.emissions.calc_ok", "Calculated and saved emission record"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function exportPack() {
    try {
      const data = await apiGet("/api/v1/emissions/export");
      setResult(data);
      toast.success(t("page.emissions.export_ok", "Export pack generated (wire verifier connector)"));
    } catch (ex) {
      setErr(String(ex));
    }
  }

  const ctx = useContextMenu<Row>();

  function exportRows(selected: Row[]) {
    downloadCsv(
      "emission-records",
      ["id", "voyage_id", "vessel_id", "fo_mt", "do_mt", "co2_mt", "cii_rating", "period"],
      selected.map((r) => [r.id, r.voyage_id ?? "", r.vessel_id ?? "", r.fo_mt, r.do_mt, r.co2_mt, r.cii_rating ?? "", r.period ?? ""]),
    );
  }

  function menuItems(target: Row): ContextMenuItem[] {
    return [
      { key: "copy", label: t("common.copy_id", "Copy id"), onClick: () => void navigator.clipboard?.writeText(target.id) },
      { key: "export", label: t("page.finance.export_selected", "Export selected"), onClick: () => exportRows([target]) },
    ];
  }

  async function onCellSave(rowId: string, colKey: string, value: unknown, row: Row) {
    const src = row as unknown as Record<string, unknown>;
    let payload: Record<string, unknown>;
    if (colKey === "fo_mt" || colKey === "do_mt") {
      const next = value === null || value === "" ? 0 : Number(value);
      if (Number.isNaN(next)) return;
      if (Number(src[colKey] ?? 0) === next) return;
      payload = { [colKey]: next };
    } else if (colKey === "voyage_id" || colKey === "vessel_id") {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    } else {
      if ((src[colKey] ?? "") === (value ?? "")) return;
      payload = { [colKey]: value === "" ? null : value };
    }
    try {
      await apiPatch(`/api/v1/emissions/${rowId}`, payload);
      toast.success(t("common.saved", "Saved"));
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  async function deleteEmission(id: string) {
    try {
      await apiDelete(`/api/v1/emissions/${id}`);
      toast.success(t("common.deleted", "Deleted"));
      await load();
    } catch (ex: any) {
      toast.error(ex?.message || String(ex));
    }
  }

  const columns: ColumnDef<Row>[] = [
    {
      key: "id",
      title: t("common.id", "ID"),
      width: 110,
      value: (r) => r.id.slice(0, 8),
      render: (v, r) => <span title={r.id}>{String(v ?? "")}</span>,
    },
    {
      key: "voyage_id",
      title: t("page.voyages.list", "Voyages"),
      width: 130,
      value: (r) => r.voyage_no || r.voyage_id || "",
      editor: {
        type: "select",
        options: [{ value: "", label: "—" }, ...voyages.map((v) => ({ value: v.id, label: v.voyage_no || v.id.slice(0, 8) }))],
      },
      render: (_v, r) => {
        // 优先序列化器附加的 voyage_no，再回落本地表，最后短 ID
        const local = voyages.find((x) => x.id === r.voyage_id);
        const label = r.voyage_no || local?.voyage_no;
        return label ? (
          <span title={r.voyage_id || undefined}>{label}</span>
        ) : r.voyage_id ? (
          <span title={r.voyage_id}>{r.voyage_id.slice(0, 8)}</span>
        ) : (
          "—"
        );
      },
    },
    {
      key: "vessel_id",
      title: t("page.estimates.vessel", "Vessel"),
      width: 130,
      value: (r) => r.vessel_name || r.vessel_id || "",
      editor: {
        type: "select",
        options: [{ value: "", label: "—" }, ...vessels.map((v) => ({ value: v.id, label: v.name || v.id.slice(0, 8) }))],
      },
      render: (_v, r) => {
        const local = vessels.find((x) => x.id === r.vessel_id);
        const label = r.vessel_name || local?.name;
        return label ? (
          <span title={r.vessel_id || undefined}>{label}</span>
        ) : r.vessel_id ? (
          <span title={r.vessel_id}>{r.vessel_id.slice(0, 8)}</span>
        ) : (
          "—"
        );
      },
    },
    {
      key: "fo_mt",
      title: t("page.emissions.fo", "FO"),
      width: 90,
      align: "right",
      value: (r) => r.fo_mt,
      editor: { type: "number", min: 0, step: 0.001 },
      render: (v) => <Num v={v as number} digits={3} />,
    },
    {
      key: "do_mt",
      title: t("page.emissions.do", "DO"),
      width: 90,
      align: "right",
      value: (r) => r.do_mt,
      editor: { type: "number", min: 0, step: 0.001 },
      render: (v) => <Num v={v as number} digits={3} />,
    },
    {
      key: "co2_mt",
      title: "CO₂",
      width: 90,
      align: "right",
      value: (r) => r.co2_mt,
      render: (v) => <Num v={v as number} digits={3} />,
    },
    {
      key: "cii_rating",
      title: "CII",
      width: 80,
      value: (r) => r.cii_rating || "",
      render: (v) => (v ? String(v) : "—"),
    },
    {
      key: "period",
      title: t("page.emissions.period", "Period"),
      minWidth: 110,
      value: (r) => r.period || "",
      editor: { type: "text" },
      render: (v) => (v ? String(v) : "—"),
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
      width: 70,
      align: "right",
      render: (_v, r) => <RowActions label={r.id.slice(0, 8)} onDelete={() => deleteEmission(r.id)} />,
    },
  ];

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.emissions", "Emissions / FuelEU") }]}
        title={t("page.emissions.title", "Emissions / FuelEU")}
        subtitle={t("page.emissions.sub", "Voyage emissions, EU ETS exposure and FuelEU intensity checks.")}
        actions={
          <>
            <Link href="/settings/connectors" className="btn btn-ghost">
              {t("page.connectors.title", "Integration Hub")}
            </Link>
            <button type="button" className="btn btn-ghost" onClick={() => exportPack()}>
              {t("page.emissions.export", "Export report")}
            </button>
          </>
        }
      />
      {err ? <p className="flash-err">{err}</p> : null}

      <section className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.emissions.calc", "FuelEU / ETS calculator")}</h3>
        <div className="form-grid">
          <label>
            {t("page.voyages.list", "Voyages")}
            <select value={form.voyage_id} onChange={(e) => setForm({ ...form, voyage_id: e.target.value })}>
              <option value="">—</option>
              {voyages.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.voyage_no || v.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
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
            FO mt
            <input value={form.fo_mt} onChange={(e) => setForm({ ...form, fo_mt: e.target.value })} />
          </label>
          <label>
            DO mt
            <input value={form.do_mt} onChange={(e) => setForm({ ...form, do_mt: e.target.value })} />
          </label>
          <label>
            LNG mt
            <input value={form.lng_mt} onChange={(e) => setForm({ ...form, lng_mt: e.target.value })} />
          </label>
          <label>
            {t("page.emissions.cargo_mt", "Cargo mt")}
            <input value={form.cargo_mt} onChange={(e) => setForm({ ...form, cargo_mt: e.target.value })} placeholder={t("common.optional", "Optional")} />
          </label>
          <label>
            {t("page.emissions.distance_nm", "Distance nm")}
            <input value={form.distance_nm} onChange={(e) => setForm({ ...form, distance_nm: e.target.value })} placeholder={t("common.optional", "Optional")} />
          </label>
          <label>
            EU {t("page.emissions.eu_share", "EU share")}
            <input value={form.eu_share} onChange={(e) => setForm({ ...form, eu_share: e.target.value })} />
          </label>
          <label>
            {t("page.emissions.ets_price", "ETS price (EUR)")}
            <input value={form.ets_price_eur} onChange={(e) => setForm({ ...form, ets_price_eur: e.target.value })} />
          </label>
        </div>
        <button className="btn btn-primary" type="button" onClick={() => void calc()}>
          {t("page.emissions.run", "Calculate compliance cost")}
        </button>
      </section>

      {result ? (
        <div className="panel" style={{ marginTop: "1rem" }}>
          <h3 style={{ marginTop: 0 }}>{t("page.emissions.result", "Results")}</h3>
          {result.eu_share != null ? (
            <p style={{ margin: "0 0 0.5rem" }}>
              EU share: <strong>{String(result.eu_share)}</strong>{" "}
              <span className="badge badge-warn">
                {result.eu_share_source === "manual"
                  ? t("page.emissions.share_manual", "Manual")
                  : t("page.emissions.share_auto", "Auto")}
              </span>
              {result.borne_by === "charterer" ? (
                <span className="badge badge-pass" style={{ marginLeft: "0.4rem" }}>
                  {t("page.emissions.borne_charterer", "Borne by charterer")}
                </span>
              ) : null}
            </p>
          ) : null}
          {result.eeoi != null ? (
            <p style={{ margin: "0 0 0.5rem" }}>
              EEOI: <strong>{Number(result.eeoi).toExponential(4)}</strong>{" "}
              <span className="muted">{t("page.emissions.eeoi_unit", "tCO2/ton-nm")}</span>
            </p>
          ) : null}
          <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.85rem" }}>{JSON.stringify(result, null, 2)}</pre>
        </div>
      ) : null}

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.emissions.records", "Emission records")}</h3>
        <StatusLegend statuses={["A", "B", "C", "D", "E"]} />
        <DataGrid<Row>
          columns={columns}
          data={rows}
          rowKey={(r) => r.id}
          editable
          onCellSave={onCellSave}
          onRowContextMenu={(row, _i, e) => ctx.open(row)(e)}
          storageKey="emissions_records_grid"
          showFooter={false}
          emptyText={t("common.empty", "No records")}
        />
      </div>

      <ContextMenu controller={ctx} items={menuItems} />
    </AppShell>
  );
}
