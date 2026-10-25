"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { msgOf } from "@/lib/errors";

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

// U9 最近使用：按数据集记住最近选择，置顶显示（日常工作减少翻找）
const RECENT_MAX = 5;

function recentGet(dataset: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = JSON.parse(localStorage.getItem(`marios_recent_${tenantScope()}_${dataset}`) || "[]");
    return Array.isArray(raw) ? raw.slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function recentPush(dataset: string, code: string) {
  if (typeof window === "undefined" || !code) return;
  const next = [code, ...recentGet(dataset).filter((c) => c !== code)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(`marios_recent_${tenantScope()}_${dataset}`, JSON.stringify(next));
  } catch {
    // 忽略存储失败
  }
}

/** 拉取参照表条目（带内存缓存 + locale 打标）。LookupSelect 与直接渲染
 *  checkbox 的页面（如对手方类型多选）共用同一份缓存。 */
export function useLookupItems(dataset: string): { items: LookupItem[]; loaded: boolean; error: string } {
  const { t, locale } = useI18n();
  const [items, setItems] = useState<LookupItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  // P1-4：参照表取不到时不能只剩一个空控件 —— 用户会以为「这个表没有可选值」，
  // 其实是没取到。单独留一个错误状态，明确说出来。
  // 错误按「数据集 + 语言」打标：换参照表时旧错误自动失效（不必在 effect 里
  // setState 清空 —— 那会触发 react-hooks/set-state-in-effect）。
  const [err, setErr] = useState<{ key: string; msg: string } | null>(null);
  const errKey = `${dataset}:${locale?.startsWith("zh") ? "zh-CN" : "en"}`;
  const loadError = err && err.key === errKey ? err.msg : "";

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
        setErr(null);
      })
      .catch((ex) => {
        if (cancelled) return;
        setItems([]);
        setLoaded(true);
        setErr({
          key: `${dataset}:${loc}`,
          msg: msgOf(ex, t("lookup.load_fail", "Reference list could not be loaded — please retry.")),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [dataset, locale, t]);

  return { items, loaded, error: loadError };
}

/** 选项行文案：showCode 时「代码 — 标签」 */
function itemText(it: LookupItem, showCode: boolean): string {
  return showCode ? `${it.code} — ${it.label}` : it.label;
}

/** 参照表选择控件 —— 单框 combobox：点开/输入即过滤，选项浮层下拉（下方空间
 *  不足时向上翻），键盘 ↑↓ 选择、Enter 确认、Esc 关闭。历史版本对长列表渲染
 *  「筛选输入框 + 原生 select」两个框叠放，观感割裂 —— 合并为一个框。 */
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
  const { t } = useI18n();
  const { items, loaded, error: loadError } = useLookupItems(dataset);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const [flipUp, setFlipUp] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // 浮层菜单：输入框下方空间不够（视口或滚动容器内）时向上翻
  const updateFlip = () => {
    const el = inputRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    setFlipUp(spaceBelow < 240 && rect.top > spaceBelow);
  };

  // 点击浮层外关闭（pointerdown 先于 input blur，选项上的点击用 preventDefault 保住焦点）
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [open]);

  // 键盘高亮项滚动进可视区
  useEffect(() => {
    if (!open || active < 0 || !listRef.current) return;
    const el = listRef.current.children[active] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) =>
        it.code.toLowerCase().includes(q) ||
        (it.label || "").toLowerCase().includes(q) ||
        (it.label_en || "").toLowerCase().includes(q) ||
        (it.label_zh || "").toLowerCase().includes(q),
    );
  }, [items, query]);

  // U9：未过滤时最近使用置顶，过滤时走普通列表
  const recents = useMemo(() => {
    if (query.trim()) return [];
    return recentGet(dataset)
      .map((c) => items.find((it) => it.code === c))
      .filter((it): it is LookupItem => Boolean(it));
  }, [items, dataset, query]);
  const rest = useMemo(
    () => filtered.filter((it) => !recents.some((r) => r.code === it.code)),
    [filtered, recents],
  );

  const valueInList = items.some((it) => it.code === value);
  const selected = items.find((it) => it.code === value);

  // 浮层选项（与过滤/最近使用同序）：空值项 + 值不在表内的历史值项 + 常规项
  const menuItems = useMemo(() => {
    const rows: { code: string; text: string; kind: "empty" | "legacy" | "item"; group?: string }[] = [];
    if (allowEmpty) {
      rows.push({ code: "", text: emptyLabel || t("common.select", "请选择"), kind: "empty" });
    }
    if (value && !valueInList) {
      rows.push({
        code: value,
        text: `${value} (${t("lookup.legacy", "legacy value")})`,
        kind: "legacy",
      });
    }
    for (const it of recents) rows.push({ code: it.code, text: itemText(it, showCode), kind: "item", group: t("lookup.recent", "最近使用") });
    for (const it of rest) rows.push({ code: it.code, text: itemText(it, showCode), kind: "item" });
    return rows;
  }, [allowEmpty, emptyLabel, t, value, valueInList, recents, rest, showCode]);

  function commit(code: string) {
    if (code) recentPush(dataset, code);
    onChange(code);
    setOpen(false);
    setQuery("");
    setActive(-1);
  }

  function openMenu() {
    if (disabled || !loaded) return;
    updateFlip();
    setOpen(true);
    // 打开时定位到当前值（空值项之后的第一项附近：直接落在当前值上）
    const idx = menuItems.findIndex((r) => r.code === value);
    setActive(idx >= 0 ? idx : 0);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      if (open) {
        e.stopPropagation(); // 只关浮层，不触发 RecordModal 的 Esc 关闭
        e.preventDefault();
        setOpen(false);
        setQuery("");
      }
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) {
        openMenu();
        return;
      }
      const dir = e.key === "ArrowDown" ? 1 : -1;
      setActive((a) => {
        const n = a + dir;
        return Math.max(0, Math.min(menuItems.length - 1, n));
      });
      return;
    }
    if (e.key === "Enter") {
      // 浮层开着时 Enter = 选中高亮项，不能落进表单 submit
      if (open && active >= 0 && active < menuItems.length) {
        e.preventDefault();
        commit(menuItems[active].code);
      }
    }
  }

  const display = open
    ? query
    : selected
      ? itemText(selected, showCode)
      : value
        ? `${value} (${t("lookup.legacy", "legacy value")})`
        : "";

  return (
    <div className={`lookup-combobox${disabled ? " is-disabled" : ""}${className ? ` ${className}` : ""}`} ref={rootRef}>
      <input
        ref={inputRef}
        type="text"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        autoComplete="off"
        disabled={disabled || !loaded}
        required={required}
        value={display}
        placeholder={emptyLabel || t("common.select", "请选择")}
        onChange={(e) => {
          setQuery(e.target.value);
          setActive(0);
          if (!open) {
            updateFlip();
            setOpen(true);
          }
        }}
        onFocus={openMenu}
        // Tab/程序化失焦关浮层；选项点击在 onMouseDown 里 preventDefault，不会走到这
        onBlur={() => {
          setOpen(false);
          setQuery("");
        }}
        onKeyDown={onKeyDown}
      />
      {open ? (
        <div className={`lookup-menu${flipUp ? " flip-up" : ""}`} ref={listRef} role="listbox">
          {menuItems.length === 0 ? (
            <div className="lookup-menu-empty">{t("lookup.none", "无匹配项")}</div>
          ) : null}
          {menuItems.map((row, i) => (
            <div key={`${row.kind}-${row.code || "empty"}-${i}`}>
              {row.group && (i === 0 || menuItems[i - 1].group !== row.group) ? (
                <div className="lookup-menu-group">{row.group}</div>
              ) : null}
              <div
                className={`lookup-menu-item${i === active ? " is-active" : ""}${row.code === value ? " is-selected" : ""}`}
                role="option"
                aria-selected={row.code === value}
                // mousedown 抢先把 blur 摄走，保证 click 能落到选项上
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(i)}
                onClick={() => commit(row.code)}
              >
                {row.text}
              </div>
            </div>
          ))}
        </div>
      ) : null}
      {!loaded ? <span className="muted">{t("common.loading", "加载中…")}</span> : null}
      {loadError ? (
        <span className="field-error" role="alert">
          {loadError}
        </span>
      ) : null}
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
