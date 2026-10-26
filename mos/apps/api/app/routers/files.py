"""File uploads with version management (DNV ShipManager-style).

Ship certificates live under uploads/certificates/{tenant_id}/{cert_id}/; generic
entity attachments (charter/voyage/claim/invoice/PDA/bunker/laytime/estimate)
live under uploads/attachments/... (services/files_store.py). Both are served
only through the authenticated download endpoint — never statically.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.responses import FileResponse

from app.db import get_db
from app.models_ship import ShipCertificate
from app.models_wave1 import Attachment
from app.security import (
    AuthContext,
    get_current_auth,
    read_roles_for_module,
    require_module,
    roles_for_module,
    tenant_has_module,
    tenant_role_grants,
)
from app.services.audit import audit
from app.services.upload_policy import get_upload_policy

router = APIRouter(tags=["Files"])

# Domain-allowed certificate types (raster/PDF only). The platform upload policy
# (document kind) is the outer ceiling — an extension must be allowed by BOTH.
ALLOWED_EXTS = {".pdf": "pdf", ".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp"}

_UPLOAD_ROOT = Path(__file__).resolve().parent.parent.parent / "uploads" / "certificates"

#: 通用附件可挂靠的实体类型 → (模块码, SQLAlchemy model)。许可轴按模块码走
#: tenant_has_module；角色轴镜像 require_module_role / require_module_read 语义
#: （写不含 viewer、读含 viewer；Role.permissions 自定义授权也生效）。
ENTITY_ATTACHMENT_TYPES: dict[str, tuple[str, type]] = {}


def _register_entity_types() -> None:
    if ENTITY_ATTACHMENT_TYPES:
        return
    from app.models_domain import (
        BunkerOrder,
        Charter,
        Claim,
        Estimate,
        Invoice,
        LaytimeCalc,
        PortCall,
        PortDisbursement,
        Voyage,
    )

    ENTITY_ATTACHMENT_TYPES.update(
        {
            "charter": ("chartering", Charter),
            "estimate": ("estimate", Estimate),
            "voyage": ("operations", Voyage),
            "port_call": ("operations", PortCall),
            "port_disbursement": ("operations", PortDisbursement),
            "bunker_order": ("bunker", BunkerOrder),
            "claim": ("claims", Claim),
            "invoice": ("finance", Invoice),
            "laytime": ("laytime", LaytimeCalc),
        }
    )


def _assert_entity_attachment_access(
    db: Session, auth: AuthContext, entity_type: str, *, write: bool
) -> type:
    """动态模块闸门 —— 模块码取决于路径参数，无法用 require_module_role 工厂。

    语义与 security.require_module_role（写）/ require_module_read（读）一致：
    许可轴 dev unlock 可旁路；角色轴永不旁路，viewer 只读。
    """
    _register_entity_types()
    entry = ENTITY_ATTACHMENT_TYPES.get(entity_type)
    if entry is None:
        raise HTTPException(422, detail={"code": "UNKNOWN_ENTITY_TYPE", "entity_type": entity_type})
    module_code, model = entry
    if not tenant_has_module(db, auth.tenant_id, module_code):
        raise HTTPException(403, detail={"code": "MODULE_NOT_LICENSED", "module": module_code})
    allowed = (roles_for_module(module_code) if write else read_roles_for_module(module_code))
    if not any(r in allowed for r in auth.roles):
        grants = tenant_role_grants(db, auth.tenant_id)
        allowed = set(allowed) | grants.get(module_code, set())
        if auth.roles and set(auth.roles) & grants.get("*", set()):
            allowed |= set(auth.roles)
    if not any(r in allowed for r in auth.roles):
        raise HTTPException(
            403, detail={"code": "ROLE_REQUIRED", "module": module_code, "roles": sorted(allowed)}
        )
    return model


class AttachmentOut(BaseModel):
    id: UUID
    entity_type: str
    entity_id: UUID
    version_no: int
    is_current: bool
    file_name: str
    mime_type: str | None
    size: int | None
    note: str | None
    uploaded_by: UUID | None
    created_at: str | None
    download_url: str


def _sniff_cert_file(raw: bytes) -> str | None:
    if raw.startswith(b"%PDF"):
        return "pdf"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


def _safe_filename(name: str) -> str:
    base = Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base) or "file"


def _attachment_out(row: Attachment) -> AttachmentOut:
    return AttachmentOut(
        id=row.id,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        version_no=row.version_no or 1,
        is_current=bool(row.is_current),
        file_name=row.file_name,
        mime_type=row.mime_type,
        size=row.size,
        note=row.note,
        uploaded_by=row.uploaded_by,
        created_at=row.created_at.isoformat() if row.created_at else None,
        download_url=f"/api/v1/files/{row.id}/download",
    )


def _cert_or_404(db: Session, tenant_id: UUID, cert_id: UUID) -> ShipCertificate:
    cert = db.get(ShipCertificate, cert_id)
    if not cert or cert.tenant_id != tenant_id:
        raise HTTPException(404, "Certificate not found")
    return cert


def _attachment_or_404(db: Session, tenant_id: UUID, attachment_id: UUID) -> Attachment:
    row = db.get(Attachment, attachment_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(404, "File not found")
    return row


def _entity_attachments(db: Session, tenant_id: UUID, entity_type: str, entity_id: UUID) -> list[Attachment]:
    return db.scalars(
        select(Attachment)
        .where(
            Attachment.tenant_id == tenant_id,
            Attachment.entity_type == entity_type,
            Attachment.entity_id == entity_id,
        )
        .order_by(Attachment.version_no.desc())
    ).all()


def _cert_attachments(db: Session, tenant_id: UUID, cert_id: UUID) -> list[Attachment]:
    return _entity_attachments(db, tenant_id, "ship_certificate", cert_id)


def _sniff_document(raw: bytes) -> str | None:
    """通用附件内容嗅探 —— 平台 document 策略允许的类型里，可校验魔数的都校验。"""
    if raw.startswith(b"%PDF"):
        return "pdf"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if len(raw) >= 4 and raw[:2] == b"PK":
        return "xlsx"  # OOXML zip container
    return None  # csv / txt —— 无可靠魔数，交给扩展名 + 策略


_EXT_TO_SNIFF = {".pdf": "pdf", ".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp", ".xlsx": "xlsx", ".xlsm": "xlsx"}


def _validated_upload(raw: bytes, filename: str | None, policy: dict) -> str:
    """校验上传字节：非空 / 大小 / 扩展名（平台策略）/ 魔数（可校验的类型）。"""
    if not raw:
        raise HTTPException(400, detail={"code": "EMPTY_FILE"})
    if len(raw) > policy["max_bytes"]:
        raise HTTPException(400, detail={"code": "FILE_TOO_LARGE", "max_bytes": policy["max_bytes"]})
    ext = Path((filename or "file").lower()).suffix.lower()
    if ext not in set(policy["exts"]):
        raise HTTPException(400, detail={"code": "UNSUPPORTED_TYPE", "ext": ext})
    expected = _EXT_TO_SNIFF.get(ext)
    if expected is not None and _sniff_document(raw) != expected:
        raise HTTPException(
            400, detail={"code": "INVALID_CONTENT", "message": "File content does not match an allowed type"}
        )
    return ext


async def _store_upload(
    db: Session,
    auth: AuthContext,
    entity_type: str,
    entity_id: UUID,
    file: UploadFile,
    note: str | None,
    *,
    allowed_exts: dict[str, str] | None = None,
    audit_action: str = "attachment.upload",
) -> Attachment:
    """校验 → 版本号 +1 → 落盘 → 旧版本置非当前 → Attachment 行 + 审计。"""
    raw = await file.read()
    policy = get_upload_policy(db, "document")
    if allowed_exts is not None:
        # 证书路径：扩展名必须同时过领域规则（raster/PDF）和平台策略
        ext = Path((file.filename or "file").lower()).suffix.lower()
        if ext not in allowed_exts:
            raise HTTPException(400, detail={"code": "UNSUPPORTED_TYPE", "ext": ext})
        if not raw:
            raise HTTPException(400, detail={"code": "EMPTY_FILE"})
        if len(raw) > policy["max_bytes"]:
            raise HTTPException(400, detail={"code": "FILE_TOO_LARGE", "max_bytes": policy["max_bytes"]})
        if ext not in set(policy["exts"]):
            raise HTTPException(400, detail={"code": "UNSUPPORTED_TYPE", "ext": ext})
        if _sniff_cert_file(raw) != allowed_exts[ext]:
            raise HTTPException(
                400, detail={"code": "INVALID_CONTENT", "message": "File content does not match an allowed type"}
            )
    else:
        _validated_upload(raw, file.filename, policy)

    next_version = (
        db.scalar(
            select(func.max(Attachment.version_no)).where(
                Attachment.tenant_id == auth.tenant_id,
                Attachment.entity_type == entity_type,
                Attachment.entity_id == entity_id,
            )
        )
        or 0
    ) + 1
    if entity_type == "ship_certificate":
        dest_dir = _UPLOAD_ROOT / str(auth.tenant_id) / str(entity_id)
    else:
        from app.services.files_store import entity_dir

        dest_dir = entity_dir(auth.tenant_id, entity_type, entity_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"v{next_version}_{_safe_filename(file.filename or 'file')}"
    dest.write_bytes(raw)
    for prev in _entity_attachments(db, auth.tenant_id, entity_type, entity_id):
        prev.is_current = False
    row = Attachment(
        tenant_id=auth.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        file_name=file.filename or dest.name,
        file_path=str(dest),
        mime_type=file.content_type,
        size=len(raw),
        version_no=next_version,
        is_current=True,
        note=note,
        uploaded_by=auth.user_id,
    )
    db.add(row)
    audit(
        db,
        action=audit_action,
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        detail={"attachment_id": str(row.id), "file_name": row.file_name, "version_no": next_version},
    )
    db.commit()
    db.refresh(row)
    return row


@router.post("/ship/certificates/{cert_id}/files", response_model=AttachmentOut)
async def upload_certificate_file(
    cert_id: UUID,
    file: UploadFile = File(...),
    note: str | None = Form(default=None),
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    cert = _cert_or_404(db, auth.tenant_id, cert_id)
    row = await _store_upload(
        db,
        auth,
        "ship_certificate",
        cert.id,
        file,
        note,
        allowed_exts=ALLOWED_EXTS,
        audit_action="ship.certificate.file_upload",
    )
    return _attachment_out(row)


@router.get("/ship/certificates/{cert_id}/files", response_model=list[AttachmentOut])
def list_certificate_files(
    cert_id: UUID,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    cert = _cert_or_404(db, auth.tenant_id, cert_id)
    return [_attachment_out(r) for r in _cert_attachments(db, auth.tenant_id, cert.id)]


# ── 通用实体附件（行业实践：单证依据挂业务对象）────────────────────────────
# 许可+角色双闸门按路径里的 entity_type 动态取模块码（见 _assert_entity_attachment_access）。


@router.post("/entities/{entity_type}/{entity_id}/files", response_model=AttachmentOut)
async def upload_entity_file(
    entity_type: str,
    entity_id: UUID,
    file: UploadFile = File(...),
    note: str | None = Form(default=None),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    model = _assert_entity_attachment_access(db, auth, entity_type, write=True)
    entity = db.get(model, entity_id)
    if entity is None or getattr(entity, "tenant_id", None) != auth.tenant_id:
        raise HTTPException(404, "Entity not found")
    row = await _store_upload(db, auth, entity_type, entity_id, file, note)
    return _attachment_out(row)


@router.get("/entities/{entity_type}/{entity_id}/files", response_model=list[AttachmentOut])
def list_entity_files(
    entity_type: str,
    entity_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    model = _assert_entity_attachment_access(db, auth, entity_type, write=False)
    entity = db.get(model, entity_id)
    if entity is None or getattr(entity, "tenant_id", None) != auth.tenant_id:
        raise HTTPException(404, "Entity not found")
    return [_attachment_out(r) for r in _entity_attachments(db, auth.tenant_id, entity_type, entity_id)]


@router.get("/files/{attachment_id}/download")
def download_file(
    attachment_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    row = _attachment_or_404(db, auth.tenant_id, attachment_id)
    path = Path(row.file_path)
    if not path.is_file():
        raise HTTPException(404, "File content missing")
    return FileResponse(path, filename=row.file_name, media_type=row.mime_type or "application/octet-stream")


@router.post("/files/{attachment_id}/current", response_model=AttachmentOut)
def set_current_file(
    attachment_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    row = _attachment_or_404(db, auth.tenant_id, attachment_id)
    if row.entity_type == "ship_certificate":
        if not tenant_has_module(db, auth.tenant_id, "ship_mgmt"):
            raise HTTPException(403, detail={"code": "MODULE_NOT_LICENSED", "module": "ship_mgmt"})
    else:
        _assert_entity_attachment_access(db, auth, row.entity_type, write=True)
    for other in db.scalars(
        select(Attachment).where(
            Attachment.tenant_id == auth.tenant_id,
            Attachment.entity_type == row.entity_type,
            Attachment.entity_id == row.entity_id,
        )
    ).all():
        other.is_current = other.id == row.id
    audit(
        db,
        action="attachment.set_current",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        detail={"attachment_id": str(row.id), "version_no": row.version_no},
    )
    db.commit()
    db.refresh(row)
    return _attachment_out(row)


@router.delete("/files/{attachment_id}")
def delete_file(
    attachment_id: UUID,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    row = _attachment_or_404(db, auth.tenant_id, attachment_id)
    if row.entity_type == "ship_certificate":
        if not tenant_has_module(db, auth.tenant_id, "ship_mgmt"):
            raise HTTPException(403, detail={"code": "MODULE_NOT_LICENSED", "module": "ship_mgmt"})
    else:
        _assert_entity_attachment_access(db, auth, row.entity_type, write=True)
    audit(
        db,
        action="attachment.delete",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        detail={"attachment_id": str(row.id), "file_name": row.file_name},
    )
    Path(row.file_path).unlink(missing_ok=True)
    db.delete(row)
    db.commit()
    return {"ok": True}
