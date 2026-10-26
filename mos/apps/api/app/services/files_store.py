"""通用实体附件落盘 —— uploads/attachments/{tenant}/{entity_type}/{entity_id}/。

与船证书的 uploads/certificates 分开存放（证书走 ship_mgmt 模块的独立语义），
版本命名 v{n}_{name} 一致，都只经鉴权下载端点对外提供，不做静态挂载。
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

_UPLOAD_ROOT = Path(__file__).resolve().parent.parent.parent / "uploads" / "attachments"


def safe_filename(name: str) -> str:
    base = Path(name).name
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base) or "file"


def entity_dir(tenant_id: UUID, entity_type: str, entity_id: UUID) -> Path:
    return _UPLOAD_ROOT / str(tenant_id) / re.sub(r"[^a-z0-9_]+", "", entity_type.lower()) / str(entity_id)


def store_entity_file(
    tenant_id: UUID, entity_type: str, entity_id: UUID, version_no: int, filename: str, content: bytes
) -> Path:
    dest_dir = entity_dir(tenant_id, entity_type, entity_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"v{version_no}_{safe_filename(filename)}"
    dest.write_bytes(content)
    return dest
