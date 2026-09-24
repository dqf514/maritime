"""Role-based navigation, workspaces and home widgets (DDS §2–3).

Sidenav is organised into functional modules (iMOS-style):
  Workbench → Chartering → Operations → Finance → Technical → Analytics
  → Master data → Administration → Platform

Each module is a collapsible section; only modules with visible items
(after role filtering) are rendered.
"""

from __future__ import annotations

from typing import Any


# ── Flat item catalogues (kept for back-compat / reference) ──────────

NAV_DESK: list[dict[str, Any]] = [
    {"id": "home", "label": "Workbench", "href": "/home", "roles": ["*"]},
    {"id": "dashboards", "label": "Live dashboards", "href": "/dashboards", "roles": ["*"]},
    {"id": "tasks", "label": "Tasks", "href": "/tasks", "roles": ["*"]},
    {"id": "estimates", "label": "Estimates", "href": "/estimates", "roles": ["chartering", "management"]},
    {"id": "charters", "label": "Charters", "href": "/charters", "roles": ["chartering", "management"]},
    {"id": "email", "label": "Email Review", "href": "/email/review", "roles": ["chartering", "operations"]},
    {"id": "ops", "label": "Voyages", "href": "/operations/voyages", "roles": ["operations", "management", "technical"]},
    {"id": "marilink", "label": "MariLink", "href": "/operations/marilink", "roles": ["operations", "management", "technical"]},
    {"id": "bunker", "label": "Bunker desk", "href": "/bunker", "roles": ["bunker", "operations", "technical", "management", "chartering"]},
    {"id": "ship", "label": "Ship management", "href": "/ship", "roles": ["technical", "operations", "management"]},
    {"id": "finance", "label": "Finance desk", "href": "/finance", "roles": ["finance", "demurrage", "management"]},
    {"id": "emissions", "label": "Emissions / FuelEU", "href": "/emissions", "roles": ["operations", "management", "technical", "finance"]},
    {"id": "pool", "label": "Pooling", "href": "/pool", "roles": ["pool_manager", "management", "finance"]},
    {"id": "trading", "label": "Trading & risk", "href": "/trading", "roles": ["risk", "management", "chartering", "finance"]},
    {"id": "twin", "label": "Fleet Twin", "href": "/twin", "roles": ["operations", "management", "technical", "risk"]},
    {"id": "exceptions", "label": "Exceptions", "href": "/exceptions", "roles": ["*"]},
    {"id": "analytics", "label": "Analytics", "href": "/analytics", "roles": ["management", "finance", "pool_manager"]},
    {"id": "ai_chat", "label": "MariAI", "href": "/ai/chat", "roles": ["chartering", "operations", "management", "bunker"]},
    {"id": "market", "label": "Market data", "href": "/analytics/market", "roles": ["chartering", "operations", "management", "bunker"]},
    {"id": "reports", "label": "Reports", "href": "/analytics/reports", "roles": ["management", "finance", "chartering", "operations"]},
    {"id": "compliance", "label": "Carbon compliance", "href": "/emissions/compliance", "roles": ["operations", "management", "technical", "finance"]},
]

NAV_ADMIN_DESK: list[dict[str, Any]] = [
    {"id": "home", "label": "Workbench", "href": "/home", "roles": ["tenant_admin"]},
    {"id": "dashboards", "label": "Live dashboards", "href": "/dashboards", "roles": ["tenant_admin"]},
    {"id": "tasks", "label": "Tasks", "href": "/tasks", "roles": ["tenant_admin"]},
    {"id": "estimates", "label": "Estimates", "href": "/estimates", "roles": ["tenant_admin"]},
    {"id": "ops", "label": "Voyages", "href": "/operations/voyages", "roles": ["tenant_admin"]},
    {"id": "bunker", "label": "Bunker desk", "href": "/bunker", "roles": ["tenant_admin"]},
    {"id": "finance", "label": "Finance desk", "href": "/finance", "roles": ["tenant_admin"]},
    {"id": "emissions", "label": "Emissions / FuelEU", "href": "/emissions", "roles": ["tenant_admin"]},
    {"id": "pool", "label": "Pooling", "href": "/pool", "roles": ["tenant_admin"]},
    {"id": "trading", "label": "Trading & risk", "href": "/trading", "roles": ["tenant_admin"]},
    {"id": "ship", "label": "Ship management", "href": "/ship", "roles": ["tenant_admin"]},
]

NAV_MASTER: list[dict[str, Any]] = [
    {"id": "vessels", "label": "Vessels", "href": "/masterdata/vessels", "roles": ["chartering", "operations", "tenant_admin", "technical", "bunker"]},
    {"id": "ports", "label": "Ports", "href": "/masterdata/ports", "roles": ["operations", "chartering", "tenant_admin"]},
    {"id": "port_reference", "label": "Port reference", "href": "/masterdata/port-reference", "roles": ["operations", "chartering", "tenant_admin"]},
    {"id": "fuel_zones", "label": "Fuel zones", "href": "/masterdata/fuel-zones", "roles": ["operations", "bunker", "tenant_admin", "compliance"]},
    {"id": "parties", "label": "Counterparties", "href": "/masterdata/counterparties", "roles": ["chartering", "finance", "tenant_admin", "compliance"]},
]

NAV_ADMIN: list[dict[str, Any]] = [
    {"id": "inbox", "label": "Approval inbox", "href": "/workflows/inbox", "roles": ["tenant_admin", "management", "finance", "chartering"]},
    {"id": "settings_hub", "label": "System settings", "href": "/settings", "roles": ["tenant_admin"]},
]

NAV_PLATFORM: list[dict[str, Any]] = [
    {"id": "plat_home", "label": "Operator console", "href": "/platform", "roles": ["platform_admin"]},
    {"id": "plat_tenants", "label": "Tenants & licenses", "href": "/platform/tenants", "roles": ["platform_admin"]},
    {"id": "plat_ops", "label": "Data & deployment", "href": "/platform/ops", "roles": ["platform_admin"]},
    {"id": "plat_saas", "label": "Plans & usage", "href": "/platform/saas", "roles": ["platform_admin"]},
    {"id": "plat_brand", "label": "Product branding", "href": "/platform/branding", "roles": ["platform_admin"]},
    {"id": "plat_identity", "label": "Identity & email", "href": "/platform/identity", "roles": ["platform_admin"]},
    {"id": "plat_health", "label": "Estate health", "href": "/platform/health", "roles": ["platform_admin"]},
]

# ── Module definitions (iMOS-style functional grouping) ──────────────

MODULES: list[dict[str, Any]] = [
    {
        "id": "chartering",
        "label": "Chartering",
        "item_ids": ["estimates", "charters", "email", "trading"],
        "roles": ["chartering", "management", "risk"],
        "collapsed_default": False,
    },
    {
        "id": "operations",
        "label": "Operations",
        "item_ids": ["ops", "marilink", "bunker", "emissions", "compliance", "exceptions"],
        "roles": ["operations", "management", "technical", "bunker"],
        "collapsed_default": False,
    },
    {
        "id": "finance",
        "label": "Finance",
        "item_ids": ["finance", "pool"],
        "roles": ["finance", "demurrage", "management", "pool_manager"],
        "collapsed_default": False,
    },
    {
        "id": "technical",
        "label": "Technical",
        "item_ids": ["ship", "twin"],
        "roles": ["technical", "operations", "management", "risk"],
        "collapsed_default": False,
    },
    {
        "id": "analytics",
        "label": "Analytics & AI",
        "item_ids": ["dashboards", "analytics", "market", "reports", "ai_chat"],
        "roles": ["*"],
        "collapsed_default": False,
    },
    {
        "id": "platform_mod",
        "label": "Platform",
        "item_ids": ["plat_home", "plat_tenants", "plat_ops", "plat_saas", "plat_brand", "plat_identity", "plat_health"],
        "roles": ["platform_admin"],
        "collapsed_default": False,
    },
]

MODULE_ORDER: list[str] = [m["id"] for m in MODULES]

# Per-role preferred module order (first N modules shown first)
ROLE_MODULE_PRIORITY: dict[str, list[str]] = {
    "chartering": ["chartering", "analytics", "operations", "finance", "technical"],
    "operations": ["operations", "technical", "analytics", "chartering", "finance"],
    "finance": ["finance", "analytics", "chartering", "operations", "technical"],
    "demurrage": ["finance", "analytics"],
    "technical": ["technical", "operations", "analytics", "finance"],
    "management": ["analytics", "chartering", "operations", "finance", "technical"],
    "tenant_admin": ["analytics", "chartering", "operations", "finance", "technical"],
    "platform_admin": ["platform_mod"],
    "pool_manager": ["finance", "analytics"],
    "risk": ["chartering", "technical", "analytics"],
    "bunker": ["operations", "analytics"],
    "viewer": ["analytics"],
}

# Legacy alias — kept for back-compat; no longer used by build_navigation
ROLE_DESK_PRIORITY: dict[str, list[str]] = ROLE_MODULE_PRIORITY

WORKSPACES: dict[str, dict[str, Any]] = {
    "chartering_day": {
        "id": "chartering_day",
        "label": "Chartering Day",
        "roles": ["chartering", "tenant_admin"],
        "home_focus": ["pipeline", "estimates", "email"],
    },
    "ops_night": {
        "id": "ops_night",
        "label": "Ops Night",
        "roles": ["operations", "tenant_admin"],
        "home_focus": ["voyages", "eta_risk", "tasks"],
    },
    "finance_desk": {
        "id": "finance_desk",
        "label": "Finance Desk",
        "roles": ["finance", "demurrage", "tenant_admin"],
        "home_focus": ["aging", "invoices", "claims"],
    },
    "technical_desk": {
        "id": "technical_desk",
        "label": "Technical Desk",
        "roles": ["technical", "tenant_admin", "operations"],
        "home_focus": ["ship", "certs", "work_orders"],
    },
    "platform_ops": {
        "id": "platform_ops",
        "label": "Platform Ops",
        "roles": ["platform_admin"],
        "home_focus": ["tenants", "licenses", "health", "ops"],
    },
    "management": {
        "id": "management",
        "label": "Management",
        "roles": ["management", "tenant_admin"],
        "home_focus": ["tce", "twin", "pnl"],
    },
}

HOME_WIDGETS: dict[str, list[dict[str, Any]]] = {
    "chartering": [
        {"id": "dash", "title": "Chartering live wall", "href": "/dashboards/chartering", "hint": "Fullscreen pipeline & market pulse"},
        {"id": "pipeline", "title": "Opportunity pipeline", "href": "/estimates", "hint": "Open estimates & convert to CP"},
        {"id": "email", "title": "Recap inbox", "href": "/email/review", "hint": "Confirm AI-parsed fixtures"},
        {"id": "charters", "title": "Active fixtures", "href": "/charters", "hint": "Approve / activate CPs"},
    ],
    "operations": [
        {"id": "dash", "title": "Ops situation room", "href": "/dashboards/operations", "hint": "Fullscreen ETA & fleet wall"},
        {"id": "voyages", "title": "In-progress voyages", "href": "/operations/voyages", "hint": "ETA, NOR, SOF"},
        {"id": "bunker", "title": "Bunker desk", "href": "/bunker", "hint": "Stem & ROB"},
        {"id": "emissions", "title": "Emissions / FuelEU", "href": "/emissions", "hint": "EU ETS · FuelEU"},
        {"id": "twin", "title": "Fleet positions", "href": "/twin", "hint": "L1 map & alerts"},
        {"id": "ship", "title": "Ship management", "href": "/ship", "hint": "Technical overlap with ops"},
    ],
    "finance": [
        {"id": "dash", "title": "Finance cash wall", "href": "/dashboards/finance", "hint": "AR aging live"},
        {"id": "invoices", "title": "Invoice desk", "href": "/finance", "hint": "Issue, collect, age"},
        {"id": "accruals", "title": "Voyage accruals", "href": "/finance", "hint": "Period close / TC hire"},
        {"id": "claims", "title": "Claims / laytime", "href": "/finance", "hint": "Demurrage workflow"},
    ],
    "demurrage": [
        {"id": "dash", "title": "Laytime wall", "href": "/dashboards/demurrage", "hint": "Time-bar & claims live"},
        {"id": "laytime", "title": "Laytime queue", "href": "/finance", "hint": "Calculate & finalize"},
        {"id": "claims", "title": "Time-bar claims", "href": "/finance", "hint": "Settle demurrage"},
    ],
    "management": [
        {"id": "dash", "title": "Executive command wall", "href": "/dashboards/management", "hint": "Boss / director fullscreen KPI"},
        {"id": "tce", "title": "TCE board", "href": "/analytics", "hint": "Fleet commercial KPIs"},
        {"id": "twin", "title": "Situation room", "href": "/twin", "hint": "Twin + what-if"},
        {"id": "pool", "title": "Pooling", "href": "/pool", "hint": "Pool points & distribution"},
        {"id": "ship", "title": "Technical fleet", "href": "/ship", "hint": "Owner technical view"},
    ],
    "technical": [
        {"id": "dash", "title": "Technical fleet wall", "href": "/dashboards/technical", "hint": "Certs · PMS · defects live"},
        {"id": "ship", "title": "Ship management", "href": "/ship", "hint": "Fleet technical desk"},
        {"id": "bunker", "title": "Bunker desk", "href": "/bunker", "hint": "ROB · stem · prices"},
        {"id": "twin", "title": "Fleet Twin", "href": "/twin", "hint": "Positions & alerts"},
        {"id": "connectors", "title": "External PMS", "href": "/settings/connectors", "hint": "Sync SpecTec / ABS / ShipNet"},
    ],
    "bunker": [
        {"id": "bunker", "title": "Bunker desk", "href": "/bunker", "hint": "Orders · ROB · quotes"},
        {"id": "ops", "title": "Voyages", "href": "/operations/voyages", "hint": "Link stems to voyages"},
        {"id": "connectors", "title": "Price feeds", "href": "/settings/connectors", "hint": "Bunker index adapters"},
    ],
    "pool_manager": [
        {"id": "pool", "title": "Pooling desk", "href": "/pool", "hint": "Points & distribution"},
        {"id": "analytics", "title": "Pool analytics", "href": "/analytics", "hint": "TCE / contribution"},
        {"id": "dash", "title": "Live wall", "href": "/dashboards", "hint": "Fleet overview"},
    ],
    "risk": [
        {"id": "trading", "title": "Trading & risk", "href": "/trading", "hint": "FFA · hedges · exposure"},
        {"id": "twin", "title": "Fleet Twin", "href": "/twin", "hint": "Positions"},
        {"id": "dash", "title": "Live wall", "href": "/dashboards", "hint": "Market pulse"},
    ],
    "tenant_admin": [
        {"id": "dash", "title": "Control wall", "href": "/dashboards/tenant_admin", "hint": "Adoption & health"},
        {"id": "health", "title": "SelfCheck", "href": "/settings/selfcheck", "hint": "Install & runtime health"},
        {"id": "users", "title": "Users & roles", "href": "/admin/users", "hint": "Invite and assign roles"},
        {"id": "security", "title": "Login & security", "href": "/admin/security", "hint": "SSO methods, domains, invites"},
        {"id": "i18n", "title": "Languages & terms", "href": "/admin/i18n", "hint": "Locale policy & term overrides"},
        {"id": "connectors", "title": "Integration Hub", "href": "/settings/connectors", "hint": "Connector health"},
        {"id": "reference", "title": "Reference data", "href": "/settings/reference", "hint": "Countries · TZ · FX codes"},
        {"id": "office", "title": "Office ecosystem", "href": "/settings/office", "hint": "Teams · SharePoint · Mail · Add-ins"},
    ],
    "platform_admin": [
        {"id": "tenants", "title": "Tenant estate", "href": "/platform/tenants", "hint": "Provision / suspend tenants"},
        {"id": "branding", "title": "Product branding", "href": "/platform/branding", "hint": "Portal logo / icon / copy"},
        {"id": "identity", "title": "Identity & IdP", "href": "/platform/identity", "hint": "Microsoft / Google / email channel"},
        {"id": "i18n", "title": "Languages & terminology", "href": "/platform/i18n", "hint": "en / zh-CN packs & term catalog"},
        {"id": "health", "title": "Platform health", "href": "/platform/health", "hint": "Cross-tenant probes"},
        {"id": "ops", "title": "Data & deployment", "href": "/platform/ops", "hint": "Datastore, init, deploy, alerts"},
        {"id": "console", "title": "Operator console", "href": "/platform", "hint": "Ops overview"},
    ],
    "viewer": [
        {"id": "home", "title": "Read-only workbench", "href": "/home", "hint": "Limited navigation"},
        {"id": "dash", "title": "Management wall (view)", "href": "/dashboards/management", "hint": "If permitted"},
    ],
}

ROLE_DEFAULT_WORKSPACE = {
    "platform_admin": "platform_ops",
    "chartering": "chartering_day",
    "operations": "ops_night",
    "finance": "finance_desk",
    "demurrage": "finance_desk",
    "technical": "technical_desk",
    "management": "management",
    "tenant_admin": "chartering_day",
}


# ── Helpers ──────────────────────────────────────────────────────────

def _role_match(user_roles: list[str], allowed: list[str]) -> bool:
    if "*" in allowed:
        return True
    return any(r in allowed for r in user_roles)


def _primary_role(user_roles: list[str]) -> str:
    for r in (
        "platform_admin",
        "chartering",
        "operations",
        "finance",
        "demurrage",
        "technical",
        "management",
        "tenant_admin",
        "pool_manager",
        "risk",
    ):
        if r in user_roles:
            return r
    return user_roles[0] if user_roles else "viewer"


def _filter_items(items: list[dict[str, Any]], roles: list[str]) -> list[dict[str, Any]]:
    out = []
    seen: set[str] = set()
    for item in items:
        if not _role_match(roles, item["roles"]):
            continue
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append({"id": item["id"], "label": item["label"], "href": item["href"]})
    return out


def _filter_module_items(module: dict[str, Any], roles: list[str]) -> list[dict[str, Any]]:
    """Return role-visible items for a module, preserving catalogue order."""
    if not _role_match(roles, module["roles"]):
        return []
    item_ids = module["item_ids"]
    catalog = {item["id"]: item for item in NAV_DESK}
    out = []
    for iid in item_ids:
        item = catalog.get(iid)
        if item and _role_match(roles, item["roles"]):
            out.append({"id": item["id"], "label": item["label"], "href": item["href"]})
    return out


def _sort_modules(modules: list[dict[str, Any]], roles: list[str]) -> list[dict[str, Any]]:
    primary = _primary_role(roles)
    order = ROLE_MODULE_PRIORITY.get(primary, ROLE_MODULE_PRIORITY.get("viewer", []))
    rank = {mid: i for i, mid in enumerate(order)}
    return sorted(modules, key=lambda m: (rank.get(m["id"], 100), m["label"]))


# ── Public API ───────────────────────────────────────────────────────

def build_navigation(user_roles: list[str], profile_tier: str = "M") -> list[dict[str, Any]]:
    """Module-based nav: Workbench → functional modules → Master → Admin."""
    roles = user_roles or ["viewer"]
    out: list[dict[str, Any]] = []

    # Workbench is always the first item (standalone, not inside a module)
    workbench = {"id": "home", "label": "Workbench", "href": "/home"}
    tasks_items = _filter_items(
        [{"id": "tasks", "label": "Tasks", "href": "/tasks", "roles": ["*"]}], roles
    )
    wb_items = [workbench] + tasks_items
    out.append({"section": "workbench", "label": "Workbench", "items": wb_items, "collapsed_default": False})

    # Functional modules — only include modules with visible items
    visible_modules = []
    for mod in MODULES:
        items = _filter_module_items(mod, roles)
        if items:
            visible_modules.append({**mod, "_items": items})

    for mod in _sort_modules(visible_modules, roles):
        out.append({
            "section": mod["id"],
            "label": mod["label"],
            "items": mod["_items"],
            "collapsed_default": mod.get("collapsed_default", False),
        })

    # Master data
    if not (profile_tier == "S" and "tenant_admin" not in roles):
        master = _filter_items(NAV_MASTER, roles)
        if master:
            out.append({"section": "master", "label": "Master data", "items": master, "collapsed_default": True})

    # Administration
    admin = _filter_items(NAV_ADMIN, roles)
    if admin:
        out.append({"section": "admin", "label": "Administration", "items": admin, "collapsed_default": False})

    return out


def build_workspaces(user_roles: list[str]) -> list[dict[str, Any]]:
    roles = user_roles or ["viewer"]
    ws = []
    for w in WORKSPACES.values():
        if w["id"] == "platform_ops" and "platform_admin" not in roles:
            continue
        if _role_match(roles, w["roles"]) or ("tenant_admin" in roles and w["id"] != "platform_ops"):
            ws.append({"id": w["id"], "label": w["label"]})
    return ws


def build_home_widgets(user_roles: list[str], workspace_id: str | None = None) -> list[dict[str, Any]]:
    roles = user_roles or ["viewer"]
    seen: set[str] = set()
    widgets: list[dict[str, Any]] = []
    order = [
        r
        for r in [
            "platform_admin",
            "tenant_admin",
            "management",
            "chartering",
            "operations",
            "finance",
            "demurrage",
            "technical",
        ]
        if r in roles
    ]
    if not order:
        order = roles
    for role in order:
        for w in HOME_WIDGETS.get(role, []):
            if w["id"] in seen:
                continue
            seen.add(w["id"])
            widgets.append(w)
    if not widgets:
        widgets = list(HOME_WIDGETS.get("viewer", []))
    if workspace_id and workspace_id in WORKSPACES:
        focus = set(WORKSPACES[workspace_id]["home_focus"])
        widgets.sort(key=lambda x: 0 if x["id"] in focus else 1)
    return widgets[:8]


def default_workspace(user_roles: list[str]) -> str:
    for role in user_roles or []:
        if role in ROLE_DEFAULT_WORKSPACE:
            return ROLE_DEFAULT_WORKSPACE[role]
    return "chartering_day"


def build_shell_payload(user_roles: list[str], profile_tier: str = "M") -> dict[str, Any]:
    roles = user_roles or ["viewer"]
    return {
        "roles": roles,
        "navigation": build_navigation(roles, profile_tier),
        "workspaces": build_workspaces(roles),
        "home_widgets": build_home_widgets(roles),
        "default_workspace": default_workspace(roles),
        "quick_actions": [
            {"label": "Live dashboard", "href": "/dashboards"},
            {"label": "Knowledge Centre", "href": "/help"},
        ],
        "is_platform": "platform_admin" in roles,
    }


# Back-compat alias for any imports expecting NAV_CATALOG
NAV_CATALOG = [
    {"section": "desk", "label": "Daily", "items": NAV_DESK},
    {"section": "master", "label": "Master data", "items": NAV_MASTER},
    {"section": "admin", "label": "Administration", "items": NAV_ADMIN},
    {"section": "platform", "label": "Platform", "items": NAV_PLATFORM},
]
