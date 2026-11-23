---
source: scripts/push_node_client.py
hash: 26dbfc5180e9c2be399cff913d9a50686eaace5b93c1a84b8c1ca62d54e4dbc0
symbols:
- __init__
- __init__
- _url
- _post
- register
- heartbeat
- ensure_registered
- mark_failure
- backoff_delay
- run
generated: gen_docs.py v1
updated_at: '2026-11-23T15:32:03'
---

# push_node_client.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

节点主动连云控面（push）出站客户端。

## 符号

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `__init__`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_url`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_post`（method）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `register`（method）
- 职责: 上报节点身份、归属与容量；重复注册由控制面幂等去重。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `heartbeat`（method）
- 职责: 周期心跳：刷新负载与最后见活时间；失败计入退避计数。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `ensure_registered`（method）
- 职责: 断线恢复后先补注册；已注册过不重复打注册路由。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `mark_failure`（method）
- 职责: 记一次失败，失败次数参与指数退避计算。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `backoff_delay`（method）
- 职责: 本次失败后的退避秒数：2^(n-1) 倍 base，封顶 max；无失败返回 0。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `run`（method）
- 职责: 心跳主循环。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
