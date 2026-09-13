"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
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
      <h1 style={{ marginTop: 0 }}>{t("page.health.title", "Platform health")}</h1>
      <p className="page-sub">{t("page.health.sub", "Cross-tenant probes and estate status.")}</p>
      <div className="panel">
        <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(health, null, 2)}</pre>
      </div>
    </AppShell>
  );
}
