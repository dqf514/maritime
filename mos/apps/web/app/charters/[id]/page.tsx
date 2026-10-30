"use client";

import { useMemo } from "react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { CharterEditor } from "@/components/CharterEditor";
import { DetailRail } from "@/components/masterdetail/DetailRail";
import { MasterDetail } from "@/components/masterdetail/MasterDetail";
import { useDetailRail } from "@/components/masterdetail/useRailItems";
import { useI18n } from "@/lib/i18n";
import { useListBackHref } from "@/lib/listContext";

// U2 单据详情页：租约可深链视图（/charters/{id}）。

/** 左栏清单行 —— /api/v1/charters（租约列表页）的形状。 */
type CharterRow = {
  id: string;
  charter_no?: string | null;
  charter_type?: string | null;
  status?: string | null;
};

export default function CharterDetailPage() {
  const { t } = useI18n();
  const params = useParams<{ id: string }>();
  const charterId = params.id;

  // 左栏（IMOS 式兄弟清单）+ 顶部「返回列表」（带列表的筛选/排序/页码）
  const backHref = useListBackHref("/charters");
  const currentRailItem = useMemo(
    () => ({
      id: charterId,
      title: `#${charterId}`,
      meta: [],
      href: `/charters/${charterId}`,
    }),
    [charterId],
  );
  const rail = useDetailRail<CharterRow>(
    {
      endpoint: "/api/v1/charters",
      params: { limit: 100 },
      mapRow: (r) => ({
        id: r.id,
        title: r.charter_no || r.id,
        meta: [r.charter_type || "", r.status || ""],
        href: `/charters/${r.id}`,
      }),
    },
    currentRailItem,
  );

  return (
    <AppShell
      breadcrumbs={[
        { label: t("nav.charters", "Charters"), href: backHref },
        { label: `#${charterId}` },
      ]}
    >
      <MasterDetail
        rail={
          <DetailRail
            items={rail.items}
            activeId={charterId}
            title={t("nav.charters", "Charters")}
            backHref={backHref}
            backLabel={t("common.back_to_list", { en: "Back to list", zh: "返回列表" })}
            loading={rail.loading}
            error={rail.error}
            onRetry={rail.reload}
          />
        }
      >
        <CharterEditor
          charterId={charterId}
          breadcrumb={[
            { label: t("nav.charters", "Charters"), href: "/charters" },
            { label: `#${charterId}` },
          ]}
        />
      </MasterDetail>
    </AppShell>
  );
}
