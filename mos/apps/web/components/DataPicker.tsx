"use client";

// 主数据可搜索选择器（闭环统一入口）：输入即搜（服务端 q）+ 最近使用置顶 +
// 清空；替代各业务表单的裸 <select> 全量下拉。PartyPicker / ContactPicker 封装。

import { useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export type PickerItem = {
  id: string;
  label: string;
  sublabel?: string | null;
};

type Props = {
  value: string;
  onChange: (id: string, item?: PickerItem) => void;
  /** 服务端检索端点（须支持 ?q= 返回 items 或数组） */
  endpoint: string;
  /** 空值文案 / 允许清空 */
  allowEmpty?: boolean;
  emptyLabel?: string;
  /** 最近使用存储键（按数据集隔离） */
  recentKey: string;
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  /** 同步预载选项（可选，提升首屏体验） */
  preload?: PickerItem[];
};

const RECENT_MAX = 5;

function recentGet(key: string): PickerItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = JSON.parse(localStorage.getItem(`marios_pick_${key}`) || "[]");
    return Array.isArray(raw) ? raw.slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function recentPush(key: string, item: PickerItem) {
  if (typeof window === "undefined") return;
  const next = [item, ...recentGet(key).filter((x) => x.id !== item.id)].slice(0, RECENT_MAX);
  try {
    localStorage.setItem(`marios_pick_${key}`, JSON.stringify(next));
  } catch {
    // 忽略存储失败
  }
}

function tenantScope(): string {
  if (typeof window === "undefined") return "ssr";
  const token = localStorage.getItem("marios_token") || "";
  let h = 0;
  for (let i = 0; i < token.length; i++) h = (h * 31 + token.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

export function DataPicker({
  value,
  onChange,
  endpoint,
  allowEmpty = true,
  emptyLabel,
  recentKey,
  placeholder,
  disabled,
  required,
  preload,
}: Props) {
  const { t } = useI18n();
  const storeKey = `${tenantScope()}_${recentKey}`;
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<PickerItem[]>(preload || []);
  const [open, setOpen] = useState(false);
  const [kbdIndex, setKbdIndex] = useState(-1);
  const [selected, setSelected] = useState<PickerItem | null>(
    () => preload?.find((x) => x.id === value) || recentGet(storeKey).find((x) => x.id === value) || null,
  );
  const boxRef = useRef<HTMLDivElement>(null);

  // 输入即搜（防抖 200ms）；空输入时展示最近使用 + 预载
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(async () => {
      try {
        const data = await apiGet(`${endpoint}${endpoint.includes("?") ? "&" : "?"}q=${encodeURIComponent(query)}&limit=30`);
        const rows: unknown[] = Array.isArray(data) ? data : (data?.items ?? []);
        const mapped: PickerItem[] = rows.map((r) => {
          const o = r as { id: string; name?: string; label?: string; counterparty_name?: string; title?: string; email?: string };
          return {
            id: o.id,
            label: o.label || o.name || o.id,
            sublabel: o.counterparty_name ?? o.email ?? null,
          };
        });
        setItems(mapped);
      } catch {
        setItems([]);
      }
    }, 200);
    return () => clearTimeout(timer);
  }, [query, open, endpoint]);

  // 点击外部收起
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // value 外部变化时补显示名
  useEffect(() => {
    if (!value) {
      setSelected(null);
      return;
    }
    if (selected?.id === value) return;
    const known = items.find((x) => x.id === value) || recentGet(storeKey).find((x) => x.id === value);
    if (known) setSelected(known);
    else {
      // 未知 id：拉一次直查（name 优先精确 id 不可查，取列表首屏兜底）
      apiGet(`${endpoint}?limit=200`)
        .then((data: unknown) => {
          const rows: unknown[] = Array.isArray(data) ? data : ((data as { items?: unknown[] })?.items ?? []);
          const hit = rows
            .map((r) => r as { id: string; name?: string; label?: string; counterparty_name?: string; email?: string })
            .find((o) => o.id === value);
          if (hit) setSelected({ id: hit.id, label: hit.label || hit.name || hit.id, sublabel: hit.counterparty_name ?? hit.email ?? null });
        })
        .catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const recents = query ? [] : recentGet(storeKey).filter((r) => !items.some((i) => i.id === r.id));
  const list = [...recents, ...items];
  const totalItems = list.length + (allowEmpty ? 1 : 0);

  return (
    <div className="data-picker" ref={boxRef}>
      <input
        type="text"
        role="combobox"
        aria-expanded={open}
        value={open ? query : selected ? selected.label : query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        placeholder={placeholder || t("picker.search", "搜索…")}
        disabled={disabled}
        required={required && !selected}
        onKeyDown={(e) => {
          if (e.key === "Escape") { setOpen(false); setKbdIndex(-1); return; }
          if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
            e.preventDefault();
            setOpen(true);
            setKbdIndex(0);
            return;
          }
          if (!open) return;
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setKbdIndex((i) => (i + 1) % totalItems);
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setKbdIndex((i) => (i <= 0 ? totalItems - 1 : i - 1));
          } else if (e.key === "Home") {
            e.preventDefault();
            setKbdIndex(0);
          } else if (e.key === "End") {
            e.preventDefault();
            setKbdIndex(totalItems - 1);
          } else if (e.key === "Enter") {
            e.preventDefault();
            if (allowEmpty && kbdIndex === 0) {
              setSelected(null); setQuery(""); onChange(""); setOpen(false); setKbdIndex(-1);
            } else {
              const itemIdx = kbdIndex - (allowEmpty ? 1 : 0);
              const item = list[itemIdx >= 0 ? itemIdx : 0];
              if (item) {
                onChange(item.id, item);
                setSelected(item);
                recentPush(storeKey, item);
                setOpen(false);
                setKbdIndex(-1);
              }
            }
          }
        }}
      />
      {selected && allowEmpty ? (
        <button
          type="button"
          className="data-picker-clear"
          aria-label={t("common.clear", "清除")}
          onClick={() => {
            setSelected(null);
            setQuery("");
            onChange("");
          }}
        >
          ×
        </button>
      ) : null}
      {open ? (
        <div className="data-picker-pop" role="listbox">
          {allowEmpty ? (
            <button
              type="button"
              className={`data-picker-item muted${kbdIndex === 0 ? " kbd-active" : ""}`}
              onClick={() => {
                setSelected(null);
                setQuery("");
                onChange("");
                setOpen(false);
                setKbdIndex(-1);
              }}
            >
              {emptyLabel || t("common.select", "Select…")}
            </button>
          ) : null}
          {list.map((it, idx) => {
            const kbdIdx = idx + (allowEmpty ? 1 : 0);
            return (
              <button
                key={it.id}
                type="button"
                className={`data-picker-item${it.id === value ? " active" : ""}${kbdIndex === kbdIdx ? " kbd-active" : ""}`}
                onClick={() => {
                  setSelected(it);
                  onChange(it.id, it);
                  recentPush(storeKey, it);
                  setOpen(false);
                  setKbdIndex(-1);
                }}
              >
                <span>{it.label}</span>
                {it.sublabel ? <span className="muted">{it.sublabel}</span> : null}
              </button>
            );
          })}
          {!list.length ? <div className="data-picker-item muted">{t("common.empty", "No records")}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

/** 对手方选择器（闭环统一入口） */
export function PartyPicker(props: Omit<Props, "endpoint" | "recentKey">) {
  return <DataPicker {...props} endpoint="/api/v1/masterdata/counterparties" recentKey="party" />;
}

/** 联系人选择器（跨公司，显示 公司 · 邮箱） */
export function ContactPicker(props: Omit<Props, "endpoint" | "recentKey">) {
  return <DataPicker {...props} endpoint="/api/v1/masterdata/counterparty-contacts" recentKey="contact" />;
}
