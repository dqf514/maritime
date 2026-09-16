import logging
import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("marios.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./voyageos_wave0.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    # No default: production must set JWT_SECRET explicitly. When empty a
    # process-level random secret is generated (see get_settings) so local
    # demos still boot, but all tokens die on restart.
    jwt_secret: str = ""
    jwt_expire_minutes: int = 720
    license_dev_unlock: str = "none"  # "all" unlocks every module — dev only
    api_cors_origins: str = "http://localhost:3000"
    s3_endpoint: str = "http://127.0.0.1:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "voyageos"
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
    # In-process sliding-window rate limiting for auth endpoints
    rate_limit_enabled: bool = True
    # Mark the HttpOnly session cookie Secure. Must be true in production
    # (HTTPS); false for local http://localhost development.
    cookie_secure: bool = False
    # Dedicated key for encrypting ops/office data at rest; falls back to jwt_secret
    ops_data_key: str = ""

    def s3_configured(self) -> bool:
        return bool(self.s3_access_key and self.s3_secret_key)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.jwt_secret:
        s.jwt_secret = secrets.token_urlsafe(48)
        log.warning(
            "JWT_SECRET 未配置：已生成进程级随机密钥，重启后所有 token 失效。"
            "生产环境必须显式设置 JWT_SECRET。"
        )
    return s
