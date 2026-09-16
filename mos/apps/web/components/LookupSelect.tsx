"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export type LookupItem = {
  id?: string;
  code: string;
  label: string;
  label_en?: string;
  label_zh?: string;
  active?: boolean;
};

type Props = {
  dataset: string;
  value: string;
  onChange: (code: string) => void;
  allowEmpty?: boolean;
  emptyLabel?: string;
  required?: boolean;
  disabled?: boolean;
  className?: string;
  /** 显示「代码 — 标签」 */
  showCode?: boolean;
};

const CACHE_TTL_MS = 10 * 60 * 1000;

const cache = new Map<string, { at: number; rows: LookupItem[] }>();

function tenantScope(): string {
  if (typeof window === "undefined") return "ssr";
  const token = localStorage.getItem("marios_token") || "";
  let h = 0;
  for (let i = 0; i < token.length; i++) h = (h * 31 + token.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

function cacheGet(key: string): LookupItem[] | null {
  const hit = cache.get(key);
  if (!hit) return null;
  if (Date.now() - hit.at > CACHE_TTL_MS) {
    cache.delete(key);
    return null;
  }
  return hit.rows;
}

export function LookupSelect({
  dataset,
  value,
  onChange,
  allowEmpty = true,
  emptyLabel,
  required,
  disabled,
  className,
  showCode = true,
}: Props) {
  const { t, locale } = useI18n();
  const [items, setItems] = useState<LookupItem[]>([]);
  const [filter, setFilter] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const loc = locale?.startsWith("zh") ? "zh-CN" : "en";
    const key = `${tenantScope()}:${dataset}:${loc}`;
    const cached = cacheGet(key);
    if (cached) {
      setItems(cached);
      setLoaded(true);
      return;
    }
    apiGet(`/api/v1/reference/${encodeURIComponent(dataset)}/items?locale=${encodeURIComponent(loc)}`)
      .then((rows: LookupItem[]) => {
        if (cancelled) return;
        cache.set(key, { at: Date.now(), rows });
        setItems(rows);
        setLoaded(true);
      })
      .catch(() => {
        if (!cancelled) {
          setItems([]);
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [dataset, locale]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) =>
        it.code.toLowerCase().includes(q) ||
        (it.label || "").toLowerCase().includes(q) ||
        (it.label_en || "").toLowerCase().includes(q) ||
        (it.label_zh || "").toLowerCase().includes(q),
    );
  }, [items, filter]);

  const longList = items.length > 40;
  const valueInList = items.some((it) => it.code === value);

  return (
    <div className={className} style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
      {longList ? (
        <input
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={t("lookup.filter", "Filter…")}
          disabled={disabled}
          aria-label={t("lookup.filter", "Filter…")}
        />
      ) : null}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        disabled={disabled || !loaded}
      >
        {allowEmpty ? <option value="">{emptyLabel || t("common.select", "Select…")}</option> : null}
        {value && !valueInList ? (
          <option value={value}>
            {value} ({t("lookup.legacy", "legacy value")})
          </option>
        ) : null}
        {filtered.map((it) => (
          <option key={it.code} value={it.code}>
            {showCode ? `${it.code} — ${it.label}` : it.label}
          </option>
        ))}
      </select>
      {!loaded ? <span className="muted">{t("common.loading", "Loading…")}</span> : null}
    </div>
  );
}

/** 清除 LookupSelect 内存缓存（管理页保存后、退出登录时调用） */
export function clearLookupCache(dataset?: string) {
  if (!dataset) {
    cache.clear();
    return;
  }
  for (const k of [...cache.keys()]) {
    if (k.split(":")[1] === dataset) cache.delete(k);
  }
}
