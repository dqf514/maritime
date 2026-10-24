"""Audit helper — write AuditLog rows for security-relevant events.

Transaction strategy (chosen after reviewing the routers): audit rows ride the
*caller's* session/transaction so an event commits atomically with the business
change it describes (e.g. password change). For code paths that raise before
any commit (e.g. failed login), pass commit=True to persist the row in its own
transaction. The whole write is wrapped in try/except: an audit failure is
logged and swallowed — it must never break the main flow.

防篡改哈希链（P1-19 残留项）
---------------------------
每一行审计带两个哈希：

- ``row_hash``  = sha256(``prev_hash`` + 本行内容)  —— 改任何一格（动作、
  明细、操作人、时间……）都会让本行的哈希对不上，**改完再把哈希改回去**也会
  因为 prev_hash 参与计算而失效；
- ``prev_hash`` = 同租户上一条审计行的 ``row_hash``（链首为空串）。

链是**按租户**串的（跨租户不串，租户之间不能互相污染）。
``verify_chain(db, tenant_id)`` 会重算每一行并报告：

- ``tampered``  —— 内容被改过（**确证**的篡改，改一行就报一行）；
- ``broken_links`` —— 链接对不上（中间行被删/被换序）。注意：并发写同一
  租户时两条行可能拿到同一个 prev（分叉），这种情况**也会**报在
  ``broken_links`` 里 —— 它是"链不连续"的警告，不是确证的篡改。

已知边界
--------
- 删掉**最后一行**在链内不可见（没有外部锚点）；加锚点需要一张带锁的
  头表，代价大于收益，因此不做。
- 审计行必须**提交后**才参与链；未提交的行不落库也不影响链。
- 链的"上一行"按 ``(created_at, id)`` 排序取，与写入顺序无关 —— 换序会被
  ``broken_links`` 抓到。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models_audit import AuditLog

log = logging.getLogger("marios.audit")

#: 哈希链算法版本 —— 换算法时 +1，旧链不再按新算法校验。
CHAIN_VERSION = "v1"

#: 链首行的 prev_hash 哨兵值（空串 = 我是第一行）。
CHAIN_START = ""


def canonical_detail(detail: dict | None) -> dict:
    """把 detail 规范化成**纯 JSON 结构**（可无损往返）。

    两个作用：

    1. 让哈希可复算 —— 写进去的 detail 必须是能原样读回来的东西；
    2. 顺手修一个老 bug：detail 里带 UUID/Decimal 时，SQLAlchemy 的 JSON
       列会 ``json.dumps`` 失败 → 审计行写不进去（异常被吞掉，行直接丢）。
       这里先转成字符串，审计就不会因为一个 UUID 整个丢掉。
    """
    if not detail:
        return {}
    try:
        return json.loads(json.dumps(detail, default=str))
    except Exception:  # noqa: BLE001 — 实在转不了就退化成 repr，绝不让审计挂掉
        return {"_unserializable": repr(detail)[:2000]}


def _canonical_json(detail: dict | None) -> str:
    """规范化 detail 的稳定字符串形式（键排序 + 无空格）。"""
    try:
        return json.dumps(detail or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        return "{}"


def _dt_key(dt: datetime | None) -> str:
    """把时间戳规范化成 UTC ISO 字符串。

    SQLite 不存时区，读回来是 naive 的 —— 按 UTC 解释（写进去的就是 UTC）。
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def compute_row_hash(
    *,
    prev_hash: str,
    action: str,
    tenant_id: UUID | None,
    actor_user_id: UUID | None,
    entity_type: str | None,
    entity_id: str | None,
    detail: dict | None,
    ip: str | None,
    created_at: datetime | None,
) -> str:
    """本行的 sha256。prev_hash 参与计算 → 改动任何一格都会让后继行失效。"""
    payload = "|".join(
        [
            CHAIN_VERSION,
            prev_hash or "",
            action or "",
            str(tenant_id) if tenant_id else "",
            str(actor_user_id) if actor_user_id else "",
            entity_type or "",
            entity_id or "",
            _canonical_json(detail),
            ip or "",
            _dt_key(created_at),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _pending_head(db: Session, tenant_id: UUID | None) -> str | None:
    """本会话里还没 flush 的上一条链行（同一事务内多次 audit() 时用）。"""
    try:
        pending = [
            r
            for r in db.new
            if isinstance(r, AuditLog) and r.row_hash and r.tenant_id == tenant_id
        ]
    except Exception:  # noqa: BLE001
        return None
    if not pending:
        return None
    last = max(pending, key=lambda r: (r.created_at or datetime.min.replace(tzinfo=timezone.utc), str(r.id)))
    return last.row_hash or CHAIN_START


def _committed_head(db: Session, tenant_id: UUID | None) -> str:
    """库里最后一条带链行的 row_hash（链首返回空串）。"""
    try:
        stmt = select(AuditLog.row_hash).where(AuditLog.row_hash.is_not(None))
        if tenant_id is None:
            stmt = stmt.where(AuditLog.tenant_id.is_(None))
        else:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(1)
        return db.execute(stmt).scalar() or CHAIN_START
    except Exception:  # noqa: BLE001
        log.exception("audit chain head lookup failed tenant=%s", tenant_id)
        return CHAIN_START


def append_audit_row(
    db: Session,
    *,
    action: str,
    tenant_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: object = None,
    detail: dict | None = None,
    ip: str | None = None,
    created_at: datetime | None = None,
) -> AuditLog:
    """写一行**带链**的审计行（不提交 —— 提交策略由调用方决定）。

    与 :func:`audit` 的区别只是"不会吞异常"，方便调用方需要拿到行对象时用。
    """
    created_at = created_at or datetime.now(timezone.utc)
    eid = str(entity_id) if entity_id is not None else None
    det = canonical_detail(detail)

    head = _pending_head(db, tenant_id)
    if head is None:
        head = _committed_head(db, tenant_id)
    prev = head or CHAIN_START

    row_hash = compute_row_hash(
        prev_hash=prev,
        action=action,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=eid,
        detail=det,
        ip=ip,
        created_at=created_at,
    )
    row = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=eid,
        detail=det,
        ip=ip,
        created_at=created_at,
        prev_hash=prev,
        row_hash=row_hash,
    )
    db.add(row)
    return row


def audit(
    db: Session,
    *,
    action: str,
    tenant_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: object = None,
    detail: dict | None = None,
    ip: str | None = None,
    commit: bool = False,
) -> None:
    """Append one audit row. Never raises."""
    try:
        append_audit_row(
            db,
            action=action,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
            ip=ip,
        )
        if commit:
            db.commit()
    except Exception:  # noqa: BLE001
        log.exception("audit write failed action=%s", action)
        if commit:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass


def verify_chain(db: Session, tenant_id: UUID | None = None) -> dict[str, Any]:
    """校验一条链（``tenant_id=None`` 校验"系统级"那串 tenant_id 为空的行）。

    返回::

        {
          "ok": bool,                 # 没有确证的篡改
          "checked": int,             # 参与校验的行数
          "tampered": [ {...}, ... ], # 确证被改过的行
          "broken_links": [ {...} ],  # 链不连续的行（删行/换序/并发分叉）
        }
    """
    stmt = select(AuditLog)
    if tenant_id is None:
        stmt = stmt.where(AuditLog.tenant_id.is_(None))
    else:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    rows = list(db.scalars(stmt.order_by(AuditLog.created_at, AuditLog.id)).all())

    tampered: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    checked = 0
    prev = CHAIN_START

    for r in rows:
        if not r.row_hash:
            # 老数据（引入哈希链之前写的行）没有哈希，跳过 —— 但不打断链。
            continue
        checked += 1
        expected = compute_row_hash(
            prev_hash=r.prev_hash or "",
            action=r.action or "",
            tenant_id=r.tenant_id,
            actor_user_id=r.actor_user_id,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            detail=r.detail,
            ip=r.ip,
            created_at=r.created_at,
        )
        if expected != r.row_hash:
            tampered.append(
                {
                    "id": str(r.id),
                    "action": r.action,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "reason": "row_hash_mismatch",
                }
            )
        if (r.prev_hash or "") != prev:
            broken.append(
                {
                    "id": str(r.id),
                    "action": r.action,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "expected_prev": prev,
                    "actual_prev": r.prev_hash or "",
                }
            )
        prev = r.row_hash

    return {
        "ok": not tampered,
        "checked": checked,
        "tampered": tampered,
        "broken_links": broken,
    }


def verify_all_chains(db: Session) -> dict[str, Any]:
    """逐租户校验所有链，返回汇总。"""
    tenant_ids = list(
        db.scalars(select(AuditLog.tenant_id).where(AuditLog.tenant_id.is_not(None)).distinct()).all()
    )
    results = []
    ok = True
    for tid in tenant_ids:
        res = verify_chain(db, tid)
        ok = ok and res["ok"]
        results.append({"tenant_id": str(tid), **res})
    system = verify_chain(db, None)
    ok = ok and system["ok"]
    results.append({"tenant_id": None, **system})
    return {"ok": ok, "chains": results}
