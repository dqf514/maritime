"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { apiMe } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/** Knowledge Centre is in-app only — unauthenticated visitors are sent to login. */
export function HelpFrame({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { t } = useI18n();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Session lives in an HttpOnly cookie — probe /me instead of the legacy token.
    apiMe()
      .then(() => {
        if (!cancelled) setReady(true);
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (!ready) {
    return (
      <div className="login-page">
        <p>{t("common.loading", "Loading MariOS…")}</p>
      </div>
    );
  }

  return (
    <AppShell>
      <div className="help-in-app">{children}</div>
    </AppShell>
  );
}
