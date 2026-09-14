"""Encrypt / mask datastore connection strings for platform ops."""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from urllib.parse import urlparse, urlunparse

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

log = logging.getLogger("voyageos.ops_crypto")

_warned_fallback = False


def _fernet() -> Fernet:
    global _warned_fallback
    s = get_settings()
    raw = s.ops_data_key
    if not raw:
        raw = s.jwt_secret
        if not _warned_fallback:
            _warned_fallback = True
            log.warning("OPS_DATA_KEY 未配置，数据落库加密回退使用 JWT_SECRET 派生密钥；生产环境请设置独立的 OPS_DATA_KEY。")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(cipher: str) -> str:
    try:
        return _fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("无法解密连接串，密钥可能已变更") from exc


# Key-versioned token encryption (v1: single Fernet key).
# 后续版本化方案：引入 v2: 前缀 + OPS_DATA_KEY_V2 / key ring，读取按前缀选 key，
# 写入始终用最新版本，支持在线重加密迁移。
TOKEN_KEY_VERSION = "v1"


def encrypt_token(plain: str | None) -> str | None:
    if plain is None:
        return None
    return f"{TOKEN_KEY_VERSION}:{encrypt_secret(plain)}"


def decrypt_token(stored: str | None) -> str | None:
    """Decrypt a versioned token; legacy plaintext values pass through."""
    if stored is None:
        return None
    if stored.startswith(f"{TOKEN_KEY_VERSION}:"):
        return decrypt_secret(stored[len(TOKEN_KEY_VERSION) + 1 :])
    return stored


def mask_connection_url(url: str) -> str:
    """Return a redacted preview safe for API responses."""
    if not url:
        return ""
    # sqlite paths — hide absolute path depth lightly
    if url.startswith("sqlite"):
        return re.sub(r"(sqlite\+?[^:]*:///?)(.+)", r"\1***", url)

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc
        if "@" in netloc:
            userinfo, host = netloc.rsplit("@", 1)
            if ":" in userinfo:
                user, _pw = userinfo.split(":", 1)
                userinfo = f"{user}:***"
            else:
                userinfo = f"{userinfo}:***"
            netloc = f"{userinfo}@{host}"
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
    except Exception:
        return "***"
