"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function PlatformHealthPage() {
  const { t } = useI18n();
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    apiGet("/api/v1/platform/health").then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <AppShell>
      <PageHeader
        title={t("page.health.title", "Platform health")}
        subtitle={t("page.health.sub", "Cross-tenant probes and estate status.")}
        breadcrumb={[{ label: t("page.platform.title", "Platform"), href: "/platform" }, { label: t("page.health.title", "Platform health") }]}
      />
      <div className="panel">
        {!health ? (
          <p className="muted">{t("common.loading", "加载中…")}</p>
        ) : (
          <dl className="kv-grid">
            {Object.entries(health).map(([key, val]) => (
              <div key={key}>
                <dt>
                  <code>{key}</code>
                </dt>
                <dd>
                  {val === null || typeof val !== "object" ? (
                    String(val)
                  ) : (
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(val, null, 2)}</pre>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </AppShell>
  );
}
