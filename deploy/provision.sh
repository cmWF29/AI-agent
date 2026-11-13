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
# 老配置文件没有 tls 段时补上（内核默认开启，但文件里的 server 段会整段覆盖默认值）
srv = cfg.setdefault("server", {})
srv.setdefault("tls", {"enabled": True, "cert": "config/tls/server.crt", "key": "config/tls/server.key"})
with open(p, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
PY

# HTTPS 证书自举（需求 5）：只有 IP 没有域名，只能自签；手机浏览器首次会告警，信任一次即可
TLS_DIR="$REPO/config/tls"
# 注意：老配置里可能没有 tls 段，而内核默认是开的 —— 缺省按“开”处理
TLS_ON="$(python3 -c "import json;c=json.load(open('$REPO/config/config.json'));(print('1') if ((c.get('server',{}).get('tls') or {}).get('enabled', True)) else print('0'))")"
if [ "$TLS_ON" = "1" ] && [ ! -f "$TLS_DIR/server.crt" ]; then
  mkdir -p "$TLS_DIR"
  IP="${HIVE_PUBLIC_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
  [ -z "$IP" ] && IP="127.0.0.1"
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -subj "/CN=$IP/O=Hive Agent" \
    -addext "subjectAltName=IP:$IP" \
    -keyout "$TLS_DIR/server.key" -out "$TLS_DIR/server.crt" >/dev/null 2>&1
  chmod 600 "$TLS_DIR/server.key"
  chmod 644 "$TLS_DIR/server.crt"
  echo "[provision] 已生成自签证书（IP=$IP）"
fi

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
SCHEME="http"
[ "$TLS_ON" = "1" ] && [ -f "$TLS_DIR/server.crt" ] && SCHEME="https"
echo "[provision] 完成：$SCHEME://<VPS_IP>:$PORT/   （密码见 config/config.json 的 server.web_password）"
[ "$SCHEME" = "https" ] && echo "[provision] 自签证书：首次访问需在浏览器点“继续访问”（安卓 Chrome：高级 → 继续前往）"
