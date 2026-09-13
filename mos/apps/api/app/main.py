from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy import text

from app.config import get_settings
from app.db import Base, SessionLocal, engine
import app.models  # noqa: F401
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
settings = get_settings()
UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
(UPLOAD_ROOT / "branding").mkdir(parents=True, exist_ok=True)


def _ensure_sqlite_user_identity_columns() -> None:
    """Best-effort ALTER for existing SQLite developer DBs."""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
        if "email_verified_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_verified_at DATETIME"))
        if "last_login_at" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_login_at DATETIME"))
        for table, col in (
            ("vessels", "deleted_at"),
            ("ports", "deleted_at"),
            ("counterparties", "deleted_at"),
        ):
            tcols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
            if tcols and col not in tcols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} DATETIME"))
        conn.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    try:
        _ensure_sqlite_user_identity_columns()
    except Exception:
        pass
    try:
        with SessionLocal() as db:
            seed_if_empty(db)
            seed_wave1_demo(db)
            seed_saas_catalog(db)
            seed_full_demo_flow(db)
            seed_i18n(db)
            bootstrap_ops_catalog(db)
            seed_reference_catalog(db)
            db.commit()
    except Exception:
        pass
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.5.2-i18n",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

origins = [o.strip() for o in settings.api_cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_ROOT)), name="uploads")


@app.get("/healthz", tags=["Health"])
def healthz():
    return {"status": "ok", "version": "1.5.2-i18n"}


@app.get("/readyz", tags=["Health"])
def readyz():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "not_ready", "error": str(exc)}
