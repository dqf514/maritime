"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Row = {
  id: string;
  voyage_id: string | null;
  vessel_id: string | null;
  fo_mt: number;
  do_mt: number;
  co2_mt: number;
  cii_rating: string | null;
  period: string | null;
};
type Ref = { id: string; name?: string; voyage_no?: string };

export default function EmissionsPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Row[]>([]);
  const [voyages, setVoyages] = useState<Ref[]>([]);
  const [vessels, setVessels] = useState<Ref[]>([]);
  const [msg, setMsg] = useState("");
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

  async function calc(e: FormEvent) {
    e.preventDefault();
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
      setMsg(t("page.emissions.calc_ok", "Calculated and saved emission record"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function exportPack() {
    try {
      const data = await apiGet("/api/v1/emissions/export");
      setResult(data);
      setMsg(t("page.emissions.export_ok", "Export pack generated (wire verifier connector)"));
    } catch (ex) {
      setErr(String(ex));
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.emissions.title", "Emissions / FuelEU")}</h1>
          <p className="page-sub">
            {t("page.emissions.sub", "Voyage emissions, EU ETS exposure and FuelEU intensity checks.")}
          </p>
        </div>
        <div className="quick-row">
          <Link href="/settings/connectors" className="btn btn-ghost">
            {t("page.connectors.title", "Integration Hub")}
          </Link>
          <button type="button" className="btn btn-ghost" onClick={() => exportPack()}>
            {t("page.emissions.export", "Export report")}
          </button>
        </div>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <form className="panel" onSubmit={calc}>
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
        <button className="btn btn-primary" type="submit">
          {t("page.emissions.run", "Calculate compliance cost")}
        </button>
      </form>

      {result ? (
        <div className="panel" style={{ marginTop: "1rem" }}>
          <h3 style={{ marginTop: 0 }}>{t("page.emissions.result", "Results")}</h3>
          {result.eu_share != null ? (
            <p style={{ margin: "0 0 0.5rem" }}>
              EU share: <strong>{String(result.eu_share)}</strong>{" "}
              <span className="badge badge-warn">
                {result.eu_share_source === "manual"
                  ? t("page.emissions.share_manual", "手动 manual")
                  : t("page.emissions.share_auto", "自动 auto")}
              </span>
              {result.borne_by === "charterer" ? (
                <span className="badge badge-pass" style={{ marginLeft: "0.4rem" }}>
                  {t("page.emissions.borne_charterer", "由租家承担")}
                </span>
              ) : null}
            </p>
          ) : null}
          {result.eeoi != null ? (
            <p style={{ margin: "0 0 0.5rem" }}>
              EEOI: <strong>{Number(result.eeoi).toExponential(4)}</strong>{" "}
              <span className="muted">{t("page.emissions.eeoi_unit", "吨CO₂/吨海里")}</span>
            </p>
          ) : null}
          <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.85rem" }}>{JSON.stringify(result, null, 2)}</pre>
        </div>
      ) : null}

      <div className="panel" style={{ marginTop: "1rem" }}>
        <h3 style={{ marginTop: 0 }}>{t("page.emissions.records", "Emission records")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>FO</th>
              <th>DO</th>
              <th>CO₂</th>
              <th>CII</th>
              <th>Period</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.id.slice(0, 8)}</td>
                <td>{r.fo_mt}</td>
                <td>{r.do_mt}</td>
                <td>{r.co2_mt}</td>
                <td>{r.cii_rating || "—"}</td>
                <td>{r.period || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
