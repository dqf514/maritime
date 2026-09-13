"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Kpi = { label: string; value: string | number; unit?: string; delta?: string | null; tone?: string };
type SeriesPoint = { t: string | number; v: number };
type Chart = { id: string; title: string; type: string; series: SeriesPoint[] };
type Snapshot = {
  role: string;
  title: string;
  subtitle: string;
  accent: string;
  generated_at: string;
  refresh_hint_sec: number;
  kpis: Kpi[];
  charts: Chart[];
  fleet_positions?: { name: string; lat: number; lon: number; status: string; speed?: number }[];
  feed?: { tone: string; text: string; ts?: string | null }[];
  heatmap?: { label: string; value: number }[];
  table?: { title: string; columns: string[]; rows: Record<string, unknown>[] };
};

function Sparkline({ series, color }: { series: SeriesPoint[]; color: string }) {
  if (!series.length) {
    return (
      <svg viewBox="0 0 220 56" className="dash-spark" aria-hidden>
        <line x1="8" y1="28" x2="212" y2="28" stroke={color} strokeOpacity="0.25" strokeWidth="2" />
      </svg>
    );
  }
  const vals = series.map((s) => s.v);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const w = 220;
  const h = 56;
  const pts = vals
    .map((v, i) => {
      const x = (i / Math.max(1, vals.length - 1)) * w;
      const y = h - ((v - min) / Math.max(0.0001, max - min)) * (h - 8) - 4;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="dash-spark" aria-hidden>
      <polyline fill="none" stroke={color} strokeWidth="2.2" points={pts} />
    </svg>
  );
}

function Bars({ series, color }: { series: SeriesPoint[]; color: string }) {
  const max = Math.max(...series.map((s) => s.v), 1);
  return (
    <div className="dash-bars">
      {series.map((s, i) => (
        <div key={i} className="dash-bar-col" title={`${s.t}: ${s.v}`}>
          <div className="dash-bar" style={{ height: `${(s.v / max) * 100}%`, background: color }} />
          <span>{String(s.t).slice(0, 6)}</span>
        </div>
      ))}
    </div>
  );
}

function Donut({ series, color }: { series: SeriesPoint[]; color: string }) {
  const total = series.reduce((a, b) => a + b.v, 0) || 1;
  let acc = 0;
  const stops = series
    .map((s, i) => {
      const start = (acc / total) * 100;
      acc += s.v;
      const end = (acc / total) * 100;
      const c = ["#2bb5b0", "#3d8bfd", "#f0a020", "#8b5cf6", color][i % 5];
      return `${c} ${start}% ${end}%`;
    })
    .join(", ");
  return (
    <div className="dash-donut-wrap">
      <div className="dash-donut" style={{ background: `conic-gradient(${stops})` }} />
      <ul>
        {series.map((s) => (
          <li key={String(s.t)}>
            <strong>{s.v}</strong> {s.t}
          </li>
        ))}
      </ul>
    </div>
  );
}

function OceanMap({ positions }: { positions: NonNullable<Snapshot["fleet_positions"]> }) {
  return (
    <div className="dash-ocean">
      <div className="dash-ocean-grid" />
      {positions.map((p, i) => {
        const x = ((p.lon + 180) / 360) * 100;
        const y = ((90 - p.lat) / 180) * 100;
        return (
          <div
            key={p.name + i}
            className={`dash-ship ${p.status}`}
            style={{ left: `${Math.min(96, Math.max(2, x))}%`, top: `${Math.min(92, Math.max(4, y))}%` }}
            title={`${p.name} ${p.status}`}
          >
            <span />
            <em>{p.name.replace(/^MV /, "")}</em>
          </div>
        );
      })}
    </div>
  );
}

export default function RoleDashboardPage() {
  const { t } = useI18n();
  const params = useParams();
  const role = String(params.role || "management");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [fullscreen, setFullscreen] = useState(false);
  const [clock, setClock] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    apiGet(`/api/v1/dashboards/${role}/snapshot`)
      .then((d) => {
        setSnap(d);
        setError("");
      })
      .catch(() => setError(t("page.dash.error", "Unable to load dashboard (role/permission).")));
  }, [role, t]);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleString());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    function onFs() {
      setFullscreen(Boolean(document.fullscreenElement));
    }
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  async function toggleFs() {
    const el = rootRef.current;
    if (!el) return;
    if (!document.fullscreenElement) await el.requestFullscreen();
    else await document.exitFullscreen();
  }

  const accent = snap?.accent || "#2bb5b0";
  const kpis = snap?.kpis || [];

  const headerMeta = useMemo(() => {
    if (!snap) return "";
    return t("page.dash.live", "Live · refreshed {time}", {
      time: new Date(snap.generated_at).toLocaleTimeString(),
    });
  }, [snap, t]);

  const wall = (
    <div ref={rootRef} className={`dash-wall ${fullscreen ? "is-fs" : ""}`} style={{ ["--dash-accent" as string]: accent }}>
      <header className="dash-top">
        <div>
          <p className="dash-eyebrow">VoyageOS · {role}</p>
          <h1>{snap?.title || t("page.dash.loading", "Loading wall…")}</h1>
          <p>{snap?.subtitle}</p>
        </div>
        <div className="dash-top-actions">
          <div className="dash-clock">
            <strong>{clock}</strong>
            <span>{headerMeta}</span>
          </div>
          <button type="button" className="dash-btn" onClick={load}>
            {t("page.dash.refresh", "Refresh")}
          </button>
          <button type="button" className="dash-btn primary" onClick={toggleFs}>
            {fullscreen ? t("page.dash.exit_fs", "Exit fullscreen") : t("page.dash.fullscreen", "Fullscreen")}
          </button>
          <Link href="/dashboards" className="dash-btn">
            {t("page.dash.all", "All walls")}
          </Link>
          <Link href="/home" className="dash-btn">
            {t("page.dash.workbench", "Workbench")}
          </Link>
        </div>
      </header>

      {error ? <p className="dash-error">{error}</p> : null}

      <section className="dash-kpis">
        {kpis.map((k) => (
          <article key={k.label} className={`dash-kpi tone-${k.tone || "neutral"}`}>
            <span>{k.label}</span>
            <strong>
              {k.value}
              {k.unit ? <small> {k.unit}</small> : null}
            </strong>
            {k.delta ? <em>{k.delta}</em> : null}
          </article>
        ))}
      </section>

      <section className="dash-main">
        <div className="dash-col">
          {(snap?.charts || []).map((c) => (
            <div key={c.id} className="dash-panel">
              <h3>{c.title}</h3>
              {c.type === "line" ? <Sparkline series={c.series} color={accent} /> : null}
              {c.type === "bar" ? <Bars series={c.series} color={accent} /> : null}
              {c.type === "donut" ? <Donut series={c.series} color={accent} /> : null}
            </div>
          ))}
          {(snap?.heatmap || []).length ? (
            <div className="dash-panel">
              <h3>{t("page.dash.heat", "Heat")}</h3>
              <div className="dash-heat">
                {snap!.heatmap!.map((h) => (
                  <div key={h.label} className="dash-heat-cell">
                    <div className="dash-heat-fill" style={{ opacity: 0.25 + h.value / 140, background: accent }} />
                    <strong>{h.value}</strong>
                    <span>{h.label}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="dash-col wide">
          {(snap?.fleet_positions || []).length ? (
            <div className="dash-panel grow">
              <h3>{t("page.dash.fleet", "Fleet situation")}</h3>
              <OceanMap positions={snap!.fleet_positions!} />
            </div>
          ) : null}
          {snap?.table?.rows?.length ? (
            <div className="dash-panel">
              <h3>{snap.table.title}</h3>
              <div className="dash-table-wrap">
                <table>
                  <thead>
                    <tr>
                      {snap.table.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {snap.table.rows.slice(0, 8).map((r, i) => (
                      <tr key={i}>
                        {snap.table!.columns.map((c) => (
                          <td key={c}>{String(r[c] ?? "—")}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>

        <div className="dash-col">
          <div className="dash-panel grow">
            <h3>{t("page.dash.feed", "Live feed")}</h3>
            <ul className="dash-feed">
              {(snap?.feed || []).map((f, i) => (
                <li key={i} className={`tone-${f.tone}`}>
                  <span />
                  <div>
                    <p>{f.text}</p>
                    {f.ts ? <small>{new Date(f.ts).toLocaleTimeString()}</small> : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );

  return <AppShell>{wall}</AppShell>;
}
