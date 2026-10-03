"use client";

// 3-Theme 系统 — Ocean / Slate / Indigo
// 取代原 dark/light 二元切换，写入 localStorage + 用户设置

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";

export type Theme = "ocean" | "slate" | "indigo";

export const THEMES: { id: Theme; name: string; nameZh: string; preview: { bg: string; accent: string; text: string } }[] = [
  {
    id: "ocean",
    name: "Ocean",
    nameZh: "海洋",
    preview: { bg: "#f4f6f8", accent: "#1A9B96", text: "#1a2332" },
  },
  {
    id: "slate",
    name: "Slate",
    nameZh: "暗夜",
    preview: { bg: "#0d1117", accent: "#58a6ff", text: "#e6edf3" },
  },
  {
    id: "indigo",
    name: "Indigo",
    nameZh: "靛蓝",
    preview: { bg: "#faf9ff", accent: "#6366f1", text: "#1e1b4b" },
  },
];

type ThemeCtx = {
  theme: Theme;
  setTheme: (t: Theme) => void;
  cycleTheme: () => void;
};

const Ctx = createContext<ThemeCtx | null>(null);
const STORAGE_KEY = "marios_theme";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "ocean";
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "ocean" || stored === "slate" || stored === "indigo") return stored;
  // 迁移旧值
  if (stored === "dark") return "slate";
  if (stored === "light") return "ocean";
  return "ocean";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("ocean");

  useEffect(() => {
    setThemeState(getInitialTheme());
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
  }, []);

  const cycleTheme = useCallback(() => {
    setThemeState((prev) => {
      const idx = THEMES.findIndex((x) => x.id === prev);
      return THEMES[(idx + 1) % THEMES.length].id;
    });
  }, []);

  return (
    <Ctx.Provider value={{ theme, setTheme, cycleTheme }}>
      {children}
    </Ctx.Provider>
  );
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useTheme must be used within <ThemeProvider>");
  return ctx;
}
