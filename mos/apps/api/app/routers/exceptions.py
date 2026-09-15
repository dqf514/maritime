"""Exception centre scan + data-quality scan endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.admin_platform import require_roles
from app.security import AuthContext, get_current_auth
from app.services.audit import audit
from app.services.dq import run_dq_scan
from app.services.exceptions import scan_exceptions

router = APIRouter(tags=["Exceptions & DQ"])


@router.get("/exceptions/scan")
def exceptions_scan(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    return scan_exceptions(db, auth.tenant_id, notify=True)


@router.post("/dq/scan")
def dq_scan(auth: AuthContext = Depends(require_roles("tenant_admin", "management")), db: Session = Depends(get_db)):
    result = run_dq_scan(db, auth.tenant_id)
    audit(
        db,
        action="dq.scan",
        tenant_id=auth.tenant_id,
        actor_user_id=auth.user_id,
        entity_type="dq_issue",
        detail=result,
    )
    db.commit()
    return result
