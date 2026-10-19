"use client";

// 页头快捷链接（收藏夹）：替换原面包屑位置的本页标题。
// - FavoriteBar：可增/删/拖动排序的收藏链接条（localStorage 持久化）
// - FavoriteButton：页面右上角的 ★ 收藏按钮（PageHeader 统一渲染）
// 两者通过模块级 store + useSyncExternalStore 同步。

import { useCallback, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useI18n } from "@/lib/i18n";
import { useToast } from "@/components/ToastProvider";

export type FavLink = { href: string; title: string };

const KEY = "marios_fav_links";
const CHANGED = "marios:fav-links-changed";

let cache: FavLink[] | null = null;
const listeners = new Set<() => void>();

function sanitize(raw: unknown): FavLink[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((x): x is FavLink => !!x && typeof x === "object" && typeof (x as FavLink).href === "string")
    .map((x) => ({ href: String(x.href), title: String(x.title || x.href) }))
    .slice(0, 30);
}

function load(): FavLink[] {
  if (cache) return cache;
  try {
    cache = sanitize(JSON.parse(localStorage.getItem(KEY) || "[]"));
  } catch {
    cache = [];
  }
  return cache;
}

function commit(next: FavLink[]) {
  cache = sanitize(next);
  try {
    localStorage.setItem(KEY, JSON.stringify(cache));
  } catch {
    // 存储失败（隐私模式）— 仅内存生效
  }
  listeners.forEach((l) => l());
  window.dispatchEvent(new CustomEvent(CHANGED));
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  const onExternal = () => cb();
  window.addEventListener(CHANGED, onExternal);
  return () => {
    listeners.delete(cb);
    window.removeEventListener(CHANGED, onExternal);
  };
}

function getSnapshot(): FavLink[] {
  return typeof window === "undefined" ? EMPTY : load();
}

const EMPTY: FavLink[] = [];

function isFav(list: FavLink[], href: string) {
  return list.some((f) => f.href === href);
}

/** 收藏链接条 — 放在页头原面包屑槽位 */
export function FavoriteBar() {
  const { t } = useI18n();
  const favs = useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);
  const [dragIndex, setDragIndex] = useState<number | null>(null);

  const onDrop = useCallback(
    (target: number) => {
      if (dragIndex === null || dragIndex === target) return;
      const next = [...favs];
      const [moved] = next.splice(dragIndex, 1);
      next.splice(target, 0, moved);
      commit(next);
      setDragIndex(null);
    },
    [dragIndex, favs],
  );

  if (!favs.length) {
    return (
      <div className="page-fav-bar page-fav-empty" aria-label={t("page.fav.bar", "Quick links")}>
        {t("page.fav.empty", "Star a page to pin quick links here")}
      </div>
    );
  }

  return (
    <div className="page-fav-bar" aria-label={t("page.fav.bar", "Quick links")}>
      {favs.map((f, i) => (
        <span
          key={f.href}
          className={`page-fav-chip${dragIndex === i ? " dragging" : ""}`}
          draggable
          onDragStart={() => setDragIndex(i)}
          onDragEnd={() => setDragIndex(null)}
          onDragOver={(e) => e.preventDefault()}
          onDrop={() => onDrop(i)}
          title={t("page.fav.reorder", "Drag to reorder")}
        >
          <Link href={f.href} className="page-fav-link">
            {f.title}
          </Link>
          <button
            type="button"
            className="page-fav-x"
            aria-label={t("page.fav.remove", "Remove from favorites")}
            onClick={() => commit(favs.filter((x) => x.href !== f.href))}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}

/** 页面右上角 ★ 收藏按钮 — PageHeader 一律渲染 */
export function FavoriteButton({ title }: { title: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const pathname = usePathname();
  const favs = useSyncExternalStore(subscribe, getSnapshot, () => EMPTY);
  const active = isFav(favs, pathname);
  const label = title || pathname;

  function toggle() {
    if (active) {
      commit(favs.filter((x) => x.href !== pathname));
      toast.info(t("page.fav.removed", "Removed from favorites"));
    } else {
      commit([...favs.filter((x) => x.href !== pathname), { href: pathname, title: label }]);
      toast.info(t("page.fav.added", "Added to favorites"));
    }
  }

  return (
    <button
      type="button"
      className={`page-fav-star${active ? " active" : ""}`}
      aria-pressed={active}
      aria-label={active ? t("page.fav.remove", "Remove from favorites") : t("page.fav.add", "Add to favorites")}
      title={active ? t("page.fav.remove", "Remove from favorites") : t("page.fav.add", "Add to favorites")}
      onClick={toggle}
    >
      <svg viewBox="0 0 20 20" width="15" height="15" aria-hidden>
        <path
          fill="currentColor"
          d="M10 1.8l2.47 5.01 5.53.8-4 3.9.94 5.5L10 14.4l-4.94 2.6.94-5.5-4-3.9 5.53-.8L10 1.8z"
        />
      </svg>
    </button>
  );
}
