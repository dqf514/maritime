"use client";

// A5 双重 UI 归并：TC 列表唯一入口 = /charters?type=tc。
// 旧路径 /charters/tc 保留为永久重定向，防止书签与外链失效。
// Next 16: useSearchParams 须位于 Suspense 边界内。

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function TcListRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const next = new URLSearchParams(searchParams.toString());
    next.set("type", "tc");
    router.replace(`/charters?${next.toString()}`);
  }, [router, searchParams]);

  return null;
}

export default function TcListAliasPage() {
  return (
    <Suspense fallback={null}>
      <TcListRedirect />
    </Suspense>
  );
}
