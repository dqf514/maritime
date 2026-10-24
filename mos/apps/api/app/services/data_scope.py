"""Row-level data-ownership scope (行级数据权限).

Complements the tenant filter: when a role's effective scope for a module is
"own", list queries additionally restrict rows to those the user created
(``created_by == me``). Supervisors keep "all".

Additive & non-breaking: no RoleDataScope rows → every module is "all", so
existing tenants/tests are unaffected until an admin tightens a role in the
permission matrix. Effective scope across a user's roles is the *most
permissive* (all wins), so a supervisor who also holds a narrower role still
sees the whole tenant.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.models_saas import RoleDataScope

log = logging.getLogger(__name__)

SUPERVISOR_ROLES = frozenset({"management", "tenant_admin", "platform_admin"})

#: 归属列候选（行级 "own" 范围按哪一列判定拥有者），按优先级。
#: 新增可被行级收窄的模型时，要么给它加 ``created_by``，要么把它的归属列
#: 加进这个列表 —— 否则 ``apply_data_scope`` 会 fail-closed 返回空集。
OWNER_COLUMNS: tuple[str, ...] = (
    "created_by",
    "owner_id",
    "owner_user_id",
    "assigned_to",
    "user_id",
)

#: 模块别名 → 归一化分组。
#:
#: 权限矩阵里的模块名（"ship"）和许可模块码（"ship_mgmt"）、业务模块码
#: （"estimate"）并不一致。以前只有接口端点自己传字符串，两边对不上就
#: **收窄静默失效** —— 管理员明明把某角色设成"只看自己建的"，列表却还是
#: 全租户的数据。现在统一归一化：别名与主模块等价。
SCOPE_MODULE_ALIASES: dict[str, str] = {
    "ship": "ship_mgmt",
    "estimate": "chartering",
    "estimates": "chartering",
}

#: 可被收窄的模块（管理端权限矩阵展示用）。没有配规则的模块一律 "all"。
DATA_SCOPE_MODULES: list[str] = [
    "operations",
    "finance",
    "chartering",
    "commercial",
    "bunker",
    "masterdata",
    "ship_mgmt",
    "claims",
    "laytime",
    "emissions",
    "pooling",
    "risk",
    "analytics",
]


def canonical_module(module: str | None) -> str:
    """把模块名归一化到分组（别名 → 主模块）。"""
    raw = (module or "").strip().lower()
    return SCOPE_MODULE_ALIASES.get(raw, raw)


def effective_scope(db: Session, tenant_id: UUID, roles: list[str], module: str) -> str:
    """Resolve a user's effective scope for a module: "own" | "all".

    - supervisors → always "all";
    - no rules for the module → "all" (unrestricted default);
    - any rule granting "all" → "all";
    - otherwise (every rule says "own") → "own".

    模块名先归一化（见 :data:`SCOPE_MODULE_ALIASES`），所以在别名分组上
    设的规则与主模块等价 —— 两边不会各说各话。
    """
    if not roles or any(r in SUPERVISOR_ROLES for r in roles):
        return "all"
    wanted = canonical_module(module)
    rows = db.scalars(
        select(RoleDataScope).where(
            RoleDataScope.tenant_id == tenant_id,
            RoleDataScope.role_code.in_(roles),
        )
    ).all()
    scopes = {r.scope for r in rows if canonical_module(r.module) == wanted}
    if not scopes:
        return "all"
    if "all" in scopes:
        return "all"
    return "own"


def apply_data_scope(stmt, model, user_id: UUID | None, scope: str):
    """Narrow a Select to the user's own rows when scope == "own".

    **失败即关闭（fail closed）** —— 以前这里是"静默放行"：

    - 模型有归属列（``created_by`` 等）→ 按归属列过滤；
    - 模型是**全局参考数据**（没有 ``tenant_id``，如 ports / port_distances）
      → "own" 对它没有意义，不加限制（不是租户数据，谈不上越权）；
    - 模型是**租户数据但没有归属列** → **返回空集**（而不是把全租户数据放出去），
      并记一条 warning。管理员设了"只看自己建的"却看到全租户的行，
      等于这个开关是摆设 —— 那比直接报错更危险。

    ``OWNER_COLUMNS`` 是归属列候选（按优先级）。加新模型时请给它加
    ``created_by``，或把它的归属列加进这个列表。
    """
    if scope != "own":
        return stmt
    if user_id is None:
        # 没有可判定的用户（匿名/系统任务）→ 关闭
        return stmt.where(false())
    cols = model.__table__.columns
    for name in OWNER_COLUMNS:
        if name in cols:
            return stmt.where(getattr(model, name) == user_id)
    if "tenant_id" not in cols:
        # 全局参考数据 —— 不适用行级归属
        return stmt
    log.warning(
        "行级数据权限无法落地（模型 %s 既无归属列也无全局标记）：已按 fail-closed 返回空集。"
        "请给该模型加 created_by 或把归属列加入 OWNER_COLUMNS。",
        getattr(model, "__tablename__", model),
    )
    return stmt.where(false())


def apply_module_scope(db: Session, stmt, model, auth, module: str):
    """行级数据权限的一站式封装：按模块解析 scope 并落到 stmt 上。

    用法::

        stmt = apply_module_scope(db, select(Invoice).where(...), Invoice, auth, "finance")

    等价于 ``apply_data_scope(stmt, model, auth.user_id, effective_scope(db,
    auth.tenant_id, auth.roles, module))`` —— 单独抽出来是为了让各个
    列表端点不必重复写那两行样板，也避免漏掉其中一半。
    """
    scope = effective_scope(db, auth.tenant_id, auth.roles, module)
    return apply_data_scope(stmt, model, auth.user_id, scope)
