"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
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
  }, [selected]);

  useEffect(() => {
    load().catch(() => setErr(t("common.failed", "加载失败")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = pools.find((p) => p.id === selected) || null;

  const activeVesselIds = useMemo(() => {
    const ids = new Set<string>();
    for (const p of pools) {
      for (const m of p.vessels) ids.add(m.vessel_id);
    }
    return ids;
  }, [pools]);

  const availableVessels = useMemo(() => {
    return vessels.filter((v) => !activeVesselIds.has(v.id));
  }, [vessels, activeVesselIds]);

  useEffect(() => {
    if (!availableVessels.length) {
      setVesselId("");
      return;
    }
    if (!availableVessels.some((v) => v.id === vesselId)) {
      setVesselId(availableVessels[0].id);
    }
  }, [availableVessels, vesselId]);

  async function createPool(e: FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      const res = await apiPost(`/api/v1/pools?name=${encodeURIComponent(name)}`);
      setMsg(t("page.pool.created", "船池已创建"));
      setName("");
      await load();
      setSelected(res.id);
    } catch (ex: any) {
      setErr(String(ex?.detail?.message || ex?.message || ex));
    }
  }

  async function addVessel(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setMsg("");
    if (!selected || !vesselId) return;
    try {
      await apiPost(`/api/v1/pools/${selected}/vessels?vessel_id=${vesselId}&points=${Number(points) || 1}`);
      setMsg(t("page.pool.vessel_ok", "已加入船池"));
      await load();
    } catch (ex: any) {
      const code = ex?.detail?.code || ex?.code;
      if (code === "VESSEL_ALREADY_IN_POOL") {
        setErr(t("page.pool.already_in", "该船已在当前船池中，不能重复加入"));
      } else if (code === "VESSEL_IN_OTHER_POOL") {
        setErr(
          t("page.pool.in_other", "该船已在其他船池「{name}」中，请先退出后再加入", {
            name: ex?.detail?.pool_name || "",
          }),
        );
      } else {
        setErr(String(ex?.detail?.message || ex?.message || ex));
      }
    }
  }

  async function removeVessel(membershipId: string) {
    if (!selected) return;
    setErr("");
    try {
      await apiDelete(`/api/v1/pools/${selected}/vessels/${membershipId}`);
      setMsg(t("page.pool.left", "已退出船池"));
      await load();
    } catch (ex: any) {
      setErr(String(ex?.detail?.message || ex?.message || ex));
    }
  }

  async function createPeriod(e: FormEvent) {
    e.preventDefault();
    setErr("");
    if (!selected) return;
    try {
      await apiPost(
        `/api/v1/pools/${selected}/periods?label=${encodeURIComponent(periodLabel)}&total_pool_result=${Number(totalResult) || 0}`,
      );
      setMsg(t("page.pool.period_ok", "期间分配已生成"));
      await load();
    } catch (ex: any) {
      setErr(String(ex?.detail?.message || ex?.message || ex));
    }
  }

  async function settle(periodId: string) {
    setErr("");
    try {
      await apiPost(`/api/v1/pools/periods/${periodId}/settle`);
      setMsg(t("page.pool.settled", "期间已结算"));
      await load();
    } catch (ex: any) {
      setErr(String(ex?.detail?.message || ex?.message || ex));
    }
  }

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.pool.title", "船舶池")}</h1>
          <p className="page-sub">
            {t("page.pool.sub", "入池船舶、期间结果与按点分配结算。同一船舶不可重复入池，也不可同时在多个池中。")}
          </p>
        </div>
      </div>
      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <form className="panel" onSubmit={createPool}>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "end" }}>
          <label>
            {t("common.name", "名称")}
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <button className="btn btn-primary" type="submit">
            {t("page.pool.create", "创建船池")}
          </button>
        </div>
      </form>

      <div className="panel" style={{ marginTop: "1rem" }}>
        <label>
          {t("page.pool.select", "当前船池")}
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
            <h3 style={{ marginTop: 0 }}>{t("page.pool.add_vessel", "加入船舶")}</h3>
            <div className="form-grid">
              <label>
                {t("page.estimates.vessel", "船舶")}
                <select value={vesselId} onChange={(e) => setVesselId(e.target.value)} disabled={!availableVessels.length}>
                  {!availableVessels.length ? (
                    <option value="">{t("page.pool.no_available", "无可加入船舶（均已在池中）")}</option>
                  ) : (
                    availableVessels.map((v) => (
                      <option key={v.id} value={v.id}>
                        {v.name}
                      </option>
                    ))
                  )}
                </select>
              </label>
              <label>
                {t("page.pool.points", "点数")}
                <input value={points} onChange={(e) => setPoints(e.target.value)} />
              </label>
            </div>
            <button className="btn btn-primary" type="submit" disabled={!availableVessels.length || !vesselId}>
              {t("common.add", "加入")}
            </button>
            <table className="table" style={{ marginTop: "1rem" }}>
              <thead>
                <tr>
                  <th>{t("page.pool.vessel", "船舶")}</th>
                  <th>{t("page.pool.points", "点数")}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {current.vessels.map((v) => (
                  <tr key={v.id}>
                    <td>{vessels.find((x) => x.id === v.vessel_id)?.name || v.vessel_id.slice(0, 8)}</td>
                    <td>{v.points}</td>
                    <td>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => removeVessel(v.id)}>
                        {t("page.pool.leave", "退出")}
                      </button>
                    </td>
                  </tr>
                ))}
                {!current.vessels.length ? (
                  <tr>
                    <td colSpan={3} className="muted">
                      {t("common.none", "无")}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </form>

          <form className="panel" style={{ marginTop: "1rem" }} onSubmit={createPeriod}>
            <h3 style={{ marginTop: 0 }}>{t("page.pool.period", "结算期间")}</h3>
            <div className="form-grid">
              <label>
                {t("page.pool.label", "期间标签")}
                <input value={periodLabel} onChange={(e) => setPeriodLabel(e.target.value)} />
              </label>
              <label>
                {t("page.pool.total", "池总结果")}
                <input value={totalResult} onChange={(e) => setTotalResult(e.target.value)} />
              </label>
            </div>
            <button className="btn btn-primary" type="submit">
              {t("page.pool.distribute", "计算分配")}
            </button>
            <table className="table" style={{ marginTop: "1rem" }}>
              <thead>
                <tr>
                  <th>{t("page.pool.label", "期间标签")}</th>
                  <th>{t("page.pool.total", "池总结果")}</th>
                  <th>{t("common.status", "状态")}</th>
                  <th>{t("page.pool.distribution", "分配")}</th>
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
                          {t("page.pool.settle", "结算")}
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
