---
source: ai_new/modules/agent_test/private/load_test.py
hash: dd089d7f6a8fb479a0df68c201744a368e2ac57c62b946a91e4a94cc7f2372b7
symbols:
- start_stub
- clean_business
- assemble
- run_demand
- make_project
- make_ticket
- _ids_from_glob
- _current_rss_mb
- mem_snapshot
- _alive_futures
- join_background
- main
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:22'
---

# load_test.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

并发压测：N 个项目 × M 个工单并发跑，LLM 全程走本地打桩网络服务，不接真实上游。

## 符号

### `start_stub`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `clean_business`（function）
- 职责: 清空业务档案：项目/工单/会话/知识/产物；保留 library 种子与配置。返回删除条目数。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `assemble`（function）
- 职责: 装配 ctx：llm 指桩，审计单检查关闭。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `run_demand`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `make_project`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `make_ticket`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_ids_from_glob`（function）
- 职责: 从 glob 相对路径解析记录 id：工单 tickets/T-x/ticket.yaml → T-x；会话 sessions/pm-1.yaml → pm-1。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_current_rss_mb`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mem_snapshot`（function）
- 职责: 采样内存与运行期回收面：当前/峰值 RSS、存活线程、死线程字典、草稿槽、订阅者。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_alive_futures`（function）
- 职责: 当前尚未收尾的后台会话任务 Future（异步运行时双池口径）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `join_background`（function）
- 职责: 等后台会话任务收敛；回催会再 dispatch 同 key，轮询到无在途 Future。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `main`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
