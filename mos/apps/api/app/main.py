import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import text

from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.services.observability import RequestObservabilityMiddleware, configure_logging
import app.models  # noqa: F401
import app.models_audit  # noqa: F401
import app.models_wave1  # noqa: F401
import app.models_domain  # noqa: F401
import app.models_saas  # noqa: F401
import app.models_ship  # noqa: F401
import app.models_identity  # noqa: F401
import app.models_i18n  # noqa: F401
import app.models_office  # noqa: F401
import app.models_ops  # noqa: F401
import app.models_recycle  # noqa: F401
import app.models_reference  # noqa: F401
from app.routers.admin_platform import router as admin_router
from app.routers.ai_hub import router as ai_router
from app.routers.commercial import router as commercial_router
from app.routers.connectors import router as connectors_router
from app.routers.dashboards import router as dashboards_router
from app.routers.email_notify import router as email_router
from app.routers.finance_ext import router as finance_router
from app.routers.help import router as help_router
from app.routers.i18n import router as i18n_router
from app.routers.identity import router as identity_router
from app.routers.masterdata import router as masterdata_router
from app.routers.office import router as office_router
from app.routers.operations import router as operations_router
from app.routers.platform import router as platform_router
from app.routers.platform_ops import router as platform_ops_router
from app.routers.recycle import router as recycle_router
from app.routers.reference import router as reference_router
from app.routers.saas import router as saas_router
from app.routers.ship_mgmt import router as ship_router
from app.seed import seed_if_empty, seed_saas_catalog, seed_wave1_demo
from app.seed_demo_flow import seed_full_demo_flow
from app.seed_i18n import seed_i18n
from app.services.platform_ops import bootstrap_ops_catalog
from app.services.reference_data import seed_reference_catalog

log = logging.getLogger("voyageos.main")
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
    databases that predate Alembic and are never stamped; do not add new
    patches here.
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
        conn.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    try:
        _ensure_sqlite_user_identity_columns()
    except Exception:
        log.exception("SQLite compatibility migration failed")
    try:
        with SessionLocal() as db:
            # Catalog / reference data is required for the app to function
            seed_saas_catalog(db)
            seed_i18n(db)
            bootstrap_ops_catalog(db)
            seed_reference_catalog(db)
            # Demo tenants & users only when explicitly enabled (SEED_DEMO=true)
            if settings.seed_demo:
                seed_if_empty(db)
                seed_wave1_demo(db)
                seed_full_demo_flow(db)
            db.commit()
    except Exception:
        log.exception("Startup seed failed")
    yield


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

app.include_router(platform_router, prefix="/api/v1")
app.include_router(platform_ops_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(saas_router, prefix="/api/v1")
app.include_router(masterdata_router, prefix="/api/v1")
app.include_router(reference_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(connectors_router, prefix="/api/v1")
app.include_router(email_router, prefix="/api/v1")
app.include_router(commercial_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(finance_router, prefix="/api/v1")
app.include_router(ship_router, prefix="/api/v1")
app.include_router(dashboards_router, prefix="/api/v1")
app.include_router(identity_router, prefix="/api/v1")
app.include_router(i18n_router, prefix="/api/v1")
app.include_router(office_router, prefix="/api/v1")
app.include_router(help_router, prefix="/api/v1")
app.include_router(recycle_router, prefix="/api/v1")

# Only branding assets are public; backups and other uploads are never statically served
app.mount("/uploads/branding", StaticFiles(directory=str(UPLOAD_ROOT / "branding")), name="branding")


@app.get("/healthz", tags=["Health"])
def healthz():
    return {"status": "ok", "version": settings.app_version}


@app.get("/readyz", tags=["Health"])
def readyz():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:  # noqa: BLE001
        log.exception("Readiness check failed")
        return JSONResponse(status_code=503, content={"status": "not_ready", "error": "dependency check failed"})
