"use client";

// 主数据导入入口 — 实体 Tab → ImportWizard（CSV 粘贴/上传 → 校验预览 → 提交）。

import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { Tabs } from "@/components/Tabs";
import { ImportWizard, type ImportEntity } from "@/components/ImportWizard";
import { useI18n } from "@/lib/i18n";

export default function MasterDataImportPage() {
  const { t } = useI18n();
  const [entity, setEntity] = useState<ImportEntity>("ports");
  const [nonce, setNonce] = useState(0);

  return (
    <AppShell>
      <PageHeader
        breadcrumb={[{ label: t("nav.master", "Master data") }, { label: t("imp.title", "Import") }]}
        title={t("imp.title", "Import")}
        subtitle={t(
          "imp.subtitle",
          "Bulk-create master data from CSV — validated preview before commit, formula injection blocked.",
        )}
      />
      <Tabs
        items={[
          { key: "ports", label: t("imp.entity_ports", "Ports") },
          { key: "counterparties", label: t("imp.entity_counterparties", "Counterparties") },
          { key: "vessels", label: t("imp.entity_vessels", "Vessels") },
        ]}
        value={entity}
        onChange={(k) => {
          setEntity(k as ImportEntity);
          setNonce((n) => n + 1);
        }}
        aria-label={t("imp.entity_tabs", "Entity")}
      />
      <ImportWizard key={`${entity}-${nonce}`} entity={entity} />
    </AppShell>
  );
}
