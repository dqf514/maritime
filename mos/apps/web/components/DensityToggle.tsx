"use client";

// 密度切换器：compact（Excel 级紧凑）/ comfortable（宽松）。
// 状态持久化到 localStorage.marios_density，并同步 <html data-density>。

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";

type Density = "compact" | "comfortable";

function getDensity(): Density {
  if (typeof window === "undefined") return "compact";
  const d = localStorage.getItem("marios_density");
  return d === "comfortable" ? "comfortable" : "compact";
}

export function DensityToggle() {
  const { t } = useI18n();
  const [density, setDensity] = useState<Density>("compact");

  useEffect(() => {
    setDensity(getDensity());
  }, []);

  function toggle() {
    const next: Density = density === "compact" ? "comfortable" : "compact";
    setDensity(next);
    localStorage.setItem("marios_density", next);
    document.documentElement.dataset.density = next;
  }

  return (
    <button
      type="button"
      className="density-toggle"
      onClick={toggle}
      title={t("density.toggle", density === "compact" ? "Switch to comfortable" : "Switch to compact")}
      aria-label={t("density.toggle", "Toggle density")}
    >
      {density === "compact" ? (
        // 密集图标：横线紧凑
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M2 3h12M2 5.5h12M2 8h12M2 10.5h12M2 13h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      ) : (
        // 宽松图标：横线稀疏
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <path d="M2 3h12M2 8h12M2 13h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      )}
    </button>
  );
}
