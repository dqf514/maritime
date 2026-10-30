"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { DetailRail } from "@/components/masterdetail/DetailRail";
import { MasterDetail } from "@/components/masterdetail/MasterDetail";
import { PageHeader } from "@/components/PageHeader";
import { apiGet } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n, type TFallback } from "@/lib/i18n";
import { useListBackHref } from "@/lib/listContext";
import { maxOf, minOf } from "@/lib/numbers";
import { formatInTz } from "@/lib/datetime";

type Kpi = { label: string; value: string | number; unit?: string; delta?: string | null; tone?: string; synthetic?: boolean };
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
type Screen = { role: string; title: string; subtitle: string; accent: string; href: string };

function Sparkline({ series, color }: { series: SeriesPoint[]; color: string }) {
  if (!series.length) {
    return (
      <svg viewBox="0 0 220 56" className="dash-spark" aria-hidden>
        <line x1="8" y1="28" x2="212" y2="28" stroke={color} strokeOpacity="0.25" strokeWidth="2" />
      </svg>
    );
  }
  const vals = series.map((s) => s.v);
  const min = minOf(vals, (v) => v);
  const max = maxOf(vals, (v) => v);
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
  const max = maxOf(series, (s) => s.v, 1);
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
      {/* 无障碍：海图是纯位置图形 —— 补一份可读的船位清单 */}
      <ul className="sr-only">
        {positions.map((p, i) => (
          <li key={`sr-ship-${p.name}-${i}`}>
            {p.name} — {p.status} — {p.lat.toFixed(2)}, {p.lon.toFixed(2)}
            {p.speed != null ? ` — ${p.speed} kn` : ""}
          </li>
        ))}
      </ul>
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

/** 图表的文字摘要 —— 纯图表块必须可读（无障碍 + 无法看图的用户）。 */
function chartSummary(c: Chart, t: (key: string, fallback?: TFallback, vars?: Record<string, string | number>) => string) {
  const vals = (c.series || []).map((s) => s.v);
  if (!vals.length) return t("page.dash.chart_empty", "No data points");
  const min = minOf(vals, (v) => v);
  const max = maxOf(vals, (v) => v);
  const last = vals[vals.length - 1];
  return t("page.dash.chart_summary", "{n} points · min {min} · max {max} · latest {last}", {
    n: vals.length,
    min,
    max,
    last,
  });
}

export default function RoleDashboardPage() {
  const { t } = useI18n();
  const router = useRouter();
  const params = useParams();
  const role = String(params.role || "management");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [fullscreen, setFullscreen] = useState(false);
  const [clock, setClock] = useState("");
  const [screens, setScreens] = useState<Screen[]>([]);
  /** 看板目录（参考数据）加载失败 */
  const [catalogErr, setCatalogErr] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const switcherRef = useRef<HTMLDivElement>(null);

  // 左栏：兄弟看板清单（IMOS 式）+「返回列表」
  const backHref = useListBackHref("/dashboards");
  const railItems = useMemo(() => {
    const items = screens.map((s) => ({
      id: s.role,
      title: s.title,
      meta: [s.subtitle].filter(Boolean) as string[],
      href: s.href,
    }));
    if (!items.some((it) => it.id === role)) {
      items.push({ id: role, title: snap?.title || role, meta: [], href: `/dashboards/${role}` });
    }
    return items;
  }, [screens, role, snap]);

  const load = useCallback(() => {
    apiGet(`/api/v1/dashboards/${role}/snapshot`)
      .then((d) => {
        setSnap(d);
        setError("");
      })
      .catch((ex) => setError(msgOf(ex, t("page.dash.error", "Unable to load dashboard (role/permission)."))));
  }, [role, t]);

  useEffect(() => {
    apiGet("/api/v1/dashboards/catalog")
      .then((c) => {
        setScreens(c.screens || []);
        setCatalogErr(null);
      })
      // 看板目录取数失败 ≠ 没有看板：给出可见提示
      .catch((ex) => setCatalogErr(msgOf(ex)));
  }, []);

  useEffect(() => {
    load();
    // 轮询在标签页不可见时暂停：后台标签没必要每 5 秒打一次 API，
    // 回到前台时立刻补一次最新数据。
    let id: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (id !== null) return;
      id = setInterval(load, 5000);
    };
    const stop = () => {
      if (id === null) return;
      clearInterval(id);
      id = null;
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") stop();
      else {
        void load();
        start();
      }
    };
    if (document.visibilityState !== "hidden") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
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

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!switcherRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    if (menuOpen) {
      document.addEventListener("mousedown", onDoc);
      document.addEventListener("keydown", onKey);
    }
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  useEffect(() => {
    setMenuOpen(false);
  }, [role]);

  async function toggleFs() {
    const el = rootRef.current;
    if (!el) return;
    if (!document.fullscreenElement) await el.requestFullscreen();
    else await document.exitFullscreen();
  }

  function switchScreen(href: string, nextRole: string) {
    setMenuOpen(false);
    if (nextRole === role) return;
    router.push(href);
  }

  const accent = snap?.accent || "#2bb5b0";
  const kpis = snap?.kpis || [];

  const headerMeta = useMemo(() => {
    if (!snap) return "";
    return t("page.dash.live", "Live · refreshed {time}", {
      time: formatInTz(snap.generated_at, null, { year: undefined, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }),
    });
  }, [snap, t]);

  const wall = (
    <div ref={rootRef} className={`dash-wall ${fullscreen ? "is-fs" : ""}`}>
      <header className="dash-top">
        <PageHeader
          left={<p className="dash-eyebrow">MariOS · {role}</p>}
          breadcrumb={[
            { label: t("nav.dashboards", "Live dashboards"), href: "/dashboards" },
            { label: snap?.title || role },
          ]}
          title={snap?.title || t("page.dash.loading", "Loading wall…")}
          subtitle={snap?.subtitle}
          actions={
            <>
              {screens.length > 1 ? (
                <div className={`dash-switcher ${menuOpen ? "open" : ""}`} ref={switcherRef}>
                  <button
                    type="button"
                    className="dash-switcher-btn"
                    aria-haspopup="listbox"
                    aria-expanded={menuOpen}
                    aria-label={t("page.dash.switch", "Switch dashboard")}
                    onClick={() => setMenuOpen((o) => !o)}
                  >
                    <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden>
                      <path fill="currentColor" d="M5.3 7.3a1 1 0 0 1 1.4 0L10 10.6l3.3-3.3a1 1 0 1 1 1.4 1.4l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 0 1 0-1.4z" />
                    </svg>
                  </button>
                  {menuOpen ? (
                    <ul className="dash-switcher-menu" role="listbox">
                      {screens.map((s) => (
                        <li key={s.role} role="option" aria-selected={s.role === role}>
                          <button
                            type="button"
                            className={s.role === role ? "active" : ""}
                            onClick={() => switchScreen(s.href, s.role)}
                          >
                            <i style={{ background: s.accent }} />
                            <span>
                              <strong>{s.title}</strong>
                              <small>{s.subtitle}</small>
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}
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
            </>
          }
        />
      </header>

      {error ? <p className="dash-error">{error}</p> : null}
      {catalogErr ? (
        <p className="dash-error">
          {t("page.dash.catalog_fail", "Dashboard catalogue could not be loaded: {msg}", { msg: catalogErr })}
        </p>
      ) : null}

      <section className="dash-kpis">
        {kpis.map((k) => (
          <article key={k.label} className={`dash-kpi tone-${k.tone || "neutral"}`}>
            <span>
              {k.label}
              {k.synthetic ? <small className="dash-kpi-demo">{t("page.dash.synthetic", "Demo")}</small> : null}
            </span>
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
          {(snap?.charts || []).map((c) => {
            // P2：纯图表必须有可读的文字摘要（屏幕阅读器/无法看图的用户）
            const summary = chartSummary(c, t);
            return (
              <div key={c.id} className="dash-panel">
                <h3>{c.title}</h3>
                <div role="img" aria-label={summary}>
                  {c.type === "line" ? <Sparkline series={c.series} color={accent} /> : null}
                  {c.type === "bar" ? <Bars series={c.series} color={accent} /> : null}
                  {c.type === "donut" ? <Donut series={c.series} color={accent} /> : null}
                </div>
                <p className="muted">{summary}</p>
              </div>
            );
          })}
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
              {snap.table.rows.length > 8 ? (
                <p className="muted">
                  {t("page.dash.table_rows_shown", "Showing the first 8 of {n} rows", { n: snap.table.rows.length })}
                </p>
              ) : null}
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
                    {f.ts ? <small>{formatInTz(f.ts, null, { year: undefined, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</small> : null}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );

  return (
    <AppShell
      breadcrumbs={[
        { label: t("nav.dashboards", "Live dashboards"), href: backHref },
        { label: snap?.title || role },
      ]}
    >
      <MasterDetail
        rail={
          <DetailRail
            items={railItems}
            activeId={role}
            title={t("nav.dashboards", "Live dashboards")}
            backHref={backHref}
            backLabel={t("common.back_to_list", { en: "Back to list", zh: "返回列表" })}
            loading={!screens.length && !catalogErr}
            error={catalogErr}
            onRetry={() => void load()}
          />
        }
      >
        {wall}
      </MasterDetail>
    </AppShell>
  );
}
