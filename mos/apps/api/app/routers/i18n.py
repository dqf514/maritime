"""i18n & terminology APIs — platform / tenant / user / public bundle."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tenant, User
from app.models_i18n import (
    Language,
    TenantI18nSettings,
    TenantTerminologyOverride,
    TerminologyTerm,
    UiMessage,
)
from app.security import AuthContext, get_current_auth, get_current_auth_optional, require_auth

router = APIRouter(tags=["i18n & Terminology"])

SUPPORTED = {"en", "zh-CN"}


def require_roles(*codes: str):
    def _dep(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if not any(c in auth.roles for c in codes):
            raise HTTPException(status_code=403, detail={"code": "ROLE_REQUIRED", "roles": list(codes)})
        return auth

    return _dep


def _now() -> datetime:
    return datetime.now().astimezone()


def normalize_locale(raw: str | None) -> str:
    if not raw:
        return "en"
    # Accept-Language may be "zh-CN,zh;q=0.9,en;q=0.8"
    primary = raw.split(",")[0].strip().split(";")[0].strip()
    if primary.lower() in ("zh", "zh-cn", "zh_cn", "zh-hans"):
        return "zh-CN"
    if primary.lower().startswith("en"):
        return "en"
    if primary in SUPPORTED:
        return primary
    return "en"


def ensure_tenant_i18n(db: Session, tenant_id) -> TenantI18nSettings:
    row = db.scalar(select(TenantI18nSettings).where(TenantI18nSettings.tenant_id == tenant_id))
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
    auth: AuthContext | None,
    explicit: str | None,
    accept_language: str | None,
) -> str:
    if explicit:
        return normalize_locale(explicit)
    if auth:
        # locale field may be "en|workspace_id"
        base = (auth.user.locale or "").split("|")[0].strip()
        if base:
            return normalize_locale(base)
        settings = ensure_tenant_i18n(db, auth.tenant_id)
        return normalize_locale(settings.default_locale)
    return normalize_locale(accept_language)


def build_message_bundle(db: Session, locale: str) -> dict[str, str]:
    locale = normalize_locale(locale)
    # English base
    en_rows = db.scalars(select(UiMessage).where(UiMessage.locale == "en")).all()
    out = {r.msg_key: r.text for r in en_rows}
    if locale != "en":
        loc_rows = db.scalars(select(UiMessage).where(UiMessage.locale == locale)).all()
        for r in loc_rows:
            out[r.msg_key] = r.text
    return out


def build_terms_bundle(db: Session, locale: str, tenant_id=None) -> dict[str, dict[str, Any]]:
    locale = normalize_locale(locale)
    terms = db.scalars(select(TerminologyTerm).where(TerminologyTerm.status == "approved")).all()
    out: dict[str, dict[str, Any]] = {}
    for t in terms:
        label = t.zh_cn if locale == "zh-CN" else t.en
        definition = t.definition_zh_cn if locale == "zh-CN" else t.definition_en
        out[t.term_key] = {
            "key": t.term_key,
            "label": label,
            "definition": definition,
            "category": t.category,
            "en": t.en,
            "zh_cn": t.zh_cn,
        }
    if tenant_id:
        overrides = db.scalars(
            select(TenantTerminologyOverride).where(
                TenantTerminologyOverride.tenant_id == tenant_id,
                TenantTerminologyOverride.status == "approved",
                TenantTerminologyOverride.locale == locale,
            )
        ).all()
        for o in overrides:
            if o.term_key in out:
                out[o.term_key]["label"] = o.label
                if o.definition:
                    out[o.term_key]["definition"] = o.definition
                out[o.term_key]["overridden"] = True
    return out


# —— Public / resolved bundle ——
@router.get("/i18n/languages")
def list_languages(db: Session = Depends(get_db)):
    rows = db.scalars(select(Language).where(Language.enabled.is_(True)).order_by(Language.sort_order)).all()
    return [
        {
            "code": r.code,
            "name": r.name,
            "native_name": r.native_name,
            "is_default": r.is_default,
        }
        for r in rows
    ]


@router.get("/i18n/bundle")
def get_bundle(
    locale: str | None = None,
    tenant_code: str | None = None,
    accept_language: str | None = Header(default=None, alias="Accept-Language"),
    auth: AuthContext | None = Depends(get_current_auth_optional),
    db: Session = Depends(get_db),
):
    loc = resolve_user_locale(db, auth=auth, explicit=locale, accept_language=accept_language)
    tenant_id = auth.tenant_id if auth else None
    if not tenant_id and tenant_code:
        t = db.scalar(select(Tenant).where(Tenant.code == tenant_code))
        tenant_id = t.id if t else None
    allowed = ["en", "zh-CN"]
    default_locale = "en"
    allow_user = True
    if tenant_id:
        s = ensure_tenant_i18n(db, tenant_id)
        allowed = s.allowed_locales or allowed
        default_locale = s.default_locale
        allow_user = s.allow_user_override
        if loc not in allowed:
            loc = normalize_locale(default_locale)
    db.commit()
    return {
        "locale": loc,
        "default_locale": default_locale,
        "allowed_locales": allowed,
        "allow_user_override": allow_user,
        "messages": build_message_bundle(db, loc),
        "terms": build_terms_bundle(db, loc, tenant_id),
        "languages": list_languages(db),
    }


class LocaleIn(BaseModel):
    locale: str


@router.put("/me/locale")
def set_my_locale(body: LocaleIn, auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    loc = normalize_locale(body.locale)
    settings = ensure_tenant_i18n(db, auth.tenant_id)
    if not settings.allow_user_override:
        raise HTTPException(403, detail={"code": "LOCALE_LOCKED", "message": "Tenant disallows user language override"})
    if loc not in (settings.allowed_locales or ["en", "zh-CN"]):
        raise HTTPException(400, detail={"code": "LOCALE_NOT_ALLOWED"})
    user = db.get(User, auth.user_id)
    assert user
    # Preserve workspace preference suffix
    parts = (user.locale or loc).split("|")
    suffix = parts[1] if len(parts) > 1 else ""
    user.locale = f"{loc}|{suffix}" if suffix else loc
    db.commit()
    return {"locale": loc}


# —— Tenant admin ——
class TenantI18nIn(BaseModel):
    default_locale: str | None = None
    allowed_locales: list[str] | None = None
    allow_user_override: bool | None = None


@router.get("/admin/i18n/settings")
def get_tenant_i18n(auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    s = ensure_tenant_i18n(db, auth.tenant_id)
    db.commit()
    return {
        "default_locale": s.default_locale,
        "allowed_locales": s.allowed_locales or ["en", "zh-CN"],
        "allow_user_override": s.allow_user_override,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


@router.put("/admin/i18n/settings")
def put_tenant_i18n(
    body: TenantI18nIn,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    s = ensure_tenant_i18n(db, auth.tenant_id)
    if body.default_locale is not None:
        s.default_locale = normalize_locale(body.default_locale)
    if body.allowed_locales is not None:
        s.allowed_locales = [normalize_locale(x) for x in body.allowed_locales]
    if body.allow_user_override is not None:
        s.allow_user_override = body.allow_user_override
    s.updated_at = _now()
    tenant = db.get(Tenant, auth.tenant_id)
    if tenant:
        tenant.default_locale = s.default_locale
    db.commit()
    return get_tenant_i18n(auth, db)


class TermOverrideIn(BaseModel):
    term_key: str
    locale: str = "en"
    label: str
    definition: str | None = None


@router.get("/admin/i18n/terminology")
def list_tenant_terms(
    q: str = "",
    locale: str = "en",
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    loc = normalize_locale(locale)
    terms = build_terms_bundle(db, loc, auth.tenant_id)
    items = list(terms.values())
    if q:
        ql = q.lower()
        items = [t for t in items if ql in t["label"].lower() or ql in t["key"].lower() or ql in (t.get("en") or "").lower()]
    return {"locale": loc, "count": len(items), "items": items[:200]}


@router.put("/admin/i18n/terminology/overrides")
def upsert_term_override(
    body: TermOverrideIn,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    loc = normalize_locale(body.locale)
    base = db.scalar(select(TerminologyTerm).where(TerminologyTerm.term_key == body.term_key))
    if not base:
        raise HTTPException(404, "Unknown term_key")
    row = db.scalar(
        select(TenantTerminologyOverride).where(
            TenantTerminologyOverride.tenant_id == auth.tenant_id,
            TenantTerminologyOverride.term_key == body.term_key,
            TenantTerminologyOverride.locale == loc,
        )
    )
    if not row:
        row = TenantTerminologyOverride(
            tenant_id=auth.tenant_id,
            term_key=body.term_key,
            locale=loc,
            label=body.label,
            definition=body.definition,
            status="approved",
        )
        db.add(row)
    else:
        row.label = body.label
        row.definition = body.definition
        row.status = "approved"
        row.updated_at = _now()
    db.commit()
    return {"ok": True, "term_key": body.term_key, "locale": loc}


# —— Platform admin ——
class UiMessageIn(BaseModel):
    msg_key: str
    locale: str
    text: str
    namespace: str = "app"


class TermIn(BaseModel):
    term_key: str
    category: str = "general"
    en: str
    zh_cn: str
    definition_en: str | None = None
    definition_zh_cn: str | None = None
    aliases: list[str] = Field(default_factory=list)
    status: str = "approved"


@router.get("/platform/i18n/overview")
def platform_i18n_overview(
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    langs = db.scalars(select(Language).order_by(Language.sort_order)).all()
    msg_count = len(db.scalars(select(UiMessage.msg_key).where(UiMessage.locale == "en")).all())
    term_count = len(db.scalars(select(TerminologyTerm)).all())
    return {
        "languages": [
            {
                "code": l.code,
                "name": l.name,
                "native_name": l.native_name,
                "enabled": l.enabled,
                "is_default": l.is_default,
            }
            for l in langs
        ],
        "ui_message_keys": msg_count,
        "terminology_terms": term_count,
        "target_terminology": 500,
    }


@router.get("/platform/i18n/messages")
def platform_list_messages(
    locale: str = "en",
    namespace: str | None = None,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    loc = normalize_locale(locale)
    q = select(UiMessage).where(UiMessage.locale == loc)
    if namespace:
        q = q.where(UiMessage.namespace == namespace)
    rows = db.scalars(q.order_by(UiMessage.msg_key)).all()
    return [{"key": r.msg_key, "locale": r.locale, "text": r.text, "namespace": r.namespace} for r in rows]


@router.put("/platform/i18n/messages")
def platform_upsert_message(
    body: UiMessageIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    loc = normalize_locale(body.locale)
    row = db.scalar(select(UiMessage).where(UiMessage.msg_key == body.msg_key, UiMessage.locale == loc))
    if not row:
        row = UiMessage(msg_key=body.msg_key, locale=loc, text=body.text, namespace=body.namespace)
        db.add(row)
    else:
        row.text = body.text
        row.namespace = body.namespace
        row.updated_at = _now()
    db.commit()
    return {"ok": True}


@router.get("/platform/i18n/terminology")
def platform_list_terms(
    q: str = "",
    category: str | None = None,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    query = select(TerminologyTerm)
    if category:
        query = query.where(TerminologyTerm.category == category)
    rows = db.scalars(query.order_by(TerminologyTerm.term_key)).all()
    items = [
        {
            "term_key": r.term_key,
            "category": r.category,
            "en": r.en,
            "zh_cn": r.zh_cn,
            "definition_en": r.definition_en,
            "definition_zh_cn": r.definition_zh_cn,
            "status": r.status,
        }
        for r in rows
    ]
    if q:
        ql = q.lower()
        items = [t for t in items if ql in t["en"].lower() or ql in t["zh_cn"].lower() or ql in t["term_key"].lower()]
    return {"count": len(items), "items": items}


@router.put("/platform/i18n/terminology")
def platform_upsert_term(
    body: TermIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = db.scalar(select(TerminologyTerm).where(TerminologyTerm.term_key == body.term_key))
    data = body.model_dump()
    if not row:
        db.add(TerminologyTerm(**data))
    else:
        for k, v in data.items():
            setattr(row, k, v)
        row.updated_at = _now()
    db.commit()
    return {"ok": True, "term_key": body.term_key}


@router.patch("/platform/i18n/languages/{code}")
def platform_toggle_language(
    code: str,
    enabled: bool = Query(...),
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = db.get(Language, code)
    if not row:
        raise HTTPException(404, "Language not found")
    if row.is_default and not enabled:
        raise HTTPException(400, "Cannot disable default language")
    row.enabled = enabled
    db.commit()
    return {"code": code, "enabled": enabled}
