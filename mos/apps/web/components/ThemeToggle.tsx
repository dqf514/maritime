"use client";

// 3-Theme 选择器 — 圆形色彩预览，点击切换

import { useState, useRef, useEffect } from "react";
import { THEMES, useTheme, type Theme } from "@/components/ThemeProvider";
import { useI18n } from "@/lib/i18n";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const current = THEMES.find((x) => x.id === theme) || THEMES[0];

  return (
    <div className="theme-picker-wrap" ref={ref}>
      <button
        type="button"
        className="theme-picker-btn"
        onClick={() => setOpen((v) => !v)}
        title={t("theme.switch", "切换主题")}
        aria-label={t("theme.switch", "切换主题")}
        aria-expanded={open}
      >
        <span className="theme-preview-dot" style={{ background: current.preview.accent }} />
        <span className="theme-preview-name">{current.name}</span>
      </button>
      {open ? (
        <div className="theme-picker-pop" role="menu">
          {THEMES.map((th) => (
            <button
              key={th.id}
              type="button"
              role="menuitem"
              className={`theme-picker-item ${theme === th.id ? "active" : ""}`}
              onClick={() => {
                setTheme(th.id);
                setOpen(false);
              }}
            >
              <span
                className="theme-preview-dot"
                style={{ background: th.preview.accent }}
              />
              <span className="theme-picker-label">
                <strong>{th.name}</strong>
                <small>{th.nameZh}</small>
              </span>
              <span
                className="theme-preview-strip"
                style={{
                  background: `linear-gradient(135deg, ${th.preview.bg} 50%, ${th.preview.accent} 50%)`,
                  borderColor: th.preview.accent,
                }}
              />
              {theme === th.id ? <span className="theme-picker-check">✓</span> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
