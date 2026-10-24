# MariOS —— 数据库备份与恢复

本目录是 `deploy/compose/docker-compose.yml` 里 `backup` 服务的脚本目录（只读挂载到容器 `/scripts`）。

## 组成

| 文件 | 作用 |
|---|---|
| `backup.sh` | 一次 Postgres 逻辑快照：`pg_dump -Fc` → 写 `.tmp` → `sha256` → **原子 rename** → `pg_restore --list` 自检 → 按保留天数清理旧快照 |
| `backup-loop.sh` | `backup` 服务的常驻入口：启动即备份一次，之后按 `BACKUP_INTERVAL_SECONDS` 循环 |
| `restore.sh` | 恢复：强制校验 sha256 → 校验快照可解析 → `RESTORE_CONFIRM=yes` 才写库 → 单事务 `--clean --if-exists` 恢复 → 打印前后行数 |

## 备份产物

```
/backups/marios-voyageos-20260101T000000Z.dump        # pg_dump 自定义格式（已压缩）
/backups/marios-voyageos-20260101T000000Z.dump.sha256  # 校验和（只有哈希值）
```

- 快照落在 named volume `mos_backups`，容器重建不丢；**但它和数据库在同一个宿主机上**，
  生产环境必须再同步一份到异地（对象存储 / 另一台机器 rsync）。
- 保留策略由 `BACKUP_RETENTION_DAYS` 控制（默认 14 天），`backup.sh` 每轮自动清理。

## 密钥不在备份里（重要）

数据库快照**不包含**加密密钥。丢了下面任何一个，已加密的数据都永久不可解：

| 变量 | 保护的东西 |
|---|---|
| `OPS_DATA_KEY` | 租户数据源连接串、AI provider key、平台侧密文 |
| `JWT_SECRET` | 登录令牌签名（OPS_DATA_KEY 未配时还会被用作加密回退密钥） |

这两个值必须**单独**备份（密码管理器 / 离线加密介质），不要只依赖数据库备份。

## 恢复流程（演练步骤）

```bash
# 1. 停应用（避免恢复期间写库）
docker compose stop api web

# 2. 看看有哪些快照
docker compose run --rm backup ls -l /backups

# 3. 校验 + 恢复（不带 RESTORE_CONFIRM 只会做校验，不会写库）
docker compose run --rm backup /scripts/restore.sh /backups/marios-voyageos-20260101T000000Z.dump

# 4. 真正恢复
docker compose run --rm -e RESTORE_CONFIRM=yes backup \
    /scripts/restore.sh /backups/marios-voyageos-20260101T000000Z.dump

# 5. 起应用并抽查
docker compose start api web
```

### 验收（每次上线前至少演练一次）

- 从 `pg_dump` 恢复到空库 → 起 API → 抽查 3 张业务表（`estimates` / `charters` / `invoices`）行数一致；
- 篡改备份文件 1 字节 → `restore.sh` 必须以退出码 3 拒绝恢复；
- 记录恢复耗时与快照体积（填到下表）。

| 演练日期 | 快照 | 恢复耗时 | 抽查结果 | 备注 |
|---|---|---|---|---|
| | | | | |

## 租户级应用备份（JSON）

应用内还有一层「按租户 dump 成 JSON」的备份（平台管理后台 → 租户备份），
落在 API 容器的 `mos_api_data` 卷里。它是**业务视角**的备份（只含带 `tenant_id` 的表），
和上面的数据库快照互补：

- 数据库快照 = 灾备（整库可恢复）；
- 租户 JSON = 跨租户搬迁 / 单租户恢复。

租户 JSON 备份文件带 `.sha256` 校验和，恢复时会强制校验；备份内容**不含**明文密钥。
