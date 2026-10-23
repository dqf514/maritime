"""单据模板管理与 PDF 出档。

- 模板管理（租户可编辑 HTML/CSS，可恢复系统默认，可实时预览）
- 出单：实体 → 模板 → HTML / PDF（PDF 缺引擎时自动回落 HTML）
- 出档留痕：每次出单记录一行，可回溯下载

产品语义：模板是租户资产；PDF 是对外正式件，因此信头（公司/银行/logo）
统一由 :mod:`app.services.doc_engine` 注入，模板作者只写版式。
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, get_current_auth, require_module
from app.services import doc_engine

# 前缀不能用 /docs —— 与 FastAPI 自带的 Swagger UI 路径冲突
router = APIRouter(prefix="/documents", tags=["Documents & templates"])

# 模板编辑属于管理动作 —— 只给能改配置的角色；出单放开到业务角色
_EDIT_ROLES = ("tenant_admin", "finance", "chartering", "management")


def require_roles(*codes: str):
    def _dep(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if not any(c in auth.roles for c in codes):
            raise HTTPException(status_code=403, detail={"code": "ROLE_REQUIRED", "roles": list(codes)})
        return auth

    return _dep


class TemplateUpdateIn(BaseModel):
    body: str | None = Field(default=None, max_length=400_000)
    css: str | None = Field(default=None, max_length=200_000)
    name: str | None = Field(default=None, max_length=128)
    enabled: bool | None = None
    is_default: bool | None = None


class PreviewIn(BaseModel):
    """预览用实体 —— 留空即用内置示例数据。

    ``body`` / ``css`` 传了就用**编辑器里的草稿**渲染，不落库 —— 编辑器要的
    是边改边看；沙箱仍然生效，草稿与落库模板同等对待。
    """

    entity_id: UUID | None = None
    sample: bool = True
    body: str | None = Field(default=None, max_length=400_000)
    css: str | None = Field(default=None, max_length=200_000)


def _spec_or_404(entity_type: str) -> doc_engine.DocType:
    spec = doc_engine.DOC_TYPES.get(entity_type)
    if spec is None:
        raise HTTPException(404, detail={"code": "UNKNOWN_DOC_TYPE", "entity_type": entity_type})
    return spec


@router.get("/letterhead")
def get_letterhead(
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """公司抬头（打印/PDF 用）。

    与 ``/admin/company-profile`` 的区别：那个是**管理端编辑**接口（tenant_admin
    only），这个是**业务端只读**接口 —— 财务/租船角色打开打印页就要拿到信头，
    不该为了读公司名而去要管理员权限（此前 PrintDoc 读的是 /masterdata/companies，
    那张表没有地址/电话/logo，所以打印出来的信头一直是空的）。
    """
    return doc_engine.build_letterhead(db, auth.tenant_id)


# ── 模板目录 ──────────────────────────────────────────────────────────────


@router.get("/templates")
def list_templates(
    entity_type: str | None = Query(default=None),
    auth: AuthContext = Depends(require_roles(*_EDIT_ROLES)),
    db: Session = Depends(get_db),
):
    doc_engine.ensure_templates(db, auth.tenant_id)
    rows = doc_engine.list_templates(db, auth.tenant_id, entity_type)
    return {
        "types": [
            {
                "code": d.code,
                "title_en": d.title_en,
                "title_zh": d.title_zh,
                "has_lines": d.has_lines,
                "module": d.module,
            }
            for d in doc_engine.DOC_TYPES.values()
        ],
        "templates": rows,
        "pdf_available": doc_engine.pdf_available(),
    }


@router.get("/templates/{template_id}")
def get_template(
    template_id: UUID,
    auth: AuthContext = Depends(require_roles(*_EDIT_ROLES)),
    db: Session = Depends(get_db),
):
    from app.models_doc import DocumentTemplate

    row = db.get(DocumentTemplate, template_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, detail={"code": "TEMPLATE_NOT_FOUND"})
    return {
        "id": str(row.id),
        "entity_type": row.entity_type,
        "code": row.code,
        "name": row.name,
        "format": row.format,
        "locale": row.locale,
        "is_default": row.is_default,
        "is_system": row.is_system,
        "version": row.version,
        "enabled": row.enabled,
        "body": row.body,
        "css": row.css,
        "system_body": row.system_body,
        "system_css": row.system_css,
        "variables": doc_engine.variable_hints(row.entity_type),
    }


@router.put("/templates/{template_id}")
def put_template(
    template_id: UUID,
    body: TemplateUpdateIn,
    auth: AuthContext = Depends(require_roles(*_EDIT_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        row = doc_engine.save_template(
            db, auth.tenant_id, template_id,
            body=body.body, css=body.css, name=body.name,
            enabled=body.enabled, is_default=body.is_default,
            user_id=auth.user_id,
        )
    except doc_engine.DocumentNotFound:
        raise HTTPException(404, detail={"code": "TEMPLATE_NOT_FOUND"}) from None
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "INVALID_TEMPLATE", "message": str(exc)}) from None
    return {"ok": True, "version": row.version}


@router.post("/templates/{template_id}/reset")
def reset_template(
    template_id: UUID,
    auth: AuthContext = Depends(require_roles(*_EDIT_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        row = doc_engine.reset_template(db, auth.tenant_id, template_id)
    except doc_engine.DocumentNotFound:
        raise HTTPException(404, detail={"code": "TEMPLATE_NOT_FOUND"}) from None
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "NOT_SYSTEM_TEMPLATE", "message": str(exc)}) from None
    return {"ok": True, "version": row.version, "body": row.body, "css": row.css}


# ── 预览 ──────────────────────────────────────────────────────────────────


@router.post("/templates/{template_id}/preview")
def preview_template(
    template_id: UUID,
    body: PreviewIn,
    auth: AuthContext = Depends(require_roles(*_EDIT_ROLES)),
    db: Session = Depends(get_db),
):
    """预览当前编辑中的 HTML —— 前端在 iframe 里直接渲染，无需落库。"""
    from types import SimpleNamespace

    from app.models_doc import DocumentTemplate
    from app.services.doc_contexts import build_context, sample_context

    row = db.get(DocumentTemplate, template_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, detail={"code": "TEMPLATE_NOT_FOUND"})
    _spec_or_404(row.entity_type)

    payload = (
        build_context(db, auth.tenant_id, row.entity_type, body.entity_id)
        if body.entity_id
        else sample_context(row.entity_type)
    ) or sample_context(row.entity_type)
    payload.update(doc_engine.build_letterhead(db, auth.tenant_id))
    payload["doc"] = {
        "type": row.entity_type,
        "title": row.name,
        "title_en": doc_engine.DOC_TYPES[row.entity_type].title_en,
        "title_zh": doc_engine.DOC_TYPES[row.entity_type].title_zh,
        "no": payload.get("no") or payload.get("doc_no") or "PREVIEW-001",
        "generated_at": payload.get("generated_at") or "",
        "entity_id": str(body.entity_id) if body.entity_id else None,
    }
    # 草稿优先 —— 编辑器边改边看；没传草稿才用已落库的版本
    draft = SimpleNamespace(
        body=row.body if body.body is None else body.body,
        css=row.css if body.css is None else body.css,
        entity_type=row.entity_type,
    )
    return {"html": doc_engine.render_with(draft, payload), "sample": body.entity_id is None}


@router.post("/templates/{template_id}/preview/pdf")
def preview_template_pdf(
    template_id: UUID,
    body: PreviewIn,
    auth: AuthContext = Depends(require_roles(*_EDIT_ROLES)),
    db: Session = Depends(get_db),
):
    """预览 PDF —— 引擎缺失时 503，前端提示回落 HTML。"""
    html = preview_template(template_id, body, auth=auth, db=db)["html"]
    try:
        pdf = doc_engine.html_to_pdf(html)
    except doc_engine.PDFEngineUnavailable as exc:
        raise HTTPException(
            503,
            detail={"code": "PDF_ENGINE_UNAVAILABLE", "message": str(exc)},
        ) from None
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="preview.pdf"'},
    )


# ── 出单 ──────────────────────────────────────────────────────────────────


@router.get("/render/{entity_type}/{entity_id}")
def render_document(
    entity_type: str,
    entity_id: UUID,
    format: Literal["html", "pdf"] = Query(default="pdf"),
    template_code: str = Query(default="default", max_length=64),
    locale: str = Query(default="en", max_length=16),
    archive: bool = Query(default=True),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """实体 → 正式单据。``format=pdf`` 缺引擎时自动回落 HTML（200 + text/html）。"""
    spec = _spec_or_404(entity_type)
    try:
        result = doc_engine.render_document(
            db, auth.tenant_id,
            entity_type=entity_type, entity_id=entity_id,
            template_code=template_code, locale=locale,
        )
    except doc_engine.DocumentNotFound as exc:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": str(exc)}) from None
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "TEMPLATE_RENDER_FAILED", "message": str(exc)}) from None

    wanted_pdf = format == "pdf"
    if wanted_pdf:
        try:
            pdf = doc_engine.html_to_pdf(result.html)
        except doc_engine.PDFEngineUnavailable:
            pdf = None
    else:
        pdf = None

    if pdf is not None:
        if archive:
            doc_engine.record_render(
                db, auth.tenant_id,
                entity_type=entity_type, entity_id=entity_id,
                result=result, content=pdf, fmt="pdf",
                content_type="application/pdf", user_id=auth.user_id,
                snapshot=doc_engine.build_letterhead(db, auth.tenant_id),
            )
        return Response(content=pdf, media_type="application/pdf", headers={
            "Content-Disposition": f'inline; filename="{result.filename}"',
        })

    if archive:
        doc_engine.record_render(
            db, auth.tenant_id,
            entity_type=entity_type, entity_id=entity_id,
            result=result, content=result.html.encode("utf-8"), fmt="html",
            content_type="text/html; charset=utf-8", user_id=auth.user_id,
            snapshot=doc_engine.build_letterhead(db, auth.tenant_id),
        )
    return HTMLResponse(
        content=result.html,
        headers={
            "Content-Disposition": f'inline; filename="{spec.code}_{entity_id}.html"',
            "X-Doc-Engine": "html-fallback",
        },
    )


# ── 外发 ──────────────────────────────────────────────────────────────────


class SendDocumentIn(BaseModel):
    entity_type: str
    entity_id: UUID
    to: str = Field(max_length=320)
    subject: str | None = Field(default=None, max_length=400)
    body: str | None = Field(default=None, max_length=20_000)
    template_code: str = Field(default="default", max_length=64)
    locale: str = Field(default="en", max_length=16)


@router.post("/send")
def send_document(
    body: SendDocumentIn,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """渲染成 PDF 并作为附件发出 —— 走平台邮件通道（Graph 优先，SMTP 兜底）。

    投递是软失败：邮件发不出去仍返回 200 并带 ``delivery.status``，
    不让"外发单据"把出单动作一起拖垮。
    """
    import base64

    spec = _spec_or_404(body.entity_type)
    try:
        result = doc_engine.render_document(
            db, auth.tenant_id,
            entity_type=body.entity_type, entity_id=body.entity_id,
            template_code=body.template_code, locale=body.locale,
        )
    except doc_engine.DocumentNotFound as exc:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": str(exc)}) from None
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "TEMPLATE_RENDER_FAILED", "message": str(exc)}) from None

    try:
        pdf = doc_engine.html_to_pdf(result.html)
    except doc_engine.PDFEngineUnavailable:
        raise HTTPException(
            503,
            detail={"code": "PDF_ENGINE_UNAVAILABLE",
                    "message": "PDF engine unavailable — install Chromium via `python -m playwright install chromium`"},
        ) from None

    doc_engine.record_render(
        db, auth.tenant_id,
        entity_type=body.entity_type, entity_id=body.entity_id,
        result=result, content=pdf, fmt="pdf",
        content_type="application/pdf", user_id=auth.user_id,
        snapshot=doc_engine.build_letterhead(db, auth.tenant_id),
    )

    subject = body.subject or f"{spec.title_en} {result.doc.get('no') or ''}".strip()
    text = body.body or (
        f"Please find attached the {spec.title_en.lower()} "
        f"{result.doc.get('no') or ''}.\n\nKind regards,"
    )
    from app.services import identity

    log = identity.send_mail(
        db,
        to_email=body.to,
        subject=subject,
        body=text,
        purpose=f"document.{body.entity_type}",
        tenant_id=auth.tenant_id,
        meta={"entity_type": body.entity_type, "entity_id": str(body.entity_id)},
        attachments=[{
            "filename": result.filename,
            "content_type": "application/pdf",
            "content": pdf,
        }],
    )
    return {
        "ok": True,
        "filename": result.filename,
        "size_bytes": len(pdf),
        "to": body.to,
        "subject": subject,
        "delivery": {
            "status": log.status,
            "channel": log.channel,
            "log_id": str(log.id),
        },
    }


# ── 出档 ──────────────────────────────────────────────────────────────────


@router.get("/renders")
def list_renders(
    entity_type: str | None = Query(default=None),
    entity_id: UUID | None = Query(default=None),
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    return {"items": doc_engine.list_renders(
        db, auth.tenant_id, entity_type=entity_type, entity_id=entity_id
    )}


@router.get("/renders/{render_id}")
def download_render(
    render_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    got = doc_engine.read_render(db, auth.tenant_id, render_id)
    if got is None:
        raise HTTPException(404, detail={"code": "RENDER_NOT_FOUND"})
    content, content_type, filename = got
    return Response(content=content, media_type=content_type, headers={
        "Content-Disposition": f'inline; filename="{filename}"',
    })
