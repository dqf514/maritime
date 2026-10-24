# deploy/compose —— 编排说明

MariOS 的单机 / 预发 / 生产编排（Docker Compose v2）。

> 面向客户的完整部署说明见 [`docs/deployment.md`](../../docs/deployment.md)；
> 本文是**实现视角**的补充（服务构成、卷、迁移、备份脚本）。

## 服务构成

| 服务 | 作用 | 关键配置 |
|---|---|---|
| `postgres` | 主库（PostgreSQL 16） | 卷 `voyageos_pg`；端口只监听 `127.0.0.1:5432` |
| `migrate` | **一次性**：把 schema 升到 head | `command: alembic upgrade head`；`restart: "no"` |
| `api` | FastAPI | 依赖 `migrate` 成功退出；健康检查打 `/readyz` |
| `web` | Next.js 前端 | 构建参数 `NEXT_PUBLIC_API_BASE`（构建期内联） |
| `backup` | `pg_dump` 定时快照 | 脚本见 `backup/`；卷 `mos_backups` |

启动依赖链：`postgres(healthy)` → `migrate(completed_successfully)` → `api(healthy)` → `web`。

> **编排里没有 Redis / MinIO。** 早期版本带过这两个容器，但系统**一行代码都没用到**
> （限流是进程内滑动窗口，文件落本地持久卷），属于"死服务"，还会让 API 因为
> 一个没人用的容器不健康而起不来。将来要接分布式限流 / 对象存储再按需加回。

## 持久卷

| 卷 | 挂载点 | 装什么 |
|---|---|---|
| `voyageos_pg` | `/var/lib/postgresql/data` | 数据库 |
| `mos_backups` | `/backups` | `pg_dump` 快照 |
| `mos_api_data` | `/srv/mos/apps/api/app/data` | 租户备份（JSON）与运行期数据 |
| `mos_api_uploads` | `/srv/mos/apps/api/uploads` | 证书、Logo、已渲染 PDF |
| `mos_api_keys` | `/srv/mos/keys` | 预留：本地密钥材料 |

> 早期版本没有 `mos_api_*` 三个卷 —— 备份与上传落在容器可写层，
> `docker compose down && up` 就会丢。**升级到当前编排后请确认这三个卷已创建。**

## 必填变量（compose 用 `${VAR:?}` 强校验，缺值直接报错）

`POSTGRES_PASSWORD`、`JWT_SECRET`、`OPS_DATA_KEY`、`NEXT_PUBLIC_API_BASE`。

`JWT_SECRET` / `OPS_DATA_KEY` 尤其重要：留空时应用会退化成「每进程随机密钥」，
重启后令牌失效、已加密数据（M365 token / SMTP 口令 / 租户数据源连接串）永久不可解。
compose 层直接拒绝启动，就是为了让这件事在部署时就暴露。

## 迁移

```bash
# 一次性迁移服务（正常由 compose 自动跑）
docker compose run --rm api alembic upgrade head

# 看当前版本 / 漂移检查
docker compose run --rm api alembic current
docker compose run --rm api alembic check
```

- 空库：`alembic upgrade head` 会按模型建全量表并登记 head（`alembic/env.py` 的空库自举）。
- 存量库（早期 `create_all` 建好、没登记版本）：先 `alembic stamp head` 再 `upgrade head`。
- 详见 [`apps/api/alembic/README.md`](../../apps/api/alembic/README.md)。

**发布顺序**：先 `alembic upgrade head`，再起新版本 API。新版本可能用到新列，
schema 没跟上会直接 500。

## 备份

`backup/` 目录下的三个脚本：

- `backup.sh` —— 一次快照（`pg_dump -Fc` → 临时文件 → sha256 → 原子 rename → 自检 → 清理旧快照）
- `backup-loop.sh` —— 常驻循环（`backup` 服务入口）
- `restore.sh` —— 恢复（强制校验 sha256 → `RESTORE_CONFIRM=yes` 才写库 → 单事务恢复 → 打印前后行数）

详见 [`backup/README.md`](./backup/README.md)。

## 反向代理与限流

前端是**浏览器直连 API**（`NEXT_PUBLIC_API_BASE`），没有服务端代理。

反代必须透传 `X-Forwarded-For`，并把反代网段写进 `TRUSTED_PROXY_IPS`
（默认 `*`，生产建议收紧成具体网段）。不配的话 `request.client.host` 恒为反代 IP，
限流会退化成「全站共用一个桶」。

## 常用命令

```bash
docker compose config -q          # 校验编排（缺必填变量会在这里报错）
docker compose ps
docker compose logs -f api
docker compose up -d --build      # 重新构建并启动
docker compose run --rm api alembic upgrade head
docker compose run --rm backup /scripts/restore.sh /backups/<快照>.dump
```
