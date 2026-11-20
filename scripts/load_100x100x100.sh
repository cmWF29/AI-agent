#!/usr/bin/env bash
# 大规模压测：100 项目 × 每项目 100 工单 × 每工单 ≥100 轮对话。
#
# 轮次口径：一轮 = 一次 assistant 步（含 system 注入 + LLM 请求 + 可能的工具执行）。
# 分片：每片只跑 index % 片数 == 片号-1 的项目，data-root 持久，中断可直接续跑。
# 打桩：全程本地桩服务，不接真实上游；trace 采样降到 0.02，避免 1M 轮把日志打爆。
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA=${DATA:-$ROOT/var/load-100x100x100}
SHARDS=${SHARDS:-10}
WORKERS=${WORKERS:-8}
ROUNDS=${ROUNDS:-100}
JOIN=${JOIN:-900}
TRACE_SAMPLE=${TRACE_SAMPLE:-0.02}

mkdir -p "$DATA"
echo "数据目录: $DATA | 分片 $SHARDS | 并发 $WORKERS | 目标 $ROUNDS 轮/工单"

for i in $(seq 1 "$SHARDS"); do
  echo "== 分片 $i/$SHARDS  $(date '+%F %T')"
  PYTHONPATH="$ROOT:$ROOT/ai_new/modules/agent_test/private" \
    python3 "$ROOT/ai_new/modules/agent_test/private/load_test.py" \
      --projects 100 --tickets 100 --workers "$WORKERS" --rounds "$ROUNDS" \
      --shard "$i/$SHARDS" --data-root "$DATA" --pm-roles developer \
      --filler-words 120 --delay 0 --join-timeout "$JOIN" \
      --trace-sample "$TRACE_SAMPLE"
done

echo "== 全部分片完成 $(date '+%F %T')"
