"""Alembic environment for MariOS.

- target_metadata comes from app.db.Base after importing every model module
  (same registration list as app/main.py).
- sqlalchemy.url is taken from app.config.get_settings().database_url
  (DATABASE_URL env var), not hardcoded in alembic.ini, so dev (SQLite) and
  prod (Postgres) share this single env.py.
- fileConfig() is intentionally NOT called: logging is configured by the app
  (app/services/observability.py); Alembic logs flow through the root logger.

Empty-database bootstrap (空库自举)
----------------------------------
历史迁移链是在「表由 ``Base.metadata.create_all()`` 建好」的假设下增量写出来的：
链里有 90+ 张表只被 ``ALTER`` 从未 ``CREATE``（迁移链落后于模型），因此
``alembic upgrade head`` 直接跑在空库上必然报 ``no such table``。

本 env.py 对**完全空库**做一次自举：按 ``Base.metadata`` 建全量表，再把
``alembic_version`` 写到 head，然后迁移链无事可做、正常退出（退出码 0）。
结果 schema 与应用自身 ``create_all`` 的结果逐字节一致，后续新增的 revision
照常在它之上增量执行。详见 ``alembic/README.md``。

自举只对「空库 + ``alembic upgrade head``」生效：
- 已有业务表的库（存量 create_all 库）**不会**被自举，仍按老流程先
  ``alembic stamp head``（见 README）；
- ``stamp`` / ``downgrade`` / ``check`` 等命令不会触发自举；
- 设 ``ALEMBIC_BOOTSTRAP_EMPTY_DB=0`` 可完全关闭自举（仅用于排障）。

Import safety: importing this module (e.g. from tests or tooling) does NOT
connect to the database and does NOT run migrations -- alembic.context only
exposes config/run_migrations while Alembic itself is executing this file.
All context.* access lives behind the guard at the bottom.
"""

from __future__ import annotations

import logging
import os

import sqlalchemy as sa
from sqlalchemy import engine_from_config, pool

from alembic import context
from alembic.script import ScriptDirectory

from app.config import get_settings
from app.db import Base

# 注意：不能用 "alembic.*" 命名的 logger —— alembic/util/messaging.py 给
# "alembic" logger 挂了 NullHandler，会把这里的提示吞掉。改用应用自己的前缀。
log = logging.getLogger("marios.alembic")

# 自举开关：ALEMBIC_BOOTSTRAP_EMPTY_DB=0 关闭空库自举
BOOTSTRAP_ENV_VAR = "ALEMBIC_BOOTSTRAP_EMPTY_DB"

# Register all models on Base.metadata.
#
# This block MUST stay an exact mirror of the import block in app/main.py (and
# tests/conftest.py). If a models_*.py module is missing here, Base.metadata is
# incomplete and `alembic revision --autogenerate` will emit drop_table for every
# table that module defines — it did exactly that once, and the generated
# migration tried to drop ~30 live tables. Diff main.py against this file whenever
# you add a models_*.py module.
import app.models  # noqa: F401,E402
import app.models_audit  # noqa: F401,E402
import app.models_wave1  # noqa: F401,E402
import app.models_vessel_ext  # noqa: F401,E402
import app.models_domain  # noqa: F401,E402
import app.models_saas  # noqa: F401,E402
import app.models_ship  # noqa: F401,E402
import app.models_identity  # noqa: F401,E402
import app.models_i18n  # noqa: F401,E402
import app.models_office  # noqa: F401,E402
import app.models_ops  # noqa: F401,E402
import app.models_recycle  # noqa: F401,E402
import app.models_reference  # noqa: F401,E402
import app.models_task  # noqa: F401,E402
import app.models_onboarding  # noqa: F401,E402
import app.models_finance_ext  # noqa: F401,E402
import app.models_gl  # noqa: F401,E402
import app.models_time_charter  # noqa: F401,E402
import app.models_config  # noqa: F401,E402
import app.models_shipshore  # noqa: F401,E402
import app.models_ai  # noqa: F401,E402
import app.models_report  # noqa: F401,E402
import app.models_jobs  # noqa: F401,E402
import app.models_clause  # noqa: F401,E402
import app.models_cargo  # noqa: F401,E402
import app.models_charter_ext  # noqa: F401,E402
import app.models_rates  # noqa: F401,E402
import app.models_coa  # noqa: F401,E402
import app.models_trading  # noqa: F401,E402
import app.models_pooling  # noqa: F401,E402
import app.models_lightering  # noqa: F401,E402
import app.models_routine  # noqa: F401,E402
import app.models_reference_ext  # noqa: F401,E402
import app.models_interface  # noqa: F401,E402
import app.models_field_perms  # noqa: F401,E402
import app.models_doc  # noqa: F401,E402
import app.models_voyage_ext  # noqa: F401,E402

target_metadata = Base.metadata


# ── 空库自举 ────────────────────────────────────────────────────────────────


def _bootstrap_enabled() -> bool:
    return os.getenv(BOOTSTRAP_ENV_VAR, "1").strip().lower() not in ("0", "false", "no", "off")


def _command_name(config) -> str:
    """当前 alembic 子命令名（upgrade / stamp / downgrade / check ...）。"""
    opts = getattr(config, "cmd_opts", None)
    cmd = getattr(opts, "cmd", None)
    fn = cmd[0] if cmd else None
    return getattr(fn, "__name__", "") or ""


def _revision_argument(config) -> str | None:
    opts = getattr(config, "cmd_opts", None)
    return getattr(opts, "revision", None) if opts is not None else None


def _wants_head_upgrade(config) -> bool:
    """只有「升级到 head」才允许空库自举。

    ``stamp``/``downgrade``/``check`` 语义上都不该建表；``upgrade <rev>``
    指向具体 revision 时同样不自举（避免把非 head 的库直接盖成 head）。
    """
    name = _command_name(config)
    if not name:
        # 编程式调用（无 cmd_opts）→ 视作 upgrade head
        return True
    if name != "upgrade":
        return False
    return _revision_argument(config) in (None, "head", "heads")


def _database_is_empty(connection) -> bool:
    """库中除 alembic_version 外没有任何表 → 空库。"""
    inspector = sa.inspect(connection)
    names = set(inspector.get_table_names())
    if names - {"alembic_version"}:
        return False
    if "alembic_version" in names:
        rows = connection.execute(sa.text("SELECT version_num FROM alembic_version")).fetchall()
        if rows:
            # 已有版本记录 → 说明这个库被迁移过，不是空库
            return False
    return True


def _stamp_head(connection, config) -> None:
    """把 alembic_version 写到当前 head（不改动任何业务表）。"""
    heads = ScriptDirectory.from_config(config).get_heads()
    if not heads:
        raise RuntimeError("alembic: 解析不到 head revision（迁移链为空或已损坏）")
    inspector = sa.inspect(connection)
    if "alembic_version" not in set(inspector.get_table_names()):
        connection.execute(
            sa.text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
    for head in heads:
        exists = connection.execute(
            sa.text("SELECT 1 FROM alembic_version WHERE version_num = :v"), {"v": head}
        ).first()
        if not exists:
            connection.execute(
                sa.text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": head}
            )
    connection.commit()


def _bootstrap_empty_database(connection, config) -> bool:
    """空库 → 按模型建全量表并 stamp 到 head。返回是否发生了自举。"""
    if not _bootstrap_enabled():
        log.info("alembic: 空库自举已关闭（%s=0）", BOOTSTRAP_ENV_VAR)
        return False
    if not _wants_head_upgrade(config):
        return False
    if not _database_is_empty(connection):
        return False
    log.warning(
        "alembic: 检测到空库 —— 按 Base.metadata 建全量表并 stamp 到 head。"
        "历史迁移链不在空库上重放（链落后于模型，详见 alembic/README.md）。"
    )
    Base.metadata.create_all(bind=connection)
    _stamp_head(connection, config)
    return True


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
        # 空库自举必须发生在 context.configure() 之前：这样迁移链看到的
        # 「当前版本」已经是 head，upgrade head 就是一次空操作（退出码 0）。
        _bootstrap_empty_database(connection, config)
        # 关键：configure() 之前必须保证连接上没有未提交事务。自举检查会执行
        # 探测 SQL，SQLAlchemy 2.x 会隐式开事务；Alembic 一旦发现连接「已在
        # 事务中」就当成外部事务，per-migration 事务不再提交，连接关闭时整批
        # 迁移被回滚（SQLite 上表现为「列加了、alembic_version 没更新」）。
        if connection.in_transaction():
            connection.commit()
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
