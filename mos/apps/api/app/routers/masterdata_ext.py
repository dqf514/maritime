"""主数据扩展 CRUD — 节假日日历 / 工作日模式 / 术语表 / 标准条款段落。

Endpoints (all under /api/v1/masterdata):
- /holiday-calendars       HolidayCalendar 列表/新建/详情/更新/删除
- /working-day-patterns    WorkingDayPattern 同上
- /term-lists              TermList 同上（category/code 下拉源）
- /standard-paragraphs     StandardParagraph 同上（cp_clause/invoice_note/claim_note）
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_reference_ext import (
    HolidayCalendar,
    StandardParagraph,
    TermList,
    WorkingDayPattern,
)
from app.security import AuthContext, require_module
from app.services.tenant_guard import scoped_get, scoped_query

router = APIRouter(prefix="/masterdata", tags=["Master Data"])  # 由 main.py 以 /api/v1 挂载


# ── Holiday calendars ──


class HolidayCalendarIn(BaseModel):
    name: str
    country_code: str | None = None
    year: int
    holidays: list[dict] | dict | None = None  # [{date, name, type}]


class HolidayCalendarOut(BaseModel):
    id: str
    name: str
    country_code: str | None
    year: int
    holidays: list | dict | None


@router.get("/holiday-calendars", response_model=list[HolidayCalendarOut])
def list_holiday_calendars(
    year: int | None = Query(None),
    country_code: str | None = Query(None),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, HolidayCalendar, auth.tenant_id)
    if year is not None:
        stmt = stmt.where(HolidayCalendar.year == year)
    if country_code:
        stmt = stmt.where(HolidayCalendar.country_code == country_code)
    rows = db.scalars(stmt.order_by(HolidayCalendar.year, HolidayCalendar.name)).all()
    return [
        HolidayCalendarOut(
            id=str(r.id),
            name=r.name,
            country_code=r.country_code,
            year=r.year,
            holidays=r.holidays,
        )
        for r in rows
    ]


@router.post("/holiday-calendars", response_model=HolidayCalendarOut, status_code=201)
def create_holiday_calendar(
    body: HolidayCalendarIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = HolidayCalendar(
        tenant_id=auth.tenant_id,
        name=body.name,
        country_code=body.country_code,
        year=body.year,
        holidays=body.holidays,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return HolidayCalendarOut(
        id=str(row.id),
        name=row.name,
        country_code=row.country_code,
        year=row.year,
        holidays=row.holidays,
    )


@router.get("/holiday-calendars/{calendar_id}", response_model=HolidayCalendarOut)
def get_holiday_calendar(
    calendar_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, HolidayCalendar, calendar_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "HOLIDAY_CALENDAR_NOT_FOUND", "message": "Holiday calendar not found"})
    return HolidayCalendarOut(
        id=str(row.id),
        name=row.name,
        country_code=row.country_code,
        year=row.year,
        holidays=row.holidays,
    )


@router.patch("/holiday-calendars/{calendar_id}", response_model=HolidayCalendarOut)
def update_holiday_calendar(
    calendar_id: UUID,
    body: HolidayCalendarIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, HolidayCalendar, calendar_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "HOLIDAY_CALENDAR_NOT_FOUND", "message": "Holiday calendar not found"})
    row.name = body.name
    row.country_code = body.country_code
    row.year = body.year
    row.holidays = body.holidays
    db.commit()
    db.refresh(row)
    return HolidayCalendarOut(
        id=str(row.id),
        name=row.name,
        country_code=row.country_code,
        year=row.year,
        holidays=row.holidays,
    )


@router.delete("/holiday-calendars/{calendar_id}")
def delete_holiday_calendar(
    calendar_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, HolidayCalendar, calendar_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "HOLIDAY_CALENDAR_NOT_FOUND", "message": "Holiday calendar not found"})
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Working day patterns ──


class WorkingDayPatternIn(BaseModel):
    name: str
    monday: bool = True
    tuesday: bool = True
    wednesday: bool = True
    thursday: bool = True
    friday: bool = True
    saturday: bool = False
    sunday: bool = False
    is_default: bool = False


class WorkingDayPatternOut(BaseModel):
    id: str
    name: str
    monday: bool
    tuesday: bool
    wednesday: bool
    thursday: bool
    friday: bool
    saturday: bool
    sunday: bool
    is_default: bool


def _pattern_out(row: WorkingDayPattern) -> WorkingDayPatternOut:
    return WorkingDayPatternOut(
        id=str(row.id),
        name=row.name,
        monday=bool(row.monday),
        tuesday=bool(row.tuesday),
        wednesday=bool(row.wednesday),
        thursday=bool(row.thursday),
        friday=bool(row.friday),
        saturday=bool(row.saturday),
        sunday=bool(row.sunday),
        is_default=bool(row.is_default),
    )


@router.get("/working-day-patterns", response_model=list[WorkingDayPatternOut])
def list_working_day_patterns(
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(scoped_query(db, WorkingDayPattern, auth.tenant_id).order_by(WorkingDayPattern.name)).all()
    return [_pattern_out(r) for r in rows]


@router.post("/working-day-patterns", response_model=WorkingDayPatternOut, status_code=201)
def create_working_day_pattern(
    body: WorkingDayPatternIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = WorkingDayPattern(
        tenant_id=auth.tenant_id,
        name=body.name,
        monday=body.monday,
        tuesday=body.tuesday,
        wednesday=body.wednesday,
        thursday=body.thursday,
        friday=body.friday,
        saturday=body.saturday,
        sunday=body.sunday,
        is_default=body.is_default,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _pattern_out(row)


@router.get("/working-day-patterns/{pattern_id}", response_model=WorkingDayPatternOut)
def get_working_day_pattern(
    pattern_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, WorkingDayPattern, pattern_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "PATTERN_NOT_FOUND", "message": "Working day pattern not found"})
    return _pattern_out(row)


@router.patch("/working-day-patterns/{pattern_id}", response_model=WorkingDayPatternOut)
def update_working_day_pattern(
    pattern_id: UUID,
    body: WorkingDayPatternIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, WorkingDayPattern, pattern_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "PATTERN_NOT_FOUND", "message": "Working day pattern not found"})
    row.name = body.name
    row.monday = body.monday
    row.tuesday = body.tuesday
    row.wednesday = body.wednesday
    row.thursday = body.thursday
    row.friday = body.friday
    row.saturday = body.saturday
    row.sunday = body.sunday
    row.is_default = body.is_default
    db.commit()
    db.refresh(row)
    return _pattern_out(row)


@router.delete("/working-day-patterns/{pattern_id}")
def delete_working_day_pattern(
    pattern_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, WorkingDayPattern, pattern_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "PATTERN_NOT_FOUND", "message": "Working day pattern not found"})
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Term lists ──


class TermListIn(BaseModel):
    category: str = Field(..., description="laytime_terms|delivery_terms|payment_terms|etc")
    code: str
    label_en: str
    label_zh: str | None = None
    sort_order: int = 0
    is_active: bool = True


class TermListOut(BaseModel):
    id: str
    category: str
    code: str
    label_en: str
    label_zh: str | None
    sort_order: int
    is_active: bool


def _term_out(row: TermList) -> TermListOut:
    return TermListOut(
        id=str(row.id),
        category=row.category,
        code=row.code,
        label_en=row.label_en,
        label_zh=row.label_zh,
        sort_order=int(row.sort_order or 0),
        is_active=bool(row.is_active),
    )


@router.get("/term-lists", response_model=list[TermListOut])
def list_term_lists(
    category: str | None = Query(None),
    active_only: bool = Query(False),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, TermList, auth.tenant_id)
    if category:
        stmt = stmt.where(TermList.category == category)
    if active_only:
        stmt = stmt.where(TermList.is_active.is_(True))
    rows = db.scalars(stmt.order_by(TermList.category, TermList.sort_order, TermList.code)).all()
    return [_term_out(r) for r in rows]


@router.post("/term-lists", response_model=TermListOut, status_code=201)
def create_term_list(
    body: TermListIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = TermList(
        tenant_id=auth.tenant_id,
        category=body.category,
        code=body.code,
        label_en=body.label_en,
        label_zh=body.label_zh,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _term_out(row)


@router.get("/term-lists/{term_id}", response_model=TermListOut)
def get_term_list(
    term_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, TermList, term_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "TERM_NOT_FOUND", "message": "Term list entry not found"})
    return _term_out(row)


@router.patch("/term-lists/{term_id}", response_model=TermListOut)
def update_term_list(
    term_id: UUID,
    body: TermListIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, TermList, term_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "TERM_NOT_FOUND", "message": "Term list entry not found"})
    row.category = body.category
    row.code = body.code
    row.label_en = body.label_en
    row.label_zh = body.label_zh
    row.sort_order = body.sort_order
    row.is_active = body.is_active
    db.commit()
    db.refresh(row)
    return _term_out(row)


@router.delete("/term-lists/{term_id}")
def delete_term_list(
    term_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, TermList, term_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "TERM_NOT_FOUND", "message": "Term list entry not found"})
    db.delete(row)
    db.commit()
    return {"ok": True}


# ── Standard paragraphs ──


class StandardParagraphIn(BaseModel):
    category: str = Field(..., description="cp_clause|invoice_note|claim_note")
    code: str
    title: str
    content: str
    is_system: bool = False


class StandardParagraphOut(BaseModel):
    id: str
    category: str
    code: str
    title: str
    content: str
    is_system: bool


def _para_out(row: StandardParagraph) -> StandardParagraphOut:
    return StandardParagraphOut(
        id=str(row.id),
        category=row.category,
        code=row.code,
        title=row.title,
        content=row.content,
        is_system=bool(row.is_system),
    )


@router.get("/standard-paragraphs", response_model=list[StandardParagraphOut])
def list_standard_paragraphs(
    category: str | None = Query(None),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, StandardParagraph, auth.tenant_id)
    if category:
        stmt = stmt.where(StandardParagraph.category == category)
    rows = db.scalars(stmt.order_by(StandardParagraph.category, StandardParagraph.code)).all()
    return [_para_out(r) for r in rows]


@router.post("/standard-paragraphs", response_model=StandardParagraphOut, status_code=201)
def create_standard_paragraph(
    body: StandardParagraphIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = StandardParagraph(
        tenant_id=auth.tenant_id,
        category=body.category,
        code=body.code,
        title=body.title,
        content=body.content,
        is_system=body.is_system,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _para_out(row)


@router.get("/standard-paragraphs/{paragraph_id}", response_model=StandardParagraphOut)
def get_standard_paragraph(
    paragraph_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, StandardParagraph, paragraph_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "PARAGRAPH_NOT_FOUND", "message": "Standard paragraph not found"})
    return _para_out(row)


@router.patch("/standard-paragraphs/{paragraph_id}", response_model=StandardParagraphOut)
def update_standard_paragraph(
    paragraph_id: UUID,
    body: StandardParagraphIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, StandardParagraph, paragraph_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "PARAGRAPH_NOT_FOUND", "message": "Standard paragraph not found"})
    row.category = body.category
    row.code = body.code
    row.title = body.title
    row.content = body.content
    row.is_system = body.is_system
    db.commit()
    db.refresh(row)
    return _para_out(row)


@router.delete("/standard-paragraphs/{paragraph_id}")
def delete_standard_paragraph(
    paragraph_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, StandardParagraph, paragraph_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": "PARAGRAPH_NOT_FOUND", "message": "Standard paragraph not found"})
    db.delete(row)
    db.commit()
    return {"ok": True}
