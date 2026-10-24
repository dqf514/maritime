#!/bin/sh
# MariOS —— 定时备份循环（backup 服务入口）
#
# 每次循环：先立刻备份一次（避免重启后当天没有快照），之后按
# BACKUP_INTERVAL_SECONDS 间隔重复。任何一次失败都不会让容器退出，
# 失败会写日志并在下一轮重试。
set -eu

: "${BACKUP_DIR:=/backups}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"

echo "[backup-loop] 启动，间隔 ${INTERVAL}s，目录 ${BACKUP_DIR}"

while true; do
    if sh /scripts/backup.sh; then
        echo "[backup-loop] 本轮完成"
    else
        echo "[backup-loop] 本轮失败（下一轮重试）" >&2
    fi
    sleep "$INTERVAL"
done
