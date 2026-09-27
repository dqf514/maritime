"use client";

import { useParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { CharterEditor } from "@/components/CharterEditor";
import { useI18n } from "@/lib/i18n";

// U2 单据详情页：租约可深链视图（/charters/{id}）。

export default function CharterDetailPage() {
  const { t } = useI18n();
  const params = useParams<{ id: string }>();

  return (
    <AppShell
      breadcrumbs={[
        { label: t("page.charters.title", "租约工作台"), href: "/charters" },
        { label: t("page.charters.edit", "编辑租约") },
      ]}
    >
      <CharterEditor charterId={params.id} />
    </AppShell>
  );
}
