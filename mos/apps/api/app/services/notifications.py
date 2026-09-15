"""Lazy, day-deduplicated notifications shared by home alerts and the exception centre."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, User, UserRole
from app.models_wave1 import Notification


def role_recipients(db: Session, tenant_id: UUID, role_codes: tuple[str, ...]) -> list[User]:
    role_ids = select(Role.id).where(Role.tenant_id == tenant_id, Role.code.in_(role_codes))
    user_ids = select(UserRole.user_id).where(UserRole.role_id.in_(role_ids))
    return db.scalars(
        select(User).where(User.id.in_(user_ids), User.tenant_id == tenant_id, User.status == "active")
    ).all()


def notify_once(
    db: Session,
    tenant_id: UUID,
    recipients: list[User],
    *,
    title: str,
    body: str,
    href: str,
    level: str,
) -> None:
    """Create at most one notification per user + href + title per day."""
    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    targets: list[UUID | None] = [u.id for u in recipients] or [None]
    for uid in targets:
        q = select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.href == href,
            Notification.title == title,
            Notification.created_at >= today_start,
        )
        q = q.where(Notification.user_id == uid) if uid else q.where(Notification.user_id.is_(None))
        if db.scalar(q):
            continue
        db.add(Notification(tenant_id=tenant_id, user_id=uid, title=title, body=body, level=level, href=href))


def notify_roles_once(
    db: Session,
    tenant_id: UUID,
    role_codes: tuple[str, ...],
    *,
    title: str,
    body: str,
    href: str,
    level: str,
) -> None:
    notify_once(db, tenant_id, role_recipients(db, tenant_id, role_codes), title=title, body=body, href=href, level=level)
