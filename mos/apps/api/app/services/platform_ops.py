"""Platform ops services: runtime DS info, connectivity, init wizard, deploy, monitor."""

from __future__ import annotations

import os
import platform
import time
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, engine as primary_engine
from app.models import Tenant
from app.models_ops import (
    AlertRule,
    MonitorMetric,
    PlatformDeploymentProfile,
    SystemInitStep,
    TenantDatastoreBinding,
)
from app.services.ops_crypto import decrypt_secret, encrypt_secret, mask_connection_url


def _now() -> datetime:
    return datetime.now().astimezone()


def runtime_datasource_info() -> dict[str, Any]:
    settings = get_settings()
    url = settings.database_url
    dialect = primary_engine.dialect.name
    driver = getattr(primary_engine.dialect, "driver", "")
    return {
        "dialect": dialect,
        "driver": driver,
        "url_masked": mask_connection_url(url),
        "is_sqlite": dialect == "sqlite",
        "is_postgres": dialect in {"postgresql", "postgres"},
        "default_for_dev": "sqlite+pysqlite:///./voyageos_wave0.db",
        "compose_default": "postgresql+psycopg://…@postgres:5432/voyageos",
        "multi_tenant_mode": "shared_schema",
        "tenant_engine_routing": "reserved",  # bindings exist; runtime uses primary
        "checked_at": _now().isoformat(),
        "notes": "本地开发默认 SQLite；Compose / 生产推荐 PostgreSQL。租户库绑定可在运维台配置，当前业务仍走主库。",
    }


def test_connection_url(url: str, timeout_sec: float = 5.0) -> dict[str, Any]:
    started = time.perf_counter()
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    try:
        eng = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return {
            "ok": True,
            "message": "连通正常",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "url_masked": mask_connection_url(url),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "message": str(exc)[:500],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "url_masked": mask_connection_url(url),
        }


def binding_to_public(row: TenantDatastoreBinding) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "purpose": row.purpose,
        "engine": row.engine,
        "host_mode": row.host_mode,
        "cloud_provider": row.cloud_provider,
        "display_name": row.display_name,
        "connection_hint": row.connection_hint,
        "options": row.options or {},
        "status": row.status,
        "last_test_at": row.last_test_at.isoformat() if row.last_test_at else None,
        "last_test_ok": row.last_test_ok,
        "last_test_message": row.last_test_message,
        "routing_policy": row.routing_policy,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def upsert_binding(
    db: Session,
    *,
    tenant_id: UUID,
    purpose: str,
    engine_name: str,
    host_mode: str,
    display_name: str,
    connection_url: str,
    cloud_provider: str | None = None,
    options: dict | None = None,
    routing_policy: str = "bind_only",
    notes: str | None = None,
    binding_id: UUID | None = None,
) -> TenantDatastoreBinding:
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise ValueError("租户不存在")
    row: TenantDatastoreBinding | None = None
    if binding_id:
        row = db.get(TenantDatastoreBinding, binding_id)
        if not row:
            raise ValueError("绑定不存在")
    else:
        row = db.scalar(
            select(TenantDatastoreBinding).where(
                TenantDatastoreBinding.tenant_id == tenant_id,
                TenantDatastoreBinding.purpose == purpose,
            )
        )
    cipher = encrypt_secret(connection_url)
    hint = mask_connection_url(connection_url)
    if row is None:
        row = TenantDatastoreBinding(
            tenant_id=tenant_id,
            purpose=purpose,
            engine=engine_name,
            host_mode=host_mode,
            cloud_provider=cloud_provider,
            display_name=display_name,
            connection_cipher=cipher,
            connection_hint=hint,
            options=options or {},
            routing_policy=routing_policy,
            notes=notes,
            status="draft",
        )
        db.add(row)
    else:
        row.engine = engine_name
        row.host_mode = host_mode
        row.cloud_provider = cloud_provider
        row.display_name = display_name
        row.connection_cipher = cipher
        row.connection_hint = hint
        row.options = options or {}
        row.routing_policy = routing_policy
        row.notes = notes
        row.status = "draft" if row.status == "disabled" else row.status
    db.commit()
    db.refresh(row)
    return row


def test_binding(db: Session, binding_id: UUID) -> dict[str, Any]:
    row = db.get(TenantDatastoreBinding, binding_id)
    if not row:
        raise ValueError("绑定不存在")
    url = decrypt_secret(row.connection_cipher)
    result = test_connection_url(url)
    row.last_test_at = _now()
    row.last_test_ok = result["ok"]
    row.last_test_message = result["message"]
    if result["ok"] and row.status in {"draft", "verified"}:
        row.status = "verified"
    db.commit()
    return {**result, "binding": binding_to_public(row)}


# —— Init wizard ——

DEFAULT_INIT_STEPS: list[dict[str, Any]] = [
    {
        "code": "ensure_schema",
        "title": "创建 / 校验数据表结构",
        "description": "在当前主库执行 create_all，确保平台表存在。",
        "sort_order": 10,
        "action_kind": "ensure_schema",
        "required": True,
    },
    {
        "code": "seed_catalog",
        "title": "写入基础目录与 SaaS 目录",
        "description": "模块、角色模板、套餐与计量目录等。",
        "sort_order": 20,
        "action_kind": "seed_catalog",
        "required": True,
    },
    {
        "code": "seed_demo",
        "title": "演示租户与样例数据（可选）",
        "description": "demo 租户、航次链路样例，便于验收。",
        "sort_order": 30,
        "action_kind": "seed_demo",
        "required": False,
    },
    {
        "code": "seed_i18n",
        "title": "语言包与术语",
        "description": "中英文 UI 文案与航运术语。",
        "sort_order": 40,
        "action_kind": "seed_i18n",
        "required": True,
    },
    {
        "code": "verify_ready",
        "title": "就绪检查",
        "description": "确认主库可读写、关键租户与运营账号可用。",
        "sort_order": 90,
        "action_kind": "verify_ready",
        "required": True,
    },
]


def ensure_init_steps(db: Session) -> list[SystemInitStep]:
    rows = list(db.scalars(select(SystemInitStep).order_by(SystemInitStep.sort_order)).all())
    if rows:
        return rows
    for spec in DEFAULT_INIT_STEPS:
        db.add(SystemInitStep(**spec, status="pending", config={}, last_result={}))
    db.commit()
    return list(db.scalars(select(SystemInitStep).order_by(SystemInitStep.sort_order)).all())


def init_step_to_public(row: SystemInitStep) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "title": row.title,
        "description": row.description,
        "sort_order": row.sort_order,
        "action_kind": row.action_kind,
        "config": row.config or {},
        "status": row.status,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
        "last_result": row.last_result or {},
        "required": row.required,
    }


def run_init_step(db: Session, step_id: UUID) -> dict[str, Any]:
    from app.seed import seed_if_empty, seed_saas_catalog, seed_wave1_demo
    from app.seed_demo_flow import seed_full_demo_flow
    from app.seed_i18n import seed_i18n

    row = db.get(SystemInitStep, step_id)
    if not row:
        raise ValueError("初始化步骤不存在")
    row.status = "running"
    db.commit()
    result: dict[str, Any] = {"ok": False}
    try:
        kind = row.action_kind
        if kind == "ensure_schema":
            Base.metadata.create_all(bind=primary_engine)
            result = {"ok": True, "message": "表结构已校验 / 创建"}
        elif kind == "seed_catalog":
            seed_if_empty(db)
            seed_saas_catalog(db)
            result = {"ok": True, "message": "基础与 SaaS 目录已写入"}
        elif kind == "seed_demo":
            seed_wave1_demo(db)
            seed_full_demo_flow(db)
            result = {"ok": True, "message": "演示数据已写入"}
        elif kind == "seed_i18n":
            seed_i18n(db)
            result = {"ok": True, "message": "语言包已写入"}
        elif kind == "verify_ready":
            with primary_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            tenants = db.scalar(select(func.count()).select_from(Tenant)) or 0
            result = {
                "ok": True,
                "message": "主库就绪",
                "tenant_count": int(tenants),
                "datasource": runtime_datasource_info(),
            }
        else:
            result = {"ok": True, "message": f"自定义步骤 {kind} 已标记完成（无额外动作）"}
        row.status = "done" if result.get("ok") else "failed"
        row.last_result = result
        row.last_run_at = _now()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        row.status = "failed"
        row.last_result = {"ok": False, "message": str(exc)[:500]}
        row.last_run_at = _now()
        db.commit()
        raise
    return init_step_to_public(row)


# —— Deployment profiles ——

BUILTIN_DEPLOY_PROFILES: list[dict[str, Any]] = [
    {
        "code": "compose_local",
        "name": "Docker Compose 一体化",
        "kind": "docker_compose",
        "cloud_provider": None,
        "region": None,
        "description": "本机或内网主机：api / web / postgres / redis / minio。",
        "template": {
            "path": "deploy/compose/docker-compose.yml",
            "services": ["postgres", "redis", "minio", "api", "web"],
            "ports": {"web": 3000, "api": 8000, "postgres": 5432},
            "database": "postgresql+psycopg",
            "steps": [
                "复制 deploy/compose/.env.example 为 .env",
                "docker compose -f deploy/compose/docker-compose.yml up -d",
                "打开 http://localhost:3000，使用平台账号完成初始化向导",
            ],
        },
        "is_builtin": True,
    },
    {
        "code": "single_host",
        "name": "单机进程部署",
        "kind": "single_host",
        "description": "开发机或小规模验收：SQLite + uvicorn + next dev/start。",
        "template": {
            "database": "sqlite+pysqlite:///./voyageos_wave0.db",
            "api": "uvicorn app.main:app --reload --port 8000",
            "web": "npm run dev",
            "steps": [
                "在 apps/api 安装依赖并启动 API",
                "在 apps/web 安装依赖并启动前端",
                "可选：配置 DATABASE_URL 指向本机 Postgres",
            ],
        },
        "is_builtin": True,
    },
    {
        "code": "cloud_aliyun_ecs",
        "name": "阿里云 ECS + RDS",
        "kind": "cloud_vm",
        "cloud_provider": "aliyun",
        "region": "cn-hangzhou",
        "description": "云主机跑容器或进程，RDS PostgreSQL 作主库（模板，需按账号落地）。",
        "template": {
            "compute": "ECS",
            "database": "RDS PostgreSQL",
            "object_storage": "OSS（可选对接 S3 兼容）",
            "security_group": ["22", "80", "443", "8000"],
            "steps": [
                "创建 VPC / 安全组",
                "开通 RDS PostgreSQL，写入 DATABASE_URL",
                "在 ECS 上部署 Compose 或 systemd 服务",
                "配置域名与 HTTPS 反向代理",
            ],
            "stub": True,
        },
        "is_builtin": True,
    },
    {
        "code": "cloud_aws_ec2",
        "name": "AWS EC2 + RDS",
        "kind": "cloud_vm",
        "cloud_provider": "aws",
        "region": "ap-southeast-1",
        "description": "海外常用：EC2 + RDS PostgreSQL + S3。",
        "template": {
            "compute": "EC2",
            "database": "RDS PostgreSQL",
            "object_storage": "S3",
            "steps": [
                "创建 VPC / security group",
                "Provision RDS and set DATABASE_URL",
                "Deploy Compose on EC2 or ECS/Fargate",
            ],
            "stub": True,
        },
        "is_builtin": True,
    },
    {
        "code": "cloud_azure_vm",
        "name": "Azure VM + Database for PostgreSQL",
        "kind": "cloud_vm",
        "cloud_provider": "azure",
        "region": "eastasia",
        "description": "Azure 虚拟机 + 托管 PostgreSQL。",
        "template": {
            "compute": "Virtual Machine",
            "database": "Azure Database for PostgreSQL",
            "object_storage": "Blob (S3 gateway optional)",
            "steps": ["创建 resource group", "Provision Flexible Server", "Deploy app stack"],
            "stub": True,
        },
        "is_builtin": True,
    },
]


def ensure_deploy_profiles(db: Session) -> list[PlatformDeploymentProfile]:
    existing = {r.code: r for r in db.scalars(select(PlatformDeploymentProfile)).all()}
    changed = False
    for spec in BUILTIN_DEPLOY_PROFILES:
        if spec["code"] in existing:
            continue
        db.add(
            PlatformDeploymentProfile(
                code=spec["code"],
                name=spec["name"],
                kind=spec["kind"],
                cloud_provider=spec.get("cloud_provider"),
                region=spec.get("region"),
                description=spec.get("description"),
                template=spec.get("template") or {},
                status="active",
                is_builtin=True,
                apply_log={},
            )
        )
        changed = True
    if changed:
        db.commit()
    return list(db.scalars(select(PlatformDeploymentProfile).order_by(PlatformDeploymentProfile.code)).all())


def profile_to_public(row: PlatformDeploymentProfile) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "kind": row.kind,
        "cloud_provider": row.cloud_provider,
        "region": row.region,
        "description": row.description,
        "template": row.template or {},
        "status": row.status,
        "is_builtin": row.is_builtin,
        "last_applied_at": row.last_applied_at.isoformat() if row.last_applied_at else None,
        "apply_log": row.apply_log or {},
    }


def apply_deploy_profile(db: Session, profile_id: UUID) -> dict[str, Any]:
    """Record a guided apply — does not SSH into cloud; returns checklist for ops UI."""
    row = db.get(PlatformDeploymentProfile, profile_id)
    if not row:
        raise ValueError("部署档案不存在")
    steps = (row.template or {}).get("steps") or []
    log = {
        "mode": "guided",
        "message": "已生成可视化部署指引；云厂商 API 编排可后续对接。",
        "steps": steps,
        "at": _now().isoformat(),
        "host": platform.node(),
    }
    row.last_applied_at = _now()
    row.apply_log = log
    row.status = "applied"
    db.commit()
    return profile_to_public(row)


# —— Monitoring ——

DEFAULT_ALERT_RULES: list[dict[str, Any]] = [
    {
        "code": "db_latency_high",
        "name": "主库探测延迟过高",
        "metric_code": "db.ping_ms",
        "operator": "gt",
        "threshold": 500,
        "severity": "warning",
        "description": "主库 SELECT 1 延迟超过 500ms",
    },
    {
        "code": "disk_usage_high",
        "name": "磁盘占用偏高",
        "metric_code": "resource.disk_pct",
        "operator": "gte",
        "threshold": 85,
        "severity": "critical",
        "description": "数据盘占用 ≥ 85%",
    },
    {
        "code": "api_error_rate",
        "name": "API 错误率预警",
        "metric_code": "app.error_rate_pct",
        "operator": "gt",
        "threshold": 5,
        "severity": "warning",
        "description": "近窗错误率超过 5%（演示指标）",
    },
]


def ensure_alert_rules(db: Session) -> list[AlertRule]:
    existing = {r.code for r in db.scalars(select(AlertRule)).all()}
    changed = False
    for spec in DEFAULT_ALERT_RULES:
        if spec["code"] in existing:
            continue
        db.add(
            AlertRule(
                **spec,
                enabled=True,
                channels={"console": True, "email": False},
                last_state="ok",
            )
        )
        changed = True
    if changed:
        db.commit()
    return list(db.scalars(select(AlertRule).order_by(AlertRule.code)).all())


def _disk_usage_pct() -> float:
    try:
        if os.name == "nt":
            import shutil

            total, used, _free = shutil.disk_usage(os.path.abspath("."))
            return round(used / total * 100, 2) if total else 0.0
        st = os.statvfs(".")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = total - free
        return round(used / total * 100, 2) if total else 0.0
    except Exception:
        return 0.0


def capture_monitor_snapshot(db: Session) -> dict[str, Any]:
    ping = test_connection_url(get_settings().database_url)
    samples = [
        ("db.ping_ms", "主库探测延迟", "database", "ms", float(ping.get("elapsed_ms") or 0)),
        ("db.up", "主库可用", "database", "bool", 1.0 if ping.get("ok") else 0.0),
        ("resource.disk_pct", "磁盘占用", "resource", "%", _disk_usage_pct()),
        ("app.error_rate_pct", "API 错误率（演示）", "app", "%", 0.5),
        ("system.tenant_count", "租户数", "app", "count", float(db.scalar(select(func.count()).select_from(Tenant)) or 0)),
    ]
    captured = _now()
    metrics_out: list[dict[str, Any]] = []
    for code, name, cat, unit, value in samples:
        m = MonitorMetric(code=code, name=name, category=cat, unit=unit, value=value, labels={}, captured_at=captured)
        db.add(m)
        metrics_out.append(
            {
                "code": code,
                "name": name,
                "category": cat,
                "unit": unit,
                "value": value,
                "captured_at": captured.isoformat(),
            }
        )
    rules = ensure_alert_rules(db)
    firings: list[dict[str, Any]] = []
    metric_map = {m["code"]: m["value"] for m in metrics_out}
    for rule in rules:
        if not rule.enabled:
            continue
        val = metric_map.get(rule.metric_code)
        if val is None:
            continue
        th = float(rule.threshold)
        op = rule.operator
        fired = False
        if op == "gt":
            fired = val > th
        elif op == "gte":
            fired = val >= th
        elif op == "lt":
            fired = val < th
        elif op == "lte":
            fired = val <= th
        elif op == "eq":
            fired = val == th
        rule.last_state = "firing" if fired else "ok"
        if fired:
            rule.last_fired_at = captured
            firings.append(alert_to_public(rule) | {"metric_value": val})
    db.commit()
    return {
        "captured_at": captured.isoformat(),
        "host": platform.node(),
        "platform": platform.platform(),
        "metrics": metrics_out,
        "alerts_firing": firings,
        "db_ping": ping,
    }


def alert_to_public(row: AlertRule) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "metric_code": row.metric_code,
        "operator": row.operator,
        "threshold": float(row.threshold),
        "severity": row.severity,
        "enabled": row.enabled,
        "channels": row.channels or {},
        "last_fired_at": row.last_fired_at.isoformat() if row.last_fired_at else None,
        "last_state": row.last_state,
        "description": row.description,
    }


def bootstrap_ops_catalog(db: Session) -> dict[str, Any]:
    steps = ensure_init_steps(db)
    profiles = ensure_deploy_profiles(db)
    rules = ensure_alert_rules(db)
    return {
        "init_steps": len(steps),
        "deploy_profiles": len(profiles),
        "alert_rules": len(rules),
    }
