import logging
import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("marios.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./voyageos_wave0.db"
    # Postgres 连接池（SQLite 忽略）。默认值按"单副本 API + 常见云 PG"选，
    # 显式化是为了让部署方一眼看到能调，而不是吃 SQLAlchemy 的隐式默认
    # （pool_size=5 / max_overflow=10，长连接不 recycle → 云防火墙掐断）。
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: float = 30.0
    db_pool_recycle: int = 1800
    # No default: production must set JWT_SECRET explicitly. When empty a
    # process-level random secret is generated (see get_settings) so local
    # demos still boot, but all tokens die on restart.
    jwt_secret: str = ""
    jwt_expire_minutes: int = 720
    license_dev_unlock: str = "none"  # "all" unlocks every module — dev only
    api_cors_origins: str = "http://localhost:3000"
    app_name: str = "MariOS API"
    app_version: str = "0.1.0-wave0"
    # Runtime environment: ENV=production disables /docs & /openapi.json
    env: str = "dev"
    # Public URLs for OAuth redirects & email links
    api_public_base: str = "http://localhost:8000"
    web_public_base: str = "http://localhost:3000"
    # Platform OAuth apps (secrets never exposed to tenants / frontend)
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_tenant: str = "common"  # common | organizations | consumers | {guid}
    google_client_id: str = ""
    google_client_secret: str = ""
    # Email
    email_channel: str = "console"  # console|smtp|sendgrid
    email_from: str = "noreply@marios.local"
    # Dev: allow stub OAuth without real IdP credentials
    oauth_allow_stub: bool = False
    # Seed demo tenants/users on startup (catalog seeds always run)
    seed_demo: bool = False
    # Startup catalog/reference seeding. Set false for read-only replicas and
    # for the test suite (tests seed their own template DB once per session).
    # Schema creation (create_all) always runs — this only gates the data.
    startup_seed: bool = True
    # In-process sliding-window rate limiting for auth endpoints
    rate_limit_enabled: bool = True
    # Background job worker (Phase 0): webhook delivery etc. Tests disable it
    # and drive app.services.job_queue.process_pending() synchronously.
    # AIS 数据源（D7）：配置后 eta_service 切换到外部供应商适配器
    ais_base_url: str = ""
    ais_api_key: str = ""
    job_worker_enabled: bool = True
    job_worker_interval: float = 2.0
    # 慢查询告警阈值（ms）；0 关闭
    slow_query_ms: float = 200.0
    # 日志格式：json（默认，日志平台可直接解析）/ kv（人读 key=value）
    log_format: str = "json"
    # Mark the HttpOnly session cookie Secure. Must be true in production
    # (HTTPS); false for local http://localhost development.
    cookie_secure: bool = False
    # Dedicated key for encrypting ops/office data at rest; falls back to jwt_secret
    ops_data_key: str = ""

    # ── 安全闸门（默认全关，逐项显式放行）──────────────────────────────
    # 自定义 SQL 报表（``data_source="sql"``）。默认关闭：raw SQL 报表一旦开启
    # 就能绕开声明式构造器的租户过滤（P0-1）。开启后仍强制租户 WHERE 过滤。
    allow_custom_sql_reports: bool = False
    # 出网白名单（逗号分隔的 host）。出网请求（webhook / 连接器测试 / LLM
    # provider）只允许落到这些 host，或公网地址；内网/环回/链路本地/元数据
    # 地址一律拒绝（P0-18）。留空 = 只允许公网。
    outbound_allowed_hosts: str = ""
    # /metrics 的抓取令牌。留空 = 生产环境直接关闭该端点（404），
    # 非生产环境放行并记一条告警。指标里含 QPS / 错误率 / 慢查询，属于运维信息，
    # 不该对匿名公网开放（审计 P2「/metrics 无鉴权」）。
    metrics_token: str = ""

    # AI / LLM — platform defaults; per-tenant AiProvider rows override these.
    # MARIOS_LLM_OFF=1 is a runtime kill switch (llm_client raises LLMNotConfigured
    # and callers fall back to rules) — kept as an env check, not a setting, so the
    # test suite can trip it without touching cached Settings.
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_model: str = "claude-sonnet-5"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.3
    llm_timeout_seconds: int = 60
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    # 按量付费开关：True 时真实 AI 调用（chat / assist / extract）按 tokens 扣
    # TenantWallet(meter_code="ai.tokens")，余额不足返回 402 QUOTA_EXCEEDED。
    # 默认关闭 —— 观测性流水（UsageLedger）照记但不阻断业务；生产开箱计费时置 True。
    ai_metering_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.jwt_secret:
        if s.env.lower() == "production":
            # 生产环境不允许「随机密钥兜底」：多副本部署时各副本密钥不同 →
            # 登录态随机失效；且 OPS_DATA_KEY 未配时 Fernet 密钥也跟着漂移 →
            # 已加密的连接串永久不可解（P0-10 / P1-18）。
            raise RuntimeError(
                "JWT_SECRET 未配置 —— 生产环境必须显式设置 JWT_SECRET（"
                "openssl rand -hex 32）。已拒绝以进程级随机密钥启动。"
            )
        s.jwt_secret = secrets.token_urlsafe(48)
        log.warning(
            "JWT_SECRET 未配置：已生成进程级随机密钥，重启后所有 token 失效。"
            "生产环境必须显式设置 JWT_SECRET。"
        )
    assert_runtime_safety(s)
    return s


def assert_runtime_safety(s: Settings) -> None:
    """生产环境启动断言 —— 不满足直接抛异常，**拒绝静默启动**。

    检查项（P0-9 / P0-10 / P1-18）：

    - ``LICENSE_DEV_UNLOCK=all``：许可旁路，生产等于「所有模块全开」；
    - ``OAUTH_ALLOW_STUB=true``：OAuth 后门（任何人可持 stub_email 登任意账号）；
    - ``JWT_SECRET`` 为空：见 :func:`get_settings`（已单独处理）；
    - ``COOKIE_SECURE=false``：会话 Cookie 会随明文 HTTP 发出（可被嗅探）。

    非生产环境只打印醒目告警 —— 开发/演示环境需要这些开关。
    """
    problems: list[str] = []
    if s.license_dev_unlock.strip().lower() == "all":
        problems.append("LICENSE_DEV_UNLOCK=all（许可旁路，生产环境等于全模块放行）")
    if s.oauth_allow_stub:
        problems.append("OAUTH_ALLOW_STUB=true（OAuth 后门，可持 stub_email 登入任意账号）")
    if not s.cookie_secure:
        problems.append("COOKIE_SECURE=false（会话 Cookie 会随明文 HTTP 发出，可被嗅探）")
    if not problems:
        return
    if s.env.lower() != "production":
        log.warning("开发环境安全项未收紧（不影响启动）：%s", "；".join(problems))
        return
    raise RuntimeError(
        "生产环境安全配置不满足，已拒绝启动："
        + "；".join(problems)
        + "。请在 .env 中修正后重启（开发环境可用 ENV=dev 绕过本检查）。"
    )
