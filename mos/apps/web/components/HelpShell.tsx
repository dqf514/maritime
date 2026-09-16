"use client";

import Link from "next/link";
import { ReactNode, useEffect, useState } from "react";
import { apiMe } from "@/lib/api";
import { LanguageSwitcher, useI18n } from "@/lib/i18n";

export function HelpShell({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    // Session lives in an HttpOnly cookie — probe /me instead of the legacy token.
    apiMe()
      .then(() => setSignedIn(true))
      .catch(() => setSignedIn(false));
  }, []);

  return (
    <div className="help-shell">
      <header className="help-top">
        <Link href="/help" className="help-brand">
          <img src="/branding/mark.svg" alt="" width={28} height={28} />
          <span>
            MariOS
            <em>{t("help.centre", "Knowledge Centre")}</em>
          </span>
        </Link>
        <nav className="help-nav">
          <Link href="/help">{t("help.home", "Browse")}</Link>
          <Link href="/help?ask=1">{t("help.ask_link", "Ask")}</Link>
          {signedIn ? (
            <Link href="/home">{t("help.back_app", "Back to app")}</Link>
          ) : (
            <Link href="/login">{t("help.sign_in", "Sign in")}</Link>
          )}
          <LanguageSwitcher />
        </nav>
      </header>
      <main className="help-main">{children}</main>
      <footer className="help-foot">
        <span>© {new Date().getFullYear()} MariOS</span>
        <span>{t("help.foot", "Product documentation — search and ask anytime.")}</span>
      </footer>
    </div>
  );
}
