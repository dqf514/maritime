"""Lazy, day-deduplicated notifications shared by home alerts and the exception centre."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, Tenant, User, UserRole
from app.models_wave1 import Notification
from app.services.ui_text import normalize_locale, user_locale


def role_recipients(db: Session, tenant_id: UUID, role_codes: tuple[str, ...]) -> list[User]:
    role_ids = select(Role.id).where(Role.tenant_id == tenant_id, Role.code.in_(role_codes))
    user_ids = select(UserRole.user_id).where(UserRole.role_id.in_(role_ids))
    return db.scalars(
        select(User).where(User.id.in_(user_ids), User.tenant_id == tenant_id, User.status == "active")
    ).all()


def _tenant_locale(db: Session, tenant_id: UUID) -> str:
    tenant = db.get(Tenant, tenant_id)
    return normalize_locale(tenant.default_locale if tenant else None)


def _pick(en: str, zh: str | None, locale: str) -> str:
    """按收件人语言挑文案（没有中文变体就退回英文原文）。"""
    if not zh:
        return en
    return zh if locale.startswith("zh") else en


def notify_once(
    db: Session,
    tenant_id: UUID,
    recipients: list[User],
    *,
    title: str,
    body: str,
    href: str,
    level: str,
    title_i18n: dict | None = None,
    body_i18n: dict | None = None,
) -> None:
    """Create at most one notification per user + href + title per day.

    ``title_i18n`` / ``body_i18n`` 给 ``{"en": ..., "zh": ...}`` 时，按**每个收件人
    自己的语言**落库 —— 系统生成的文案（过期预警、任务提醒…）不该在英文界面里
    直接冒中文。没有传就原样落 ``title`` / ``body``（老调用方不受影响）。
    """
    # created_at is server-generated UTC (func.now()); window must be UTC too,
    # otherwise dedupe breaks when local date != UTC date
    today_start = datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time(), tzinfo=timezone.utc)
    targets: list[UUID | None] = [u.id for u in recipients] or [None]
    localized = bool(title_i18n or body_i18n)
    fallback_locale = _tenant_locale(db, tenant_id) if localized else "en"
    for uid in targets:
        locale = (user_locale(db, uid) if uid is not None else fallback_locale) if localized else "en"
        t = _pick(title, (title_i18n or {}).get("zh"), locale)
        b = _pick(body, (body_i18n or {}).get("zh"), locale)
        q = select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.href == href,
            Notification.title == t,
            Notification.created_at >= today_start,
        )
        q = q.where(Notification.user_id == uid) if uid else q.where(Notification.user_id.is_(None))
        if db.scalar(q):
            continue
        db.add(Notification(tenant_id=tenant_id, user_id=uid, title=t, body=b, level=level, href=href))


def notify_roles_once(
    db: Session,
    tenant_id: UUID,
    role_codes: tuple[str, ...],
    *,
    title: str,
    body: str,
    href: str,
    level: str,
    title_i18n: dict | None = None,
    body_i18n: dict | None = None,
) -> None:
    notify_once(
        db,
        tenant_id,
        role_recipients(db, tenant_id, role_codes),
        title=title,
        body=body,
        href=href,
        level=level,
        title_i18n=title_i18n,
        body_i18n=body_i18n,
    )
