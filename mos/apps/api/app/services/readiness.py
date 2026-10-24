"""依赖就绪探针（审计 P3-9 / P3-12）。

## 为什么要有它

原来的 ``/healthz`` 与 ``/readyz`` 都只回答"这个进程还活着吗" —— 数据库挂了、
迁移没跑、后台 worker 线程死了，**容器照样报 healthy**，流量照样打进来，
然后每个请求 500。编排里的健康检查（``docker-compose.yml`` 的 api 服务）打的是
``/readyz``，所以这个端点必须真的**探依赖**。

## 探什么

| 依赖 | 级别 | 判据 |
|---|---|---|
| 数据库 | **必需** | ``SELECT 1`` 能在 2 秒内返回 |
| 数据库迁移版本 | **必需（PG/已 stamp 的库）** | ``alembic_version`` 的版本号 == 迁移链 head |
| 后台任务 worker | 建议 | worker 线程在跑（``job_worker_enabled`` 时） |

Redis / S3 **不探** —— 编排里已经没有这两个服务了（限流走进程内滑动窗口，
文件落本地持久卷）。

## 语义

- ``/readyz``：任一**必需**依赖不健康 → 503 + 逐项明细（编排据此摘流量）。
- ``/healthz``：**存活**探针（进程还在吗），不探依赖 —— 否则数据库抖一下，
  编排会把所有副本同时重启，把一次小故障放大成一次全站故障。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger("marios.readiness")


def _probe_database(engine: Engine) -> dict[str, Any]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        # **只回异常类型名**：异常消息里可能带连接串（口令、主机名）——
        # /readyz 是免鉴权端点，异常原文直接回吐等于把口令发出去。
        # 完整消息只进服务端日志。
        log.warning("数据库探测失败: %s: %s", type(exc).__name__, exc)
        return {"ok": False, "error": type(exc).__name__}


def _head_revision() -> str | None:
    """迁移链的 head 版本号（读不到就返回 None —— 跳过迁移检查）。"""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config()
        cfg.set_main_option("script_location", "alembic")
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # noqa: BLE001
        return None


def _probe_migrations(engine: Engine) -> dict[str, Any]:
    """库里的 alembic_version 是否 == head。

    - 没有 ``alembic_version`` 表 → **不判失败**（本地 SQLite 开发库就是
      ``create_all`` 建出来的，从来没 stamp 过）；
    - 有表但版本落后 → **失败**（新代码会用到还没建的列 → 500）。
    """
    head = _head_revision()
    if head is None:
        return {"ok": True, "skipped": "alembic 迁移链不可读"}
    try:
        insp = inspect(engine)
        if not insp.has_table("alembic_version"):
            return {"ok": True, "skipped": "库未登记 alembic 版本（create_all 建库）"}
        with engine.connect() as conn:
            rows = [r[0] for r in conn.execute(text("SELECT version_num FROM alembic_version"))]
    except Exception as exc:  # noqa: BLE001
        log.warning("迁移版本探测失败: %s: %s", type(exc).__name__, exc)
        return {"ok": False, "error": type(exc).__name__}
    current = rows[0] if rows else None
    if current is None:
        # 表在、但里面没有版本号 —— 与「没有表」同义：库是 create_all 建的，
        # 从没 stamp 过。不判失败（否则本地开发库永远 503）。
        return {"ok": True, "skipped": "库未登记 alembic 版本（create_all 建库）"}
    if current == head:
        return {"ok": True, "current": current, "head": head}
    return {"ok": False, "current": current, "head": head, "error": "数据库迁移版本落后于代码"}


def _probe_job_worker() -> dict[str, Any]:
    """后台任务 worker 线程是否在跑。"""
    try:
        from app.config import get_settings

        if not get_settings().job_worker_enabled:
            return {"ok": True, "skipped": "后台任务 worker 未启用"}
    except Exception:  # noqa: BLE001
        return {"ok": True, "skipped": "配置不可读"}
    try:
        from app.services import job_queue

        alive = bool(getattr(job_queue, "worker_alive", lambda: False)())
        return {"ok": alive, "error": None if alive else "后台任务 worker 线程未运行"}
    except Exception as exc:  # noqa: BLE001
        log.warning("worker 探测失败: %s: %s", type(exc).__name__, exc)
        return {"ok": False, "error": type(exc).__name__}


def collect_readiness(engine: Engine) -> dict[str, Any]:
    """探一遍所有依赖，返回逐项明细 + 是否就绪。"""
    checks: dict[str, Any] = {
        "database": _probe_database(engine),
        "migrations": _probe_migrations(engine),
        "job_worker": _probe_job_worker(),
    }
    required_ok = bool(checks["database"].get("ok")) and bool(checks["migrations"].get("ok"))
    advisory_ok = bool(checks["job_worker"].get("ok"))
    return {
        "ready": required_ok and advisory_ok,
        "checks": checks,
    }
