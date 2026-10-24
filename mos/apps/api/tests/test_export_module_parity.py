"""CSV 导出端点的许可模块必须与对应列表端点一致（P2「导出端点角色不齐」）。

导出是列表的"另一条腿" —— 两边的许可闸门必须同码，否则会出现两种
荒唐局面：

- 买了 claims / laytime 模块的租户**能看列表却导不出**（导出卡在别的
  模块码上）；
- 买了 finance 却没买 claims 的租户**不用看列表就能把索赔导出去** ——
  许可闸门形同虚设。

这个测试直接读各路由模块里列表端点的依赖闭包，把模块码与导出的
模块码对上。
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from app.routers import (
    bunker,
    claims,
    commercial,
    invoices,
    laytimes,
    masterdata,
    masterdata_ext,
    operations,
    payment_batches,
    ship_mgmt,
    tasks,
)
from app.routers.exports import ENTITIES

#: 导出实体 → (路由模块, 列表端点路径)。
ENTITY_LIST_ROUTES: dict[str, tuple[object, str]] = {
    "voyages": (operations, "/voyages"),
    "invoices": (invoices, "/invoices"),
    "certificates": (ship_mgmt, "/ship/certificates"),
    "tasks": (tasks, "/tasks"),
    "vessels": (masterdata, "/masterdata/vessels"),
    "distances": (commercial, "/distances"),
    "counterparties": (masterdata, "/masterdata/counterparties"),
    "ports": (masterdata, "/masterdata/ports"),
    "cargo-names": (masterdata_ext, "/masterdata/cargo-names"),
    "claims": (claims, "/claims"),
    "charters": (commercial, "/charters"),
    "laytimes": (laytimes, "/laytimes"),
    "bunker-orders": (bunker, "/bunker-orders"),
    "payments": (payment_batches, "/payments/payable-invoices"),
}

#: 这些实体的导出刻意不带许可闸门（导出内容比列表更窄，自带行级收窄）。
NO_MODULE_GATE = {"tasks"}


def _find_route(module, path: str) -> APIRoute:
    for r in module.router.routes:
        if isinstance(r, APIRoute) and r.path == path:
            return r
    raise AssertionError(f"{module.__name__} 里找不到列表端点 {path}")


def _module_code(route: APIRoute) -> str | None:
    """从路由依赖里挖出 ``require_module(code)`` 的模块码。"""
    for dep in route.dependant.dependencies:
        call = dep.call
        code = getattr(call, "__code__", None)
        if code is None:
            continue
        for name, cell in zip(code.co_freevars, getattr(call, "__closure__", None) or ()):
            if name == "module_code" and isinstance(cell.cell_contents, str):
                return cell.cell_contents
    return None


def test_export_entities_cover_all_lists():
    """导出实体集合与列表路径集合一一对应（多一个少一个都是漂移）。"""
    assert set(ENTITY_LIST_ROUTES) == set(ENTITIES)


@pytest.mark.parametrize("entity", sorted(ENTITY_LIST_ROUTES))
def test_export_module_matches_list_module(entity):
    module, path = ENTITY_LIST_ROUTES[entity]
    list_route = _find_route(module, path)
    list_module = _module_code(list_route)
    export_module = ENTITIES[entity][0]

    if entity in NO_MODULE_GATE:
        assert export_module is None
        return

    assert export_module is not None, f"{entity} 的导出缺少许可闸门"
    assert list_module is not None, (
        f"{entity} 的列表端点 {path} 没有 require_module —— "
        "无法与导出比对，请先确认列表端点的许可轴"
    )
    assert export_module == list_module, (
        f"{entity}：导出用模块 '{export_module}'，列表用 '{list_module}' —— "
        "两者必须同码，否则会出现「看得到却导不出」或「不用看就能导出」"
    )
