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
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import Uuid, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import BackupJob, Tenant
from app.services.timeutil import utcnow_naive

log = logging.getLogger("marios.tenant_backup")

# 备份文件格式标记（v2 = 信封：加密 + 校验和 + 原子写）
BACKUP_FORMAT = "marios.tenant-backup.v2"
# 是否加密：默认开；TENANT_BACKUP_ENCRYPT=0 可退回明文（仅本地调试）
_ENCRYPT_ENV = "TENANT_BACKUP_ENCRYPT"
# 备份根目录（默认 app/data；容器里由 compose 挂持久卷到此处）
_ROOT_ENV = "TENANT_BACKUP_ROOT"

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
    override = os.getenv(_ROOT_ENV, "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "data"


def _stable_key() -> str | None:
    """用于备份加密的**稳定**密钥。

    刻意不读 ``get_settings().jwt_secret``：该字段为空时应用会生成进程级随机值，
    用它加密就等于「重启即永久不可解」。这里只认显式配置的环境变量。
    """
    for name in ("OPS_DATA_KEY", "JWT_SECRET"):
        val = os.getenv(name, "").strip()
        if val:
            return val
    return None


def _fernet() -> Fernet | None:
    raw = _stable_key()
    if not raw:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    return Fernet(key)


def _encryption_enabled() -> bool:
    return os.getenv(_ENCRYPT_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def ensure_model_registry() -> list[str]:
    """确保全部模型模块已注册到 ``Base.metadata``。

    ``app.models`` 只含租户/用户底座，其余 30+ 个 ``models_*.py`` 由 ``app.main``
    在启动时导入。在应用进程内调用本服务没问题，但**以脚本/运维命令方式单独调用**
    时，元数据里只会有 8 张表 —— 备份会「静默只备了零头」，恢复/清理同样漏表。
    这里按模块名前缀自动补齐导入，新增 ``models_*.py`` 无需再手工登记。

    返回导入失败的模块名列表（不再静默吞掉：失败的模块意味着备份少了几张表）。
    """
    import importlib
    import pkgutil

    import app

    failed: list[str] = []
    for mod in pkgutil.iter_modules(app.__path__):
        if not mod.name.startswith("models"):
            continue
        try:
            importlib.import_module(f"app.{mod.name}")
        except Exception:  # pragma: no cover — 单个模型模块失败不应阻断备份
            log.exception("模型模块导入失败，该模块定义的表不会被备份：%s", mod.name)
            failed.append(mod.name)
    return failed


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


# ────────────────────────── 用户绑定（无 tenant_id 列的关联表）──────────────────────────
#
# ``user_roles`` / ``user_org_memberships`` 是**按 user_id 归属**的关联表，
# 本身没有 ``tenant_id`` 列 —— 「扫带 tenant_id 的表」这条规则扫不到它们。
# 后果是：备份文件里根本没有用户的角色/组织归属，恢复之后用户**一个角色都没有**，
# 登录进去什么也看不见（审计 P2-10）。
#
# 这两张表用**可移植的键**记录：用户用 email、角色用 code、组织用 id+code。
# 为什么不用裸 UUID：备份可能跨实例/跨库恢复，UUID 不保证一致；
# email / role.code 在租户内是稳定的业务键。
BINDING_ROLES = "roles"
BINDING_ORGS = "org_memberships"


def _dump_user_bindings(db: Session, tenant_id: UUID) -> dict[str, list[dict[str, Any]]]:
    """Dump the tenant-scoped *join* tables that carry no ``tenant_id`` column.

    只收本租户用户的绑定行（用户表按 ``tenant_id`` 过滤）。
    """
    out: dict[str, list[dict[str, Any]]] = {BINDING_ROLES: [], BINDING_ORGS: []}
    meta = Base.metadata
    users_t = meta.tables.get("users")
    roles_t = meta.tables.get("roles")
    user_roles_t = meta.tables.get("user_roles")
    if users_t is None or user_roles_t is None:
        return out

    email_by_id = {
        str(r[0]): r[1]
        for r in db.execute(select(users_t.c.id, users_t.c.email).where(users_t.c.tenant_id == tenant_id)).all()
    }
    if not email_by_id:
        return out

    # 角色：id → code（按租户过滤，避免把别的租户的角色写进来）
    code_by_role_id: dict[str, str] = {}
    if roles_t is not None:
        for rid, code in db.execute(
            select(roles_t.c.id, roles_t.c.code).where(roles_t.c.tenant_id == tenant_id)
        ).all():
            code_by_role_id[str(rid)] = code

    for uid, rid in db.execute(select(user_roles_t.c.user_id, user_roles_t.c.role_id)).all():
        email = email_by_id.get(str(uid))
        if not email:
            continue
        out[BINDING_ROLES].append(
            {
                "email": email,
                "role_code": code_by_role_id.get(str(rid)),
                "role_id": str(rid),
            }
        )

    # 组织归属
    org_t = meta.tables.get("org_units")
    memb_t = meta.tables.get("user_org_memberships")
    if org_t is not None and memb_t is not None:
        org_info = {
            str(r[0]): {"code": r[1], "name": r[2]}
            for r in db.execute(
                select(org_t.c.id, org_t.c.code, org_t.c.name).where(org_t.c.tenant_id == tenant_id)
            ).all()
        }
        for uid, oid, is_primary in db.execute(
            select(memb_t.c.user_id, memb_t.c.org_unit_id, memb_t.c.is_primary)
        ).all():
            email = email_by_id.get(str(uid))
            if not email:
                continue
            info = org_info.get(str(oid), {})
            out[BINDING_ORGS].append(
                {
                    "email": email,
                    "org_unit_id": str(oid),
                    "org_code": info.get("code"),
                    "org_name": info.get("name"),
                    "is_primary": bool(is_primary),
                }
            )
    return out


def _as_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _restore_user_bindings(db: Session, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Re-create ``user_roles`` / ``user_org_memberships`` from a dump payload.

    匹配顺序（从稳到脆）：
    - 用户：email（租户内唯一）
    - 角色：role_code（租户内唯一）→ role_id
    - 组织：org_unit_id → org_code

    匹配不上的行**跳过**（不猜、不硬塞）—— 宁可少绑一个角色，也不能把用户
    挂到别的租户的角色上（越权）。
    """
    result: dict[str, dict[str, int]] = {
        "user_roles": {"inserted": 0, "skipped": 0},
        "user_org_memberships": {"inserted": 0, "skipped": 0},
    }
    section = payload.get("user_bindings") or {}
    if not section:
        return result

    meta = Base.metadata
    users_t = meta.tables.get("users")
    roles_t = meta.tables.get("roles")
    user_roles_t = meta.tables.get("user_roles")
    org_t = meta.tables.get("org_units")
    memb_t = meta.tables.get("user_org_memberships")
    if users_t is None or user_roles_t is None:
        return result

    uid_by_email = {
        str(r[1]).strip().lower(): r[0]
        for r in db.execute(select(users_t.c.id, users_t.c.email).where(users_t.c.tenant_id == tenant_id)).all()
    }

    # 角色：code → id（租户内），id → code（用于校验 role_id 属于本租户）
    role_id_by_code: dict[str, UUID] = {}
    role_code_by_id: dict[str, str] = {}
    if roles_t is not None:
        for rid, code in db.execute(
            select(roles_t.c.id, roles_t.c.code).where(roles_t.c.tenant_id == tenant_id)
        ).all():
            role_id_by_code[str(code).strip().lower()] = rid
            role_code_by_id[str(rid)] = code

    for item in section.get(BINDING_ROLES) or []:
        uid = uid_by_email.get(str(item.get("email") or "").strip().lower())
        if uid is None:
            continue
        rid: UUID | None = None
        code = item.get("role_code")
        if code:
            rid = role_id_by_code.get(str(code).strip().lower())
        if rid is None:
            cand = _as_uuid(item.get("role_id"))
            # role_id 必须确实属于本租户，否则拒绝（防止越权挂载）
            if cand is not None and str(cand) in role_code_by_id:
                rid = cand
        if rid is None:
            continue
        exists = db.execute(
            select(user_roles_t.c.user_id).where(
                user_roles_t.c.user_id == uid, user_roles_t.c.role_id == rid
            )
        ).first()
        if exists:
            result["user_roles"]["skipped"] += 1
            continue
        db.execute(user_roles_t.insert().values(user_id=uid, role_id=rid))
        result["user_roles"]["inserted"] += 1

    # 组织归属
    if org_t is not None and memb_t is not None:
        org_id_by_code: dict[str, UUID] = {}
        org_ids: set[str] = set()
        for oid, ocode in db.execute(
            select(org_t.c.id, org_t.c.code).where(org_t.c.tenant_id == tenant_id)
        ).all():
            org_id_by_code[str(ocode).strip().lower()] = oid
            org_ids.add(str(oid))
        for item in section.get(BINDING_ORGS) or []:
            uid = uid_by_email.get(str(item.get("email") or "").strip().lower())
            if uid is None:
                continue
            oid: UUID | None = None
            cand = _as_uuid(item.get("org_unit_id"))
            if cand is not None and str(cand) in org_ids:
                oid = cand
            if oid is None:
                ocode = item.get("org_code")
                if ocode:
                    oid = org_id_by_code.get(str(ocode).strip().lower())
            if oid is None:
                continue
            exists = db.execute(
                select(memb_t.c.id).where(memb_t.c.user_id == uid, memb_t.c.org_unit_id == oid)
            ).first()
            if exists:
                result["user_org_memberships"]["skipped"] += 1
                continue
            db.execute(
                memb_t.insert().values(
                    id=uuid4(),
                    user_id=uid,
                    org_unit_id=oid,
                    is_primary=bool(item.get("is_primary", True)),
                )
            )
            result["user_org_memberships"]["inserted"] += 1

    return result


def dump_tenant(db: Session, tenant_id: UUID, *, created_by: UUID | None = None, trigger: str = "platform") -> dict[str, Any]:
    """Full-row dump of every tenant-scoped table. Returns the payload; caller persists."""
    failed_modules = ensure_model_registry()
    tables: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    # 一致性快照：备份期间的写入不应让各表落在不同时间点上（撕裂快照）。
    # REPEATABLE READ 是 Postgres 的标准做法；SQLite 不支持该语法 → 退化为默认隔离。
    try:
        db.connection().exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    except Exception:  # pragma: no cover — 方言/事务状态不支持时忽略
        log.debug("当前方言不支持 REPEATABLE READ，备份使用默认隔离级别", exc_info=True)
    for table in tenant_tables():
        rows = _dump_table(db, table, tenant_id)
        tables[table.name] = rows
        counts[table.name] = len(rows)
    # 无 tenant_id 列的关联表（用户角色 / 组织归属）单独走「可移植键」通道，
    # 否则恢复出来的用户**没有任何角色**（审计 P2-10）。
    bindings = _dump_user_bindings(db, tenant_id)
    counts["user_roles"] = len(bindings[BINDING_ROLES])
    counts["user_org_memberships"] = len(bindings[BINDING_ORGS])
    return {
        "version": 2,
        "tenant_id": str(tenant_id),
        "created_at": utcnow_naive().isoformat(),
        "created_by": str(created_by) if created_by else None,
        "trigger": trigger,
        "row_counts": counts,
        "total_rows": sum(counts.values()),
        "tables": tables,
        "user_bindings": bindings,
        "skipped_model_modules": failed_modules,
    }


def _encode_payload(payload: dict[str, Any]) -> bytes:
    """把载荷编码成落盘字节：可用密钥时 Fernet 加密，否则明文 JSON。"""
    plain = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    if not _encryption_enabled():
        return plain
    fernet = _fernet()
    if fernet is None:
        log.warning(
            "未配置 OPS_DATA_KEY / JWT_SECRET —— 租户备份将以**明文**落盘。"
            "生产环境必须配置 OPS_DATA_KEY（否则重启后备份文件无人能解）。"
        )
        return plain
    token = fernet.encrypt(plain).decode("ascii")
    envelope = {
        "format": BACKUP_FORMAT,
        "encrypted": True,
        "algo": "fernet",
        "data": token,
    }
    return json.dumps(envelope, ensure_ascii=False).encode("utf-8")


def write_backup_file(db: Session, tenant_id: UUID, payload: dict[str, Any], *, created_by: UUID | None = None) -> BackupJob:
    """Persist payload under data/backups/tenant/... and record a BackupJob.

    落盘顺序：写 ``*.tmp`` → fsync → ``os.replace`` 原子发布 → 写 ``.sha256``。
    """
    job_id = uuid4()
    rel = f"backups/tenant/{tenant_id}/{job_id}.json"
    path = _data_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _encode_payload(payload)
    digest = hashlib.sha256(raw).hexdigest()

    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "wb") as fh:
        fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)  # 原子发布

    # 校验和与文件一一对应（恢复时强制校验）
    sum_path = path.with_name(path.name + ".sha256")
    tmp_sum = sum_path.with_name(sum_path.name + ".tmp")
    tmp_sum.write_text(digest, encoding="utf-8")
    os.replace(tmp_sum, sum_path)

    job = BackupJob(
        tenant_id=tenant_id,
        status="completed",
        trigger=payload.get("trigger") or "platform",
        storage_path=rel,
        checksum=digest,
        created_by=created_by,
        finished_at=utcnow_naive(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def restore_tenant(db: Session, tenant_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
    """Insert rows from a dump payload (FK order). Existing PKs are skipped.

    返回值里带 ``expected_total`` / ``mismatched_tables``：按备份里的
    ``row_counts`` 对账，恢复了多少、缺了多少一目了然（审计 P0-15）。
    """
    ensure_model_registry()
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

    # 用户角色 / 组织归属：这两张表没有 tenant_id 列，上面的拓扑插入碰不到它们。
    # 不恢复 = 恢复出来的用户一个角色都没有（审计 P2-10）。
    bindings = _restore_user_bindings(db, tenant_id, payload)
    for name, cnt in bindings.items():
        if cnt["inserted"] or cnt["skipped"]:
            inserted[name] = cnt["inserted"]
            skipped[name] = cnt["skipped"]
    db.commit()

    # 行数对账：备份里记了多少、这次恢复回来多少
    expected: dict[str, int] = {k: int(v) for k, v in (payload.get("row_counts") or {}).items()}
    mismatched: dict[str, dict[str, int]] = {}
    for name, want in expected.items():
        got = inserted.get(name, 0) + skipped.get(name, 0)
        if got != want:
            mismatched[name] = {"expected": want, "restored": got}
    return {
        "inserted": inserted,
        "skipped_existing": skipped,
        "inserted_total": sum(inserted.values()),
        "expected_total": sum(expected.values()) or payload.get("total_rows") or 0,
        "mismatched_tables": mismatched,
    }


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
    """读取并校验备份文件；校验和不匹配一律拒绝（不写入任何数据）。"""
    path = _data_root() / rel_path
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"backup file not found: {rel_path}")
    raw = path.read_bytes()

    # 校验和：文件旁必须有 .sha256，且与内容一致
    sum_path = path.with_name(path.name + ".sha256")
    if sum_path.exists():
        expected = sum_path.read_text(encoding="utf-8").strip()
        actual = hashlib.sha256(raw).hexdigest()
        if expected and expected != actual:
            log.error("备份文件校验和不匹配，拒绝恢复：%s", rel_path)
            raise HTTPException(
                400,
                detail={
                    "code": "BACKUP_INTEGRITY_FAILED",
                    "message": "备份文件校验和不匹配，可能已被篡改或截断",
                },
            )
    else:
        log.warning("备份文件缺少校验和文件（%s.sha256），按未校验处理", path.name)

    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            400,
            detail={"code": "BACKUP_CORRUPTED", "message": f"备份文件无法解析：{exc}"},
        ) from exc

    if isinstance(envelope, dict) and envelope.get("format") == BACKUP_FORMAT and envelope.get("encrypted"):
        fernet = _fernet()
        if fernet is None:
            raise HTTPException(
                400,
                detail={
                    "code": "BACKUP_KEY_MISSING",
                    "message": "备份文件已加密，但本实例没有 OPS_DATA_KEY / JWT_SECRET，无法解密",
                },
            )
        try:
            plain = fernet.decrypt(str(envelope.get("data") or "").encode("ascii"))
        except (InvalidToken, ValueError) as exc:
            raise HTTPException(
                400,
                detail={
                    "code": "BACKUP_DECRYPT_FAILED",
                    "message": "备份文件解密失败（密钥已变更或文件损坏）",
                },
            ) from exc
        return json.loads(plain.decode("utf-8"))

    # 兼容 v1（明文 JSON 直写）
    return envelope


def list_tenant_backups(db: Session, tenant_id: UUID, limit: int = 50) -> list[BackupJob]:
    return list(
        db.scalars(
            select(BackupJob)
            .where(BackupJob.tenant_id == tenant_id)
            .order_by(BackupJob.created_at.desc())
            .limit(limit)
        ).all()
    )
