"""Platform ops console APIs — `/api/v1/platform/ops/...`."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tenant
from app.models_ops import AlertRule, PlatformDeploymentProfile, SystemInitStep, TenantDatastoreBinding
from app.routers.admin_platform import require_roles
from app.security import AuthContext
from app.config import get_settings
from app.services import platform_ops as ops
from app.services.tenant_datastore import TenantDatastoreResolver

router = APIRouter(prefix="/platform/ops", tags=["Platform Ops"])


class DatastoreBindingIn(BaseModel):
    tenant_id: UUID
    purpose: str = "primary"
    engine: str = Field(..., description="sqlite|postgres|mysql|cloud_rds")
    host_mode: str = Field("local", description="local|server|cloud")
    cloud_provider: str | None = None
    display_name: str
    connection_url: str = Field(..., min_length=3)
    options: dict = Field(default_factory=dict)
    routing_policy: str = "bind_only"
    notes: str | None = None


class DatastoreTestIn(BaseModel):
    connection_url: str | None = None
    binding_id: UUID | None = None


class InitStepPatch(BaseModel):
    status: str | None = None
    title: str | None = None
    description: str | None = None
    config: dict | None = None


class DeployProfileIn(BaseModel):
    code: str
    name: str
    kind: str
    cloud_provider: str | None = None
    region: str | None = None
    description: str | None = None
    template: dict = Field(default_factory=dict)


class AlertRuleIn(BaseModel):
    code: str
    name: str
    metric_code: str
    operator: str = "gt"
    threshold: float
    severity: str = "warning"
    enabled: bool = True
    channels: dict = Field(default_factory=lambda: {"console": True})
    description: str | None = None


class AlertRulePatch(BaseModel):
    name: str | None = None
    operator: str | None = None
    threshold: float | None = None
    severity: str | None = None
    enabled: bool | None = None
    channels: dict | None = None
    description: str | None = None


@router.get("/overview")
def ops_overview(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    catalog = ops.bootstrap_ops_catalog(db)
    ds = ops.runtime_datasource_info()
    bindings = db.scalar(select(TenantDatastoreBinding.id).limit(1))
    return {
        "datasource": ds,
        "catalog": catalog,
        "has_tenant_bindings": bindings is not None,
        "capabilities": {
            "tenant_db_binding": True,
            "tenant_engine_switch": False,
            "connectivity_test": True,
            "init_wizard": True,
            "deploy_profiles": True,
            "monitor_alerts": True,
        },
    }


@router.get("/datasource")
def ops_datasource(auth: AuthContext = Depends(require_roles("platform_admin"))):
    _ = auth
    return ops.runtime_datasource_info()


@router.post("/datasource/test")
def ops_datasource_test(
    body: DatastoreTestIn | None = None,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    payload = body or DatastoreTestIn()
    if payload.binding_id:
        try:
            return ops.test_binding(db, payload.binding_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail={"code": "BINDING_NOT_FOUND", "message": str(exc)}) from exc
    if payload.connection_url:
        return ops.test_connection_url(payload.connection_url)
    return ops.test_connection_url(get_settings().database_url)


@router.get("/datastores")
def list_datastores(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = db.scalars(select(TenantDatastoreBinding).order_by(TenantDatastoreBinding.created_at.desc())).all()
    return [ops.binding_to_public(r) for r in rows]


@router.post("/datastores")
def create_datastore(
    body: DatastoreBindingIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    try:
        row = ops.upsert_binding(
            db,
            tenant_id=body.tenant_id,
            purpose=body.purpose,
            engine_name=body.engine,
            host_mode=body.host_mode,
            display_name=body.display_name,
            connection_url=body.connection_url,
            cloud_provider=body.cloud_provider,
            options=body.options,
            routing_policy=body.routing_policy,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "BIND_FAILED", "message": str(exc)}) from exc
    return ops.binding_to_public(row)


@router.put("/datastores/{binding_id}")
def update_datastore(
    binding_id: UUID,
    body: DatastoreBindingIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    try:
        row = ops.upsert_binding(
            db,
            tenant_id=body.tenant_id,
            purpose=body.purpose,
            engine_name=body.engine,
            host_mode=body.host_mode,
            display_name=body.display_name,
            connection_url=body.connection_url,
            cloud_provider=body.cloud_provider,
            options=body.options,
            routing_policy=body.routing_policy,
            notes=body.notes,
            binding_id=binding_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "BIND_FAILED", "message": str(exc)}) from exc
    return ops.binding_to_public(row)


@router.delete("/datastores/{binding_id}")
def delete_datastore(
    binding_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = db.get(TenantDatastoreBinding, binding_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "BINDING_NOT_FOUND", "message": "绑定不存在"})
    db.delete(row)
    db.commit()
    return {"ok": True, "id": str(binding_id)}


@router.post("/datastores/{binding_id}/test")
def test_datastore(
    binding_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    try:
        return ops.test_binding(db, binding_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "BINDING_NOT_FOUND", "message": str(exc)}) from exc


@router.get("/datastores/resolve/{tenant_id}")
def resolve_datastore(
    tenant_id: UUID,
    purpose: str = "primary",
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    if not db.get(Tenant, tenant_id):
        raise HTTPException(status_code=404, detail={"code": "TENANT_NOT_FOUND", "message": "租户不存在"})
    resolver = TenantDatastoreResolver(db)
    return resolver.to_public(resolver.resolve(tenant_id, purpose))


@router.get("/init/steps")
def list_init_steps(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = ops.ensure_init_steps(db)
    return [ops.init_step_to_public(r) for r in rows]


@router.patch("/init/steps/{step_id}")
def patch_init_step(
    step_id: UUID,
    body: InitStepPatch,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = db.get(SystemInitStep, step_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "STEP_NOT_FOUND", "message": "步骤不存在"})
    if body.status is not None:
        row.status = body.status
    if body.title is not None:
        row.title = body.title
    if body.description is not None:
        row.description = body.description
    if body.config is not None:
        row.config = body.config
    db.commit()
    return ops.init_step_to_public(row)


@router.post("/init/steps/{step_id}/run")
def run_init_step(
    step_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    try:
        return ops.run_init_step(db, step_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "STEP_NOT_FOUND", "message": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail={"code": "STEP_FAILED", "message": str(exc)[:500]}) from exc


@router.get("/deploy/profiles")
def list_deploy_profiles(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = ops.ensure_deploy_profiles(db)
    return [ops.profile_to_public(r) for r in rows]


@router.post("/deploy/profiles")
def create_deploy_profile(
    body: DeployProfileIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    exists = db.scalar(select(PlatformDeploymentProfile).where(PlatformDeploymentProfile.code == body.code))
    if exists:
        raise HTTPException(status_code=409, detail={"code": "CODE_EXISTS", "message": "档案编码已存在"})
    row = PlatformDeploymentProfile(
        code=body.code,
        name=body.name,
        kind=body.kind,
        cloud_provider=body.cloud_provider,
        region=body.region,
        description=body.description,
        template=body.template,
        status="active",
        is_builtin=False,
        apply_log={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ops.profile_to_public(row)


@router.post("/deploy/profiles/{profile_id}/apply")
def apply_deploy_profile(
    profile_id: UUID,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    try:
        return ops.apply_deploy_profile(db, profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "PROFILE_NOT_FOUND", "message": str(exc)}) from exc


@router.get("/monitor/snapshot")
def monitor_snapshot(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    return ops.capture_monitor_snapshot(db)


@router.get("/monitor/alerts")
def list_alerts(auth: AuthContext = Depends(require_roles("platform_admin")), db: Session = Depends(get_db)):
    _ = auth
    rows = ops.ensure_alert_rules(db)
    return [ops.alert_to_public(r) for r in rows]


@router.post("/monitor/alerts")
def create_alert(
    body: AlertRuleIn,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    if db.scalar(select(AlertRule).where(AlertRule.code == body.code)):
        raise HTTPException(status_code=409, detail={"code": "CODE_EXISTS", "message": "规则编码已存在"})
    row = AlertRule(
        code=body.code,
        name=body.name,
        metric_code=body.metric_code,
        operator=body.operator,
        threshold=body.threshold,
        severity=body.severity,
        enabled=body.enabled,
        channels=body.channels,
        description=body.description,
        last_state="ok",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return ops.alert_to_public(row)


@router.patch("/monitor/alerts/{rule_id}")
def patch_alert(
    rule_id: UUID,
    body: AlertRulePatch,
    auth: AuthContext = Depends(require_roles("platform_admin")),
    db: Session = Depends(get_db),
):
    _ = auth
    row = db.get(AlertRule, rule_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "RULE_NOT_FOUND", "message": "规则不存在"})
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return ops.alert_to_public(row)
