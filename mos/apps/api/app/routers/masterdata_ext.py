"""主数据扩展 CRUD — 节假日日历 / 工作日模式 / 术语表 / 标准条款段落 + IMOS Data Center 子表。

Endpoints (all under /api/v1/masterdata):
- /holiday-calendars       HolidayCalendar 列表/新建/详情/更新/删除
- /working-day-patterns    WorkingDayPattern 同上
- /term-lists              TermList 同上（category/code 下拉源）
- /standard-paragraphs     StandardParagraph 同上（cp_clause/invoice_note/claim_note）

IMOS Data Center parity（P10）子表：
- /cargo-groups            商品大类
- /cargo-names[/{id}/properties]  货物品名主数据 + Title/Value 属性
- /ports/{port_id}/berths|aliases 港口泊位/别名（随 Port 为全局参照数据，写需管理员）
- /vessels/{id}/port-consumptions|speed-consumptions  停泊工况油耗矩阵 / 航速油耗曲线
- /counterparties/{id}/properties   对手方 Title/Value 属性

与本文件原有的硬删除不同，上述子表统一走 ``soft_delete``（模型都带 ``deleted_at``，
删除进回收站），与 ``routers/masterdata.py`` 的 vessel/port/counterparty 口径一致；
新增的 entity_type 已在 ``routers/recycle.py`` 的 ENTITY_LOOKUP 登记，否则恢复时 400。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models_cargo import CargoGroup, CargoName, CargoNameProperty
from app.models_reference_ext import (
    HolidayCalendar,
    StandardParagraph,
    TermList,
    WorkingDayPattern,
)
from app.models_vessel_ext import VesselPortConsumption, VesselSpeedConsumption
from app.models_wave1 import (
    Counterparty,
    CounterpartyProperty,
    Port,
    PortAlias,
    PortBerth,
    Vessel,
)
from app.routers.masterdata import _require_port_admin
from app.schemas_wave1 import (
    CargoGroupIn,
    CargoGroupOut,
    CargoGroupPatch,
    CargoNameIn,
    CargoNameOut,
    CargoNamePatch,
    CargoNamePropertyOut,
    CounterpartyPropertyOut,
    PortAliasIn,
    PortAliasOut,
    PortAliasPatch,
    PortBerthIn,
    PortBerthOut,
    PortBerthPatch,
    TitleValueIn,
    TitleValuePatch,
    VesselPortConsumptionIn,
    VesselPortConsumptionOut,
    VesselPortConsumptionPatch,
    VesselSpeedConsumptionIn,
    VesselSpeedConsumptionOut,
    MasterDataName,
    _reject_empty,
)
from app.security import AuthContext, require_module
from app.services.recycle import soft_delete
from app.services.tenant_guard import scoped_get, scoped_query
from app.services.data_scope import apply_module_scope

router = APIRouter(prefix="/masterdata", tags=["Master Data"])  # 由 main.py 以 /api/v1 挂载


# ── Holiday calendars ──


class HolidayCalendarIn(BaseModel):
    name: MasterDataName
    country_code: str | None = None
    year: int
    holidays: list[dict] | dict | None = None  # [{date, name, type}]

    _name_not_empty = _reject_empty("name")


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
    name: MasterDataName
    monday: bool = True
    tuesday: bool = True
    wednesday: bool = True
    thursday: bool = True
    friday: bool = True
    saturday: bool = False
    sunday: bool = False
    is_default: bool = False

    _name_not_empty = _reject_empty("name")


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
    category: Annotated[
        str, Field(min_length=1, max_length=64)
    ] = Field(..., description="laytime_terms|delivery_terms|payment_terms|etc")
    code: Annotated[str, Field(min_length=1, max_length=64)]
    label_en: MasterDataName
    label_zh: str | None = None
    sort_order: int = 0
    is_active: bool = True

    _category_not_empty = _reject_empty("category")
    _code_not_empty = _reject_empty("code")
    _label_en_not_empty = _reject_empty("label_en")


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
    category: Annotated[
        str, Field(min_length=1, max_length=64)
    ] = Field(..., description="cp_clause|invoice_note|claim_note")
    code: Annotated[str, Field(min_length=1, max_length=64)]
    title: MasterDataName
    content: str
    is_system: bool = False

    _category_not_empty = _reject_empty("category")
    _code_not_empty = _reject_empty("code")
    _title_not_empty = _reject_empty("title")


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


# ══ IMOS Data Center parity（P10）════════════════════════════════════════════
#
# 下面 6 组子资源与本文件上方的老资源有两点刻意的不同：
#   1. 删除走 soft_delete（模型都带 deleted_at，进回收站可恢复）——与同前缀的
#      routers/masterdata.py 中 vessel/port/counterparty 口径一致；
#   2. 唯一键冲突统一回落成 409，而不是 SQLAlchemy IntegrityError 冒泡成 500。
# PATCH 一律 model_dump(exclude_unset=True)：只写提交过的字段，避免未提交字段
# 被默认值清空（字段集是 IMOS 规模，全量 setattr 代价很大）；请求体用 schemas_wave1
# 里的 *Patch（键字段可缺省、显式 null 拒绝 422），不能复用 create body。


def _parent_or_404(db: Session, model, row_id: UUID, auth: AuthContext, code: str, message: str):
    """取租户内父记录；不存在/跨租户/已软删一律 404（scoped_get 已按 IDOR 约定不区分原因）。"""
    row = scoped_get(db, model, row_id, auth.tenant_id)
    if not row:
        raise HTTPException(404, detail={"code": code, "message": message})
    return row


def _commit_or_conflict(db: Session, code: str, message: str) -> None:
    """提交；撞唯一键则回滚并 409（各子表的唯一约束见 models_*.py）。"""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"code": code, "message": message})


def _port_child_or_404(row, *, port_id: UUID, deleted_ok: bool = False, code: str, message: str):
    """端口子行：无 tenant_id（全局参照数据），改由 port_id 归属 + 软删除状态判定。"""
    if row is None or row.port_id != port_id or (not deleted_ok and row.deleted_at):
        raise HTTPException(404, detail={"code": code, "message": message})
    return row


# ── Cargo groups ──


@router.get("/cargo-groups", response_model=list[CargoGroupOut])
def list_cargo_groups(
    q: str = "",
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, CargoGroup, auth.tenant_id)
    if q.strip():
        stmt = stmt.where(CargoGroup.name.ilike(f"%{q.strip()}%"))
    rows = db.scalars(stmt.order_by(CargoGroup.name)).all()
    return [CargoGroupOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/cargo-groups", response_model=CargoGroupOut, status_code=201)
def create_cargo_group(
    body: CargoGroupIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = CargoGroup(tenant_id=auth.tenant_id, **body.model_dump())
    db.add(row)
    _commit_or_conflict(db, "CARGO_GROUP_EXISTS", "Cargo group name already exists")
    db.refresh(row)
    return CargoGroupOut.model_validate(row, from_attributes=True)


@router.get("/cargo-groups/{group_id}", response_model=CargoGroupOut)
def get_cargo_group(
    group_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = _parent_or_404(db, CargoGroup, group_id, auth, "CARGO_GROUP_NOT_FOUND", "Cargo group not found")
    return CargoGroupOut.model_validate(row, from_attributes=True)


@router.patch("/cargo-groups/{group_id}", response_model=CargoGroupOut)
def update_cargo_group(
    group_id: UUID,
    body: CargoGroupPatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = _parent_or_404(db, CargoGroup, group_id, auth, "CARGO_GROUP_NOT_FOUND", "Cargo group not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    _commit_or_conflict(db, "CARGO_GROUP_EXISTS", "Cargo group name already exists")
    db.refresh(row)
    return CargoGroupOut.model_validate(row, from_attributes=True)


@router.delete("/cargo-groups/{group_id}")
def delete_cargo_group(
    group_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = _parent_or_404(db, CargoGroup, group_id, auth, "CARGO_GROUP_NOT_FOUND", "Cargo group not found")
    soft_delete(db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="cargo_group", row=row, title=row.name)
    db.commit()
    return {"ok": True, "recycled": True}


# ── Cargo names（货物品名主数据）──


@router.get("/cargo-names", response_model=list[CargoNameOut])
def list_cargo_names(
    q: str = "",
    group_id: UUID | None = Query(None),
    inactive: bool | None = Query(None, description="true/false 过滤停用品名；省略则全部"),
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    stmt = scoped_query(db, CargoName, auth.tenant_id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                CargoName.short_name.ilike(like),
                CargoName.full_name.ilike(like),
                CargoName.product_code.ilike(like),
            )
        )
    if group_id is not None:
        stmt = stmt.where(CargoName.cargo_group_id == group_id)
    if inactive is not None:
        stmt = stmt.where(CargoName.inactive.is_(bool(inactive)))
    # 行级数据权限：scope 收窄到 "own" 时只看自己建的货种
    stmt = apply_module_scope(db, stmt, CargoName, auth, "masterdata")
    rows = db.scalars(stmt.order_by(CargoName.short_name)).all()
    return [CargoNameOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/cargo-names", response_model=CargoNameOut, status_code=201)
def create_cargo_name(
    body: CargoNameIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = CargoName(tenant_id=auth.tenant_id, created_by=auth.user_id, **body.model_dump())
    db.add(row)
    _commit_or_conflict(db, "CARGO_NAME_EXISTS", "Cargo short name already exists")
    db.refresh(row)
    return CargoNameOut.model_validate(row, from_attributes=True)


@router.get("/cargo-names/{cargo_name_id}", response_model=CargoNameOut)
def get_cargo_name(
    cargo_name_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = _parent_or_404(db, CargoName, cargo_name_id, auth, "CARGO_NAME_NOT_FOUND", "Cargo name not found")
    return CargoNameOut.model_validate(row, from_attributes=True)


@router.patch("/cargo-names/{cargo_name_id}", response_model=CargoNameOut)
def update_cargo_name(
    cargo_name_id: UUID,
    body: CargoNamePatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = _parent_or_404(db, CargoName, cargo_name_id, auth, "CARGO_NAME_NOT_FOUND", "Cargo name not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    _commit_or_conflict(db, "CARGO_NAME_EXISTS", "Cargo short name already exists")
    db.refresh(row)
    return CargoNameOut.model_validate(row, from_attributes=True)


@router.delete("/cargo-names/{cargo_name_id}")
def delete_cargo_name(
    cargo_name_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = _parent_or_404(db, CargoName, cargo_name_id, auth, "CARGO_NAME_NOT_FOUND", "Cargo name not found")
    soft_delete(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="cargo_name", row=row, title=row.short_name
    )
    db.commit()
    return {"ok": True, "recycled": True}


# ── Cargo name properties（Title/Value）──


@router.get("/cargo-names/{cargo_name_id}/properties", response_model=list[CargoNamePropertyOut])
def list_cargo_name_properties(
    cargo_name_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _parent_or_404(db, CargoName, cargo_name_id, auth, "CARGO_NAME_NOT_FOUND", "Cargo name not found")
    stmt = (
        scoped_query(db, CargoNameProperty, auth.tenant_id)
        .where(CargoNameProperty.cargo_name_id == cargo_name_id)
        .order_by(CargoNameProperty.title)
    )
    rows = db.scalars(stmt).all()
    return [CargoNamePropertyOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/cargo-names/{cargo_name_id}/properties", response_model=CargoNamePropertyOut, status_code=201)
def create_cargo_name_property(
    cargo_name_id: UUID,
    body: TitleValueIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _parent_or_404(db, CargoName, cargo_name_id, auth, "CARGO_NAME_NOT_FOUND", "Cargo name not found")
    row = CargoNameProperty(tenant_id=auth.tenant_id, cargo_name_id=cargo_name_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return CargoNamePropertyOut.model_validate(row, from_attributes=True)


@router.patch("/cargo-names/{cargo_name_id}/properties/{property_id}", response_model=CargoNamePropertyOut)
def update_cargo_name_property(
    cargo_name_id: UUID,
    property_id: UUID,
    body: TitleValuePatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, CargoNameProperty, property_id, auth.tenant_id)
    if row is None or row.cargo_name_id != cargo_name_id:
        raise HTTPException(404, detail={"code": "CARGO_NAME_PROPERTY_NOT_FOUND", "message": "Property not found"})
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return CargoNamePropertyOut.model_validate(row, from_attributes=True)


@router.delete("/cargo-names/{cargo_name_id}/properties/{property_id}")
def delete_cargo_name_property(
    cargo_name_id: UUID,
    property_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, CargoNameProperty, property_id, auth.tenant_id)
    if row is None or row.cargo_name_id != cargo_name_id:
        raise HTTPException(404, detail={"code": "CARGO_NAME_PROPERTY_NOT_FOUND", "message": "Property not found"})
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="cargo_name_property",
        row=row,
        title=row.title,
    )
    db.commit()
    return {"ok": True, "recycled": True}


# ── Port berths / aliases（全局参照数据 —— 随父级 Port 无 tenant_id）──
# 读不按租户过滤（港口本身全局共享），写必须 tenant_admin/platform_admin，
# 门槛与 masterdata.update_port 的 _require_port_admin 同一条规则。


def _get_global_port(port_id: UUID, db: Session) -> Port:
    port = db.get(Port, port_id)
    if not port or port.deleted_at:
        raise HTTPException(404, detail={"code": "PORT_NOT_FOUND", "message": "Port not found"})
    return port


@router.get("/ports/{port_id}/berths", response_model=list[PortBerthOut])
def list_port_berths(
    port_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _ = auth
    _get_global_port(port_id, db)
    rows = db.scalars(
        select(PortBerth)
        .where(PortBerth.port_id == port_id, PortBerth.deleted_at.is_(None))
        .order_by(PortBerth.short_name)
    ).all()
    return [PortBerthOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/ports/{port_id}/berths", response_model=PortBerthOut, status_code=201)
def create_port_berth(
    port_id: UUID,
    body: PortBerthIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_port_admin(auth)
    _get_global_port(port_id, db)
    row = PortBerth(port_id=port_id, **body.model_dump())
    db.add(row)
    _commit_or_conflict(db, "BERTH_EXISTS", "Berth short name already exists for this port")
    db.refresh(row)
    return PortBerthOut.model_validate(row, from_attributes=True)


@router.patch("/ports/{port_id}/berths/{berth_id}", response_model=PortBerthOut)
def update_port_berth(
    port_id: UUID,
    berth_id: UUID,
    body: PortBerthPatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_port_admin(auth)
    row = _port_child_or_404(
        db.get(PortBerth, berth_id), port_id=port_id, code="BERTH_NOT_FOUND", message="Berth not found"
    )
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    _commit_or_conflict(db, "BERTH_EXISTS", "Berth short name already exists for this port")
    db.refresh(row)
    return PortBerthOut.model_validate(row, from_attributes=True)


@router.delete("/ports/{port_id}/berths/{berth_id}")
def delete_port_berth(
    port_id: UUID,
    berth_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_port_admin(auth)
    row = _port_child_or_404(
        db.get(PortBerth, berth_id), port_id=port_id, code="BERTH_NOT_FOUND", message="Berth not found"
    )
    soft_delete(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="port_berth", row=row, title=row.short_name
    )
    db.commit()
    return {"ok": True, "recycled": True}


@router.get("/ports/{port_id}/aliases", response_model=list[PortAliasOut])
def list_port_aliases(
    port_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _ = auth
    _get_global_port(port_id, db)
    rows = db.scalars(
        select(PortAlias)
        .where(PortAlias.port_id == port_id, PortAlias.deleted_at.is_(None))
        .order_by(PortAlias.alias)
    ).all()
    return [PortAliasOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/ports/{port_id}/aliases", response_model=PortAliasOut, status_code=201)
def create_port_alias(
    port_id: UUID,
    body: PortAliasIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_port_admin(auth)
    _get_global_port(port_id, db)
    row = PortAlias(port_id=port_id, **body.model_dump())
    db.add(row)
    _commit_or_conflict(db, "PORT_ALIAS_EXISTS", "Alias already exists for this port")
    db.refresh(row)
    return PortAliasOut.model_validate(row, from_attributes=True)


@router.patch("/ports/{port_id}/aliases/{alias_id}", response_model=PortAliasOut)
def update_port_alias(
    port_id: UUID,
    alias_id: UUID,
    body: PortAliasPatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_port_admin(auth)
    row = _port_child_or_404(
        db.get(PortAlias, alias_id), port_id=port_id, code="PORT_ALIAS_NOT_FOUND", message="Alias not found"
    )
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    _commit_or_conflict(db, "PORT_ALIAS_EXISTS", "Alias already exists for this port")
    db.refresh(row)
    return PortAliasOut.model_validate(row, from_attributes=True)


@router.delete("/ports/{port_id}/aliases/{alias_id}")
def delete_port_alias(
    port_id: UUID,
    alias_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _require_port_admin(auth)
    row = _port_child_or_404(
        db.get(PortAlias, alias_id), port_id=port_id, code="PORT_ALIAS_NOT_FOUND", message="Alias not found"
    )
    soft_delete(
        db, tenant_id=auth.tenant_id, user_id=auth.user_id, entity_type="port_alias", row=row, title=row.alias
    )
    db.commit()
    return {"ok": True, "recycled": True}


# ── Vessel in-port consumption matrix（IMOS In Port Consumption Table）──


@router.get("/vessels/{vessel_id}/port-consumptions", response_model=list[VesselPortConsumptionOut])
def list_vessel_port_consumptions(
    vessel_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _parent_or_404(db, Vessel, vessel_id, auth, "VESSEL_NOT_FOUND", "Vessel not found")
    rows = db.scalars(
        scoped_query(db, VesselPortConsumption, auth.tenant_id)
        .where(VesselPortConsumption.vessel_id == vessel_id)
        .order_by(VesselPortConsumption.fuel_grade)
    ).all()
    return [VesselPortConsumptionOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/vessels/{vessel_id}/port-consumptions", response_model=VesselPortConsumptionOut, status_code=201)
def create_vessel_port_consumption(
    vessel_id: UUID,
    body: VesselPortConsumptionIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _parent_or_404(db, Vessel, vessel_id, auth, "VESSEL_NOT_FOUND", "Vessel not found")
    row = VesselPortConsumption(tenant_id=auth.tenant_id, vessel_id=vessel_id, **body.model_dump())
    db.add(row)
    _commit_or_conflict(db, "FUEL_GRADE_EXISTS", "This fuel grade already has a row for the vessel")
    db.refresh(row)
    return VesselPortConsumptionOut.model_validate(row, from_attributes=True)


@router.patch("/vessels/{vessel_id}/port-consumptions/{row_id}", response_model=VesselPortConsumptionOut)
def update_vessel_port_consumption(
    vessel_id: UUID,
    row_id: UUID,
    body: VesselPortConsumptionPatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, VesselPortConsumption, row_id, auth.tenant_id)
    if row is None or row.vessel_id != vessel_id:
        raise HTTPException(404, detail={"code": "PORT_CONSUMPTION_NOT_FOUND", "message": "Row not found"})
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    _commit_or_conflict(db, "FUEL_GRADE_EXISTS", "This fuel grade already has a row for the vessel")
    db.refresh(row)
    return VesselPortConsumptionOut.model_validate(row, from_attributes=True)


@router.delete("/vessels/{vessel_id}/port-consumptions/{row_id}")
def delete_vessel_port_consumption(
    vessel_id: UUID,
    row_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, VesselPortConsumption, row_id, auth.tenant_id)
    if row is None or row.vessel_id != vessel_id:
        raise HTTPException(404, detail={"code": "PORT_CONSUMPTION_NOT_FOUND", "message": "Row not found"})
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="vessel_port_consumption",
        row=row,
        title=row.fuel_grade,
    )
    db.commit()
    return {"ok": True, "recycled": True}


# ── Vessel speed / consumption curve（IMOS Speed Consumption Table）──


@router.get("/vessels/{vessel_id}/speed-consumptions", response_model=list[VesselSpeedConsumptionOut])
def list_vessel_speed_consumptions(
    vessel_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _parent_or_404(db, Vessel, vessel_id, auth, "VESSEL_NOT_FOUND", "Vessel not found")
    rows = db.scalars(
        scoped_query(db, VesselSpeedConsumption, auth.tenant_id)
        .where(VesselSpeedConsumption.vessel_id == vessel_id)
        .order_by(VesselSpeedConsumption.speed)
    ).all()
    return [VesselSpeedConsumptionOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/vessels/{vessel_id}/speed-consumptions", response_model=VesselSpeedConsumptionOut, status_code=201)
def create_vessel_speed_consumption(
    vessel_id: UUID,
    body: VesselSpeedConsumptionIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _parent_or_404(db, Vessel, vessel_id, auth, "VESSEL_NOT_FOUND", "Vessel not found")
    row = VesselSpeedConsumption(tenant_id=auth.tenant_id, vessel_id=vessel_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return VesselSpeedConsumptionOut.model_validate(row, from_attributes=True)


@router.patch("/vessels/{vessel_id}/speed-consumptions/{row_id}", response_model=VesselSpeedConsumptionOut)
def update_vessel_speed_consumption(
    vessel_id: UUID,
    row_id: UUID,
    body: VesselSpeedConsumptionIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, VesselSpeedConsumption, row_id, auth.tenant_id)
    if row is None or row.vessel_id != vessel_id:
        raise HTTPException(404, detail={"code": "SPEED_CONSUMPTION_NOT_FOUND", "message": "Row not found"})
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return VesselSpeedConsumptionOut.model_validate(row, from_attributes=True)


@router.delete("/vessels/{vessel_id}/speed-consumptions/{row_id}")
def delete_vessel_speed_consumption(
    vessel_id: UUID,
    row_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, VesselSpeedConsumption, row_id, auth.tenant_id)
    if row is None or row.vessel_id != vessel_id:
        raise HTTPException(404, detail={"code": "SPEED_CONSUMPTION_NOT_FOUND", "message": "Row not found"})
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="vessel_speed_consumption",
        row=row,
        title=str(row.speed),
    )
    db.commit()
    return {"ok": True, "recycled": True}


# ── Counterparty properties（Title/Value）──


@router.get("/counterparties/{party_id}/properties", response_model=list[CounterpartyPropertyOut])
def list_counterparty_properties(
    party_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _parent_or_404(db, Counterparty, party_id, auth, "COUNTERPARTY_NOT_FOUND", "Counterparty not found")
    rows = db.scalars(
        scoped_query(db, CounterpartyProperty, auth.tenant_id)
        .where(CounterpartyProperty.counterparty_id == party_id)
        .order_by(CounterpartyProperty.title)
    ).all()
    return [CounterpartyPropertyOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/counterparties/{party_id}/properties", response_model=CounterpartyPropertyOut, status_code=201)
def create_counterparty_property(
    party_id: UUID,
    body: TitleValueIn,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    _parent_or_404(db, Counterparty, party_id, auth, "COUNTERPARTY_NOT_FOUND", "Counterparty not found")
    row = CounterpartyProperty(tenant_id=auth.tenant_id, counterparty_id=party_id, **body.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return CounterpartyPropertyOut.model_validate(row, from_attributes=True)


@router.patch("/counterparties/{party_id}/properties/{property_id}", response_model=CounterpartyPropertyOut)
def update_counterparty_property(
    party_id: UUID,
    property_id: UUID,
    body: TitleValuePatch,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, CounterpartyProperty, property_id, auth.tenant_id)
    if row is None or row.counterparty_id != party_id:
        raise HTTPException(404, detail={"code": "COUNTERPARTY_PROPERTY_NOT_FOUND", "message": "Property not found"})
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return CounterpartyPropertyOut.model_validate(row, from_attributes=True)


@router.delete("/counterparties/{party_id}/properties/{property_id}")
def delete_counterparty_property(
    party_id: UUID,
    property_id: UUID,
    auth: AuthContext = Depends(require_module("masterdata")),
    db: Session = Depends(get_db),
):
    row = scoped_get(db, CounterpartyProperty, property_id, auth.tenant_id)
    if row is None or row.counterparty_id != party_id:
        raise HTTPException(404, detail={"code": "COUNTERPARTY_PROPERTY_NOT_FOUND", "message": "Property not found"})
    soft_delete(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        entity_type="counterparty_property",
        row=row,
        title=row.title,
    )
    db.commit()
    return {"ok": True, "recycled": True}
