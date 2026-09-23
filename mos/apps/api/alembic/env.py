"""Alembic environment for MariOS.

- target_metadata comes from app.db.Base after importing every model module
  (same registration list as app/main.py).
- sqlalchemy.url is taken from app.config.get_settings().database_url
  (DATABASE_URL env var), not hardcoded in alembic.ini, so dev (SQLite) and
  prod (Postgres) share this single env.py.
- fileConfig() is intentionally NOT called: logging is configured by the app
  (app/services/observability.py); Alembic logs flow through the root logger.

Import safety: importing this module (e.g. from tests or tooling) does NOT
connect to the database and does NOT run migrations -- alembic.context only
exposes config/run_migrations while Alembic itself is executing this file.
All context.* access lives behind the guard at the bottom.
"""

from __future__ import annotations

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.config import get_settings
from app.db import Base

# Register all models on Base.metadata (mirror of the import block in app/main.py)
import app.models  # noqa: F401,E402
import app.models_audit  # noqa: F401,E402
import app.models_domain  # noqa: F401,E402
import app.models_finance_ext  # noqa: F401,E402
import app.models_i18n  # noqa: F401,E402
import app.models_identity  # noqa: F401,E402
import app.models_office  # noqa: F401,E402
import app.models_ops  # noqa: F401,E402
import app.models_recycle  # noqa: F401,E402
import app.models_reference  # noqa: F401,E402
import app.models_saas  # noqa: F401,E402
import app.models_ship  # noqa: F401,E402
import app.models_wave1  # noqa: F401,E402
import app.models_gl  # noqa: F401,E402
import app.models_time_charter  # noqa: F401,E402
import app.models_config  # noqa: F401,E402
import app.models_shipshore  # noqa: F401,E402
import app.models_ai  # noqa: F401,E402
import app.models_report  # noqa: F401,E402

target_metadata = Base.metadata


def run_migrations_offline(config) -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online(config) -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot ALTER COLUMN; batch mode recreates the table instead
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


def run_migrations() -> None:
    """Entry point used when Alembic execs this file."""
    config = context.config
    # The ini placeholder URL is always overridden from app config (DATABASE_URL).
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    if context.is_offline_mode():
        run_migrations_offline(config)
    else:
        run_migrations_online(config)


# context.config exists only while Alembic is running this file; a plain
# import (tests, tooling) takes the no-run path.
if hasattr(context, "config"):
    run_migrations()
