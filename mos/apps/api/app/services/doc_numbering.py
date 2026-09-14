"""Per-tenant sequential document numbering (INV/CP/V-YYYY-NNNNN).

Numbers are allocated inside the caller's transaction by scanning the current
maximum suffix for the tenant+year, so two documents never share a number per
tenant (also enforced by UniqueConstraint on the models). Legacy rows whose
suffix is not numeric are ignored.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session


def next_doc_number(db: Session, tenant_id: UUID, model, column, prefix: str) -> str:
    year = datetime.now().year
    like = f"{prefix}-{year}-%"
    existing = db.scalars(select(column).where(model.tenant_id == tenant_id, column.like(like))).all()
    max_seq = 0
    for no in existing:
        try:
            max_seq = max(max_seq, int(str(no).rsplit("-", 1)[1]))
        except (ValueError, IndexError):
            continue
    return f"{prefix}-{year}-{max_seq + 1:05d}"
