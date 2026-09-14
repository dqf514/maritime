"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useI18n } from "@/lib/i18n";

import { API_BASE as API } from "@/lib/api";

function MagicLinkPage() {
  const sp = useSearchParams();
  const router = useRouter();
  const { t } = useI18n();
  const [errorKey, setErrorKey] = useState<"missing" | "bad" | "">("");

  useEffect(() => {
    const token = sp.get("token");
    if (!token) {
      setErrorKey("missing");
      return;
    }
    fetch(`${API}/api/v1/auth/magic-link/confirm`, {
      method: "POST",
      credentials: "include", // required so the Set-Cookie session is stored
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        await res.json().catch(() => ({}));
        if (!res.ok) throw new Error("fail");
        // Cookie session planted by the server — just navigate.
        router.replace("/home");
      })
      .catch(() => setErrorKey("bad"));
  }, [sp, router]);

  const error =
    errorKey === "missing"
      ? t("login.magic_missing", "Missing token")
      : errorKey === "bad"
        ? t("login.magic_bad", "Invalid or expired magic link")
        : "";

  return (
    <div className="login-stage">
      <div className="login-stage-bg" aria-hidden />
      <div className="login-card" style={{ maxWidth: 420, margin: "4rem auto", position: "relative", zIndex: 1 }}>
        <h1 style={{ marginTop: 0 }}>{t("login.magic_title", "Magic link")}</h1>
        {error ? (
          <>
            <div className="error">{error}</div>
            <Link href="/login">{t("login.magic_back", "Back to sign-in")}</Link>
          </>
        ) : (
          <p>{t("login.magic_signing", "Signing you in…")}</p>
        )}
      </div>
    </div>
  );
}

export default function MagicLinkPageWrapper() {
  return (
    <Suspense>
      <MagicLinkPage />
    </Suspense>
  );
}
