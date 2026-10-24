"""统一时间基准（UTC）。

平台存储约定
------------
所有 ``DateTime`` 列存 **naive UTC**：

* 服务端默认值 ``func.now()`` 在 SQLite / Postgres 上都是 UTC；
* SQLite 读回时会丢掉 ``tzinfo``，naive-UTC 是两种引擎唯一一致的表示；
* 前端 ``lib/datetime.ts`` 按同一约定解析：**不带偏移的 ISO 串即 UTC**。

因此业务代码写库必须使用 :func:`utcnow_naive`（或直接写 naive UTC），
**不要**使用 ``datetime.now()``（本地墙钟）或 ``datetime.now().astimezone()``
（带本地偏移，SQLite 落库时偏移被丢弃 → 整体偏移一个 UTC 时差，历史缺陷）。
"""

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """当前 UTC 时刻（naive）。写库 / 与库中既有时间比较时使用。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """当前 UTC 时刻（aware）。用于需要显式瞬时语义的场景（签名、租约）。"""
    return datetime.now(timezone.utc)
