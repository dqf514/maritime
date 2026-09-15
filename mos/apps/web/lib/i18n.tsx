"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { API_BASE as API } from "./api";
const STORAGE_KEY = "voyageos_locale";

type Term = {
  key: string;
  label: string;
  definition?: string | null;
  category?: string;
  en?: string;
  zh_cn?: string;
  overridden?: boolean;
};

type Lang = { code: string; name: string; native_name: string; is_default?: boolean };

type Bundle = {
  locale: string;
  default_locale: string;
  allowed_locales: string[];
  allow_user_override: boolean;
  messages: Record<string, string>;
  terms: Record<string, Term>;
  languages: Lang[];
};

/** English string, or bilingual object when seed may be missing. */
export type TFallback = string | { en: string; zh?: string };

type I18nCtx = {
  locale: string;
  ready: boolean;
  languages: Lang[];
  t: (key: string, fallback?: TFallback, vars?: Record<string, string | number>) => string;
  term: (key: string, fallback?: string) => string;
  termDef: (key: string) => string;
  setLocale: (locale: string) => Promise<void>;
  reload: () => Promise<void>;
};

const Ctx = createContext<I18nCtx | null>(null);

function readStoredLocale(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(STORAGE_KEY);
}

function hasCjk(s: string): boolean {
  return /[\u4e00-\u9fff]/.test(s);
}

function resolveFallback(fallback: TFallback | undefined, locale: string): string | undefined {
  if (fallback == null) return undefined;
  if (typeof fallback === "string") return fallback;
  return locale.startsWith("zh") ? fallback.zh || fallback.en : fallback.en;
}

export function I18nProvider({ children, tenantCode }: { children: ReactNode; tenantCode?: string }) {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [ready, setReady] = useState(false);
  const [pendingLocale, setPendingLocale] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const stored = readStoredLocale();
    const qs = new URLSearchParams();
    if (stored) qs.set("locale", stored);
    if (tenantCode) qs.set("tenant_code", tenantCode);
    const headers: HeadersInit = {};
    const token = typeof window !== "undefined" ? localStorage.getItem("voyageos_token") : null;
    if (token) headers.Authorization = `Bearer ${token}`;
    if (stored) headers["Accept-Language"] = stored;
    const res = await fetch(`${API}/api/v1/i18n/bundle?${qs.toString()}`, { headers, credentials: "include" });
    if (!res.ok) {
      setReady(true);
      return;
    }
    const data = (await res.json()) as Bundle;
    setBundle(data);
    setPendingLocale(null);
    if (typeof document !== "undefined") {
      document.documentElement.lang = data.locale === "zh-CN" ? "zh-CN" : "en";
    }
    setReady(true);
  }, [tenantCode]);

  useEffect(() => {
    // Only touch localStorage after mount — avoids SSR/client locale mismatch.
    const stored = readStoredLocale();
    if (stored) {
      setPendingLocale(stored.startsWith("zh") ? "zh-CN" : "en");
    }
    reload().catch(() => setReady(true));
  }, [reload]);

  const setLocale = useCallback(
    async (locale: string) => {
      const next = locale.startsWith("zh") ? "zh-CN" : "en";
      localStorage.setItem(STORAGE_KEY, next);
      setPendingLocale(next);
      if (typeof document !== "undefined") {
        document.documentElement.lang = next === "zh-CN" ? "zh-CN" : "en";
      }
      // Session is the HttpOnly cookie; always persist locale server-side.
      // The legacy Bearer header is only kept as a fallback for pre-cookie sessions.
      const token = localStorage.getItem("voyageos_token");
      await fetch(`${API}/api/v1/me/locale`, {
        method: "PUT",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ locale: next }),
      }).catch(() => undefined);
      await reload();
    },
    [reload],
  );

  const value = useMemo<I18nCtx>(() => {
    const messages = bundle?.messages || {};
    const terms = bundle?.terms || {};
    // Never read localStorage during render (SSR vs client hydrate mismatch).
    const activeLocale = pendingLocale || bundle?.locale || "en";
    return {
      locale: activeLocale,
      ready,
      languages: bundle?.languages || [
        { code: "en", name: "English", native_name: "English" },
        { code: "zh-CN", name: "Chinese", native_name: "简体中文" },
      ],
      t: (key, fallback, vars) => {
        let s = messages[key];
        if (!s) {
          const fb = resolveFallback(fallback, activeLocale);
          if (fb) {
            // Block Chinese string-fallback leaking into English UI when seed is incomplete
            if (!activeLocale.startsWith("zh") && hasCjk(fb) && typeof fallback === "string") {
              s = key.includes(".") ? key.split(".").slice(-1)[0].replace(/_/g, " ") : key;
            } else {
              s = fb;
            }
          } else {
            s = key;
          }
        }
        if (vars) {
          for (const [k, v] of Object.entries(vars)) {
            s = s.replaceAll(`{${k}}`, String(v));
          }
        }
        return s;
      },
      term: (key, fallback) => terms[key]?.label || fallback || key,
      termDef: (key) => terms[key]?.definition || "",
      setLocale,
      reload,
    };
  }, [bundle, ready, pendingLocale, setLocale, reload]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n() {
  const ctx = useContext(Ctx);
  if (!ctx) {
    return {
      locale: "en",
      ready: true,
      languages: [] as Lang[],
      t: (key: string, fallback?: TFallback, vars?: Record<string, string | number>) => {
        let s = resolveFallback(fallback, "en") || key;
        if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
        return s;
      },
      term: (key: string, fallback?: string) => fallback || key,
      termDef: () => "",
      setLocale: async () => undefined,
      reload: async () => undefined,
    } satisfies I18nCtx;
  }
  return ctx;
}

export function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, setLocale, t, ready } = useI18n();
  // Until i18n is ready, render a stable EN-active state matching SSR defaults.
  const isZh = ready && Boolean(locale?.startsWith("zh"));
  return (
    <div
      className={className || "lang-switch"}
      role="group"
      aria-label={t("shell.language", "Language")}
      title={t("shell.language", "Language")}
      suppressHydrationWarning
    >
      <button
        type="button"
        className={isZh ? "active" : ""}
        aria-pressed={isZh}
        onClick={() => {
          setLocale("zh-CN").catch(() => undefined);
        }}
      >
        中文
      </button>
      <span className="lang-sep" aria-hidden>
        |
      </span>
      <button
        type="button"
        className={!isZh ? "active" : ""}
        aria-pressed={!isZh}
        onClick={() => {
          setLocale("en").catch(() => undefined);
        }}
      >
        EN
      </button>
    </div>
  );
}
