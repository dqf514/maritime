"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { StateView } from "@/components/StateView";
import { apiGet } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";
import { parseUtc } from "@/lib/datetime";

type TenantUsage = {
  id: string;
  code: string;
  name: string;
  status: string;
  users: number;
  voyages: number;
  invoices: number;
  tasks: number;
};

type Health = {
  tenant_count?: number;
  active?: number;
  suspended?: number;
  api_version?: string;
  checked_at?: string;
  resources?: {
    disk_pct?: number;
    db_ping_ms?: number;
    db_up?: boolean;
    db_size_bytes?: number | null;
    cpu_count?: number;
  };
  tenants_usage?: TenantUsage[];
  [k: string]: unknown;
};

function fmtBytes(n?: number | null): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

/** ISO 时间戳 → UTC 可读 `YYYY-MM-DD HH:mm:ss`（平台存储基准为 UTC） */
function formatTs(raw?: string): string {
  if (!raw) return "—";
  const d = parseUtc(raw);
  if (!d) return raw;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

export default function PlatformHealthPage() {
  const { t } = useI18n();
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setErr(null);
    try {
      setHealth(await apiGet("/api/v1/platform/health"));
    } catch (ex) {
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const res = health?.resources;
  const stats: { key: string; label: string; value: string }[] = [
    { key: "tenant_count", label: t("page.health.tenants", "租户总数"), value: String(health?.tenant_count ?? "—") },
    { key: "active", label: t("page.health.active", "活跃租户"), value: String(health?.active ?? "—") },
    { key: "suspended", label: t("page.health.suspended", "已停用"), value: String(health?.suspended ?? "—") },
    { key: "disk", label: t("page.health.disk", "磁盘占用"), value: res ? `${res.disk_pct ?? 0}%` : "—" },
    { key: "ping", label: t("page.health.db_ping", "DB 延迟"), value: res ? `${res.db_ping_ms ?? 0} ms` : "—" },
    { key: "dbsize", label: t("page.health.db_size", "库大小"), value: fmtBytes(res?.db_size_bytes) },
    { key: "cpu", label: t("page.health.cpu", "CPU 核"), value: res ? String(res.cpu_count ?? "—") : "—" },
  ];

  const meta: { key: string; label: string; value: string }[] = [
    { key: "api_version", label: t("page.health.api_version", "API 版本"), value: health?.api_version || "—" },
    { key: "db_up", label: t("page.health.db_up", "数据库"), value: res ? (res.db_up ? t("page.health.db_ok", "正常") : t("page.health.db_down", "不可用")) : "—" },
    { key: "checked_at", label: t("page.health.checked_at", "检查时间"), value: formatTs(health?.checked_at) },
  ];

  const tenants = health?.tenants_usage || [];

  return (
    <AppShell>
      <PageHeader
        title={t("page.health.title", "Platform health")}
        subtitle={t("page.health.sub", "Cross-tenant probes and estate status.")}
        breadcrumb={[{ label: t("page.platform.title", "Platform"), href: "/platform" }, { label: t("page.health.title", "Platform health") }]}
      />
      <StateView loading={loading} error={err ?? undefined} empty={false} onRetry={() => load()}>
        {health ? (
          <>
          <div className="wb-kpi-strip">
            {stats.map((s) => (
              <div key={s.key} className="wb-kpi-item">
                <span className="wb-kpi-val">{s.value}</span>
                <span className="wb-kpi-label">{s.label}</span>
              </div>
            ))}
          </div>
          <div className="panel">
            <dl className="kv-grid">
              {meta.map((m) => (
                <div key={m.key}>
                  <dt>{m.label}</dt>
                  <dd>{m.value}</dd>
                </div>
              ))}
            </dl>
          </div>

          {/* Per-tenant usage 明细 */}
          <div className="panel">
            <h2 className="panel-title">{t("page.health.tenant_usage", "各租户明细")}</h2>
            {tenants.length ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("page.health.col_code", "代码")}</th>
                    <th>{t("page.health.col_name", "名称")}</th>
                    <th>{t("page.health.col_status", "状态")}</th>
                    <th className="num">{t("page.health.col_users", "用户")}</th>
                    <th className="num">{t("page.health.col_voyages", "航次")}</th>
                    <th className="num">{t("page.health.col_invoices", "发票")}</th>
                    <th className="num">{t("page.health.col_tasks", "任务")}</th>
                  </tr>
                </thead>
                <tbody>
                  {tenants.map((tu) => (
                    <tr key={tu.id}>
                      <td>{tu.code}</td>
                      <td>{tu.name}</td>
                      <td>
                        <span className={`status-badge ${tu.status === "active" ? "ok" : "warn"}`}>{tu.status}</span>
                      </td>
                      <td className="num">{tu.users}</td>
                      <td className="num">{tu.voyages}</td>
                      <td className="num">{tu.invoices}</td>
                      <td className="num">{tu.tasks}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">{t("page.health.no_tenants", "暂无租户")}</p>
            )}
          </div>
        </>
        ) : null}
      </StateView>
    </AppShell>
  );
}
