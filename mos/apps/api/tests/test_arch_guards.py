"""架构守卫（Phase 0）：租户隔离强制化 + schema 冻结。

1. ``test_no_new_unprotected_router_queries`` — 扫描 routers/ 的 ORM 查询点，
   凡函数体内既不出现 ``tenant_id`` 过滤也不使用 ``scoped_get/scoped_query``
   封装的，记为未保护点。基线（``arch_baseline.json``）之外**不允许新增**。
   跨租户是设计意图的平台路由显式豁免。
   **全局参考数据豁免**：表里**根本没有 ``tenant_id`` 列**的模型
   （港口、港口别���/泊位、Worldscale 费率表、节假日、货物品名 …）天然不是
   "漏了租户过滤" —— 守卫改为按模型判定，这类查询点不再计入未保护清单。
   这不是放水：漏写租户过滤的错误只在**有 tenant_id 的表**上才成立。
2. ``test_alter_patches_frozen`` — ``app/main.py`` 的 SQLite ALTER 兼容补丁
   列表已冻结：schema 变更一律新增 Alembic revision（见 alembic/README.md），
   不再往补丁列表加列。确需更新基线时必须在评审中明示。

首次引入即建立基线；后续改动让基线只减不增（重构消掉未保护点是鼓励方向）。
"""

from __future__ import annotations

import ast
import importlib
import json
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
ROUTERS = API_ROOT / "app" / "routers"
MAIN_PY = API_ROOT / "app" / "main.py"
BASELINE_FILE = Path(__file__).resolve().parent / "arch_baseline.json"

# 跨租户可见是设计意图的平台路由（test_platform_admin_semantics 语义）：
# 这些文件不参与隔离扫描，但仍受其他守卫约束。
CROSS_TENANT_BY_DESIGN = {
    "platform.py",
    "platform_ops.py",
    "admin_platform.py",
}

QUERY_FUNCS = {"select", "update", "delete", "insert"}
# 这些 Session 方法名不会出现在 dict 上，恒计为查询点
QUERY_METHODS = {"scalars", "scalar", "execute", "query"}
# .get 需区分 ORM Session.get(Model, pk) 与 dict.get(k)：
# 仅当接收者是 session/db 风格对象时才计为查询点（dict.get 是常见误报）
GET_METHODS = {"get"}
SESSION_HINTS = {"db", "session", "sess", "conn", "connection", "dao", "store", "datastore"}
PROTECT_MARKERS = ("tenant_id", "scoped_get", "scoped_query")


def _global_reference_models() -> set[str]:
    """返回所有**没有 tenant_id 列**的 ORM 模型名。

    这些是全局参考数据（港口、港口别名/泊位、Worldscale 费率、节假日、
    货物品名、参考包 …）—— 表里没有租户维度，查询它们不存在"漏租户过滤"
    这类缺陷。若把它们和真正的租户表混在一起按字符串猜，会误伤/漏判，
    所以这里直接读 ORM 元数据。
    """
    names: set[str] = set()
    for mod_path in sorted(API_ROOT.glob("app/models*.py")):
        mod_name = "app." + mod_path.stem
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001 - 单个模块导入失败不应让守卫失效
            continue
        for obj in vars(mod).values():
            table = getattr(obj, "__table__", None)
            if table is None:
                continue
            if "tenant_id" not in {c.name for c in table.columns}:
                names.add(obj.__name__)
    return names


_GLOBAL_REFERENCE_MODELS: set[str] | None = None


def _global_models() -> set[str]:
    global _GLOBAL_REFERENCE_MODELS
    if _GLOBAL_REFERENCE_MODELS is None:
        _GLOBAL_REFERENCE_MODELS = _global_reference_models()
    return _GLOBAL_REFERENCE_MODELS


def _queried_model_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """函数体内 ``select(Model)`` / ``Model.__table__`` 提到的模型名。"""
    out: set[str] = set()
    for stmt in fn.body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id in {"select", "update", "delete"}:
                for arg in node.args:
                    if isinstance(arg, ast.Name):
                        out.add(arg.id)
    return out


def _func_protected(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    src = ast.dump(fn)
    if any(marker in src for marker in PROTECT_MARKERS):
        return True
    # 只查全局参考数据的函数 → 结构上不可能漏租户过滤
    models = _queried_model_names(fn)
    return bool(models) and models <= _global_models()


def _session_like(receiver: ast.AST) -> bool:
    try:
        text = ast.unparse(receiver)
    except Exception:
        return False
    return any(seg in SESSION_HINTS for seg in text.split("."))


def _has_query_site(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    # 只扫函数体：装饰器（@router.get 等）不是 ORM 查询点
    for stmt in fn.body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id in QUERY_FUNCS:
                return True
            if isinstance(f, ast.Attribute) and f.attr in QUERY_METHODS:
                return True
            if isinstance(f, ast.Attribute) and f.attr in GET_METHODS and _session_like(f.value):
                return True
    return False


def unprotected_query_sites() -> list[str]:
    out: list[str] = []
    for path in sorted(ROUTERS.glob("*.py")):
        if path.name in CROSS_TENANT_BY_DESIGN or path.name.startswith("_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _has_query_site(node) and not _func_protected(node):
                    out.append(f"{path.name}::{node.name}")
    return sorted(out)


def test_no_new_unprotected_router_queries():
    baseline = set(json.loads(BASELINE_FILE.read_text(encoding="utf-8"))["unprotected_query_sites"])
    current = set(unprotected_query_sites())
    new = sorted(current - baseline)
    assert not new, (
        "新的未受租户保护的查询点（路由函数需带 tenant_id 过滤或使用 "
        f"scoped_get/scoped_query）：{new}"
    )


def alter_patch_columns() -> list[str]:
    """Extract the frozen (table, col) pairs from main.py's compatibility patches."""
    src = MAIN_PY.read_text(encoding="utf-8")
    pairs = re.findall(r'\(\s*"([a-z_]+)",\s*"([a-z_]+)"', src)
    return sorted({f"{t}.{c}" for t, c in pairs})


def test_alter_patches_frozen():
    frozen = sorted(json.loads(BASELINE_FILE.read_text(encoding="utf-8"))["alter_patch_columns"])
    current = alter_patch_columns()
    added = sorted(set(current) - set(frozen))
    assert not added, (
        f"app/main.py 的 ALTER 兼容补丁列表已冻结，检测到新增列 {added}。"
        "schema 变更请新增 Alembic revision（alembic/README.md）。"
    )
