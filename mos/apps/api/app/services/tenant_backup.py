"""全租户数据备份 / 恢复 / 清理（平台管理员运维工具）。

与 ``settings/dataops`` 的 Wave-0 配置备份不同：这里按 ``Base.metadata`` 中
所有带 ``tenant_id`` 列的表做全量行级 dump（JSON），支持：

- ``dump_tenant``  — 全量备份（写 ``data/backups/tenant/<tid>/<job>.json`` + BackupJob 记录）
- ``restore_tenant`` — 从备份文件恢复（按 FK 顺序插入，已存在的主键跳过）
- ``purge_tenant`` — 清空租户业务数据（保留租户本体/用户/许可等身份底座，可选连用户一起清）

序列化：UUID→str、datetime/date→ISO、Decimal→str、bytes→base64（带标记还原）。
恢复插入顺序按 ``sorted_tables``（拓扑），删除按其逆序，避免 FK 约束冲突。
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Uuid, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import BackupJob, Tenant
from app.services.timeutil import utcnow_naive

# 清理时默认保留的身份/平台底座表（业务数据全部清除）
PURGE_KEEP = {
    "tenants",
    "users",
    "user_identities",
    "roles",  # 保留角色定义，避免已保留用户的角色挂空
    "tenant_module_licenses",
    "tenant_auth_policies",
    "backup_jobs",
    "backup_schedules",
    "api_keys",
    "audit_logs",
}


def _data_root() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def ensure_model_registry() -> None:
    """确保全部模型模块已注册到 ``Base.metadata``。

    ``app.models`` 只含租户/用户底座，其余 30+ 个 ``models_*.py`` 由 ``app.main``
    在启动时导入。在应用进程内调用本服务没问题，但**以脚本/运维命令方式单独调用**
    时，元数据里只会有 8 张表 —— 备份会「静默只备了零头」，恢复/清理同样漏表。
    这里按模块名前缀自动补齐导入，新增 ``models_*.py`` 无需再手工登记。
    """
    import importlib
    import pkgutil

    import app

    for mod in pkgutil.iter_modules(app.__path__):
        if not mod.name.startswith("models"):
            continue
        try:
            importlib.import_module(f"app.{mod.name}")
        except Exception:  # pragma: no cover — 单个模型模块失败不应阻断备份
            continue


def tenant_tables() -> list:
    """All tables carrying a tenant_id column."""
    ensure_model_registry()
    return [t for t in Base.metadata.sorted_tables if "tenant_id" in t.columns]


def _encode(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return {"__dt__": value.isoformat()}
    if isinstance(value, date):
        return {"__d__": value.isoformat()}
    if isinstance(value, Decimal):
        return {"__dec__": str(value)}
    if isinstance(value, (bytes, bytearray)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        if "__dt__" in value:
            return datetime.fromisoformat(value["__dt__"])
        if "__d__" in value:
            return date.fromisoformat(value["__d__"])
        if "__dec__" in value:
            return Decimal(value["__dec__"])
        if "__b64__" in value:
            return base64.b64decode(value["__b64__"])
    return value


def _dump_table(db: Session, table, tenant_id: UUID) -> list[dict[str, Any]]:
    rows = db.execute(select(table).where(table.c.tenant_id == tenant_id)).mappings().all()
    out = []
    for r in rows:
        out.append({c.name: _encode(r[c.name]) for c in table.columns})
    return out


def dump_tenant(db: Session, tenant_id: UUID, *, created_by: UUID | None = None, trigger: str = "platform") -> dict[str, Any]:
    """Full-row dump of every tenant-scoped table. Returns the payload; caller persists."""
    tables: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    for table in tenant_tables():
        rows = _dump_table(db, table, tenant_id)
        tables[table.name] = rows
        counts[table.name] = len(rows)
    return {
        "version": 2,
        "tenant_id": str(tenant_id),
        "created_at": utcnow_naive().isoformat(),
        "created_by": str(created_by) if created_by else None,
        "trigger": trigger,
        "row_counts": counts,
        "total_rows": sum(counts.values()),
        "tables": tables,
    }


def write_backup_file(db: Session, tenant_id: UUID, payload: dict[str, Any], *, created_by: UUID | None = None) -> BackupJob:
    """Persist payload JSON under data/backups/tenant/... and record a BackupJob."""
    job_id = uuid4()
    rel = f"backups/tenant/{tenant_id}/{job_id}.json"
    path = _data_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=1)
    path.write_text(raw, encoding="utf-8")
    job = BackupJob(
        tenant_id=tenant_id,
        status="completed",
        trigger=payload.get("trigger") or "platform",
        storage_path=rel,
        checksum=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        created_by=created_by,
        finished_at=utcnow_naive(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def restore_tenant(db: Session, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
    """Insert rows from a dump payload (FK order). Existing PKs are skipped."""
    ensure_model_registry()
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    inserted: dict[str, int] = {}
    skipped: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:  # parents first
        rows = (payload.get("tables") or {}).get(table.name)
        if not rows or "tenant_id" not in table.columns:
            continue
        pk_cols = list(table.primary_key.columns)
        ins = 0
        skip = 0
        for row in rows:
            values: dict[str, Any] = {}
            for c in table.columns:
                if c.name not in row:
                    continue
                v = _decode(row[c.name])
                # Uuid 列（含主键/外键）需还原为 uuid.UUID，SQLite CHAR(32) 绑定才正确。
                # 注意 sqlalchemy.Uuid（泛型）与 sqlalchemy.UUID（具体类）不是同一个类，
                # 泛型是基类，用 Uuid 判断可同时覆盖两者。
                if isinstance(v, str) and isinstance(c.type, Uuid):
                    v = UUID(v)
                values[c.name] = v
            if values.get("tenant_id") and str(values["tenant_id"]) != str(tenant_id):
                continue
            if pk_cols:
                pk_vals = [values.get(c.name) for c in pk_cols]
                if all(v is not None for v in pk_vals):
                    exists = db.execute(
                        select(pk_cols[0]).where(*[c == values[c.name] for c in pk_cols])
                    ).first()
                    if exists:
                        skip += 1
                        continue
            db.execute(table.insert().values(**values))
            ins += 1
        if ins or skip:
            inserted[table.name] = ins
            skipped[table.name] = skip
    db.commit()
    return {"inserted": inserted, "skipped_existing": skipped, "inserted_total": sum(inserted.values())}


def purge_tenant(db: Session, tenant_id: UUID, *, include_users: bool = False) -> dict[str, Any]:
    """Delete all tenant-scoped business rows. Keeps identity baseline (see PURGE_KEEP).

    ``include_users=True`` additionally removes users / identities / API keys.
    The Tenant row itself is always kept.
    """
    keep = set(PURGE_KEEP)
    ensure_model_registry()
    if not include_users:
        pass  # users already in keep
    else:
        keep -= {"users", "user_identities", "api_keys"}
    deleted: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):  # children first
        if "tenant_id" not in table.columns or table.name in keep:
            continue
        res = db.execute(table.delete().where(table.c.tenant_id == tenant_id))
        if res.rowcount:
            deleted[table.name] = int(res.rowcount)
    if include_users:
        # orphaned rows keyed by user_id (no tenant_id column)
        from app.models import User

        live = set(db.scalars(select(User.id)).all())
        for name in ("user_org_memberships", "user_roles"):
            t = Base.metadata.tables.get(name)
            if t is None or "user_id" not in t.columns:
                continue
            user_ids = [r[0] for r in db.execute(select(t.c.user_id).distinct()).all()]
            dead = [u for u in user_ids if u not in live]
            if dead:
                res = db.execute(t.delete().where(t.c.user_id.in_(dead)))
                if res.rowcount:
                    deleted[name] = int(res.rowcount)
    db.commit()
    return {"deleted": deleted, "deleted_total": sum(deleted.values()), "include_users": include_users}


def load_backup_payload(rel_path: str) -> dict[str, Any]:
    path = _data_root() / rel_path
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"backup file not found: {rel_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_tenant_backups(db: Session, tenant_id: UUID, limit: int = 50) -> list[BackupJob]:
    return list(
        db.scalars(
            select(BackupJob)
            .where(BackupJob.tenant_id == tenant_id)
            .order_by(BackupJob.created_at.desc())
            .limit(limit)
        ).all()
    )
