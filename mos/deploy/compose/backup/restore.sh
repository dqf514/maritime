#!/bin/sh
# MariOS —— 从 pg_dump 快照恢复
#
# 用法（在 backup 容器里）：
#   docker compose run --rm backup /scripts/restore.sh /backups/marios-voyageos-20260101T000000Z.dump
#
# 安全约束：
# - 强制校验 .sha256，缺失或不匹配一律拒绝恢复；
# - 先用 pg_restore --list 验证快照可解析；
# - 需要 RESTORE_CONFIRM=yes 才会真正写库（--clean 会先删对象）；
# - 恢复在单个事务里完成，失败即回滚。
set -eu

: "${PGHOST:=postgres}"
: "${PGUSER:?PGUSER 必须设置}"
: "${PGPASSWORD:?PGPASSWORD 必须设置}"
: "${PGDATABASE:?PGDATABASE 必须设置}"

BACKUP="${1:-}"
if [ -z "$BACKUP" ]; then
    echo "用法: restore.sh <备份文件.dump>" >&2
    exit 2
fi
if [ ! -f "$BACKUP" ]; then
    echo "备份文件不存在: $BACKUP" >&2
    exit 2
fi

# ── 1. 校验和 ──────────────────────────────────────────────────────────
SUM_FILE="${BACKUP}.sha256"
if [ ! -f "$SUM_FILE" ]; then
    echo "缺少校验文件 $SUM_FILE —— 拒绝恢复（备份可能被篡改或截断）" >&2
    exit 3
fi
EXPECTED="$(cat "$SUM_FILE")"
ACTUAL="$(sha256sum "$BACKUP" | cut -d' ' -f1)"
if [ "$EXPECTED" != "$ACTUAL" ]; then
    echo "校验和不匹配 —— 拒绝恢复" >&2
    echo "  期望: $EXPECTED" >&2
    echo "  实际: $ACTUAL" >&2
    exit 3
fi
echo "[restore] 校验通过: $BACKUP"

# ── 2. 快照可解析性 ────────────────────────────────────────────────────
if ! pg_restore --list "$BACKUP" > /dev/null; then
    echo "快照无法解析 —— 拒绝恢复" >&2
    exit 4
fi

# ── 3. 确认 ────────────────────────────────────────────────────────────
if [ "${RESTORE_CONFIRM:-}" != "yes" ]; then
    echo "这是破坏性操作（会 --clean 目标库现有对象）。" >&2
    echo "确认无误后重跑，并带上 RESTORE_CONFIRM=yes。" >&2
    echo "即将恢复：$BACKUP → ${PGUSER}@${PGHOST}/${PGDATABASE}" >&2
    exit 5
fi

echo "[restore] 恢复前各表行数："
psql --host "$PGHOST" --username "$PGUSER" --dbname "$PGDATABASE" --tuples-only --no-align \
    --command "SELECT relname || '=' || n_live_tup FROM pg_stat_user_tables ORDER BY relname;" || true

echo "[restore] 开始恢复……"
pg_restore \
    --host "$PGHOST" \
    --username "$PGUSER" \
    --dbname "$PGDATABASE" \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    --single-transaction \
    "$BACKUP"

echo "[restore] 恢复后各表行数："
psql --host "$PGHOST" --username "$PGUSER" --dbname "$PGDATABASE" --tuples-only --no-align \
    --command "SELECT relname || '=' || n_live_tup FROM pg_stat_user_tables ORDER BY relname;" || true

echo "[restore] 完成。请再抽查 3 张业务表（estimates / charters / invoices）的行数与内容。"
