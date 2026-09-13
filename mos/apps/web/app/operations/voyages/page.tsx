"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type RefItem = { id: string; name: string; unlocode?: string };
type Voyage = { id: string; voyage_no: string; status: string; cargo: string | null; vessel_id: string | null };
type PortCall = {
  id: string;
  voyage_id: string;
  port_id: string | null;
  seq: number;
  purpose: string;
  eta: string | null;
  etd: string | null;
  agent: string | null;
};
type Schedule = {
  id: string;
  title: string;
  block_type: string;
  start_at: string;
  end_at: string;
  hard_conflict: boolean;
  vessel_id: string;
};
type Twin = {
  level: string;
  noon_track: Array<{ at: string; lat: number | null; lon: number | null }>;
  port_calls: PortCall[];
};

function toLocalInput(iso: string | null | undefined) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInput(v: string) {
  if (!v) return null;
  return new Date(v).toISOString();
}

export default function VoyagesPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<Voyage[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [ports, setPorts] = useState<RefItem[]>([]);
  const [agents, setAgents] = useState<RefItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [portCalls, setPortCalls] = useState<PortCall[]>([]);
  const [selectedPc, setSelectedPc] = useState<string>("");
  const [sofEvents, setSofEvents] = useState<Array<{ id: string; event_code: string; event_at: string | null; port_call_id: string }>>([]);
  const [twin, setTwin] = useState<Twin | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const [newVoyageNo, setNewVoyageNo] = useState("");
  const [newCargo, setNewCargo] = useState("");

  const [pcPurpose, setPcPurpose] = useState("load");
  const [pcSeq, setPcSeq] = useState("1");
  const [pcPort, setPcPort] = useState("");
  const [pcEta, setPcEta] = useState("");
  const [pcEtd, setPcEtd] = useState("");
  const [pcAgent, setPcAgent] = useState("");

  const [sofCode, setSofCode] = useState("NOR");
  const [sofAt, setSofAt] = useState("");

  const [noonLat, setNoonLat] = useState("");
  const [noonLon, setNoonLon] = useState("");
  const [noonSpeed, setNoonSpeed] = useState("");
  const [noonFo, setNoonFo] = useState("");
  const [noonDo, setNoonDo] = useState("");
  const [noonEta, setNoonEta] = useState("");
  const [noonRemarks, setNoonRemarks] = useState("");

  const load = useCallback(async () => {
    const [v, s, p, parties] = await Promise.all([
      apiGet("/api/v1/voyages"),
      apiGet("/api/v1/schedules"),
      apiGet("/api/v1/masterdata/ports"),
      apiGet("/api/v1/masterdata/counterparties").catch(() => []),
    ]);
    setRows(v);
    setSchedules(s);
    setPorts(p);
    setAgents(
      (parties as Array<{ id: string; name: string; type?: string }>).filter(
        (x) => !x.type || x.type === "agent" || x.type === "other",
      ),
    );
    if (!pcPort && p[0]?.id) setPcPort(p[0].id);
    return v as Voyage[];
  }, [pcPort]);

  const loadPortCalls = useCallback(async (voyageId: string, preferPc?: string) => {
    const pcs: PortCall[] = await apiGet(`/api/v1/port-calls?voyage_id=${voyageId}`);
    setPortCalls(pcs);
    const keep = preferPc && pcs.some((p) => p.id === preferPc) ? preferPc : pcs[0]?.id || "";
    setSelectedPc(keep);
    try {
      const sof = await apiGet(`/api/v1/sof-events?voyage_id=${voyageId}`);
      setSofEvents(sof);
    } catch {
      setSofEvents([]);
    }
    try {
      const tw = await apiGet(`/api/v1/twin/voyages/${voyageId}`);
      setTwin(tw);
    } catch {
      setTwin(null);
    }
  }, []);

  useEffect(() => {
    load()
      .then((v) => {
        if (v[0]) {
          setSelectedId(v[0].id);
          return loadPortCalls(v[0].id);
        }
      })
      .catch(() => setErr(t("common.failed", "Failed")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function selectVoyage(id: string) {
    setSelectedId(id);
    setTwin(null);
    setErr("");
    try {
      await loadPortCalls(id);
    } catch (ex) {
      setErr(String(ex));
    }
  }

  async function createVoyage(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const vno = newVoyageNo.trim() || `V-${new Date().toISOString().slice(0, 10).replace(/-/g, "")}-MAN`;
      const created = await apiPost("/api/v1/voyages", {
        voyage_no: vno,
        cargo: newCargo || null,
      });
      setMsg(t("page.voyages.created", "Voyage {no} created", { no: created.voyage_no }));
      setNewVoyageNo("");
      setNewCargo("");
      const list = await load();
      if (created.id) {
        setSelectedId(created.id);
        await loadPortCalls(created.id);
      } else if (list[0]) {
        setSelectedId(list[0].id);
      }
    } catch (ex: any) {
      setErr(ex?.message || String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function move(id: string, target: string) {
    setBusy(true);
    try {
      await apiPost(`/api/v1/voyages/${id}/transition`, { target });
      setMsg(t("page.voyages.moved", "Voyage → {target}", { target }));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function saveSelectedVoyage() {
    if (!selected) return;
    setBusy(true);
    try {
      await apiPatch(`/api/v1/voyages/${selected.id}`, {
        voyage_no: selected.voyage_no,
        cargo: selected.cargo,
      });
      setMsg(t("common.saved", "已保存"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function removeVoyage() {
    if (!selected) return;
    if (!window.confirm(t("common.confirm_delete", "Delete this record? It will move to the recycle bin and can be restored."))) return;
    setBusy(true);
    try {
      await apiDelete(`/api/v1/voyages/${selected.id}`);
      setSelectedId(null);
      setMsg(t("common.recycled", "已移入回收站"));
      await load();
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addPortCall(e: FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    setBusy(true);
    setErr("");
    try {
      await apiPost("/api/v1/port-calls", {
        voyage_id: selectedId,
        port_id: pcPort || null,
        seq: Number(pcSeq) || 1,
        purpose: pcPurpose,
        eta: fromLocalInput(pcEta),
        etd: fromLocalInput(pcEtd),
        agent: pcAgent || null,
      });
      setMsg(t("page.voyages.pc_ok", "Port call added"));
      setPcSeq(String((Number(pcSeq) || 1) + 1));
      await loadPortCalls(selectedId);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addSof(e: FormEvent) {
    e.preventDefault();
    if (!selectedPc) {
      setErr(t("page.voyages.need_pc", "Select a port call first"));
      return;
    }
    setBusy(true);
    try {
      await apiPost("/api/v1/sof-events", {
        port_call_id: selectedPc,
        event_code: sofCode,
        event_at: fromLocalInput(sofAt) || new Date().toISOString(),
      });
      setMsg(t("page.voyages.sof_ok", "SOF {code} recorded", { code: sofCode }));
      if (selectedId) await loadPortCalls(selectedId);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  async function addNoon(e: FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    setBusy(true);
    try {
      await apiPost("/api/v1/noon-reports", {
        voyage_id: selectedId,
        report_at: new Date().toISOString(),
        lat: noonLat === "" ? null : Number(noonLat),
        lon: noonLon === "" ? null : Number(noonLon),
        speed: noonSpeed === "" ? null : Number(noonSpeed),
        rob_fo: noonFo === "" ? null : Number(noonFo),
        rob_do: noonDo === "" ? null : Number(noonDo),
        eta_next: fromLocalInput(noonEta),
        remarks: noonRemarks || null,
      });
      setMsg(t("page.voyages.noon_ok", "Noon report filed"));
      await loadPortCalls(selectedId);
    } catch (ex) {
      setErr(String(ex));
    } finally {
      setBusy(false);
    }
  }

  function portLabel(id: string | null) {
    if (!id) return "—";
    const p = ports.find((x) => x.id === id);
    return p ? `${p.name}${p.unlocode ? ` (${p.unlocode})` : ""}` : id.slice(0, 8);
  }

  const selected = rows.find((r) => r.id === selectedId) || null;
  const conflicts = schedules.filter((s) => s.hard_conflict);

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.voyages.title", "营运工作台")}</h1>
          <p className="page-sub">
            {t("page.voyages.sub", "航次、港序、SOF、正午报与冲突。选中航次后可在右侧编辑或删除。")}
          </p>
        </div>
        <Link href="/settings/recycle" className="btn btn-ghost">
          {t("nav.recycle", "回收站")}
        </Link>
      </div>

      {msg ? <p className="flash">{msg}</p> : null}
      {err ? <p className="flash-err">{err}</p> : null}

      <div className="desk-split">
        <div className="panel desk-list">
          <h3 style={{ margin: "0.85rem 1rem 0.35rem", fontSize: "0.95rem" }}>{t("page.voyages.list", "Voyages")}</h3>
          <form className="form-grid" style={{ padding: "0 1rem 0.75rem" }} onSubmit={createVoyage}>
            <label>
              {t("page.voyages.no", "No")}
              <input value={newVoyageNo} onChange={(e) => setNewVoyageNo(e.target.value)} placeholder="V-…" />
            </label>
            <label>
              {t("page.voyages.cargo", "Cargo")}
              <input value={newCargo} onChange={(e) => setNewCargo(e.target.value)} />
            </label>
            <div style={{ display: "flex", alignItems: "end" }}>
              <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>
                {t("page.voyages.create", "New voyage")}
              </button>
            </div>
          </form>
          <p className="muted" style={{ padding: "0 1rem", marginTop: 0, fontSize: "0.8rem" }}>
            {t("page.voyages.create_hint", "Or activate a charter to auto-create a voyage + schedule block.")}
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>{t("page.voyages.no", "No")}</th>
                <th>{t("page.voyages.cargo", "Cargo")}</th>
                <th>{t("common.status", "Status")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.id === selectedId ? "selected" : ""} onClick={() => selectVoyage(r.id)}>
                  <td>{r.voyage_no}</td>
                  <td>{r.cargo || "—"}</td>
                  <td>{r.status}</td>
                </tr>
              ))}
              {!rows.length ? (
                <tr>
                  <td colSpan={3} className="muted">
                    {t("common.empty", "No records")}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div>
          {selected ? (
            <div className="panel" style={{ marginTop: 0 }}>
              <div className="page-header" style={{ marginBottom: "0.5rem" }}>
                <div>
                  <h3 style={{ margin: 0 }}>
                    {selected.voyage_no} · {selected.status}
                  </h3>
                  <label style={{ display: "block", marginTop: "0.5rem" }}>
                    {t("page.voyages.cargo", "货物")}
                    <input
                      value={selected.cargo || ""}
                      onChange={(e) =>
                        setRows((prev) => prev.map((r) => (r.id === selected.id ? { ...r, cargo: e.target.value } : r)))
                      }
                    />
                  </label>
                </div>
                <div className="desk-toolbar" style={{ margin: 0 }}>
                  <button className="btn btn-sm" type="button" disabled={busy} onClick={saveSelectedVoyage}>
                    {t("common.save", "保存")}
                  </button>
                  {selected.status === "planned" ? (
                    <button className="btn btn-primary btn-sm" type="button" disabled={busy} onClick={() => move(selected.id, "in_progress")}>
                      {t("page.voyages.start", "开工")}
                    </button>
                  ) : null}
                  {selected.status === "in_progress" ? (
                    <button className="btn btn-sm" type="button" disabled={busy} onClick={() => move(selected.id, "completed")}>
                      {t("page.voyages.complete", "完成")}
                    </button>
                  ) : null}
                  <button className="btn btn-danger btn-sm" type="button" disabled={busy} onClick={removeVoyage}>
                    {t("common.delete", "删除")}
                  </button>
                </div>
              </div>

              <div className="desk-section">
                <h3>{t("page.voyages.port_calls", "Port calls")}</h3>
                <table className="table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>{t("page.voyages.port", "Port")}</th>
                      <th>{t("page.voyages.purpose", "Purpose")}</th>
                      <th>ETA</th>
                      <th>ETD</th>
                      <th>{t("page.voyages.agent", "Agent")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {portCalls.map((pc) => (
                      <tr
                        key={pc.id}
                        className={pc.id === selectedPc ? "selected" : ""}
                        style={{ cursor: "pointer" }}
                        onClick={() => setSelectedPc(pc.id)}
                      >
                        <td>{pc.seq}</td>
                        <td>{portLabel(pc.port_id)}</td>
                        <td>{pc.purpose}</td>
                        <td>{pc.eta ? toLocalInput(pc.eta).replace("T", " ") : "—"}</td>
                        <td>{pc.etd ? toLocalInput(pc.etd).replace("T", " ") : "—"}</td>
                        <td>{pc.agent || "—"}</td>
                      </tr>
                    ))}
                    {!portCalls.length ? (
                      <tr>
                        <td colSpan={6} className="muted">
                          {t("common.empty", "No records")}
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>

                <form className="form-grid" onSubmit={addPortCall} style={{ marginTop: "0.75rem" }}>
                  <label>
                    {t("page.voyages.purpose", "Purpose")}
                    <select value={pcPurpose} onChange={(e) => setPcPurpose(e.target.value)}>
                      <option value="load">load</option>
                      <option value="discharge">discharge</option>
                      <option value="bunker">bunker</option>
                      <option value="transit">transit</option>
                    </select>
                  </label>
                  <label>
                    {t("page.voyages.seq", "Seq")}
                    <input type="number" value={pcSeq} onChange={(e) => setPcSeq(e.target.value)} />
                  </label>
                  <label>
                    {t("page.voyages.port", "Port")}
                    <select value={pcPort} onChange={(e) => setPcPort(e.target.value)}>
                      {ports.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    ETA
                    <input type="datetime-local" value={pcEta} onChange={(e) => setPcEta(e.target.value)} />
                  </label>
                  <label>
                    ETD
                    <input type="datetime-local" value={pcEtd} onChange={(e) => setPcEtd(e.target.value)} />
                  </label>
                  <label>
                    {t("page.voyages.agent", "代理")}
                    <select value={pcAgent} onChange={(e) => setPcAgent(e.target.value)}>
                      <option value="">{t("common.select", "请选择")}</option>
                      {agents.map((a) => (
                        <option key={a.id} value={a.name}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div style={{ display: "flex", alignItems: "end" }}>
                    <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>
                      {t("page.voyages.add_pc", "Add port call")}
                    </button>
                  </div>
                </form>
              </div>

              <div className="desk-section">
                <h3>{t("page.voyages.sof", "SOF events")}</h3>
                <form className="form-grid" onSubmit={addSof}>
                  <label>
                    {t("page.voyages.port_call", "Port call")}
                    <select value={selectedPc} onChange={(e) => setSelectedPc(e.target.value)}>
                      <option value="">{t("common.select", "Select…")}</option>
                      {portCalls.map((pc) => (
                        <option key={pc.id} value={pc.id}>
                          #{pc.seq} {pc.purpose} · {portLabel(pc.port_id)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("page.voyages.event", "Event")}
                    <select value={sofCode} onChange={(e) => setSofCode(e.target.value)}>
                      <option value="NOR">NOR</option>
                      <option value="COMMENCED">COMMENCED</option>
                      <option value="COMPLETED">COMPLETED</option>
                      <option value="SAILED">SAILED</option>
                    </select>
                  </label>
                  <label>
                    {t("page.voyages.event_at", "Event at")}
                    <input type="datetime-local" value={sofAt} onChange={(e) => setSofAt(e.target.value)} />
                  </label>
                  <div style={{ display: "flex", alignItems: "end" }}>
                    <button className="btn btn-sm" type="submit" disabled={busy}>
                      {t("page.voyages.post_sof", "Post SOF")}
                    </button>
                  </div>
                </form>
                <table className="table" style={{ marginTop: "0.75rem" }}>
                  <thead>
                    <tr>
                      <th>{t("page.voyages.event", "Event")}</th>
                      <th>{t("page.voyages.event_at", "Event at")}</th>
                      <th>{t("page.voyages.port_call", "Port call")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sofEvents.map((ev) => (
                      <tr key={ev.id}>
                        <td>{ev.event_code}</td>
                        <td>{ev.event_at ? new Date(ev.event_at).toLocaleString() : "—"}</td>
                        <td>{ev.port_call_id.slice(0, 8)}</td>
                      </tr>
                    ))}
                    {!sofEvents.length ? (
                      <tr>
                        <td colSpan={3} className="muted">
                          {t("common.no_data", "No data")}
                        </td>
                      </tr>
                    ) : null}
                  </tbody>
                </table>
              </div>

              <div className="desk-section">
                <h3>{t("page.voyages.noon", "Noon report")}</h3>
                <form className="form-grid" onSubmit={addNoon}>
                  <label>
                    Lat
                    <input type="number" step="any" value={noonLat} onChange={(e) => setNoonLat(e.target.value)} />
                  </label>
                  <label>
                    Lon
                    <input type="number" step="any" value={noonLon} onChange={(e) => setNoonLon(e.target.value)} />
                  </label>
                  <label>
                    {t("page.voyages.speed", "Speed")}
                    <input type="number" step="any" value={noonSpeed} onChange={(e) => setNoonSpeed(e.target.value)} />
                  </label>
                  <label>
                    ROB FO
                    <input type="number" step="any" value={noonFo} onChange={(e) => setNoonFo(e.target.value)} />
                  </label>
                  <label>
                    ROB DO
                    <input type="number" step="any" value={noonDo} onChange={(e) => setNoonDo(e.target.value)} />
                  </label>
                  <label>
                    ETA next
                    <input type="datetime-local" value={noonEta} onChange={(e) => setNoonEta(e.target.value)} />
                  </label>
                  <label style={{ gridColumn: "1 / -1" }}>
                    {t("page.voyages.remarks", "Remarks")}
                    <input value={noonRemarks} onChange={(e) => setNoonRemarks(e.target.value)} />
                  </label>
                  <div style={{ display: "flex", alignItems: "end" }}>
                    <button className="btn btn-sm" type="submit" disabled={busy}>
                      {t("page.voyages.post_noon", "Post noon")}
                    </button>
                  </div>
                </form>
              </div>

              <div className="desk-section">
                <h3>{t("page.voyages.twin", "Twin track")}</h3>
                {twin ? (
                  <>
                    <p className="muted">
                      L{twin.level} · {twin.noon_track?.length || 0} noon points · {twin.port_calls?.length || 0} port calls
                    </p>
                    <table className="table">
                      <thead>
                        <tr>
                          <th>{t("page.voyages.at", "At")}</th>
                          <th>Lat</th>
                          <th>Lon</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(twin.noon_track || []).map((n, i) => (
                          <tr key={i}>
                            <td>{n.at ? toLocalInput(n.at).replace("T", " ") : "—"}</td>
                            <td>{n.lat ?? "—"}</td>
                            <td>{n.lon ?? "—"}</td>
                          </tr>
                        ))}
                        {!twin.noon_track?.length ? (
                          <tr>
                            <td colSpan={3} className="muted">
                              {t("page.voyages.no_track", "No noon track yet")}
                            </td>
                          </tr>
                        ) : null}
                      </tbody>
                    </table>
                  </>
                ) : (
                  <p className="muted">{t("page.voyages.twin_na", "Twin data unavailable (module or empty).")}</p>
                )}
              </div>
            </div>
          ) : (
            <div className="panel" style={{ marginTop: 0 }}>
              <p className="muted">{t("page.voyages.select", "Select a voyage")}</p>
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>{t("page.voyages.schedule", "Schedule blocks")}</h3>
        {conflicts.length ? (
          <p className="flash-err">
            {t("page.voyages.conflicts_n", "{n} hard conflict(s)", { n: conflicts.length })}
          </p>
        ) : (
          <p className="muted">{t("page.voyages.no_conflicts", "No hard conflicts")}</p>
        )}
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.title", "Title")}</th>
              <th>{t("page.voyages.block_type", "Type")}</th>
              <th>{t("page.voyages.start_at", "Start")}</th>
              <th>{t("page.voyages.end_at", "End")}</th>
              <th>{t("page.voyages.conflict", "Conflict")}</th>
            </tr>
          </thead>
          <tbody>
            {schedules.map((s) => (
              <tr key={s.id}>
                <td>{s.title}</td>
                <td>{s.block_type}</td>
                <td>{toLocalInput(s.start_at).replace("T", " ")}</td>
                <td>{toLocalInput(s.end_at).replace("T", " ")}</td>
                <td>
                  {s.hard_conflict ? (
                    <span className="badge badge-fail">{t("page.voyages.hard", "HARD")}</span>
                  ) : (
                    <span className="badge badge-pass">{t("page.voyages.ok", "ok")}</span>
                  )}
                </td>
              </tr>
            ))}
            {!schedules.length ? (
              <tr>
                <td colSpan={5} className="muted">
                  {t("common.empty", "No records")}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
