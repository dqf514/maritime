"""服务端 UI 文案 —— 后端生成的业务文案按用户语言取回。

前端的 i18n 目录（``ui_messages``）只管得到前端的文案；**后端生成的文案**
（航次收尾清单、完成航次时自动生成的跟进任务…）不经过前端 ``t()``，只能由
服务端按 locale 取回再返回/落库，否则英文界面里会直接漏出中文。

取文案的键与前端共用同一张目录表（``app/seed_i18n.py`` 播种），
缺失时调用方自带兜底（中文原文），不会因为目录未播种而报错。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant, User
from app.models_i18n import TenantI18nSettings, UiMessage

if TYPE_CHECKING:  # pragma: no cover - 仅类型
    from app.security import AuthContext

SUPPORTED_LOCALES = {"en", "zh-CN"}


def normalize_locale(raw: str | None) -> str:
    """把 Accept-Language / 用户设置 / 显式参数归一成 ``en`` / ``zh-CN``。"""
    if not raw:
        return "en"
    # Accept-Language 形如 "zh-CN,zh;q=0.9,en;q=0.8"
    primary = raw.split(",")[0].strip().split(";")[0].strip()
    if primary.lower() in ("zh", "zh-cn", "zh_cn", "zh-hans"):
        return "zh-CN"
    if primary.lower().startswith("en"):
        return "en"
    if primary in SUPPORTED_LOCALES:
        return primary
    return "en"


def ensure_tenant_i18n(db: Session, tenant_id) -> TenantI18nSettings:
    """租户 i18n 设置（不存在则按租户默认语言建一条）。"""
    row = db.scalar(
        select(TenantI18nSettings).where(TenantI18nSettings.tenant_id == tenant_id)
    )
    if not row:
        tenant = db.get(Tenant, tenant_id)
        row = TenantI18nSettings(
            tenant_id=tenant_id,
            default_locale=(tenant.default_locale if tenant else "en") or "en",
            allowed_locales=["en", "zh-CN"],
            allow_user_override=True,
        )
        db.add(row)
        db.flush()
    return row


def resolve_user_locale(
    db: Session,
    *,
    auth: "AuthContext | None" = None,
    explicit: str | None = None,
    accept_language: str | None = None,
) -> str:
    """解析当前请求的语言：显式参数 > 用户个人设置 > 租户默认 > Accept-Language。"""
    if explicit:
        return normalize_locale(explicit)
    if auth is not None:
        # locale 字段可能是 "en|workspace_id"
        base = (auth.user.locale or "").split("|")[0].strip()
        if base:
            return normalize_locale(base)
        settings = ensure_tenant_i18n(db, auth.tenant_id)
        return normalize_locale(settings.default_locale)
    return normalize_locale(accept_language)


def user_locale(db: Session, user_id) -> str:
    """某个用户的个人语言（未设置 → en）。后台任务用它决定落库文案的语言。"""
    if not user_id:
        return "en"
    row = db.get(User, user_id)
    base = (row.locale or "").split("|")[0].strip() if row is not None else ""
    return normalize_locale(base)


def messages_for(db: Session, keys: list[str], locale: str = "en") -> dict[str, str]:
    """按 locale 取一批文案；locale 缺失时回退 ``en``，都没有则不返回该键。"""
    out: dict[str, str] = {}
    if not keys:
        return out
    rows = db.scalars(
        select(UiMessage).where(UiMessage.msg_key.in_(keys), UiMessage.locale == "en")
    ).all()
    out = {r.msg_key: r.text for r in rows}
    locale = normalize_locale(locale)
    if locale != "en":
        loc_rows = db.scalars(
            select(UiMessage).where(UiMessage.msg_key.in_(keys), UiMessage.locale == locale)
        ).all()
        out.update({r.msg_key: r.text for r in loc_rows})
    return out


def fill(template: str, vars: dict | None) -> str:
    """把 ``{name}`` 占位符替换掉（缺失的占位符原样保留，不用 str.format）。"""
    if not vars:
        return template
    out = template
    for k, v in vars.items():
        out = out.replace("{" + str(k) + "}", str(v))
    return out
