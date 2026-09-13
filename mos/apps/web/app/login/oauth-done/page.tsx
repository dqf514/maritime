"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useI18n } from "@/lib/i18n";

export default function OAuthDonePage() {
  const sp = useSearchParams();
  const router = useRouter();
  const { t } = useI18n();

  useEffect(() => {
    const token = sp.get("token");
    if (token) {
      localStorage.setItem("voyageos_token", token);
      router.replace("/home");
    } else {
      router.replace("/login?oauth_error=missing_token");
    }
  }, [sp, router]);

  return <p style={{ padding: "2rem" }}>{t("login.oauth_done", "Completing sign-in…")}</p>;
}
