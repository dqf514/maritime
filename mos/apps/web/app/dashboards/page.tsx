"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { HubTile } from "@/components/HubTile";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Screen = { role: string; title: string; subtitle: string; accent: string; href: string };

export default function DashboardsIndexPage() {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<{ default_role: string; screens: Screen[] } | null>(null);

  useEffect(() => {
    apiGet("/api/v1/dashboards/catalog").then(setCatalog).catch(() => undefined);
  }, []);

  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("page.dashboards.title", "Live dashboards")}</h1>
          <p className="page-sub">
            {t(
              "page.dashboards.sub",
              "Role walls for owner / director / chartering / ops / finance / technical — fullscreen, live pulse.",
            )}
          </p>
        </div>
      </div>
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
    </AppShell>
  );
}
