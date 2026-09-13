"""Public Knowledge Centre API — catalogue, articles, search, ask."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services import knowledge_base as kb

router = APIRouter(prefix="/help", tags=["Knowledge Centre"])


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    locale: str | None = None


@router.get("/catalog")
def help_catalog(locale: str | None = Query(None)):
    return kb.catalog(locale)


@router.get("/categories")
def help_categories(locale: str | None = Query(None)):
    return kb.list_categories(locale)


@router.get("/articles/{slug}")
def help_article(slug: str, locale: str | None = Query(None)):
    art = kb.get_article(slug, locale)
    if not art:
        from fastapi import HTTPException

        raise HTTPException(404, "Article not found")
    return art


@router.get("/search")
def help_search(q: str = "", locale: str | None = Query(None), limit: int = Query(20, ge=1, le=50)):
    return {"query": q, "items": kb.search(q, locale, limit=limit)}


@router.post("/ask")
def help_ask(body: AskIn):
    return kb.ask(body.question, body.locale)
