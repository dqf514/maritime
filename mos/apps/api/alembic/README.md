# Alembic 数据库迁移（P3 起）

VoyageOS 从 P3 开始使用 Alembic 管理 schema 变更。本目录为标准 Alembic 布局：

- `env.py` — 从 `app.config.get_settings().database_url`（即 `DATABASE_URL` 环境变量）读取连接，
  `target_metadata` 为 `app.db.Base.metadata`（导入全部模型模块后）。
- `versions/54d9ef473ec3_baseline_schema.py` — 基线迁移（autogenerate 生成，108 张表，含 `audit_logs`）。

## 过渡策略（重要）

- **存量库**（已有的 dev SQLite 文件 / 已部署实例）：表已由 `create_all` + `app/main.py` 里的手写
  ALTER 补丁建好。**不要**直接 `alembic upgrade head`，先执行一次：
  ```bash
  ./.venv/Scripts/python.exe -m alembic stamp head
  ```
- **新库**：应用启动仍会执行 `Base.metadata.create_all()`（过渡期保留），首次启动后同样
  `alembic stamp head` 即可；空库直接 `alembic upgrade head` 也能得到完整 schema，二者等价。
- **今后的 schema 变更**：一律新增 Alembic revision（`alembic revision --autogenerate -m "..."`），
  不要再往 `app/main.py` 的 ALTER 补丁列表里加列。老补丁仅为兼容未 stamp 的旧 dev 库而保留。

## 常用命令（在 `mos/apps/api` 下执行）

```bash
# 查看当前版本 / 最新版本
./.venv/Scripts/python.exe -m alembic current
./.venv/Scripts/python.exe -m alembic heads

# 生成新迁移（先确保 DATABASE_URL 指向一个已是最新 schema 的库）
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add xxx column"

# 升级 / 回退
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m alembic downgrade -1

# 存量库登记基线（只写 alembic_version，不改表）
./.venv/Scripts/python.exe -m alembic stamp head
```

SQLite 说明：`env.py` 在 SQLite 下启用 `render_as_batch`（表重建模式），以绕过
SQLite 不支持 `ALTER COLUMN` 的限制。日志由应用侧 `app/services/observability.py` 统一配置，
`env.py` 刻意不调用 `fileConfig`。

测试导入：直接 `import` 本目录的 `env.py` 不会连接数据库（`alembic.context` 只有在 Alembic
执行该文件时才暴露 `config`，`env.py` 据此跳过迁移执行，只完成模型注册）。
