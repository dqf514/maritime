"""架构守卫（Phase 0）：租户隔离强制化 + schema 冻结。

1. ``test_no_new_unprotected_router_queries`` — 扫描 routers/ 的 ORM 查询点，
   凡函数体内既不出现 ``tenant_id`` 过滤也不使用 ``scoped_get/scoped_query``
   封装的，记为未保护点。基线（``arch_baseline.json``）之外**不允许新增**。
   跨租户是设计意图的平台路由显式豁免。
2. ``test_alter_patches_frozen`` — ``app/main.py`` 的 SQLite ALTER 兼容补丁
   列表已冻结：schema 变更一律新增 Alembic revision（见 alembic/README.md），
   不再往补丁列表加列。确需更新基线时必须在评审中明示。

首次引入即建立基线；后续改动让基线只减不增（重构消掉未保护点是鼓励方向）。
"""

from __future__ import annotations

import ast
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
QUERY_METHODS = {"get", "scalars", "scalar", "execute", "query"}
PROTECT_MARKERS = ("tenant_id", "scoped_get", "scoped_query")


def _func_protected(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    src = ast.dump(fn)
    return any(marker in src for marker in PROTECT_MARKERS)


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
