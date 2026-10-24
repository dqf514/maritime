"""回收站覆盖度：凡是进了回收站的实体，都必须能被「恢复」。

背景：``routers/recycle.py`` 的 ``ENTITY_LOOKUP`` 决定哪些 entity_type 可以恢复。
历史上它只登记了 27 类，而各路由实际会写入 46 类软删记录 —— 另外 19 类在回收站里
看得见条目、点「恢复」必然 400 UNSUPPORTED_TYPE（前端只弹一句 "Failed"）。

本文件锁住两件事：
1. 静态守卫 —— 各路由里 ``soft_delete(entity_type="…")`` 的字面量类型必须都在
   ``ENTITY_LOOKUP`` 里；新增实体类型却忘了登记时，测试立即失败。
2. 功能回归 —— 典型实体（task）删除 → 进回收站 → 恢复 → 重新可见。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.routers.recycle import ENTITY_LOOKUP

ROUTERS_DIR = Path(__file__).resolve().parent.parent / "app" / "routers"


def _soft_delete_entity_types() -> set[str]:
    """扫描所有路由里 ``soft_delete(...)`` 调用的 entity_type 字面量。"""
    types: set[str] = set()
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for match in re.finditer(r"soft_delete\(", src):
            i = match.end()
            depth = 1
            while i < len(src) and depth:
                if src[i] == "(":
                    depth += 1
                elif src[i] == ")":
                    depth -= 1
                i += 1
            block = src[match.end() : i]
            found = re.search(r'entity_type\s*=\s*"([^"]+)"', block)
            if found:
                types.add(found.group(1))
    return types


def test_every_soft_deleted_entity_type_is_restorable():
    """任何被软删并写入回收站的实体类型，都必须在 ENTITY_LOOKUP 里登记。"""
    types = _soft_delete_entity_types()
    assert len(types) >= 40, f"扫描到的 entity_type 异常偏少（{len(types)}），扫描逻辑可能失效"
    missing = sorted(t for t in types if t not in ENTITY_LOOKUP)
    assert not missing, f"回收站无法恢复的实体类型（点恢复必报 UNSUPPORTED_TYPE）: {missing}"


def test_restore_status_defaults_cover_lookup():
    """有 status 列的实体，恢复时必须有兜底状态（payload 缺失时用）。"""
    from app.services.recycle import DEFAULT_RESTORE_STATUS

    missing = []
    for entity_type, (model, _scoped) in ENTITY_LOOKUP.items():
        if "status" in model.__table__.columns and entity_type not in DEFAULT_RESTORE_STATUS:
            missing.append(entity_type)
    assert not missing, f"缺少 DEFAULT_RESTORE_STATUS 兜底: {missing}"


def test_task_delete_restore_roundtrip(client, auth_headers):
    """任务删除 → 回收站可见 → 恢复 → 重新出现在任务列表。"""
    created = client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"title": "RECYCLE-COVERAGE-TASK", "priority": "normal"},
    )
    assert created.status_code in (200, 201), created.text
    task_id = created.json()["id"]

    deleted = client.delete(f"/api/v1/tasks/{task_id}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text

    bin_rows = client.get("/api/v1/recycle-bin", headers=auth_headers).json()
    hit = [x for x in bin_rows if x["entity_type"] == "task" and x["entity_id"] == task_id]
    assert hit, "任务删除后应出现在回收站"

    restored = client.post(f"/api/v1/recycle-bin/{hit[0]['id']}/restore", headers=auth_headers)
    assert restored.status_code == 200, restored.text

    rows = client.get("/api/v1/tasks", headers=auth_headers).json()
    assert any(x["id"] == task_id for x in rows), "恢复后任务应重新出现在列表"
