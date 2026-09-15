"""Page-level SOP guides — bilingual, login-gated."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.security import AuthContext, get_current_auth
from app.services import page_guides

router = APIRouter(tags=["Guides"])


@router.get("/guides/{page_key}")
def get_guide(page_key: str, auth: AuthContext = Depends(get_current_auth)):
    guide = page_guides.get_guide(page_key)
    if guide is None:
        raise HTTPException(404, detail={"code": "GUIDE_NOT_FOUND", "page_key": page_key})
    return guide
