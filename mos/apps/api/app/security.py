import hashlib
import ipaddress
import logging
import socket
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import bcrypt
from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AfterValidator
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import ApiKey, Tenant, TenantModuleLicense, User, UserRole, Role

log = logging.getLogger("marios.security")

bearer = HTTPBearer(auto_error=False)
settings = get_settings()

# Dual-track browser session: interactive sign-in issues the JWT both in the
# JSON body (backward compatible) and as this HttpOnly cookie.
# CSRF rationale: the cookie is SameSite=Lax, so cross-site POST/PUT/DELETE
# requests do not carry it — only top-level safe navigations do. Combined with
# CORS allow_credentials restricted to explicit origins (see app/main.py), the
# cross-site request forgery surface is considered acceptable and no separate
# CSRF token is required. Non-cookie callers (API keys, Bearer headers) are
# unaffected by browser CSRF by construction.
SESSION_COOKIE_NAME = "marios_token"
# Pre-rebrand cookie name; still accepted so existing browser sessions stay
# valid until their natural expiry.
LEGACY_SESSION_COOKIE_NAME = "voyageos_token"


def session_cookie_max_age(session_hours: int | None = None) -> int:
    """会话 cookie 的 ``max_age``（秒）。

    ⚠️ 必须与 **JWT 的实际有效期**一致：租户把会话时长设成 2 小时时，
    JWT 是 2 小时过期，但 cookie 仍按全局 12 小时挂 —— 浏览器里留着一枚
    早就失效的 cookie，用户看到的是"莫名其妙 401"而不是干净的登出
    （P2「session_hours 死配置」的残留）。
    """
    if session_hours and int(session_hours) > 0:
        return int(session_hours) * 3600
    return settings.jwt_expire_minutes * 60


def set_session_cookie(response: Response, token: str, session_hours: int | None = None) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
        max_age=session_cookie_max_age(session_hours),
    )


def clear_session_cookie(response: Response) -> None:
    """清掉会话 cookie —— **两个都要清**（含 legacy 别名）。

    旧名 ``voyageos_token`` 仍被 :func:`get_current_auth` 接受，若登出时只清
    新名，持有旧 cookie 的会话在登出后**依然有效**（P1-16）。
    """
    for name in (SESSION_COOKIE_NAME, LEGACY_SESSION_COOKIE_NAME):
        response.set_cookie(
            name,
            "",
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            path="/",
            max_age=0,
        )


# ── 登出即失效（P1-16）────────────────────────────────────────────────
# JWT 本身无状态，登出后旧 token 还能用满 12 小时。这里用一份进程内的
# 「已登出 token 指纹」黑名单把登出那一刻的 token 作废：
# 登出时把 token 的 SHA-256 摘要 + 过期时间记进来，之后每次鉴权比对一次。
# 进程内存储 —— 多副本部署需要换成共享存储（Redis / DB），当前单进程部署
# 已能覆盖「登出后浏览器 cookie 立刻失效」这个真实诉求。
_REVOKED_TOKENS: dict[str, float] = {}


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def revoke_token(token: str, *, expires_at: datetime | None = None) -> None:
    """把一个 token 加入登出黑名单。"""
    exp = expires_at or (datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes))
    _prune_revoked()
    _REVOKED_TOKENS[token_fingerprint(token)] = exp.timestamp()


def _prune_revoked() -> None:
    """清掉已过期的黑名单条目（黑名单不能无限增长）。"""
    now = datetime.now(timezone.utc).timestamp()
    for fp, exp in list(_REVOKED_TOKENS.items()):
        if exp < now:
            _REVOKED_TOKENS.pop(fp, None)


def is_token_revoked(token: str) -> bool:
    fp = token_fingerprint(token)
    exp = _REVOKED_TOKENS.get(fp)
    if exp is None:
        return False
    if exp < datetime.now(timezone.utc).timestamp():
        _REVOKED_TOKENS.pop(fp, None)
        return False
    return True


def hash_password(password: str) -> str:
    """bcrypt 哈希 —— **按字节截断到 72**。

    bcrypt 的上限是 **72 字节不是 72 字符**（24 个汉字就到顶），且 bcrypt>=4.1
    对超长输入直接抛 ``ValueError`` → 未捕获就是 500。旧版 bcrypt(<4.1) 是
    **静默截断**的，所以历史用户的超长密码 hash 就是「截断后」的 —— 这里
    复刻老语义，既不 500，也兼容存量 hash。
    """
    return bcrypt.hashpw(_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """bcrypt 校验 —— 同样按 72 字节截断（兼容 bcrypt<4.1 的静默截断语义）。"""
    try:
        return bcrypt.checkpw(_bcrypt_bytes(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


#: 登录时用的**哑元哈希**（bcrypt cost 与真实口令一致）。
#:
#: 审计 P2「账号枚举」：登录失败时若用户不存在就**直接跳过 bcrypt**，
#: 用户存在才跑一次 → 两次失败的响应时间差 ~390ms，攻击者据此判断
#: 「这个邮箱有没有账号」。这里对不存在的用户也跑一次同样的 bcrypt，
#: 把时间差抹平。
_DUMMY_HASH = "$2b$12$wAUFyDXuW3NxC/p.LnRQXeWCVOGOmHk6tCwUOhvrMF.tf7nhZm..K"


def verify_password_or_dummy(password: str, password_hash: str | None) -> bool:
    """``password_hash`` 为空（用户不存在 / 无口令）时也跑一次 bcrypt。

    返回值恒为 ``False``（没有可比对的哈希），但**耗时**与真实校验一致 ——
    消除「用户不存在 → 立刻返回」的时序侧信道。
    """
    if not password_hash:
        try:
            bcrypt.checkpw(_bcrypt_bytes(password), _DUMMY_HASH.encode("utf-8"))
        except ValueError:  # pragma: no cover —— 哑元哈希是固定合法值
            pass
        return False
    return verify_password(password, password_hash)


#: bcrypt 的硬上限（字节）
BCRYPT_MAX_BYTES = 72


def _bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def password_byte_length(password: str) -> int:
    """口令的 UTF-8 **字节**长度（bcrypt 的真实上限单位）。"""
    return len(password.encode("utf-8"))


def validate_password_settable(password: str) -> str:
    """**设置**口令时的入参校验 —— 超 72 字节直接拒（422）。

    bcrypt 的上限是 **72 字节不是 72 字符**（24 个汉字就到顶），且
    bcrypt>=4.1 对超长输入**直接抛 ValueError** → 未捕获就是 500。
    老版本 bcrypt(<4.1) 是**静默截断**的，所以历史用户的超长口令 hash
    是「截断后」的 —— 校验侧（:func:`verify_password`）按同样的截断语义
    复刻，既不 500 也不锁死存量用户。

    ⚠️ 只在**设置**口令侧拒（这里）；**登录**侧不拒 —— 否则老用户会被
    锁在门外。
    """
    if password_byte_length(password) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"password must be at most {BCRYPT_MAX_BYTES} bytes when encoded as UTF-8"
        )
    return password


#: 「设置口令」字段的 Pydantic 类型 —— 超过 72 字节直接 422。
#:
#: 用法：``password: SetPassword = Field(min_length=8)``。
SetPassword = Annotated[str, AfterValidator(validate_password_settable)]


def _as_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def create_access_token(
    *,
    user_id: UUID,
    tenant_id: UUID,
    email: str,
    pwv: int = 1,
    session_hours: int | None = None,
) -> str:
    """签发访问令牌。

    ``session_hours`` 是**租户级**会话时长（``TenantAuthPolicy.session_hours``）。
    以前这个配置是死配置 —— 管理员在控制平面把它改成 2 小时，登录后拿到的令牌
    仍然是全局 ``JWT_EXPIRE_MINUTES``（默认 12 小时）才过期，配置形同虚设。
    为 None / 非法值时回落到全局配置。

    ``jti``（JWT ID，逐令牌唯一）有两个作用：

    1. **令牌唯一性** —— ``exp`` 精确到秒，同一用户在同一秒内两次登录会拿到
       **完全相同**的令牌（载荷里除 exp 外全都一样）。登出黑名单（P1-16）按
       令牌指纹作废，于是「A 登出 → B 同秒登录被误伤」。
    2. 将来接真正的会话表时，``jti`` 就是主键。
    """
    minutes = settings.jwt_expire_minutes
    if session_hours is not None and session_hours > 0:
        minutes = int(session_hours) * 60
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "pwv": pwv,
        "jti": uuid4().hex,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


class AuthContext:
    def __init__(self, user: User, roles: list[str]):
        self.user = user
        self.roles = roles
        self.tenant_id = user.tenant_id
        self.user_id = user.id


def _auth_from_user(db: Session, user: User) -> AuthContext:
    role_codes = list(
        db.scalars(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
        ).all()
    )
    return AuthContext(user=user, roles=role_codes)


def _auth_from_api_key(db: Session, raw_key: str) -> AuthContext:
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.status == "active"))
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if row.expires_at and _as_aware(row.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")
    user: User | None = None
    if row.user_id:
        # Keys are bound to a specific user at creation time
        bound = db.get(User, row.user_id)
        if bound and bound.tenant_id == row.tenant_id and bound.status == "active":
            user = bound
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner inactive")
    else:
        # Legacy keys without owner binding: fall back to earliest active user
        user = db.scalar(
            select(User).where(User.tenant_id == row.tenant_id, User.status == "active").order_by(User.created_at.asc())
        )
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active user for API key tenant")
    ctx = _auth_from_user(db, user)
    ctx.api_key_id = row.id  # type: ignore[attr-defined]
    ctx.api_key_scopes = list(row.scopes or [])  # type: ignore[attr-defined]
    return ctx


def _assert_tenant_active(db: Session, ctx: AuthContext) -> None:
    tenant = db.get(Tenant, ctx.tenant_id)
    if tenant and tenant.status == "suspended" and "platform_admin" not in ctx.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "TENANT_SUSPENDED", "message": "Tenant suspended"},
        )


def _auth_from_jwt(db: Session, token: str) -> AuthContext:
    """Shared JWT verification for Bearer header and HttpOnly cookie tracks:
    signature, tenant binding, user status, logout revocation and password-version
    (pwv) revocation."""
    # 登出黑名单 —— 登出后该 token 立即作废（P1-16）
    if is_token_revoked(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tenant_id"])
    except (JWTError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    user = db.get(User, user_id)
    if not user or user.tenant_id != tenant_id or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive")

    # Password version: tokens issued before a password change are revoked
    token_pwv = payload.get("pwv")
    if token_pwv is None or int(token_pwv) != int(user.password_version or 1):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    ctx = _auth_from_user(db, user)
    _assert_tenant_active(db, ctx)
    return ctx


def get_current_auth(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    legacy_session_cookie: str | None = Cookie(default=None, alias=LEGACY_SESSION_COOKIE_NAME),
) -> AuthContext:
    # Resolution order: X-API-Key, then Authorization Bearer, then session cookie.
    # A present-but-invalid header/API key fails immediately (no cookie fallback),
    # so programmatic callers get deterministic 401s.
    if x_api_key:
        ctx = _auth_from_api_key(db, x_api_key)
        _assert_tenant_active(db, ctx)
        # P1-15：API Key 的 scope **真正生效** —— 按请求路径判定该 key
        # 有没有覆盖这一块 API（以前全仓只有 1 个端点声明 scope，
        # 于是 scopes=["office"] 的 key 能调财务/管理/报表的所有端点）。
        _assert_api_key_scope(ctx, request.url.path, request.method)
        return ctx
    if creds is not None:
        return _auth_from_jwt(db, creds.credentials)
    token = session_cookie or legacy_session_cookie
    if token:
        return _auth_from_jwt(db, token)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


require_auth = get_current_auth


def get_current_auth_optional(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    legacy_session_cookie: str | None = Cookie(default=None, alias=LEGACY_SESSION_COOKIE_NAME),
) -> AuthContext | None:
    if creds is None and not x_api_key and not session_cookie and not legacy_session_cookie:
        return None
    try:
        return get_current_auth(
            request=request,
            creds=creds,
            db=db,
            x_api_key=x_api_key,
            session_cookie=session_cookie,
            legacy_session_cookie=legacy_session_cookie,
        )
    except HTTPException:
        return None


def require_api_scope(*required: str):
    """Scope check for API-key callers. JWT (interactive) auth passes through —
    user-level authorization is handled by role/module checks.

    Scope 语义（P1-15）：scope 是**能力名**，不是路径片段。
    - ``*``：全放行；
    - 精确匹配：``office`` / ``finance`` / ``reports`` / ``admin`` …；
    - **未声明任何 scope 的 API Key 一律拒绝**（空 scope = 无授权），
      避免「签发一把没 scope 的 key 就能调遍全站」。
    """

    def _dep(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        scopes = getattr(auth, "api_key_scopes", None)
        if scopes is None:
            return auth  # JWT（交互式）—— 由角色/模块闸门负责
        scopes = [str(s) for s in scopes]
        if "*" in scopes:
            return auth
        if not required:
            # 端点未声明 scope 要求：API Key 至少要有 *一个* scope 才算「有意授权」
            if not scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "SCOPE_REQUIRED", "scopes": list(required)},
                )
            return auth
        if not any(s in scopes for s in required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "SCOPE_REQUIRED", "scopes": list(required)},
            )
        return auth

    return _dep


# ── API Key scope 真正生效（P1-15）──────────────────────────────────────
#: API 路径前缀 → 该前缀需要的 scope 名。API Key 调用时按**最长前缀**匹配，
#: 匹配不到就要求 key 自带的 scope 命中该前缀的 scope 名。
#:
#: 为什么要有这张表：审计发现 ``require_api_scope`` 全仓**只有 1 处**调用，
#: 于是「声明 scopes=["office"] 的 key」实际上能调用全部财务/管理/报表端点
#: —— scope 形同虚设。现在 scope 在**鉴权入口**就按路径判定，
#: 不依赖每个路由是否记得声明 scope。
API_KEY_PATH_SCOPES: tuple[tuple[str, str], ...] = (
    ("/api/v1/office", "office"),
    ("/api/v1/invoices", "finance"),
    ("/api/v1/payments", "finance"),
    ("/api/v1/payment-batches", "finance"),
    ("/api/v1/finance", "finance"),
    ("/api/v1/gl", "finance"),
    ("/api/v1/claims", "claims"),
    ("/api/v1/laytimes", "laytime"),
    ("/api/v1/reports", "reports"),
    ("/api/v1/exports", "exports"),
    ("/api/v1/admin", "admin"),
    ("/api/v1/platform", "platform"),
    ("/api/v1/settings/api-keys", "apim"),
    ("/api/v1/settings/dataops", "dataops"),
    ("/api/v1/ai", "ai"),
    ("/api/v1/email", "email"),
    ("/api/v1/documents", "docs"),
)


def _required_scope_for_path(path: str) -> str | None:
    """请求路径 → 需要的 scope 名（最长前缀匹配）；无匹配则 None。"""
    best: tuple[int, str] | None = None
    for prefix, scope in API_KEY_PATH_SCOPES:
        if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), scope)
    return best[1] if best else None


def _assert_api_key_scope(auth: AuthContext, path: str, method: str) -> None:
    """API Key 的 scope 必须**覆盖**这次请求（P1-15）。

    - 路径落在某个受控前缀下 → key 必须持有该前缀的 scope（或 ``*``）；
    - 路径不在表里 → key 至少要有一个非空 scope（否则等于一把万能钥匙）；
    - 写方法（POST/PUT/PATCH/DELETE）额外要求 key 持有 ``write``
      （或 ``*``）—— 读权限不能改数据。
    """
    scopes = [str(s) for s in (getattr(auth, "api_key_scopes", None) or [])]
    if not scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SCOPE_REQUIRED", "message": "API key has no scopes"},
        )
    if "*" in scopes:
        return
    required = _required_scope_for_path(path)
    if required and required not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SCOPE_REQUIRED", "scopes": [required]},
        )
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and not (
        "write" in scopes or "*" in scopes
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "SCOPE_REQUIRED", "scopes": ["write"]},
        )


# ── 角色闸门（P1-14）───────────────────────────────────────────────────
# 「许可」与「授权」是两条轴：
#   * 许可（require_module）：租户**买没买**这个模块 —— 商业合同问题；
#   * 授权（require_roles / require_module_role）：这个**用户**能不能动这个模块。
# 之前 require_module 被当角色闸门用，于是「租户买了 finance」就等于
# 「租户里任何人都能读写财务」—— 越权。
#
# 角色→模块的映射以 **shell_nav.MODULES[].roles** 为准（前端导航已经认这套），
# 再补三条产品现实：
#   * ``tenant_admin`` —— 通配（租户管理员管一切）；
#   * ``viewer``       —— 只读兜底（不进任何可写模块）；
#   * 角色码在导航里叫 ``chartering`` / ``operations`` / ``technical`` /
#     ``finance`` / ``platform_admin``，而 ``require_module`` 用的模块码是
#     ``estimate`` / ``laytime`` / ``claims`` / ``ship_mgmt`` / ``bunker`` …
#     —— 两套命名不一致，下面这张表是**手工映射**（原因见注释）。
#
# ``LICENSE_DEV_UNLOCK=all`` **只旁路许可，不旁路角色**：许可旁路是商业开关
# （开发期全开合理），角色闸门是安全轴（旁路了等于测不出越权）。

#: require_module 的模块码 → shell_nav 的模块 id（**手工映射**）。
#:
#: 为什么要手工：`require_module` 用的模块码与 ``shell_nav`` 的模块 id 是两套
#: 不同源的命名 —— 前者来自 :data:`app.seed.CORE_MODULES`（许可目录），后者
#: 来自导航分组。逐条对应关系与原因：
#:
#: ==========  ==================  ==========================================
#: module code  shell_nav module   原因
#: ==========  ==================  ==========================================
#: chartering   chartering         同名
#: estimate     chartering         「估价/预算」在导航里属于租约工作台
#: email        chartering         「邮件审阅」是租约工作台的子项
#: operations   operations         同名
#: bunker       operations         「加油台」是操作台的子项
#: emissions    operations         「排放/合规」是操作台的子项
#: masterdata   operations         船舶/港口/对手方主数据由操作侧共用
#: ship_mgmt    technical          「船舶管理」属技术台
#: twin         technical          「Fleet Twin」与技术台同组
#: laytime      finance            滞期费按财务口径结算
#: claims       finance            索赔同属财务口径
#: pooling      finance            池期结算走财务
#: risk         finance            交易与风控在财务模块
#: finance      finance            同名
#: analytics    analytics          「分析报表」独立成组（roles = ["*"]）
#: ai           analytics          MariAI 在分析模块内
#: commercial   chartering         商务条款属租约工作台
#: ==========  ==================  ==========================================
#:
#: 下面这组**不**走 shell_nav，直接写死角色 —— 它们对应导航里的
#: 「Administration / 设置」区（``NAV_ADMIN``），那里只有 ``tenant_admin``，
#: 而 platform 侧的操作由 ``platform_admin`` 承担：
_MODULE_TO_SHELL_MODULE: dict[str, str] = {
    "chartering": "chartering",
    "estimate": "chartering",
    "email": "chartering",
    "commercial": "chartering",
    "operations": "operations",
    "bunker": "operations",
    "emissions": "operations",
    "masterdata": "operations",
    "ship_mgmt": "technical",
    "twin": "technical",
    "laytime": "finance",
    "claims": "finance",
    "pooling": "finance",
    "risk": "finance",
    "finance": "finance",
    "analytics": "analytics",
    "ai": "analytics",
}

#: 直接写死角色、不经 shell_nav 的模块码（管理面 / 平台面）
_MODULE_EXPLICIT_ROLES: dict[str, set[str]] = {
    "admin": {"tenant_admin", "platform_admin"},
    "integration": {"tenant_admin", "platform_admin"},
    "dataops": {"tenant_admin", "platform_admin"},
    "apim": {"tenant_admin", "platform_admin"},
    "docs": {"tenant_admin", "finance", "chartering", "management"},
    "selfcheck": {"tenant_admin", "platform_admin"},
}


def _shell_module_roles() -> dict[str, set[str]]:
    """shell_nav 的模块 → 允许的角色集合（读一次即缓存）。"""
    global _SHELL_MODULE_ROLES
    if _SHELL_MODULE_ROLES is not None:
        return _SHELL_MODULE_ROLES
    roles: dict[str, set[str]] = {}
    try:
        from app.services.shell_nav import MODULES

        for mod in MODULES:
            roles[mod["id"]] = set(mod.get("roles") or [])
    except Exception:  # noqa: BLE001 — 导航读不到时退化为「只有 tenant_admin」
        log.exception("shell_nav 角色映射读取失败，角色闸门退化为 tenant_admin")
        roles = {}
    _SHELL_MODULE_ROLES = roles
    return roles


_SHELL_MODULE_ROLES: dict[str, set[str]] | None = None

#: 无论导航怎么配都能写这些模块的角色（产品现实：租户管理员）
_ALWAYS_WRITE_ROLES = {"tenant_admin"}


def roles_for_module(module_code: str) -> set[str]:
    """某个 ``require_module`` 模块码 → 允许**写**的角色集合。

    ``tenant_admin`` 恒在；``viewer`` 恒不在（只读兜底）。

    ⚠️ ``shell_nav`` 里有 ``roles=["*"]`` 的**通配条目**（home / dashboards /
    tasks / exceptions）。``"*"`` 不是真实角色码，字面比较永远匹配不上 ——
    所以这里把通配展开成「除 viewer 外的所有已知角色」，而不是把 ``"*"``
    原样带进集合（那会让该模块变成「只有 tenant_admin 能进」）。
    """
    roles = set(_ALWAYS_WRITE_ROLES)
    explicit = _MODULE_EXPLICIT_ROLES.get(module_code)
    if explicit is not None:
        roles |= explicit
    else:
        shell_module = _MODULE_TO_SHELL_MODULE.get(module_code)
        if shell_module:
            module_roles = _shell_module_roles().get(shell_module, set())
            if "*" in module_roles:
                # 通配条目 → 展开成「除 viewer 外的全部已知角色」
                roles |= _all_known_roles() - {"viewer"}
            else:
                roles |= module_roles
    roles.discard("viewer")
    return roles


def _all_known_roles() -> set[str]:
    """仓库里出现过的全部角色码（用于展开 ``roles=["*"]`` 通配）。"""
    global _ALL_KNOWN_ROLES
    if _ALL_KNOWN_ROLES is not None:
        return _ALL_KNOWN_ROLES
    roles: set[str] = set()
    try:
        from app.seed import TENANT_ROLE_DEFS

        roles |= {code for code, _name, _perms in TENANT_ROLE_DEFS}
    except Exception:  # noqa: BLE001 — 种子表读不到时退化为最小集合
        log.exception("角色码清单读取失败，通配展开退化为最小集合")
    roles |= {"tenant_admin", "platform_admin", "viewer"}
    _ALL_KNOWN_ROLES = roles
    return roles


_ALL_KNOWN_ROLES: set[str] | None = None


def require_roles(*codes: str):
    """角色闸门 —— 与 :func:`require_module`（许可轴）分开。

    403 的 ``detail`` 里同时给出 ``roles``（要求）与 ``code``（仓库统一风格）。
    """

    def _dep(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if not any(c in auth.roles for c in codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "ROLE_REQUIRED", "roles": list(codes)},
            )
        return auth

    return _dep


def tenant_role_grants(db: Session, tenant_id) -> dict[str, set[str]]:
    """租户自定义的「角色 → 模块写权限」映射（来自 ``Role.permissions``）。

    ``Role.permissions`` 的形状（见 ``app/seed.py:TENANT_ROLE_DEFS``）是
    ``{"<module_code>": True, ..., "read": True}``：

    - ``{"finance": True}`` → 持有该角色的用户被授予 ``finance`` 模块的**写**权限；
    - ``{"*": True}`` → 该角色被授予**所有**模块的写权限；
    - ``{"read": True}`` → 只读标记，**不**授予任何写权限。

    返回 ``{module_code: {role_code, ...}}``，外加一个 ``"*"`` 键表示
    「这些角色被授予了**所有**模块的写权限」。这张表以前**从不参与鉴权**
    —— 租户管理员在「角色」页改的授权是摆设（P2「Role.permissions 从未参与鉴权」）。
    现在它只**追加**静态映射（shell_nav）之外的授权，不会收回静态映射已有的权限。
    """
    from app.models import Role

    grants: dict[str, set[str]] = {}
    try:
        rows = db.execute(
            select(Role.code, Role.permissions).where(Role.tenant_id == tenant_id)
        ).all()
    except Exception:  # noqa: BLE001 — 表不存在（老库）时退化为"无自定义授权"
        log.exception("读取租户角色授权失败，按无自定义授权处理")
        return grants
    for code, perms in rows:
        if not isinstance(perms, dict):
            continue
        for module_code, granted in perms.items():
            if not granted or module_code in ("read", "none"):
                continue
            if module_code == "*":
                # viewer 恒为只读 —— 与 roles_for_module 的不变式保持一致
                if code != "viewer":
                    grants.setdefault("*", set()).add(code)
                continue
            grants.setdefault(module_code, set()).add(code)
    return grants


def read_roles_for_module(module_code: str) -> set[str]:
    """某个模块码 → 允许**读**（查看/导出）的角色集合。

    与 :func:`roles_for_module`（写角色）的区别：

    - 写角色集合里**不含** ``viewer``（只读兜底角色）；
    - 读角色集合**含** ``viewer`` —— 导出是读操作，viewer 应当能导。
    """
    return roles_for_module(module_code) | {"viewer"}


def require_module_read(module_code: str, *extra_roles: str):
    """许可 + 角色双闸门（**读**端点用 —— 列表、导出、报表）。

    与 :func:`require_module_role` 的区别：允许 ``viewer``（只读角色），
    并且**不**被 ``LICENSE_DEV_UNLOCK`` 旁路（许可轴可以被 dev unlock 旁路，
    角色轴不行）。

    以前导出端点只有许可轴（``require_module``），角色轴缺失 → 菜单里被锁
    在模块外的角色照样能把整张表导出去（"能导不能看"倒挂，P2）。
    """

    def _dep(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)) -> AuthContext:
        if settings.license_dev_unlock != "all":
            lic = db.scalar(
                select(TenantModuleLicense).where(
                    TenantModuleLicense.tenant_id == auth.tenant_id,
                    TenantModuleLicense.module_code == module_code,
                    TenantModuleLicense.status.in_(["active", "grace"]),
                )
            )
            if lic and lic.expires_at and _as_aware(lic.expires_at) < datetime.now(timezone.utc):
                lic = None
            if not lic:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "MODULE_NOT_LICENSED", "module": module_code},
                )
        allowed = read_roles_for_module(module_code) | set(extra_roles)
        if not any(r in allowed for r in auth.roles):
            grants = tenant_role_grants(db, auth.tenant_id)
            allowed |= grants.get(module_code, set())
            if auth.roles and set(auth.roles) & grants.get("*", set()):
                allowed |= set(auth.roles)
        if not any(r in allowed for r in auth.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ROLE_REQUIRED",
                    "module": module_code,
                    "roles": sorted(allowed),
                },
            )
        return auth

    return _dep


def require_module_role(module_code: str, *extra_roles: str):
    """许可 + 角色双闸门（写端点用）。

    - 许可：租户买了这个模块（``require_module`` 的语义，``LICENSE_DEV_UNLOCK=all`` 旁路）；
    - 角色：用户持有的角色确实被允许**写**这个模块（**不被 dev unlock 旁路**）。
    """

    def _dep(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)) -> AuthContext:
        if settings.license_dev_unlock != "all":
            lic = db.scalar(
                select(TenantModuleLicense).where(
                    TenantModuleLicense.tenant_id == auth.tenant_id,
                    TenantModuleLicense.module_code == module_code,
                    TenantModuleLicense.status.in_(["active", "grace"]),
                )
            )
            if lic and lic.expires_at and _as_aware(lic.expires_at) < datetime.now(timezone.utc):
                lic = None
            if not lic:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={"code": "MODULE_NOT_LICENSED", "module": module_code},
                )
        allowed = roles_for_module(module_code) | set(extra_roles)
        if not any(r in allowed for r in auth.roles):
            # 静态映射（shell_nav）没放行 → 再看**租户自定义授权**
            # （``Role.permissions`` JSON：``{"finance": True}`` = 该角色被授予
            # 财务模块写权限）。以前这一列**从不参与鉴权**，租户管理员在
            # 「角色」页改的授权全是摆设（P2「Role.permissions 从未参与鉴权」）。
            #
            # 只在**将要拒绝**时才查一次库 —— 放行路径零额外开销。
            grants = tenant_role_grants(db, auth.tenant_id)
            allowed |= grants.get(module_code, set())
            if auth.roles and set(auth.roles) & grants.get("*", set()):
                allowed |= set(auth.roles)
        if not any(r in allowed for r in auth.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ROLE_REQUIRED",
                    "module": module_code,
                    "roles": sorted(allowed),
                },
            )
        return auth

    return _dep


def require_module(module_code: str):
    """**许可**闸门（租户买没买这个模块）。

    ⚠️ 这**不是**角色闸门 —— 「买了模块」不等于「这个人有权操作」。
    写端点请用 :func:`require_module_role`（许可 + 角色）或
    :func:`require_roles`（纯角色）。
    """

    def _dep(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)) -> AuthContext:
        if not tenant_has_module(db, auth.tenant_id, module_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "MODULE_NOT_LICENSED", "module": module_code},
            )
        return auth

    return _dep


# ── 出网白名单（P0-18 SSRF）──────────────────────────────────────────────
#: 云厂商元数据地址（即使解析成公网 IP 也要拦）
_METADATA_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "metadata",
        "instance-data",
        "169.254.169.254",
        "100.100.100.200",
        "fd00:ec2::254",
    }
)


def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return True
    if addr.is_reserved or addr.is_multicast or addr.is_unspecified:
        return True
    # 100.64.0.0/10（运营商级 NAT）与 192.0.0.0/24 等「非公网但非私网」段
    if addr.version == 4 and ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10"):
        return True
    return False


def outbound_allowed_hosts() -> set[str]:
    """配置里显式放行的出网 host（小写去端口）。"""
    raw = (settings.outbound_allowed_hosts or "").strip()
    out: set[str] = set()
    for part in raw.replace(";", ",").split(","):
        host = part.strip().lower()
        if host:
            out.add(host.split(":", 1)[0] if host.count(":") == 1 else host)
    return out


def assert_safe_outbound_url(url: str, *, purpose: str = "outbound request") -> str:
    """出网 URL 白名单校验 —— 拒绝内网/环回/链路本地/元数据地址（P0-18）。

    - 只允许 http / https；
    - host 命中 ``OUTBOUND_ALLOWED_HOSTS`` → 显式放行（租户自建内网服务）；
    - host 是 IP 字面量 → 按地址段判定；
    - host 是域名 → **解析后**逐个检查 A/AAAA 结果（防 DNS rebinding 之外的
      直接指向内网的写法），解析失败则拒绝（fail-closed）。

    失败抛 ``HTTPException`` 403，code = ``OUTBOUND_URL_BLOCKED``。
    """
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OUTBOUND_URL_BLOCKED",
                "message": f"{purpose}: unsupported URL scheme",
            },
        )
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "OUTBOUND_URL_BLOCKED", "message": f"{purpose}: URL has no host"},
        )
    allowed = outbound_allowed_hosts()
    # 显式白名单优先（租户自建内网服务），但**元数据地址永不放行**
    if host in allowed and host not in _METADATA_HOSTS:
        return url
    if host in _METADATA_HOSTS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OUTBOUND_URL_BLOCKED",
                "message": f"{purpose}: metadata endpoint is not allowed",
            },
        )

    # IP 字面量
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if _is_blocked_ip(host):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "OUTBOUND_URL_BLOCKED",
                    "message": f"{purpose}: private/loopback/link-local address is not allowed",
                },
            )
        return url

    # 域名 —— 解析后逐个检查
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "OUTBOUND_URL_BLOCKED",
                "message": f"{purpose}: host could not be resolved",
            },
        ) from exc
    for info in infos:
        addr = info[4][0]
        if _is_blocked_ip(addr):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "OUTBOUND_URL_BLOCKED",
                    "message": f"{purpose}: host resolves to a private address",
                },
            )
    return url


def require_feature(feature_code: str):
    """Enforce tenant feature permission matrix (see /admin/permissions)."""

    def _dep(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)) -> AuthContext:
        from app.services.saas_engine import assert_feature

        assert_feature(db, auth.tenant_id, auth.roles, feature_code)
        return auth

    return _dep


def tenant_has_module(db: Session, tenant_id: UUID, module_code: str) -> bool:
    """该租户是否**买**了某模块（许可轴，``require_module`` 的可复用内核）。

    服务层要用（比如 AI 工具执行前查模块许可），但那里没有 FastAPI 依赖，
    所以把判定逻辑抽成函数，``require_module`` 与它共用同一份语义。
    """
    if settings.license_dev_unlock == "all":
        return True
    lic = db.scalar(
        select(TenantModuleLicense).where(
            TenantModuleLicense.tenant_id == tenant_id,
            TenantModuleLicense.module_code == module_code,
            TenantModuleLicense.status.in_(["active", "grace"]),
        )
    )
    if lic and lic.expires_at and _as_aware(lic.expires_at) < datetime.now(timezone.utc):
        return False
    return lic is not None


#: 备份/导出落盘时**必须剔除**的列（P0-21）。
#: ``tenant_backup._dump_table`` 会把每张表**所有列**原样导出 ——
#: 包括 ``users.password_hash``、``api_keys.key_hash``、以及连接器配置里的
#: 明文密钥。备份文件落在磁盘上（``data/backups/tenant/…``），一旦被读走
#: 就是「全量口令哈希 + 明文 API Key」。
SENSITIVE_DUMP_COLUMNS: frozenset[str] = frozenset(
    {
        "password_hash",
        "key_hash",
        "secret_ref",
        "ms_client_secret",
        "smtp_password_cipher",
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "api_key",
        "secret",
    }
)

#: 配置 JSON 里出现这些键名就整块剔除
SENSITIVE_DUMP_KEY_HINTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "private_key",
)


def redact_sensitive_fields(payload: dict) -> dict:
    """把备份 payload 里的敏感列/敏感配置键剔除（P0-21）。

    就地修改并返回同一个 dict（dump payload 是一次性构造的）。
    """
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        return payload
    for _table, rows in tables.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in list(row.keys()):
                if key in SENSITIVE_DUMP_COLUMNS:
                    row.pop(key, None)
                    continue
                value = row.get(key)
                if isinstance(value, dict):
                    row[key] = {
                        k: v
                        for k, v in value.items()
                        if not any(h in str(k).lower() for h in SENSITIVE_DUMP_KEY_HINTS)
                    }
    return payload


def error_body(code: str, message: str, details: list[Any] | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or []}}
