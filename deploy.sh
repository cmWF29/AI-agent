#!/usr/bin/env bash
# VPS 一键部署：拉齐 GitHub → 装/刷新 systemd 单元 → 重启 → 探活。
# 开发阶段口径：reset --hard 到 origin/master；线上 data 不受影响的部分随仓库走。
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/ai_new}"
UNIT="/etc/systemd/system/hive-ai.service"
BASE="https://127.0.0.1:8788"

cd "$APP_DIR"
git fetch -q origin master
git reset --hard -q origin/master
echo "HEAD=$(git rev-parse --short HEAD)"

install -m 0644 deploy/hive-ai.service "$UNIT"
systemctl daemon-reload
systemctl enable -q hive-ai
systemctl restart hive-ai

for _ in $(seq 1 30); do
  if curl -skf -m 3 "$BASE/api/health/live" >/dev/null; then
    echo "health OK: $(curl -sk -m 3 "$BASE/api/health/live")"
    exit 0
  fi
  sleep 2
done
echo "探活失败，看 systemctl status hive-ai -l 与 $APP_DIR/run.log" >&2
exit 1
