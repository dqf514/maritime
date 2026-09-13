"use client";

/** Shared stroke icons — sidenav, hub tiles, quick links (one visual system). */
export function NavIcon({
  id,
  className = "nav-icon",
  size = 18,
}: {
  id: string;
  className?: string;
  size?: number;
}) {
  const common = {
    className,
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };

  switch (id) {
    case "home":
      return (
        <svg {...common}>
          <path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z" />
        </svg>
      );
    case "dashboards":
      return (
        <svg {...common}>
          <rect x="3" y="3" width="7" height="9" rx="1" />
          <rect x="14" y="3" width="7" height="5" rx="1" />
          <rect x="14" y="12" width="7" height="9" rx="1" />
          <rect x="3" y="16" width="7" height="5" rx="1" />
        </svg>
      );
    case "estimates":
      return (
        <svg {...common}>
          <path d="M8 4h9a2 2 0 0 1 2 2v14l-4-2-4 2V6a2 2 0 0 0-2-2H6" />
          <path d="M8 9h6M8 13h4" />
        </svg>
      );
    case "charters":
      return (
        <svg {...common}>
          <path d="M7 4h10v16H7z" />
          <path d="M10 8h4M10 12h4M10 16h2" />
        </svg>
      );
    case "email":
      return (
        <svg {...common}>
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="m3 7 9 7 9-7" />
        </svg>
      );
    case "ops":
      return (
        <svg {...common}>
          <path d="M3 17h6l3-8 3 12 3-6h3" />
        </svg>
      );
    case "bunker":
      return (
        <svg {...common}>
          <path d="M7 7h8v14H7z" />
          <path d="M15 10h3l2 2v6h-5" />
          <path d="M9 4h4v3H9z" />
        </svg>
      );
    case "emissions":
      return (
        <svg {...common}>
          <path d="M5 19c2-6 4-10 7-14 3 4 5 8 7 14" />
          <path d="M8 19h8" />
        </svg>
      );
    case "pool":
      return (
        <svg {...common}>
          <circle cx="8" cy="10" r="3" />
          <circle cx="16" cy="10" r="3" />
          <circle cx="12" cy="16" r="3" />
        </svg>
      );
    case "trading":
      return (
        <svg {...common}>
          <path d="M4 16 10 8l4 4 6-8" />
          <path d="M4 20h16" />
        </svg>
      );
    case "ship":
      return (
        <svg {...common}>
          <path d="M4 16h16l-2 4H6l-2-4Z" />
          <path d="M12 4v8M8 8h8" />
        </svg>
      );
    case "finance":
    case "billing":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8" />
          <path d="M12 7v10M9.5 9.5c.8-1 2-1.5 2.5-1.5s1.8.4 1.8 1.5S12 11 12 11s-2 .5-2 1.8 1.2 1.7 2.5 1.7 2-.5 2.5-1.2" />
        </svg>
      );
    case "twin":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
        </svg>
      );
    case "analytics":
      return (
        <svg {...common}>
          <path d="M4 19V5M4 19h16" />
          <path d="M8 15v-4M12 15V8M16 15v-7" />
        </svg>
      );
    case "vessels":
      return (
        <svg {...common}>
          <path d="M3 15h18l-2.5 4H5.5L3 15Z" />
          <path d="M6 15V9l6-4 6 4v6" />
        </svg>
      );
    case "ports":
      return (
        <svg {...common}>
          <path d="M12 21s7-5.2 7-11a7 7 0 1 0-14 0c0 5.8 7 11 7 11Z" />
          <circle cx="12" cy="10" r="2.5" />
        </svg>
      );
    case "parties":
    case "users":
      return (
        <svg {...common}>
          <circle cx="9" cy="8" r="3" />
          <circle cx="17" cy="9" r="2.5" />
          <path d="M3 19c0-3 2.5-5 6-5s6 2 6 5M14 19c.3-2 1.8-3.5 4-3.5 1.5 0 2.7.6 3.4 1.5" />
        </svg>
      );
    case "inbox":
      return (
        <svg {...common}>
          <path d="M4 8h16v11H4z" />
          <path d="M4 12h4l2 2h4l2-2h4" />
          <path d="m8 8 4-4 4 4" />
        </svg>
      );
    case "settings_hub":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3v2.2M12 18.8V21M4.9 6.1l1.6 1.6M17.5 16.3l1.6 1.6M3 12h2.2M18.8 12H21M4.9 17.9l1.6-1.6M17.5 7.7l1.6-1.6" />
        </svg>
      );
    case "company":
      return (
        <svg {...common}>
          <path d="M4 20V8l6-4 6 4v12" />
          <path d="M10 20V12h4v8" />
          <path d="M7 11h2M7 14h2M15 11h2M15 14h2" />
        </svg>
      );
    case "org":
      return (
        <svg {...common}>
          <rect x="9" y="3" width="6" height="4" rx="1" />
          <rect x="3" y="17" width="6" height="4" rx="1" />
          <rect x="15" y="17" width="6" height="4" rx="1" />
          <path d="M12 7v4M6 13v4M18 13v4M6 13h12" />
        </svg>
      );
    case "security":
    case "account":
      return (
        <svg {...common}>
          <path d="M12 3 4 7v5c0 4.5 3.4 7.8 8 9 4.6-1.2 8-4.5 8-9V7l-8-4Z" />
          <path d="M9.5 12.2 11.2 14l3.5-3.8" />
        </svg>
      );
    case "i18n":
    case "plat_i18n":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3c2.5 2.8 3.8 5.8 3.8 9s-1.3 6.2-3.8 9c-2.5-2.8-3.8-5.8-3.8-9S9.5 5.8 12 3Z" />
        </svg>
      );
    case "perm":
      return (
        <svg {...common}>
          <rect x="4" y="4" width="16" height="16" rx="2" />
          <path d="M8 9h8M8 12h8M8 15h5" />
        </svg>
      );
    case "wf":
    case "workflows":
      return (
        <svg {...common}>
          <rect x="3" y="4" width="7" height="5" rx="1" />
          <rect x="14" y="4" width="7" height="5" rx="1" />
          <rect x="8.5" y="15" width="7" height="5" rx="1" />
          <path d="M10 9v2.5h4V9M12 11.5V15" />
        </svg>
      );
    case "selfcheck":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="m8 12.5 2.5 2.5L16 9.5" />
        </svg>
      );
    case "migrate":
      return (
        <svg {...common}>
          <path d="M7 7h11v3l3-3.5L18 3v3H7a4 4 0 0 0 0 8h2" />
          <path d="M17 17H6v-3l-3 3.5L6 21v-3h11a4 4 0 0 0 0-8h-2" />
        </svg>
      );
    case "backup":
      return (
        <svg {...common}>
          <path d="M7 7a5 5 0 0 1 9.9-1A4.5 4.5 0 0 1 18 15H8a4 4 0 0 1-1-7.9" />
          <path d="M12 11v6M9.5 14.5 12 17l2.5-2.5" />
        </svg>
      );
    case "ai":
      return (
        <svg {...common}>
          <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
          <path d="M6.5 6.5 8.5 8.5M15.5 15.5l2 2M17.5 6.5 15.5 8.5M8.5 15.5l-2 2" />
          <circle cx="12" cy="12" r="3.5" />
        </svg>
      );
    case "connectors":
      return (
        <svg {...common}>
          <path d="M9 8V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v3" />
          <rect x="7" y="8" width="10" height="7" rx="1.5" />
          <path d="M10 15v4M14 15v4M9 22h6" />
        </svg>
      );
    case "office":
      return (
        <svg {...common}>
          <rect x="3" y="4" width="8" height="8" rx="1" />
          <rect x="13" y="4" width="8" height="8" rx="1" />
          <rect x="3" y="14" width="8" height="6" rx="1" />
          <rect x="13" y="14" width="8" height="6" rx="1" />
        </svg>
      );
    case "licenses":
      return (
        <svg {...common}>
          <path d="M8 4h8l3 3v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z" />
          <path d="M9 11h6M9 15h4M14 4v4h4" />
        </svg>
      );
    case "apikeys":
      return (
        <svg {...common}>
          <circle cx="8" cy="14" r="3.5" />
          <path d="M11 12.5 20 3.5M16.5 4.5l3 3M14.5 6.5l2 2" />
        </svg>
      );
    case "plat_home":
      return (
        <svg {...common}>
          <path d="M4 10h16v10H4z" />
          <path d="M8 10V7l4-3 4 3v3" />
          <path d="M9 14h2M13 14h2M9 17h6" />
        </svg>
      );
    case "plat_tenants":
      return (
        <svg {...common}>
          <path d="M4 20V9l4-3 4 3v11" />
          <path d="M12 20V10l4-3 4 3v10" />
          <path d="M6 13h2M6 16h2M14 13h2M14 16h2" />
        </svg>
      );
    case "plat_ops":
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="14" rx="2" />
          <path d="M7 15h2M11 15h6M8 8l2 2 4-4" />
        </svg>
      );
    case "plat_saas":
      return (
        <svg {...common}>
          <path d="M4 16a4 4 0 0 1 3-6 5 5 0 0 1 9.5 1.5A3.5 3.5 0 0 1 18 16Z" />
          <path d="M9 16v2M12 15v3M15 16v2" />
        </svg>
      );
    case "plat_brand":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="8" />
          <path d="M12 8v8M9 10.5c1-1 2-1.5 3-1.5s2 .5 2.5 1.2c.4.6 0 1.3-1 1.8H12" />
        </svg>
      );
    case "plat_identity":
      return (
        <svg {...common}>
          <circle cx="12" cy="9" r="3.5" />
          <path d="M5.5 19c1.5-3 4-4.5 6.5-4.5s5 1.5 6.5 4.5" />
          <path d="M16.5 7.5 18 6l1.5 1.5" />
        </svg>
      );
    case "plat_health":
      return (
        <svg {...common}>
          <path d="M3 12h4l2-5 3 10 2-5h5" />
        </svg>
      );
    case "help":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M9.5 9.5a2.5 2.5 0 1 1 3.3 2.3c-.8.4-1.3 1-1.3 1.7V14" />
          <path d="M12 17h.01" />
        </svg>
      );
    case "sec_desk":
      return (
        <svg {...common}>
          <path d="M4 7h16M4 12h16M4 17h10" />
        </svg>
      );
    case "sec_master":
      return (
        <svg {...common}>
          <ellipse cx="12" cy="7" rx="7" ry="3" />
          <path d="M5 7v5c0 1.7 3.1 3 7 3s7-1.3 7-3V7M5 12v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5" />
        </svg>
      );
    case "sec_admin":
      return (
        <svg {...common}>
          <path d="M12 3 4 7v5c0 4.5 3.4 7.8 8 9 4.6-1.2 8-4.5 8-9V7l-8-4Z" />
        </svg>
      );
    case "sec_platform":
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="6" rx="1" />
          <rect x="3" y="14" width="18" height="6" rx="1" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="7" />
          <path d="M12 8v4M12 16h.01" />
        </svg>
      );
  }
}

export function sectionIconId(section: string): string {
  if (section === "desk") return "sec_desk";
  if (section === "master") return "sec_master";
  if (section === "admin") return "sec_admin";
  if (section === "platform") return "sec_platform";
  return "sec_desk";
}

/** Map route / widget id → icon id (same family as sidenav). */
export function resolveIconId(hrefOrId: string): string {
  const s = (hrefOrId || "").toLowerCase();

  // Prefer longest path match so /settings/ai wins over /settings
  const table: [string, string][] = [
    ["/settings/dataops/migrate", "migrate"],
    ["/settings/dataops/backup", "backup"],
    ["/settings/selfcheck", "selfcheck"],
    ["/settings/connectors", "connectors"],
    ["/settings/api-keys", "apikeys"],
    ["/settings/licenses", "licenses"],
    ["/settings/office", "office"],
    ["/settings/ai", "ai"],
    ["/admin/organization", "org"],
    ["/admin/permissions", "perm"],
    ["/admin/workflows", "wf"],
    ["/admin/security", "security"],
    ["/admin/billing", "billing"],
    ["/admin/company", "company"],
    ["/admin/users", "users"],
    ["/admin/i18n", "i18n"],
    ["/admin/org", "org"],
    ["/account/security", "account"],
    ["/workflows/inbox", "inbox"],
    ["/masterdata/counterparties", "parties"],
    ["/masterdata/vessels", "vessels"],
    ["/masterdata/ports", "ports"],
    ["/platform/tenants", "plat_tenants"],
    ["/platform/branding", "plat_brand"],
    ["/platform/identity", "plat_identity"],
    ["/platform/i18n", "plat_i18n"],
    ["/platform/saas", "plat_saas"],
    ["/platform/health", "plat_health"],
    ["/platform/ops", "plat_ops"],
    ["/platform", "plat_home"],
    ["/dashboards", "dashboards"],
    ["/estimates", "estimates"],
    ["/charters", "charters"],
    ["/operations", "ops"],
    ["/analytics", "analytics"],
    ["/finance", "finance"],
    ["/settings", "settings_hub"],
    ["/email", "email"],
    ["/ship", "ship"],
    ["/twin", "twin"],
    ["/help", "help"],
    ["/home", "home"],
  ];
  for (const [needle, icon] of table) {
    if (s === needle || s.startsWith(`${needle}/`) || s.startsWith(`${needle}?`)) return icon;
  }

  if (s.includes("dash")) return "dashboards";
  if (s.includes("estimate")) return "estimates";
  if (s.includes("charter")) return "charters";
  if (s.includes("voyage") || s === "ops" || s.includes("ops_")) return "ops";
  if (s.includes("financ") || s.includes("invoice") || s.includes("billing")) return "finance";
  if (s.includes("ship") || s.includes("pms") || s.includes("tech")) return "ship";
  if (s.includes("inbox") || s.includes("approv")) return "inbox";
  if (s.includes("twin")) return "twin";
  if (s.includes("email")) return "email";
  if (s.includes("help") || s.includes("knowledge")) return "help";
  if (s.includes("analytic")) return "analytics";
  if (s.includes("port")) return "ports";
  if (s.includes("vessel")) return "vessels";
  if (s.includes("part")) return "parties";
  return "settings_hub";
}
