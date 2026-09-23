"""Phase 5 — Market data endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import AuthContext, require_module
from app.services import market_data as mkt

router = APIRouter(prefix="/market-data", tags=["Market Data"])


@router.get("/latest")
def latest_quotes(
    category: str | None = Query(None, description="bunker|index|tce"),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return mkt.get_latest_quotes(db, auth.tenant_id, category)


@router.get("/history/{symbol}")
def history(
    symbol: str,
    days: int = Query(30, ge=1, le=365),
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return mkt.get_history(db, auth.tenant_id, symbol, days)


@router.get("/bunker-comparison")
def bunker_comparison(
    auth: AuthContext = Depends(require_module("operations")),
    db: Session = Depends(get_db),
):
    return mkt.get_bunker_comparison(db, auth.tenant_id)


@router.post("/seed-demo", status_code=201)
def seed_demo(
    auth: AuthContext = Depends(require_module("admin")),
    db: Session = Depends(get_db),
):
    count = mkt.seed_demo_data(db, auth.tenant_id)
    return {"seeded": count}
