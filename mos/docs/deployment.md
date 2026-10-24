# 部署指南（Docker Compose）

面向实施与运维人员的 MariOS 单机 / 预发 / 生产部署说明。
客户可见语气；内部研发细节见 [DEVELOPMENT.md](../DEVELOPMENT.md)。

## 1. 前置条件

| 项 | 要求 |
|---|---|
| Docker / Compose | Docker 24+，`docker compose version` ≥ v2.24 |
| 端口 | `8000`（API）、`3000`（Web）—— 默认只监听 `127.0.0.1`，外部访问走反向代理 |
| 磁盘 | ≥ 20 GB（含镜像、数据库卷、备份卷） |
| 反向代理 | 生产建议 nginx / Traefik 终结 HTTPS，并把 API 的 `/readyz` 作为探针 |

## 2. 准备配置

```bash
cd deploy/compose
cp .env.example .env
```

`.env` 里**必须**填这几项（留空时 `docker compose` 会直接报错退出，不会用弱默认值兜底）：

| 变量 | 生成方式 | 说明 |
|---|---|---|
| `POSTGRES_PASSWORD` | `openssl rand -base64 24` | 数据库口令 |
| `JWT_SECRET` | `openssl rand -hex 32` | 令牌签名密钥（**重启后必须不变**） |
| `OPS_DATA_KEY` | `openssl rand -hex 32` | 平台侧密文加密密钥（**不要复用 JWT_SECRET**） |
| `NEXT_PUBLIC_API_BASE` | 如 `https://api.example.com` | 前端访问 API 的地址（**构建期内联**） |

另外建议按环境调整：

- `ENV=production`（默认即 production：关闭 `/docs` 与 `/openapi.json`）
- `COOKIE_SECURE=true`（HTTPS 部署必开）
- `LICENSE_DEV_UNLOCK=none`（默认；`=all` 会绕过全部模块许可证门禁，**仅本地开发**）
- `OAUTH_ALLOW_STUB=false`（默认；`=true` 是「任意邮箱免密登录」后门，**仅本地演示**）
- `API_CORS_ORIGINS` / `API_PUBLIC_BASE` / `WEB_PUBLIC_BASE` 改成真实域名
- `TRUSTED_PROXY_IPS` —— 反代网段（默认 `*`）。反代后限流按 `X-Forwarded-For` 分桶，
  不配这一项全站会共用一个限流桶。

> `JWT_SECRET` / `OPS_DATA_KEY` 变了，**已加密的数据（租户数据源连接串、M365 token、
> SMTP 口令、AI key）就永久解不开了**。请单独离线备份这两个值。

## 3. 启动

```bash
docker compose up -d
```

启动顺序：`postgres`（健康）→ `migrate`（`alembic upgrade head`，退出码必须为 0）→
`api`（健康）→ `web`。

- 空库不需要额外操作：`alembic upgrade head` 会按模型建全量表并登记版本。
- 存量库（早期由 `create_all` 建好、尚未登记版本）：先 `docker compose run --rm api alembic stamp head`，
  再 `docker compose run --rm api alembic upgrade head`。
- 查看状态：`docker compose ps`、`docker compose logs -f api`。

## 4. 发布新版本

```bash
git pull
docker compose build            # 重建 API / Web 镜像
docker compose run --rm api alembic upgrade head   # 迁移（务必在建新版本之前）
docker compose up -d
```

`alembic upgrade head` 必须在 API 起来之前跑完 —— 新版本可能用到新列，
旧 schema 会直接 500。

## 5. 反向代理

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
}
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

- 必须透传 `X-Forwarded-For`（否则限流与审计日志记到的都是反代 IP）；
- 反代网段填进 `TRUSTED_PROXY_IPS`；
- 前端是**浏览器直连 API**（`NEXT_PUBLIC_API_BASE` 决定），没有服务端代理，
  该地址必须是浏览器可达的公网地址；改完要 `docker compose build web` 重建。

## 6. 健康检查

| 端点 | 含义 |
|---|---|
| `GET /healthz` | 进程存活 |
| `GET /readyz` | 就绪（会探数据库）—— **编排与反代都用这个** |

## 7. 备份与恢复

- 数据库：`backup` 服务按 `BACKUP_INTERVAL_SECONDS` 定时 `pg_dump`（自定义格式，已压缩），
  每个快照带 `.sha256`，并按 `BACKUP_RETENTION_DAYS` 清理旧快照。
- 业务数据：平台运维台的「租户备份」导出 JSON（带校验和，有密钥时加密）。
- 恢复步骤与演练记录见 [`deploy/compose/backup/README.md`](../deploy/compose/backup/README.md)。

## 8. 常见问题

| 现象 | 原因与处理 |
|---|---|
| compose 启动即报 `required variable JWT_SECRET is missing a value` | `.env` 没填必填项 |
| API 起来后报 `column ... does not exist` | 忘了跑 `alembic upgrade head` |
| 所有用户共用一个限流桶 | 反代没透传 `X-Forwarded-For`，或 `TRUSTED_PROXY_IPS` 没配 |
| 前端请求打到 `localhost:8000` | `NEXT_PUBLIC_API_BASE` 没改或改完没重建 web 镜像 |
| 重启后 M365 / SMTP / 租户数据源连不上 | `OPS_DATA_KEY` 变了（换了密钥等于数据作废） |
| 备份/上传文件消失 | 没挂持久卷（`mos_api_data` / `mos_api_uploads`） |

## 9. 安全清单（上线前逐项确认）

- [ ] `ENV=production`，`/docs` 与 `/openapi.json` 已关闭
- [ ] `LICENSE_DEV_UNLOCK=none`、`OAUTH_ALLOW_STUB=false`、`SEED_DEMO=false`
- [ ] `JWT_SECRET` / `OPS_DATA_KEY` 已设置且**离线备份**
- [ ] `COOKIE_SECURE=true`（HTTPS）
- [ ] Postgres 端口只监听 `127.0.0.1`，口令已改强
- [ ] 反代透传 `X-Forwarded-For`，`TRUSTED_PROXY_IPS` 已收紧
- [ ] 数据库备份已跑通，且**做过一次恢复演练**
- [ ] `docker compose run --rm api alembic current` 显示 head
