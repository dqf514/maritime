"""参考数据 API：下拉消费 + 管理员克隆/自定义。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, get_current_auth, require_module
from app.services import reference_data as refsvc

router = APIRouter(prefix="/reference", tags=["Reference Data"])


def _locale(auth: AuthContext, locale: str | None) -> str:
    if locale:
        return locale
    user_loc = getattr(auth.user, "locale", None)
    return user_loc or "zh-CN"


def _require_admin(auth: AuthContext) -> None:
    if "tenant_admin" not in auth.roles and "platform_admin" not in auth.roles:
        raise HTTPException(403, detail={"code": "ADMIN_REQUIRED", "message": "需要租户管理员"})


@router.get("/datasets")
def get_datasets(
    locale: str | None = None,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    return refsvc.list_datasets(db, auth.tenant_id, _locale(auth, locale))


@router.get("/{dataset_code}/items")
def get_items(
    dataset_code: str,
    q: str | None = None,
    locale: str | None = None,
    active_only: bool = Query(True),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    return refsvc.list_items(
        db,
        auth.tenant_id,
        dataset_code,
        locale=_locale(auth, locale),
        q=q,
        active_only=active_only,
        admin=False,
    )


@router.get("/{dataset_code}/admin/items")
def admin_items(
    dataset_code: str,
    q: str | None = None,
    locale: str | None = None,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    return refsvc.list_items(
        db,
        auth.tenant_id,
        dataset_code,
        locale=_locale(auth, locale),
        q=q,
        active_only=False,
        admin=True,
    )


@router.post("/{dataset_code}/clone")
def clone_dataset(
    dataset_code: str,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        result = refsvc.clone_dataset(db, auth.tenant_id, dataset_code)
    except ValueError as e:
        raise HTTPException(404 if str(e) == "DATASET_NOT_FOUND" else 400, detail={"code": str(e)})
    db.commit()
    return result


@router.post("/{dataset_code}/reset")
def reset_dataset(
    dataset_code: str,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    result = refsvc.reset_dataset(db, auth.tenant_id, dataset_code)
    db.commit()
    return result


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(system|local)$")


@router.post("/{dataset_code}/mode")
def set_mode(
    dataset_code: str,
    body: ModeIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        result = refsvc.set_mode(db, auth.tenant_id, dataset_code, body.mode)
    except ValueError as e:
        raise HTTPException(400, detail={"code": str(e)})
    db.commit()
    return result


class ItemIn(BaseModel):
    code: str
    label_en: str
    label_zh: str
    sort_order: int = 0
    active: bool = True
    meta: dict = Field(default_factory=dict)


class ItemPatch(BaseModel):
    code: str | None = None
    label_en: str | None = None
    label_zh: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    meta: dict | None = None


@router.post("/{dataset_code}/items")
def create_item(
    dataset_code: str,
    body: ItemIn,
    locale: str | None = None,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        row = refsvc.create_item(
            db,
            auth.tenant_id,
            dataset_code,
            code=body.code,
            label_en=body.label_en,
            label_zh=body.label_zh,
            sort_order=body.sort_order,
            meta=body.meta,
            active=body.active,
        )
    except ValueError as e:
        raise HTTPException(409 if str(e) == "CODE_EXISTS" else 400, detail={"code": str(e)})
    db.commit()
    db.refresh(row)
    return refsvc._serialize(row, _locale(auth, locale))


@router.patch("/items/{item_id}")
def patch_item(
    item_id: UUID,
    body: ItemPatch,
    locale: str | None = None,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        row = refsvc.update_item(
            db,
            auth.tenant_id,
            item_id,
            code=body.code,
            label_en=body.label_en,
            label_zh=body.label_zh,
            sort_order=body.sort_order,
            active=body.active,
            meta=body.meta,
        )
    except ValueError as e:
        code = str(e)
        raise HTTPException(404 if "NOT_FOUND" in code else 409, detail={"code": code})
    db.commit()
    db.refresh(row)
    return refsvc._serialize(row, _locale(auth, locale))


@router.delete("/items/{item_id}")
def remove_item(
    item_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_admin(auth)
    try:
        refsvc.delete_item(db, auth.tenant_id, item_id)
    except ValueError as e:
        raise HTTPException(404, detail={"code": str(e)})
    db.commit()
    return {"ok": True}
