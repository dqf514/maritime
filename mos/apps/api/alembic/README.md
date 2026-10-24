# Alembic 数据库迁移

MariOS 用 Alembic 管理 schema 变更。本目录为标准 Alembic 布局：

- `env.py` — 从 `app.config.get_settings().database_url`（即 `DATABASE_URL` 环境变量）读取连接，
  `target_metadata` 为 `app.db.Base.metadata`（导入全部模型模块后）。
- `versions/` — 迁移链（单一 head，线性）。
- `versions/54d9ef473ec3_baseline_schema.py` — 历史基线（2024 年那轮 autogenerate 产物）。

## ⚠️ 关于「空库 upgrade head」的重要说明（不要再照旧文档操作）

**旧文档的说法是错的**：历史上这条链是在「表由 `Base.metadata.create_all()` 建好」的
前提下增量写出来的 —— 链里有 **90+ 张表只被 `ALTER`、从未 `CREATE`**（迁移链落后于模型）。
所以**直接**在空库上跑 `alembic upgrade head` 必然报 `no such table: …`。

现在的做法（`alembic/env.py` 里的**空库自举**）：

| 场景 | 命令 | 结果 |
|------|------|------|
| **全新空库** | `alembic upgrade head` | env.py 检测到空库 → 按 `Base.metadata` 建全量表 → 把 `alembic_version` 登记到 head → 迁移链无事可做，**退出码 0**；结果与应用自身 `create_all` 完全一致 |
| **存量库**（已由 `create_all` 建好、尚未 stamp） | `alembic stamp head` → `alembic upgrade head` | `stamp` 只写版本号（不改表），之后 `upgrade` 把后续新增的 revision 增量执行 |
| **已在 head 的库** | `alembic upgrade head` | 无操作，退出码 0 |

自举只对「**完全空库 + `alembic upgrade head`**」生效；`stamp` / `downgrade` / `check`
不会建表。设 `ALEMBIC_BOOTSTRAP_EMPTY_DB=0` 可完全关闭自举（仅排障用）。

> 迁移链与 `create_all` 的结果**不再**等价 —— 现在是「以模型为准」：
> 空库自举出来的 schema 就是模型定义的 schema，`alembic check` 无 diff。

## 迁移约定（新增 revision 前必读）

本仓库 schema 的真源是 **`Base.metadata`（模型）**：应用启动时 `create_all` 会补建缺失的表，
但**从不 ALTER 已有表**。因此：

1. **模型改了列 → 必须同时加一条 revision**，否则存量库永远拿不到这一列。
   （这正是历史上迁移链与模型漂移的根因。）
2. **revision 必须幂等**：写之前先看库里有没有（列 / 索引 / 约束）。
   `create_all` 可能已经把列建出来了，直接 `op.add_column` 会报「duplicate column」。
   本目录现有 revision 统一采用「**ORM 没声明 → 跳过；库里有 → 跳过；否则补齐**」的写法。
3. **约束跟着 ORM 走**：唯一约束/部分唯一索引的列与 `WHERE` 条件都从
   `Base.metadata` 读，不在迁移里硬编码（避免与 ORM 侧漂移）。
4. **SQLite 注意**：SQLite 不支持 `ALTER TABLE … ADD CONSTRAINT`，改约束要走
   `op.batch_alter_table`（重建表）。

新增 revision：

```bash
cd apps/api
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add xxx column"
```

`--autogenerate` 需要**一个已经是最新 schema 的库**（本地 SQLite 开发库即可）。

## 常用命令（在 `mos/apps/api` 下执行）

```bash
# 查看当前版本 / 最新版本 / 迁移历史
./.venv/Scripts/python.exe -m alembic current
./.venv/Scripts/python.exe -m alembic heads
./.venv/Scripts/python.exe -m alembic history

# 空库升级（自举建表 + 登记 head）
./.venv/Scripts/python.exe -m alembic upgrade head

# 存量库登记基线（只写 alembic_version，不改表）
./.venv/Scripts/python.exe -m alembic stamp head

# 回退一版
./.venv/Scripts/python.exe -m alembic downgrade -1

# 漂移检查：库结构必须与模型一致（CI 里是硬门禁）
./.venv/Scripts/python.exe -m alembic check
```

## 与应用启动的关系

- 应用启动时的 `Base.metadata.create_all()` **保留**（过渡期兜底：只建缺失的表）。
  - Postgres 上若检测到 `tenants` / `invoices` 已存在，说明 `migrate` 服务已建好
    schema，**直接跳过 create_all**（迁移是 schema 的唯一真源；顺带避免多副本
    同时启动时并发 CREATE TABLE 报 DuplicateTableError）。
  - SQLite（本地开发）仍然照常 create_all。
- 真正的 schema 变更**一律走 Alembic**：容器里 `migrate` 服务跑 `alembic upgrade head`，
  `api` 服务通过 `depends_on: migrate (service_completed_successfully)` 等它成功退出。
- `app/main.py` 里那些「guarded ALTER 补丁」只为兼容未 stamp 的老 dev SQLite 库而保留，
  **不要**再往里加新列。

SQLite 说明：`env.py` 在 SQLite 下启用 `render_as_batch`（表重建模式），以绕过
SQLite 不支持 `ALTER COLUMN` 的限制。日志由应用侧 `app/services/observability.py` 统一配置，
`env.py` 刻意不调用 `fileConfig`。

测试导入：直接 `import` 本目录的 `env.py` 不会连接数据库（`alembic.context` 只有在 Alembic
执行该文件时才暴露 `config`，`env.py` 据此跳过迁移执行，只完成模型注册）。
