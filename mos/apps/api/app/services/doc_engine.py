"""单据渲染引擎 — Jinja2 模板 → HTML → PDF（Playwright 无头 Chromium）。

设计要点：
- **模板是租户可编辑的不可信输入**：一律用 :class:`jinja2.sandbox.SandboxedEnvironment`
  渲染，且上下文只放纯 dict/list/标量（不传 ORM 对象），杜绝通过模板读任意属性。
- **PDF 引擎可选**：playwright/Chromium 未安装时 :func:`html_to_pdf` 抛
  :class:`PDFEngineUnavailable`，上层回落到返回 HTML（浏览器打印即得 PDF）。
  这样开发机/CI 不装 Chromium 也能跑全套测试。
- **浏览器常驻复用**：Chromium 启动约 1s，逐次拉起会让"导出 PDF"不可用。
  这里维护模块级单例 + 线程锁；失败则下次重试，不缓存坏句柄。
- **信头统一**：公司抬头（TenantCompanyProfile）+ 默认银行账户 + logo 内联
  base64（PDF 不支持外部 URL 引图，必须内联）。

出档留痕见 :class:`app.models_doc.DocumentRender` —— PDF 字节落盘
``uploads/documents/{tenant_id}/``，库中只存路径与信头快照。
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from jinja2 import StrictUndefined
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models_doc import DocumentRender, DocumentTemplate

log = logging.getLogger("marios.doc_engine")

UPLOAD_ROOT = Path(__file__).resolve().parent.parent.parent / "uploads"


class PDFEngineUnavailable(RuntimeError):
    """PDF 引擎（playwright + Chromium）不可用 —— 调用方应回落 HTML。"""


class DocumentNotFound(LookupError):
    """实体或模板不存在。"""


# ── 单据类型注册表 ────────────────────────────────────────────────────────
#
# 每个对外单据类型在此登记：显示名、编号字段取法、语言键。
# 上下文由 ``doc_contexts`` 里的 builder 提供；登记表只管"有哪些类型、叫什么"。


@dataclass(frozen=True)
class DocType:
    code: str
    title_en: str
    title_zh: str
    # 该单据的编号在上下文里的字段名（模板用 doc.no 取）
    no_key: str = "no"
    # 是否有行项目表（发票/计算书有，估算单没有）
    has_lines: bool = False
    # 关联模块（用于 require_module 校验）
    module: str = "finance"


DOC_TYPES: dict[str, DocType] = {
    d.code: d
    for d in (
        DocType("invoice", "Invoice", "发票", has_lines=True, module="finance"),
        DocType("credit_note", "Credit Note", "贷记通知单", has_lines=True, module="finance"),
        DocType("laytime_statement", "Laytime Statement", "装卸时间计算书", has_lines=True, module="laytime"),
        DocType("hire_statement", "Hire Statement", "租金账单", has_lines=True, module="chartering"),
        DocType("charter_recap", "Fixture Recap", "租约成交回顾", has_lines=True, module="chartering"),
        DocType("estimate", "Estimate / TCE", "估算报价单", module="estimate"),
        DocType("pda", "Proforma Disbursement Account", "港口使费预付单", has_lines=True, module="finance"),
        DocType("claim", "Statement of Claim", "索赔函", has_lines=True, module="laytime"),
        DocType("sof", "Statement of Facts", "事实记录", has_lines=True, module="operations"),
        DocType("coa", "Contract of Affreightment", "包运合同", module="chartering"),
        DocType("voyage_instruction", "Voyage Instruction", "航次指令", module="operations"),
        DocType("statement_of_account", "Statement of Account", "对账单", has_lines=True, module="finance"),
        DocType("remittance_advice", "Remittance Advice", "汇款通知", has_lines=True, module="finance"),
        DocType("bdn", "Bunker Delivery Note", "供油报告", has_lines=True, module="bunker"),
    )
}


# ── 信头 ──────────────────────────────────────────────────────────────────


def _logo_data_uri(db: Session, tenant_id: UUID, logo_url: str | None) -> str | None:
    """把 logo 读成 data URI —— PDF 不会去加载外部 URL。

    ``logo_url`` 可能是相对路径 ``/uploads/branding/<tid>/x.png``，也可能是
    管理端存下来的绝对 URL ``http://host/uploads/branding/<tid>/x.png?v=1``。
    两者都归一到路径段再校验 —— 只认本租户 branding 目录下的文件，
    顺带挡掉路径穿越与外链。
    """
    if not logo_url:
        return None
    path = str(logo_url).split("?")[0].split("#")[0]
    # 绝对 URL → 只取 path（不含 scheme/host，外链在此被切断）
    if "://" in path:
        path = path.split("://", 1)[1]
        path = "/" + path.split("/", 1)[1] if "/" in path else "/"
    m = re.match(r"^/uploads/branding/([0-9a-fA-F-]{36})/([^/]+)$", path)
    if not m or m.group(1).lower() != str(tenant_id).lower():
        log.warning("doc_engine: rejecting logo path %r", logo_url)
        return None
    name = m.group(2)
    if "/" in name or "\\" in name or ".." in name:
        return None
    dest = UPLOAD_ROOT / "branding" / str(tenant_id) / name
    try:
        raw = dest.read_bytes()
    except OSError:
        return None
    if not raw or len(raw) > 1_500_000:
        return None
    ctype = mimetypes.guess_type(name)[0] or "image/png"
    return f"data:{ctype};base64,{base64.b64encode(raw).decode('ascii')}"


def _default_bank_account(db: Session, tenant_id: UUID) -> dict:
    """默认银行账户 —— 对外单据的收款指引（有则展示，无则留空不报错）。"""
    out = {
        "bank_name": None,
        "account_name": None,
        "account_number": None,
        "swift": None,
        "iban": None,
        "currency": None,
    }
    try:
        from app.models_finance_ext import BankAccount

        row = db.scalar(
            select(BankAccount)
            .where(BankAccount.tenant_id == tenant_id)
            .order_by(BankAccount.is_default.desc())
            .limit(1)
        )
        if row is not None:
            for k in out:
                out[k] = getattr(row, k, None)
    except Exception:  # noqa: BLE001 — 银行账户缺失不应阻断出单
        log.exception("doc_engine: bank account lookup failed")
    return out


def build_letterhead(db: Session, tenant_id: UUID) -> dict:
    """公司抬头上下文（模板里的 ``company`` / ``bank``）。"""
    from app.models import Tenant
    from app.models_saas import TenantCompanyProfile

    tenant = db.get(Tenant, tenant_id)
    row = db.scalar(select(TenantCompanyProfile).where(TenantCompanyProfile.tenant_id == tenant_id))
    fallback_name = (tenant.name if tenant else None) or "MariOS"
    if row is None:
        profile = {
            "legal_name": fallback_name,
            "display_name": fallback_name,
            "address": None, "phone": None, "email": None, "website": None,
            "tax_no": None, "registration_no": None,
            "brand_primary": "#1A9B96", "brand_secondary": None,
            "logo_data": None,
        }
    else:
        profile = {
            "legal_name": row.legal_name or fallback_name,
            "display_name": row.display_name or fallback_name,
            "address": row.address,
            "phone": row.phone,
            # 公司档案里暂无 email 列，从 meta 读（老租户可能手工填过）
            "email": (row.meta or {}).get("email"),
            "website": row.website,
            "tax_no": row.tax_no,
            "registration_no": (row.meta or {}).get("registration_no"),
            "brand_primary": row.brand_primary or "#1A9B96",
            "brand_secondary": row.brand_secondary,
            "logo_data": _logo_data_uri(db, tenant_id, row.logo_url),
        }
    return {"company": profile, "bank": _default_bank_account(db, tenant_id)}


# ── 模板存取 ──────────────────────────────────────────────────────────────


def _template_query(db: Session, tenant_id: UUID):
    return select(DocumentTemplate).where(DocumentTemplate.tenant_id == tenant_id)


def get_template(
    db: Session,
    tenant_id: UUID,
    entity_type: str,
    *,
    code: str = "default",
    locale: str | None = None,
) -> DocumentTemplate | None:
    q = _template_query(db, tenant_id).where(
        DocumentTemplate.entity_type == entity_type,
        DocumentTemplate.code == code,
    )
    if locale:
        q = q.where(DocumentTemplate.locale == locale)
    else:
        q = q.where(DocumentTemplate.is_default.is_(True))
    return db.scalar(q.order_by(DocumentTemplate.locale))


def list_templates(db: Session, tenant_id: UUID, entity_type: str | None = None) -> list[dict]:
    q = _template_query(db, tenant_id)
    if entity_type:
        q = q.where(DocumentTemplate.entity_type == entity_type)
    rows = db.scalars(
        q.order_by(DocumentTemplate.entity_type, DocumentTemplate.code, DocumentTemplate.locale)
    ).all()
    return [
        {
            "id": str(r.id),
            "entity_type": r.entity_type,
            "code": r.code,
            "name": r.name,
            "format": r.format,
            "locale": r.locale,
            "is_default": r.is_default,
            "is_system": r.is_system,
            "version": r.version,
            "enabled": r.enabled,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "edited": bool(r.is_system and (r.body != (r.system_body or "") or r.css != (r.system_css or ""))),
        }
        for r in rows
    ]


def ensure_templates(db: Session, tenant_id: UUID) -> int:
    """把系统内置模板补种到租户（幂等，返回本次新建/同步条数）。

    除了新建，还要**同步内置版本**：否则内置模板修了 bug / 改进版式，
    存量租户永远停在首次补种那一版。同步规则：

    - 租户没改过（``body == system_body``）→ 直接换成新的内置版
    - 租户改过 → 只更新 ``system_body``/``system_css``，不动他们的 ``body``；
      这样"恢复默认"能拿到新版，而他们的定制不会被覆盖

    **并发安全**：这是个读端点也会调的写操作（``GET /documents/templates``）。
    两个请求同时进来会看到同样的"不存在"，然后同时 INSERT，撞
    ``UNIQUE(tenant_id, entity_type, code, locale)`` → 整个请求 500，
    浏览器只看到一句 CORS 报错，页面直接白掉。
    所以插入包在 SAVEPOINT 里：撞了就认输（模板已经在库里了，功能不受影响）。
    """
    from app.services.doc_templates import SYSTEM_TEMPLATES

    created = 0
    pending: list[DocumentTemplate] = []
    for spec in SYSTEM_TEMPLATES:
        system_body = spec["body"]
        system_css = spec.get("css", "")
        exists = db.scalar(
            _template_query(db, tenant_id).where(
                DocumentTemplate.entity_type == spec["entity_type"],
                DocumentTemplate.code == spec.get("code", "default"),
                DocumentTemplate.locale == spec.get("locale", "en"),
            )
        )
        if exists is None:
            pending.append(
                DocumentTemplate(
                    tenant_id=tenant_id,
                    entity_type=spec["entity_type"],
                    code=spec.get("code", "default"),
                    name=spec["name"],
                    format="html",
                    body=system_body,
                    css=system_css,
                    locale=spec.get("locale", "en"),
                    is_default=True,
                    is_system=True,
                    system_body=system_body,
                    system_css=system_css,
                    enabled=True,
                )
            )
            continue
        if not exists.is_system:
            continue  # 租户自建的同名模板，不碰
        # 租户是否偏离过内置版
        unedited = (exists.body or "") == (exists.system_body or "") and \
                   (exists.css or "") == (exists.system_css or "")
        new_system = (exists.system_body or "") != system_body or \
                     (exists.system_css or "") != system_css
        if not new_system:
            continue
        if unedited:
            # 没改过 → 直接升到新内置版
            exists.body, exists.css = system_body, system_css
        exists.system_body, exists.system_css = system_body, system_css
        exists.version = (exists.version or 1) + 1
        exists.updated_at = datetime.now(timezone.utc)
        created += 1

    if pending:
        try:
            # SAVEPOINT：撞唯一约束时只回滚这一批，不牵连整个请求
            with db.begin_nested():
                for row in pending:
                    db.add(row)
                db.flush()
            created += len(pending)
        except IntegrityError:
            # 并发插入 —— 赢家已经建好了，输家认输即可（模板照常能读）。
            # SAVEPOINT 回滚已经把 pending 里那批对象踢出会话，不用再清理。
            log.info("document templates already seeded concurrently; skipping")

    if created:
        db.commit()
    return created


def save_template(
    db: Session,
    tenant_id: UUID,
    template_id: UUID,
    *,
    body: str | None = None,
    css: str | None = None,
    name: str | None = None,
    enabled: bool | None = None,
    is_default: bool | None = None,
    user_id: UUID | None = None,
) -> DocumentTemplate:
    """保存模板编辑。模板是租户输入 —— 这里只做长度与类型校验，渲染侧沙箱兜底。"""
    row = db.get(DocumentTemplate, template_id)
    if not row or row.tenant_id != tenant_id:
        raise DocumentNotFound("template not found")
    if body is not None:
        if len(body) > 400_000:
            raise ValueError("template body too large")
        row.body = body
    if css is not None:
        if len(css) > 200_000:
            raise ValueError("template css too large")
        row.css = css
    if name is not None:
        row.name = name[:128]
    if enabled is not None:
        row.enabled = bool(enabled)
    if is_default is not None:
        row.is_default = bool(is_default)
    row.version = (row.version or 1) + 1
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = user_id
    db.commit()
    db.refresh(row)
    return row


def reset_template(db: Session, tenant_id: UUID, template_id: UUID) -> DocumentTemplate:
    """恢复系统默认版式（system_body / system_css）。"""
    row = db.get(DocumentTemplate, template_id)
    if not row or row.tenant_id != tenant_id:
        raise DocumentNotFound("template not found")
    if not row.is_system:
        raise ValueError("not a system template — nothing to restore")
    row.body = row.system_body or ""
    row.css = row.system_css or ""
    row.version = (row.version or 1) + 1
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


# ── 渲染 ──────────────────────────────────────────────────────────────────


@dataclass
class RenderResult:
    html: str
    doc: dict = field(default_factory=dict)
    template_id: UUID | None = None
    template_version: int = 1
    filename: str = "document.pdf"


_BASE_CSS = """
/* 内置基础版式 — 租户 css 覆盖在它之后，可整体改写。 */
:root { --brand: #1A9B96; --ink: #1f2933; --muted: #6b7280; --rule: #d7dce1; }
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC",
               "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
               "Helvetica Neue", Arial, sans-serif;
  font-size: 10.5pt; color: var(--ink); line-height: 1.45;
}
/* 纵向弹性布局 —— 签署栏沉到页底，避免内容短时留下一大片空白 */
body { display: flex; flex-direction: column; min-height: 100%; }
@page { size: A4; }
.doc-head { display: flex; align-items: flex-start; justify-content: space-between;
            border-bottom: 2px solid var(--brand); padding-bottom: 12px; margin-bottom: 18px; }
.doc-brand { display: flex; gap: 12px; align-items: flex-start; max-width: 62%; }
.doc-logo { max-height: 46px; max-width: 150px; }
.doc-company-name { font-size: 13pt; font-weight: 700; margin: 0 0 3px; }
.doc-company-meta { font-size: 8.5pt; color: var(--muted); margin: 0; }
.doc-title-block { text-align: right; }
.doc-title { font-size: 15pt; font-weight: 700; margin: 0 0 4px; letter-spacing: .02em; }
.doc-no { font-size: 9pt; color: var(--muted); margin: 0; }
table { width: 100%; border-collapse: collapse; margin: 0 0 14px; }
th { text-align: left; font-size: 8.5pt; text-transform: uppercase; letter-spacing: .04em;
     color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--rule);
     padding: 5px 6px; background: #f7f9fa; }
td { padding: 5px 6px; border-bottom: 1px solid #eef1f4; font-size: 9.5pt; vertical-align: top; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.sect { font-size: 10pt; font-weight: 700; margin: 18px 0 8px; padding-bottom: 4px;
        border-bottom: 1px solid var(--rule); }
.grid-2 { display: flex; gap: 28px; margin-bottom: 16px; }
.grid-2 > div { flex: 1; }
.kv { display: grid; grid-template-columns: 40% 60%; gap: 3px 8px; font-size: 9.5pt; }
.kv dt { color: var(--muted); margin: 0; }
.kv dd { margin: 0; }
.total-row td { font-weight: 700; border-top: 2px solid var(--ink); border-bottom: none;
                font-size: 11pt; padding-top: 8px; }
.note { font-size: 8.5pt; color: var(--muted); margin-top: 14px; }
.sign { margin-top: auto; padding-top: 48px; display: flex; justify-content: space-between; gap: 40px; }
.sign > div { flex: 1; }
.sign-line { border-top: 1px solid var(--ink); margin-top: 52px; padding-top: 5px;
             font-size: 9pt; color: var(--muted); }
"""


def _fmt_money(v: Any) -> str:
    """金额 → 1,234.56；None/空 → 空串（模板不必写 if 分支）。"""
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_num(v: Any, dp: int = 2) -> str:
    """通用数字 → 千分位，控制小数位。"""
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):,.{dp}f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_pct(v: Any, dp: int = 2) -> str:
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):,.{dp}f}%"
    except (TypeError, ValueError):
        return str(v)


def _env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(
        undefined=StrictUndefined,   # 模板写错字段名要立刻暴露，而不是静默印空白
        # P0-4：**必须转义**。上下文里全是「租户/用户可编辑」的字段
        # （对手方名、备注、货名、地址…）—— 老代码 autoescape=False 意味着
        # 对手方名写成 `<img src=x onerror="fetch('/api/v1/settings/api-keys')">`
        # 就会在财务/管理员打开单据时执行（存储型 XSS → 会话接管）。
        # 模板**正文**是租户自己写的 HTML（模板作者即租户本人），不受影响；
        # 只有 {{ }} 插值被转义 —— 这正是我们要的行为。
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # 模板里金额一律走 money —— 千分位是正式单据的基本要求
    env.filters["money"] = _fmt_money
    env.filters["num"] = _fmt_num
    env.filters["pct"] = _fmt_pct
    return env


def render_document(
    db: Session,
    tenant_id: UUID,
    *,
    entity_type: str,
    entity_id: UUID | None = None,
    template_code: str = "default",
    locale: str = "en",
    extra: dict | None = None,
) -> RenderResult:
    """实体 → 模板 → 完整 HTML。不生成 PDF（那是 :func:`html_to_pdf` 的事）。"""
    from app.services.doc_contexts import as_sections, build_context

    spec = DOC_TYPES.get(entity_type)
    if spec is None:
        raise DocumentNotFound(f"unknown document type: {entity_type}")

    tpl = get_template(db, tenant_id, entity_type, code=template_code, locale=locale)
    if tpl is None:
        ensure_templates(db, tenant_id)
        tpl = get_template(db, tenant_id, entity_type, code=template_code, locale=locale)
    if tpl is None:
        raise DocumentNotFound(f"no template for {entity_type}")

    payload = build_context(db, tenant_id, entity_type, entity_id)
    payload.update(build_letterhead(db, tenant_id))
    payload["doc"] = {
        "type": entity_type,
        "title": spec.title_zh if locale.lower().startswith("zh") else spec.title_en,
        "title_en": spec.title_en,
        "title_zh": spec.title_zh,
        "no": payload.get("no") or payload.get("doc_no") or "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entity_id": str(entity_id) if entity_id else None,
    }
    if extra:
        payload.update(extra)
    payload = as_sections(payload)

    try:
        html = _env().from_string(tpl.body).render(**payload)
    except TemplateError as exc:
        raise ValueError(f"template render failed: {exc}") from exc

    css = _brand_css(payload) + _BASE_CSS + "\n" + (tpl.css or "")
    if not re.search(r"<style[^>]*>", html, re.I):
        html = f"<style>{css}</style>\n{html}"
    elif tpl.css:
        html = re.sub(r"</head>", f"<style>{css}</style>\n</head>", html, count=1, flags=re.I)

    fname = _safe_filename(payload.get("doc", {}).get("title") or entity_type,
                           payload.get("doc", {}).get("no"))
    return RenderResult(
        html=html,
        doc=payload.get("doc", {}),
        template_id=tpl.id,
        template_version=tpl.version,
        filename=fname,
    )


_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _brand_css(payload: dict) -> str:
    """把租户品牌色注入 :root —— 抬头分隔线、强调色随之统一。

    品牌色是租户可写的字符串，直接拼进 CSS 等于注入面；只放行 #rgb/#rrggbb。
    """
    company = payload.get("company") or {}
    color = (company or {}).get("brand_primary") or ""
    if not isinstance(color, str) or not _HEX_COLOR.match(color.strip()):
        return ""
    return f":root {{ --brand: {color.strip()}; }}\n"


def render_with(tpl: Any, payload: dict) -> str:
    """用一份**未落库**的模板（编辑器里的草稿）渲染完整 HTML —— 预览专用。

    :attr:`tpl` 只需要 ``body`` / ``css`` / ``entity_type`` 属性，不必是
    :class:`DocumentTemplate` 实例，方便前端把编辑中的草稿直接丢进来。
    """
    from app.services.doc_contexts import as_sections

    try:
        html = _env().from_string(tpl.body or "").render(**as_sections(payload))
    except TemplateError as exc:
        raise ValueError(f"template render failed: {exc}") from exc
    css = _brand_css(payload) + _BASE_CSS + "\n" + (tpl.css or "")
    if not re.search(r"<style[^>]*>", html, re.I):
        return f"<style>{css}</style>\n{html}"
    return re.sub(r"</head>", f"<style>{css}</style>\n</head>", html, count=1, flags=re.I)


# 模板可用变量速查（编辑器右栏提示，避免模板作者瞎猜字段名）
_VARIABLE_HINTS: dict[str, list[tuple[str, str]]] = {
    "_common": [
        ("company.legal_name / display_name / address / phone / email / tax_no", "公司抬头"),
        ("company.logo_data", "logo（已内联为 data URI，PDF 可显示）"),
        ("bank.bank_name / account_name / account_number / swift / iban / currency", "收款银行"),
        ("doc.title / doc.no / doc.generated_at", "单据标题、编号、生成时间"),
    ],
    "invoice": [
        ("counterparty.name / address / attention", "收票方 Bill-To"),
        ("header.issue_date / due_date / currency / payment_terms", "开票日、到期日、币种、付款条件"),
        ("lines[].description / qty / unit / rate / amount", "行项目"),
        ("totals.subtotal / tax / total / amount_paid / balance", "合计"),
    ],
    "laytime_statement": [
        ("vessel.name / imo", "船名 / IMO"),
        ("header.voyage_no / cargo / laycan / rate / demurrage_rate", "航次、货物、装卸率"),
        ("port_calls[].port / nor / laytime_start / laytime_end / laytime_used", "港口作业"),
        ("totals.total_time / total_used / demurrage / despatch", "合计时间与速遣/滞期"),
    ],
}


def variable_hints(entity_type: str) -> list[dict]:
    """模板编辑器的变量提示 —— 通用信头 + 该单据类型的专属字段。"""
    out = [{"name": n, "desc": d} for n, d in _VARIABLE_HINTS.get("_common", [])]
    for n, d in _VARIABLE_HINTS.get(entity_type, []):
        out.append({"name": n, "desc": d})
    return out


def _safe_filename(title: str, no: str | None) -> str:
    stem = re.sub(r"[^\w一-鿿-]+", "_", (title or "document").strip())[:60].strip("_")
    if no:
        tail = re.sub(r"[^\w一-鿿-]+", "_", str(no).strip())[:40].strip("_")
        if tail:
            stem = f"{stem}_{tail}"
    return f"{stem or 'document'}.pdf"


# ── PDF 引擎 ──────────────────────────────────────────────────────────────

_playwright_lock = threading.Lock()
_playwright_cm = None
_browser = None

# Playwright sync API 的 greenlet 绑定线程 —— 所有 PDF 渲染集中到这条专属线程，
# 浏览器单例也只在这里创建 / 关闭（见 html_to_pdf 的说明）。
_pdf_executor = None
_pdf_executor_lock = threading.Lock()


def _pdf_worker() -> ThreadPoolExecutor:
    global _pdf_executor
    with _pdf_executor_lock:
        if _pdf_executor is None:
            _pdf_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="marios-pdf")
        return _pdf_executor

_PDF_MARGIN = {"top": "20mm", "bottom": "18mm", "left": "16mm", "right": "16mm"}

_FOOTER = """
<style>
  .f {{ width:100%; padding:0 16mm; font-size:8px; color:#8a94a0;
        display:flex; justify-content:space-between;
        font-family:"Segoe UI","Microsoft YaHei","Noto Sans CJK SC",sans-serif; }}
</style>
<div class="f"><span></span><span>Page <span class="pageNumber"></span> / <span class="totalPages"></span></span></div>
"""


_chromium_probe_cache: tuple[bool, float] | None = None


def _chromium_installed() -> bool:
    """Chromium 二进制是否真的在盘上。

    P1-10：旧实现只 ``import playwright.sync_api`` —— **Python 包在，浏览器没下**
    时它照样返回 True，界面显示「PDF 可用」，用户一点导出就炸。镜像里如果
    没跑 ``playwright install chromium`` 就是这个状态。

    这里做一次真实的文件系统探测（``INSTALLATION_COMPLETE`` 标记 / chrome 可执行
    文件），结果缓存 60 秒 —— 探测要进文件系统，而 ``/docs/capabilities`` 会被
    前端频繁调用。
    """
    global _chromium_probe_cache
    now = time.time()
    if _chromium_probe_cache and now - _chromium_probe_cache[1] < 60:
        return _chromium_probe_cache[0]

    result = False
    try:
        import playwright.sync_api  # noqa: F401

        roots: list[Path] = []
        env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if env:
            roots.append(Path(env))
        home = Path.home()
        roots.extend(
            [
                home / ".cache" / "ms-playwright",
                home / "Library" / "Caches" / "ms-playwright",
                home / "AppData" / "Local" / "ms-playwright",
                Path("/ms-playwright"),
            ]
        )
        for root in roots:
            try:
                if not root.is_dir():
                    continue
                for entry in root.iterdir():
                    if not entry.is_dir() or not entry.name.startswith("chromium"):
                        continue
                    # playwright 装完会在浏览器目录里放 INSTALLATION_COMPLETE
                    if (entry / "INSTALLATION_COMPLETE").exists():
                        result = True
                        break
                    # 兜底：目录里有 chrome 可执行文件
                    for exe in entry.rglob("chrome*"):
                        if exe.is_file() and exe.suffix in ("", ".exe"):
                            result = True
                            break
                    if result:
                        break
            except Exception:  # noqa: BLE001 - 探测失败按「没有」算
                continue
            if result:
                break
    except Exception:  # noqa: BLE001
        result = False

    _chromium_probe_cache = (result, now)
    return result


def pdf_available() -> bool:
    """PDF 渲染是否**真的**可用（Python 包 + Chromium 二进制都要在）。"""
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return _chromium_installed()


def _get_browser():
    """常驻 Chromium —— 逐次启动会让导出慢到不可用。"""
    global _browser, _playwright_cm
    if _browser is not None:
        try:
            _browser.is_connected()  # 句柄可能已被外部关闭
            return _browser
        except Exception:  # noqa: BLE001
            _browser = None
    from playwright.sync_api import sync_playwright

    _playwright_cm = sync_playwright()
    pw = _playwright_cm.start()
    _browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    return _browser


def html_to_pdf(html: str, *, wait_ms: int = 150) -> bytes:
    """HTML → PDF 字节。引擎缺失/启动失败抛 :class:`PDFEngineUnavailable`。

    Playwright 的 **sync API 绑定 greenlet**：浏览器一旦在 A 线程启动，就只能在该线程
    里调用，否则抛 ``Cannot switch to a different thread``。FastAPI 的同步路由跑在
    anyio 线程池里、线程会轮换，所以模块级浏览器单例直接跨线程复用必然出错
    （实测并发导出 PDF 约一半 503）。

    因此把渲染全部交给一个**专属单线程**：浏览器也只在该线程里创建 / 关闭，
    跨线程问题从根上消失，浏览器单例的性能收益保留。
    """
    try:
        from playwright.sync_api import Error as PWError  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise PDFEngineUnavailable(f"playwright not installed: {exc}") from exc

    future = _pdf_worker().submit(_render_pdf, html, wait_ms)
    try:
        return future.result()
    except PDFEngineUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — 工作线程异常退出等
        raise PDFEngineUnavailable(f"pdf engine unavailable: {exc}") from exc


def _render_pdf(html: str, wait_ms: int) -> bytes:
    """在 PDF 专属线程里执行渲染（Playwright sync API 只能在同一线程内使用）。"""
    from playwright.sync_api import Error as PWError

    with _playwright_lock:
        try:
            browser = _get_browser()
            page = browser.new_page()
            try:
                # P0-4/P2：**渲染时禁止加载远程子资源**。单据正文里如果
                # 出现 ``<img src="http://169.254.169.254/...">``，浏览器会
                # 替服务器去打内网（元数据地址 / Redis / Postgres）—— 这是
                # 借 PDF 渲染当 SSRF 跳板。只放行 ``data:`` / ``about:``。
                # （测试用的假 page 没有 route → 跳过，不影响真浏览器。）
                _install_resource_guard(page)
                page.set_content(html, wait_until="load")
                if wait_ms:
                    page.wait_for_timeout(wait_ms)  # 让 data: URI 图片解码完
                return page.pdf(
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=True,
                    margin=_PDF_MARGIN,
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=_FOOTER,
                )
            finally:
                page.close()
        except PDFEngineUnavailable:
            raise
        except PWError as exc:
            _reset_browser()
            raise PDFEngineUnavailable(f"chromium render failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 — 启动失败等
            _reset_browser()
            raise PDFEngineUnavailable(f"pdf engine unavailable: {exc}") from exc


def _block_remote_resources(route, request) -> None:  # noqa: ANN001 — playwright 回调
    """拦截 PDF 渲染里的**远程**子资源请求（只放行 data: / about: / blob:）。"""
    url = (getattr(request, "url", "") or "").strip().lower()
    if url.startswith(("data:", "about:", "blob:")):
        route.continue_()
        return
    route.abort()


def _install_resource_guard(page) -> None:  # noqa: ANN001 — playwright page
    """给渲染页装上「只放行本地资源」的拦截器（测试假 page 无 route 时跳过）。"""
    route = getattr(page, "route", None)
    if route is None:
        return
    route("**/*", _block_remote_resources)


def _reset_browser() -> None:
    global _browser, _playwright_cm
    try:
        if _browser is not None:
            _browser.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        if _playwright_cm is not None:
            _playwright_cm.stop()
    except Exception:  # noqa: BLE001
        pass
    _browser = None
    _playwright_cm = None


# ── 出档 ──────────────────────────────────────────────────────────────────


def record_render(
    db: Session,
    tenant_id: UUID,
    *,
    entity_type: str,
    entity_id: UUID | None,
    result: RenderResult,
    content: bytes,
    fmt: str,
    content_type: str,
    user_id: UUID | None = None,
    snapshot: dict | None = None,
) -> DocumentRender:
    """落盘 PDF 并留痕。PDF 字节不进库。"""
    render_id = uuid.uuid4()
    dest_dir = UPLOAD_ROOT / "documents" / str(tenant_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = "pdf" if fmt == "pdf" else "html"
    dest = dest_dir / f"{render_id}.{ext}"
    dest.write_bytes(content)

    row = DocumentRender(
        id=render_id,
        tenant_id=tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        template_id=result.template_id,
        template_version=result.template_version,
        doc_no=result.doc.get("no") or None,
        title=result.doc.get("title"),
        format=fmt,
        filename=f"{Path(result.filename).stem}.{ext}",
        content_type=content_type,
        size_bytes=len(content),
        # 相对 UPLOAD_ROOT —— 绝对路径在换机/容器部署后失效
        storage_path=f"documents/{tenant_id}/{render_id}.{ext}",
        snapshot=snapshot or {},
        rendered_by=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def read_render(db: Session, tenant_id: UUID, render_id: UUID) -> tuple[bytes, str, str] | None:
    """读回落盘的出档文件 → (bytes, content_type, filename)。"""
    row = db.get(DocumentRender, render_id)
    if not row or row.tenant_id != tenant_id or not row.storage_path:
        return None
    dest = (UPLOAD_ROOT / row.storage_path).resolve()
    try:
        dest.relative_to(UPLOAD_ROOT.resolve())
    except ValueError:
        log.error("doc_engine: path escape blocked for %s", row.storage_path)
        return None
    try:
        return dest.read_bytes(), row.content_type, row.filename
    except OSError:
        return None


def list_renders(
    db: Session, tenant_id: UUID, *, entity_type: str | None = None, entity_id: UUID | None = None
) -> list[dict]:
    q = select(DocumentRender).where(DocumentRender.tenant_id == tenant_id)
    if entity_type:
        q = q.where(DocumentRender.entity_type == entity_type)
    if entity_id:
        q = q.where(DocumentRender.entity_id == entity_id)
    rows = db.scalars(q.order_by(DocumentRender.created_at.desc()).limit(200)).all()
    return [
        {
            "id": str(r.id),
            "entity_type": r.entity_type,
            "entity_id": str(r.entity_id) if r.entity_id else None,
            "doc_no": r.doc_no,
            "title": r.title,
            "format": r.format,
            "filename": r.filename,
            "size_bytes": r.size_bytes,
            "template_version": r.template_version,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
