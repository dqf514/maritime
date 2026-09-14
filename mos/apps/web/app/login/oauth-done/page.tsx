"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useI18n } from "@/lib/i18n";

function OAuthDonePage() {
  const sp = useSearchParams();
  const router = useRouter();
  const { t } = useI18n();

  useEffect(() => {
    // DEPRECATED compat: the OAuth callback still appends ?token= to this URL,
    // but the session is the HttpOnly cookie it set on the redirect — the query
    // token is never persisted anymore. Presence of the param just signals success.
    const token = sp.get("token");
    if (token) {
      router.replace("/home");
    } else {
      router.replace("/login?oauth_error=missing_token");
    }
  }, [sp, router]);

  return <p style={{ padding: "2rem" }}>{t("login.oauth_done", "Completing sign-in…")}</p>;
}

export default function OAuthDonePageWrapper() {
  return (
    <Suspense>
      <OAuthDonePage />
    </Suspense>
  );
}
