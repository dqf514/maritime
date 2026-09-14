"""SaaS platform (developer) + tenant billing / org / workflow APIs."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tenant, TenantModuleLicense
from app.models_saas import (
    OrgUnit,
    PaymentOrder,
    PaymentProvider,
    PlatformAiEndpoint,
    PlatformBranding,
    SaaSPlan,
    TenantCompanyProfile,
    TenantSubscription,
    UsageMeterDef,
    UsagePack,
    WorkflowDefinition,
    WorkflowInstance,
    FeaturePermission,
    UserOrgMembership,
)
from app.models import User
from app.routers.admin_platform import require_roles
from app.security import AuthContext, get_current_auth
from app.services.recycle import soft_delete
from app.services.saas_engine import (
    FEATURE_CATALOG,
    advance_workflow,
    consume_usage,
    credit_usage,
    get_or_create_wallet,
    start_workflow,
)

router = APIRouter(tags=["SaaS"])


def _sniff_image_type(raw: bytes) -> str | None:
    """Detect image type from magic bytes (content-based, not extension-based)."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


def _branding_out(row: PlatformBranding) -> dict:
    return {
        "product_name": row.product_name,
        "tagline": row.tagline,
        "logo_url": row.logo_url,
        "icon_url": row.icon_url,
        "favicon_url": row.favicon_url,
        "primary_color": row.primary_color,
        "hero_title": row.hero_title,
        "hero_subtitle": row.hero_subtitle,
        "meta": row.meta or {},
    }


def _ensure_branding(db: Session) -> PlatformBranding:
    row = db.scalar(select(PlatformBranding).limit(1))
    if not row:
        row = PlatformBranding()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.get("/public/branding")
def public_branding(db: Session = Depends(get_db)):
    """Unauthenticated — product portal / login shell."""
    return _branding_out(_ensure_branding(db))


class BrandingIn(BaseModel):
    product_name: str | None = None
    tagline: str | None = None
    logo_url: str | None = None
    icon_url: str | None = None
    favicon_url: str | None = None
    primary_color: str | None = None
    hero_title: str | None = None
    hero_subtitle: str | None = None


@router.get("/platform/branding")
def get_platform_branding(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    return _branding_out(_ensure_branding(db))


@router.put("/platform/branding")
def put_platform_branding(
    body: BrandingIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = _ensure_branding(db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _branding_out(row)


@router.post("/platform/branding/reset")
def reset_platform_branding(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    row = _ensure_branding(db)
    row.product_name = "VoyageOS"
    row.tagline = "Maritime commercial operating system"
    row.logo_url = "/branding/logo.svg"
    row.icon_url = "/branding/mark.svg"
    row.favicon_url = "/branding/mark.svg"
    row.primary_color = "#1A9B96"
    row.hero_title = "One OS for the commercial voyage lifecycle"
    row.hero_subtitle = (
        "From estimate and fixture to operations, laytime, finance and twin — with SaaS control plane built in."
    )
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _branding_out(row)


@router.post("/platform/branding/upload")
async def upload_platform_branding_asset(
    kind: str = "logo",
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    """Upload logo / icon / favicon; stored under /uploads/branding and URL written to branding."""
    _ = auth
    if kind not in {"logo", "icon", "favicon"}:
        raise HTTPException(400, detail={"code": "INVALID_KIND", "allowed": ["logo", "icon", "favicon"]})
    raw = await file.read()
    if not raw:
        raise HTTPException(400, detail={"code": "EMPTY_FILE"})
    if len(raw) > 2_500_000:
        raise HTTPException(400, detail={"code": "FILE_TOO_LARGE", "max_bytes": 2500000})
    name = (file.filename or "asset").lower()
    ext = Path(name).suffix.lower()
    # Raster formats only — SVG is scriptable markup and must never be served as an image
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(400, detail={"code": "UNSUPPORTED_TYPE", "ext": ext})
    sniffed = _sniff_image_type(raw)
    expected = "jpg" if ext == ".jpeg" else ext.lstrip(".")
    if sniffed != expected:
        raise HTTPException(400, detail={"code": "INVALID_CONTENT", "message": "File content does not match an allowed image type"})
    upload_dir = Path(__file__).resolve().parent.parent.parent / "uploads" / "branding"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"{kind}{ext}"
    dest = upload_dir / dest_name
    dest.write_bytes(raw)
    # Cache-bust so portal picks up new file immediately
    public_url = f"/uploads/branding/{dest_name}?v={int(datetime.now(timezone.utc).timestamp())}"
    # Absolute URL for cross-origin Next.js (API host)
    from app.config import get_settings

    base = get_settings().api_public_base.rstrip("/")
    absolute = f"{base}{public_url}"
    row = _ensure_branding(db)
    if kind == "logo":
        row.logo_url = absolute
    elif kind == "icon":
        row.icon_url = absolute
    else:
        row.favicon_url = absolute
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _branding_out(row)


# ───────── Developer / Platform catalog ─────────
class PlanIn(BaseModel):
    code: str
    name: str
    description: str | None = None
    billing_period: str = "monthly"
    price_amount: float
    currency: str = "USD"
    included_modules: dict = Field(default_factory=dict)
    included_quotas: dict = Field(default_factory=dict)
    seat_limit: int | None = None


@router.get("/platform/saas/plans")
def list_plans(auth: AuthContext = Depends(require_roles("platform_admin", "tenant_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(SaaSPlan).where(SaaSPlan.status == "active").order_by(SaaSPlan.price_amount)).all()
    return [_plan_out(r) for r in rows]


@router.post("/platform/saas/plans")
def create_plan(body: PlanIn, auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    if db.scalar(select(SaaSPlan).where(SaaSPlan.code == body.code)):
        raise HTTPException(409, "Plan code exists")
    row = SaaSPlan(**body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _plan_out(row)


def _plan_out(r: SaaSPlan) -> dict:
    return {
        "id": str(r.id),
        "code": r.code,
        "name": r.name,
        "description": r.description,
        "billing_period": r.billing_period,
        "price_amount": float(r.price_amount),
        "currency": r.currency,
        "included_modules": r.included_modules or {},
        "included_quotas": r.included_quotas or {},
        "seat_limit": r.seat_limit,
        "status": r.status,
    }


@router.get("/platform/saas/meters")
def list_meters(auth: AuthContext = Depends(require_roles("platform_admin", "tenant_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(UsageMeterDef)).all()
    return [
        {
            "code": r.code,
            "name": r.name,
            "unit": r.unit,
            "overage_price": float(r.overage_price),
            "currency": r.currency,
        }
        for r in rows
    ]


@router.get("/platform/saas/packs")
def list_packs(auth: AuthContext = Depends(require_roles("platform_admin", "tenant_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(UsagePack).where(UsagePack.status == "active")).all()
    return [
        {
            "id": str(r.id),
            "code": r.code,
            "name": r.name,
            "meter_code": r.meter_code,
            "quantity": float(r.quantity),
            "price_amount": float(r.price_amount),
            "currency": r.currency,
        }
        for r in rows
    ]


class PackIn(BaseModel):
    code: str
    name: str
    meter_code: str
    quantity: float
    price_amount: float
    currency: str = "USD"


@router.post("/platform/saas/packs")
def create_pack(body: PackIn, auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    row = UsagePack(**body.model_dump())
    db.add(row)
    db.commit()
    return {"id": str(row.id), "code": row.code}


@router.get("/platform/saas/ai-endpoints")
def list_ai_endpoints(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(PlatformAiEndpoint)).all()
    return [
        {
            "id": str(r.id),
            "code": r.code,
            "name": r.name,
            "provider_type": r.provider_type,
            "model_default": r.model_default,
            "status": r.status,
            "meter_code": r.meter_code,
            "tokens_per_call_est": r.tokens_per_call_est,
        }
        for r in rows
    ]


class AiEndpointIn(BaseModel):
    code: str
    name: str
    provider_type: str
    base_url: str | None = None
    model_default: str | None = None
    meter_code: str = "ai.tokens"
    tokens_per_call_est: int = 1000


@router.post("/platform/saas/ai-endpoints")
def create_ai_endpoint(body: AiEndpointIn, auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    row = PlatformAiEndpoint(**body.model_dump(), status="active")
    db.add(row)
    db.commit()
    return {"id": str(row.id), "code": row.code}


@router.get("/platform/saas/payments/providers")
def list_payment_providers(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(PaymentProvider)).all()
    return [{"code": r.code, "name": r.name, "status": r.status} for r in rows]


@router.get("/platform/saas/overview")
def platform_saas_overview(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    subs = db.scalars(select(TenantSubscription)).all()
    orders = db.scalars(select(PaymentOrder).where(PaymentOrder.status == "paid")).all()
    return {
        "active_subscriptions": sum(1 for s in subs if s.status in {"active", "trialing"}),
        "mrr_estimate": sum(float(db.get(SaaSPlan, s.plan_id).price_amount) for s in subs if s.status == "active" and db.get(SaaSPlan, s.plan_id)),
        "paid_orders": len(orders),
        "paid_volume": sum(float(o.amount) for o in orders),
    }


def _raise_self_checkout_disabled() -> None:
    raise HTTPException(
        status_code=403,
        detail={
            "code": "SELF_CHECKOUT_DISABLED",
            "message": "Online checkout is not enabled. Ask the platform administrator to assign a plan or credit usage.",
        },
    )


def _apply_plan_to_tenant(
    db: Session,
    *,
    tenant_id: UUID,
    plan: SaaSPlan,
    user_id: UUID | None,
    grant_quotas: bool = True,
    note: str | None = None,
) -> TenantSubscription:
    """Activate/replace subscription and sync module licenses (+ optional included quotas)."""
    for old in db.scalars(
        select(TenantSubscription).where(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status.in_(["active", "trialing"]),
        )
    ).all():
        old.status = "cancelled"
    sub = TenantSubscription(
        tenant_id=tenant_id,
        plan_id=plan.id,
        status="active",
        started_on=date.today(),
        current_period_end=date.today() + timedelta(days=365 if plan.billing_period == "yearly" else 30),
        auto_renew=True,
        meta={"assigned_by": "platform", "note": note},
    )
    db.add(sub)
    db.flush()
    now = datetime.now().astimezone()
    for mod, enabled in (plan.included_modules or {}).items():
        if not enabled:
            continue
        lic = db.scalar(
            select(TenantModuleLicense).where(
                TenantModuleLicense.tenant_id == tenant_id,
                TenantModuleLicense.module_code == mod,
            )
        )
        if not lic:
            db.add(
                TenantModuleLicense(
                    tenant_id=tenant_id,
                    module_code=mod,
                    status="active",
                    activated_at=now,
                    features={},
                )
            )
        else:
            lic.status = "active"
    if grant_quotas:
        for meter, qty in (plan.included_quotas or {}).items():
            credit_usage(
                db,
                tenant_id=tenant_id,
                meter_code=meter,
                quantity=Decimal(str(qty)),
                ref_type="subscription",
                ref_id=str(sub.id),
                note=note or f"Plan {plan.code} included quota",
                user_id=user_id,
            )
    return sub


def _credit_pack_to_tenant(
    db: Session,
    *,
    tenant_id: UUID,
    pack: UsagePack,
    user_id: UUID | None,
    note: str | None = None,
) -> dict:
    credit_usage(
        db,
        tenant_id=tenant_id,
        meter_code=pack.meter_code,
        quantity=Decimal(str(pack.quantity)),
        ref_type="usage_pack",
        ref_id=str(pack.id),
        note=note or f"Platform credit {pack.code}",
        user_id=user_id,
    )
    return {"meter_code": pack.meter_code, "quantity": float(pack.quantity), "pack_code": pack.code}


# ───────── Platform: assign subscription / credit (until online payment) ─────────
@router.get("/platform/saas/subscriptions")
def list_platform_subscriptions(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(TenantSubscription).order_by(TenantSubscription.created_at.desc()).limit(200)).all()
    out = []
    for s in rows:
        tenant = db.get(Tenant, s.tenant_id)
        plan = db.get(SaaSPlan, s.plan_id)
        out.append(
            {
                "id": str(s.id),
                "tenant_id": str(s.tenant_id),
                "tenant_code": tenant.code if tenant else None,
                "tenant_name": tenant.name if tenant else None,
                "status": s.status,
                "started_on": s.started_on.isoformat() if s.started_on else None,
                "current_period_end": s.current_period_end.isoformat() if s.current_period_end else None,
                "plan": _plan_out(plan) if plan else None,
            }
        )
    return out


class PlatformAssignPlanIn(BaseModel):
    plan_code: str
    grant_quotas: bool = True
    note: str | None = None


@router.post("/platform/saas/tenants/{tenant_id}/assign-plan")
def platform_assign_plan(
    tenant_id: UUID,
    body: PlatformAssignPlanIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    plan = db.scalar(select(SaaSPlan).where(SaaSPlan.code == body.plan_code, SaaSPlan.status == "active"))
    if not plan:
        raise HTTPException(404, "Plan not found")
    # Record a platform-fulfilled order for audit
    order = PaymentOrder(
        tenant_id=tenant_id,
        provider_code="manual",
        purpose="subscription",
        amount=plan.price_amount,
        currency=plan.currency,
        status="paid",
        ref_type="plan",
        ref_id=str(plan.id),
        paid_at=datetime.now().astimezone(),
        meta={"plan_code": plan.code, "fulfilled_by": "platform_admin", "note": body.note},
    )
    db.add(order)
    sub = _apply_plan_to_tenant(
        db,
        tenant_id=tenant_id,
        plan=plan,
        user_id=auth.user_id,
        grant_quotas=body.grant_quotas,
        note=body.note or f"Platform assigned {plan.code}",
    )
    db.commit()
    return {
        "ok": True,
        "subscription_id": str(sub.id),
        "tenant_code": tenant.code,
        "plan_code": plan.code,
        "status": sub.status,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
    }


class PlatformCreditPackIn(BaseModel):
    pack_code: str
    note: str | None = None


@router.post("/platform/saas/tenants/{tenant_id}/credit-pack")
def platform_credit_pack(
    tenant_id: UUID,
    body: PlatformCreditPackIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    pack = db.scalar(select(UsagePack).where(UsagePack.code == body.pack_code, UsagePack.status == "active"))
    if not pack:
        raise HTTPException(404, "Pack not found")
    order = PaymentOrder(
        tenant_id=tenant_id,
        provider_code="manual",
        purpose="usage_pack",
        amount=pack.price_amount,
        currency=pack.currency,
        status="paid",
        ref_type="usage_pack",
        ref_id=str(pack.id),
        paid_at=datetime.now().astimezone(),
        meta={"pack_code": pack.code, "fulfilled_by": "platform_admin", "note": body.note},
    )
    db.add(order)
    credited = _credit_pack_to_tenant(
        db,
        tenant_id=tenant_id,
        pack=pack,
        user_id=auth.user_id,
        note=body.note or f"Platform credit {pack.code}",
    )
    db.commit()
    return {"ok": True, "tenant_code": tenant.code, **credited}


@router.post("/platform/saas/tenants/{tenant_id}/cancel-subscription")
def platform_cancel_subscription(
    tenant_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    cancelled = 0
    for sub in db.scalars(
        select(TenantSubscription).where(
            TenantSubscription.tenant_id == tenant_id,
            TenantSubscription.status.in_(["active", "trialing"]),
        )
    ).all():
        sub.status = "cancelled"
        cancelled += 1
    db.commit()
    return {"ok": True, "tenant_code": tenant.code, "cancelled": cancelled}


# ───────── Tenant subscription & wallet (read + future checkout) ─────────
@router.get("/billing/subscription")
def my_subscription(auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    sub = db.scalar(
        select(TenantSubscription)
        .where(TenantSubscription.tenant_id == auth.tenant_id)
        .order_by(TenantSubscription.created_at.desc())
        .limit(1)
    )
    if not sub:
        return {"status": "none", "plan": None, "self_checkout": False}
    plan = db.get(SaaSPlan, sub.plan_id)
    return {
        "id": str(sub.id),
        "status": sub.status,
        "started_on": sub.started_on.isoformat(),
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "auto_renew": sub.auto_renew,
        "plan": _plan_out(plan) if plan else None,
        "self_checkout": False,
    }


class SubscribeIn(BaseModel):
    plan_code: str
    provider_code: str = "manual"


@router.post("/billing/subscribe")
def subscribe(body: SubscribeIn, auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    """Reserved for future online payment. Currently platform assigns plans."""
    _ = body, auth, db
    _raise_self_checkout_disabled()


@router.post("/billing/orders/{order_id}/confirm-paid")
def confirm_paid(order_id: UUID, auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    """Platform-only payment capture until provider webhooks are wired."""
    order = db.get(PaymentOrder, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status == "paid":
        return {"status": "paid", "order_id": str(order.id)}
    order.status = "paid"
    order.paid_at = datetime.now().astimezone()
    if order.purpose == "subscription" and order.ref_id:
        plan = db.get(SaaSPlan, UUID(order.ref_id))
        if plan:
            _apply_plan_to_tenant(
                db,
                tenant_id=order.tenant_id,
                plan=plan,
                user_id=auth.user_id,
                grant_quotas=True,
                note=f"Order {order.id} paid",
            )
    elif order.purpose == "usage_pack" and order.ref_id:
        pack = db.get(UsagePack, UUID(order.ref_id))
        if pack:
            _credit_pack_to_tenant(db, tenant_id=order.tenant_id, pack=pack, user_id=auth.user_id)
    db.commit()
    return {"status": "paid", "order_id": str(order.id)}


class TopUpIn(BaseModel):
    pack_code: str
    provider_code: str = "manual"


@router.post("/billing/topup")
def topup(body: TopUpIn, auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    """Reserved for future online payment. Currently platform credits packs."""
    _ = body, auth, db
    _raise_self_checkout_disabled()



@router.get("/billing/wallet")
def wallet(auth: AuthContext = Depends(require_roles("tenant_admin", "chartering", "operations", "finance")), db: Session = Depends(get_db)):
    from app.models_saas import TenantWallet

    rows = db.scalars(select(TenantWallet).where(TenantWallet.tenant_id == auth.tenant_id)).all()
    return [{"meter_code": r.meter_code, "balance": float(r.balance)} for r in rows]


@router.get("/billing/usage")
def usage_ledger(auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    from app.models_saas import UsageLedger

    rows = db.scalars(
        select(UsageLedger).where(UsageLedger.tenant_id == auth.tenant_id).order_by(UsageLedger.created_at.desc()).limit(100)
    ).all()
    return [
        {
            "meter_code": r.meter_code,
            "quantity": float(r.quantity),
            "direction": r.direction,
            "note": r.note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/billing/ai/invoke-demo")
def invoke_ai_demo(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    """Demo metered AI call — deducts ai.tokens like Feishu-style packs."""
    endpoint = db.scalar(select(PlatformAiEndpoint).where(PlatformAiEndpoint.status == "active").limit(1))
    tokens = endpoint.tokens_per_call_est if endpoint else 1000
    wallet = consume_usage(
        db,
        tenant_id=auth.tenant_id,
        meter_code="ai.tokens",
        quantity=Decimal(str(tokens)),
        ref_type="ai_invoke",
        ref_id=endpoint.code if endpoint else "demo",
        note="Demo AI skill invoke",
        user_id=auth.user_id,
    )
    db.commit()
    return {
        "ok": True,
        "endpoint": endpoint.code if endpoint else "local-demo",
        "tokens_charged": tokens,
        "balance": float(wallet.balance),
        "result": {"summary": "Stub AI response — metered successfully"},
    }


# ───────── Company profile / org / permissions ─────────
class CompanyProfileIn(BaseModel):
    legal_name: str | None = None
    display_name: str | None = None
    logo_url: str | None = None
    website: str | None = None
    tax_no: str | None = None
    address: str | None = None
    phone: str | None = None
    brand_primary: str | None = None
    brand_secondary: str | None = None


@router.get("/admin/company-profile")
def get_company_profile(auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    row = db.scalar(select(TenantCompanyProfile).where(TenantCompanyProfile.tenant_id == auth.tenant_id))
    tenant = db.get(Tenant, auth.tenant_id)
    if not row:
        return {
            "legal_name": tenant.name if tenant else None,
            "display_name": tenant.name if tenant else None,
            "logo_url": None,
            "brand_primary": "#1a8a8a",
        }
    return {
        "legal_name": row.legal_name,
        "display_name": row.display_name,
        "logo_url": row.logo_url,
        "website": row.website,
        "tax_no": row.tax_no,
        "address": row.address,
        "phone": row.phone,
        "brand_primary": row.brand_primary,
        "brand_secondary": row.brand_secondary,
    }


@router.put("/admin/company-profile")
def put_company_profile(body: CompanyProfileIn, auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    row = db.scalar(select(TenantCompanyProfile).where(TenantCompanyProfile.tenant_id == auth.tenant_id))
    if not row:
        row = TenantCompanyProfile(tenant_id=auth.tenant_id)
        db.add(row)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    row.updated_at = datetime.now(timezone.utc)
    if body.display_name:
        tenant = db.get(Tenant, auth.tenant_id)
        if tenant:
            tenant.name = body.display_name
    db.commit()
    return {"ok": True}


class OrgUnitIn(BaseModel):
    code: str
    name: str
    parent_id: UUID | None = None
    unit_type: str = "dept"
    manager_user_id: UUID | None = None


@router.get("/admin/org-units")
def list_org_units(auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(OrgUnit).where(OrgUnit.tenant_id == auth.tenant_id, OrgUnit.status != "deleted")
    ).all()
    out = []
    for r in rows:
        member_ids = list(
            db.scalars(
                select(UserOrgMembership.user_id).where(
                    UserOrgMembership.org_unit_id == r.id, UserOrgMembership.is_primary.is_(True)
                )
            ).all()
        )
        manager = db.get(User, r.manager_user_id) if r.manager_user_id else None
        out.append(
            {
                "id": str(r.id),
                "code": r.code,
                "name": r.name,
                "parent_id": str(r.parent_id) if r.parent_id else None,
                "unit_type": r.unit_type,
                "manager_user_id": str(r.manager_user_id) if r.manager_user_id else None,
                "manager_name": manager.full_name if manager else None,
                "status": r.status,
                "member_count": len(member_ids),
            }
        )
    return out


@router.post("/admin/org-units")
def create_org_unit(body: OrgUnitIn, auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    row = OrgUnit(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    db.commit()
    return {"id": str(row.id), "code": row.code}


class OrgUnitUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    unit_type: str | None = None
    parent_id: UUID | None = None
    manager_user_id: UUID | None = None
    status: str | None = None


@router.patch("/admin/org-units/{unit_id}")
def update_org_unit(
    unit_id: UUID,
    body: OrgUnitUpdate,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    row = db.get(OrgUnit, unit_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Org unit not found")
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] == "deleted":
        data.pop("status")
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    return {"id": str(row.id), "code": row.code, "name": row.name, "status": row.status}


@router.delete("/admin/org-units/{unit_id}")
def delete_org_unit(
    unit_id: UUID,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    row = db.get(OrgUnit, unit_id)
    if not row or row.tenant_id != auth.tenant_id or row.status == "deleted":
        raise HTTPException(404, "Org unit not found")
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="org_unit",
        row=row,
        title=f"{row.code} {row.name}",
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.post("/admin/users/{user_id}/org")
def assign_user_org(
    user_id: UUID,
    org_unit_id: UUID,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    """Assign primary org unit (query: org_unit_id). Use PUT with null to clear."""
    return _set_user_org(db, auth, user_id, org_unit_id)


class UserOrgIn(BaseModel):
    org_unit_id: UUID | None = None


@router.put("/admin/users/{user_id}/org")
def put_user_org(
    user_id: UUID,
    body: UserOrgIn,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    return _set_user_org(db, auth, user_id, body.org_unit_id)


def _set_user_org(db: Session, auth: AuthContext, user_id: UUID, org_unit_id: UUID | None) -> dict:
    user = db.get(User, user_id)
    if not user or user.tenant_id != auth.tenant_id or user.status == "deleted":
        raise HTTPException(404, "User not found")
    for m in db.scalars(
        select(UserOrgMembership).where(UserOrgMembership.user_id == user_id, UserOrgMembership.is_primary.is_(True))
    ).all():
        m.is_primary = False
    if org_unit_id:
        unit = db.get(OrgUnit, org_unit_id)
        if not unit or unit.tenant_id != auth.tenant_id or unit.status == "deleted":
            raise HTTPException(404, "Org unit not found")
        existing = db.scalar(
            select(UserOrgMembership).where(UserOrgMembership.user_id == user_id, UserOrgMembership.org_unit_id == org_unit_id)
        )
        if existing:
            existing.is_primary = True
        else:
            db.add(UserOrgMembership(user_id=user_id, org_unit_id=org_unit_id, is_primary=True))
    db.commit()
    return {"ok": True, "org_unit_id": str(org_unit_id) if org_unit_id else None}


@router.get("/admin/org-units/{unit_id}/members")
def list_org_members(
    unit_id: UUID,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    unit = db.get(OrgUnit, unit_id)
    if not unit or unit.tenant_id != auth.tenant_id or unit.status == "deleted":
        raise HTTPException(404, "Org unit not found")
    memberships = db.scalars(
        select(UserOrgMembership).where(UserOrgMembership.org_unit_id == unit_id, UserOrgMembership.is_primary.is_(True))
    ).all()
    out = []
    for m in memberships:
        user = db.get(User, m.user_id)
        if not user or user.status == "deleted":
            continue
        out.append(
            {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "status": user.status,
                "is_manager": str(user.id) == str(unit.manager_user_id) if unit.manager_user_id else False,
            }
        )
    return out


@router.get("/admin/features/catalog")
def feature_catalog(auth: AuthContext = Depends(require_roles("tenant_admin"))):
    _ = auth
    return FEATURE_CATALOG


@router.get("/admin/features/matrix")
def feature_matrix(auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(FeaturePermission).where(FeaturePermission.tenant_id == auth.tenant_id)).all()
    return [{"role_code": r.role_code, "feature_code": r.feature_code, "allowed": r.allowed} for r in rows]


class FeatureSetIn(BaseModel):
    role_code: str
    feature_code: str
    allowed: bool = True


@router.put("/admin/features")
def set_feature(body: FeatureSetIn, auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    row = db.scalar(
        select(FeaturePermission).where(
            FeaturePermission.tenant_id == auth.tenant_id,
            FeaturePermission.role_code == body.role_code,
            FeaturePermission.feature_code == body.feature_code,
        )
    )
    if not row:
        row = FeaturePermission(tenant_id=auth.tenant_id, role_code=body.role_code, feature_code=body.feature_code, allowed=body.allowed)
        db.add(row)
    else:
        row.allowed = body.allowed
    db.commit()
    return {"ok": True}


# ───────── Workflows ─────────
class WorkflowDefIn(BaseModel):
    code: str
    name: str
    entity_type: str
    steps: list[dict] = Field(default_factory=list)
    enabled: bool = True


@router.get("/admin/workflows")
def list_workflows(auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(WorkflowDefinition).where(WorkflowDefinition.tenant_id == auth.tenant_id)).all()
    return [
        {
            "id": str(r.id),
            "code": r.code,
            "name": r.name,
            "entity_type": r.entity_type,
            "steps": r.steps,
            "enabled": r.enabled,
        }
        for r in rows
    ]


@router.post("/admin/workflows")
def upsert_workflow(body: WorkflowDefIn, auth: AuthContext = Depends(require_roles("tenant_admin")), db: Session = Depends(get_db)):
    row = db.scalar(
        select(WorkflowDefinition).where(WorkflowDefinition.tenant_id == auth.tenant_id, WorkflowDefinition.code == body.code)
    )
    if not row:
        row = WorkflowDefinition(
            tenant_id=auth.tenant_id,
            code=body.code,
            name=body.name,
            entity_type=body.entity_type,
            steps={"steps": body.steps},
            enabled=body.enabled,
        )
        db.add(row)
    else:
        row.name = body.name
        row.entity_type = body.entity_type
        row.steps = {"steps": body.steps}
        row.enabled = body.enabled
    db.commit()
    return {"id": str(row.id), "code": row.code, "enabled": row.enabled, "steps": row.steps}


class WorkflowPatchIn(BaseModel):
    name: str | None = None
    entity_type: str | None = None
    steps: list[dict] | None = None
    enabled: bool | None = None


@router.patch("/admin/workflows/{workflow_id}")
def patch_workflow(
    workflow_id: UUID,
    body: WorkflowPatchIn,
    auth: AuthContext = Depends(require_roles("tenant_admin")),
    db: Session = Depends(get_db),
):
    row = db.get(WorkflowDefinition, workflow_id)
    if not row or row.tenant_id != auth.tenant_id:
        raise HTTPException(404, "Workflow not found")
    if body.name is not None:
        row.name = body.name
    if body.entity_type is not None:
        row.entity_type = body.entity_type
    if body.steps is not None:
        row.steps = {"steps": body.steps}
    if body.enabled is not None:
        row.enabled = body.enabled
    db.commit()
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "entity_type": row.entity_type,
        "steps": row.steps,
        "enabled": row.enabled,
    }


@router.get("/workflows/inbox")
def workflow_inbox(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(WorkflowInstance).where(WorkflowInstance.tenant_id == auth.tenant_id, WorkflowInstance.status == "running")
    ).all()
    out = []
    for inst in rows:
        definition = db.get(WorkflowDefinition, inst.definition_id)
        steps = (definition.steps or {}).get("steps", []) if definition else []
        step = steps[inst.current_step] if inst.current_step < len(steps) else None
        if step and step.get("role_code") not in auth.roles and "tenant_admin" not in auth.roles:
            continue
        out.append(
            {
                "id": str(inst.id),
                "entity_type": inst.entity_type,
                "entity_id": str(inst.entity_id),
                "current_step": inst.current_step,
                "step": step,
                "definition": definition.name if definition else None,
            }
        )
    return out


class WorkflowDecisionIn(BaseModel):
    decision: str  # approve|reject
    comment: str | None = None


@router.post("/workflows/{instance_id}/decide")
def workflow_decide(
    instance_id: UUID,
    body: WorkflowDecisionIn,
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    from app.services.saas_engine import assert_feature

    if body.decision not in {"approve", "reject"}:
        raise HTTPException(400, "decision must be approve|reject")
    assert_feature(db, auth.tenant_id, auth.roles, "workflow.approve")
    inst = advance_workflow(
        db,
        instance_id=instance_id,
        tenant_id=auth.tenant_id,
        actor_roles=auth.roles,
        actor_user_id=auth.user_id,
        decision=body.decision,
        comment=body.comment,
    )
    # side effects on entity when fully approved
    if inst.status == "approved":
        _apply_approved_entity(db, inst)
    db.commit()
    return {"id": str(inst.id), "status": inst.status, "current_step": inst.current_step}


def _apply_approved_entity(db: Session, inst: WorkflowInstance) -> None:
    from datetime import timedelta
    from uuid import uuid4

    from app.models_domain import Charter, Invoice, ScheduleBlock, Voyage
    from app.services.state_machine import CHARTER_TRANSITIONS, INVOICE_TRANSITIONS, transition

    if inst.entity_type == "charter":
        row = db.get(Charter, inst.entity_id)
        if row and row.status == "pending_approval":
            row.status = transition("charter", row.status, "active", CHARTER_TRANSITIONS)
            if row.vessel_id:
                vno = f"V-{datetime.now().strftime('%Y%m%d')}-{str(uuid4())[:4].upper()}"
                voyage = Voyage(
                    tenant_id=row.tenant_id,
                    voyage_no=vno,
                    status="planned",
                    vessel_id=row.vessel_id,
                    charter_id=row.id,
                    cargo=(row.freight_terms or {}).get("cargo"),
                    cp_date=date.today(),
                )
                db.add(voyage)
                db.flush()
                start = datetime.now(timezone.utc)
                end = start + timedelta(days=14)
                db.add(
                    ScheduleBlock(
                        tenant_id=row.tenant_id,
                        vessel_id=row.vessel_id,
                        block_type="voyage",
                        title=vno,
                        start_at=start,
                        end_at=end,
                        voyage_id=voyage.id,
                        hard_conflict=False,
                    )
                )
    elif inst.entity_type == "invoice":
        row = db.get(Invoice, inst.entity_id)
        if row and row.status == "pending_approval":
            row.status = transition("invoice", row.status, "issued", INVOICE_TRANSITIONS)
            row.issued_at = datetime.now(timezone.utc)


# re-export helper for other routers
def begin_entity_workflow(db: Session, tenant_id: UUID, entity_type: str, entity_id: UUID, user_id: UUID):
    return start_workflow(db, tenant_id=tenant_id, entity_type=entity_type, entity_id=entity_id, started_by=user_id)
