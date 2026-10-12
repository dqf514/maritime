"use client";

// D7 / B1：403 解释页 — 静默弹回首页改为可读的拒绝说明
// （缺失角色授权，或模块未获得租户许可），带目标区域名与返回入口。

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { PageHeader } from "@/components/PageHeader";
import { useI18n } from "@/lib/i18n";

const AREA_PREFIXES: Array<[string, string, string]> = [
  ["/operations", "denied.area_ops", "Operations"],
  ["/estimates", "denied.area_estimates", "Estimates"],
  ["/charters", "denied.area_charters", "Chartering"],
  ["/finance", "denied.area_finance", "Finance"],
  ["/settings", "denied.area_settings", "Settings"],
  ["/admin", "denied.area_admin", "Administration"],
  ["/platform", "denied.area_platform", "Platform"],
  ["/masterdata", "denied.area_master", "Master data"],
  ["/analytics", "denied.area_analytics", "Analytics"],
  ["/ai", "denied.area_ai", "MariAI"],
  ["/trading", "denied.area_trading", "Trading & Risk"],
  ["/pool", "denied.area_pool", "Pooling"],
  ["/bunker", "denied.area_bunker", "Bunker desk"],
  ["/ship", "denied.area_ship", "Ship management"],
  ["/emissions", "denied.area_emissions", "Emissions"],
  ["/twin", "denied.area_twin", "Fleet Twin"],
  ["/workflows", "denied.area_workflows", "Workflows"],
];

function DeniedBody() {
  const { t } = useI18n();
  const params = useSearchParams();
  const target = params.get("m") || "";

  let areaKey = "denied.area_unknown";
  let areaFallback = target || t("denied.area_unknown", "this area");
  for (const [prefix, key, fb] of AREA_PREFIXES) {
    if (target === prefix || target.startsWith(`${prefix}/`)) {
      areaKey = key;
      areaFallback = fb;
      break;
    }
  }
  const area = t(areaKey, areaFallback);

  return (
    <AppShell>
      <PageHeader
        title={t("denied.title", "Access restricted")}
        subtitle={t("denied.subtitle", "This area is not available for your account.")}
        breadcrumb={[
          { label: t("nav.home", "Workbench"), href: "/home" },
          { label: t("denied.title", "Access restricted") },
        ]}
      />
      <div className="panel denied-panel">
        <p>
          {t("denied.body", "You tried to open {area}, which your current role or tenant license does not grant access to.", {
            area,
          })}
        </p>
        <ul className="denied-reasons">
          <li>{t("denied.reason_role", "Your role does not include permission for this area.")}</li>
          <li>{t("denied.reason_license", "The required module may not be licensed for your tenant.")}</li>
        </ul>
        <p className="muted">
          {t("denied.contact", "If you believe you should have access, contact your tenant administrator to adjust your role or module licenses.")}
          {target ? ` (${target})` : ""}
        </p>
        <div className="denied-actions">
          <Link className="btn primary" href="/home">
            {t("denied.back", "Back to Workbench")}
          </Link>
        </div>
      </div>
    </AppShell>
  );
}

export default function DeniedPage() {
  return (
    <Suspense fallback={null}>
      <DeniedBody />
    </Suspense>
  );
}
