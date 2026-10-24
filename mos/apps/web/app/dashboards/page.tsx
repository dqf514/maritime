"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { HubTile } from "@/components/HubTile";
import { StateView } from "@/components/StateView";
import { apiGet } from "@/lib/api";
import { msgOf } from "@/lib/errors";
import { useI18n } from "@/lib/i18n";

type Screen = { role: string; title: string; subtitle: string; accent: string; href: string };

export default function DashboardsIndexPage() {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<{ default_role: string; screens: Screen[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const data = await apiGet("/api/v1/dashboards/catalog");
      setCatalog(data);
      setErr(null);
    } catch (ex) {
      setCatalog(null);
      setErr(msgOf(ex));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.dashboards", "Live dashboards") }]}
        title={t("page.dashboards.title", "Live dashboards")}
        subtitle={t(
          "page.dashboards.sub",
          "Role walls for owner / director / chartering / ops / finance / technical — fullscreen, live pulse.",
        )}
      />
      <StateView
        loading={loading}
        error={err ?? undefined}
        empty={!loading && !err && !(catalog?.screens || []).length}
        emptyText={t("page.dashboards.empty", "No dashboards available")}
        onRetry={() => void load()}
      >
        <div className="workbench-grid">
          {(catalog?.screens || []).map((s) => (
            <HubTile
              key={s.role}
              href={s.href}
              icon="dashboards"
              title={s.title}
              description={s.subtitle}
              style={{ borderTop: `3px solid ${s.accent}` }}
            />
          ))}
        </div>
      </StateView>
    </AppShell>
  );
}
