# 覆盖率缺口清单

基线：行 97.91%（14492/14761），分支 97.16%（5031/5178），共 43 个产品文件有缺口。
> 快照：2026-11-26 08:51 全量运行（77 模块 0 失败）。此后已把 `agent/knowledge/__init__.py`、`agent_common/config` 包装层、`store/private/_idem.py` 补到 100%，本表尚未反映，下一轮全量会刷新。

| 模块 | 文件 | 缺行 | 缺分支 | 行覆盖 |
|---|---|---:|---:|---:|
| agent_common/http | ai_new/modules/agent_common/http/private/_server.py | 32 | 15 | 88.6% |
| agent_common/react | ai_new/modules/agent_common/react/__init__.py | 19 | 15 | 83.9% |
| agent/knowledge | ai_new/modules/agent/knowledge/__init__.py | 16 | 6 | 76.1% |
| agent_common/host | ai_new/modules/agent_common/host/private/_probe.py | 19 | 3 | 73.2% |
| agent/channel | ai_new/modules/agent/channel/__init__.py | 11 | 9 | 81.7% |
| agent_common/api | ai_new/modules/agent_common/api/__init__.py | 16 | 3 | 69.4% |
| agent/web | ai_new/modules/agent/web/private/_panel.py | 11 | 6 | 72.6% |
| agent/sandbox | ai_new/modules/agent/sandbox/__init__.py | 13 | 1 | 58.8% |
| agent_common/host | ai_new/modules/agent_common/host/__init__.py | 11 | 3 | 65.9% |
| agent_common/exec | ai_new/modules/agent_common/exec/private/_runner.py | 10 | 3 | 95.3% |
| agent_common/react | ai_new/modules/agent_common/react/private/_pure.py | 3 | 10 | 94.2% |
| agent/artifacts | ai_new/modules/agent/artifacts/__init__.py | 6 | 6 | 88.8% |
| agent_common/store | ai_new/modules/agent_common/store/private/_files.py | 5 | 7 | 90.6% |
| agent_common/archive | ai_new/modules/agent_common/archive/private/_index.py | 5 | 6 | 89.7% |
| agent_common/plat | ai_new/modules/agent_common/plat/private/_net.py | 8 | 3 | 88.8% |
| agent/cloud | ai_new/modules/agent/cloud/private/_pure.py | 6 | 4 | 93.8% |
| agent_common/archive | ai_new/modules/agent_common/archive/private/_lock.py | 7 | 3 | 83.1% |
| agent/library | ai_new/modules/agent/library/private/_pure.py | 0 | 9 | 99.1% |
| agent_common/archive | ai_new/modules/agent_common/archive/private/_cache.py | 7 | 2 | 88.8% |
| agent_common/archive | ai_new/modules/agent_common/archive/private/_metrics.py | 4 | 5 | 81.2% |
| agent_common/plat | ai_new/modules/agent_common/plat/private/_proc.py | 8 | 1 | 67.9% |
| agent/cloud | ai_new/modules/agent/cloud/private/_seal.py | 5 | 3 | 94.8% |
| agent_common/api | ai_new/modules/agent_common/api/private/_gen.py | 4 | 4 | 92.8% |
| agent/cloud | ai_new/modules/agent/cloud/private/_guard.py | 3 | 3 | 96.6% |
| agent/tickets | ai_new/modules/agent/tickets/private/_pure.py | 3 | 3 | 99.0% |
| agent_common/store | ai_new/modules/agent_common/store/__init__.py | 6 | 0 | 66.7% |
| agent/cloud | ai_new/modules/agent/cloud/private/_rsync.py | 3 | 2 | 96.6% |
| agent_common/api | ai_new/modules/agent_common/api/private/_wire.py | 3 | 2 | 88.6% |
| agent_common/archive | ai_new/modules/agent_common/archive/__init__.py | 4 | 0 | 78.9% |
| agent/health | ai_new/modules/agent/health/private/_pure.py | 2 | 1 | 81.2% |
| agent/todos | ai_new/modules/agent/todos/__init__.py | 1 | 2 | 91.7% |
| agent_common/codec | ai_new/modules/agent_common/codec/__init__.py | 3 | 0 | 85.7% |
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
| agent_common/http | 32 | 15 |
| agent_common/react | 22 | 25 |
| agent_common/archive | 27 | 16 |
| agent_common/host | 31 | 7 |
| agent_common/api | 23 | 9 |
| agent/cloud | 19 | 12 |
| agent/knowledge | 16 | 6 |
| agent_common/store | 13 | 9 |
| agent/channel | 11 | 9 |
| agent_common/plat | 16 | 4 |
| agent/web | 12 | 6 |
| agent/sandbox | 13 | 1 |
| agent_common/exec | 10 | 3 |
| agent/artifacts | 6 | 6 |
| agent/library | 0 | 10 |
| agent/tickets | 3 | 3 |
| agent/health | 2 | 1 |
| agent/todos | 1 | 2 |
| agent_common/codec | 3 | 0 |
| agent_common/hooks | 3 | 0 |
| agent_common/net | 3 | 0 |
| agent_common/runtime | 3 | 0 |
| agent/asr | 0 | 2 |
| agent/logs | 0 | 1 |
