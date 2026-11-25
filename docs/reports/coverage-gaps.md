# 覆盖率缺口清单

基线：行 95.19%（14179/14771），分支 92.92%（4819/5186），共 64 个产品文件有缺口。

| 模块 | 文件 | 缺行 | 缺分支 | 行覆盖 |
|---|---|---:|---:|---:|
| agent/sessions | ai_new/modules/agent/sessions/__init__.py | 37 | 29 | 76.6% |
| agent/projects | ai_new/modules/agent/projects/__init__.py | 39 | 25 | 78.4% |
| agent/cloud | ai_new/modules/agent/cloud/private/_s3.py | 29 | 26 | 90.7% |
| agent_common/llm | ai_new/modules/agent_common/llm/__init__.py | 36 | 17 | 45.9% |
| agent_common/http | ai_new/modules/agent_common/http/private/_server.py | 32 | 15 | 88.6% |
| agent_common/ops | ai_new/modules/agent_common/ops/private/_pure.py | 19 | 12 | 67.0% |
| agent/auth | ai_new/modules/agent/auth/__init__.py | 20 | 8 | 87.3% |
| agent_common/config | ai_new/modules/agent_common/config/private/_loader.py | 16 | 11 | 80.7% |
| agent_common/react | ai_new/modules/agent_common/react/__init__.py | 14 | 13 | 87.2% |
| agent/projects | ai_new/modules/agent/projects/private/_pure.py | 17 | 9 | 84.5% |
| agent/sandbox | ai_new/modules/agent/sandbox/private/_winpath.py | 13 | 12 | 84.7% |
| agent/todos | ai_new/modules/agent/todos/private/_pure.py | 12 | 11 | 86.3% |
| agent/knowledge | ai_new/modules/agent/knowledge/__init__.py | 16 | 6 | 76.1% |
| agent/sessions | ai_new/modules/agent/sessions/private/_run_pure.py | 11 | 11 | 92.5% |
| agent_common/host | ai_new/modules/agent_common/host/private/_probe.py | 19 | 3 | 73.2% |
| agent_common/codec | ai_new/modules/agent_common/codec/private/_codec.py | 19 | 2 | 84.6% |
| agent/channel | ai_new/modules/agent/channel/__init__.py | 11 | 9 | 81.7% |
| agent_common/archive | ai_new/modules/agent_common/archive/private/_backend.py | 12 | 8 | 63.6% |
| agent_common/api | ai_new/modules/agent_common/api/__init__.py | 16 | 3 | 69.4% |
| agent_common/graph | ai_new/modules/agent_common/graph/private/_pure.py | 8 | 10 | 89.4% |
| agent/web | ai_new/modules/agent/web/private/_panel.py | 11 | 6 | 72.6% |
| agent_common/store | ai_new/modules/agent_common/store/private/_idem.py | 11 | 6 | 88.9% |
| agent/logs | ai_new/modules/agent/logs/private/_pure.py | 8 | 8 | 86.4% |
| agent/sandbox | ai_new/modules/agent/sandbox/__init__.py | 13 | 1 | 58.8% |
| agent_common/host | ai_new/modules/agent_common/host/__init__.py | 11 | 3 | 65.9% |
| agent_common/exec | ai_new/modules/agent_common/exec/private/_runner.py | 10 | 3 | 95.3% |
| agent/artifacts | ai_new/modules/agent/artifacts/__init__.py | 6 | 6 | 88.8% |
| agent/channel | ai_new/modules/agent/channel/private/_pure.py | 8 | 4 | 62.5% |
| agent/sandbox | ai_new/modules/agent/sandbox/private/_pure.py | 6 | 6 | 89.8% |
| agent_common/react | ai_new/modules/agent_common/react/private/_pure.py | 3 | 9 | 94.6% |
| agent_common/store | ai_new/modules/agent_common/store/private/_files.py | 5 | 7 | 90.6% |
| agent_common/archive | ai_new/modules/agent_common/archive/private/_index.py | 5 | 6 | 89.7% |
| agent_common/plat | ai_new/modules/agent_common/plat/private/_net.py | 8 | 3 | 88.8% |
| agent/cloud | ai_new/modules/agent/cloud/private/_pure.py | 6 | 4 | 93.8% |
| agent_common/archive | ai_new/modules/agent_common/archive/private/_lock.py | 7 | 3 | 83.1% |
| agent/auth | ai_new/modules/agent/auth/private/_pure.py | 4 | 5 | 95.5% |
| agent/library | ai_new/modules/agent/library/private/_pure.py | 0 | 9 | 99.1% |
| agent_common/archive | ai_new/modules/agent_common/archive/private/_metrics.py | 4 | 5 | 81.2% |
| agent_common/plat | ai_new/modules/agent_common/plat/private/_proc.py | 8 | 1 | 67.9% |
| agent/cloud | ai_new/modules/agent/cloud/private/_seal.py | 5 | 3 | 94.8% |
| agent_common/api | ai_new/modules/agent_common/api/private/_gen.py | 4 | 4 | 92.8% |
| agent/cloud | ai_new/modules/agent/cloud/private/_guard.py | 3 | 3 | 96.6% |
| agent/tickets | ai_new/modules/agent/tickets/private/_pure.py | 3 | 3 | 99.0% |
| agent_common/archive | ai_new/modules/agent_common/archive/private/_cache.py | 5 | 1 | 92.5% |
| agent_common/llm | ai_new/modules/agent_common/llm/private/_client.py | 2 | 4 | 97.3% |
| agent_common/store | ai_new/modules/agent_common/store/__init__.py | 6 | 0 | 66.7% |
| agent/cloud | ai_new/modules/agent/cloud/private/_rsync.py | 3 | 2 | 96.6% |
| agent_common/api | ai_new/modules/agent_common/api/private/_wire.py | 3 | 2 | 88.6% |
| agent_common/archive | ai_new/modules/agent_common/archive/__init__.py | 4 | 0 | 78.9% |
| agent/health | ai_new/modules/agent/health/private/_pure.py | 2 | 1 | 81.2% |
| agent/todos | ai_new/modules/agent/todos/__init__.py | 1 | 2 | 91.7% |
| agent_common/codec | ai_new/modules/agent_common/codec/__init__.py | 3 | 0 | 85.7% |
| agent_common/config | ai_new/modules/agent_common/config/__init__.py | 3 | 0 | 70.0% |
| agent_common/hooks | ai_new/modules/agent_common/hooks/__init__.py | 3 | 0 | 75.0% |
| agent_common/net | ai_new/modules/agent_common/net/__init__.py | 3 | 0 | 78.6% |
| agent_common/runtime | ai_new/modules/agent_common/runtime/__init__.py | 3 | 0 | 78.6% |
| agent/asr | ai_new/modules/agent/asr/private/_engine.py | 0 | 2 | 97.7% |
| agent/cloud | ai_new/modules/agent/cloud/private/_archive.py | 2 | 0 | 77.8% |
| agent_common/host | ai_new/modules/agent_common/host/private/_profile.py | 1 | 1 | 94.9% |
| agent_common/store | ai_new/modules/agent_common/store/private/_archive_read.py | 1 | 1 | 90.5% |
| agent_common/store | ai_new/modules/agent_common/store/private/_docpath.py | 1 | 1 | 96.9% |
| agent/library | ai_new/modules/agent/library/__init__.py | 0 | 1 | 95.7% |
| agent/logs | ai_new/modules/agent/logs/__init__.py | 0 | 1 | 97.4% |
| agent/web | ai_new/modules/agent/web/private/_pure.py | 1 | 0 | 96.7% |

## 按模块聚合

| 模块 | 缺行 | 缺分支 |
|---|---:|---:|
| agent/projects | 56 | 34 |
| agent/sessions | 48 | 40 |
| agent/cloud | 48 | 38 |
| agent_common/archive | 37 | 23 |
| agent_common/llm | 38 | 21 |
| agent/sandbox | 32 | 19 |
| agent_common/http | 32 | 15 |
| agent_common/react | 17 | 22 |
| agent_common/store | 24 | 15 |
| agent_common/host | 31 | 7 |
| agent/auth | 24 | 13 |
| agent/channel | 19 | 13 |
| agent_common/api | 23 | 9 |
| agent_common/ops | 19 | 12 |
| agent_common/config | 19 | 11 |
| agent/todos | 13 | 13 |
| agent_common/codec | 22 | 2 |
| agent/knowledge | 16 | 6 |
| agent_common/plat | 16 | 4 |
| agent_common/graph | 8 | 10 |
| agent/web | 12 | 6 |
| agent/logs | 8 | 9 |
| agent_common/exec | 10 | 3 |
| agent/artifacts | 6 | 6 |
| agent/library | 0 | 10 |
| agent/tickets | 3 | 3 |
| agent/health | 2 | 1 |
| agent_common/hooks | 3 | 0 |
| agent_common/net | 3 | 0 |
| agent_common/runtime | 3 | 0 |
| agent/asr | 0 | 2 |
