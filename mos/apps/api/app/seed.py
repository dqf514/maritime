from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Module, Role, Tenant, TenantModuleLicense, User, UserRole
from app.security import hash_password

CORE_MODULES = [
    ("platform", "Platform", True),
    ("shell", "Shell", True),
    ("identity", "Identity", True),
    ("tenancy", "Tenancy", True),
    ("license", "License", True),
    ("rbac", "RBAC", True),
    ("ai", "AI Hub", True),
    ("integration", "Integration Hub", True),
    ("apim", "API Management", True),
    ("i18n", "i18n & Terminology", True),
    ("notify", "Notifications", True),
    ("audit", "Audit", True),
    ("selfcheck", "SelfCheck", True),
    ("dataops", "DataOps", True),
    ("docs", "Documents", True),
    ("workflow", "Workflow", True),
    ("masterdata", "Master Data", False),
    ("estimate", "Estimate", False),
    ("chartering", "Chartering", False),
    ("operations", "Operations", False),
    ("laytime", "Laytime", False),
    ("finance", "Finance", False),
    ("email", "Email", False),
    ("analytics", "Analytics", False),
    ("twin", "Digital Twin", False),
    ("bunker", "Bunker", False),
    ("claims", "Claims", False),
    ("pooling", "Pooling", False),
    ("risk", "Risk", False),
    ("ship_mgmt", "Ship Management", False),
    ("emissions", "Emissions & FuelEU", False),
]


def seed_if_empty(db: Session) -> None:
    _ensure_module_catalog(db)
    if not db.scalar(select(Tenant).limit(1)):
        tenant = Tenant(
            name="Demo Shipping",
            code="demo",
            status="active",
            default_locale="en",
            default_timezone="UTC",
            profile_tier="M",
        )
        db.add(tenant)
        db.flush()
        _ensure_demo_licenses(db, tenant.id)
        db.commit()
    else:
        _ensure_demo_licenses(db)
    _ensure_platform_tenant(db)
    _ensure_tenant_roles_and_users(db)
    db.commit()


LICENSED_MODULES = {
    "masterdata",
    "estimate",
    "chartering",
    "operations",
    "laytime",
    "finance",
    "email",
    "analytics",
    "twin",
    "dataops",
    "bunker",
    "claims",
    "pooling",
    "risk",
    "ship_mgmt",
    "emissions",
}


def _ensure_module_catalog(db: Session) -> None:
    for code, name, is_core in CORE_MODULES:
        existing = db.get(Module, code)
        if not existing:
            db.add(Module(code=code, name=name, is_core=is_core, description=name))
    db.flush()


def _ensure_demo_licenses(db: Session, tenant_id=None) -> None:
    if tenant_id is None:
        tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
        if not tenant:
            return
        tenant_id = tenant.id
    now = datetime.now(timezone.utc)
    for code, _name, is_core in CORE_MODULES:
        if not (is_core or code in LICENSED_MODULES):
            continue
        exists = db.scalar(
            select(TenantModuleLicense).where(
                TenantModuleLicense.tenant_id == tenant_id,
                TenantModuleLicense.module_code == code,
            )
        )
        if not exists:
            db.add(
                TenantModuleLicense(
                    tenant_id=tenant_id,
                    module_code=code,
                    status="active",
                    activated_at=now,
                    features={},
                )
            )
    db.commit()


TENANT_ROLE_DEFS = [
    ("tenant_admin", "Tenant Admin", {"*": True}),
    ("chartering", "Chartering", {"estimate": True, "chartering": True, "email": True}),
    ("operations", "Operations", {"operations": True, "twin": True, "ship_mgmt": True}),
    ("finance", "Finance", {"finance": True}),
    ("demurrage", "Demurrage", {"laytime": True, "claims": True}),
    ("management", "Management", {"analytics": True, "twin": True, "ship_mgmt": True}),
    ("technical", "Technical / Superintendent", {"ship_mgmt": True, "operations": True, "twin": True}),
    ("viewer", "Viewer", {"read": True}),
]

DEMO_USERS = [
    ("admin@demo.marios", "Demo Admin", ["tenant_admin"]),
    ("charterer@demo.marios", "Alex Charterer", ["chartering"]),
    ("ops@demo.marios", "Olivia Ops", ["operations"]),
    ("finance@demo.marios", "Finn Finance", ["finance"]),
    ("demurrage@demo.marios", "Dana Demurrage", ["demurrage"]),
    ("mgmt@demo.marios", "Morgan Mgmt", ["management"]),
    ("tech@demo.marios", "Taylor Tech", ["technical"]),
]


def _ensure_role(db: Session, tenant_id, code: str, name: str, permissions: dict) -> Role:
    role = db.scalar(select(Role).where(Role.tenant_id == tenant_id, Role.code == code))
    if not role:
        role = Role(tenant_id=tenant_id, code=code, name=name, permissions=permissions)
        db.add(role)
        db.flush()
    return role


def _ensure_user_with_roles(db: Session, tenant_id, email: str, full_name: str, role_codes: list[str], password: str = "Demo1234!") -> None:
    from datetime import datetime

    user = db.scalar(select(User).where(User.tenant_id == tenant_id, User.email == email))
    if not user:
        user = User(
            tenant_id=tenant_id,
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            status="active",
            locale="en",
            timezone="UTC",
            email_verified_at=datetime.now().astimezone(),
        )
        db.add(user)
        db.flush()
    elif getattr(user, "email_verified_at", None) is None:
        user.email_verified_at = datetime.now().astimezone()
    existing = set(
        db.scalars(select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id)).all()
    )
    for code in role_codes:
        if code in existing:
            continue
        role = db.scalar(select(Role).where(Role.tenant_id == tenant_id, Role.code == code))
        if role:
            db.add(UserRole(user_id=user.id, role_id=role.id))
            existing.add(code)
    db.flush()


def _ensure_platform_tenant(db: Session) -> None:
    sys_tenant = db.scalar(select(Tenant).where(Tenant.code == "sys"))
    if not sys_tenant:
        sys_tenant = Tenant(
            name="MariOS Platform",
            code="sys",
            status="active",
            default_locale="en",
            default_timezone="UTC",
            profile_tier="E",
        )
        db.add(sys_tenant)
        db.flush()
    _ensure_role(db, sys_tenant.id, "platform_admin", "Platform Admin", {"platform": True})
    _ensure_user_with_roles(
        db,
        sys_tenant.id,
        "ops@marios.platform",
        "Platform Operator",
        ["platform_admin"],
        password="Ops1234!",
    )


def _ensure_tenant_roles_and_users(db: Session) -> None:
    for tenant in db.scalars(select(Tenant).where(Tenant.code != "sys")).all():
        for code, name, perms in TENANT_ROLE_DEFS:
            _ensure_role(db, tenant.id, code, name, perms)
        if tenant.code == "demo":
            for email, full_name, roles in DEMO_USERS:
                _ensure_user_with_roles(db, tenant.id, email, full_name, roles)


def seed_wave1_demo(db: Session) -> None:
    """Idempotent demo masterdata / AI / connectors for Wave 1."""
    from datetime import date
    from decimal import Decimal

    from app.models_wave1 import (
        AiProvider,
        AiSkillBinding,
        Company,
        ConnectorInstance,
        Counterparty,
        ExchangeRate,
        Port,
        Vessel,
    )

    tenant = db.scalar(select(Tenant).where(Tenant.code == "demo"))
    if not tenant:
        return

    if not db.scalar(select(Company).where(Company.tenant_id == tenant.id).limit(1)):
        db.add(Company(tenant_id=tenant.id, name="Demo Shipping Co", code="DEMO", base_currency="USD"))

    if not db.scalar(select(Vessel).where(Vessel.tenant_id == tenant.id).limit(1)):
        db.add(
            Vessel(
                tenant_id=tenant.id,
                name="MV DEMO WAVE",
                imo="9000001",
                flag="SG",
                vessel_type="Bulker",
                dwt=Decimal("58000"),
                speed_knots=Decimal("13.5"),
                consumption_sea=Decimal("28"),
                consumption_port=Decimal("3.5"),
            )
        )

    if not db.scalar(select(Port).limit(1)):
        db.add_all(
            [
                Port(unlocode="SGSIN", name="Singapore", country="SG", timezone="Asia/Singapore"),
                Port(unlocode="NLRTM", name="Rotterdam", country="NL", timezone="Europe/Amsterdam"),
                Port(unlocode="CNTXG", name="Tianjin Xingang", country="CN", timezone="Asia/Shanghai"),
            ]
        )

    if not db.scalar(select(Counterparty).where(Counterparty.tenant_id == tenant.id).limit(1)):
        db.add(
            Counterparty(
                tenant_id=tenant.id,
                name="Atlantic Brokers Ltd",
                type="broker",
                country="GB",
                sanctions_status="clear",
            )
        )

    if not db.scalar(select(ExchangeRate).where(ExchangeRate.tenant_id == tenant.id).limit(1)):
        db.add(
            ExchangeRate(
                tenant_id=tenant.id,
                base_currency="USD",
                quote_currency="CNY",
                rate=Decimal("7.12000000"),
                rate_date=date.today(),
                source="seed",
            )
        )

    if not db.scalar(select(AiProvider).where(AiProvider.tenant_id == tenant.id).limit(1)):
        primary = AiProvider(
            tenant_id=tenant.id,
            name="Demo OpenAI Compatible",
            provider_type="openai_compatible",
            base_url="https://api.openai.com/v1",
            model_default="gpt-4o-mini",
            secret_ref="secret://demo/openai",
            status="active",
        )
        fallback = AiProvider(
            tenant_id=tenant.id,
            name="Demo Local Fallback",
            provider_type="openai_compatible",
            base_url="http://127.0.0.1:11434/v1",
            model_default="llama3.1",
            secret_ref="secret://demo/local",
            status="active",
        )
        db.add_all([primary, fallback])
        db.flush()
        db.add(
            AiSkillBinding(
                tenant_id=tenant.id,
                skill_code="email.extract.recap",
                primary_provider_id=primary.id,
                fallback_provider_id=fallback.id,
                enabled=True,
            )
        )

    if not db.scalar(select(ConnectorInstance).where(ConnectorInstance.tenant_id == tenant.id).limit(1)):
        db.add(
            ConnectorInstance(
                tenant_id=tenant.id,
                connector_type="fx.manual",
                instance_name="Manual FX",
                status="active",
                config={},
                last_health={"ok": True, "message": "seed"},
            )
        )

    db.commit()

def seed_saas_catalog(db: Session) -> None:
    """Idempotent SaaS plans, meters, packs, payment providers, AI endpoints, demo workflows."""
    from datetime import date, timedelta
    from decimal import Decimal

    from app.models_saas import (
        OrgUnit,
        PaymentProvider,
        PlatformAiEndpoint,
        SaaSPlan,
        TenantCompanyProfile,
        TenantSubscription,
        UsageMeterDef,
        UsagePack,
        WorkflowDefinition,
    )
    from app.services.saas_engine import credit_usage

    meters = [
        ("ai.tokens", "AI Tokens", "token", Decimal("0.000002")),
        ("api.calls", "API Calls", "count", Decimal("0.001")),
        ("storage.gb", "Object Storage", "gb", Decimal("0.02")),
    ]
    for code, name, unit, overage in meters:
        if not db.scalar(select(UsageMeterDef).where(UsageMeterDef.code == code)):
            db.add(UsageMeterDef(code=code, name=name, unit=unit, overage_price=overage, currency="USD"))

    if not db.scalar(select(SaaSPlan).where(SaaSPlan.code == "starter")):
        db.add(
            SaaSPlan(
                code="starter",
                name="Starter",
                description="Solo / micro operator — core commercial modules",
                billing_period="monthly",
                price_amount=Decimal("499"),
                included_modules={
                    "masterdata": True,
                    "estimate": True,
                    "chartering": True,
                    "operations": True,
                    "email": True,
                    "dataops": True,
                    "ai": True,
                },
                included_quotas={"ai.tokens": 500000, "api.calls": 50000},
                seat_limit=5,
            )
        )
    if not db.scalar(select(SaaSPlan).where(SaaSPlan.code == "fleet")):
        db.add(
            SaaSPlan(
                code="fleet",
                name="Fleet Pro",
                description="Mid fleet — finance, laytime, twin, analytics",
                billing_period="monthly",
                price_amount=Decimal("2499"),
                included_modules={
                    "masterdata": True,
                    "estimate": True,
                    "chartering": True,
                    "operations": True,
                    "laytime": True,
                    "finance": True,
                    "claims": True,
                    "bunker": True,
                    "email": True,
                    "analytics": True,
                    "twin": True,
                    "ai": True,
                    "dataops": True,
                    "workflow": True,
                    "ship_mgmt": True,
                },
                included_quotas={"ai.tokens": 5000000, "api.calls": 500000, "storage.gb": 100},
                seat_limit=50,
            )
        )
    if not db.scalar(select(SaaSPlan).where(SaaSPlan.code == "enterprise")):
        db.add(
            SaaSPlan(
                code="enterprise",
                name="Enterprise",
                description="Group / multi-brand — pooling, risk, unlimited seats",
                billing_period="yearly",
                price_amount=Decimal("99000"),
                included_modules={m[0]: True for m in CORE_MODULES},
                included_quotas={"ai.tokens": 50000000, "api.calls": 5000000, "storage.gb": 2000},
                seat_limit=None,
            )
        )

    packs = [
        ("ai_1m", "AI 1M tokens", "ai.tokens", Decimal("1000000"), Decimal("29")),
        ("ai_10m", "AI 10M tokens", "ai.tokens", Decimal("10000000"), Decimal("249")),
        ("api_100k", "API 100k calls", "api.calls", Decimal("100000"), Decimal("19")),
    ]
    for code, name, meter, qty, price in packs:
        if not db.scalar(select(UsagePack).where(UsagePack.code == code)):
            db.add(UsagePack(code=code, name=name, meter_code=meter, quantity=qty, price_amount=price))

    for code, name, status in [
        ("manual", "Manual / Wire transfer", "active"),
        ("stripe", "Stripe", "adapter_pending"),
        ("alipay", "Alipay", "adapter_pending"),
        ("wechat_pay", "WeChat Pay", "adapter_pending"),
    ]:
        if not db.scalar(select(PaymentProvider).where(PaymentProvider.code == code)):
            db.add(PaymentProvider(code=code, name=name, status=status, config={}))

    if not db.scalar(select(PlatformAiEndpoint).where(PlatformAiEndpoint.code == "voyageos-gateway")):
        db.add(
            PlatformAiEndpoint(
                code="voyageos-gateway",
                name="MariOS AI Gateway",
                provider_type="openai_compatible",
                base_url="https://ai.marios.local/v1",
                model_default="marios-maritime-mini",
                meter_code="ai.tokens",
                tokens_per_call_est=1200,
                status="active",
            )
        )

    demo = db.scalar(select(Tenant).where(Tenant.code == "demo"))
    if demo:
        if not db.scalar(select(TenantCompanyProfile).where(TenantCompanyProfile.tenant_id == demo.id)):
            db.add(
                TenantCompanyProfile(
                    tenant_id=demo.id,
                    legal_name="Demo Shipping Pte Ltd",
                    display_name="Demo Shipping",
                    logo_url="/branding/demo-logo.svg",
                    website="https://demo.marios.local",
                    tax_no="SG-DEMO-001",
                    address="1 Harbourfront Ave, Singapore",
                    brand_primary="#1a8a8a",
                )
            )
        if not db.scalar(select(OrgUnit).where(OrgUnit.tenant_id == demo.id).limit(1)):
            root = OrgUnit(tenant_id=demo.id, code="HQ", name="Headquarters", unit_type="company")
            db.add(root)
            db.flush()
            db.add(OrgUnit(tenant_id=demo.id, parent_id=root.id, code="CHARTER", name="Chartering", unit_type="dept"))
            db.add(OrgUnit(tenant_id=demo.id, parent_id=root.id, code="OPS", name="Operations", unit_type="dept"))
            db.add(OrgUnit(tenant_id=demo.id, parent_id=root.id, code="FIN", name="Finance", unit_type="dept"))

        # Link demo users to departments (idempotent)
        from app.models import User
        from app.models_saas import UserOrgMembership

        dept_map = {
            "charterer@demo.marios": "CHARTER",
            "ops@demo.marios": "OPS",
            "finance@demo.marios": "FIN",
            "mgmt@demo.marios": "HQ",
            "admin@demo.marios": "HQ",
        }
        for email, code in dept_map.items():
            user = db.scalar(select(User).where(User.tenant_id == demo.id, User.email == email))
            unit = db.scalar(select(OrgUnit).where(OrgUnit.tenant_id == demo.id, OrgUnit.code == code))
            if not user or not unit:
                continue
            if db.scalar(
                select(UserOrgMembership).where(
                    UserOrgMembership.user_id == user.id, UserOrgMembership.org_unit_id == unit.id
                )
            ):
                continue
            # demote existing primary
            for m in db.scalars(
                select(UserOrgMembership).where(UserOrgMembership.user_id == user.id, UserOrgMembership.is_primary.is_(True))
            ).all():
                m.is_primary = False
            db.add(UserOrgMembership(user_id=user.id, org_unit_id=unit.id, is_primary=True))
            if code == "HQ" and email == "admin@demo.marios" and not unit.manager_user_id:
                unit.manager_user_id = user.id
            if code != "HQ" and not unit.manager_user_id:
                unit.manager_user_id = user.id

        fleet = db.scalar(select(SaaSPlan).where(SaaSPlan.code == "fleet"))
        if fleet and not db.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == demo.id).limit(1)):
            sub = TenantSubscription(
                tenant_id=demo.id,
                plan_id=fleet.id,
                status="active",
                started_on=date.today(),
                current_period_end=date.today() + timedelta(days=30),
                auto_renew=True,
            )
            db.add(sub)
            db.flush()
            credit_usage(
                db,
                tenant_id=demo.id,
                meter_code="ai.tokens",
                quantity=Decimal("5000000"),
                ref_type="subscription",
                ref_id=str(sub.id),
                note="Seed Fleet Pro quota",
            )

        if not db.scalar(
            select(WorkflowDefinition).where(WorkflowDefinition.tenant_id == demo.id, WorkflowDefinition.code == "charter_approval")
        ):
            db.add(
                WorkflowDefinition(
                    tenant_id=demo.id,
                    code="charter_approval",
                    name="Charter activation approval",
                    entity_type="charter",
                    steps={
                        "steps": [
                            {"name": "Commercial review", "role_code": "management"},
                            {"name": "Tenant admin confirm", "role_code": "tenant_admin"},
                        ]
                    },
                    enabled=True,
                )
            )
        if not db.scalar(
            select(WorkflowDefinition).where(WorkflowDefinition.tenant_id == demo.id, WorkflowDefinition.code == "invoice_approval")
        ):
            db.add(
                WorkflowDefinition(
                    tenant_id=demo.id,
                    code="invoice_approval",
                    name="Invoice issue approval",
                    entity_type="invoice",
                    steps={"steps": [{"name": "Finance lead", "role_code": "finance"}]},
                    enabled=True,
                )
            )

    from app.models_saas import PlatformBranding

    if not db.scalar(select(PlatformBranding).limit(1)):
        db.add(PlatformBranding())

    # Identity defaults
    from app.services.identity import ensure_platform_identity, ensure_tenant_policy

    ensure_platform_identity(db)
    if demo:
        policy = ensure_tenant_policy(db, demo.id)
        # Demo stays friction-light unless tenant admin tightens
        policy.require_email_verify = False
        policy.microsoft_enabled = True
        policy.google_enabled = True
        policy.magic_link_enabled = True

    db.commit()
