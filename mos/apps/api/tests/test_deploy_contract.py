"""部署契约的静态断言（部署 / 运维专项）。

这些断言锁住的是「改了就会出事、又很难在功能测试里发现」的东西：
- `.env.example` 里不能有生效的开发后门（许可旁路 / OAuth 桩后门）；
- compose 必须显式要求密钥，缺值直接报错（不能退化成每进程随机密钥）；
- 镜像里必须带 Alembic 与 Chromium（否则生产库拿不到新列、PDF 谎报可用）；
- 空库 `alembic upgrade head` 必须退出 0，且 `alembic check` 无漂移。

纯静态断言 + 一次真实的空库迁移，不依赖网络与 Docker。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path



MOS_ROOT = Path(__file__).resolve().parents[3]          # mos/
API_ROOT = MOS_ROOT / "apps" / "api"
COMPOSE_DIR = MOS_ROOT / "deploy" / "compose"
COMPOSE_YML = COMPOSE_DIR / "docker-compose.yml"
ENV_EXAMPLE = COMPOSE_DIR / ".env.example"
DOCKERFILE = API_ROOT / "Dockerfile"
ALEMBIC_DIR = API_ROOT / "alembic"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _env_example_values() -> dict[str, str]:
    """解析 .env.example（注释行忽略，取第一处赋值）。"""
    out: dict[str, str] = {}
    for line in _read(ENV_EXAMPLE).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out.setdefault(key.strip(), value.strip())
    return out


# ────────────────────────── .env.example ──────────────────────────


def test_env_example_has_no_dev_backdoor_enabled():
    """许可旁路 / OAuth 桩后门 / 开发环境 必须是**关闭**状态。"""
    values = _env_example_values()
    assert values.get("LICENSE_DEV_UNLOCK") == "none", "LICENSE_DEV_UNLOCK 默认不得为 all"
    assert values.get("OAUTH_ALLOW_STUB") == "false", "OAUTH_ALLOW_STUB 默认不得为 true"
    assert values.get("ENV") == "production", "ENV 必须是生效值 production"
    assert values.get("SEED_DEMO") == "false", "SEED_DEMO 默认不得为 true"


def test_env_example_requires_secrets():
    """密钥类变量必须留空 —— 留空即由 compose 拒绝启动（而不是弱默认值）。

    注：Redis / MinIO 已从编排移除（系统全程不连它们 —— 限流走进程内滑动
    窗口、文件落本地持久卷），所以这两个口令不再存在。
    """
    values = _env_example_values()
    for key in ("POSTGRES_PASSWORD", "JWT_SECRET", "OPS_DATA_KEY"):
        assert key in values, f".env.example 缺少 {key}"
        assert values[key] == "", f"{key} 必须留空（由 compose 的 :? 强校验），不能带占位弱值"


def _settings_fields() -> list[str]:
    """config.py 里 ``Settings`` 类的字段名（**只取类体**）。

    旧实现对整份文件跑正则，会把函数里的局部变量注解
    （``problems: list[str] = []``）也当成配置项 —— 报出
    ".env.example 缺少 PROBLEMS" 这种根本不存在的配置。
    """
    config_src = _read(API_ROOT / "app" / "config.py")
    lines = config_src.splitlines()
    fields: list[str] = []
    in_class = False
    for line in lines:
        if line.startswith("class Settings"):
            in_class = True
            continue
        if in_class:
            if line and not line[0].isspace():
                break  # 出了类体
            m = re.match(r"^\s{4}([a-z][a-z0-9_]*)\s*:\s*\w", line)
            if m:
                fields.append(m.group(1))
    return fields


def test_env_example_documents_every_app_setting():
    """app/config.py 的每个 Settings 字段都应在 .env.example 里有对应项。"""
    values = _env_example_values()
    missing = sorted({f.upper() for f in _settings_fields() if f.upper() not in values})
    assert not missing, f".env.example 缺少应用配置项：{missing}"


# ────────────────────────── compose ──────────────────────────


def test_compose_requires_secrets_and_interpolates_api_base():
    compose = _read(COMPOSE_YML)
    for var in ("POSTGRES_PASSWORD", "JWT_SECRET", "OPS_DATA_KEY"):
        assert f"${{{var}:?" in compose, f"compose 应对 {var} 使用 :? 强校验"
    # P0-11：NEXT_PUBLIC_API_BASE 必须是插值，且 build args 里也要有
    assert "NEXT_PUBLIC_API_BASE: ${NEXT_PUBLIC_API_BASE:?" in compose
    assert "NEXT_PUBLIC_API_BASE: http://localhost:8000" not in compose, "API 地址不得硬编码"


def test_compose_has_no_dead_services():
    """编排里不得有「没人用却挡着启动」的死服务（审计 P2）。

    历史版本带 redis + minio 两个容器，但系统一行代码都没用到；更糟的是
    api `depends_on: redis(healthy)` —— 一个**没人用的容器**不健康，
    API 就起不来。现在这两个服务已移除，锁死这个结论。
    """
    compose = _read(COMPOSE_YML)
    for dead in ("\n  redis:", "\n  minio:"):
        assert dead not in compose, f"编排里仍有死服务 {dead.strip()}"
    assert "depends_on:\n" in compose
    # api 不得依赖 redis
    api_block = compose.split("\n  api:")[1].split("\n  web:")[0]
    assert "redis" not in api_block, "api 不得依赖未被使用的 redis 服务"


def test_compose_has_migration_service_and_persistent_volumes():
    compose = _read(COMPOSE_YML)
    # P0-8：迁移必须由一次性服务执行，且 api 依赖它成功退出
    assert "alembic" in compose and "upgrade" in compose and "head" in compose
    assert "service_completed_successfully" in compose
    # P0-14：备份 / 上传 / 备份快照都要落持久卷
    for vol in ("mos_api_data:", "mos_api_uploads:", "mos_backups:"):
        assert vol in compose, f"compose 缺少持久卷 {vol}"
    # P1-3：探针要探依赖（/readyz），不是只探进程（/healthz）
    assert "/readyz" in compose
    # P0-12：可信代理跳数必须可配
    assert "TRUSTED_PROXY_IPS" in compose


def test_compose_backup_service_present():
    """P0-13：Postgres 必须有备份/恢复程序。"""
    compose = _read(COMPOSE_YML)
    assert "backup:" in compose
    for script in ("backup.sh", "restore.sh", "backup-loop.sh"):
        assert (COMPOSE_DIR / "backup" / script).exists(), f"缺少备份脚本 {script}"
    restore = _read(COMPOSE_DIR / "backup" / "restore.sh")
    assert "sha256" in restore, "恢复脚本必须校验 checksum"
    assert "RESTORE_CONFIRM" in restore, "恢复脚本必须有二次确认"


# ────────────────────────── Dockerfile ──────────────────────────


def test_dockerfile_ships_alembic_chromium_and_proxy_config():
    dockerfile = _read(DOCKERFILE)
    # P0-8：镜像里必须有 Alembic 与迁移目录
    assert "apps/api/alembic" in dockerfile
    assert "apps/api/alembic.ini" in dockerfile
    # P1-10：Chromium 必须真的装进镜像（否则 pdf_available() 谎报可用）
    assert "playwright install" in dockerfile and "chromium" in dockerfile
    # P0-12：必须信任代理头
    assert "--proxy-headers" in dockerfile and "--forwarded-allow-ips" in dockerfile
    # 探针探依赖
    assert "/readyz" in dockerfile
    # 构建上下文是 mos/ 根（fixtures 在 mos/fixtures）
    assert "mos/" in dockerfile


# ────────────────────────── alembic ──────────────────────────


def test_alembic_chain_has_single_head():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(ALEMBIC_DIR))
    heads = script.get_heads()
    assert len(heads) == 1, f"迁移链必须只有一个 head，实际：{heads}"


def test_alembic_env_py_registers_all_model_modules():
    """env.py 的模型导入清单必须覆盖 app/main.py（漏一个模块 = 漏一张表）。

    同理 ``tests/conftest.py`` 也必须覆盖 main.py —— 单测库是用
    ``Base.metadata.create_all`` 建的，漏一个模块就等于那张表在单测里
    **根本不存在**（测试通过、生产报"no such table"）。
    """
    env_src = _read(ALEMBIC_DIR / "env.py")
    main_src = _read(API_ROOT / "app" / "main.py")
    conftest_src = _read(API_ROOT / "tests" / "conftest.py")
    env_models = set(re.findall(r"^import (app\.models[\w.]*)", env_src, re.M))
    main_models = set(re.findall(r"^import (app\.models[\w.]*)", main_src, re.M))
    conftest_models = set(re.findall(r"^import (app\.models[\w.]*)", conftest_src, re.M))
    missing = sorted(main_models - env_models)
    assert not missing, f"alembic/env.py 缺少模型模块：{missing}"
    missing_conftest = sorted(main_models - conftest_models)
    assert not missing_conftest, f"tests/conftest.py 缺少模型模块：{missing_conftest}"


def test_alembic_upgrade_head_on_empty_database(tmp_path):
    """空库 `alembic upgrade head` 必须退出 0，且之后 `alembic check` 无漂移。"""
    db_path = tmp_path / "empty.db"
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path.as_posix()}"
    env["ALEMBIC_BOOTSTRAP_EMPTY_DB"] = "1"

    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert up.returncode == 0, f"空库 upgrade head 失败：\n{up.stdout}\n{up.stderr}"

    chk = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert chk.returncode == 0, f"alembic check 报出漂移：\n{chk.stdout}\n{chk.stderr}"
