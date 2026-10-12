// 航次详情唯一入口 = workspace（Phase 2 面板式工作台）。
// 旧裸页 /operations/voyages/{id} 保留为永久重定向，防止书签与外链失效。

import { redirect } from "next/navigation";

export default async function VoyageDetailAlias({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  redirect(`/operations/voyages/${id}/workspace`);
}
