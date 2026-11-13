#!/usr/bin/env bash
# 本地整机联调（不用真 Key、不花钱）：假 LLM + 真 watchdog + 真 agent + CLI/网页链路。
#   bash deploy/local_demo.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${TMPDIR:-/tmp}/hive-demo"
PORT="${HIVE_DEMO_PORT:-18787}"
MOCK_PORT="${HIVE_MOCK_PORT:-9911}"
TOKEN="demo-token"

rm -rf "$RUN"; mkdir -p "$RUN"
cp -r "$REPO/hive" "$REPO/web" "$REPO/deploy" "$REPO/config" "$REPO/tests" "$RUN/"
cp "$REPO/.gitignore" "$REPO/VERSION" "$RUN/"
cat > "$RUN/config/config.json" <<JSON
{
  "server": {"host": "127.0.0.1", "port": $PORT, "token": "$TOKEN", "web_password": "demo"},
  "llm": {"base_url": "http://127.0.0.1:$MOCK_PORT", "api_key": "demo", "model": "mock-deepseek",
          "timeout": 30, "max_retries": 1},
  "tool_output": {"inline_max_chars": 200},
  "observability": {"level": "debug"}
}
JSON
( cd "$RUN" && git init -q && git add -A && git -c user.email=a@b -c user.name=demo commit -qm "demo v1" )

python3 "$REPO/tests/mock_server.py" "$MOCK_PORT" > "$RUN/mock.log" 2>&1 &
MOCK_PID=$!
python3 "$RUN/deploy/watchdog.py" --repo "$RUN" --config "$RUN/config/config.json" --interval 3 \
    > "$RUN/watchdog.log" 2>&1 &
WD_PID=$!
trap 'kill $WD_PID $MOCK_PID 2>/dev/null || true' EXIT

echo "等 agent 起来 ..."; sleep 6
echo "--- health ---";  curl -s "http://127.0.0.1:$PORT/api/health"; echo
echo "--- CLI ask ---";  PYTHONPATH="$REPO" python3 -m hive.cli ask --text "本地联调" \
                          --url "http://127.0.0.1:$PORT" --token "$TOKEN" --json
echo "--- 网页链路（内部真的跑 CLI）---"
JOB=$(curl -s -X POST "http://127.0.0.1:$PORT/api/chat/send" -H "X-Auth-Token: $TOKEN" \
        -H "Content-Type: application/json" -d '{"text":"网页来的消息"}' \
        | python3 -c "import sys,json;print(json.load(sys.stdin)['job_id'])")
for _ in $(seq 1 30); do
  sleep 1
  S=$(curl -s "http://127.0.0.1:$PORT/api/chat/job/$JOB" -H "X-Auth-Token: $TOKEN" \
        | python3 -c "import sys,json;d=json.load(sys.stdin)['job'];print(d['status'],'|',d.get('reply','') or d.get('error',''))")
  case "$S" in done*|error*) break;; esac
done
echo "$S"
echo "--- 数据落在：$RUN （日志 $RUN/data/logs）---"
echo "按 Ctrl-C 结束（自动杀掉 demo 进程）"
wait $WD_PID
