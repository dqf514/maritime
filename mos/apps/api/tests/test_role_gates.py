"""P1-14 · 「许可闸门 ≠ 授权闸门」——管理面写端点的角色矩阵。

审计结论（见 ``_guide_work/sim/AUDIT-REPORT.md`` §P1-14）：

- ``require_module(code)`` 只回答「**这个租户买没买这个模块**」，**完全不查
  角色**；
- 管理面模块码（``admin`` / ``integration`` / ``dataops`` / ``apim`` /
  ``selfcheck``）被 105 个端点当作**授权**闸门用；
- 而 ``admin`` **根本不是模块目录里的模块**（``app/seed.py:CORE_MODULES``
  没有它）→ 生产环境这 54 个端点对**所有人** 403（含 tenant_admin）；
  开发环境 ``LICENSE_DEV_UNLOCK=all`` 又让它们对**任何登录用户**敞开。

两条都错。正确形态：

- 管理面端点用**角色闸门**（``require_roles("tenant_admin", …)`` 或
  ``require_module_role(code)`` = 许可 + 角色）；
- 许可轴只回答"买没买"，**永远不单独当授权用**。

这个测试做两件事：

1. **结构不变式** —— 遍历全部路由，断言「管理面模块码的写端点**必须**带
   角色闸门」。新加的端点忘了加角色闸门 → 直接失败。
2. **功能矩阵** —— 真实登录各角色，断言普通业务角色打不开管理面写端点。
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from fastapi.routing import APIRoute

from tests.isolation_helpers import login

API = "/api/v1"

#: 管理面模块码 —— 这些码的写端点必须再叠一层角色闸门。
ADMIN_PLANE_MODULES = {
    "admin",
    "integration",
    "dataops",
    "apim",
    "selfcheck",
}

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _all_routes() -> list[APIRoute]:
    """遍历 app/routers 下的全部路由。

    注意：本版本的 FastAPI **不会**把 include_router 之后的路由摊平到
    ``app.routes``（那里只有 7 个 ``_IncludedRouter``），必须逐个 import
    路由模块再读 ``module.router.routes``。
    """
    import app.routers as routers_pkg

    out: list[APIRoute] = []
    for mod_info in pkgutil.iter_modules(routers_pkg.__path__):
        try:
            mod = importlib.import_module(f"app.routers.{mod_info.name}")
        except Exception:  # noqa: BLE001 — 个别模块可能依赖可选依赖
            continue
        router = getattr(mod, "router", None)
        if router is None:
            continue
        for r in getattr(router, "routes", []):
            if isinstance(r, APIRoute):
                out.append(r)
    return out


def _gates(route: APIRoute) -> set[tuple[str, str | None]]:
    """把路由依赖里的闸门解析成 ``{("module", code) | ("module_role", code) | ("roles", None)}``。"""
    gates: set[tuple[str, str | None]] = set()
    for dep in route.dependant.dependencies:
        call = dep.call
        code_obj = getattr(call, "__code__", None)
        if code_obj is None:
            continue
        freevars = list(code_obj.co_freevars)
        cells = list(getattr(call, "__closure__", None) or ())
        closure: dict[str, object] = {}
        for name, cell in zip(freevars, cells):
            try:
                closure[name] = cell.cell_contents
            except ValueError:  # noqa: BLE001 — 空闭包槽
                continue
        if "module_code" in freevars:
            module_code = closure.get("module_code")
            if not isinstance(module_code, str):
                continue
            if "extra_roles" in freevars:
                gates.add(("module_role", module_code))
            else:
                gates.add(("module", module_code))
        elif "codes" in freevars:
            gates.add(("roles", None))
    return gates


# —— 结构不变式 ——
def test_admin_plane_write_endpoints_have_role_gate():
    """管理面模块码的写端点必须同时带角色闸门（许可轴不能单独当授权用）。"""
    offenders: list[str] = []
    for route in _all_routes():
        if not (set(route.methods or ()) & WRITE_METHODS):
            continue
        gates = _gates(route)
        module_codes = {c for kind, c in gates if kind == "module" and c}
        if not (module_codes & ADMIN_PLANE_MODULES):
            continue
        if ("roles", None) in gates or any(kind == "module_role" for kind, _ in gates):
            continue
        offenders.append(f"{sorted(route.methods)} {route.path}")
    assert not offenders, (
        "这些管理面写端点只有许可闸门（require_module），没有角色闸门 —— "
        "任何登录用户都能操作：\n  " + "\n  ".join(sorted(offenders))
    )


def test_no_write_endpoint_uses_unknown_module_code():
    """`require_module("admin")` 这种**目录里不存在**的模块码必须清零。

    目录见 app/seed.py:CORE_MODULES —— 不存在的码在生产环境会让端点对
    所有人 403（租户管理员也进不去）。
    """
    from app.seed import CORE_MODULES

    known = {code for code, _name, _core in CORE_MODULES}
    offenders: list[str] = []
    for route in _all_routes():
        for kind, code in _gates(route):
            if kind != "module" or not code:
                continue
            if code not in known:
                offenders.append(f"{sorted(route.methods)} {route.path} → {code!r}")
    assert not offenders, (
        "这些端点用了模块目录里不存在的模块码（生产环境必然 403）：\n  "
        + "\n  ".join(sorted(offenders))
    )


# —— 功能矩阵 ——
#: 管理面端点（真实路径，router 各自带 prefix）。
ADMIN_ONLY_ENDPOINTS = [
    ("GET", "/api/v1/webhooks/subscriptions", None),
    ("GET", "/api/v1/field-permissions/entities", None),
    ("GET", "/api/v1/udf/entities", None),
    ("GET", "/api/v1/config/flags", None),
]


@pytest.mark.parametrize("method,path,body", ADMIN_ONLY_ENDPOINTS)
def test_non_admin_role_is_blocked(client, method, path, body):
    """普通业务角色打不开管理面端点。"""
    headers = login(client, "charterer@demo.marios")
    resp = client.request(method, path, headers=headers)
    assert resp.status_code == 403, f"{method} {path} 对 chartering 角色返回了 {resp.status_code}"


def test_tenant_admin_can_reach_admin_plane(client, auth_headers):
    """租户管理员**必须**能打开管理面端点（不能像现在这样被 403 挡在门外）。"""
    resp = client.get("/api/v1/field-permissions/entities", headers=auth_headers)
    assert resp.status_code == 200, resp.text


def test_viewer_is_never_a_write_role():
    """viewer 永远不是写角色（闸门表层面的断言）。"""
    from app.security import roles_for_module

    for module in ("admin", "integration", "dataops", "apim", "selfcheck"):
        assert "viewer" not in roles_for_module(module)
        assert "tenant_admin" in roles_for_module(module)



# —— 租户自定义授权（Role.permissions 参与鉴权）——
def test_tenant_role_permissions_grant_module_access(client, auth_headers, db_engine):
    """``Role.permissions`` 以前**从不参与鉴权**（P2「Role.permissions 从未参与鉴权」）。

    租户管理员给某个角色加一个模块授权后，持有该角色的用户**应该**能操作该模块。
    """
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.models import Role

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    db = TestingSession()
    try:
        row = db.scalar(select(Role).where(Role.tenant_id == _demo_tid(db), Role.code == "chartering"))
        assert row is not None
        old = dict(row.permissions or {})
        # 前提：种子里的 chartering 角色**没有** dataops 授权，否则本用例形同虚设。
        assert not old.get("dataops"), f"种子已授予 dataops，本用例失去意义：{old}"
        row.permissions = {**old, "dataops": True}
        db.commit()

        # 租户管理员改授权的端点本身也要能用
        upd = client.put(
            "/api/v1/admin/roles/chartering/permissions",
            headers=auth_headers,
            json={"permissions": {**old, "dataops": True}},
        )
        assert upd.status_code == 200, upd.text
        assert upd.json()["permissions"].get("dataops") is True
    finally:
        db.close()

    # 现在 chartering 角色应当被允许访问 dataops 模块的端点。
    #
    # 端点必须用**角色闸门**（``require_module_role("dataops")``），否则
    # ``Role.permissions`` 根本没机会参与鉴权 —— 以前这里打的是
    # ``/field-permissions/entities``（只挂 ``require_roles``），无论怎么授权
    # 都能过，授权"生效"是假象。
    headers = login(client, "charterer@demo.marios")
    resp = client.get("/api/v1/settings/dataops/backups", headers=headers)
    assert resp.status_code == 200, f"租户自定义授权未生效：{resp.status_code} {resp.text}"


def test_tenant_role_grant_does_not_open_dataops_before_grant(client, db_engine):
    """反向护栏：**没**授权时 dataops 端点必须 403（授权不是橡皮图章）。"""
    from sqlalchemy.orm import sessionmaker

    TestingSession = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    db = TestingSession()
    try:
        from app.models import Role
        from sqlalchemy import select

        row = db.scalar(select(Role).where(Role.tenant_id == _demo_tid(db), Role.code == "chartering"))
        assert row is not None
        assert not (row.permissions or {}).get("dataops")
    finally:
        db.close()

    headers = login(client, "charterer@demo.marios")
    resp = client.get("/api/v1/settings/dataops/backups", headers=headers)
    assert resp.status_code == 403, f"未授权却放行了：{resp.status_code} {resp.text}"


def test_viewer_cannot_receive_wildcard_write_grant(client, auth_headers):
    """viewer 是只读角色 —— 不允许给它 ``"*"`` 通配写授权。"""
    resp = client.put(
        "/api/v1/admin/roles/viewer/permissions",
        headers=auth_headers,
        json={"permissions": {"*": True}},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "ROLE_PERMISSION_INVALID"


def _demo_tid(db):
    from sqlalchemy import select

    from app.models import Tenant

    return db.scalar(select(Tenant).where(Tenant.code == "demo")).id
