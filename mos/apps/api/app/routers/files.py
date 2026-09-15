"""Certificate file uploads with version management (DNV ShipManager-style).

Files live under uploads/certificates/{tenant_id}/{cert_id}/v{n}_{name} and are
served only through the authenticated download endpoint — never statically.
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
from app.security import AuthContext, get_current_auth, require_module
from app.services.audit import audit

router = APIRouter(tags=["Files"])

MAX_CERT_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_EXTS = {".pdf": "pdf", ".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".webp": "webp"}

_UPLOAD_ROOT = Path(__file__).resolve().parent.parent.parent / "uploads" / "certificates"


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


def _cert_attachments(db: Session, tenant_id: UUID, cert_id: UUID) -> list[Attachment]:
    return db.scalars(
        select(Attachment)
        .where(
            Attachment.tenant_id == tenant_id,
            Attachment.entity_type == "ship_certificate",
            Attachment.entity_id == cert_id,
        )
        .order_by(Attachment.version_no.desc())
    ).all()


@router.post("/ship/certificates/{cert_id}/files", response_model=AttachmentOut)
async def upload_certificate_file(
    cert_id: UUID,
    file: UploadFile = File(...),
    note: str | None = Form(default=None),
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    cert = _cert_or_404(db, auth.tenant_id, cert_id)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, detail={"code": "EMPTY_FILE"})
    if len(raw) > MAX_CERT_FILE_BYTES:
        raise HTTPException(400, detail={"code": "FILE_TOO_LARGE", "max_bytes": MAX_CERT_FILE_BYTES})
    name = (file.filename or "file").lower()
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, detail={"code": "UNSUPPORTED_TYPE", "ext": ext})
    if _sniff_cert_file(raw) != ALLOWED_EXTS[ext]:
        raise HTTPException(
            400, detail={"code": "INVALID_CONTENT", "message": "File content does not match an allowed type"}
        )
    next_version = (
        db.scalar(
            select(func.max(Attachment.version_no)).where(
                Attachment.tenant_id == auth.tenant_id,
                Attachment.entity_type == "ship_certificate",
                Attachment.entity_id == cert.id,
            )
        )
        or 0
    ) + 1
    dest_dir = _UPLOAD_ROOT / str(auth.tenant_id) / str(cert.id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"v{next_version}_{_safe_filename(file.filename or 'file')}"
    dest.write_bytes(raw)
    for prev in _cert_attachments(db, auth.tenant_id, cert.id):
        prev.is_current = False
    row = Attachment(
        tenant_id=auth.tenant_id,
        entity_type="ship_certificate",
        entity_id=cert.id,
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
        action="ship.certificate.file_upload",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="ship_certificate",
        entity_id=cert.id,
        detail={"attachment_id": str(row.id), "file_name": row.file_name, "version_no": next_version},
    )
    db.commit()
    db.refresh(row)
    return _attachment_out(row)


@router.get("/ship/certificates/{cert_id}/files", response_model=list[AttachmentOut])
def list_certificate_files(
    cert_id: UUID,
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    cert = _cert_or_404(db, auth.tenant_id, cert_id)
    return [_attachment_out(r) for r in _cert_attachments(db, auth.tenant_id, cert.id)]


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
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    row = _attachment_or_404(db, auth.tenant_id, attachment_id)
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
    auth: AuthContext = Depends(require_module("ship_mgmt")),
    db: Session = Depends(get_db),
):
    row = _attachment_or_404(db, auth.tenant_id, attachment_id)
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
