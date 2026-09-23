import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Isolate tests from developer SQLite file
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["LICENSE_DEV_UNLOCK"] = "all"
os.environ["JWT_SECRET"] = "test-secret"
# Demo data is seeded by the db_engine fixture; rate limiting is exercised in test_security_fixes.py
os.environ["SEED_DEMO"] = "true"
os.environ["RATE_LIMIT_ENABLED"] = "false"

from app.db import Base, get_db  # noqa: E402
import app.models  # noqa: E402, F401
import app.models_wave1  # noqa: E402, F401
import app.models_domain  # noqa: E402, F401
import app.models_saas  # noqa: E402, F401
import app.models_ship  # noqa: E402, F401
import app.models_identity  # noqa: E402, F401
import app.models_i18n  # noqa: E402, F401
import app.models_office  # noqa: E402, F401
import app.models_ops  # noqa: E402, F401
import app.models_recycle  # noqa: E402, F401
import app.models_reference  # noqa: E402, F401
import app.models_finance_ext  # noqa: E402, F401
import app.models_gl  # noqa: E402, F401
import app.models_time_charter  # noqa: E402, F401
import app.models_config  # noqa: E402, F401
import app.models_shipshore  # noqa: E402, F401
import app.models_ai  # noqa: E402, F401
import app.models_report  # noqa: E402, F401
from app.main import app as fastapi_app  # noqa: E402
from app.seed import seed_if_empty, seed_saas_catalog, seed_wave1_demo  # noqa: E402
from app.seed_demo_flow import seed_full_demo_flow  # noqa: E402
from app.seed_i18n import seed_i18n  # noqa: E402
from app.services.platform_ops import bootstrap_ops_catalog  # noqa: E402
from app.services.reference_data import seed_reference_catalog  # noqa: E402


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSession() as db:
        seed_if_empty(db)
        seed_wave1_demo(db)
        seed_saas_catalog(db)
        seed_full_demo_flow(db)
        seed_i18n(db)
        bootstrap_ops_catalog(db)
        seed_reference_catalog(db)
        db.commit()
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def client(db_engine) -> Generator[TestClient, None, None]:
    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)

    def _override_db() -> Generator[Session, None, None]:
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = _override_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@demo.marios", "password": "Demo1234!", "tenant_code": "demo"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def oauth_stub(monkeypatch):
    """Enable dev stub OAuth for tests that exercise the stub flow (off by default)."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "oauth_allow_stub", True)


@pytest.fixture()
def mail_capture(monkeypatch):
    """Capture send_mail kwargs so tests can extract challenge tokens from email links."""
    import re
    from types import SimpleNamespace

    from app.routers import identity as identity_router

    sent: list[dict] = []
    real_send_mail = identity_router.send_mail

    def _capture(db, **kwargs):
        sent.append(kwargs)
        return real_send_mail(db, **kwargs)

    monkeypatch.setattr(identity_router, "send_mail", _capture)

    def _token(purpose: str) -> str:
        for kw in reversed(sent):
            if kw.get("purpose") == purpose:
                m = re.search(r"token=([^\s&]+)", kw.get("body") or "")
                if m:
                    return m.group(1)
        raise AssertionError(f"no mail captured for purpose={purpose}")

    return SimpleNamespace(sent=sent, extract_token=_token)
