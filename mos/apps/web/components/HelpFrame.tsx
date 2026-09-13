"use client";

import { ReactNode, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { useI18n } from "@/lib/i18n";

/** Knowledge Centre is in-app only — unauthenticated visitors are sent to login. */
export function HelpFrame({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { t } = useI18n();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!localStorage.getItem("voyageos_token")) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  if (!ready) {
    return (
      <div className="login-page">
        <p>{t("common.loading", "Loading VoyageOS…")}</p>
      </div>
    );
  }

  return (
    <AppShell>
      <div className="help-in-app">{children}</div>
    </AppShell>
  );
}
