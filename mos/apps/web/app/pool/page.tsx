"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Pool = {
  id: string;
  name: string;
  vessel_count: number;
  vessels: { id: string; vessel_id: string; points: number }[];
  periods: { id: string; label: string; total_pool_result: number; status: string; distribution: Record<string, number> }[];
};
type Vessel = { id: string; name: string };

export default function PoolPage() {
  const { t } = useI18n();
  const [pools, setPools] = useState<Pool[]>([]);
  const [vessels, setVessels] = useState<Vessel[]>([]);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string>("");
  const [vesselId, setVesselId] = useState("");
  const [points, setPoints] = useState("1");
  const [periodLabel, setPeriodLabel] = useState("2026-Q3");
  const [totalResult, setTotalResult] = useState("1000000");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    const [p, v] = await Promise.all([apiGet("/api/v1/pools"), apiGet("/api/v1/masterdata/vessels").catch(() => [])]);
    setPools(p);
    setVessels(v);
    if (!selected && p[0]?.id) setSelected(p[0].id);
    if (!vesselId && v[0]?.id) setVesselId(v[0].id);
  }, [selected, vesselId]);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "Failed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = pools.find((p) => p.id === selected) || null;

  async function createPool(e: FormEvent) {
    e.preventDefault();
    try {
      const res = await apiPost(`/api/v1/pools?name=${encodeURIComponent(name)}`);
      setMsg(t("page.pool.created", "Pool created"));
      setName("");
      await load();
      setSelected(res.id);
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function addVessel(e: FormEvent) {
    e.preventDefault();
    if (!selected) return;
    try {
      await apiPost(`/api/v1/pools/${selected}/vessels?vessel_id=${vesselId}&points=${Number(points) || 1}`);
      setMsg(t("page.pool.vessel_ok", "Vessel added to pool"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function createPeriod(e: FormEvent) {
    e.preventDefault();
    if (!selected) return;
    try {
      await apiPost(
        `/api/v1/pools/${selected}/periods?label=${encodeURIComponent(periodLabel)}&total_pool_result=${Number(totalResult) || 0}`,
      );
      setMsg(t("page.pool.period_ok", "Period distribution generated"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function settle(periodId: string) {
    try {
      await apiPost(`/api/v1/pools/periods/${periodId}/settle`);
      setMsg(t("page.pool.settled", "Period settled"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.pool.title", "Pooling")}</h1>
          <p className="page-sub">{t("page.pool.sub", "Pool vessels, period results and points-based distribution.")}</p>
        </div>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <form className="panel" onSubmit={createPool}>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("common.name", "Name")}
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.pool.create", "Create pool")}
          </button>
        </div>
      </form>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <label>
          {t("page.pool.select", "Current pool")}
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {pools.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.vessel_count})
              </option>
            ))}
          </select>
        </label>
      </div>

      {current ? (
        <>
          <form className="panel" style={{ marginTop: "1rem" }} onSubmit={addVessel}>
            <h3 style={{ marginTop: 0 }}>{t("page.pool.add_vessel", "Add vessel")}</h3>
            <div className="form-grid">
              <label>
                {t("page.estimates.vessel", "Vessel")}
                <select value={vesselId} onChange={(e) => setVesselId(e.target.value)}>
                  {vessels.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("page.pool.points", "Points")}
                <input value={points} onChange={(e) => setPoints(e.target.value)} />
              </label>
            </div>
            <button className="btn btn-primary" type="submit">
              {t("common.add", "Add")}
            </button>
            <table className="table" style={{ marginTop: "1rem" }}>
              <thead>
                <tr>
                  <th>{t("page.pool.vessel", "Vessel")}</th>
                  <th>{t("page.pool.points", "Points")}</th>
                </tr>
              </thead>
              <tbody>
                {current.vessels.map((v) => (
                  <tr key={v.id}>
                    <td>{vessels.find((x) => x.id === v.vessel_id)?.name || v.vessel_id.slice(0, 8)}</td>
                    <td>{v.points}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </form>

          <form className="panel" style={{ marginTop: "1rem" }} onSubmit={createPeriod}>
            <h3 style={{ marginTop: 0 }}>{t("page.pool.period", "Settlement period")}</h3>
            <div className="form-grid">
              <label>
                {t("page.pool.label", "Label")}
                <input value={periodLabel} onChange={(e) => setPeriodLabel(e.target.value)} />
              </label>
              <label>
                {t("page.pool.total", "Pool total result")}
                <input value={totalResult} onChange={(e) => setTotalResult(e.target.value)} />
              </label>
            </div>
            <button className="btn btn-primary" type="submit">
              {t("page.pool.distribute", "Calculate distribution")}
            </button>
            <table className="table" style={{ marginTop: "1rem" }}>
              <thead>
                <tr>
                  <th>{t("page.pool.label", "Label")}</th>
                  <th>{t("page.pool.total", "Pool total result")}</th>
                  <th>{t("common.status", "Status")}</th>
                  <th>{t("page.pool.distribution", "Distribution")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {current.periods.map((p) => (
                  <tr key={p.id}>
                    <td>{p.label}</td>
                    <td>{p.total_pool_result.toLocaleString()}</td>
                    <td>{p.status}</td>
                    <td>
                      <code style={{ fontSize: "0.75rem" }}>{JSON.stringify(p.distribution)}</code>
                    </td>
                    <td>
                      {p.status !== "settled" ? (
                        <button type="button" className="btn btn-sm" onClick={() => settle(p.id)}>
                          {t("page.pool.settle", "Settle")}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </form>
        </>
      ) : null}
    </AppShell>
  );
}
