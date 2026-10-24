import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import text

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.services.observability import RequestObservabilityMiddleware, configure_logging, install_slow_query_log
from app.services.security_headers import SecurityHeadersMiddleware
from app.services.error_envelope import install_error_handlers
from app.services.audit_middleware import AuditTrailMiddleware
from app.services.ratelimit import RateLimitMiddleware
from app.services.readiness import collect_readiness
import app.models  # noqa: F401
import app.models_audit  # noqa: F401
import app.models_wave1  # noqa: F401
import app.models_vessel_ext  # noqa: F401
import app.models_domain  # noqa: F401
import app.models_saas  # noqa: F401
import app.models_ship  # noqa: F401
import app.models_identity  # noqa: F401
import app.models_i18n  # noqa: F401
import app.models_office  # noqa: F401
import app.models_ops  # noqa: F401
import app.models_recycle  # noqa: F401
import app.models_reference  # noqa: F401
import app.models_task  # noqa: F401
import app.models_onboarding  # noqa: F401
import app.models_finance_ext  # noqa: F401
import app.models_gl  # noqa: F401
import app.models_time_charter  # noqa: F401
import app.models_config  # noqa: F401
import app.models_shipshore  # noqa: F401
import app.models_ai  # noqa: F401
import app.models_report  # noqa: F401
import app.models_jobs  # noqa: F401
import app.models_clause  # noqa: F401
import app.models_cargo  # noqa: F401
import app.models_charter_ext  # noqa: F401
import app.models_rates  # noqa: F401
import app.models_coa  # noqa: F401
import app.models_trading  # noqa: F401
import app.models_pooling  # noqa: F401
import app.models_lightering  # noqa: F401
import app.models_reference_ext  # noqa: F401
import app.models_interface  # noqa: F401
import app.models_field_perms  # noqa: F401
import app.models_doc  # noqa: F401
import app.models_voyage_ext  # noqa: F401
from app.routers.admin_platform import router as admin_router
from app.routers.ai_chat import router as ai_chat_router
from app.routers.ai_actions import router as ai_actions_router
from app.routers.ai_assist import router as ai_assist_router
from app.routers.metrics import router as metrics_router
from app.routers.ai_hub import router as ai_router
from app.routers.webhooks import router as webhooks_router
from app.routers.market_data import positions_router as market_positions_router
from app.routers.market_data import router as market_data_router
from app.routers.email_intelligence import router as email_intel_router
from app.routers.report import router as report_router
from app.routers.compliance import router as compliance_router
from app.routers.commercial import router as commercial_router
from app.routers.time_charter import router as time_charter_router
from app.routers.config import router as config_router
from app.routers.meta import router as meta_router
from app.routers.connectors import router as connectors_router
from app.routers.dashboards import router as dashboards_router
from app.routers.email_notify import router as email_router
from app.routers.exceptions import router as exceptions_router
from app.routers.exports import router as exports_router
from app.routers.imports import router as imports_router
from app.routers.files import router as files_router
from app.routers.finance_ext import router as finance_router
from app.routers.finance_depth import router as finance_depth_router
from app.routers.payment_batches import router as payment_batches_router
from app.routers.payment_export import router as payment_export_router
from app.routers.gl_management import router as gl_management_router
from app.routers.laytimes import router as laytimes_router
from app.routers.claims import router as claims_router
from app.routers.invoices import router as invoices_router
from app.routers.mirror_invoices import router as mirror_invoices_router
from app.routers.approvals import router as approvals_router
from app.routers.bunker import router as bunker_router
from app.routers.portcosts import router as portcosts_router
from app.routers.rates import router as rates_router
from app.routers.guides import router as guides_router
from app.routers.help import router as help_router
from app.routers.home import router as home_router
from app.routers.i18n import router as i18n_router
from app.routers.identity import router as identity_router
from app.routers.marilink import router as marilink_router
from app.routers.masterdata import router as masterdata_router
from app.routers.office import router as office_router
from app.routers.onboarding import router as onboarding_router
from app.routers.operations import router as operations_router
from app.routers.platform import router as platform_router
from app.routers.platform_ops import router as platform_ops_router
from app.routers.recycle import router as recycle_router
from app.routers.reference import router as reference_router
from app.routers.saas import router as saas_router
from app.routers.ship_mgmt import router as ship_router
from app.routers.vessel_detail import router as vessel_detail_router
from app.routers.tasks import router as tasks_router
from app.routers.user_state import router as user_state_router
from app.routers.cargo import router as cargo_router
from app.routers.scheduling import router as scheduling_router
from app.routers.coa import router as coa_router
from app.routers.trading import router as trading_router
from app.routers.pooling import router as pooling_router
from app.routers.lightering import router as lightering_router
from app.routers.masterdata_ext import router as masterdata_ext_router
from app.routers.interface_messages import router as interface_messages_router
from app.routers.field_perms import router as field_perms_router
from app.routers.udf import router as udf_router
from app.routers.docs import router as docs_router
from app.seed import seed_if_empty, seed_saas_catalog, seed_wave1_demo
from app.seed_demo_flow import seed_full_demo_flow, stamp_demo_attribution
from app.seed_masterdata_gaps import seed_masterdata_gaps
from app.seed_i18n import seed_i18n
from app.services.platform_ops import bootstrap_ops_catalog
from app.services.reference_data import seed_reference_catalog
from app.services.clause_library import seed_clause_pack
from app.services.report_builder import seed_report_datasets
from app.services.config_service import seed_config_flag_presets

log = logging.getLogger("marios.main")
# Structured logging is configured at import time so every module logger
# (including uvicorn's) emits the same key=value format from the start.
configure_logging()
settings = get_settings()
UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
(UPLOAD_ROOT / "branding").mkdir(parents=True, exist_ok=True)


def _ensure_sqlite_user_identity_columns() -> None:
    """Best-effort ALTER for existing SQLite developer DBs.

    Transition note (P3): new schema changes go through Alembic (see
    alembic/README.md). These guarded ALTER patches are kept for existing dev
    databases that predate Alembic and are never stamped; new patches are added
    only when a dev SQLite database in the wild needs the column (e.g.
    attachments versioning).
    """
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
        if "email_verified_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_verified_at DATETIME"))
        if "last_login_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_login_at DATETIME"))
        if "password_version" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN password_version INTEGER DEFAULT 1"))
        api_key_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(api_keys)")).fetchall()}
        if api_key_cols:
            if "user_id" not in api_key_cols:
                conn.execute(text("ALTER TABLE api_keys ADD COLUMN user_id CHAR(32)"))
            if "expires_at" not in api_key_cols:
                conn.execute(text("ALTER TABLE api_keys ADD COLUMN expires_at DATETIME"))
        for table, col in (
            ("vessels", "deleted_at"),
            ("ports", "deleted_at"),
            ("counterparties", "deleted_at"),
        ):
            tcols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            if tcols and col not in tcols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} DATETIME"))
        tenant_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(tenants)")).fetchall()}
        if tenant_cols:
            for col, decl in (
                ("ms_client_id", "TEXT"),
                ("ms_client_secret", "TEXT"),
                ("ms_tenant", "TEXT"),
                ("ms_override_enabled", "BOOLEAN DEFAULT 0"),
            ):
                if col not in tenant_cols:
                    conn.execute(text(f"ALTER TABLE tenants ADD COLUMN {col} {decl}"))
        policy_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(tenant_auth_policies)")).fetchall()}
        if policy_cols:
            for col, decl in (
                ("microsoft_tenant_hint", "TEXT"),
                ("google_hosted_domain", "TEXT"),
                ("sso_notes", "TEXT"),
            ):
                if col not in policy_cols:
                    conn.execute(text(f"ALTER TABLE tenant_auth_policies ADD COLUMN {col} {decl}"))
        # P0 commercial columns (models_domain.py); each guarded so reruns are no-ops
        for table, col, decl in (
            ("charters", "demurrage_rate", "NUMERIC(12, 2)"),
            ("charters", "despatch_rate", "NUMERIC(12, 2)"),
            ("charters", "laytime_terms", "VARCHAR(32)"),
            ("charters", "cp_form", "VARCHAR(32)"),
            ("charters", "freight_rate", "NUMERIC(14, 4)"),
            ("charters", "freight_basis", "VARCHAR(16)"),
            ("charters", "cargo_qty", "NUMERIC(18, 3)"),
            ("charters", "load_rate_pd", "NUMERIC(12, 2)"),
            ("charters", "disch_rate_pd", "NUMERIC(12, 2)"),
            ("charters", "address_comm_pct", "NUMERIC(5, 2)"),
            ("charters", "brokerage_pct", "NUMERIC(5, 2)"),
            ("charters", "hire_per_day", "NUMERIC(12, 2)"),
            ("charters", "hire_cycle_days", "INTEGER"),
            ("charters", "delivery_port_id", "CHAR(32)"),
            ("charters", "redelivery_port_id", "CHAR(32)"),
            ("charters", "delivery_at", "DATETIME"),
            ("charters", "redelivery_at", "DATETIME"),
            ("charters", "ets_responsibility", "VARCHAR(16)"),
            ("port_calls", "nor_at", "DATETIME"),
            ("port_calls", "eosp_at", "DATETIME"),
            ("port_calls", "bl_date", "DATETIME"),
            ("invoices", "base_amount", "NUMERIC(18, 2)"),
            ("invoices", "fx_rate", "NUMERIC(18, 6)"),
            ("invoices", "credit_note_of_id", "CHAR(32)"),
            ("claims", "deductions", "JSON"),
            ("bunker_orders", "bdn_qty", "NUMERIC(18, 3)"),
            ("bunker_orders", "density_kg_m3", "NUMERIC(10, 2)"),
            ("bunker_orders", "sulphur_pct", "NUMERIC(5, 3)"),
            ("bunker_orders", "bdn_date", "DATETIME"),
            ("bunker_orders", "supplier", "VARCHAR(128)"),
            ("bunker_orders", "barge", "VARCHAR(128)"),
            ("ports", "holidays", "JSON"),
            ("ports", "is_eu", "BOOLEAN"),
            # P1 commercial columns
            ("coa_liftings", "voyage_id", "CHAR(32)"),
            ("coa_liftings", "laycan_from", "DATETIME"),
            ("coa_liftings", "laycan_to", "DATETIME"),
            # P2 operations columns: noon-report weather observations
            ("noon_reports", "wind_bf", "NUMERIC(4, 1)"),
            ("noon_reports", "sea_state", "VARCHAR(32)"),
            ("noon_reports", "current_kn", "NUMERIC(5, 2)"),
            # ERP counterparty fields
            ("counterparties", "address", "TEXT"),
            ("counterparties", "tax_id", "TEXT"),
            ("counterparties", "swift_code", "TEXT"),
            ("counterparties", "registration_no", "TEXT"),
            ("counterparties", "website", "TEXT"),
            ("counterparties", "phone", "TEXT"),
            ("counterparties", "email", "TEXT"),
            ("counterparties", "notes", "TEXT"),
        ):
            try:
                tcols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
                if tcols and col not in tcols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {decl}"))
            except Exception:  # noqa: BLE001
                log.exception("SQLite migration patch failed for %s.%s", table, col)
        try:
            conn.execute(text("UPDATE ports SET is_eu = 0 WHERE is_eu IS NULL"))
        except Exception:  # noqa: BLE001
            log.exception("SQLite migration backfill failed for ports.is_eu")
        # Attachment versioning columns (certificate file history)
        try:
            att_cols = {r[1] for r in conn.execute(text("PRAGMA table_info(attachments)")).fetchall()}
            if att_cols:
                for col, decl in (
                    ("version_no", "INTEGER"),
                    ("is_current", "BOOLEAN"),
                    ("note", "TEXT"),
                ):
                    if col not in att_cols:
                        conn.execute(text(f"ALTER TABLE attachments ADD COLUMN {col} {decl}"))
                conn.execute(text("UPDATE attachments SET version_no = 1 WHERE version_no IS NULL"))
                conn.execute(text("UPDATE attachments SET is_current = 1 WHERE is_current IS NULL"))
        except Exception:  # noqa: BLE001
            log.exception("SQLite migration patch failed for attachments versioning")
        conn.commit()


def _apply_rebrand_data_patches() -> None:
    """VoyageOS -> MariOS rebrand: rewrite seeded demo emails and default branding.

    Pure UPDATE statements guarded by WHERE on the old value, so reruns are
    no-ops on any database (SQLite dev or Postgres deploy).
    """
    stmts = (
        "UPDATE users SET email = REPLACE(email, 'demo.voyageos', 'demo.marios') WHERE email LIKE '%demo.voyageos%'",
        "UPDATE users SET email = REPLACE(email, 'voyageos.platform', 'marios.platform') WHERE email LIKE '%voyageos.platform%'",
        "UPDATE platform_branding SET product_name = 'MariOS' WHERE product_name = 'VoyageOS'",
    )
    with engine.connect() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:  # noqa: BLE001
                log.exception("Rebrand data patch failed: %s", stmt)
        conn.commit()


def _apply_wording_patches() -> None:
    """文案整改（幂等）：中文「大屏/实时大屏」统一为「数据看板」。

    代码/种子已改，这里同步存量 i18n 行（ui_messages.text），
    任何部署升级后可见文案一次性迁移；REPLACE 幂等，重复执行无副作用。
    """
    stmts = (
        "UPDATE ui_messages SET text = REPLACE(REPLACE(REPLACE(text, '实时大屏', '数据看板'), '数据大屏', '数据看板'), '大屏', '数据看板') WHERE text LIKE '%大屏%'",
        # 修复 tab 标题误显示 key 后缀（如 "tab fleet" → "Fleet"）
        "UPDATE ui_messages SET text = 'Fleet' WHERE msg_key = 'page.ship.tab_fleet' AND (text LIKE '%tab%' OR text = '')",
        "UPDATE ui_messages SET text = 'Certificate overview' WHERE msg_key = 'page.ship.tab_certs' AND (text LIKE '%tab%' OR text = '')",
    )
    with engine.connect() as conn:
        for stmt in stmts:
            try:
                conn.execute(text(stmt))
            except Exception:  # noqa: BLE001
                log.exception("Wording patch failed: %s", stmt)
        conn.commit()


def _create_all_safe() -> None:
    """建表 —— 多副本部署下不炸（P2-8）。

    Postgres 上多个 API 副本同时启动会**并发 CREATE TABLE** → DuplicateTableError
    → 整个副本起不来（"滚动发布时随机一个 pod 挂"）。

    处理方式：

    1. Postgres：先查关键表是否已存在 —— 存在说明 migrate 服务
       （``alembic upgrade head``）已经建好 schema，**直接跳过 create_all**
       （迁移是 schema 的唯一真源，不该被 create_all 覆盖）；
    2. 表不存在才 create_all，并把 "DuplicateTable / already exists" 当成
       "另一个副本抢先建好了"——不是错误；
    3. 其它异常照旧抛出（不能把建表失败静默掉）。
    """
    try:
        if not str(engine.url).startswith("sqlite"):
            from sqlalchemy import inspect

            insp = inspect(engine)
            if insp.has_table("tenants") and insp.has_table("invoices"):
                log.info("Postgres: schema 已存在（由 migrate 服务管理），跳过 create_all")
                return
        Base.metadata.create_all(bind=engine)
    except Exception as exc:  # noqa: BLE001
        text_repr = str(exc).lower()
        if "duplicatetable" in type(exc).__name__.lower() or "already exists" in text_repr:
            log.info("create_all: 表已由并发副本创建，跳过（%s）", type(exc).__name__)
            return
        log.exception("create_all 失败")
        raise


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.slow_query_ms > 0:
        install_slow_query_log(settings.slow_query_ms)
    _create_all_safe()
    try:
        _ensure_sqlite_user_identity_columns()
    except Exception:
        log.exception("SQLite compatibility migration failed")
    try:
        _apply_rebrand_data_patches()
    except Exception:
        log.exception("Rebrand data patch failed")
    try:
        _apply_wording_patches()
    except Exception:
        log.exception("Wording data patch failed")
    try:
        if not settings.startup_seed:
            log.info("STARTUP_SEED=false — 跳过启动种子数据")
        else:
            with SessionLocal() as db:
                # Catalog / reference data is required for the app to function
                seed_saas_catalog(db)
                seed_i18n(db)
                bootstrap_ops_catalog(db)
                seed_reference_catalog(db)
                seed_clause_pack(db)
                seed_report_datasets(db)
                seed_config_flag_presets(db)
                # 预置燃油区（ECA / EU ETS 多边形）—— estimate_enrich 的 ECA 天数
                # 与 EU 份额推断依赖这些区划；幂等（按 zone_name 去重）。
                from app.services.fuel_zone_service import seed_preset_zones

                seed_preset_zones(db)
                # Demo tenants & users only when explicitly enabled (SEED_DEMO=true)
                if settings.seed_demo:
                    seed_if_empty(db)
                    seed_wave1_demo(db)
                    seed_full_demo_flow(db)
                    seed_masterdata_gaps(db)
                    # 演示数据补「创建人 / 修改人」—— 否则归属条永远显示「—」。
                    from sqlalchemy import select as _sel

                    from app.models import Tenant as _Tenant

                    demo_tenant = db.scalar(_sel(_Tenant).where(_Tenant.code == "demo"))
                    if demo_tenant is not None:
                        stamp_demo_attribution(db, demo_tenant)
                db.commit()
    except Exception:
        log.exception("Startup seed failed")
    # Phase 0 后台作业 worker（webhook 投递等）；测试环境由 conftest 关闭
    job_stop = threading.Event()
    job_thread = None
    if settings.job_worker_enabled:
        from app.services.job_queue import run_worker
        from app.services.report_scheduler import install_scheduler, register_handlers
        from app.services.backup_scheduler import (
            install_scheduler as install_backup_scheduler,
            register_handlers as register_backup_handlers,
        )

        register_handlers()
        register_backup_handlers()
        try:
            with SessionLocal() as db:
                install_scheduler(db)
        except Exception:
            log.exception("report schedule bootstrap failed")
        try:
            with SessionLocal() as db:
                install_backup_scheduler(db)
        except Exception:
            log.exception("backup schedule bootstrap failed")
        job_thread = threading.Thread(target=run_worker, args=(job_stop,), name="marios-jobs", daemon=True)
        job_thread.start()
    yield
    job_stop.set()
    if job_thread is not None:
        job_thread.join(timeout=5)


_is_production = settings.env.lower() == "production"

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=None if _is_production else "/docs",
    openapi_url=None if _is_production else "/openapi.json",
)

origins = [o.strip() for o in settings.api_cors_origins.split(",") if o.strip()] or ["http://localhost:3000"]
# allow_credentials is never combined with a wildcard origin
_allow_credentials = "*" not in origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Outermost middleware (added last): request-id propagation + access logging.
app.add_middleware(RequestObservabilityMiddleware)
# 写操作自动留痕（审计 P1-19）—— 显式 audit() 之外的兜底全覆盖。
app.add_middleware(AuditTrailMiddleware)
# 路径级限流（审计 P1-20）—— 导出 / PDF / 报表 / AI 这些高成本端点原来无限流。
app.add_middleware(RateLimitMiddleware)
# 安全响应头（CSP / nosniff / HSTS…）—— 见 services/security_headers.py
app.add_middleware(SecurityHeadersMiddleware)
# 统一错误信封：403/409 的 detail 字典一律补人话 message（P1-3）
install_error_handlers(app)

app.include_router(platform_router, prefix="/api/v1")
app.include_router(platform_ops_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(saas_router, prefix="/api/v1")
app.include_router(masterdata_router, prefix="/api/v1")
app.include_router(reference_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(ai_chat_router, prefix="/api/v1")
app.include_router(ai_actions_router, prefix="/api/v1")
app.include_router(ai_assist_router, prefix="/api/v1")
app.include_router(metrics_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(market_data_router, prefix="/api/v1")
app.include_router(market_positions_router, prefix="/api/v1")
app.include_router(email_intel_router, prefix="/api/v1")
app.include_router(report_router, prefix="/api/v1")
app.include_router(compliance_router, prefix="/api/v1")
app.include_router(connectors_router, prefix="/api/v1")
app.include_router(email_router, prefix="/api/v1")
app.include_router(commercial_router, prefix="/api/v1")
app.include_router(time_charter_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(meta_router, prefix="/api/v1")
app.include_router(marilink_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(finance_router, prefix="/api/v1")
app.include_router(finance_depth_router, prefix="/api/v1")
app.include_router(payment_batches_router, prefix="/api/v1")
app.include_router(payment_export_router, prefix="/api/v1")
app.include_router(gl_management_router, prefix="/api/v1")
app.include_router(laytimes_router, prefix="/api/v1")
app.include_router(claims_router, prefix="/api/v1")
app.include_router(invoices_router, prefix="/api/v1")
app.include_router(mirror_invoices_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(bunker_router, prefix="/api/v1")
app.include_router(portcosts_router, prefix="/api/v1")
app.include_router(rates_router, prefix="/api/v1")
app.include_router(ship_router, prefix="/api/v1")
app.include_router(vessel_detail_router, prefix="/api/v1")
app.include_router(files_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(user_state_router, prefix="/api/v1")
app.include_router(home_router, prefix="/api/v1")
app.include_router(exceptions_router, prefix="/api/v1")
app.include_router(dashboards_router, prefix="/api/v1")
app.include_router(identity_router, prefix="/api/v1")
app.include_router(i18n_router, prefix="/api/v1")
app.include_router(office_router, prefix="/api/v1")
app.include_router(help_router, prefix="/api/v1")
app.include_router(recycle_router, prefix="/api/v1")
app.include_router(guides_router, prefix="/api/v1")
app.include_router(onboarding_router, prefix="/api/v1")
app.include_router(exports_router, prefix="/api/v1")
app.include_router(imports_router, prefix="/api/v1")
app.include_router(cargo_router, prefix="/api/v1")
app.include_router(scheduling_router, prefix="/api/v1")
app.include_router(coa_router, prefix="/api/v1")
app.include_router(trading_router, prefix="/api/v1")
app.include_router(pooling_router, prefix="/api/v1")
app.include_router(lightering_router, prefix="/api/v1")
app.include_router(masterdata_ext_router, prefix="/api/v1")
app.include_router(interface_messages_router, prefix="/api/v1")
app.include_router(field_perms_router, prefix="/api/v1")
app.include_router(udf_router, prefix="/api/v1")
app.include_router(docs_router, prefix="/api/v1")

# Only branding assets are public; backups and other uploads are never statically served
app.mount("/uploads/branding", StaticFiles(directory=str(UPLOAD_ROOT / "branding")), name="branding")


@app.get("/healthz", tags=["Health"])
def healthz():
    """**存活**探针 —— 只回答"进程还在吗"，不探依赖。

    故意不探数据库：依赖抖一下时如果这里也报 unhealthy，编排会把所有副本
    同时重启，一次小故障就被放大成全站故障。依赖健康看 ``/readyz``。
    """
    return {"status": "ok", "version": settings.app_version}


@app.get("/readyz", tags=["Health"])
def readyz():
    """**就绪**探针 —— 真的探依赖（审计 P3-9 / P3-12）。

    编排的 api 健康检查打的就是这个端点：数据库不通、迁移版本落后、
    后台任务线程死了 → 503 → 编排摘流量/不再路由进来。
    """
    result = collect_readiness(engine)
    if not result["ready"]:
        log.warning("Readiness check failed: %s", result["checks"])
        return JSONResponse(status_code=503, content={"status": "not_ready", **result})
    return {"status": "ready", **result}
