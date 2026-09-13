"""OmniSearch / path ACL — align with sidenav roles + module licenses."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import TenantModuleLicense
from app.schemas import SearchHit
from app.services.shell_nav import (
    NAV_ADMIN,
    NAV_ADMIN_DESK,
    NAV_DESK,
    NAV_MASTER,
    NAV_PLATFORM,
    _role_match,
    build_navigation,
)

# Always visible to any signed-in user
PUBLIC_AUTHED = {
    "nav.home": SearchHit(
        id="nav.home",
        title="Workbench",
        keywords=["home", "dashboard", "workbench", "工作台"],
        module="shell",
        href="/home",
    ),
    "nav.help": SearchHit(
        id="nav.help",
        title="Knowledge Centre",
        keywords=["help", "docs", "knowledge", "faq", "手册", "知识库", "帮助", "问答"],
        module="shell",
        href="/help",
    ),
    "nav.dashboards": SearchHit(
        id="nav.dashboards",
        title="Live dashboards",
        keywords=["dashboard", "看板", "live"],
        module="shell",
        href="/dashboards",
    ),
}

# Extra omni entries beyond sidenav (settings / commands)
EXTRA_OMNI: list[dict[str, Any]] = [
    {
        "hit": SearchHit(
            id="nav.i18n",
            title="Languages & terminology",
            keywords=["i18n", "language", "术语", "terminology", "locale"],
            module="i18n",
            href="/admin/i18n",
        ),
        "roles": ["tenant_admin"],
        "license": "i18n",
    },
    {
        "hit": SearchHit(
            id="nav.plat_i18n",
            title="Platform languages",
            keywords=["i18n", "zh-CN", "terminology"],
            module="i18n",
            href="/platform/i18n",
        ),
        "roles": ["platform_admin"],
        "license": None,
    },
    {
        "hit": SearchHit(
            id="nav.ai",
            title="AI Hub",
            keywords=["ai", "llm", "provider"],
            module="ai",
            href="/settings/ai",
        ),
        "roles": ["tenant_admin"],
        "license": "ai",
    },
    {
        "hit": SearchHit(
            id="nav.reference",
            title="参考数据源",
            keywords=["reference", "country", "timezone", "currency", "国家", "时区", "货币", "字典", "船型"],
            module="masterdata",
            href="/settings/reference",
        ),
        "roles": ["tenant_admin"],
        "license": "masterdata",
    },
    {
        "hit": SearchHit(
            id="nav.connectors",
            title="Connectors",
            keywords=["connector", "integration"],
            module="integration",
            href="/settings/connectors",
        ),
        "roles": ["tenant_admin"],
        "license": "integration",
    },
    {
        "hit": SearchHit(
            id="nav.office",
            title="Office ecosystem",
            keywords=["office", "teams", "sharepoint", "onedrive", "outlook", "m365", "graph", "webhook"],
            module="integration",
            href="/settings/office",
        ),
        "roles": ["tenant_admin"],
        "license": "integration",
    },
    {
        "hit": SearchHit(
            id="cmd.selfcheck",
            title="Run SelfCheck",
            keywords=["health", "selfcheck"],
            module="selfcheck",
            href="/settings/selfcheck",
            action="selfcheck.run",
        ),
        "roles": ["tenant_admin"],
        "license": "selfcheck",
    },
    {
        "hit": SearchHit(
            id="cmd.migrate",
            title="Start Migration",
            keywords=["migrate", "pst", "o365", "excel"],
            module="dataops",
            href="/settings/dataops/migrate",
        ),
        "roles": ["tenant_admin"],
        "license": "dataops",
    },
    {
        "hit": SearchHit(
            id="cmd.backup",
            title="Backup Now",
            keywords=["backup", "snapshot"],
            module="dataops",
            href="/settings/dataops/backup",
            action="dataops.backup",
        ),
        "roles": ["tenant_admin"],
        "license": "dataops",
    },
    {
        "hit": SearchHit(
            id="nav.licenses",
            title="Module Licenses",
            keywords=["license", "modules"],
            module="license",
            href="/settings/licenses",
        ),
        "roles": ["tenant_admin"],
        "license": None,
    },
    {
        "hit": SearchHit(
            id="nav.apikeys",
            title="API Keys",
            keywords=["api", "key"],
            module="apim",
            href="/settings/api-keys",
        ),
        "roles": ["tenant_admin"],
        "license": "apim",
    },
    {
        "hit": SearchHit(
            id="nav.settings",
            title="系统设置",
            keywords=["settings", "admin", "系统设置", "设置"],
            module="shell",
            href="/settings",
        ),
        "roles": ["tenant_admin"],
        "license": None,
    },
    {
        "hit": SearchHit(
            id="nav.recycle",
            title="回收站",
            keywords=["recycle", "trash", "回收站", "删除"],
            module="shell",
            href="/settings/recycle",
        ),
        "roles": ["tenant_admin"],
        "license": None,
    },
    {
        "hit": SearchHit(
            id="nav.users",
            title="Users & roles",
            keywords=["users", "roles", "用户", "角色"],
            module="shell",
            href="/admin/users",
        ),
        "roles": ["tenant_admin"],
        "license": None,
    },
]

# Map sidenav id -> omni SearchHit fields
NAV_HIT_META: dict[str, dict[str, Any]] = {
    "home": {"title": "Workbench", "keywords": ["home", "dashboard", "workbench"], "module": "shell", "license": None},
    "dashboards": {"title": "Live dashboards", "keywords": ["dashboard", "看板"], "module": "shell", "license": None},
    "estimates": {"title": "Estimates", "keywords": ["estimate", "tce", "估算"], "module": "estimate", "license": "estimate"},
    "charters": {"title": "Charters", "keywords": ["charter", "cp", "fixture", "租约"], "module": "chartering", "license": "chartering"},
    "email": {"title": "Email Review", "keywords": ["email", "recap", "review"], "module": "email", "license": "email"},
    "ops": {"title": "Operations", "keywords": ["voyage", "ops", "schedule", "航次"], "module": "operations", "license": "operations"},
    "bunker": {"title": "Bunker desk", "keywords": ["bunker", "fuel", "燃油", "ROB"], "module": "bunker", "license": "bunker"},
    "ship": {"title": "Ship management", "keywords": ["ship", "pms", "certificate", "crew"], "module": "ship_mgmt", "license": "ship_mgmt"},
    "finance": {"title": "Finance", "keywords": ["invoice", "laytime", "claim", "财务"], "module": "finance", "license": "finance"},
    "emissions": {"title": "Emissions / FuelEU", "keywords": ["emission", "fueleu", "ets", "碳", "排放"], "module": "emissions", "license": "emissions"},
    "pool": {"title": "Pooling", "keywords": ["pool", "pooling", "船队池"], "module": "pooling", "license": "pooling"},
    "trading": {"title": "Trading & risk", "keywords": ["risk", "trading", "ffa", "风控"], "module": "risk", "license": "risk"},
    "twin": {"title": "Fleet Twin", "keywords": ["twin", "map", "ais"], "module": "twin", "license": "twin"},
    "analytics": {"title": "Analytics", "keywords": ["report", "tce", "pnl"], "module": "analytics", "license": "analytics"},
    "vessels": {"title": "Vessels", "keywords": ["vessel", "imo", "ship", "船舶"], "module": "masterdata", "license": "masterdata"},
    "ports": {"title": "Ports", "keywords": ["port", "unlocode", "港口"], "module": "masterdata", "license": "masterdata"},
    "parties": {"title": "Counterparties", "keywords": ["counterparty", "charterer", "对手方"], "module": "masterdata", "license": "masterdata"},
    "inbox": {"title": "Approval inbox", "keywords": ["workflow", "approval", "审批"], "module": "shell", "license": None},
    "settings_hub": {"title": "系统设置", "keywords": ["settings", "admin", "系统设置", "设置"], "module": "shell", "license": None},
    "plat_home": {"title": "Operator console", "keywords": ["platform", "operator"], "module": "platform", "license": None},
    "plat_tenants": {"title": "Tenants & licenses", "keywords": ["tenant", "license"], "module": "platform", "license": None},
    "plat_ops": {
        "title": "Platform data & deployment",
        "keywords": ["ops", "database", "postgres", "deploy", "运维"],
        "module": "platform",
        "license": None,
    },
    "plat_saas": {"title": "Plans & usage", "keywords": ["saas", "plan", "usage"], "module": "platform", "license": None},
    "plat_brand": {"title": "Product branding", "keywords": ["branding", "logo"], "module": "platform", "license": None},
    "plat_identity": {"title": "Identity & email", "keywords": ["identity", "smtp", "sso"], "module": "platform", "license": None},
    "plat_health": {"title": "Estate health", "keywords": ["health", "estate"], "module": "platform", "license": None},
}


def _licensed_set(db: Session, tenant_id) -> set[str] | None:
    """None means unlock-all (dev)."""
    if get_settings().license_dev_unlock == "all":
        return None
    rows = db.scalars(
        select(TenantModuleLicense.module_code).where(
            TenantModuleLicense.tenant_id == tenant_id,
            TenantModuleLicense.status.in_(["active", "grace"]),
        )
    ).all()
    return set(rows)


def _module_ok(licensed: set[str] | None, module_code: str | None) -> bool:
    if not module_code:
        return True
    if licensed is None:
        return True
    return module_code in licensed


def _nav_catalog() -> list[dict[str, Any]]:
    """Flatten nav definitions with roles."""
    out: list[dict[str, Any]] = []
    for group in (NAV_DESK, NAV_ADMIN_DESK, NAV_MASTER, NAV_ADMIN, NAV_PLATFORM):
        for item in group:
            meta = NAV_HIT_META.get(item["id"], {})
            out.append(
                {
                    "id": item["id"],
                    "href": item["href"],
                    "roles": item["roles"],
                    "title": meta.get("title") or item["label"],
                    "keywords": meta.get("keywords") or [item["label"].lower()],
                    "module": meta.get("module") or "shell",
                    "license": meta.get("license"),
                }
            )
    return out


def allowed_omni_hits(db: Session, *, tenant_id, roles: list[str]) -> list[SearchHit]:
    roles = roles or ["viewer"]
    licensed = _licensed_set(db, tenant_id)
    hits: list[SearchHit] = []
    seen: set[str] = set()

    # Always-on shell
    for key, hit in PUBLIC_AUTHED.items():
        if key not in seen:
            hits.append(hit)
            seen.add(key)

    for item in _nav_catalog():
        if not _role_match(roles, item["roles"]):
            continue
        # tenant_admin-only admin desk entries already have roles; business desks need match
        if not _module_ok(licensed, item.get("license")):
            continue
        oid = f"nav.{item['id']}"
        if oid in seen or item["id"] in seen:
            continue
        hits.append(
            SearchHit(
                id=oid,
                title=item["title"],
                keywords=list(item["keywords"]),
                module=item["module"],
                href=item["href"],
            )
        )
        seen.add(oid)
        seen.add(item["id"])

    for extra in EXTRA_OMNI:
        if not _role_match(roles, extra["roles"]):
            continue
        if not _module_ok(licensed, extra.get("license")):
            continue
        hit: SearchHit = extra["hit"]
        if hit.id in seen:
            continue
        hits.append(hit)
        seen.add(hit.id)

    return hits


def filter_omni_query(hits: list[SearchHit], q: str) -> list[SearchHit]:
    qn = q.strip().lower()
    if not qn:
        return hits[:8]
    out = []
    for item in hits:
        blob = " ".join([item.title.lower(), item.id, *(item.keywords or [])])
        if qn in blob:
            out.append(item)
    return out


def path_is_allowed(db: Session, *, tenant_id, roles: list[str], path: str) -> bool:
    """Whether the user may open this app path (prefix match on allowed hrefs)."""
    p = (path or "/").split("?")[0]
    if not p.startswith("/"):
        p = "/" + p
    # Public / account always
    if p == "/" or p.startswith("/login") or p.startswith("/help") or p.startswith("/account") or p.startswith("/manual"):
        return True
    if p.startswith("/home") or p.startswith("/dashboards"):
        return True

    allowed_hrefs = {h.href for h in allowed_omni_hits(db, tenant_id=tenant_id, roles=roles) if h.href}
    # Also include navigation hrefs (same set usually)
    for sec in build_navigation(roles):
        for it in sec.get("items") or []:
            if it.get("href"):
                allowed_hrefs.add(it["href"])

    if "tenant_admin" in roles:
        allowed_hrefs.update({"/settings", "/admin", "/workflows/inbox"})
    if "platform_admin" in roles:
        allowed_hrefs.add("/platform")

    for href in allowed_hrefs:
        if p == href or p.startswith(href.rstrip("/") + "/"):
            return True
    return False


def allowed_path_prefixes(db: Session, *, tenant_id, roles: list[str]) -> list[str]:
    hits = allowed_omni_hits(db, tenant_id=tenant_id, roles=roles)
    prefixes = sorted({h.href for h in hits if h.href})
    if "tenant_admin" in roles:
        for x in ("/settings", "/admin", "/workflows"):
            if x not in prefixes:
                prefixes.append(x)
    if "platform_admin" in roles and "/platform" not in prefixes:
        prefixes.append("/platform")
    for x in ("/home", "/help", "/account", "/dashboards"):
        if x not in prefixes:
            prefixes.append(x)
    return sorted(prefixes)
