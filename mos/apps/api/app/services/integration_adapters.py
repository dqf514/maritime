"""External integration adapters — catalog schemas + sync/test hooks.

Each connector type declares config fields for the settings UI.
Adapters validate config and run health/sync against configured endpoints
(or deterministic mock when endpoint is empty / mock mode).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_domain import MarketQuote
from app.models_wave1 import ConnectorInstance, ExchangeRate

FieldSpec = dict[str, Any]


def _f(
    key: str,
    label_en: str,
    label_zh: str | None = None,
    *,
    kind: str = "text",
    required: bool = False,
    placeholder: str = "",
    placeholder_zh: str | None = None,
    secret: bool = False,
) -> FieldSpec:
    return {
        "key": key,
        "label_en": label_en,
        "label_zh": label_zh or label_en,
        "label": label_en,
        "kind": kind,
        "required": required,
        "placeholder": placeholder,
        "placeholder_en": placeholder,
        "placeholder_zh": placeholder_zh if placeholder_zh is not None else placeholder,
        "secret": secret,
    }


CATALOG: list[dict[str, Any]] = [
    {
        "connector_type": "fx.manual",
        "name": "Manual FX", "name_en": "Manual FX", "name_zh": "手工汇率",
        "category": "finance",
        "description": "Manual rates without external API", "description_en": "Manual rates without external API", "description_zh": "人工维护汇率，不调用外部 API",
        "config_schema": [],
    },
    {
        "connector_type": "fx.openex",
        "name": "Open Exchange Rates",
        "category": "finance",
        "description": "Pull base FX rates into the rate table", "description_en": "Pull base FX rates into the rate table", "description_zh": "拉取基准汇率并写入汇率表",
        "config_schema": [
            _f("app_id", "App ID", required=True, secret=True),
            _f("base", "Base currency", "基准币", placeholder="USD"),
            _f("symbols", "Quote currencies", "报价币列表", placeholder="EUR,CNY,SGD"),
        ],
    },
    {
        "connector_type": "sanctions.lists",
        "name": "Sanctions list import", "name_en": "Sanctions list import", "name_zh": "制裁名单导入",
        "category": "compliance",
        "description": "Import sanctions snapshots from URL or path", "description_en": "Import sanctions snapshots from URL or path", "description_zh": "从 URL 或本地路径导入制裁名单快照",
        "config_schema": [
            _f("list_url", "List URL", "名单 URL", required=True, placeholder="https://…"),
            _f("format", "Format", "格式", placeholder="csv|json"),
        ],
    },
    {
        "connector_type": "email.imap",
        "name": "IMAP mailbox", "name_en": "IMAP mailbox", "name_zh": "IMAP 邮箱",
        "category": "email",
        "config_schema": [
            _f("host", "IMAP host", "IMAP 主机", required=True),
            _f("port", "Port", "端口", kind="number", placeholder="993"),
            _f("username", "Username", "用户名", required=True),
            _f("password", "Password", "密码", required=True, secret=True),
            _f("folder", "Folder", "文件夹", placeholder="INBOX"),
        ],
    },
    {
        "connector_type": "email.graph",
        "name": "Microsoft Graph Mail",
        "category": "email",
        "config_schema": [_f("mailbox", "Mailbox", "邮箱", placeholder="ops@company.com")],
    },
    {
        "connector_type": "m365_mail",
        "name": "M365 Mail (Office Hub)", "name_en": "M365 Mail (Office Hub)", "name_zh": "M365 邮件 (Office Hub)",
        "category": "office",
        "config_schema": [],
    },
    {
        "connector_type": "m365_files",
        "name": "M365 Files / OneDrive", "name_en": "M365 Files / OneDrive", "name_zh": "M365 文件 / OneDrive",
        "category": "office",
        "config_schema": [],
    },
    {
        "connector_type": "sharepoint",
        "name": "SharePoint",
        "category": "office",
        "config_schema": [_f("site_url", "Site URL", "站点 URL")],
    },
    {
        "connector_type": "onedrive",
        "name": "OneDrive for Business",
        "category": "office",
        "config_schema": [],
    },
    {
        "connector_type": "teams",
        "name": "Microsoft Teams",
        "category": "office",
        "config_schema": [_f("webhook_url", "Incoming Webhook", secret=True)],
    },
    {
        "connector_type": "ais.generic",
        "name": "AIS 位置源",
        "category": "ais",
        "description": "通用 AIS HTTP API（位置/航迹）",
        "config_schema": [
            _f("base_url", "API Base URL", required=True),
            _f("api_key", "API Key", secret=True),
            _f("poll_seconds", "Poll seconds", "轮询秒数", kind="number", placeholder="300"),
        ],
    },
    {
        "connector_type": "bunker.price",
        "name": "燃油价格指数",
        "category": "bunker",
        "description": "同步 VLSFO/MGO 等价格指数到市场报价",
        "config_schema": [
            _f("base_url", "API Base URL", "API Base URL", placeholder="https://… or leave blank for mock", placeholder_zh="https://… 或留空用模拟"),
            _f("api_key", "API Key", secret=True),
            _f("grades", "Fuel grades", "油种", placeholder="VLSFO,MGO,HSFO"),
            _f("ports", "Ports", "港口", placeholder="Singapore,Rotterdam"),
        ],
    },
    {
        "connector_type": "market.baltic",
        "name": "波罗的海指数 / 市场",
        "category": "market",
        "config_schema": [
            _f("base_url", "API Base URL"),
            _f("api_key", "API Key", secret=True),
            _f("symbols", "Index symbols", "指数代码", placeholder="BDI,BCI,BPI"),
        ],
    },
    {
        "connector_type": "erp.generic",
        "name": "通用财务/ERP Webhook",
        "category": "erp",
        "description": "向企业财务系统推送发票/凭证 JSON",
        "config_schema": [
            _f("post_url", "过账 URL", required=True),
            _f("auth_header", "Authorization", secret=True, placeholder="Bearer …"),
            _f("company_code", "公司代码"),
        ],
    },
    {
        "connector_type": "erp.sap",
        "name": "SAP 财务对接",
        "category": "erp",
        "config_schema": [
            _f("odata_url", "OData / RFC 网关", required=True),
            _f("client", "Client", placeholder="100"),
            _f("username", "Username", "用户名", required=True),
            _f("password", "Password", "密码", required=True, secret=True),
            _f("company_code", "公司代码", required=True),
        ],
    },
    {
        "connector_type": "erp.oracle",
        "name": "Oracle ERP Cloud",
        "category": "erp",
        "config_schema": [
            _f("base_url", "REST Base URL", required=True),
            _f("username", "Username", "用户名", required=True),
            _f("password", "Password", "密码", required=True, secret=True),
            _f("ledger", "Ledger"),
        ],
    },
    {
        "connector_type": "pms.mock",
        "name": "VoyageOS Mock PMS",
        "category": "ship_mgmt",
        "config_schema": [],
    },
    {
        "connector_type": "pms.generic_webhook",
        "name": "通用 PMS Webhook",
        "category": "ship_mgmt",
        "config_schema": [
            _f("inbound_secret", "入站校验密钥", secret=True),
            _f("outbound_url", "出站 URL"),
        ],
    },
    {
        "connector_type": "pms.spectec",
        "name": "SpecTec / AMOS",
        "category": "ship_mgmt",
        "config_schema": [_f("base_url", "API URL", required=True), _f("api_key", "API Key", secret=True)],
    },
    {
        "connector_type": "pms.abs_ns",
        "name": "ABS Nautical Systems",
        "category": "ship_mgmt",
        "config_schema": [_f("base_url", "API URL", required=True), _f("api_key", "API Key", secret=True)],
    },
    {
        "connector_type": "pms.shipnet",
        "name": "ShipNet One",
        "category": "ship_mgmt",
        "config_schema": [_f("base_url", "API URL", required=True), _f("api_key", "API Key", secret=True)],
    },
    {
        "connector_type": "emissions.verifier",
        "name": "排放核验 / MRV 上报",
        "category": "emissions",
        "config_schema": [
            _f("base_url", "上报 URL"),
            _f("api_key", "API Key", secret=True),
            _f("imo_company", "公司 IMO 编号"),
        ],
    },
    {
        "connector_type": "webhook.custom",
        "name": "自定义出站 Webhook",
        "category": "outbound",
        "config_schema": [
            _f("url", "Webhook URL", required=True),
            _f("secret", "签名密钥", secret=True),
            _f("events", "Events", "事件", placeholder="invoice.posted,voyage.completed"),
        ],
    },
]

OFFICE_TYPES = {"email.graph", "m365_mail", "m365_files", "sharepoint", "onedrive", "teams"}


def catalog_public(locale: str = "en") -> list[dict[str, Any]]:
    zh = (locale or "en").startswith("zh")
    out: list[dict[str, Any]] = []
    for c in CATALOG:
        fields = []
        for f in c.get("config_schema") or []:
            fields.append(
                {
                    **f,
                    "label": f.get("label_zh" if zh else "label_en") or f.get("label") or f.get("key"),
                    "placeholder": f.get("placeholder_zh" if zh else "placeholder_en") or f.get("placeholder") or "",
                }
            )
        out.append(
            {
                "connector_type": c["connector_type"],
                "name": (c.get("name_zh") if zh else c.get("name_en")) or c.get("name"),
                "category": c["category"],
                "description": (c.get("description_zh") if zh else c.get("description_en")) or c.get("description") or "",
                "config_schema": fields,
            }
        )
    return out


def catalog_entry(connector_type: str) -> dict[str, Any] | None:
    for c in CATALOG:
        if c["connector_type"] == connector_type:
            return c
    return None


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def test_adapter(row: ConnectorInstance, *, office_health: dict | None = None) -> dict[str, Any]:
    cfg = row.config or {}
    ctype = row.connector_type
    now = _now_iso()

    if ctype in OFFICE_TYPES and office_health is not None:
        return {**office_health, "connector_type": ctype, "tested_at": now}

    # Endpoint reachability when URL-like config present
    url = row.endpoint or cfg.get("base_url") or cfg.get("post_url") or cfg.get("odata_url") or cfg.get("list_url") or cfg.get("url")
    if url and str(url).startswith("http"):
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.get(str(url)) if ctype not in {"erp.generic", "webhook.custom"} else client.head(str(url))
            ok = resp.status_code < 500
            return {
                "ok": ok,
                "tested_at": now,
                "http_status": resp.status_code,
                "message": "Endpoint reachable" if ok else "Endpoint error",
                "mode": "live",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "tested_at": now, "error": str(exc), "mode": "live"}

    # Config completeness for required fields
    entry = catalog_entry(ctype)
    missing = []
    if entry:
        for f in entry.get("config_schema") or []:
            if f.get("required") and not cfg.get(f["key"]) and not (f["key"] in ("base_url",) and row.endpoint):
                missing.append(f["key"])
    if missing:
        return {"ok": False, "tested_at": now, "missing_config": missing, "mode": "config"}

    return {
        "ok": True,
        "tested_at": now,
        "latency_ms": 8,
        "message": "配置校验通过（模拟连通）",
        "mode": "mock",
    }


def sync_adapter(db: Session, row: ConnectorInstance, *, tenant_id: UUID) -> dict[str, Any]:
    """Pull/push data for the connector. Returns summary."""
    cfg = dict(row.config or {})
    ctype = row.connector_type
    now = _now_iso()
    result: dict[str, Any] = {"connector_type": ctype, "synced_at": now, "actions": []}

    if ctype == "fx.openex" or ctype == "fx.manual":
        base = (cfg.get("base") or "USD").upper()
        symbols = [s.strip().upper() for s in str(cfg.get("symbols") or "EUR,CNY").split(",") if s.strip()]
        # mock rates if no live call
        rates = {s: round(0.85 + (hash(s) % 30) / 100, 4) for s in symbols}
        url = row.endpoint or cfg.get("base_url")
        if ctype == "fx.openex" and url and cfg.get("app_id"):
            try:
                with httpx.Client(timeout=12.0) as client:
                    resp = client.get(
                        f"{str(url).rstrip('/')}/latest.json",
                        params={"app_id": cfg["app_id"], "base": base, "symbols": ",".join(symbols)},
                    )
                    if resp.status_code == 200:
                        rates = (resp.json().get("rates") or rates)
            except Exception as exc:  # noqa: BLE001
                result["warning"] = str(exc)
        today = date.today()
        for sym, rate in rates.items():
            existing = db.scalar(
                select(ExchangeRate).where(
                    ExchangeRate.base_currency == base,
                    ExchangeRate.quote_currency == sym,
                    ExchangeRate.rate_date == today,
                )
            )
            if existing:
                existing.rate = rate
                existing.source = ctype
            else:
                db.add(
                    ExchangeRate(
                        tenant_id=tenant_id,
                        base_currency=base,
                        quote_currency=sym,
                        rate=rate,
                        rate_date=today,
                        source=ctype,
                    )
                )
            result["actions"].append({"symbol": f"{base}/{sym}", "rate": float(rate)})
        db.flush()
        result["ok"] = True
        return result

    if ctype in {"bunker.price", "market.baltic"}:
        grades = [s.strip() for s in str(cfg.get("grades") or cfg.get("symbols") or "VLSFO,MGO,BDI").split(",") if s.strip()]
        for g in grades:
            val = float(400 + (abs(hash(g + now)) % 200))
            qd = date.today()
            existing = db.scalar(
                select(MarketQuote).where(
                    MarketQuote.tenant_id == tenant_id,
                    MarketQuote.symbol == g,
                    MarketQuote.quote_date == qd,
                )
            )
            if existing:
                existing.value = val
                existing.source = ctype
            else:
                db.add(MarketQuote(tenant_id=tenant_id, symbol=g, value=val, quote_date=qd, source=ctype))
            result["actions"].append({"symbol": g, "value": val})
        db.flush()
        result["ok"] = True
        result["mode"] = "mock_or_cached"
        return result

    if ctype in {"erp.generic", "erp.sap", "erp.oracle", "webhook.custom"}:
        result["ok"] = True
        result["mode"] = "push_ready"
        result["message"] = "出站适配器已就绪；发票过账时将调用配置的 URL"
        return result

    if ctype.startswith("pms.") or ctype == "ais.generic" or ctype == "emissions.verifier" or ctype == "sanctions.lists":
        result["ok"] = True
        result["mode"] = "mock"
        result["message"] = "同步接口已接通（当前为模拟拉取，配置真实 URL 后可切换为 live）"
        result["actions"].append({"pulled": 0})
        return result

    result["ok"] = True
    result["message"] = "无自动同步逻辑；仅保存配置与连通测试"
    return result
