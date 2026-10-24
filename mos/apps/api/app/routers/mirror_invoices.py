"""镜像发票（intercompany mirror）路由 — 源改镜像跟 / 不可独立编辑.

See services/invoice_mirror.py for the domain rules. This router only wires
HTTP: create a mirror for a source invoice, and read the mirror chain with
pull-sync applied first.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tenant
from app.models_domain import Invoice
from app.security import AuthContext, require_module
from app.services.tenant_guard import scoped_get

from app.services import invoice_mirror

router = APIRouter()


class MirrorCreateIn(BaseModel):
    target_tenant_id: UUID | None = None


@router.post("/invoices/{invoice_id}/mirror")
def create_invoice_mirror(
    invoice_id: UUID,
    body: MirrorCreateIn | None = None,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """为源发票生成镜像（同租户默认；跨租户需 CFGEnableIntercompany）。"""
    source = scoped_get(db, Invoice, invoice_id, auth.tenant_id)
    if source is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Invoice not found"})
    if source.mirror_of_id is not None:
        raise HTTPException(
            422,
            detail={"code": "NOT_MIRRORABLE", "message": "Invoice is itself a mirror; cannot mirror a mirror"},
        )

    existing = invoice_mirror.find_mirror(db, source.id)
    if existing is not None:
        # P1-17：镜像在**别的租户**时，只有开了公司间镜像才回显它的 id ——
        # 否则 409 的 detail 就把外租户的单据 id 送出去了。
        cross_ok = (
            existing.tenant_id == auth.tenant_id
            or invoice_mirror.intercompany_enabled(db, auth.tenant_id, auth.user_id)
        )
        detail: dict = {
            "code": "MIRROR_EXISTS",
            "message": "Invoice already has a mirror",
        }
        if cross_ok:
            detail["mirror_id"] = str(existing.id)
        raise HTTPException(409, detail=detail)

    target_tenant_id = (body.target_tenant_id if body else None) or auth.tenant_id
    if target_tenant_id != auth.tenant_id:
        if not invoice_mirror.intercompany_enabled(db, auth.tenant_id, auth.user_id):
            raise HTTPException(
                403,
                detail={
                    "code": "INTERCOMPANY_DISABLED",
                    "message": "Cross-tenant mirror requires CFGEnableIntercompany",
                    "target_tenant_id": str(target_tenant_id),
                },
            )
        target = db.get(Tenant, target_tenant_id)
        if target is None or target.status == "deleted":
            raise HTTPException(
                404,
                detail={"code": "TENANT_NOT_FOUND", "message": "target_tenant_id does not exist"},
            )

    try:
        mirror = invoice_mirror.create_mirror_invoice(db, source, target_tenant_id)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "NOT_MIRRORABLE", "message": str(exc)})
    db.commit()
    db.refresh(mirror)
    return invoice_mirror.invoice_payload(mirror)


@router.get("/invoices/{invoice_id}/mirror-chain")
def get_invoice_mirror_chain(
    invoice_id: UUID,
    auth: AuthContext = Depends(require_module("finance")),
    db: Session = Depends(get_db),
):
    """返回 [source, mirror] 链；返回前对 draft 镜像做 pull-sync（源改镜像跟）。"""
    inv = scoped_get(db, Invoice, invoice_id, auth.tenant_id)
    if inv is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Invoice not found"})

    # Pull-sync from the source side (源改镜像跟) before assembling the chain.
    source = inv if inv.mirror_of_id is None else db.get(Invoice, inv.mirror_of_id)
    if source is not None:
        invoice_mirror.sync_mirrors(db, source, user_id=auth.user_id)
        db.commit()

    chain = invoice_mirror.get_mirror_chain(db, invoice_id, auth.tenant_id, user_id=auth.user_id)
    return {"items": chain, "count": len(chain)}
