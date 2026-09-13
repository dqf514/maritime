"""参考数据服务：系统包种子、有效列表解析、租户克隆与 CRUD。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_reference import ReferenceDataset, ReferenceItem, TenantReferenceConfig
from app.services.reference_packs import DATASETS, iter_system_items


def seed_reference_catalog(db: Session, *, force_refresh_system: bool = False) -> dict:
    """幂等写入数据源目录与系统条目。"""
    created_ds = 0
    created_items = 0
    for ds in DATASETS:
        row = db.get(ReferenceDataset, ds["code"])
        if not row:
            db.add(
                ReferenceDataset(
                    code=ds["code"],
                    name_en=ds["name_en"],
                    name_zh=ds["name_zh"],
                    description_en=ds.get("description_en"),
                    description_zh=ds.get("description_zh"),
                    sort_order=ds.get("sort_order", 0),
                    editable=True,
                )
            )
            created_ds += 1
        else:
            row.name_en = ds["name_en"]
            row.name_zh = ds["name_zh"]
            row.description_en = ds.get("description_en")
            row.description_zh = ds.get("description_zh")
            row.sort_order = ds.get("sort_order", 0)

        existing = {
            r.code: r
            for r in db.scalars(
                select(ReferenceItem).where(
                    ReferenceItem.dataset_code == ds["code"],
                    ReferenceItem.scope_key == "system",
                )
            ).all()
        }
        for code, label_en, label_zh, sort_order, meta in iter_system_items(ds["code"]):
            if code in existing:
                if force_refresh_system:
                    it = existing[code]
                    it.label_en = label_en
                    it.label_zh = label_zh
                    it.sort_order = sort_order
                    it.meta = meta or {}
                    it.active = True
                continue
            db.add(
                ReferenceItem(
                    id=uuid4(),
                    dataset_code=ds["code"],
                    tenant_id=None,
                    scope_key="system",
                    code=code,
                    label_en=label_en,
                    label_zh=label_zh,
                    sort_order=sort_order,
                    active=True,
                    source="system",
                    meta=meta or {},
                )
            )
            created_items += 1
    db.flush()
    return {"datasets": created_ds, "items": created_items}


def _scope(tenant_id: UUID | None) -> str:
    return "system" if tenant_id is None else str(tenant_id)


def get_mode(db: Session, tenant_id: UUID, dataset_code: str) -> str:
    cfg = db.scalar(
        select(TenantReferenceConfig).where(
            TenantReferenceConfig.tenant_id == tenant_id,
            TenantReferenceConfig.dataset_code == dataset_code,
        )
    )
    return cfg.mode if cfg else "system"


def list_datasets(db: Session, tenant_id: UUID, locale: str = "zh-CN") -> list[dict]:
    rows = db.scalars(select(ReferenceDataset).order_by(ReferenceDataset.sort_order, ReferenceDataset.code)).all()
    zh = locale.startswith("zh")
    out = []
    for r in rows:
        mode = get_mode(db, tenant_id, r.code)
        sys_count = db.scalars(
            select(ReferenceItem).where(ReferenceItem.dataset_code == r.code, ReferenceItem.scope_key == "system")
        ).all()
        local_count = db.scalars(
            select(ReferenceItem).where(ReferenceItem.dataset_code == r.code, ReferenceItem.scope_key == str(tenant_id))
        ).all()
        out.append(
            {
                "code": r.code,
                "name": r.name_zh if zh else r.name_en,
                "name_en": r.name_en,
                "name_zh": r.name_zh,
                "description": (r.description_zh if zh else r.description_en) or "",
                "mode": mode,
                "editable": r.editable,
                "system_count": len(sys_count),
                "local_count": len(local_count),
                "active_local_count": sum(1 for x in local_count if x.active),
            }
        )
    return out


def _serialize(item: ReferenceItem, locale: str) -> dict:
    zh = locale.startswith("zh")
    return {
        "id": str(item.id),
        "dataset_code": item.dataset_code,
        "code": item.code,
        "label": item.label_zh if zh else item.label_en,
        "label_en": item.label_en,
        "label_zh": item.label_zh,
        "sort_order": item.sort_order,
        "active": item.active,
        "source": item.source,
        "meta": item.meta or {},
        "is_local": item.scope_key != "system",
    }


def list_items(
    db: Session,
    tenant_id: UUID,
    dataset_code: str,
    *,
    locale: str = "zh-CN",
    q: str | None = None,
    active_only: bool = True,
    admin: bool = False,
) -> list[dict]:
    mode = get_mode(db, tenant_id, dataset_code)
    scope = str(tenant_id) if mode == "local" else "system"
    rows = db.scalars(
        select(ReferenceItem)
        .where(ReferenceItem.dataset_code == dataset_code, ReferenceItem.scope_key == scope)
        .order_by(ReferenceItem.sort_order, ReferenceItem.code)
    ).all()
    if active_only and not admin:
        rows = [r for r in rows if r.active]
    if q:
        qq = q.strip().lower()
        rows = [
            r
            for r in rows
            if qq in r.code.lower()
            or qq in (r.label_en or "").lower()
            or qq in (r.label_zh or "").lower()
        ]
    return [_serialize(r, locale) for r in rows]


def clone_dataset(db: Session, tenant_id: UUID, dataset_code: str) -> dict:
    ds = db.get(ReferenceDataset, dataset_code)
    if not ds:
        raise ValueError("DATASET_NOT_FOUND")
    system_rows = db.scalars(
        select(ReferenceItem).where(ReferenceItem.dataset_code == dataset_code, ReferenceItem.scope_key == "system")
    ).all()
    scope = str(tenant_id)
    # 清除旧本地副本后重建
    old = db.scalars(
        select(ReferenceItem).where(ReferenceItem.dataset_code == dataset_code, ReferenceItem.scope_key == scope)
    ).all()
    for o in old:
        db.delete(o)
    db.flush()
    n = 0
    for s in system_rows:
        db.add(
            ReferenceItem(
                id=uuid4(),
                dataset_code=dataset_code,
                tenant_id=tenant_id,
                scope_key=scope,
                code=s.code,
                label_en=s.label_en,
                label_zh=s.label_zh,
                sort_order=s.sort_order,
                active=s.active,
                source="cloned",
                origin_code=s.code,
                meta=dict(s.meta or {}),
            )
        )
        n += 1
    cfg = db.scalar(
        select(TenantReferenceConfig).where(
            TenantReferenceConfig.tenant_id == tenant_id,
            TenantReferenceConfig.dataset_code == dataset_code,
        )
    )
    now = datetime.now()
    if not cfg:
        cfg = TenantReferenceConfig(
            tenant_id=tenant_id,
            dataset_code=dataset_code,
            mode="local",
            cloned_at=now,
        )
        db.add(cfg)
    else:
        cfg.mode = "local"
        cfg.cloned_at = now
        cfg.updated_at = now
    db.flush()
    return {"dataset_code": dataset_code, "mode": "local", "cloned": n}


def reset_dataset(db: Session, tenant_id: UUID, dataset_code: str) -> dict:
    scope = str(tenant_id)
    old = db.scalars(
        select(ReferenceItem).where(ReferenceItem.dataset_code == dataset_code, ReferenceItem.scope_key == scope)
    ).all()
    for o in old:
        db.delete(o)
    cfg = db.scalar(
        select(TenantReferenceConfig).where(
            TenantReferenceConfig.tenant_id == tenant_id,
            TenantReferenceConfig.dataset_code == dataset_code,
        )
    )
    if cfg:
        cfg.mode = "system"
        cfg.updated_at = datetime.now()
    else:
        db.add(
            TenantReferenceConfig(
                tenant_id=tenant_id,
                dataset_code=dataset_code,
                mode="system",
            )
        )
    db.flush()
    return {"dataset_code": dataset_code, "mode": "system", "removed_local": len(old)}


def set_mode(db: Session, tenant_id: UUID, dataset_code: str, mode: str) -> dict:
    if mode not in ("system", "local"):
        raise ValueError("INVALID_MODE")
    if mode == "local":
        local_n = len(
            db.scalars(
                select(ReferenceItem).where(
                    ReferenceItem.dataset_code == dataset_code,
                    ReferenceItem.scope_key == str(tenant_id),
                )
            ).all()
        )
        if local_n == 0:
            return clone_dataset(db, tenant_id, dataset_code)
    cfg = db.scalar(
        select(TenantReferenceConfig).where(
            TenantReferenceConfig.tenant_id == tenant_id,
            TenantReferenceConfig.dataset_code == dataset_code,
        )
    )
    now = datetime.now()
    if not cfg:
        db.add(
            TenantReferenceConfig(
                tenant_id=tenant_id,
                dataset_code=dataset_code,
                mode=mode,
                updated_at=now,
            )
        )
    else:
        cfg.mode = mode
        cfg.updated_at = now
    db.flush()
    return {"dataset_code": dataset_code, "mode": mode}


def create_item(
    db: Session,
    tenant_id: UUID,
    dataset_code: str,
    *,
    code: str,
    label_en: str,
    label_zh: str,
    sort_order: int = 0,
    meta: dict | None = None,
    active: bool = True,
) -> ReferenceItem:
    if get_mode(db, tenant_id, dataset_code) != "local":
        clone_dataset(db, tenant_id, dataset_code)
    scope = str(tenant_id)
    code = code.strip()
    exists = db.scalar(
        select(ReferenceItem).where(
            ReferenceItem.dataset_code == dataset_code,
            ReferenceItem.scope_key == scope,
            ReferenceItem.code == code,
        )
    )
    if exists:
        raise ValueError("CODE_EXISTS")
    row = ReferenceItem(
        id=uuid4(),
        dataset_code=dataset_code,
        tenant_id=tenant_id,
        scope_key=scope,
        code=code,
        label_en=label_en.strip() or code,
        label_zh=label_zh.strip() or label_en.strip() or code,
        sort_order=sort_order,
        active=active,
        source="custom",
        meta=meta or {},
    )
    db.add(row)
    db.flush()
    return row


def update_item(
    db: Session,
    tenant_id: UUID,
    item_id: UUID,
    *,
    label_en: str | None = None,
    label_zh: str | None = None,
    sort_order: int | None = None,
    active: bool | None = None,
    meta: dict | None = None,
    code: str | None = None,
) -> ReferenceItem:
    row = db.get(ReferenceItem, item_id)
    if not row or row.scope_key != str(tenant_id):
        raise ValueError("NOT_FOUND_OR_SYSTEM")
    if code is not None and code.strip() != row.code:
        neo = code.strip()
        clash = db.scalar(
            select(ReferenceItem).where(
                ReferenceItem.dataset_code == row.dataset_code,
                ReferenceItem.scope_key == row.scope_key,
                ReferenceItem.code == neo,
            )
        )
        if clash:
            raise ValueError("CODE_EXISTS")
        row.code = neo
    if label_en is not None:
        row.label_en = label_en
    if label_zh is not None:
        row.label_zh = label_zh
    if sort_order is not None:
        row.sort_order = sort_order
    if active is not None:
        row.active = active
    if meta is not None:
        row.meta = meta
    row.updated_at = datetime.now()
    if row.source == "cloned":
        row.source = "cloned"  # still cloned but customized
    db.flush()
    return row


def delete_item(db: Session, tenant_id: UUID, item_id: UUID) -> None:
    row = db.get(ReferenceItem, item_id)
    if not row or row.scope_key != str(tenant_id):
        raise ValueError("NOT_FOUND_OR_SYSTEM")
    db.delete(row)
    db.flush()
