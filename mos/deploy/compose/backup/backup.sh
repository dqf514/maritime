#!/bin/sh
# MariOS —— Postgres 逻辑备份（一次快照）
#
# 产物：<BACKUP_DIR>/marios-<db>-<UTC 时间戳>.dump        （pg_dump -Fc 自带压缩）
#       <BACKUP_DIR>/marios-<db>-<UTC 时间戳>.dump.sha256  （校验和）
#
# 关键点：
# - 先写 .tmp 再 rename —— 备份目录里不会出现「写了一半」的快照；
# - .sha256 与 .dump 一一对应，恢复时强制校验；
# - 备份内容是数据库，不含明文密钥（密钥在 OPS_DATA_KEY / JWT_SECRET 里，
#   必须另外单独备份，见 backup/README.md）。
set -eu

: "${PGHOST:=postgres}"
: "${PGUSER:?PGUSER 必须设置}"
: "${PGPASSWORD:?PGPASSWORD 必须设置}"
: "${PGDATABASE:?PGDATABASE 必须设置}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BASE="marios-${PGDATABASE}-${TS}"
TMP="${BACKUP_DIR}/.${BASE}.dump.tmp"
FINAL="${BACKUP_DIR}/${BASE}.dump"

echo "[backup] 开始备份 ${PGDATABASE} @ ${PGHOST} → ${BASE}.dump"
pg_dump \
    --host "$PGHOST" \
    --username "$PGUSER" \
    --dbname "$PGDATABASE" \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
    --file "$TMP"

# 校验和只存哈希值（不带文件名），便于跨目录核对
sha256sum "$TMP" | cut -d' ' -f1 > "${TMP}.sha256"

# 可读性检查：pg_dump 自定义格式能被 pg_restore 解析才算有效快照
pg_restore --list "$TMP" > /dev/null

# 原子发布：先落校验和，再落快照 —— 目录里不会存在「有快照没校验和」的组合
mv "${TMP}.sha256" "${FINAL}.sha256"
mv "$TMP" "$FINAL"

SIZE="$(du -h "$FINAL" | cut -f1)"
echo "[backup] 完成：${FINAL}（${SIZE}）"

# 保留策略：超过保留期的快照与其校验和一起删除
if [ "$RETENTION_DAYS" -gt 0 ]; then
    echo "[backup] 清理超过 ${RETENTION_DAYS} 天的旧快照"
    find "$BACKUP_DIR" -maxdepth 1 -type f -name "marios-${PGDATABASE}-*.dump" \
        -mtime "+${RETENTION_DAYS}" -print -delete || true
    find "$BACKUP_DIR" -maxdepth 1 -type f -name "marios-${PGDATABASE}-*.dump.sha256" \
        -mtime "+${RETENTION_DAYS}" -print -delete || true
    find "$BACKUP_DIR" -maxdepth 1 -type f -name ".marios-${PGDATABASE}-*.tmp*" -mtime "+1" -delete || true
fi
