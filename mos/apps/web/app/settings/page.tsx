"use client";

import { AppShell } from "@/components/AppShell";
import { HubTile } from "@/components/HubTile";
import { useI18n } from "@/lib/i18n";

const TILES = [
  {
    href: "/help",
    icon: "help",
    titleKey: "settings.tile.help",
    title: "Knowledge Centre",
    descKey: "settings.tile.help_d",
    desc: "Guides, search and Q&A",
  },
  {
    href: "/admin/billing",
    icon: "billing",
    titleKey: "settings.tile.billing",
    title: "Subscription & usage",
    descKey: "settings.tile.billing_d",
    desc: "Plans, AI packs, wallet, ledger",
  },
  {
    href: "/admin/company",
    icon: "company",
    titleKey: "settings.tile.company",
    title: "Company & brand",
    descKey: "settings.tile.company_d",
    desc: "Logo, legal name, brand colors",
  },
  {
    href: "/admin/org",
    icon: "org",
    titleKey: "settings.tile.org",
    title: "Org structure",
    descKey: "settings.tile.org_d",
    desc: "HQ / departments / teams",
  },
  {
    href: "/admin/users",
    icon: "users",
    titleKey: "settings.tile.users",
    title: "Users & roles",
    descKey: "settings.tile.users_d",
    desc: "Invite and assign roles",
  },
  {
    href: "/admin/security",
    icon: "security",
    titleKey: "settings.tile.security",
    title: "Login & security",
    descKey: "settings.tile.security_d",
    desc: "SSO methods, email verify, domains, invites",
  },
  {
    href: "/admin/i18n",
    icon: "i18n",
    titleKey: "settings.i18n",
    title: "Languages & terminology",
    descKey: "settings.i18n_desc",
    desc: "Locale policy and maritime term overrides",
  },
  {
    href: "/account/security",
    icon: "account",
    titleKey: "settings.tile.account",
    title: "My account security",
    descKey: "settings.tile.account_d",
    desc: "Verify email, password, linked IdPs",
  },
  {
    href: "/admin/permissions",
    icon: "perm",
    titleKey: "settings.tile.perm",
    title: "Feature permissions",
    descKey: "settings.tile.perm_d",
    desc: "Fine-grained capability matrix",
  },
  {
    href: "/admin/workflows",
    icon: "wf",
    titleKey: "settings.tile.wf",
    title: "Workflows",
    descKey: "settings.tile.wf_d",
    desc: "Approval process definitions",
  },
  {
    href: "/workflows/inbox",
    icon: "inbox",
    titleKey: "settings.tile.inbox",
    title: "Approval inbox",
    descKey: "settings.tile.inbox_d",
    desc: "Pending business approvals",
  },
  {
    href: "/settings/selfcheck",
    icon: "selfcheck",
    titleKey: "settings.tile.selfcheck",
    title: "SelfCheck",
    descKey: "settings.tile.selfcheck_d",
    desc: "Install & runtime diagnostics",
  },
  {
    href: "/settings/dataops/migrate",
    icon: "migrate",
    titleKey: "settings.tile.migrate",
    title: "Migrate",
    descKey: "settings.tile.migrate_d",
    desc: "AI inbound migration wizard",
  },
  {
    href: "/settings/dataops/backup",
    icon: "backup",
    titleKey: "settings.tile.backup",
    title: "Backup",
    descKey: "settings.tile.backup_d",
    desc: "One-click tenant backup",
  },
  {
    href: "/settings/ai",
    icon: "ai",
    titleKey: "settings.tile.ai",
    title: "AI Hub",
    descKey: "settings.tile.ai_d",
    desc: "Tenant skill bindings",
  },
  {
    href: "/settings/reference",
    icon: "migrate",
    titleKey: "settings.tile.reference",
    title: "Reference data",
    descKey: "settings.tile.reference_d",
    desc: "Countries, time zones, currencies, vessel types — clone and customize locally",
  },
  {
    href: "/settings/connectors",
    icon: "connectors",
    titleKey: "settings.tile.connectors",
    title: "Integration Hub",
    descKey: "settings.tile.connectors_d",
    desc: "FX, bunker, AIS, ERP, sanctions, emissions adapters",
  },
  {
    href: "/settings/office",
    icon: "office",
    titleKey: "settings.tile.office",
    title: "Office ecosystem",
    descKey: "settings.tile.office_d",
    desc: "Teams, SharePoint, OneDrive, Mail & add-ins",
  },
  {
    href: "/settings/licenses",
    icon: "licenses",
    titleKey: "settings.tile.licenses",
    title: "Module licenses",
    descKey: "settings.tile.licenses_d",
    desc: "Active module entitlements",
  },
  {
    href: "/settings/api-keys",
    icon: "apikeys",
    titleKey: "settings.tile.apikeys",
    title: "API keys",
    descKey: "settings.tile.apikeys_d",
    desc: "Integration keys for partners",
  },
  {
    href: "/settings/recycle",
    icon: "backup",
    titleKey: "settings.tile.recycle",
    title: "Recycle bin",
    descKey: "settings.tile.recycle_d",
    desc: "Restore or permanently purge soft-deleted records",
  },
];

export default function SettingsHubPage() {
  const { t } = useI18n();
  return (
    <AppShell>
      <div className="page-header">
        <div>
          <h1 style={{ margin: 0 }}>{t("settings.title", "系统设置")}</h1>
          <p className="page-sub">{t("settings.sub", "租户级配置入口：用户、安全、许可、集成等。")}</p>
        </div>
      </div>
      <div className="workbench-grid">
        {TILES.map((tile) => (
          <HubTile
            key={tile.href}
            href={tile.href}
            icon={tile.icon}
            title={t(tile.titleKey, tile.title)}
            description={t(tile.descKey, tile.desc)}
          />
        ))}
      </div>
    </AppShell>
  );
}
