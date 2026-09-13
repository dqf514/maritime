"""Encrypt / mask datastore connection strings for platform ops."""

from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import urlparse, urlunparse

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def _fernet() -> Fernet:
    raw = get_settings().jwt_secret.encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(cipher: str) -> str:
    try:
        return _fernet().decrypt(cipher.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("无法解密连接串，密钥可能已变更") from exc


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
