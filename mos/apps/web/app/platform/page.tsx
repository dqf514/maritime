"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { HubTile } from "@/components/HubTile";
import { apiGet } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function PlatformHomePage() {
  const { t } = useI18n();
  const [health, setHealth] = useState<{ tenant_count: number; active: number; suspended: number } | null>(null);

  useEffect(() => {
    apiGet("/api/v1/platform/health").then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <AppShell>
      <PageHeader
        title={t("page.platform.title", "Platform operator console")}
        subtitle={t(
          "page.platform.sub",
          "Tenants & licenses, identity & mail channel, product branding, plans & usage, data plane & deployment. Use the sidebar entries for full configuration.",
        )}
        breadcrumb={[{ label: t("nav.plat_home", "Operator console") }]}
      />
      <div className="workbench-grid">
        <HubTile
          href="/platform/tenants"
          icon="plat_tenants"
          title={t("page.platform.tenants", "租户与许可证")}
          description={t("page.platform.tenants_d", "开通/暂停、编辑档位，按模块开关许可证")}
          meta={<div className="metric">{health?.tenant_count ?? "—"}</div>}
        />
        <HubTile
          href="/platform/branding"
          icon="plat_brand"
          title={t("page.platform.brand", "产品品牌")}
          description={t("page.platform.brand_d", "上传 Logo / 图标，编辑门户文案与主色")}
        />
        <HubTile
          href="/platform/identity"
          icon="plat_identity"
          title={t("page.platform.identity", "身份与邮件")}
          description={t("page.platform.identity_d", "登录方式、邮件通道、发件人 From、默认策略")}
        />
        <HubTile
          href="/platform/i18n"
          icon="plat_i18n"
          title={t("page.platform.i18n", "语言与术语")}
          description={t("page.platform.i18n_d", "en / zh-CN 语言包与航运术语库")}
        />
        <HubTile
          href="/platform/saas"
          icon="plat_saas"
          title={t("page.platform.saas", "套餐与用量")}
          description={t("page.platform.saas_d", "商业套餐、AI 网关、支付提供商目录")}
        />
        <HubTile
          href="/platform/health"
          icon="plat_health"
          title={t("page.platform.health", "租户健康")}
          description={`${t("page.platform.active", "启用")} ${health?.active ?? "—"} · ${t("page.platform.suspended", "暂停")} ${health?.suspended ?? "—"}`}
        />
        <HubTile
          href="/platform/ops"
          icon="plat_ops"
          title={t("page.platform.ops", "数据与部署")}
          description={t("page.platform.ops_d", "数据源、初始化向导、部署档案、监控")}
        />
        <HubTile
          href="/platform/interfaces"
          icon="plat_ops"
          title={t("page.platform.interfaces", "Interface messages")}
          description={t("page.platform.interfaces_d", "Inbound / outbound interface payloads, status and retry")}
        />
      </div>
    </AppShell>
  );
}
