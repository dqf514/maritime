"""Central upload policy — platform-level type & size limits (ConfigFlag-backed).

Every upload surface (certificate files, branding assets, migration Excel, CSV
imports) previously hard-coded its own size cap and extension allowlist. This
module gives the platform a single, admin-editable source of truth:

- three *kinds* — ``document`` (generic files), ``image`` (branding/logo),
  ``data`` (CSV/text imports);
- each kind has a ``max_bytes`` ceiling and an ``exts`` allowlist.

Values live in ConfigFlag at **platform scope** (see services/config_service) so
a platform admin can tighten/loosen limits without a redeploy. Absent flags fall
back to the conservative DEFAULTS below — the current shipped behaviour.

Routes keep any *stricter* domain rules of their own (magic-byte sniffing,
raster-only branding, xlsx zip-header checks); the policy is the outer ceiling
every upload must respect.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.config_service import ConfigService

# kind -> {max_bytes, exts}. Conservative defaults = today's shipped limits.
DEFAULT_UPLOAD_POLICY: dict[str, dict[str, Any]] = {
    "document": {
        "max_bytes": 10 * 1024 * 1024,
        "exts": [".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xlsx", ".xlsm", ".csv"],
    },
    "image": {
        "max_bytes": 2_500_000,
        "exts": [".png", ".jpg", ".jpeg", ".webp"],
    },
    "data": {
        "max_bytes": 2 * 1024 * 1024,
        "exts": [".csv", ".txt"],
    },
}

KINDS = tuple(DEFAULT_UPLOAD_POLICY.keys())
_PREFIX = "upload."


def _flag_key(kind: str, field: str) -> str:
    return f"{_PREFIX}{kind}.{field}"


def get_upload_policy(db: Session, kind: str = "document") -> dict[str, Any]:
    """Return the effective policy for a kind (platform flag, else default)."""
    base = DEFAULT_UPLOAD_POLICY.get(kind, DEFAULT_UPLOAD_POLICY["document"])
    max_bytes = ConfigService.get_number(
        db, _flag_key(kind, "max_bytes"), default=float(base["max_bytes"])
    )
    exts = ConfigService.get_string(db, _flag_key(kind, "exts"), default="")
    if isinstance(exts, str) and exts.strip() and exts.strip().lower() != "none":
        parsed = [e.strip().lower() for e in exts.split(",") if e.strip()]
    else:
        parsed = list(base["exts"])
    return {"kind": kind, "max_bytes": int(max_bytes or base["max_bytes"]), "exts": parsed}


def get_all_upload_policies(db: Session) -> dict[str, dict[str, Any]]:
    return {kind: get_upload_policy(db, kind) for kind in KINDS}


def save_upload_policy(
    db: Session,
    kind: str,
    *,
    max_bytes: int | None = None,
    exts: list[str] | None = None,
    updated_by: UUID | None = None,
) -> dict[str, Any]:
    """Persist a kind's policy at platform scope. Returns the saved policy."""
    if kind not in KINDS:
        raise HTTPException(400, detail={"code": "INVALID_UPLOAD_KIND", "allowed": list(KINDS)})
    if max_bytes is not None:
        if max_bytes <= 0 or max_bytes > 200 * 1024 * 1024:
            raise HTTPException(400, detail={"code": "INVALID_MAX_BYTES", "max": 200 * 1024 * 1024})
        ConfigService.set(
            db, _flag_key(kind, "max_bytes"), float(max_bytes),
            category="uploads", description=f"Max upload size for {kind} (bytes)",
            updated_by=updated_by,
        )
    if exts is not None:
        norm = sorted({e.strip().lower() for e in exts if e.strip()})
        if not norm:
            raise HTTPException(400, detail={"code": "EMPTY_EXTS"})
        for e in norm:
            if not e.startswith(".") or "/" in e or "\\" in e or ".." in e:
                raise HTTPException(400, detail={"code": "INVALID_EXT", "ext": e})
        ConfigService.set(
            db, _flag_key(kind, "exts"), ",".join(norm),
            category="uploads", description=f"Allowed extensions for {kind}",
            updated_by=updated_by,
        )
    return get_upload_policy(db, kind)


def assert_upload_allowed(policy: dict[str, Any], raw_len: int, filename: str) -> str:
    """Enforce size + extension against a policy. Returns the lowercased ext.

    Raises 400 FILE_TOO_LARGE / UNSUPPORTED_TYPE (matching existing upload error
    codes so frontends keep working).
    """
    max_bytes = int(policy["max_bytes"])
    if raw_len > max_bytes:
        raise HTTPException(400, detail={"code": "FILE_TOO_LARGE", "max_bytes": max_bytes})
    ext = Path((filename or "").lower()).suffix
    allowed = set(policy["exts"])
    if ext not in allowed:
        raise HTTPException(400, detail={"code": "UNSUPPORTED_TYPE", "ext": ext, "allowed": sorted(allowed)})
    return ext
