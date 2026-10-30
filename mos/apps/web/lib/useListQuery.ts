"use client";

import { useCallback, useEffect, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { publishListContext } from "./listContext";
import { toFiniteNumber, toPageNumber } from "./numbers";

/**
 * URL-backed list query state (U1 列表协议): tab / page / limit / filters live
 * in the query string so views are shareable, bookmarkable and survive the
 * back button. Patch values with `setQuery`; pass `null` to remove a key.
 *
 * Next 16: `useSearchParams` must be used under a <Suspense> boundary —
 * wrap the page component that calls this hook (see finance/page.tsx).
 */

const PAGE_LIMITS = [10, 25, 50, 100];
const DEFAULT_LIMIT = 50;

export function useListQuery() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const query = useMemo(() => Object.fromEntries(searchParams.entries()), [searchParams]);

  const setQuery = useCallback(
    (patch: Record<string, string | number | null | undefined>, opts?: { resetPage?: boolean }) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === undefined || value === "") next.delete(key);
        else next.set(key, String(value));
      }
      if (opts?.resetPage) next.delete("page");
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [searchParams, router, pathname],
  );

  // P1-24：页码是 1 起始的整数。`?page=abc` 不能产出 NaN —— 用显式守卫
  // （语义与原来的 `Math.max(1, Number(q.page) || 1)` 一致，只是更明确）。
  const page = toPageNumber(query.page);
  const parsedLimit = toFiniteNumber(query.limit);
  const limit = parsedLimit !== null && PAGE_LIMITS.includes(parsedLimit) ? parsedLimit : DEFAULT_LIMIT;

  // 把当前 URL 状态镜像进 sessionStorage —— 详情页据此重建「返回列表」链接，
  // 这样列表的筛选/排序/页码在往返中不丢（详情页 URL 本身保持干净）。
  useEffect(() => {
    publishListContext(pathname, { qs: searchParams.toString() });
  }, [pathname, searchParams]);

  return { query, setQuery, page, limit };
}
