---
source: ai_new/modules/agent_common/boot/private/_graph.py
hash: 6bf4b2c3c929a2b7610712e56fa1ff251358a55c59ce5203fd3c281eba68ade3
symbols:
- plan
- _hook_graph
- _read_demands
- _as_hooks
- _demand_routes
- _demand_emit_points
- _check_stmt
- _hook_call
- _load_module
- _exec_nodes
- _reachable
- _local_target
- _surface
- _assign_targets
- _api_call_route
- _toposort
- _find_cycle
generated: gen_docs.py v1
updated_at: '2026-11-23T04:10:21'
---

# _graph.py

> 由 `scripts/gen_docs.py` 生成；手改会被下次生成覆盖。
> 职责/入参出参/副作用/依赖/不变量/关联需求由人工在下方补充；生成器只提取 docstring 与符号。

## 概览

装配图扫描（组合根的私有实现）。

## 符号

### `plan`（function）
- 职责: 扫描并返回装配计划。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_hook_graph`（function）
- 职责: 静态需求图：模块声明了哪个点、谁触发、需求把它接到了哪些服务。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_read_demands`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_as_hooks`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_demand_routes`（function）
- 职责: 需求语句树里所有的服务调用（需求语言由 demand_engine 解释）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_demand_emit_points`（function）
- 职责: 需求里经 hooks.emit 触发的点（模块不自己 emit，触发由需求编排）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_check_stmt`（function）
- 职责: 需求语言的语法检查：语句只有 call（要返回值）与 send（单向通知）两种。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_hook_call`（function）
- 职责: 识别 `ctx.hooks.point("name")` / `ctx.hooks.emit("name", ...)`。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_load_module`（function）
- 职责: 聚合模块的公开文件与 private/ 下所有 .py 的函数定义，键是 (文件主名, 函数名)。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_exec_nodes`（function）
- 职责: setup 期会真正执行的节点（不进嵌套 def/class/λ 的体）。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_reachable`（function）
- 职责: 从 __init__.setup 出发，沿模块内部调用（_file.fn / _fn）做可达分析。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_local_target`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_surface`（function）
- 职责: setup 期摸到的 ctx 面：读了什么、写了什么、调了哪些路由、挂了哪些私有状态。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_assign_targets`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_api_call_route`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_toposort`（function）
- 职责: （无 docstring）
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充

### `_find_cycle`（function）
- 职责: 在成环的节点里找一条具体环路径，用于报错。
- 入参/出参: 待人工补充
- 副作用/依赖/不变量: 待人工补充
- 关联需求/测试: 待人工补充
