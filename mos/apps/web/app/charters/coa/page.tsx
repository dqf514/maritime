"use client";

// A5 双重 UI 归并：COA 列表唯一入口 = /charters?type=coa。
// 旧路径 /charters/coa 保留为永久重定向，防止书签与外链失效。
// Next 16: useSearchParams 须位于 Suspense 边界内。

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function CoaListRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const next = new URLSearchParams(searchParams.toString());
    next.set("type", "coa");
    router.replace(`/charters?${next.toString()}`);
  }, [router, searchParams]);

  return null;
}

export default function CoaListAliasPage() {
  return (
    <Suspense fallback={null}>
      <CoaListRedirect />
    </Suspense>
  );
}
