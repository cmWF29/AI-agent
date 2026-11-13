#!/usr/bin/env bash
# 在 VPS 上执行：安装/更新 systemd 单元与配置，然后重启服务。
# 可重复执行（幂等）。
set -euo pipefail

REPO="/opt/hive/current"
AUTOSTART=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --autostart) AUTOSTART=1; shift ;;
    *) shift ;;
  esac
done

SECRETS="/opt/hive/secrets.env"
if [ -f "$SECRETS" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$SECRETS"
  set +a
fi

mkdir -p "$REPO/data" "$REPO/data/logs" "$REPO/data/control"

if [ ! -f "$REPO/config/config.json" ]; then
  cp "$REPO/config/config.example.json" "$REPO/config/config.json"
  echo "[provision] 已生成 config/config.json"
fi

# 把 secrets.env 里的密钥/密码写进配置（只在尚未设置时写，避免覆盖手工修改）
python3 - "$REPO/config/config.json" <<'PY'
import json, os, sys
p = sys.argv[1]
with open(p, "r", encoding="utf-8") as f:
    cfg = json.load(f)
key = os.environ.get("HIVE_LLM_API_KEY") or ""
cur = (cfg.get("llm") or {}).get("api_key") or ""
if key and (not cur or cur.startswith("PUT_YOUR")):
    cfg["llm"]["api_key"] = key
    print("[provision] 已写入 DeepSeek API Key")
pw = os.environ.get("HIVE_WEB_PASSWORD") or ""
if pw:
    cfg.setdefault("server", {})["web_password"] = pw
tok = os.environ.get("HIVE_TOKEN") or ""
if tok:
    cfg.setdefault("server", {})["token"] = tok
with open(p, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
PY

PYTHON_BIN="$(command -v python3)"
sed -e "s|__REPO__|$REPO|g" -e "s|__PYTHON__|$PYTHON_BIN|g" \
    "$REPO/deploy/hive-watchdog.service" > /etc/systemd/system/hive-watchdog.service

systemctl daemon-reload
systemctl enable hive-watchdog >/dev/null 2>&1 || true

if [ "$AUTOSTART" = "1" ]; then
  systemctl restart hive-watchdog || systemctl start hive-watchdog
  sleep 2
  systemctl --no-pager --lines=5 status hive-watchdog || true
fi

PORT="$(python3 -c "import json;print(json.load(open('$REPO/config/config.json'))['server']['port'])")"
echo "[provision] 完成：http://<VPS_IP>:$PORT/   （密码见 config/config.json 的 server.web_password）"
