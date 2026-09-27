"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

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

  const page = Math.max(1, Number(query.page) || 1);
  const parsedLimit = Number(query.limit);
  const limit = PAGE_LIMITS.includes(parsedLimit) ? parsedLimit : DEFAULT_LIMIT;

  return { query, setQuery, page, limit };
}
