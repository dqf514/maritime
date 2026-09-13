from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+pysqlite:///./voyageos_wave0.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_minutes: int = 720
    license_dev_unlock: str = "all"
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    s3_endpoint: str = "http://127.0.0.1:9000"
    s3_access_key: str = "voyageos"
    s3_secret_key: str = "voyageossecret"
    s3_bucket: str = "voyageos"
    app_name: str = "VoyageOS API"
    app_version: str = "0.1.0-wave0"
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
    email_from: str = "noreply@voyageos.local"
    # Dev: allow stub OAuth without real IdP credentials
    oauth_allow_stub: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
